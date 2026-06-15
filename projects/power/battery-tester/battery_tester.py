#!/usr/bin/env python3
"""
Battery Tester — ET5406A+ DC Load + SDM3045X + SPD3303X

Measures battery capacity (mAh), internal resistance, and supports multi-cycle
charge/discharge testing to track capacity fade.

Physical connections:
  Battery terminals → ET5406A+ load input (large banana terminals)
  Battery terminals → SDM3045X (Voltage Sense, Hi/Lo; 4-wire if possible)
  SPD3303X CH1 (optional) → Battery terminals for CC-CV charging (cycle mode)

NOTE: ET5406A+ must be connected via USB (/dev/ttyUSB0).  Hardware not currently
bench-tested.

Usage:
  python battery_tester.py                              # capacity measurement
  python battery_tester.py --mode internal-resistance  # pulse method IR test
  python battery_tester.py --mode cycle --cycles 3     # 3 charge/discharge cycles
  python battery_tester.py --mode capacity --discharge-current 2.0 --cutoff-voltage 3.0
"""

import argparse
import csv as csv_module
import os
import sys
import time
from datetime import datetime

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np

# ---------------------------------------------------------------------------
# Shared drivers
# ---------------------------------------------------------------------------

from rf_bench.siglent import SDM3000X, SPD3303X                            # noqa: E402

# ---------------------------------------------------------------------------
# ET5406A+ load
# ---------------------------------------------------------------------------

from rf_bench.yertai import ET5406A, ET5406AError
from rf_bench import connect

# ---------------------------------------------------------------------------
# Defaults
# ---------------------------------------------------------------------------

DEFAULT_DMM_HOST  = None  # Now uses inventory
DEFAULT_SPD_HOST  = None  # Now uses inventory
DEFAULT_LOAD_PORT = "/dev/ttyUSB0"

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _mah_trapezoid(times_s: list[float], currents_a: list[float]) -> float:
    """Integrate current over time using the trapezoidal rule.  Returns mAh."""
    if len(times_s) < 2:
        return 0.0
    mah = 0.0
    for i in range(len(times_s) - 1):
        dt_h   = (times_s[i + 1] - times_s[i]) / 3600.0
        i_avg  = (currents_a[i] + currents_a[i + 1]) / 2.0
        mah   += i_avg * 1000.0 * dt_h
    return mah


def _connect_load(port: str):
    """Connect to ET5406A+ load.  Returns load object or raises RuntimeError."""
    try:
        return ET5406A(port)
    except ET5406AError as exc:
        raise RuntimeError(f"Cannot connect to ET5406A+ on {port}: {exc}") from exc


def _safe_load_off(load) -> None:
    """Disable load output, ignoring errors (used in finally blocks)."""
    if load is None:
        return
    try:
        load.off()
    except Exception:
        pass


def _safe_psu_off(psu) -> None:
    """Disable all PSU channels, ignoring errors."""
    if psu is None:
        return
    try:
        psu.disable_all()
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Capacity measurement
# ---------------------------------------------------------------------------

def run_capacity(load, dmm: SDM3000X, args) -> dict:
    """
    Discharge battery at constant current until cutoff voltage or max time.
    Returns summary dict.
    """
    discharge_a   = args.discharge_current
    cutoff_v      = args.cutoff_voltage
    max_s         = args.max_time_min * 60.0
    interval_s    = args.log_interval_s

    print(f"\n[CAPACITY]  I={discharge_a:.3f} A  cutoff={cutoff_v:.3f} V  "
          f"max={args.max_time_min:.0f} min  interval={interval_s:.0f} s")

    # Setup load: constant current
    load.mode = "CC"
    load.CC_current = discharge_a
    load.off()

    # Measure open-circuit voltage first
    time.sleep(0.5)
    v_ocv = dmm.measure_vdc()
    print(f"  OCV before discharge: {v_ocv:.4f} V")
    if v_ocv < cutoff_v:
        print(f"  ERROR: Battery voltage ({v_ocv:.3f} V) is already below cutoff ({cutoff_v:.3f} V).")
        print("         Connect a charged battery and retry.")
        return {}

    # Start discharge
    load.on()
    t_start = time.time()

    timestamps:  list[float] = [0.0]
    voltages:    list[float] = [v_ocv]
    currents:    list[float] = [0.0]
    mah_cumul:   list[float] = [0.0]

    print(f"\n  {'Time':>8}  {'Voltage':>9}  {'Current':>9}  {'mAh':>8}")
    print("  " + "-" * 42)

    try:
        while True:
            time.sleep(interval_s)
            t_now = time.time() - t_start
            v_now = dmm.measure_vdc()
            # Use set current as actual (ET54 CC is accurate; SPD not in loop)
            i_now = discharge_a

            timestamps.append(t_now)
            voltages.append(v_now)
            currents.append(i_now)

            # Trapezoidal integration up to this point
            mah = _mah_trapezoid(timestamps, currents)
            mah_cumul.append(mah)

            print(f"  {t_now/60:>7.2f}m  {v_now:>8.4f}V  {i_now:>7.3f}A  {mah:>8.2f}")

            if v_now < cutoff_v:
                print(f"  Cutoff voltage {cutoff_v:.3f} V reached — stopping discharge.")
                break
            if t_now >= max_s:
                print(f"  Maximum time {args.max_time_min:.0f} min reached — stopping discharge.")
                break

    finally:
        load.off()

    v_final  = voltages[-1]
    duration = timestamps[-1]
    capacity = mah_cumul[-1]
    avg_v    = float(np.mean(voltages[1:])) if len(voltages) > 1 else v_ocv

    print(f"\n  Capacity:         {capacity:.2f} mAh")
    print(f"  Average voltage:  {avg_v:.4f} V")
    print(f"  Duration:         {duration/60:.2f} min")

    return {
        "timestamps":  timestamps,
        "voltages":    voltages,
        "currents":    currents,
        "mah_cumul":   mah_cumul,
        "capacity_mah": capacity,
        "avg_v":        avg_v,
        "v_ocv":        v_ocv,
        "v_final":      v_final,
        "duration_s":   duration,
    }


# ---------------------------------------------------------------------------
# Internal resistance (pulse method)
# ---------------------------------------------------------------------------

def run_internal_resistance(load, dmm: SDM3000X, args) -> dict:
    """
    Measure internal resistance via DC pulse load step.
    Returns summary dict with R_int in mΩ.
    """
    i1 = args.ir_current1
    i2 = args.ir_current2

    print(f"\n[INTERNAL RESISTANCE]  I1={i1:.3f} A  I2={i2:.3f} A")

    load.mode = "CC"

    # Open circuit voltage
    load.off()
    time.sleep(1.0)
    v_oc = dmm.measure_vdc()
    print(f"  V_OC  (no load):       {v_oc:.6f} V")

    # Low current step
    load.CC_current = i1
    load.on()
    time.sleep(1.0)
    v1 = dmm.measure_vdc()
    print(f"  V1 @ I1={i1:.3f} A:   {v1:.6f} V")

    # High current step
    load.CC_current = i2
    time.sleep(1.0)
    v2 = dmm.measure_vdc()
    print(f"  V2 @ I2={i2:.3f} A:   {v2:.6f} V")

    load.off()

    # R_int from pulse method
    delta_v = v1 - v2
    delta_i = i2 - i1
    if delta_i == 0:
        print("  ERROR: I1 == I2 — cannot compute R_int.")
        return {}

    r_int_ohm = delta_v / delta_i
    r_int_mohm = r_int_ohm * 1000.0

    # Simple OCV method (R = (V_OC - V2) / I2)
    r_simple_mohm = ((v_oc - v2) / i2) * 1000.0 if i2 > 0 else 0.0

    print(f"\n  R_int (pulse method):  {r_int_mohm:.2f} mΩ")
    print(f"  R_int (OCV method):    {r_simple_mohm:.2f} mΩ  (V_OC vs full load)")

    return {
        "v_oc":           v_oc,
        "v1":             v1,
        "v2":             v2,
        "i1":             i1,
        "i2":             i2,
        "r_int_mohm":     r_int_mohm,
        "r_simple_mohm":  r_simple_mohm,
    }


# ---------------------------------------------------------------------------
# Cycle mode
# ---------------------------------------------------------------------------

def run_charge_phase(psu: SPD3303X, dmm: SDM3000X,
                     charge_a: float, charge_v: float,
                     cutoff_fraction: float = 0.05,
                     max_min: float = 180.0) -> dict:
    """
    Charge battery via SPD CH1 in CC→CV mode.
    Stops when current drops to cutoff_fraction × charge_a or max_min is reached.
    Returns summary dict.
    """
    print(f"\n  [CHARGE]  CC={charge_a:.3f} A  CV={charge_v:.3f} V  "
          f"cutoff at I < {charge_a*cutoff_fraction*1000:.0f} mA")

    psu.set_voltage(1, charge_v)
    psu.set_current(1, charge_a)
    psu.enable(1)

    t_start = time.time()
    max_s   = max_min * 60.0
    mah     = 0.0
    prev_t  = 0.0
    prev_i  = charge_a

    print(f"  {'Time':>8}  {'Voltage':>9}  {'Current':>9}  {'Mode':>4}")
    print("  " + "-" * 38)

    try:
        while True:
            time.sleep(10.0)
            t_now = time.time() - t_start
            v_now = psu.measure_voltage(1)
            i_now = psu.measure_current(1)
            mode  = psu.get_mode(1)

            # Trapezoidal integration
            dt_h   = (t_now - prev_t) / 3600.0
            i_avg  = (prev_i + i_now) / 2.0
            mah   += i_avg * 1000.0 * dt_h
            prev_t = t_now
            prev_i = i_now

            print(f"  {t_now/60:>7.2f}m  {v_now:>8.4f}V  {i_now:>7.3f}A  {mode:>4}")

            cutoff_a = charge_a * cutoff_fraction
            if mode == 'CV' and i_now < cutoff_a:
                print(f"  Taper current {cutoff_a*1000:.0f} mA reached — charge complete.")
                break
            if t_now >= max_s:
                print(f"  Max charge time {max_min:.0f} min reached.")
                break
    finally:
        psu.disable(1)

    return {"duration_s": time.time() - t_start - 10, "mah_charged": mah}


def run_cycle(load, psu: SPD3303X, dmm: SDM3000X, args, cycle_num: int) -> dict:
    """Run one charge + discharge cycle.  Returns capacity dict."""
    print(f"\n{'='*50}")
    print(f"CYCLE {cycle_num}")
    print(f"{'='*50}")

    # Charge phase
    charge_result = run_charge_phase(
        psu, dmm,
        charge_a  = args.charge_current,
        charge_v  = args.charge_voltage,
        max_min   = args.max_time_min,
    )
    print(f"  Charge: {charge_result['mah_charged']:.1f} mAh  "
          f"({charge_result['duration_s']/60:.1f} min)")

    # Rest before discharge
    print("  Resting 60 s ...")
    time.sleep(60)

    # Discharge phase
    discharge_result = run_capacity(load, dmm, args)

    if not discharge_result:
        return {}
    discharge_result["cycle_num"] = cycle_num
    discharge_result["mah_charged"] = charge_result["mah_charged"]
    return discharge_result


# ---------------------------------------------------------------------------
# Output: CSV
# ---------------------------------------------------------------------------

def save_csv_capacity(data: dict, output_prefix: str) -> str:
    path = f"{output_prefix}_capacity.csv"
    with open(path, "w", newline="") as f:
        w = csv_module.writer(f)
        w.writerow(["elapsed_s", "elapsed_min", "voltage_v", "current_a", "mah_cumulative"])
        for t, v, i, mah in zip(data["timestamps"], data["voltages"],
                                 data["currents"],   data["mah_cumul"]):
            w.writerow([f"{t:.2f}", f"{t/60:.4f}", f"{v:.6f}", f"{i:.6f}", f"{mah:.4f}"])
    return path


# ---------------------------------------------------------------------------
# Output: plots
# ---------------------------------------------------------------------------

def plot_discharge(data: dict, output_prefix: str) -> str:
    times_min = [t / 60.0 for t in data["timestamps"]]

    fig, ax1 = plt.subplots(figsize=(10, 5))
    color_v = "#1f77b4"
    color_i = "#d62728"

    ax1.plot(times_min, data["voltages"], color=color_v, linewidth=1.8, label="Voltage (V)")
    ax1.set_xlabel("Time (min)")
    ax1.set_ylabel("Voltage (V)", color=color_v)
    ax1.tick_params(axis="y", labelcolor=color_v)
    ax1.axhline(data.get("cutoff_v", min(data["voltages"])),
                color=color_v, linestyle="--", linewidth=0.8, alpha=0.6,
                label=f"Cutoff {data.get('cutoff_v', 0):.2f} V")

    ax2 = ax1.twinx()
    ax2.plot(times_min, [i * 1000 for i in data["currents"]],
             color=color_i, linewidth=1.4, linestyle="--", label="Current (mA)")
    ax2.set_ylabel("Current (mA)", color=color_i)
    ax2.tick_params(axis="y", labelcolor=color_i)

    cap   = data.get("capacity_mah", 0)
    dur   = data.get("duration_s", 0)
    avg_v = data.get("avg_v", 0)
    title = (f"Discharge Curve — {cap:.1f} mAh  "
             f"({dur/60:.1f} min, avg {avg_v:.3f} V)")
    ax1.set_title(title)

    lines1, labels1 = ax1.get_legend_handles_labels()
    lines2, labels2 = ax2.get_legend_handles_labels()
    ax1.legend(lines1 + lines2, labels1 + labels2, fontsize=9, loc="upper right")
    ax1.grid(True, alpha=0.3)

    plt.tight_layout()
    path = f"{output_prefix}_discharge.png"
    plt.savefig(path, dpi=150, bbox_inches="tight")
    plt.close(fig)
    return path


def plot_cycle_fade(cycle_results: list[dict], output_prefix: str) -> str:
    cycle_nums = [c["cycle_num"] for c in cycle_results if "capacity_mah" in c]
    capacities = [c["capacity_mah"] for c in cycle_results if "capacity_mah" in c]

    fig, ax = plt.subplots(figsize=(7, 4))
    ax.plot(cycle_nums, capacities, "o-", color="#1f77b4", linewidth=1.8, markersize=7)
    ax.set_xlabel("Cycle Number")
    ax.set_ylabel("Discharge Capacity (mAh)")
    ax.set_title("Capacity vs Cycle")
    ax.grid(True, alpha=0.35)
    if capacities:
        ax.set_ylim(bottom=0, top=max(capacities) * 1.15)
    plt.tight_layout()
    path = f"{output_prefix}_cycle_fade.png"
    plt.savefig(path, dpi=150, bbox_inches="tight")
    plt.close(fig)
    return path


# ---------------------------------------------------------------------------
# Output: text summary
# ---------------------------------------------------------------------------

def save_txt_summary(data: dict, ir_data: dict | None, cycle_results: list[dict],
                     args, output_prefix: str) -> str:
    path = f"{output_prefix}_battery.txt"
    ts   = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    sep  = "=" * 60

    lines = [
        sep,
        "  BATTERY TEST SUMMARY",
        f"  Generated: {ts}",
        f"  Mode:      {args.mode}",
        sep, "",
    ]

    if data and "capacity_mah" in data:
        lines += [
            "  CAPACITY:",
            f"    Discharge current : {args.discharge_current:.3f} A",
            f"    Cutoff voltage    : {args.cutoff_voltage:.3f} V",
            f"    Capacity          : {data['capacity_mah']:.2f} mAh",
            f"    Duration          : {data['duration_s']/60:.2f} min",
            f"    Average voltage   : {data['avg_v']:.4f} V",
            f"    OCV before        : {data['v_ocv']:.4f} V",
            f"    Final voltage     : {data['v_final']:.4f} V",
            "",
        ]

    if ir_data and "r_int_mohm" in ir_data:
        lines += [
            "  INTERNAL RESISTANCE:",
            f"    Method (pulse)  : {ir_data['r_int_mohm']:.2f} mΩ",
            f"    Method (OCV)    : {ir_data['r_simple_mohm']:.2f} mΩ",
            f"    V_OC            : {ir_data['v_oc']:.4f} V",
            f"    V @ {ir_data['i1']:.2f} A       : {ir_data['v1']:.4f} V",
            f"    V @ {ir_data['i2']:.2f} A       : {ir_data['v2']:.4f} V",
            "",
        ]

    if cycle_results:
        lines.append("  CYCLE SUMMARY:")
        for c in cycle_results:
            if "capacity_mah" not in c:
                continue
            lines.append(f"    Cycle {c['cycle_num']:2d}: {c['capacity_mah']:.1f} mAh"
                         f"  ({c['duration_s']/60:.1f} min)")
        if len(cycle_results) >= 2:
            first = cycle_results[0].get("capacity_mah", 0)
            last  = cycle_results[-1].get("capacity_mah", 0)
            if first > 0:
                retention = last / first * 100.0
                lines.append(f"    Retention cycle {cycle_results[0]['cycle_num']}"
                              f"→{cycle_results[-1]['cycle_num']}: {retention:.1f}%")
        lines.append("")

    text = "\n".join(lines) + "\n"
    with open(path, "w") as fh:
        fh.write(text)
    return path


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Battery Tester — ET5406A+ DC Load + SDM3045X + SPD3303X",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Modes:
  capacity           — Constant-current discharge to cutoff voltage; reports mAh.
  internal-resistance — DC pulse method (two current levels); reports R_int in mΩ.
  cycle              — Charge (SPD CC-CV) → discharge (ET5406A+ CC) × N cycles.
                        Tracks capacity fade across cycles.

NOTE: ET5406A+ must be connected via USB (/dev/ttyUSB0).  Without it the
      load-dependent tests cannot run.

Examples:
  python battery_tester.py                          # capacity, 1 A, 3.0 V cutoff
  python battery_tester.py --mode internal-resistance
  python battery_tester.py --mode cycle --cycles 5 --charge-current 0.5 --charge-voltage 4.2
  python battery_tester.py --discharge-current 2.0 --cutoff-voltage 2.8  # 2S LiPo half-pack
""",
    )

    parser.add_argument("--mode", choices=["capacity", "internal-resistance", "cycle"],
                        default="capacity",
                        help="Test mode (default: capacity)")
    parser.add_argument("--discharge-current", type=float, default=1.0,
                        help="Discharge current in amps (default: 1.0)")
    parser.add_argument("--cutoff-voltage",    type=float, default=3.0,
                        help="Discharge cutoff voltage in volts (default: 3.0)")
    parser.add_argument("--max-time-min",      type=float, default=300.0,
                        help="Maximum test time in minutes (default: 300)")
    parser.add_argument("--log-interval-s",    type=float, default=10.0,
                        help="Logging interval in seconds (default: 10)")
    parser.add_argument("--charge-current",    type=float, default=0.5,
                        help="Cycle mode: charge current in amps (default: 0.5)")
    parser.add_argument("--charge-voltage",    type=float, default=4.2,
                        help="Cycle mode: charge CV setpoint in volts (default: 4.2)")
    parser.add_argument("--cycles",            type=int,   default=1,
                        help="Cycle mode: number of charge/discharge cycles (default: 1)")
    parser.add_argument("--ir-current1",       type=float, default=0.1,
                        help="IR test: low current step in amps (default: 0.1)")
    parser.add_argument("--ir-current2",       type=float, default=1.0,
                        help="IR test: high current step in amps (default: 1.0)")
    parser.add_argument("--load-port",         default=DEFAULT_LOAD_PORT,
                        help=f"ET5406A+ serial port (default: {DEFAULT_LOAD_PORT})")
    parser.add_argument("--dmm-host",          default=DEFAULT_DMM_HOST,
                        help=f"SDM3045X IP address (default: {DEFAULT_DMM_HOST})")
    parser.add_argument("--spd-host",          default=DEFAULT_SPD_HOST,
                        help=f"SPD3303X IP address (default: {DEFAULT_SPD_HOST})")
    parser.add_argument("--output",            default=None,
                        help="Output filename prefix (default: timestamped)")

    args = parser.parse_args()

    if args.output is None:
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        args.output = f"battery_{args.mode.replace('-','_')}_{ts}"

    print(f"Battery Tester — mode: {args.mode.upper()}")
    print(f"  Output prefix : {args.output}")

    load  = None
    psu   = None
    dmm   = None
    discharge_data: dict = {}
    ir_data:        dict = {}
    cycle_results: list[dict] = []

    try:
        # Connect DMM (always required for voltage)
        print(f"\nConnecting to SDM3045X via inventory'} ...", end=" ", flush=True)
        dmm = connect(args.dmm_host or 'sdm')
        print(f"OK  ({dmm.identify().strip()})")

        # Connect ET54 load (required for all current tests)
        print(f"Connecting to ET5406A+ via inventory'} ...", end=" ", flush=True)
        load = _connect_load(args.load_port)
        load.off()
        print("OK")

        # Connect SPD (required for cycle mode)
        if args.mode == "cycle":
            print(f"Connecting to SPD3303X via inventory'} ...", end=" ", flush=True)
            psu = connect(args.spd_host or 'spd')
            print(f"OK  ({psu.identify().strip()})")
            psu.disable_all()

        # Run selected mode
        if args.mode == "capacity":
            discharge_data = run_capacity(load, dmm, args)

        elif args.mode == "internal-resistance":
            ir_data = run_internal_resistance(load, dmm, args)
            # Also measure OCV for reference
            discharge_data = {}

        elif args.mode == "cycle":
            if psu is None:
                print("ERROR: SPD3303X connection required for cycle mode.")
                sys.exit(1)
            for cycle_num in range(1, args.cycles + 1):
                c = run_cycle(load, psu, dmm, args, cycle_num)
                if c:
                    cycle_results.append(c)
            # Use last cycle discharge data for primary plots
            if cycle_results:
                discharge_data = cycle_results[-1]

        # Save outputs
        print(f"\n[SAVING RESULTS]")

        if discharge_data and "timestamps" in discharge_data:
            csv_path = save_csv_capacity(discharge_data, args.output)
            discharge_data["cutoff_v"] = args.cutoff_voltage
            png_path = plot_discharge(discharge_data, args.output)
            print(f"  Discharge plot → {png_path}")
            print(f"  CSV data       → {csv_path}")

        if len(cycle_results) > 1:
            fade_path = plot_cycle_fade(cycle_results, args.output)
            print(f"  Cycle fade     → {fade_path}")

        txt_path = save_txt_summary(discharge_data, ir_data if ir_data else None,
                                    cycle_results, args, args.output)
        print(f"  Summary        → {txt_path}")
        print()
        with open(txt_path) as fh:
            print(fh.read())

    except RuntimeError as exc:
        print(f"\nERROR: {exc}")
        sys.exit(1)
    except KeyboardInterrupt:
        print("\nInterrupted — disabling load and PSU.")
        _safe_load_off(load)
        _safe_psu_off(psu)
        sys.exit(0)
    except ConnectionRefusedError as exc:
        print(f"\nCannot connect to instrument: {exc}")
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
        _safe_load_off(load)
        _safe_psu_off(psu)
        if dmm is not None:
            try:
                dmm.close()
            except Exception:
                pass


if __name__ == "__main__":
    main()
