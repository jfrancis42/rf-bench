#!/usr/bin/env python3
"""
Multi-DUT Sequential Component Tester

Steps through relay positions on an XL9535 I2C relay board (via Bus Pirate I2C),
closes one relay at a time, measures the connected component with a Siglent SDM3045X
bench DMM, then opens it and moves to the next.

Use cases:
    Crystal sorting:   measure fs/Rs of 8+ crystals automatically
    Capacitor binning: measure C per socket, sort by value
    Resistor matching: 4-wire Kelvin resistance per socket
    Diode Vf matching: forward voltage per socket

Usage:
    python relay_multidut.py --mode res [options]   # 2-wire resistance
    python relay_multidut.py --mode res4w [options] # 4-wire Kelvin
    python relay_multidut.py --mode cap [options]   # capacitance
    python relay_multidut.py --mode diode [options] # diode Vf
    python relay_multidut.py --mode ping [options]  # relay self-test (no DMM)
"""

import argparse
import csv
import json
import os
import statistics
import sys
import time
from datetime import datetime

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

from rf_bench.siglent import SDM3000X
from rf_bench.buspirate import BusPirate
from rf_bench.relay import XL9535

# ── Defaults ──────────────────────────────────────────────────────────────────

DEFAULT_DMM      = "10.1.1.63"
DEFAULT_BP       = "/dev/ttyUSB1"
DEFAULT_I2C_ADDR = 0x20
DEFAULT_POSITIONS = list(range(8))
DEFAULT_DELAY_MS  = 50
DEFAULT_TOLERANCE = 1.0
NUM_READINGS      = 3          # median of N readings per position

# Value above which a DMM reading is considered open-circuit (SDM overrange sentinel)
OVERRANGE_THRESHOLD = 9.0e37

# ── Mode configuration ─────────────────────────────────────────────────────────

MODE_INFO = {
    "res":   {"label": "2-wire resistance", "unit": "Ω",  "plot": True},
    "res4w": {"label": "4-wire resistance", "unit": "Ω",  "plot": True},
    "cap":   {"label": "capacitance",       "unit": "F",  "plot": True},
    "diode": {"label": "diode Vf",          "unit": "V",  "plot": False},
    "ping":  {"label": "relay self-test",   "unit": None, "plot": False},
}


# ── Formatting helpers ─────────────────────────────────────────────────────────

def format_value(val: float, unit: str) -> str:
    """Human-readable formatting for measured values."""
    if unit == "Ω":
        if val >= 1e9:
            return f"{val/1e9:.3f} GΩ"
        if val >= 1e6:
            return f"{val/1e6:.3f} MΩ"
        if val >= 1e3:
            return f"{val/1e3:.3f} kΩ"
        return f"{val:.3f} Ω"
    if unit == "F":
        if val >= 1e-3:
            return f"{val*1e3:.3f} mF"
        if val >= 1e-6:
            return f"{val*1e6:.3f} µF"
        if val >= 1e-9:
            return f"{val*1e9:.3f} nF"
        return f"{val*1e12:.3f} pF"
    if unit == "V":
        return f"{val:.4f} V"
    return str(val)


def is_overrange(val: float) -> bool:
    """Return True if the DMM returned an overrange / open-circuit sentinel."""
    return abs(val) >= OVERRANGE_THRESHOLD


# ── DMM configuration ──────────────────────────────────────────────────────────

def configure_dmm(dmm: SDM3000X, mode: str):
    """Configure the DMM for the requested measurement mode."""
    if mode == "res":
        dmm.configure_resistance(four_wire=False)
    elif mode == "res4w":
        dmm.configure_resistance(four_wire=True)
    elif mode == "cap":
        # configure_capacitance is not in the SDM3000X driver as a configure_ variant;
        # use the one-shot measure path inside the measurement loop instead.
        pass
    elif mode == "diode":
        dmm.configure_diode()


def take_measurement(dmm: SDM3000X, mode: str) -> float:
    """Trigger a single measurement in the current mode. Returns float in SI units."""
    if mode == "cap":
        return dmm.measure_capacitance()
    # All other modes use configure_*() + read()
    return dmm.read()


# ── Main measurement loop ──────────────────────────────────────────────────────

def run_measurement(args) -> list[dict]:
    """
    Connect to Bus Pirate + DMM, step through relay positions, collect readings.
    Returns list of result dicts (one per position).
    """
    positions = args.positions
    delay_s   = args.delay / 1000.0
    active_high = not args.active_low
    mode      = args.mode

    # Load optional label map
    labels = {}
    if args.label:
        with open(args.label) as f:
            labels = json.load(f)

    results = []

    print(f"Mode: {MODE_INFO[mode]['label']}")
    print(f"Positions: {positions}")
    print(f"Settle delay: {args.delay} ms")
    if args.nominal is not None:
        print(f"Nominal: {args.nominal}  tolerance: ±{args.tolerance}%")
    print()

    with BusPirate(args.bp) as bp:
        bp.set_pullups(True)
        bp.i2c_configure(speed_hz=100_000)

        with XL9535(bp, i2c_addr=args.addr, active_high=active_high,
                    num_relays=max(positions) + 1) as rl:
            rl.configure_outputs()
            rl.all_off()

            with SDM3000X(args.dmm) as dmm:
                # Configure DMM once (cap mode does one-shot per reading)
                if mode != "cap":
                    configure_dmm(dmm, mode)

                for pos in positions:
                    label = labels.get(str(pos), f"pos{pos}")

                    rl.close_only(pos)
                    time.sleep(delay_s)

                    # Collect NUM_READINGS, use median to reject relay-bounce transients
                    readings = []
                    for _ in range(NUM_READINGS):
                        try:
                            v = take_measurement(dmm, mode)
                        except Exception as e:
                            print(f"  pos {pos} ({label}): DMM read error: {e}")
                            v = float("nan")
                        readings.append(v)
                        if mode == "cap":
                            time.sleep(0.2)  # cap measurements are slow

                    rl.all_off()

                    # Filter NaNs before median
                    valid = [r for r in readings if not (r != r)]
                    if not valid:
                        median_val = float("nan")
                    else:
                        median_val = statistics.median(valid)

                    # Build result record
                    rec = {
                        "pos":    pos,
                        "label":  label,
                        "value":  median_val,
                        "open":   is_overrange(median_val) or (median_val != median_val),
                    }

                    # Deviation from nominal
                    if args.nominal is not None and not rec["open"]:
                        dev_pct = (median_val - args.nominal) / args.nominal * 100.0
                        rec["dev_pct"] = dev_pct
                        rec["pass"]    = abs(dev_pct) <= args.tolerance
                    else:
                        rec["dev_pct"] = None
                        rec["pass"]    = None

                    results.append(rec)

                    # Print live result
                    _print_result(rec, MODE_INFO[mode]["unit"], args)

        bp.i2c_exit()

    return results


def _print_result(rec: dict, unit: str | None, args):
    """Print one result line to stdout."""
    pos   = rec["pos"]
    label = rec["label"]

    if rec["open"]:
        value_str = "OPEN"
    else:
        value_str = format_value(rec["value"], unit) if unit else str(rec["value"])

    dev_str  = ""
    pass_str = ""
    if rec["dev_pct"] is not None:
        dev_str  = f"  {rec['dev_pct']:+.3f}%"
        pass_str = f"  [{'PASS' if rec['pass'] else 'FAIL'}]"

    print(f"  pos {pos:2d}  {label:<12s}  {value_str:>18s}{dev_str}{pass_str}")


# ── Ping mode (relay self-test, no DMM) ──────────────────────────────────────

def run_ping(args):
    """Cycle each relay open/close, report OK. No DMM connection required."""
    positions   = args.positions
    active_high = not args.active_low
    delay_s     = args.delay / 1000.0

    print(f"Relay self-test: positions {positions}")
    print(f"Bus Pirate: {args.bp}  I2C addr: 0x{args.addr:02X}")
    print()

    with BusPirate(args.bp) as bp:
        bp.set_pullups(True)
        bp.i2c_configure(speed_hz=100_000)

        with XL9535(bp, i2c_addr=args.addr, active_high=active_high,
                    num_relays=max(positions) + 1) as rl:
            rl.configure_outputs()
            rl.all_off()

            for pos in positions:
                rl.close_only(pos)
                time.sleep(delay_s)
                rl.all_off()
                time.sleep(0.01)
                print(f"  relay {pos:2d}: OK")

        bp.i2c_exit()

    print("\nSelf-test complete.")


# ── Summary table and CSV output ──────────────────────────────────────────────

def print_summary(results: list[dict], mode: str, args):
    """Print a sorted summary table (if --sort) and pass/fail counts."""
    unit = MODE_INFO[mode]["unit"]
    data = [r for r in results if not r["open"]]

    if args.sort and data:
        data_sorted = sorted(data, key=lambda r: r["value"])
        open_recs   = [r for r in results if r["open"]]
        ordered     = data_sorted + open_recs
    else:
        ordered = results

    print("\n" + "─" * 60)
    print("SUMMARY" + (f"  (sorted by value)" if args.sort else ""))
    print("─" * 60)
    for rec in ordered:
        _print_result(rec, unit, args)

    # Pass/fail count
    judged = [r for r in results if r["pass"] is not None]
    if judged:
        n_pass = sum(1 for r in judged if r["pass"])
        n_fail = len(judged) - n_pass
        print(f"\nResult: {n_pass} PASS / {n_fail} FAIL out of {len(judged)} measured")


def save_csv(results: list[dict], mode: str, path: str):
    """Save results to CSV file."""
    unit = MODE_INFO[mode]["unit"]
    with open(path, "w", newline="") as f:
        fieldnames = ["pos", "label", "value_raw", f"value_{unit or 'raw'}",
                      "open", "dev_pct", "pass"]
        w = csv.DictWriter(f, fieldnames=["pos", "label", "value_raw",
                                          "formatted", "open", "dev_pct", "pass"])
        w.writeheader()
        for rec in results:
            w.writerow({
                "pos":       rec["pos"],
                "label":     rec["label"],
                "value_raw": "" if rec["open"] else rec["value"],
                "formatted": "OPEN" if rec["open"] else (
                    format_value(rec["value"], unit) if unit else rec["value"]
                ),
                "open":      rec["open"],
                "dev_pct":   "" if rec["dev_pct"] is None else f"{rec['dev_pct']:.4f}",
                "pass":      "" if rec["pass"] is None else ("PASS" if rec["pass"] else "FAIL"),
            })
    print(f"CSV saved: {path}")


# ── Histogram plot ─────────────────────────────────────────────────────────────

def plot_histogram(results: list[dict], mode: str, out_path: str):
    """Bar chart: one bar per position (value on y-axis)."""
    unit   = MODE_INFO[mode]["unit"]
    valid  = [r for r in results if not r["open"]]
    if not valid:
        print("No valid readings — skipping plot.")
        return

    positions = [r["pos"] for r in valid]
    labels    = [r["label"] for r in valid]
    values    = [r["value"] for r in valid]

    fig, ax = plt.subplots(figsize=(max(8, len(valid) * 0.9), 5))
    colors = []
    for r in valid:
        if r["pass"] is False:
            colors.append("#d62728")   # red — FAIL
        elif r["pass"] is True:
            colors.append("#2ca02c")   # green — PASS
        else:
            colors.append("#1f77b4")   # blue — no nominal set

    bars = ax.bar(range(len(valid)), values, color=colors)
    ax.set_xticks(range(len(valid)))
    ax.set_xticklabels([f"{p}\n{l}" for p, l in zip(positions, labels)], fontsize=9)
    ax.set_ylabel(f"Measured value ({unit})")
    ax.set_title(f"Multi-DUT {MODE_INFO[mode]['label']} — {len(valid)} positions")
    ax.grid(axis="y", linestyle="--", alpha=0.5)

    # Annotate bars with formatted value
    for bar, r in zip(bars, valid):
        ax.text(bar.get_x() + bar.get_width() / 2,
                bar.get_height() * 1.01,
                format_value(r["value"], unit),
                ha="center", va="bottom", fontsize=7, rotation=45)

    plt.tight_layout()
    plt.savefig(out_path, dpi=150)
    print(f"Plot saved: {out_path}")


# ── Argument parsing ──────────────────────────────────────────────────────────

def parse_positions(s: str) -> list[int]:
    """Parse comma-separated relay positions: '0,1,2,3' → [0, 1, 2, 3]."""
    try:
        return [int(x.strip()) for x in s.split(",")]
    except ValueError:
        raise argparse.ArgumentTypeError(
            f"Invalid positions '{s}' — expected comma-separated integers"
        )


def hex_int(s: str) -> int:
    return int(s, 0)


def main():
    ap = argparse.ArgumentParser(
        description="Multi-DUT sequential component tester (XL9535 relay + SDM3045X DMM)"
    )
    ap.add_argument("--mode", required=True,
                    choices=["res", "res4w", "cap", "diode", "ping"],
                    help="Measurement mode")
    ap.add_argument("--bp",   default=DEFAULT_BP,
                    help=f"Bus Pirate serial port (default {DEFAULT_BP})")
    ap.add_argument("--dmm",  default=DEFAULT_DMM,
                    help=f"SDM3045X IP address (default {DEFAULT_DMM})")
    ap.add_argument("--addr", type=hex_int, default=DEFAULT_I2C_ADDR,
                    metavar="ADDR",
                    help=f"XL9535 I2C address in hex (default 0x{DEFAULT_I2C_ADDR:02X})")
    ap.add_argument("--positions", type=parse_positions,
                    default=DEFAULT_POSITIONS,
                    metavar="LIST",
                    help="Comma-separated relay positions to test (default 0,1,2,3,4,5,6,7)")
    ap.add_argument("--active-high", dest="active_low", action="store_false", default=False,
                    help="Relay board active-HIGH polarity (default, ULN2803)")
    ap.add_argument("--active-low", dest="active_low", action="store_true",
                    help="Relay board active-LOW polarity")
    ap.add_argument("--delay", type=int, default=DEFAULT_DELAY_MS, metavar="MS",
                    help=f"Settle delay after relay closes in ms (default {DEFAULT_DELAY_MS})")
    ap.add_argument("--label", metavar="FILE",
                    help='JSON file mapping position to label {"0":"X1","1":"X2",...}')
    ap.add_argument("--out", metavar="CSV",
                    help="Output CSV file (default: timestamped)")
    ap.add_argument("--sort", action="store_true",
                    help="Sort summary results by measured value (ascending)")
    ap.add_argument("--nominal", type=float, metavar="VAL",
                    help="Nominal value for deviation calculation (e.g. 14074000 for crystal Hz)")
    ap.add_argument("--tolerance", type=float, default=DEFAULT_TOLERANCE, metavar="PCT",
                    help=f"Flag outside ±N%% of nominal (default {DEFAULT_TOLERANCE})")
    args = ap.parse_args()

    # ── Ping mode: no DMM ────────────────────────────────────────────────────
    if args.mode == "ping":
        run_ping(args)
        return

    # ── Measurement modes ────────────────────────────────────────────────────
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    csv_path  = args.out or f"multidut_{args.mode}_{timestamp}.csv"
    plot_path = f"multidut_{args.mode}_{timestamp}.png"

    results = run_measurement(args)

    print_summary(results, args.mode, args)
    save_csv(results, args.mode, csv_path)

    if MODE_INFO[args.mode]["plot"]:
        plot_histogram(results, args.mode, plot_path)


if __name__ == "__main__":
    main()
