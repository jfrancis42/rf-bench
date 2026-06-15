#!/usr/bin/env python3
"""
S-Meter Calibration — SunSDR dBFS to dBm mapping via IC-7300 S-meter reference.

Injects a known signal from the SDG1062X function generator through a calibrated
attenuator.  Both the IC-7300 S-meter and the SunSDR IQ capture measure the same
signal simultaneously.  The IC-7300's calibrated S-meter provides the dBm reference;
the SunSDR measures dBFS.  The result is a dBFS → dBm correction table.

This extends the calibration approach from projects/radio/rx-crosscheck/ to the
SunSDR HF path.

Hardware required:
  - SDG1062X function generator (or any calibrated RF source)
  - Calibrated attenuator (optional — attenuate to safe input levels)
  - RF splitter to feed both IC-7300 and SunSDR from the same source
  - IC-7300 with rigctld running
  - SunSDR2 Pro with ExpertSDR3 TCI enabled

Usage:
    python cal_smeter.py --sdr-host 192.168.1.100 --sdg-host 10.1.1.50 \
        --radio-host localhost --freq 14000000 --out cal-sunsdr.json
    python cal_smeter.py --sdr-host 192.168.1.100 --sdg-host 10.1.1.50 \
        --radio-host localhost --freq 7100000 --power-steps -10,-20,-30,-40,-50,-60,-70
"""

import argparse
import json
import sys
import time

import numpy as np

from rf_bench.icom import IC7300
from rf_bench.siglent import SDG1000X
from rf_bench.sunsdr import SunSDR, SunSDRError
from rf_bench import connect


# ── Default calibration sweep ─────────────────────────────────────────────────

DEFAULT_POWER_STEPS_DBM = [-20, -30, -40, -50, -60, -70, -80, -90]
SDG_DEFAULT_FREQ_HZ     = 1_000.0   # Audio tone injected into IC-7300


# ── IQ power measurement ──────────────────────────────────────────────────────

def _measure_sdr_dbfs(sdr: SunSDR, n_samples: int = 48_000) -> float:
    """
    Measure RMS power of current SunSDR IQ capture in dBFS.

    Returns the RMS power: 10*log10(mean(|iq|^2)).
    """
    iq = sdr.capture_iq(n_samples)
    return float(10.0 * np.log10(np.mean(np.abs(iq) ** 2) + 1e-60))


def _measure_sdr_peak_dbfs(sdr: SunSDR, n_samples: int = 48_000,
                            rbw_hz: float = 500.0) -> float:
    """
    Measure peak FFT bin power in dBFS.

    More suitable for narrowband signal measurement than RMS.
    """
    iq    = sdr.capture_iq(n_samples)
    rate  = sdr.sample_rate
    n     = len(iq)
    window = np.hanning(n).astype(np.float32)
    psd   = np.abs(np.fft.fft(iq * window)) ** 2 / np.sum(window ** 2)
    return float(10.0 * np.log10(np.max(psd) + 1e-60))


# ── S-meter reading ───────────────────────────────────────────────────────────

def _measure_rig_strength_dbm(rig: IC7300, n: int = 5, settle_s: float = 0.3
                               ) -> float:
    """
    Take N IC-7300 S-meter readings and return the average in dBm equivalent.

    Hamlib returns STRENGTH as dB relative to S9 (typically).
    IC-7300 S-meter calibration: S9 ≈ -73 dBm on HF.
    1 S-unit = 6 dB.

    dBm = hamlib_strength - 73   (approximate, varies by band and Hamlib version)
    """
    time.sleep(settle_s)
    readings = []
    for _ in range(n):
        try:
            s = rig.get_strength()
            if not np.isnan(s):
                readings.append(s)
        except Exception:
            pass
        time.sleep(0.1)

    if not readings:
        return float("nan")
    avg = float(np.mean(readings))
    # Hamlib 4.x IC-7300: STRENGTH is dB relative to S9.
    # S9 on HF = -73 dBm (ITU standard).
    return avg - 73.0


# ── Calibration sweep ─────────────────────────────────────────────────────────

def run_calibration(sdg: SDG1000X | None, rig: IC7300, sdr: SunSDR,
                    freq_hz: int, power_steps_dbm: list[float],
                    n_samples: int = 48_000) -> list[dict]:
    """
    Sweep through power levels, recording both SunSDR dBFS and IC-7300 dBm.

    If sdg is None, prompts the operator to set each power level manually.

    Returns list of {'target_dbm', 'rig_dbm', 'sdr_rms_dbfs', 'sdr_peak_dbfs'}
    """
    results = []
    rig.set_frequency(freq_hz)
    rig.set_mode("usb")
    sdr.set_frequency(freq_hz)
    sdr.set_mode("USB")
    time.sleep(0.1)

    for pwr_dbm in power_steps_dbm:
        if sdg:
            # Configure SDG: sine wave at 1 kHz audio tone, set output level
            sdg.set_sine(1, freq_hz=SDG_DEFAULT_FREQ_HZ, level_dbm=pwr_dbm)
            sdg.output_on(1)
            time.sleep(0.3)
        else:
            print(f"  Set source to {pwr_dbm:.0f} dBm and press Enter...")
            try:
                input()
            except EOFError:
                pass

        # Take measurements
        rig_dbm      = _measure_rig_strength_dbm(rig)
        sdr_rms_dbfs = _measure_sdr_dbfs(sdr, n_samples)
        sdr_pk_dbfs  = _measure_sdr_peak_dbfs(sdr, n_samples)

        result = {
            "target_dbm":    round(pwr_dbm, 1),
            "rig_dbm":       round(rig_dbm, 2),
            "sdr_rms_dbfs":  round(sdr_rms_dbfs, 2),
            "sdr_peak_dbfs": round(sdr_pk_dbfs, 2),
            "freq_hz":       freq_hz,
        }
        results.append(result)
        print(f"  {pwr_dbm:+5.0f} dBm target  →  "
              f"IC-7300: {rig_dbm:+6.1f} dBm  "
              f"SunSDR RMS: {sdr_rms_dbfs:+6.1f} dBFS  "
              f"Peak: {sdr_pk_dbfs:+6.1f} dBFS")

    if sdg:
        sdg.output_off(1)

    return results


# ── Fit and table ─────────────────────────────────────────────────────────────

def _fit_correction(results: list[dict]) -> dict:
    """
    Linear least-squares fit: dBm = m * dBFS + b.

    Returns {'slope': m, 'intercept': b, 'r2': r-squared, 'n': n_points,
             'rms_error_db': rms_fit_error}
    """
    dbfs = np.array([r["sdr_rms_dbfs"] for r in results if not np.isnan(r["rig_dbm"])])
    dbm  = np.array([r["rig_dbm"]      for r in results if not np.isnan(r["rig_dbm"])])

    if len(dbfs) < 2:
        return {"error": "insufficient valid points for fit"}

    A        = np.vstack([dbfs, np.ones(len(dbfs))]).T
    result   = np.linalg.lstsq(A, dbm, rcond=None)
    m, b     = result[0]
    predicted = m * dbfs + b
    residuals = dbm - predicted
    ss_res    = float(np.sum(residuals ** 2))
    ss_tot    = float(np.sum((dbm - np.mean(dbm)) ** 2))
    r2        = 1.0 - ss_res / (ss_tot + 1e-60)
    rms_err   = float(np.sqrt(np.mean(residuals ** 2)))

    return {
        "slope":        round(float(m), 4),
        "intercept":    round(float(b), 2),
        "r2":           round(r2, 4),
        "n":            int(len(dbfs)),
        "rms_error_db": round(rms_err, 2),
    }


def _print_summary(results: list[dict], fit: dict, freq_hz: int) -> None:
    print(f"\n  === S-Meter Calibration Results ===")
    print(f"  Frequency: {freq_hz/1e6:.4f} MHz")
    print(f"  Points: {len(results)}")
    print()
    print(f"  {'Target':>8}  {'IC-7300':>9}  {'SDR RMS':>9}  {'SDR Peak':>9}")
    print(f"  {'─'*42}")
    for r in results:
        rig_str = f"{r['rig_dbm']:+8.1f}" if not np.isnan(r["rig_dbm"]) else "    N/A "
        print(f"  {r['target_dbm']:>+7.0f}  "
              f"{rig_str}  "
              f"{r['sdr_rms_dbfs']:>+8.1f}  "
              f"{r['sdr_peak_dbfs']:>+8.1f}")

    print()
    if "error" not in fit:
        print(f"  Linear fit: dBm = {fit['slope']:.4f} × dBFS + {fit['intercept']:.2f}")
        print(f"  R²: {fit['r2']:.4f}  |  RMS error: {fit['rms_error_db']:.2f} dB  "
              f"|  N: {fit['n']}")
        print()
        print(f"  Correction formula (Python):")
        print(f"    def dbfs_to_dbm(dbfs): return {fit['slope']:.4f} * dbfs + {fit['intercept']:.2f}")
    else:
        print(f"  Fit failed: {fit['error']}")


# ── Main ──────────────────────────────────────────────────────────────────────

def run(args: argparse.Namespace) -> None:
    if args.power_steps:
        try:
            power_steps = [float(x) for x in args.power_steps.split(",")]
        except ValueError:
            print("ERROR: --power-steps must be comma-separated dBm values")
            sys.exit(1)
    else:
        power_steps = DEFAULT_POWER_STEPS_DBM

    freq_hz = args.freq

    print(f"\n  S-Meter Calibration")
    print(f"  Frequency: {freq_hz/1e6:.4f} MHz")
    print(f"  Power steps: {[f'{p:+.0f}' for p in power_steps]} dBm")
    print()

    # Connect to SDG (optional)
    sdg = None
    if args.sdg_host:
        print(f"  Connecting to SDG1062X at {args.sdg_host}...")
        try:
            sdg = connect(args.sdg_host or 'sdg')
            print(f"  SDG connected: {sdg.identify()}")
        except Exception as e:
            print(f"  WARNING: SDG connection failed ({e})")
            print(f"  Will prompt for manual level changes.")

    # Connect to IC-7300
    print(f"  Connecting to IC-7300 via rigctld at {args.radio_host}:{args.radio_port}...")
    try:
        rig = IC7300(host=args.radio_host, port=args.radio_port)
        print(f"  IC-7300 connected.")
    except Exception as e:
        print(f"  ERROR: {e}")
        sys.exit(1)

    # Connect to SunSDR
    print(f"  Connecting to SunSDR...")
    try:
        sdr = SunSDR(args.sdr_host, port=args.sdr_port, iq_rate=192_000)
    except SunSDRError as e:
        print(f"  ERROR: {e}")
        rig.close()
        sys.exit(1)

    print(f"  Connected: {sdr.identify()['device']}")
    print()
    print(f"  Starting calibration sweep...")
    print(f"  {'─'*55}")
    print(f"  {'Target':>8}  {'IC-7300':>9}  {'SDR RMS':>9}  {'SDR Peak':>9}")
    print(f"  {'─'*55}")

    try:
        results = run_calibration(sdg, rig, sdr, freq_hz, power_steps,
                                  n_samples=args.samples)
        fit     = _fit_correction(results)
        _print_summary(results, fit, freq_hz)

        # Save to JSON
        if args.out:
            data = {
                "freq_hz":    freq_hz,
                "power_steps_dbm": power_steps,
                "results":    results,
                "fit":        fit,
                "note": "dBm = slope * sdr_rms_dbfs + intercept",
            }
            with open(args.out, "w") as f:
                json.dump(data, f, indent=2)
            print(f"\n  Saved to: {args.out}")

    finally:
        if sdg:
            try:
                sdg.output_off_all()
                sdg.close()
            except Exception:
                pass
        rig.close()
        sdr.close()


# ── CLI ───────────────────────────────────────────────────────────────────────

def main() -> None:
    p = argparse.ArgumentParser(
        description="S-Meter Calibration — SunSDR dBFS → dBm via IC-7300 reference",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Hardware setup:
  SDG1062X → calibrated splitter → IC-7300 ANT + SunSDR ANT
  (or: SDG → 30 dB attenuator → splitter → both radios)

Examples:
  python cal_smeter.py --sdr-host 192.168.1.100 --sdg-host 10.1.1.50 --radio-host localhost
  python cal_smeter.py --sdr-host 192.168.1.100 --radio-host localhost --freq 7100000
  python cal_smeter.py --sdr-host 192.168.1.100 --radio-host localhost --out cal-sunsdr.json
        """,
    )
    p.add_argument("--radio-host",   default="localhost", dest="radio_host",
                   help="rigctld host for IC-7300 (default: localhost)")
    p.add_argument("--radio-port",   type=int, default=4532, dest="radio_port")
    p.add_argument("--sdr-host",     required=True, dest="sdr_host",
                   help="SunSDR host IP")
    p.add_argument("--sdr-port",     type=int, default=50001, dest="sdr_port")
    p.add_argument("--sdg-host",     default=None, dest="sdg_host",
                   help="SDG1062X host IP (optional; prompts manually if omitted)")
    p.add_argument("--freq",         type=int, default=14_000_000,
                   help="Test frequency in Hz (default: 14000000)")
    p.add_argument("--power-steps",  default=None, dest="power_steps",
                   help="Comma-separated dBm power levels (default: -20,-30,...,-90)")
    p.add_argument("--samples",      type=int, default=48_000,
                   help="IQ samples per power step (default: 48000 = 250ms @ 192kHz)")
    p.add_argument("--out",          default="cal-sunsdr.json",
                   help="Output JSON calibration file (default: cal-sunsdr.json)")

    args = p.parse_args()
    run(args)


if __name__ == "__main__":
    main()
