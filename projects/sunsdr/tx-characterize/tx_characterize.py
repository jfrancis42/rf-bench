#!/usr/bin/env python3
"""
TX Characterization — IC-7300 transmitter + SunSDR2 Pro wideband IQ receiver.

Uses the IC-7300 as the HF transmitter (controlled via rigctld) and the
SunSDR2 Pro as a wideband IQ capture receiver.  At 192 kHz rate the SunSDR
captures ±96 kHz around the carrier simultaneously — enough to see the carrier,
2nd/3rd-order IMD products, and harmonics within the passband in a single capture.

Measurements:
  carrier   — carrier power, noise floor, close-in spectral purity
  two-tone  — IMD3 and IMD5 products from a two-tone audio input

The IC-7300 must have rigctld running:
  rigctld -m 3073 -r /dev/ttyUSB0 -s 115200

Usage:
    python tx_characterize.py --radio-host localhost --sdr-host 192.168.1.100 --freq 14000000
    python tx_characterize.py --mode two-tone --radio-host localhost --sdr-host 192.168.1.100
    python tx_characterize.py --mode carrier  --freq 7100000 --duration 3
"""

import argparse
import signal
import sys
import time

import numpy as np

from rf_bench.icom import IC7300
from rf_bench.sunsdr import SunSDR, SunSDRError


# ── ANSI colours ─────────────────────────────────────────────────────────────

RESET  = "\033[0m"
BOLD   = "\033[1m"
DIM    = "\033[2m"
CYAN   = "\033[96m"
YELLOW = "\033[93m"
GREEN  = "\033[92m"
RED    = "\033[91m"


# ── IQ analysis ───────────────────────────────────────────────────────────────

def _hann_psd_db(iq: np.ndarray, rate: int,
                 rbw_hz: float = 200.0) -> tuple[np.ndarray, np.ndarray]:
    """
    Welch-averaged Hann-windowed PSD.  Returns (freq_relative_hz, psd_dbfs).

    Power is unnormalised dBFS for cross-bin amplitude comparisons.
    """
    n       = len(iq)
    nperseg = max(64, 1 << int(np.log2(max(int(rate / rbw_hz), 64))))
    nperseg = min(nperseg, n)
    step    = max(1, nperseg // 2)
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
    psd_db = (10.0 * np.log10(psd + 1e-30)).astype(np.float32)
    return (np.fft.fftshift(freq_r).astype(np.float32),
            np.fft.fftshift(psd_db))


def _bin_power(freq_r: np.ndarray, psd_db: np.ndarray,
               target_hz: float, window_hz: float = 2000.0) -> float:
    """Return peak dBFS within ±window_hz/2 of target_hz (relative to carrier)."""
    mask = np.abs(freq_r - target_hz) <= window_hz / 2
    if not np.any(mask):
        return float("nan")
    return float(np.max(psd_db[mask]))


def _noise_floor(psd_db: np.ndarray, exclude_bw_hz: float,
                 freq_r: np.ndarray) -> float:
    """Median of PSD bins outside ±exclude_bw_hz of carrier."""
    mask = np.abs(freq_r) > exclude_bw_hz
    if not np.any(mask):
        return float(np.median(psd_db))
    return float(np.median(psd_db[mask]))


# ── Carrier measurement ───────────────────────────────────────────────────────

def _measure_carrier(sdr: SunSDR, carrier_hz: int, rate: int,
                     n_captures: int = 3) -> dict:
    """
    Measure carrier power, close-in noise floor, and harmonics visible in passband.

    Returns dict with keys: carrier_dbfs, noise_dbfs, snr_db,
    harmonic_2_hz (or None), harmonic_2_dbfs, harmonic_2_dbc
    """
    sdr.set_frequency(carrier_hz)
    time.sleep(0.05)

    iq_blocks = [sdr.capture_iq(rate) for _ in range(n_captures)]
    iq = np.concatenate(iq_blocks)

    freq_r, psd_db = _hann_psd_db(iq, rate, rbw_hz=100.0)

    carrier_dbfs = _bin_power(freq_r, psd_db, 0.0, window_hz=2000.0)
    noise_dbfs   = _noise_floor(psd_db, exclude_bw_hz=5000.0, freq_r=freq_r)
    snr_db       = carrier_dbfs - noise_dbfs

    # Check for harmonics in the ±96 kHz passband
    # Only the fundamental is in-band; harmonics are far above
    # (carrier at 14 MHz, 2nd harmonic at 28 MHz — far outside ±96 kHz)
    # Report close-in spurs instead
    spur_hz, spur_dbfs = _find_spurs(freq_r, psd_db, carrier_dbfs, threshold_dbc=-40.0)

    return {
        "carrier_dbfs":  round(carrier_dbfs, 2),
        "noise_dbfs":    round(noise_dbfs, 2),
        "snr_db":        round(snr_db, 2),
        "spurs":         spur_hz,
        "spur_levels":   spur_dbfs,
    }


def _find_spurs(freq_r: np.ndarray, psd_db: np.ndarray,
                carrier_dbfs: float, threshold_dbc: float = -40.0
                ) -> tuple[list[float], list[float]]:
    """Find spectral spurs more than 3 kHz from carrier above threshold_dbc."""
    noise    = float(np.median(psd_db))
    above    = psd_db > (noise + 6.0)   # 6 dB above noise
    off_carr = np.abs(freq_r) > 3000.0  # exclude ±3 kHz of carrier
    mask     = above & off_carr

    # Group consecutive bins
    spur_hz:    list[float] = []
    spur_dbfs:  list[float] = []
    in_spur, start = False, 0
    for i, flag in enumerate(mask):
        if flag and not in_spur:
            start, in_spur = i, True
        elif not flag and in_spur:
            mid = (start + i) // 2
            p   = float(psd_db[mid])
            if (p - carrier_dbfs) >= threshold_dbc:
                spur_hz.append(round(float(freq_r[mid])))
                spur_dbfs.append(round(p, 2))
            in_spur = False

    return spur_hz, spur_dbfs


# ── Two-tone IMD measurement ──────────────────────────────────────────────────

def _measure_two_tone(sdr: SunSDR, carrier_hz: int, rate: int,
                      tone1_hz: float = 700.0, tone2_hz: float = 1900.0,
                      n_captures: int = 3) -> dict:
    """
    Measure IMD from two-tone signal.

    The IC-7300 must be in USB mode with two audio tones injected
    at tone1_hz and tone2_hz (e.g. from the SDG1062X or a PC audio interface).
    This script only performs the IQ capture and analysis.

    IMD3 products appear at: 2*f2 - f1 and 2*f1 - f2 (relative to carrier)
    IMD5 products appear at: 3*f2 - 2*f1 and 3*f1 - 2*f2
    """
    sdr.set_frequency(carrier_hz)
    time.sleep(0.05)

    iq_blocks = [sdr.capture_iq(rate) for _ in range(n_captures)]
    iq = np.concatenate(iq_blocks)

    freq_r, psd_db = _hann_psd_db(iq, rate, rbw_hz=100.0)

    t1, t2 = tone1_hz, tone2_hz
    tone1_dbfs = _bin_power(freq_r, psd_db, t1, window_hz=500.0)
    tone2_dbfs = _bin_power(freq_r, psd_db, t2, window_hz=500.0)
    tone_avg   = (tone1_dbfs + tone2_dbfs) / 2.0

    # 3rd-order IMD products
    imd3_lo_dbfs = _bin_power(freq_r, psd_db, 2*t1 - t2, window_hz=500.0)
    imd3_hi_dbfs = _bin_power(freq_r, psd_db, 2*t2 - t1, window_hz=500.0)

    # 5th-order IMD products
    imd5_lo_dbfs = _bin_power(freq_r, psd_db, 3*t1 - 2*t2, window_hz=500.0)
    imd5_hi_dbfs = _bin_power(freq_r, psd_db, 3*t2 - 2*t1, window_hz=500.0)

    noise_dbfs = _noise_floor(psd_db, exclude_bw_hz=10_000.0, freq_r=freq_r)

    imd3_dbc = min(imd3_lo_dbfs, imd3_hi_dbfs) - tone_avg
    imd5_dbc = min(imd5_lo_dbfs, imd5_hi_dbfs) - tone_avg

    return {
        "tone1_hz":      t1,
        "tone2_hz":      t2,
        "tone1_dbfs":    round(tone1_dbfs, 2),
        "tone2_dbfs":    round(tone2_dbfs, 2),
        "tone_avg_dbfs": round(tone_avg, 2),
        "noise_dbfs":    round(noise_dbfs, 2),
        "imd3_lo_dbfs":  round(imd3_lo_dbfs, 2),
        "imd3_hi_dbfs":  round(imd3_hi_dbfs, 2),
        "imd3_dbc":      round(imd3_dbc, 2),
        "imd5_lo_dbfs":  round(imd5_lo_dbfs, 2),
        "imd5_hi_dbfs":  round(imd5_hi_dbfs, 2),
        "imd5_dbc":      round(imd5_dbc, 2),
    }


# ── Main ──────────────────────────────────────────────────────────────────────

def run(args: argparse.Namespace) -> None:
    carrier_hz = args.freq
    iq_rate    = 192_000

    print(f"\n  TX Characterization")
    print(f"  Radio: {args.radio_host}:{args.radio_port}")
    print(f"  SDR:   {args.sdr_host}:{args.sdr_port}")
    print(f"  Mode:  {args.mode}")
    print(f"  Freq:  {carrier_hz/1e6:.6f} MHz")
    print()

    # Connect to IC-7300 via rigctld
    print(f"  Connecting to IC-7300 via rigctld...")
    try:
        rig = IC7300(host=args.radio_host, port=args.radio_port)
    except Exception as e:
        print(f"  ERROR: cannot connect to rigctld at {args.radio_host}:{args.radio_port}: {e}")
        print(f"  Start rigctld: rigctld -m 3073 -r /dev/ttyUSB0 -s 115200")
        sys.exit(1)

    # Connect to SunSDR
    print(f"  Connecting to SunSDR...")
    try:
        sdr = SunSDR(args.sdr_host, port=args.sdr_port, iq_rate=iq_rate)
    except SunSDRError as e:
        print(f"  ERROR: {e}")
        rig.close()
        sys.exit(1)

    print(f"  Connected: {sdr.identify()['device']}")
    print()

    stop = False
    def _sigint(*_):
        nonlocal stop
        stop = True
    signal.signal(signal.SIGINT, _sigint)

    try:
        # Configure IC-7300
        rig.set_frequency(carrier_hz)
        rig.set_mode("usb", passband_hz=2800)
        time.sleep(0.3)

        # Configure SunSDR receive
        sdr.set_frequency(carrier_hz)
        sdr.set_mode("USB")
        time.sleep(0.05)

        if args.mode == "carrier":
            print(f"  Engaging IC-7300 PTT (carrier/tune)...")
            print(f"  WARNING: Transmitting on {carrier_hz/1e6:.4f} MHz")
            print(f"  Ensure dummy load or antenna is connected.")
            print()

            rig._cmd("\\set_ptt 1")   # rigctld PTT on
            time.sleep(0.5)           # let ALC settle

            print(f"  Capturing IQ ({args.duration}s, {iq_rate/1e3:.0f} kHz rate)...")
            n_captures = max(1, int(args.duration))
            result     = _measure_carrier(sdr, carrier_hz, iq_rate, n_captures)

            rig._cmd("\\set_ptt 0")   # PTT off

            print(f"\n  === Carrier Measurement Results ===")
            print(f"  Frequency:    {carrier_hz/1e6:.6f} MHz")
            print(f"  Carrier:      {result['carrier_dbfs']:+.1f} dBFS")
            print(f"  Noise floor:  {result['noise_dbfs']:+.1f} dBFS")
            print(f"  S/N:          {result['snr_db']:+.1f} dB")
            if result["spurs"]:
                print(f"\n  Spurs detected:")
                for f, p in zip(result["spurs"], result["spur_levels"]):
                    dbc = p - result["carrier_dbfs"]
                    print(f"    {f/1e3:+.1f} kHz offset:  {p:+.1f} dBFS  ({dbc:+.1f} dBc)")
            else:
                print(f"  No significant spurs detected above threshold.")

        elif args.mode == "two-tone":
            print(f"  Two-tone test mode.")
            print(f"  IMPORTANT: Inject two audio tones at {args.tone1:.0f} Hz and "
                  f"{args.tone2:.0f} Hz into the IC-7300 mic/audio input.")
            print(f"  Then engage PTT on the IC-7300 manually or via external control.")
            print(f"  Press Enter when IC-7300 is transmitting two-tone signal...")
            try:
                input()
            except EOFError:
                pass

            print(f"  Capturing IQ...")
            n_captures = max(1, int(args.duration))
            result     = _measure_two_tone(sdr, carrier_hz, iq_rate,
                                           tone1_hz=args.tone1,
                                           tone2_hz=args.tone2,
                                           n_captures=n_captures)

            print(f"\n  === Two-Tone IMD Results ===")
            print(f"  Frequency:    {carrier_hz/1e6:.6f} MHz")
            print(f"  Tone 1:       {result['tone1_hz']:.0f} Hz  →  "
                  f"{result['tone1_dbfs']:+.1f} dBFS")
            print(f"  Tone 2:       {result['tone2_hz']:.0f} Hz  →  "
                  f"{result['tone2_dbfs']:+.1f} dBFS")
            print(f"  Noise floor:  {result['noise_dbfs']:+.1f} dBFS")
            print(f"\n  IMD Products:")
            print(f"  IMD3 low:     {result['imd3_lo_dbfs']:+.1f} dBFS")
            print(f"  IMD3 high:    {result['imd3_hi_dbfs']:+.1f} dBFS")
            print(f"  IMD3 (dBc):   {result['imd3_dbc']:+.1f} dBc")
            print(f"  IMD5 low:     {result['imd5_lo_dbfs']:+.1f} dBFS")
            print(f"  IMD5 high:    {result['imd5_hi_dbfs']:+.1f} dBFS")
            print(f"  IMD5 (dBc):   {result['imd5_dbc']:+.1f} dBc")

    except Exception as e:
        print(f"\n  ERROR: {e}")
        raise
    finally:
        try:
            rig._cmd("\\set_ptt 0")   # ensure PTT off
        except Exception:
            pass
        rig.close()
        sdr.close()


# ── CLI ───────────────────────────────────────────────────────────────────────

def main() -> None:
    p = argparse.ArgumentParser(
        description="TX Characterization — IC-7300 + SunSDR2 Pro",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Requires:
  - rigctld running for the IC-7300:
    rigctld -m 3073 -r /dev/ttyUSB0 -s 115200
  - SunSDR2 Pro with ExpertSDR3 TCI enabled
  - Appropriate RF path between IC-7300 TX and SunSDR RX
    (directional coupler, or separate antennas with isolation)

Examples:
  python tx_characterize.py --sdr-host 192.168.1.100 --freq 14000000
  python tx_characterize.py --sdr-host 192.168.1.100 --mode two-tone --freq 7100000
  python tx_characterize.py --sdr-host 192.168.1.100 --mode carrier --freq 14074000 --duration 5
        """,
    )
    p.add_argument("--radio-host", default="localhost", dest="radio_host",
                   help="rigctld host (default: localhost)")
    p.add_argument("--radio-port", type=int, default=4532, dest="radio_port",
                   help="rigctld port (default: 4532)")
    p.add_argument("--sdr-host",   default="sunsdr.local", dest="sdr_host",
                   help="SunSDR host IP")
    p.add_argument("--sdr-port",   type=int, default=50001, dest="sdr_port")
    p.add_argument("--freq",       type=int, default=14_000_000,
                   help="Test frequency in Hz (default: 14000000 = 14 MHz)")
    p.add_argument("--mode",       choices=["carrier", "two-tone"], default="carrier",
                   help="Measurement mode (default: carrier)")
    p.add_argument("--duration",   type=float, default=3.0,
                   help="IQ capture duration in seconds (default: 3)")
    p.add_argument("--tone1",      type=float, default=700.0,
                   help="First audio tone frequency Hz for two-tone test (default: 700)")
    p.add_argument("--tone2",      type=float, default=1900.0,
                   help="Second audio tone frequency Hz for two-tone test (default: 1900)")

    args = p.parse_args()
    run(args)


if __name__ == "__main__":
    main()
