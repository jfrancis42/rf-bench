#!/usr/bin/env python3
"""
Flipper Zero 125 kHz RFID Field Characterizer

The Flipper emulates a 125 kHz LF RFID reader field. The SSA3032X Plus with a
coupling loop measures:
  - Frequency accuracy (zero-span centroid, ppm error)
  - Harmonic content (100 kHz – 2 MHz sweep)
  - Field strength vs. distance (manual step mode)

Usage:
  python rfid_field.py --test all
  python rfid_field.py --test freq
  python rfid_field.py --test harmonics
  python rfid_field.py --test distance --ssa 10.1.1.60
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
DEFAULT_SSA_HOST  = None  # Now uses inventory
DEFAULT_SERIAL    = "/dev/ttyACM0"
RFID_FREQ_HZ      = 125_000
RFID_SPAN_HZ      = 10_000       # span for frequency measurement
HARMONIC_START_HZ = 100_000
HARMONIC_STOP_HZ  = 2_000_000
NOMINAL_KEY       = "EM4100"     # key type used to activate field
NOMINAL_DATA      = "0102030405"

_running = True


def _sigint_handler(sig, frame):
    global _running
    _running = False
    print("\n  [Ctrl+C — stopping]")


signal.signal(signal.SIGINT, _sigint_handler)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_frequency(fz: FlipperZero, ssa: SSA3000X) -> dict:
    """Measure 125 kHz carrier frequency accuracy."""
    print("\n[FREQUENCY ACCURACY TEST]")
    print("  Activating RFID field (EM4100 emulation) ...")
    fz.lfrfid_emulate(NOMINAL_KEY, NOMINAL_DATA)
    time.sleep(0.5)

    start = RFID_FREQ_HZ - RFID_SPAN_HZ // 2
    stop  = RFID_FREQ_HZ + RFID_SPAN_HZ // 2
    ssa.setup_band(start, stop)
    ssa.single_sweep()
    trace = ssa.get_trace()
    freqs = np.linspace(start, stop, len(trace))

    peak_idx = int(np.argmax(trace))
    peak_hz  = float(freqs[peak_idx])
    peak_dbm = float(trace[peak_idx])
    ppm      = (peak_hz - RFID_FREQ_HZ) / RFID_FREQ_HZ * 1e6

    fz.lfrfid_stop()

    result = {"nominal_hz": RFID_FREQ_HZ, "measured_hz": peak_hz,
              "power_dbm": peak_dbm, "ppm": ppm}
    print(f"  Nominal : {RFID_FREQ_HZ/1e3:.3f} kHz")
    print(f"  Measured: {peak_hz/1e3:.4f} kHz")
    print(f"  Power   : {peak_dbm:+.1f} dBm")
    print(f"  Error   : {ppm:+.2f} ppm")
    return result


def test_harmonics(fz: FlipperZero, ssa: SSA3000X) -> list:
    """Sweep 100 kHz–2 MHz to measure harmonic content."""
    print("\n[HARMONIC CONTENT TEST]")
    print(f"  Sweep: {HARMONIC_START_HZ/1e3:.0f} kHz – {HARMONIC_STOP_HZ/1e3:.0f} kHz")
    fz.lfrfid_emulate(NOMINAL_KEY, NOMINAL_DATA)
    time.sleep(0.5)

    ssa.setup_band(HARMONIC_START_HZ, HARMONIC_STOP_HZ)
    ssa.single_sweep()
    trace = ssa.get_trace()
    freqs = np.linspace(HARMONIC_START_HZ, HARMONIC_STOP_HZ, len(trace))

    fz.lfrfid_stop()

    # Extract fundamental + harmonics
    results = []
    fund_dbm = None
    for n in range(1, 17):
        target_hz = RFID_FREQ_HZ * n
        if target_hz < HARMONIC_START_HZ or target_hz > HARMONIC_STOP_HZ:
            continue
        idx = int(np.argmin(np.abs(freqs - target_hz)))
        dbm = float(trace[idx])
        if n == 1:
            fund_dbm = dbm
        dbc = dbm - fund_dbm if fund_dbm is not None else 0.0
        results.append({"n": n, "freq_hz": target_hz, "power_dbm": dbm, "dbc": dbc})

    print(f"  {'Harmonic':>8}  {'Freq (kHz)':>12}  {'Power (dBm)':>12}  {'dBc':>8}")
    print("  " + "-" * 46)
    for r in results:
        flag = " *** HIGH" if r["n"] > 1 and r["dbc"] > -30 else ""
        print(f"  {r['n']:>8}  {r['freq_hz']/1e3:>12.1f}  {r['power_dbm']:>+12.1f}"
              f"  {r['dbc']:>+8.1f}{flag}")

    return results


def test_distance(fz: FlipperZero, ssa: SSA3000X) -> list:
    """Manual distance sweep: prompt user to move loop, measure field strength."""
    print("\n[FIELD STRENGTH vs. DISTANCE]")
    print("  Connect a coupling loop to the SSA input.")
    print("  At each prompt, position the loop at the stated distance and press Enter.")

    fz.lfrfid_emulate(NOMINAL_KEY, NOMINAL_DATA)
    time.sleep(0.5)

    ssa.setup_band(
        RFID_FREQ_HZ - RFID_SPAN_HZ // 2,
        RFID_FREQ_HZ + RFID_SPAN_HZ // 2,
    )

    distances_cm = [0, 1, 2, 3, 5, 7, 10, 15, 20, 30]
    results = []

    print(f"\n  {'Distance (cm)':>14}  {'Power (dBm)':>12}")
    print("  " + "-" * 30)

    for d in distances_cm:
        if not _running:
            break
        input(f"  Position loop at {d:3d} cm, then press Enter ...")
        ssa.single_sweep()
        trace = ssa.get_trace()
        peak_dbm = float(np.max(trace))
        results.append({"distance_cm": d, "power_dbm": peak_dbm})
        print(f"  {d:>14}  {peak_dbm:>+12.1f}")

    fz.lfrfid_stop()
    return results


# ---------------------------------------------------------------------------
# Plot
# ---------------------------------------------------------------------------

def plot_all(freq_result: dict, harmonic_results: list,
             distance_results: list, output_prefix: str) -> None:
    cols = sum([
        1 if freq_result else 0,
        1 if harmonic_results else 0,
        1 if distance_results else 0,
    ])
    if cols == 0:
        return

    fig, axes = plt.subplots(1, cols, figsize=(5 * cols, 5))
    if cols == 1:
        axes = [axes]
    ax_idx = 0

    if freq_result:
        ax = axes[ax_idx]; ax_idx += 1
        ax.bar(["125 kHz"], [freq_result["ppm"]], color='steelblue')
        ax.axhline(0, color='black', linewidth=0.8)
        ax.set_ylabel("Frequency Error (ppm)")
        ax.set_title("RFID Field Frequency Accuracy")
        ax.tick_params(labelsize=9)

    if harmonic_results:
        ax = axes[ax_idx]; ax_idx += 1
        ns   = [r["n"] for r in harmonic_results]
        dbcs = [r["dbc"] for r in harmonic_results]
        ax.bar(ns, dbcs, color='tomato')
        ax.axhline(-30, color='orange', linestyle='--', linewidth=1, label='−30 dBc')
        ax.set_xlabel("Harmonic")
        ax.set_ylabel("Level (dBc)")
        ax.set_title("RFID Harmonic Content")
        ax.legend(fontsize=8)
        ax.tick_params(labelsize=9)

    if distance_results:
        ax = axes[ax_idx]; ax_idx += 1
        dist = [r["distance_cm"] for r in distance_results]
        pwr  = [r["power_dbm"]   for r in distance_results]
        ax.plot(dist, pwr, 'o-', color='green')
        ax.set_xlabel("Distance (cm)")
        ax.set_ylabel("Coupled Power (dBm)")
        ax.set_title("RFID Field Strength vs. Distance")
        ax.grid(True, alpha=0.4)
        ax.tick_params(labelsize=9)

    plt.tight_layout()
    path = f"{output_prefix}_rfid_field.png"
    plt.savefig(path, dpi=150, bbox_inches='tight')
    plt.close(fig)
    print(f"\n  Plot → {path}")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Flipper Zero 125 kHz RFID field characterizer",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python rfid_field.py --test all
  python rfid_field.py --test freq --ssa 10.1.1.60
  python rfid_field.py --test distance
""",
    )
    parser.add_argument("--ssa",    default=DEFAULT_SSA_HOST, metavar="HOST",
                        help=f"SSA IP address (default {DEFAULT_SSA_HOST})")
    parser.add_argument("--serial", default=DEFAULT_SERIAL, metavar="PORT",
                        help=f"Flipper serial port (default {DEFAULT_SERIAL})")
    parser.add_argument("--test",   default="all",
                        choices=["freq", "harmonics", "distance", "all"],
                        help="Test to run (default: all)")
    parser.add_argument("--output", default=None, metavar="PREFIX",
                        help="Output filename prefix (default: timestamped)")

    args = parser.parse_args()

    if args.output is None:
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        args.output = f"rfid_field_{ts}"

    try:
        print(f"Connecting to Flipper via inventory ...")
        fz = FlipperZero(args.serial)
        print(f"  {fz.identify()}")

        print(f"Connecting to SSA via inventory ...")
        ssa = connect(args.ssa or 'ssa')
        print(f"  {ssa.identify()}")

        freq_result      = {}
        harmonic_results = []
        distance_results = []

        run_all = args.test == "all"

        if _running and (run_all or args.test == "freq"):
            freq_result = test_frequency(fz, ssa)

        if _running and (run_all or args.test == "harmonics"):
            harmonic_results = test_harmonics(fz, ssa)

        if _running and (run_all or args.test == "distance"):
            distance_results = test_distance(fz, ssa)

        # Save JSON
        results = {
            "generated": datetime.now().isoformat(),
            "frequency": freq_result,
            "harmonics": harmonic_results,
            "distance":  distance_results,
        }
        json_path = f"{args.output}_rfid_field.json"
        with open(json_path, "w") as fh:
            json.dump(results, fh, indent=2)
        print(f"  Data  → {json_path}")

        plot_all(freq_result, harmonic_results, distance_results, args.output)

    except KeyboardInterrupt:
        pass
    except Exception as exc:
        import traceback
        print(f"\nError: {exc}")
        traceback.print_exc()
        sys.exit(1)
    finally:
        try:
            fz.lfrfid_stop()
        except Exception:
            pass


if __name__ == "__main__":
    main()
