#!/usr/bin/env python3
"""
VHF Transmitter Measurement — IC-9700 + SunSDR TRX 1 + SSA3032X.

IC-9700 transmits a CW carrier at 144 MHz.
SunSDR TRX 1 captures ±96 kHz IQ around the carrier simultaneously — for IMD analysis.
SSA3032X measures harmonic content and spectral purity across a wider span.

Measurements:
  1. SSA wide span: sweep 100–500 MHz, find carrier and harmonics (288, 432, 576 MHz)
  2. SunSDR IQ: capture ±96 kHz at carrier frequency, measure carrier level,
     noise floor, close-in spurs, and IMD products (if two-tone audio injected)
  3. Combined report: carrier power from SSA (dBm), close-in analysis from SunSDR

Usage:
    python vhf_tx_test.py --radio-host localhost --sdr-host 192.168.1.100 \
        --ssa-host 10.1.1.60 --carrier-freq 144050000
    python vhf_tx_test.py --radio-host localhost --sdr-host 192.168.1.100 \
        --ssa-host 10.1.1.60 --carrier-freq 144200000 --mode two-tone
"""

import argparse
import sys
import time

import numpy as np

from rf_bench.icom import IC9700
from rf_bench.siglent import SSA3000X
from rf_bench.sunsdr import SunSDR, SunSDRError
from rf_bench import connect


# ── Constants ─────────────────────────────────────────────────────────────────

VHF_LO = 100_000_000
VHF_HI = 150_000_000

# IQ rate for SunSDR TRX 1
SUNSDR_VHF_RATE = 192_000

# SSA sweep parameters
SSA_SPAN_HZ   = 400_000_000   # 100–500 MHz span for harmonic search
SSA_CENTER_HZ = 300_000_000   # Center of SSA wide span
SSA_RBW_HZ    = 100_000       # 100 kHz RBW for harmonic search


# ── SSA harmonic analysis ─────────────────────────────────────────────────────

def _ssa_harmonic_scan(ssa: SSA3000X, carrier_hz: int,
                       ) -> dict:
    """
    Use SSA to measure carrier and harmonics.

    Sets up a span from slightly below the carrier to 3× the carrier frequency.
    Captures the trace and reports power at the carrier, 2nd, and 3rd harmonics.
    """
    h2 = carrier_hz * 2
    h3 = carrier_hz * 3
    start = max(100_000, carrier_hz - 50_000_000)
    stop  = h3 + 50_000_000

    ssa.setup_band(
        start_hz = start,
        stop_hz  = stop,
    )
    ssa.single_sweep()
    trace = ssa.get_trace()   # numpy array of dBm values

    # Frequency axis
    freq_hz = np.linspace(start, stop, len(trace))

    def _peak_near(f: int, window_hz: float = 2_000_000.0) -> float:
        mask = np.abs(freq_hz - f) <= window_hz / 2
        if not np.any(mask):
            return float("nan")
        return float(np.max(trace[mask]))

    carrier_dbm = _peak_near(carrier_hz)
    h2_dbm      = _peak_near(h2)
    h3_dbm      = _peak_near(h3)

    h2_dbc = h2_dbm - carrier_dbm if not np.isnan(carrier_dbm) else float("nan")
    h3_dbc = h3_dbm - carrier_dbm if not np.isnan(carrier_dbm) else float("nan")

    return {
        "carrier_hz":   carrier_hz,
        "carrier_dbm":  round(carrier_dbm, 2),
        "h2_hz":        h2,
        "h2_dbm":       round(h2_dbm, 2),
        "h2_dbc":       round(h2_dbc, 2),
        "h3_hz":        h3,
        "h3_dbm":       round(h3_dbm, 2),
        "h3_dbc":       round(h3_dbc, 2),
    }


# ── SunSDR IQ analysis ────────────────────────────────────────────────────────

def _psd_unnormalised(iq: np.ndarray, rate: int,
                      rbw_hz: float = 200.0) -> tuple[np.ndarray, np.ndarray]:
    """Welch PSD, unnormalised dBFS."""
    n       = len(iq)
    nperseg = max(64, 1 << int(np.log2(max(int(rate / rbw_hz), 64))))
    nperseg = min(nperseg, n)
    step    = max(1, nperseg // 2)
    window  = np.hanning(nperseg).astype(np.float32)
    wpow    = float(np.sum(window ** 2))
    segs    = []
    pos     = 0
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


def _peak_in_window(freq_r: np.ndarray, psd_db: np.ndarray,
                    target_hz: float, window_hz: float) -> float:
    mask = np.abs(freq_r - target_hz) <= window_hz / 2
    if not np.any(mask):
        return float("nan")
    return float(np.max(psd_db[mask]))


def _sdr_carrier_analysis(sdr: SunSDR, carrier_hz: int,
                           n_samples: int = 192_000) -> dict:
    """Capture IQ and measure carrier and close-in spurs."""
    sdr.set_frequency(carrier_hz)
    time.sleep(0.05)
    iq = sdr.capture_iq(n_samples)

    freq_r, psd_db = _psd_unnormalised(iq, SUNSDR_VHF_RATE, rbw_hz=100.0)

    noise_dbfs    = float(np.median(psd_db[np.abs(freq_r) > 5000.0]))
    carrier_dbfs  = _peak_in_window(freq_r, psd_db, 0.0, window_hz=2000.0)
    snr_db        = carrier_dbfs - noise_dbfs

    # Find spurs (more than 5 kHz from carrier, more than 6 dB above noise)
    spur_freqs = []
    spur_levels = []
    above = (psd_db - noise_dbfs) > 6.0
    off   = np.abs(freq_r) > 5000.0
    mask  = above & off
    in_s, start = False, 0
    for i, flag in enumerate(mask):
        if flag and not in_s:
            start, in_s = i, True
        elif not flag and in_s:
            mid = (start + i) // 2
            p   = float(psd_db[mid])
            if (p - carrier_dbfs) >= -50.0:
                spur_freqs.append(round(float(freq_r[mid])))
                spur_levels.append(round(p, 2))
            in_s = False

    return {
        "carrier_dbfs": round(carrier_dbfs, 2),
        "noise_dbfs":   round(noise_dbfs, 2),
        "snr_db":       round(snr_db, 2),
        "spur_freqs":   spur_freqs,
        "spur_levels":  spur_levels,
    }


def _sdr_imd_analysis(sdr: SunSDR, carrier_hz: int,
                      tone1_hz: float = 700.0, tone2_hz: float = 1900.0,
                      n_samples: int = 192_000) -> dict:
    """Measure IMD products from two-tone signal."""
    sdr.set_frequency(carrier_hz)
    time.sleep(0.05)
    iq = sdr.capture_iq(n_samples)

    freq_r, psd_db = _psd_unnormalised(iq, SUNSDR_VHF_RATE, rbw_hz=100.0)

    noise = float(np.median(psd_db))
    t1, t2 = tone1_hz, tone2_hz

    tone1    = _peak_in_window(freq_r, psd_db, t1, window_hz=500.0)
    tone2    = _peak_in_window(freq_r, psd_db, t2, window_hz=500.0)
    tone_avg = (tone1 + tone2) / 2.0

    imd3_lo  = _peak_in_window(freq_r, psd_db, 2*t1 - t2, window_hz=500.0)
    imd3_hi  = _peak_in_window(freq_r, psd_db, 2*t2 - t1, window_hz=500.0)
    imd5_lo  = _peak_in_window(freq_r, psd_db, 3*t1 - 2*t2, window_hz=500.0)
    imd5_hi  = _peak_in_window(freq_r, psd_db, 3*t2 - 2*t1, window_hz=500.0)

    return {
        "tone1_dbfs":  round(tone1, 2),
        "tone2_dbfs":  round(tone2, 2),
        "noise_dbfs":  round(noise, 2),
        "imd3_lo":     round(imd3_lo, 2),
        "imd3_hi":     round(imd3_hi, 2),
        "imd3_dbc":    round(min(imd3_lo, imd3_hi) - tone_avg, 2),
        "imd5_lo":     round(imd5_lo, 2),
        "imd5_hi":     round(imd5_hi, 2),
        "imd5_dbc":    round(min(imd5_lo, imd5_hi) - tone_avg, 2),
    }


# ── Main ──────────────────────────────────────────────────────────────────────

def run(args: argparse.Namespace) -> None:
    carrier_hz = args.carrier_freq

    if not (VHF_LO <= carrier_hz <= VHF_HI):
        print(f"ERROR: --carrier-freq {carrier_hz} is outside TRX 1 range "
              f"({VHF_LO/1e6:.0f}–{VHF_HI/1e6:.0f} MHz)")
        sys.exit(1)

    print(f"\n  VHF Transmitter Measurement")
    print(f"  Radio:   {args.radio_host}:{args.radio_port}  (IC-9700)")
    print(f"  SunSDR:  {args.sdr_host}:{args.sdr_port}  (TRX 1)")
    print(f"  SSA:     {args.ssa_host}")
    print(f"  Carrier: {carrier_hz/1e6:.4f} MHz")
    print(f"  Mode:    {args.mode}")
    print()

    # Connect to IC-9700
    print(f"  Connecting to IC-9700...")
    try:
        rig = IC9700(host=args.radio_host, port=args.radio_port)
        print(f"  IC-9700 connected.")
    except Exception as e:
        print(f"  ERROR: {e}")
        sys.exit(1)

    # Connect to SunSDR TRX 1
    print(f"  Connecting to SunSDR TRX 1...")
    try:
        sdr = SunSDR(args.sdr_host, port=args.sdr_port,
                     trx=1, iq_rate=SUNSDR_VHF_RATE)
    except SunSDRError as e:
        print(f"  ERROR: {e}")
        rig.close()
        sys.exit(1)

    print(f"  SunSDR connected: {sdr.identify()['device']}")

    # Connect to SSA
    print(f"  Connecting to SSA3032X...")
    ssa = None
    try:
        ssa = connect(args.ssa_host or 'ssa')
        ssa.connect()
        print(f"  SSA connected: {ssa.identify()}")
    except Exception as e:
        print(f"  WARNING: SSA connection failed ({e})")
        print(f"  Continuing without SSA measurements.")

    try:
        # Configure IC-9700
        rig.set_frequency(carrier_hz)
        rig.set_mode("cw")
        time.sleep(0.2)
        sdr.set_frequency(carrier_hz)
        sdr.set_mode("USB")
        time.sleep(0.05)

        print(f"\n  Engaging IC-9700 TX...")
        print(f"  WARNING: Transmitting on {carrier_hz/1e6:.4f} MHz")
        print(f"  Ensure dummy load or directional coupler is connected.")
        rig.set_ptt(True)
        time.sleep(0.5)   # ALC settle

        # === SSA wide-span harmonic measurement ===
        ssa_result = None
        if ssa:
            print(f"\n  SSA: measuring harmonics...")
            try:
                ssa_result = _ssa_harmonic_scan(ssa, carrier_hz)
            except Exception as e:
                print(f"  SSA measurement failed: {e}")

        # === SunSDR IQ analysis ===
        print(f"  SunSDR TRX 1: capturing IQ...")
        if args.mode == "carrier":
            sdr_result = _sdr_carrier_analysis(sdr, carrier_hz)
        elif args.mode == "two-tone":
            print(f"  Inject two audio tones ({args.tone1:.0f} Hz + {args.tone2:.0f} Hz) "
                  f"into IC-9700, then press Enter...")
            try:
                input()
            except EOFError:
                pass
            sdr_result = _sdr_imd_analysis(sdr, carrier_hz,
                                           tone1_hz=args.tone1,
                                           tone2_hz=args.tone2)
        else:
            print(f"  Unknown mode: {args.mode}")
            sdr_result = {}

        rig.set_ptt(False)

        # === Print results ===
        print(f"\n  === VHF TX Measurement Results ===")
        print(f"  Carrier: {carrier_hz/1e6:.4f} MHz  Mode: {args.mode}")

        if ssa_result:
            print(f"\n  SSA3032X harmonic measurements:")
            print(f"  Carrier ({ssa_result['carrier_hz']/1e6:.4f} MHz):  "
                  f"{ssa_result['carrier_dbm']:+.1f} dBm")
            print(f"  2nd harmonic ({ssa_result['h2_hz']/1e6:.4f} MHz):  "
                  f"{ssa_result['h2_dbm']:+.1f} dBm  ({ssa_result['h2_dbc']:+.1f} dBc)")
            print(f"  3rd harmonic ({ssa_result['h3_hz']/1e6:.4f} MHz):  "
                  f"{ssa_result['h3_dbm']:+.1f} dBm  ({ssa_result['h3_dbc']:+.1f} dBc)")

        if args.mode == "carrier":
            print(f"\n  SunSDR TRX 1 close-in analysis (IQ, ±96 kHz):")
            print(f"  Carrier:      {sdr_result.get('carrier_dbfs', 'N/A'):+.1f} dBFS")
            print(f"  Noise floor:  {sdr_result.get('noise_dbfs', 'N/A'):+.1f} dBFS")
            print(f"  S/N:          {sdr_result.get('snr_db', 'N/A'):+.1f} dB")
            if sdr_result.get("spur_freqs"):
                print(f"  Spurs:")
                for f, p in zip(sdr_result["spur_freqs"], sdr_result["spur_levels"]):
                    dbc = p - sdr_result["carrier_dbfs"]
                    print(f"    {f/1e3:+.1f} kHz offset:  {p:+.1f} dBFS  ({dbc:+.1f} dBc)")
        elif args.mode == "two-tone":
            print(f"\n  SunSDR TRX 1 IMD analysis:")
            print(f"  Tone avg:  {((sdr_result.get('tone1_dbfs',0) + sdr_result.get('tone2_dbfs',0))/2):+.1f} dBFS")
            print(f"  IMD3:      {sdr_result.get('imd3_dbc', 'N/A'):+.1f} dBc")
            print(f"  IMD5:      {sdr_result.get('imd5_dbc', 'N/A'):+.1f} dBc")
            print(f"  Noise:     {sdr_result.get('noise_dbfs', 'N/A'):+.1f} dBFS")

    except Exception as e:
        print(f"\n  ERROR: {e}")
        raise
    finally:
        try:
            rig.set_ptt(False)
        except Exception:
            pass
        rig.close()
        sdr.close()
        if ssa:
            try:
                ssa.disconnect()
            except Exception:
                pass


# ── CLI ───────────────────────────────────────────────────────────────────────

def main() -> None:
    p = argparse.ArgumentParser(
        description="VHF TX Measurement — IC-9700 + SunSDR TRX 1 + SSA3032X",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Requires:
  - IC-9700 with rigctld running: rigctld -m 3081 -r /dev/ttyUSB0 -s 115200
  - SunSDR2 Pro with ExpertSDR3 TCI, TRX 1 enabled
  - SSA3032X spectrum analyzer on LAN
  - Directional coupler + attenuator between IC-9700 TX and SunSDR TRX 1 RX

Examples:
  python vhf_tx_test.py --sdr-host 192.168.1.100 --ssa-host 10.1.1.60 --carrier-freq 144050000
  python vhf_tx_test.py --sdr-host 192.168.1.100 --ssa-host 10.1.1.60 --mode two-tone
        """,
    )
    p.add_argument("--radio-host",    default="localhost", dest="radio_host",
                   help="rigctld host for IC-9700 (default: localhost)")
    p.add_argument("--radio-port",    type=int, default=4532, dest="radio_port")
    p.add_argument("--sdr-host",      required=True, dest="sdr_host",
                   help="SunSDR host IP")
    p.add_argument("--sdr-port",      type=int, default=50001, dest="sdr_port")
    p.add_argument("--ssa-host",      default="10.1.1.60", dest="ssa_host",
                   help="SSA3032X host IP (default: 10.1.1.60)")
    p.add_argument("--carrier-freq",  type=int, default=144_050_000, dest="carrier_freq",
                   help="TX carrier frequency in Hz (default: 144050000 = 144.050 MHz)")
    p.add_argument("--mode",          choices=["carrier", "two-tone"], default="carrier",
                   help="Measurement mode (default: carrier)")
    p.add_argument("--tone1",         type=float, default=700.0,
                   help="First audio tone Hz for two-tone (default: 700)")
    p.add_argument("--tone2",         type=float, default=1900.0,
                   help="Second audio tone Hz for two-tone (default: 1900)")

    args = p.parse_args()
    run(args)


if __name__ == "__main__":
    main()
