#!/usr/bin/env python3
"""
Phase Noise Measurement — IC-7300 carrier + SunSDR2 Pro IQ capture.

The IC-7300 transmits a stable CW carrier at a known frequency.  The SunSDR
captures IQ at 192 kHz rate.  The phase noise profile L(f) is computed from
the FFT of the captured IQ by comparing PSD near the carrier to the carrier
power, sweeping offset frequencies from 10 Hz to 96 kHz.

At 192 kHz IQ rate, a single capture at the carrier frequency shows the full
close-in phase noise profile (±96 kHz offsets) in one shot.

L(f) in dBc/Hz = PSD(f) - carrier_power - 10*log10(rbw_hz) - 3dB (USB correction)

Usage:
    python phase_noise.py --radio-host localhost --sdr-host 192.168.1.100 --carrier-freq 14000000
    python phase_noise.py --sdr-host 192.168.1.100 --carrier-freq 7100000 --duration 10
    python phase_noise.py --sdr-host 192.168.1.100 --carrier-freq 14000000 --out phase_noise.json
"""

import argparse
import json
import sys
import time

import numpy as np

from rf_bench.icom import IC7300
from rf_bench.sunsdr import SunSDR, SunSDRError
from rf_bench import connect


# ── Phase noise analysis ──────────────────────────────────────────────────────

def _compute_phase_noise(iq: np.ndarray, rate: int,
                         rbw_hz: float = 100.0
                         ) -> tuple[np.ndarray, np.ndarray]:
    """
    Compute phase noise L(f) in dBc/Hz from a carrier IQ capture.

    Method:
    1. Compute Welch-averaged PSD with Hann windowing
    2. Find the carrier bin (should be near DC in baseband)
    3. L(f) = PSD(f) - carrier_power - 10*log10(rbw)

    Returns:
        (offset_hz, phase_noise_dbc_hz) — numpy arrays
        offset_hz: positive offsets only (0.1 Hz to rate/2)
        phase_noise_dbc_hz: L(f) in dBc/Hz at each offset
    """
    n       = len(iq)
    nperseg = max(128, 1 << int(np.log2(max(int(rate / rbw_hz), 128))))
    nperseg = min(nperseg, n)
    step    = max(1, nperseg // 4)   # 75% overlap for smoother estimate
    window  = np.hanning(nperseg).astype(np.float32)
    wpow    = float(np.sum(window ** 2))

    segs = []
    pos  = 0
    while pos + nperseg <= n:
        seg = iq[pos: pos + nperseg] * window
        segs.append(np.abs(np.fft.fft(seg, n=nperseg)) ** 2)
        pos += step

    if not segs:
        segs = [np.abs(np.fft.fft(iq * window[:n], n=n)) ** 2]
        wpow = float(np.sum(window[:n] ** 2))
        nperseg = n

    psd    = np.mean(segs, axis=0) / wpow
    freq_r = np.fft.fftfreq(nperseg, d=1.0 / rate)

    # Find carrier — it's the largest peak
    carrier_bin = int(np.argmax(psd))
    carrier_psd = float(psd[carrier_bin])

    # Phase noise = PSD relative to carrier power, normalised to 1 Hz bandwidth
    # L(f) = 10*log10(PSD(f) / carrier_power / rbw_effective)
    # where rbw_effective = rate / nperseg (bin spacing)
    bin_bw = float(rate) / nperseg
    psd_norm = psd / (carrier_psd * bin_bw + 1e-60)
    L_f_db   = 10.0 * np.log10(psd_norm + 1e-60)

    # Return only positive offsets (symmetric, take positive half)
    n_half    = nperseg // 2
    freq_pos  = np.abs(freq_r[:n_half])
    L_f_pos   = L_f_db[:n_half]

    # Sort by offset
    sort_idx  = np.argsort(freq_pos)
    freq_pos  = freq_pos[sort_idx]
    L_f_pos   = L_f_pos[sort_idx]

    # Exclude the carrier bin itself (< 2 Hz offset)
    mask      = freq_pos > 2.0
    return freq_pos[mask].astype(np.float32), L_f_pos[mask].astype(np.float32)


def _summarize_at_offsets(offset_hz: np.ndarray, L_f: np.ndarray,
                           targets: list[float]) -> dict[float, float]:
    """Return L(f) at specific offset frequencies by nearest-bin interpolation."""
    result = {}
    for target in targets:
        idx    = int(np.argmin(np.abs(offset_hz - target)))
        result[target] = round(float(L_f[idx]), 1)
    return result


# ── Display ───────────────────────────────────────────────────────────────────

def _print_results(carrier_hz: int, duration_s: float,
                   at_offsets: dict, n_averages: int,
                   offset_hz: np.ndarray, L_f: np.ndarray) -> None:
    print(f"\n  === Phase Noise Results ===")
    print(f"  Carrier:    {carrier_hz/1e6:.6f} MHz")
    print(f"  Duration:   {duration_s:.1f} s  ({n_averages} segments averaged)")
    print()
    print(f"  L(f) at standard offsets:")
    print(f"  {'Offset':>12}  {'L(f) dBc/Hz':>14}")
    print(f"  {'─'*28}")

    offsets_khz = [
        (10,       "10 Hz"),
        (100,      "100 Hz"),
        (1_000,    "1 kHz"),
        (10_000,   "10 kHz"),
        (100_000,  "100 kHz"),
    ]
    for hz, label in offsets_khz:
        if hz in at_offsets:
            print(f"  {label:>12}  {at_offsets[hz]:>+12.1f} dBc/Hz")
        else:
            # Find nearest
            idx = int(np.argmin(np.abs(offset_hz - hz)))
            print(f"  {label:>12}  {float(L_f[idx]):>+12.1f} dBc/Hz")

    print()
    # Print profile in decade steps
    print(f"  Phase noise profile (selected offsets):")
    print(f"  {'Offset Hz':>12}  {'L(f)':>12}")
    print(f"  {'─'*26}")
    decade_points = np.logspace(1, np.log10(max(offset_hz)), 30)
    for d in decade_points:
        idx = int(np.argmin(np.abs(offset_hz - d)))
        if abs(offset_hz[idx] - d) / d < 0.5:   # within 50% of target
            print(f"  {offset_hz[idx]:>12.1f}  {float(L_f[idx]):>+10.1f}")


# ── Main ──────────────────────────────────────────────────────────────────────

def run(args: argparse.Namespace) -> None:
    carrier_hz = args.carrier_freq
    iq_rate    = 192_000
    duration_s = args.duration

    print(f"\n  Phase Noise Measurement")
    print(f"  Carrier: {carrier_hz/1e6:.6f} MHz")
    print(f"  Duration: {duration_s:.1f}s  |  IQ rate: {iq_rate/1e3:.0f} kHz")
    print()

    # Optionally connect to IC-7300 for PTT control
    rig = None
    if args.radio_host:
        print(f"  Connecting to IC-7300 via rigctld at {args.radio_host}:{args.radio_port}...")
        try:
            rig = IC7300(host=args.radio_host, port=args.radio_port)
            rig.set_frequency(carrier_hz)
            rig.set_mode("cw")
            print(f"  IC-7300 ready.")
        except Exception as e:
            print(f"  WARNING: rigctld connection failed ({e})")
            print(f"  Continuing without radio control — engage TX manually.")

    print(f"  Connecting to SunSDR...")
    try:
        sdr = SunSDR(args.sdr_host, port=args.sdr_port, iq_rate=iq_rate)
    except SunSDRError as e:
        print(f"  ERROR: {e}")
        if rig:
            rig.close()
        sys.exit(1)

    print(f"  Connected: {sdr.identify()['device']}")
    sdr.set_frequency(carrier_hz)
    sdr.set_mode("USB")
    time.sleep(0.05)

    try:
        # Engage PTT
        if rig:
            print(f"  Engaging IC-7300 TX (CW carrier)...")
            rig._cmd("\\set_ptt 1")
            time.sleep(0.5)   # ALC settle
        else:
            print(f"  Waiting for carrier to be active...")
            print(f"  (Start transmission now, then press Enter)")
            try:
                input()
            except EOFError:
                pass

        # Capture IQ
        n_samples = int(iq_rate * duration_s)
        print(f"  Capturing {n_samples} IQ samples ({duration_s:.1f}s)...")
        iq = sdr.capture_iq(n_samples)
        print(f"  Capture complete.  Computing phase noise...")

        # Release PTT
        if rig:
            rig._cmd("\\set_ptt 0")

        # Compute phase noise
        offset_hz, L_f = _compute_phase_noise(iq, iq_rate, rbw_hz=10.0)

        at_offsets = _summarize_at_offsets(
            offset_hz, L_f,
            [10, 100, 1_000, 10_000, 100_000]
        )

        # Estimate number of averages used
        nperseg_approx = max(128, 1 << int(np.log2(max(int(iq_rate / 10.0), 128))))
        n_avg = max(1, n_samples // (nperseg_approx // 4))

        _print_results(carrier_hz, duration_s, at_offsets, n_avg, offset_hz, L_f)

        # Save to JSON
        if args.out:
            data = {
                "carrier_hz": carrier_hz,
                "iq_rate":    iq_rate,
                "duration_s": duration_s,
                "at_offsets": {str(k): v for k, v in at_offsets.items()},
                "offset_hz":  offset_hz.tolist(),
                "L_f_dbc_hz": L_f.tolist(),
            }
            with open(args.out, "w") as f:
                json.dump(data, f, indent=2)
            print(f"\n  Saved to: {args.out}")

    except SunSDRError as e:
        print(f"  ERROR during capture: {e}")
        if rig:
            try:
                rig._cmd("\\set_ptt 0")
            except Exception:
                pass
    finally:
        if rig:
            try:
                rig._cmd("\\set_ptt 0")
            except Exception:
                pass
            rig.close()
        sdr.close()


# ── CLI ───────────────────────────────────────────────────────────────────────

def main() -> None:
    p = argparse.ArgumentParser(
        description="Phase Noise Measurement — IC-7300 carrier + SunSDR2 Pro",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Measures L(f) phase noise from 10 Hz to 96 kHz offset using the IC-7300 as the
carrier source and the SunSDR2 Pro as the IQ capture receiver.

The IC-7300 transmits a CW carrier; the SunSDR captures the full ±96 kHz around
it in one shot, enabling single-capture phase noise measurement.

Compare to: projects/radio/phase-noise/ (SSA-based, wider dynamic range at large offsets)

Examples:
  python phase_noise.py --sdr-host 192.168.1.100 --carrier-freq 14000000
  python phase_noise.py --sdr-host 192.168.1.100 --carrier-freq 7100000 --duration 30
  python phase_noise.py --sdr-host 192.168.1.100 --carrier-freq 14000000 --out pn.json
        """,
    )
    p.add_argument("--radio-host",     default=None, dest="radio_host",
                   help="rigctld host for IC-7300 PTT control (optional)")
    p.add_argument("--radio-port",     type=int, default=4532, dest="radio_port")
    p.add_argument("--sdr-host",       required=True, dest="sdr_host",
                   help="SunSDR host IP")
    p.add_argument("--sdr-port",       type=int, default=50001, dest="sdr_port")
    p.add_argument("--carrier-freq",   type=int, required=True, dest="carrier_freq",
                   help="Carrier frequency in Hz")
    p.add_argument("--duration",       type=float, default=10.0,
                   help="IQ capture duration in seconds (default: 10; longer = more averages)")
    p.add_argument("--out",            default=None,
                   help="Save results to JSON file (optional)")

    args = p.parse_args()
    run(args)


if __name__ == "__main__":
    main()
