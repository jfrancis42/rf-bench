#!/usr/bin/env python3
"""
Component Bin Sorter — SDM3045X continuous measurement with E12/E24 binning

Reads resistance, capacitance, or diode Vf from the SDM3045X continuously.
After each stable reading, announces the nearest E-series bin and logs to CSV.
Stability: reading must change >5% (new component), then stabilize within 0.1%
across 3 consecutive samples.

Usage:
  python dmm_sorter.py --mode resistance
  python dmm_sorter.py --mode capacitance --series E24
  python dmm_sorter.py --mode kelvin --tolerance 1 --log sorted.csv
  python dmm_sorter.py --mode diode
"""

import argparse
import csv
import os
import signal
import sys
import time
from datetime import datetime

import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                '..', 'rf-bench'))

from rf_bench.siglent import SDM3000X              # noqa: E402
from rf_bench.utils import E12_SERIES, E24_SERIES  # noqa: E402

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

DEFAULT_DMM_HOST  = "10.1.1.63"
STABLE_COUNT      = 3      # consecutive readings within STABLE_PCT to declare stable
STABLE_PCT        = 0.001  # 0.1% stability window
CHANGE_PCT        = 0.05   # 5% change triggers component-change reset
POLL_INTERVAL_S   = 0.15   # seconds between DMM reads
DEFAULT_TOLERANCE = 5.0    # pass/fail tolerance %
DEFAULT_SERIES    = "E12"

_running = True


def _sigint_handler(sig, frame):
    global _running
    _running = False
    print("\n  [Ctrl+C received — stopping ...]")


signal.signal(signal.SIGINT, _sigint_handler)

# ---------------------------------------------------------------------------
# E-series nearest value
# ---------------------------------------------------------------------------

def nearest_e_value(value: float, series: list[float]) -> float:
    """Return the nearest E-series value (with decade scaling) to value."""
    if value <= 0:
        return float('nan')
    decade = 10 ** np.floor(np.log10(value))
    normalised = value / decade
    diffs = [abs(normalised - s) for s in series]
    nearest = series[int(np.argmin(diffs))]
    return nearest * decade


def format_value(value: float, mode: str) -> str:
    """Format a measurement value with appropriate units."""
    if mode in ('resistance', 'kelvin'):
        if value < 1e3:
            return f"{value:.3f} Ω"
        elif value < 1e6:
            return f"{value/1e3:.3f} kΩ"
        else:
            return f"{value/1e6:.3f} MΩ"
    elif mode == 'capacitance':
        if value < 1e-9:
            return f"{value*1e12:.3f} pF"
        elif value < 1e-6:
            return f"{value*1e9:.3f} nF"
        else:
            return f"{value*1e6:.3f} µF"
    elif mode == 'diode':
        return f"{value:.4f} V"
    return f"{value:.6g}"


def tolerance_check(measured: float, nominal: float, tol_pct: float) -> str:
    """Return 'PASS' or 'FAIL' based on tolerance check."""
    if nominal == 0:
        return "PASS"
    error_pct = abs(measured - nominal) / nominal * 100.0
    return "PASS" if error_pct <= tol_pct else f"FAIL ({error_pct:.1f}%)"


# ---------------------------------------------------------------------------
# DMM measurement dispatch
# ---------------------------------------------------------------------------

def measure_once(dmm: SDM3000X, mode: str) -> float | None:
    """Take one measurement; return float or None on error."""
    try:
        if mode == 'resistance':
            return dmm.measure_resistance()
        elif mode == 'kelvin':
            return dmm.measure_resistance_4w()
        elif mode == 'capacitance':
            return dmm.measure_capacitance()
        elif mode == 'diode':
            return dmm.measure_diode()
    except Exception as exc:
        print(f"  [DMM read error: {exc}]", end='\r', flush=True)
    return None


# ---------------------------------------------------------------------------
# Main sorter loop
# ---------------------------------------------------------------------------

def run_sorter(dmm: SDM3000X, args: argparse.Namespace) -> None:
    """Continuous sorter loop."""
    series_values = E24_SERIES if args.series == 'E24' else E12_SERIES
    log_writer: csv.DictWriter | None = None
    log_file = None
    component_count = 0

    if args.log:
        log_file = open(args.log, 'w', newline='')
        fieldnames = ['timestamp', 'component', 'mode', 'measured', 'nominal',
                      'error_pct', 'result']
        log_writer = csv.DictWriter(log_file, fieldnames=fieldnames)
        log_writer.writeheader()

    readings: list[float] = []
    last_announced: float | None = None

    print(f"\n  Mode     : {args.mode}")
    print(f"  Series   : {args.series}")
    print(f"  Tolerance: ±{args.tolerance}%")
    if args.log:
        print(f"  Log      : {args.log}")
    print("\n  Probe component... (Ctrl+C to quit)\n")

    try:
        while _running:
            val = measure_once(dmm, args.mode)
            if val is None or not np.isfinite(val) or val <= 0:
                readings.clear()
                time.sleep(POLL_INTERVAL_S)
                continue

            readings.append(val)

            # Detect large change (new component placed) → reset buffer
            if len(readings) >= 2:
                ratio = abs(readings[-1] - readings[-2]) / max(abs(readings[-2]), 1e-30)
                if ratio > CHANGE_PCT:
                    readings = [readings[-1]]

            # Check stability: last 3 readings within 0.1%
            if len(readings) >= STABLE_COUNT:
                window = readings[-STABLE_COUNT:]
                spread = max(window) / max(min(window), 1e-30)
                if spread < (1.0 + STABLE_PCT):
                    stable_val = float(np.mean(window))

                    # Skip if same component still sitting on probes
                    if last_announced is not None:
                        still_same = abs(stable_val - last_announced) / max(abs(last_announced), 1e-30) < CHANGE_PCT
                        if still_same:
                            time.sleep(POLL_INTERVAL_S)
                            continue

                    last_announced = stable_val
                    component_count += 1
                    nominal = nearest_e_value(stable_val, series_values) if args.mode != 'diode' else stable_val
                    result  = tolerance_check(stable_val, nominal, args.tolerance) if args.mode != 'diode' else "—"

                    measured_str = format_value(stable_val, args.mode)
                    nominal_str  = format_value(nominal, args.mode) if args.mode != 'diode' else "—"
                    error_pct    = (abs(stable_val - nominal) / max(abs(nominal), 1e-30) * 100.0
                                    if args.mode != 'diode' else 0.0)

                    print(f"  [{component_count:4d}]  {measured_str:>14}  →  {args.series}: {nominal_str:>14}  "
                          f"error: {error_pct:+.1f}%  {result}")
                    print('\a', end='', flush=True)  # system bell

                    if log_writer:
                        log_writer.writerow({
                            'timestamp':  datetime.now().isoformat(),
                            'component':  component_count,
                            'mode':       args.mode,
                            'measured':   stable_val,
                            'nominal':    nominal,
                            'error_pct':  f"{error_pct:.2f}",
                            'result':     result,
                        })
                        log_file.flush()

                    readings.clear()

            time.sleep(POLL_INTERVAL_S)

    finally:
        if log_file:
            log_file.close()

    print(f"\n  Session complete — {component_count} components sorted.")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Component bin sorter — SDM3045X continuous measurement with E-series binning",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python dmm_sorter.py --mode resistance
  python dmm_sorter.py --mode capacitance --series E24 --log caps.csv
  python dmm_sorter.py --mode kelvin --tolerance 1
  python dmm_sorter.py --mode diode
""",
    )
    parser.add_argument("--dmm",       default=DEFAULT_DMM_HOST, metavar="HOST",
                        help=f"SDM3045X IP address (default {DEFAULT_DMM_HOST})")
    parser.add_argument("--mode",      choices=['resistance', 'kelvin', 'capacitance', 'diode'],
                        default='resistance',
                        help="Measurement mode (default: resistance)")
    parser.add_argument("--series",    choices=['E12', 'E24'], default=DEFAULT_SERIES,
                        help=f"E-series for binning (default {DEFAULT_SERIES})")
    parser.add_argument("--tolerance", type=float, default=DEFAULT_TOLERANCE, metavar="PCT",
                        help=f"Pass/fail tolerance in %% (default {DEFAULT_TOLERANCE})")
    parser.add_argument("--log",       default=None, metavar="FILE",
                        help="CSV log file path")

    args = parser.parse_args()

    print(f"Connecting to SDM3045X @ {args.dmm} ...")
    try:
        dmm = SDM3000X(args.dmm)
        print(f"  {dmm.identify()}")
        run_sorter(dmm, args)
    except ConnectionRefusedError as exc:
        print(f"\nCannot connect to DMM: {exc}")
        sys.exit(1)
    except OSError as exc:
        print(f"\nNetwork error: {exc}")
        sys.exit(1)
    except Exception as exc:
        import traceback
        print(f"\nUnexpected error: {exc}")
        traceback.print_exc()
        sys.exit(1)
    finally:
        try:
            dmm.disconnect()
        except Exception:
            pass


if __name__ == "__main__":
    main()
