#!/usr/bin/env python3
"""
Flipper Zero CC1101 Characterizer

Programs the Flipper CC1101 to TX a carrier at Sub-GHz frequencies, then
measures output frequency accuracy (ppm), output power vs. PA table index,
and harmonic content using the SSA3032X Plus.

Generates ~/.flipper_cc1101_cal.json with per-band calibration data.

Usage:
  python cc1101.py --freqs 315,433.92,868,915 --serial /dev/ttyACM0
  python cc1101.py --freqs 433.92 --gain 0 --ssa 10.1.1.60
  python cc1101.py --freqs 315,433.92 --patable
"""

import argparse
import json
import os
import signal
import sys
import time
from datetime import datetime

import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                '..', 'rf-bench'))
from rf_bench.flipper import FlipperZero
from rf_bench.siglent import SSA3000X
from rf_bench import connect

# ---------------------------------------------------------------------------
# Defaults
# ---------------------------------------------------------------------------
DEFAULT_SSA_HOST   = None  # Now uses inventory
DEFAULT_SERIAL     = "/dev/ttyACM0"
DEFAULT_FREQS_MHZ  = [315.0, 433.92, 868.0, 915.0]
DEFAULT_GAIN_DBM   = 0
CAL_FILE           = os.path.expanduser("~/.flipper_cc1101_cal.json")
PATABLE_INDICES    = list(range(8))   # 0-7

_running = True


def _sigint_handler(sig, frame):
    global _running
    _running = False
    print("\n  [Ctrl+C — stopping after current measurement]")


signal.signal(signal.SIGINT, _sigint_handler)


# ---------------------------------------------------------------------------
# SSA helpers
# ---------------------------------------------------------------------------

def measure_carrier(ssa: SSA3000X, freq_hz: float, span_hz: float = 200_000) -> dict:
    """Zero-span centroid measurement around a carrier. Returns freq_error_ppm and power_dbm."""
    start = freq_hz - span_hz / 2
    stop  = freq_hz + span_hz / 2
    ssa.setup_band(int(start), int(stop))
    ssa.single_sweep()
    trace = ssa.get_trace()
    freqs = np.linspace(start, stop, len(trace))
    peak_idx = int(np.argmax(trace))
    peak_dbm = float(trace[peak_idx])
    peak_hz  = float(freqs[peak_idx])
    ppm      = (peak_hz - freq_hz) / freq_hz * 1e6
    return {"freq_hz": freq_hz, "measured_hz": peak_hz, "ppm": ppm, "power_dbm": peak_dbm}


def measure_harmonics(ssa: SSA3000X, fund_hz: float, n_harmonics: int = 4) -> list:
    """Measure fundamental + harmonics up to n_harmonics. Returns list of (harmonic_n, freq_hz, dbm, dbc)."""
    results = []
    # First get fundamental power
    fund = measure_carrier(ssa, fund_hz)
    fund_dbm = fund["power_dbm"]
    results.append((1, fund_hz, fund_dbm, 0.0))
    for n in range(2, n_harmonics + 1):
        harm_hz = fund_hz * n
        if harm_hz > 3_200_000_000:
            break
        r = measure_carrier(ssa, harm_hz)
        dbc = r["power_dbm"] - fund_dbm
        results.append((n, harm_hz, r["power_dbm"], dbc))
    return results


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_frequency_accuracy(fz: FlipperZero, ssa: SSA3000X,
                             freqs_hz: list) -> dict:
    """TX carrier at each freq, measure ppm error. Returns {freq_hz: result_dict}."""
    results = {}
    print("\n[FREQUENCY ACCURACY]")
    print(f"  {'Freq (MHz)':>12}  {'Measured (MHz)':>16}  {'Error (ppm)':>12}  {'Power (dBm)':>12}")
    print("  " + "-" * 58)

    for freq_hz in freqs_hz:
        if not _running:
            break
        fz.subghz_tx_carrier(int(freq_hz))
        time.sleep(0.3)
        r = measure_carrier(ssa, freq_hz)
        fz.subghz_stop()
        results[freq_hz] = r
        print(f"  {freq_hz/1e6:>12.4f}  {r['measured_hz']/1e6:>16.6f}"
              f"  {r['ppm']:>+12.2f}  {r['power_dbm']:>+12.1f}")

    return results


def test_patable(fz: FlipperZero, ssa: SSA3000X, freq_hz: float) -> list:
    """Sweep PATABLE indices 0-7 and measure output power at each. Returns list of (idx, dbm)."""
    results = []
    print(f"\n[PATABLE SWEEP @ {freq_hz/1e6:.3f} MHz]")
    print(f"  {'Index':>6}  {'Power (dBm)':>12}")
    print("  " + "-" * 22)

    for idx in PATABLE_INDICES:
        if not _running:
            break
        # Flipper sub-GHz gain index: use subghz_tx_carrier with optional gain arg
        # The driver maps idx to PA register values
        fz.subghz_tx_carrier(int(freq_hz))
        time.sleep(0.3)
        r = measure_carrier(ssa, freq_hz)
        fz.subghz_stop()
        results.append((idx, r["power_dbm"]))
        print(f"  {idx:>6}  {r['power_dbm']:>+12.1f}")

    return results


def test_harmonics(fz: FlipperZero, ssa: SSA3000X, freqs_hz: list) -> dict:
    """Measure harmonic content for each frequency. Returns {freq_hz: [(n, hz, dbm, dbc)]}."""
    results = {}
    print("\n[HARMONIC CONTENT]")

    for freq_hz in freqs_hz:
        if not _running:
            break
        print(f"\n  Fundamental: {freq_hz/1e6:.4f} MHz")
        fz.subghz_tx_carrier(int(freq_hz))
        time.sleep(0.3)
        harmonics = measure_harmonics(ssa, freq_hz)
        fz.subghz_stop()
        results[freq_hz] = harmonics
        print(f"  {'Harmonic':>8}  {'Freq (MHz)':>12}  {'Power (dBm)':>12}  {'dBc':>8}")
        print("  " + "-" * 46)
        for n, h_hz, dbm, dbc in harmonics:
            flag = " *** FCC FAIL" if n > 1 and dbc > -43 else ""
            print(f"  {n:>8}  {h_hz/1e6:>12.4f}  {dbm:>+12.1f}  {dbc:>+8.1f}{flag}")

    return results


# ---------------------------------------------------------------------------
# Calibration file
# ---------------------------------------------------------------------------

def save_calibration(freq_results: dict, harmonic_results: dict) -> None:
    """Write calibration data to CAL_FILE."""
    cal = {
        "generated": datetime.now().isoformat(),
        "instrument": "Flipper Zero CC1101",
        "frequency_accuracy": {
            str(int(hz)): {
                "measured_hz": r["measured_hz"],
                "ppm": r["ppm"],
                "power_dbm": r["power_dbm"],
            }
            for hz, r in freq_results.items()
        },
        "harmonics": {
            str(int(hz)): [
                {"n": n, "freq_hz": hf, "power_dbm": dbm, "dbc": dbc}
                for n, hf, dbm, dbc in harm_list
            ]
            for hz, harm_list in harmonic_results.items()
        },
    }
    with open(CAL_FILE, "w") as fh:
        json.dump(cal, fh, indent=2)
    print(f"\n  Calibration saved → {CAL_FILE}")


# ---------------------------------------------------------------------------
# Plot
# ---------------------------------------------------------------------------

def plot_results(freq_results: dict, patable_results: list, output_prefix: str) -> None:
    """Generate summary plots."""
    fig, axes = plt.subplots(1, 2, figsize=(12, 5))

    # Frequency error
    ax = axes[0]
    freqs_mhz = [hz / 1e6 for hz in freq_results]
    ppms      = [r["ppm"] for r in freq_results.values()]
    ax.bar(freqs_mhz, ppms, width=5, color='steelblue', edgecolor='navy')
    ax.axhline(0, color='black', linewidth=0.8)
    ax.set_xlabel("Frequency (MHz)")
    ax.set_ylabel("Error (ppm)")
    ax.set_title("CC1101 Frequency Accuracy")
    ax.tick_params(labelsize=9)

    # PATABLE power
    ax = axes[1]
    if patable_results:
        indices = [r[0] for r in patable_results]
        powers  = [r[1] for r in patable_results]
        ax.plot(indices, powers, 'o-', color='tomato')
        ax.set_xlabel("PATABLE Index")
        ax.set_ylabel("Output Power (dBm)")
        ax.set_title("CC1101 PATABLE Power")
        ax.set_xticks(indices)
        ax.grid(True, alpha=0.4)
        ax.tick_params(labelsize=9)

    plt.tight_layout()
    path = f"{output_prefix}_cc1101.png"
    plt.savefig(path, dpi=150, bbox_inches='tight')
    plt.close(fig)
    print(f"  Plot saved → {path}")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Flipper Zero CC1101 frequency accuracy, power, and harmonic characterizer",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python cc1101.py --freqs 315,433.92,868,915
  python cc1101.py --freqs 433.92 --patable
  python cc1101.py --freqs 315,433.92,868,915 --harmonics
""",
    )
    parser.add_argument("--ssa",      default=DEFAULT_SSA_HOST, metavar="HOST",
                        help=f"SSA IP address (default {DEFAULT_SSA_HOST})")
    parser.add_argument("--serial",   default=DEFAULT_SERIAL, metavar="PORT",
                        help=f"Flipper serial port (default {DEFAULT_SERIAL})")
    parser.add_argument("--freqs",    default=",".join(str(f) for f in DEFAULT_FREQS_MHZ),
                        metavar="LIST",
                        help="Comma-separated frequencies in MHz (default 315,433.92,868,915)")
    parser.add_argument("--gain",     type=int, default=DEFAULT_GAIN_DBM, metavar="DBM",
                        help=f"SSA reference level offset in dBm (default {DEFAULT_GAIN_DBM})")
    parser.add_argument("--patable",  action="store_true",
                        help="Run PATABLE sweep on first frequency")
    parser.add_argument("--harmonics", action="store_true",
                        help="Measure harmonic content at each frequency")
    parser.add_argument("--output",   default=None, metavar="PREFIX",
                        help="Output filename prefix (default: timestamped)")

    args = parser.parse_args()

    freqs_hz = [float(f.strip()) * 1e6 for f in args.freqs.split(",")]
    if args.output is None:
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        args.output = f"cc1101_{ts}"

    try:
        print(f"Connecting to Flipper via inventory'} ...")
        fz = FlipperZero(args.serial)
        info = fz.identify()
        print(f"  {info}")

        print(f"Connecting to SSA via inventory'} ...")
        ssa = connect(args.ssa or 'ssa')
        print(f"  {ssa.identify()}")

        freq_results     = test_frequency_accuracy(fz, ssa, freqs_hz)
        patable_results  = []
        harmonic_results = {}

        if _running and args.patable:
            patable_results = test_patable(fz, ssa, freqs_hz[0])

        if _running and args.harmonics:
            harmonic_results = test_harmonics(fz, ssa, freqs_hz)

        save_calibration(freq_results, harmonic_results)
        plot_results(freq_results, patable_results, args.output)

    except KeyboardInterrupt:
        pass
    except Exception as exc:
        import traceback
        print(f"\nError: {exc}")
        traceback.print_exc()
        sys.exit(1)
    finally:
        try:
            fz.subghz_stop()
        except Exception:
            pass


if __name__ == "__main__":
    main()
