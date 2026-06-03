#!/usr/bin/env python3
"""
Flipper Zero Sub-GHz Receiver Sensitivity Mapper

Maps CC1101 receiver sensitivity by stepping the SSA tracking generator level
from -20 to -120 dBm at 315/433.92/868/915 MHz. Flipper reports RSSI at each
level. Produces per-band RSSI calibration table and minimum detectable signal (MDS).

Usage:
  python subghz_sensitivity.py --freqs 315,433.92,868,915
  python subghz_sensitivity.py --freqs 433.92 --serial /dev/ttyACM0
  python subghz_sensitivity.py --ssa 10.1.1.60 --freqs 315,433.92
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

# ---------------------------------------------------------------------------
# Defaults
# ---------------------------------------------------------------------------
DEFAULT_SSA_HOST  = "10.1.1.60"
DEFAULT_SERIAL    = "/dev/ttyACM0"
DEFAULT_FREQS_MHZ = [315.0, 433.92, 868.0, 915.0]
LEVEL_START_DBM   = -20.0
LEVEL_STOP_DBM    = -120.0
LEVEL_STEP_DBM    = -5.0
MDS_THRESHOLD_DBM = -3.0   # RSSI loss relative to linear region = MDS

_running = True


def _sigint_handler(sig, frame):
    global _running
    _running = False
    print("\n  [Ctrl+C — stopping after current measurement]")


signal.signal(signal.SIGINT, _sigint_handler)


# ---------------------------------------------------------------------------
# Measurement
# ---------------------------------------------------------------------------

def sweep_sensitivity(fz: FlipperZero, ssa: SSA3000X,
                      freq_hz: float, duration_per_step: float = 0.5) -> list:
    """
    Step SSA tracking generator level from LEVEL_START to LEVEL_STOP.
    At each level read Flipper RSSI.
    Returns list of (applied_dbm, rssi_readings) tuples.
    """
    results = []
    levels = np.arange(LEVEL_START_DBM, LEVEL_STOP_DBM + LEVEL_STEP_DBM, LEVEL_STEP_DBM)
    print(f"\n  [SENSITIVITY @ {freq_hz/1e6:.4f} MHz]  levels: {len(levels)}")
    print(f"  {'Applied (dBm)':>14}  {'RSSI mean (dBm)':>16}  {'RSSI std':>10}")
    print("  " + "-" * 46)

    ssa.setup_band(int(freq_hz - 500_000), int(freq_hz + 500_000))
    ssa.enable_tracking_generator(dbm=LEVEL_START_DBM)

    for level in levels:
        if not _running:
            break
        ssa.enable_tracking_generator(dbm=float(level))
        time.sleep(0.1)
        readings = fz.subghz_get_rssi(int(freq_hz), duration_s=duration_per_step)
        if readings:
            mean_rssi = float(np.mean(readings))
            std_rssi  = float(np.std(readings))
        else:
            mean_rssi = -150.0
            std_rssi  = 0.0
        results.append((float(level), mean_rssi, std_rssi))
        print(f"  {level:>+14.1f}  {mean_rssi:>+16.1f}  {std_rssi:>10.2f}")

    ssa.disable_tracking_generator()
    return results


def find_mds(results: list) -> float:
    """
    Estimate MDS as the applied level where RSSI departs from the linear trend
    by more than MDS_THRESHOLD_DBM dB (compression).
    Returns applied dBm at MDS, or NaN if not found.
    """
    if len(results) < 4:
        return float('nan')

    applied = np.array([r[0] for r in results])
    rssi    = np.array([r[1] for r in results])

    # Fit linear to top 5 points (high signal region)
    top_n = min(5, len(results))
    coeffs = np.polyfit(applied[:top_n], rssi[:top_n], 1)
    linear_pred = np.polyval(coeffs, applied)
    delta = rssi - linear_pred

    # MDS = first point where RSSI is >3 dB below linear prediction
    for i in range(len(delta) - 1, -1, -1):
        if delta[i] > MDS_THRESHOLD_DBM:
            return float(applied[i])

    return float(applied[-1])


# ---------------------------------------------------------------------------
# Plot
# ---------------------------------------------------------------------------

def plot_sensitivity(all_results: dict, output_prefix: str) -> None:
    """Plot RSSI vs. applied level for all frequencies."""
    n_freqs = len(all_results)
    fig, axes = plt.subplots(1, n_freqs, figsize=(5 * n_freqs, 5), sharey=False)
    if n_freqs == 1:
        axes = [axes]

    for ax, (freq_hz, results) in zip(axes, all_results.items()):
        applied = [r[0] for r in results]
        rssi    = [r[1] for r in results]
        ax.plot(applied, rssi, 'o-', label='RSSI')
        ax.plot(applied, applied, 'k--', alpha=0.4, label='Ideal (1:1)')
        mds = find_mds(results)
        if not np.isnan(mds):
            ax.axvline(mds, color='red', linestyle=':', linewidth=1.5,
                       label=f'MDS ≈ {mds:+.0f} dBm')
        ax.set_xlabel("Applied Level (dBm)")
        ax.set_ylabel("RSSI (dBm)")
        ax.set_title(f"{freq_hz/1e6:.3f} MHz")
        ax.legend(fontsize=8)
        ax.grid(True, alpha=0.4)
        ax.tick_params(labelsize=9)

    plt.suptitle("Flipper Zero CC1101 RX Sensitivity", fontsize=12)
    plt.tight_layout()
    path = f"{output_prefix}_sensitivity.png"
    plt.savefig(path, dpi=150, bbox_inches='tight')
    plt.close(fig)
    print(f"  Plot → {path}")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Map Flipper Zero CC1101 receiver sensitivity vs. SSA input level",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python subghz_sensitivity.py --freqs 315,433.92,868,915
  python subghz_sensitivity.py --freqs 433.92 --serial /dev/ttyACM0
""",
    )
    parser.add_argument("--ssa",    default=DEFAULT_SSA_HOST, metavar="HOST",
                        help=f"SSA IP address (default {DEFAULT_SSA_HOST})")
    parser.add_argument("--serial", default=DEFAULT_SERIAL, metavar="PORT",
                        help=f"Flipper serial port (default {DEFAULT_SERIAL})")
    parser.add_argument("--freqs",  default=",".join(str(f) for f in DEFAULT_FREQS_MHZ),
                        metavar="LIST",
                        help="Comma-separated MHz (default 315,433.92,868,915)")
    parser.add_argument("--output", default=None, metavar="PREFIX",
                        help="Output filename prefix (default: timestamped)")

    args = parser.parse_args()
    freqs_hz = [float(f.strip()) * 1e6 for f in args.freqs.split(",")]

    if args.output is None:
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        args.output = f"subghz_sensitivity_{ts}"

    fz  = None
    ssa = None
    try:
        print(f"Connecting to Flipper @ {args.serial} ...")
        fz = FlipperZero(args.serial)
        print(f"  {fz.identify()}")

        print(f"Connecting to SSA @ {args.ssa} ...")
        ssa = SSA3000X(args.ssa)
        print(f"  {ssa.identify()}")

        all_results: dict[float, list] = {}
        cal_table: dict = {}

        for freq_hz in freqs_hz:
            if not _running:
                break
            results = sweep_sensitivity(fz, ssa, freq_hz)
            all_results[freq_hz] = results
            mds = find_mds(results)
            cal_table[str(int(freq_hz))] = {
                "mds_dbm": mds,
                "levels": results,
            }
            print(f"  MDS @ {freq_hz/1e6:.3f} MHz ≈ {mds:+.1f} dBm")

        # Save calibration JSON
        cal_path = f"{args.output}_cal.json"
        cal_data = {
            "generated": datetime.now().isoformat(),
            "instrument": "Flipper Zero CC1101",
            "bands": cal_table,
        }
        with open(cal_path, "w") as fh:
            json.dump(cal_data, fh, indent=2)
        print(f"\n  Calibration → {cal_path}")

        if all_results:
            plot_sensitivity(all_results, args.output)

    except KeyboardInterrupt:
        pass
    except Exception as exc:
        import traceback
        print(f"\nError: {exc}")
        traceback.print_exc()
        sys.exit(1)
    finally:
        if ssa is not None:
            try:
                ssa.disable_tracking_generator()
            except Exception:
                pass


if __name__ == "__main__":
    main()
