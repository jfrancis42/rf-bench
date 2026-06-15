#!/usr/bin/env python3
"""
IV Tracer — Siglent SPD3303X + SDM3045X

Traces I-V curves for diodes, Zeners, LEDs, BJTs (family of curves), and MOSFETs.

Physical connections:
  Diode/Zener/LED:
    SPD CH1 (+) → device anode
    SPD CH1 (−) → device cathode (common ground)
    SPD built-in current sense used for I (accurate to ~1 mA)
    Optional: SDM in series for µA-range leakage (--use-dmm)

  BJT (NPN, common-emitter family):
    SPD CH1 (+/−) → collector/emitter (V_CE sweep)
    SPD CH2 (+) → base via R_base (V_B = I_B_target × R_base)
    Common emitter GND shared between CH1− and CH2−
    I_C from CH1 current readback; I_B = (V_CH2 − V_BE_est) / R_base

  MOSFET (N-channel, common-source family):
    SPD CH1 (+/−) → drain/source (V_DS sweep)
    SPD CH2 (+) → gate (V_GS step; I_G ≈ 0)
    Common source GND shared between CH1− and CH2−
    I_D from CH1 current readback

Usage:
  python iv_tracer.py                            # diode, default sweep
  python iv_tracer.py --device zener             # Zener, 0–5.1 V
  python iv_tracer.py --device led               # LED, 0–3.5 V with 20 mV steps
  python iv_tracer.py --device bjt --r-base 1000 # BJT family
  python iv_tracer.py --device mosfet            # MOSFET family
  python iv_tracer.py --dry-run                  # print voltage sequence, do not apply
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

from rf_bench.siglent import SPD3303X, SDM3000X                            # noqa: E402
from rf_bench import connect

# ---------------------------------------------------------------------------
# Defaults
# ---------------------------------------------------------------------------

DEFAULT_SPD_HOST  = None  # Now uses inventory
DEFAULT_DMM_HOST  = None  # Now uses inventory

# Per-device default sweep limits
DEVICE_DEFAULTS = {
    "diode":  {"v_stop": 1.5,  "v_step": 0.02},
    "zener":  {"v_stop": 5.1,  "v_step": 0.05},
    "led":    {"v_stop": 3.5,  "v_step": 0.02},
    "bjt":    {"v_stop": 10.0, "v_step": 0.1},
    "mosfet": {"v_stop": 10.0, "v_step": 0.1},
}

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _vf_at_current(voltages: list[float], currents: list[float],
                   target_ma: float) -> float | None:
    """Return interpolated forward voltage at target_ma milliamps (or None)."""
    target_a = target_ma / 1000.0
    for i in range(len(currents) - 1):
        if currents[i] <= target_a <= currents[i + 1]:
            if currents[i + 1] == currents[i]:
                return voltages[i]
            frac = (target_a - currents[i]) / (currents[i + 1] - currents[i])
            return voltages[i] + frac * (voltages[i + 1] - voltages[i])
    return None


def _hfe(v_ce_arr: np.ndarray, i_c_arr: np.ndarray, i_b: float,
         v_ce_eval: float = 5.0) -> float | None:
    """Return hFE = I_C / I_B at v_ce_eval (interpolated)."""
    if i_b <= 0:
        return None
    if len(v_ce_arr) < 2:
        return None
    i_c = float(np.interp(v_ce_eval, v_ce_arr, i_c_arr))
    if i_c <= 0:
        return None
    return i_c / i_b


# ---------------------------------------------------------------------------
# Diode / Zener / LED sweep
# ---------------------------------------------------------------------------

def run_diode_sweep(psu: SPD3303X, dmm: SDM3000X | None, args) -> dict:
    """Sweep V on CH1, measure I.  Returns {'voltages', 'currents'}."""
    v_start   = args.v_start
    v_stop    = args.v_stop
    v_step    = args.v_step
    i_limit   = args.i_limit
    settle_s  = args.settle_ms / 1000.0
    use_dmm   = (dmm is not None and args.use_dmm)

    voltages: list[float] = []
    currents: list[float] = []

    n_steps = max(1, round((v_stop - v_start) / v_step) + 1)
    v_points = [v_start + i * v_step for i in range(n_steps)]
    if v_points[-1] < v_stop - 1e-9:
        v_points.append(v_stop)

    if args.dry_run:
        print(f"[DRY RUN] Diode sweep: {len(v_points)} steps from "
              f"{v_start:.3f} V to {v_stop:.3f} V, step {v_step:.3f} V")
        for v in v_points:
            print(f"  V_set={v:.3f} V")
        return {"voltages": [], "currents": []}

    print(f"\n[SWEEP] {args.device.upper()}  {v_start:.3f}–{v_stop:.3f} V  "
          f"step={v_step:.3f} V  I_limit={i_limit*1000:.0f} mA")
    print(f"{'V_set':>8}  {'V_meas':>8}  {'I_meas':>10}  {'Mode':>4}")
    print("-" * 38)

    psu.set_voltage(1, v_start)
    psu.set_current(1, i_limit)
    psu.enable(1)
    cc_hit = False

    try:
        for v_set in v_points:
            psu.set_voltage(1, v_set)
            time.sleep(settle_s)

            v_meas = psu.measure_voltage(1)
            if use_dmm:
                i_meas = dmm.measure_idc()
            else:
                i_meas = psu.measure_current(1)
            mode = psu.get_mode(1)

            voltages.append(v_meas)
            currents.append(i_meas)

            print(f"{v_set:>8.3f}  {v_meas:>8.3f}  {i_meas*1000:>8.3f} mA  {mode:>4}")

            if mode == 'CC':
                if not cc_hit:
                    print(f"  [!] Current limit reached at {v_set:.3f} V — "
                          "holding current, not increasing voltage further.")
                    cc_hit = True
                # Safety: stop incrementing if CC was hit on two consecutive points
                # (The loop continues to record the point but we break to protect device)
                break

    finally:
        psu.disable(1)

    return {"voltages": voltages, "currents": currents}


# ---------------------------------------------------------------------------
# BJT family of curves
# ---------------------------------------------------------------------------

def run_bjt_sweep(psu: SPD3303X, args) -> list[dict]:
    """Sweep V_CE for multiple I_B steps.  Returns list of curve dicts."""
    v_stop        = args.v_stop
    v_step        = args.v_step
    v_start       = args.v_start
    i_limit       = args.i_limit
    settle_s      = args.settle_ms / 1000.0
    n_curves      = args.n_curves
    r_base        = args.r_base
    max_ib_ma     = args.base_current_ma

    # Build I_B steps (µA to max_ib_ma)
    if n_curves <= 1:
        ib_steps_ma = [max_ib_ma]
    else:
        ib_steps_ma = [max_ib_ma * i / (n_curves - 1) for i in range(n_curves)]

    n_vce = max(1, round((v_stop - v_start) / v_step) + 1)
    vce_points = [v_start + i * v_step for i in range(n_vce)]
    if vce_points[-1] < v_stop - 1e-9:
        vce_points.append(v_stop)

    if args.dry_run:
        print(f"[DRY RUN] BJT family: {n_curves} curves, "
              f"I_B from 0 to {max_ib_ma:.1f} mA, "
              f"V_CE from {v_start:.2f} to {v_stop:.2f} V")
        for ib_ma in ib_steps_ma:
            v_base = (ib_ma / 1000.0) * r_base
            print(f"  I_B={ib_ma:.2f} mA  V_CH2={v_base:.3f} V")
        return []

    curves: list[dict] = []

    print(f"\n[SWEEP] BJT family  I_B=0–{max_ib_ma:.1f} mA  "
          f"V_CE={v_start:.2f}–{v_stop:.2f} V  R_base={r_base:.0f} Ω")

    psu.set_voltage(1, v_start)
    psu.set_current(1, i_limit)
    psu.set_voltage(2, 0.0)
    psu.set_current(2, max_ib_ma / 1000.0 * 1.5)  # headroom
    psu.enable(1)
    psu.enable(2)

    try:
        for ib_ma in ib_steps_ma:
            v_base_set = (ib_ma / 1000.0) * r_base
            psu.set_voltage(2, v_base_set)
            time.sleep(0.1)  # allow base to settle

            vce_list: list[float] = []
            ic_list:  list[float] = []

            print(f"\n  I_B≈{ib_ma:.2f} mA  (V_CH2={v_base_set:.3f} V)")
            print(f"  {'V_CE':>8}  {'I_C':>10}  {'Mode':>4}")
            print("  " + "-" * 28)

            for v_set in vce_points:
                psu.set_voltage(1, v_set)
                time.sleep(settle_s)

                vce_meas = psu.measure_voltage(1)
                ic_meas  = psu.measure_current(1)
                mode     = psu.get_mode(1)

                vce_list.append(vce_meas)
                ic_list.append(ic_meas)

                print(f"  {v_set:>8.3f}  {ic_meas*1000:>8.3f} mA  {mode:>4}")

                if mode == 'CC':
                    print(f"  [!] I_C limit at V_CE={v_set:.3f} V — stopping this curve.")
                    break

            # Estimate actual I_B from CH2
            v_ch2_actual = psu.measure_voltage(2)
            v_be_est     = 0.65  # rough estimate; user can adjust R_base to get desired I_B
            i_b_actual   = max(0.0, (v_ch2_actual - v_be_est) / r_base)

            curves.append({
                "ib_ma_set":  ib_ma,
                "ib_actual":  i_b_actual,
                "vce":        vce_list,
                "ic":         ic_list,
            })

        psu.set_voltage(2, 0.0)  # turn off base drive

    finally:
        psu.disable(1)
        psu.disable(2)

    return curves


# ---------------------------------------------------------------------------
# MOSFET family of curves
# ---------------------------------------------------------------------------

def run_mosfet_sweep(psu: SPD3303X, args) -> list[dict]:
    """Sweep V_DS for multiple V_GS steps.  Returns list of curve dicts."""
    v_stop    = args.v_stop
    v_step    = args.v_step
    v_start   = args.v_start
    i_limit   = args.i_limit
    settle_s  = args.settle_ms / 1000.0
    n_curves  = args.n_curves

    # V_GS steps: from 0 to v_stop in n_curves steps
    vgs_stop = v_stop
    if n_curves <= 1:
        vgs_steps = [vgs_stop]
    else:
        vgs_steps = [vgs_stop * i / (n_curves - 1) for i in range(n_curves)]

    n_vds = max(1, round((v_stop - v_start) / v_step) + 1)
    vds_points = [v_start + i * v_step for i in range(n_vds)]
    if vds_points[-1] < v_stop - 1e-9:
        vds_points.append(v_stop)

    if args.dry_run:
        print(f"[DRY RUN] MOSFET family: {n_curves} curves, "
              f"V_GS from 0 to {vgs_stop:.2f} V, "
              f"V_DS from {v_start:.2f} to {v_stop:.2f} V")
        for vgs in vgs_steps:
            print(f"  V_GS={vgs:.3f} V")
        return []

    curves: list[dict] = []

    print(f"\n[SWEEP] MOSFET family  V_GS=0–{vgs_stop:.2f} V  "
          f"V_DS={v_start:.2f}–{v_stop:.2f} V")

    psu.set_voltage(1, v_start)
    psu.set_current(1, i_limit)
    psu.set_voltage(2, 0.0)
    psu.set_current(2, 0.01)  # gate draws negligible current; small headroom
    psu.enable(1)
    psu.enable(2)

    try:
        for vgs in vgs_steps:
            psu.set_voltage(2, vgs)
            time.sleep(0.1)

            vds_list: list[float] = []
            id_list:  list[float] = []

            print(f"\n  V_GS={vgs:.3f} V")
            print(f"  {'V_DS':>8}  {'I_D':>10}  {'Mode':>4}")
            print("  " + "-" * 28)

            for v_set in vds_points:
                psu.set_voltage(1, v_set)
                time.sleep(settle_s)

                vds_meas = psu.measure_voltage(1)
                id_meas  = psu.measure_current(1)
                mode     = psu.get_mode(1)

                vds_list.append(vds_meas)
                id_list.append(id_meas)

                print(f"  {v_set:>8.3f}  {id_meas*1000:>8.3f} mA  {mode:>4}")

                if mode == 'CC':
                    print(f"  [!] I_D limit at V_DS={v_set:.3f} V — stopping this curve.")
                    break

            curves.append({
                "vgs":  vgs,
                "vds":  vds_list,
                "id":   id_list,
            })

        psu.set_voltage(2, 0.0)

    finally:
        psu.disable(1)
        psu.disable(2)

    return curves


# ---------------------------------------------------------------------------
# Output: CSV
# ---------------------------------------------------------------------------

def save_csv_diode(voltages: list[float], currents: list[float],
                   output_prefix: str) -> str:
    path = f"{output_prefix}_iv.csv"
    with open(path, "w", newline="") as f:
        w = csv_module.writer(f)
        w.writerow(["voltage_v", "current_a", "current_ma"])
        for v, i in zip(voltages, currents):
            w.writerow([f"{v:.6f}", f"{i:.9f}", f"{i*1000:.6f}"])
    return path


def save_csv_bjt(curves: list[dict], output_prefix: str) -> str:
    path = f"{output_prefix}_iv.csv"
    with open(path, "w", newline="") as f:
        w = csv_module.writer(f)
        w.writerow(["ib_ma_set", "ib_actual_ma", "v_ce_v", "i_c_a", "i_c_ma"])
        for c in curves:
            for vce, ic in zip(c["vce"], c["ic"]):
                w.writerow([f"{c['ib_ma_set']:.4f}", f"{c['ib_actual']*1000:.4f}",
                             f"{vce:.6f}", f"{ic:.9f}", f"{ic*1000:.6f}"])
    return path


def save_csv_mosfet(curves: list[dict], output_prefix: str) -> str:
    path = f"{output_prefix}_iv.csv"
    with open(path, "w", newline="") as f:
        w = csv_module.writer(f)
        w.writerow(["v_gs_v", "v_ds_v", "i_d_a", "i_d_ma"])
        for c in curves:
            for vds, id_ in zip(c["vds"], c["id"]):
                w.writerow([f"{c['vgs']:.4f}", f"{vds:.6f}",
                             f"{id_:.9f}", f"{id_*1000:.6f}"])
    return path


# ---------------------------------------------------------------------------
# Output: text summary
# ---------------------------------------------------------------------------

def save_txt_diode(voltages: list[float], currents: list[float],
                   device: str, output_prefix: str) -> str:
    path = f"{output_prefix}_iv.txt"
    ts   = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    sep  = "=" * 60
    lines = [
        sep,
        f"  I-V TRACE SUMMARY  —  {device.upper()}",
        f"  Generated: {ts}",
        sep, "",
        f"  Points measured: {len(voltages)}",
    ]
    if voltages:
        lines.append(f"  V range:  {min(voltages):.4f} – {max(voltages):.4f} V")
        lines.append(f"  I range:  {min(currents)*1000:.4f} – {max(currents)*1000:.4f} mA")

    # V_f at standard currents
    lines.append("")
    lines.append("  Forward voltage at standard currents:")
    for target_ma in (1, 5, 10, 20, 50, 100):
        vf = _vf_at_current(voltages, currents, target_ma)
        if vf is not None:
            lines.append(f"    V_f @ {target_ma:3d} mA = {vf:.4f} V")
        else:
            lines.append(f"    V_f @ {target_ma:3d} mA = N/A (not reached)")

    text = "\n".join(lines) + "\n"
    with open(path, "w") as fh:
        fh.write(text)
    return path


def save_txt_bjt(curves: list[dict], r_base: float, output_prefix: str) -> str:
    path = f"{output_prefix}_iv.txt"
    ts   = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    sep  = "=" * 60
    lines = [
        sep,
        "  I-V TRACE SUMMARY  —  BJT (NPN, Common Emitter)",
        f"  Generated: {ts}",
        f"  R_base = {r_base:.0f} Ω",
        sep, "",
        "  hFE (β) at V_CE = 5 V:",
    ]
    for c in curves:
        if not c["vce"]:
            continue
        vce_arr = np.array(c["vce"])
        ic_arr  = np.array(c["ic"])
        hfe = _hfe(vce_arr, ic_arr, c["ib_actual"])
        if hfe is not None:
            lines.append(f"    I_B={c['ib_actual']*1000:6.2f} mA → hFE = {hfe:.1f}")
        else:
            lines.append(f"    I_B={c['ib_actual']*1000:6.2f} mA → hFE = N/A")

    text = "\n".join(lines) + "\n"
    with open(path, "w") as fh:
        fh.write(text)
    return path


def save_txt_mosfet(curves: list[dict], output_prefix: str) -> str:
    path = f"{output_prefix}_iv.txt"
    ts   = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    sep  = "=" * 60
    lines = [
        sep,
        "  I-V TRACE SUMMARY  —  MOSFET (N-channel, Common Source)",
        f"  Generated: {ts}",
        sep, "",
        "  Peak drain current per V_GS step:",
    ]
    for c in curves:
        if not c["id"]:
            continue
        id_max = max(c["id"])
        lines.append(f"    V_GS={c['vgs']:.3f} V → I_D_max={id_max*1000:.2f} mA")

    text = "\n".join(lines) + "\n"
    with open(path, "w") as fh:
        fh.write(text)
    return path


# ---------------------------------------------------------------------------
# Output: plots
# ---------------------------------------------------------------------------

def plot_diode(voltages: list[float], currents: list[float],
               device: str, output_prefix: str) -> str:
    fig, ax = plt.subplots(figsize=(8, 5))
    ax.plot(voltages, [i * 1000 for i in currents],
            color="#1f77b4", linewidth=1.8, label=device.upper())

    # Mark V_f at 10 mA and 20 mA
    for target_ma, color in ((10, "green"), (20, "darkorange")):
        vf = _vf_at_current(voltages, currents, target_ma)
        if vf is not None:
            ax.axhline(target_ma, color=color, linestyle="--", linewidth=0.9,
                       alpha=0.7, label=f"V_f@{target_ma}mA={vf:.3f}V")
            ax.axvline(vf, color=color, linestyle="--", linewidth=0.9, alpha=0.7)

    ax.set_xlabel("Voltage (V)")
    ax.set_ylabel("Current (mA)")
    ax.set_title(f"I-V Curve — {device.upper()}  "
                 f"({datetime.now().strftime('%Y-%m-%d %H:%M')})")
    ax.set_xlim(left=0)
    ax.set_ylim(bottom=0)
    ax.grid(True, alpha=0.35)
    ax.legend(fontsize=9)

    plt.tight_layout()
    path = f"{output_prefix}_iv.png"
    plt.savefig(path, dpi=150, bbox_inches="tight")
    plt.close(fig)
    return path


def plot_bjt(curves: list[dict], output_prefix: str) -> str:
    fig, ax = plt.subplots(figsize=(9, 6))
    cmap = plt.cm.viridis
    colors = [cmap(i / max(len(curves) - 1, 1)) for i in range(len(curves))]

    for c, col in zip(curves, colors):
        if not c["vce"]:
            continue
        label = f"I_B={c['ib_actual']*1000:.2f} mA"
        ax.plot(c["vce"], [i * 1000 for i in c["ic"]],
                color=col, linewidth=1.5, label=label)

    ax.set_xlabel("V_CE (V)")
    ax.set_ylabel("I_C (mA)")
    ax.set_title(f"BJT I_C vs V_CE Family  "
                 f"({datetime.now().strftime('%Y-%m-%d %H:%M')})")
    ax.set_xlim(left=0)
    ax.set_ylim(bottom=0)
    ax.grid(True, alpha=0.35)
    ax.legend(fontsize=8, loc="lower right")

    plt.tight_layout()
    path = f"{output_prefix}_iv.png"
    plt.savefig(path, dpi=150, bbox_inches="tight")
    plt.close(fig)
    return path


def plot_mosfet(curves: list[dict], output_prefix: str) -> str:
    fig, ax = plt.subplots(figsize=(9, 6))
    cmap = plt.cm.plasma
    colors = [cmap(i / max(len(curves) - 1, 1)) for i in range(len(curves))]

    for c, col in zip(curves, colors):
        if not c["vds"]:
            continue
        label = f"V_GS={c['vgs']:.2f} V"
        ax.plot(c["vds"], [i * 1000 for i in c["id"]],
                color=col, linewidth=1.5, label=label)

    ax.set_xlabel("V_DS (V)")
    ax.set_ylabel("I_D (mA)")
    ax.set_title(f"MOSFET I_D vs V_DS Family  "
                 f"({datetime.now().strftime('%Y-%m-%d %H:%M')})")
    ax.set_xlim(left=0)
    ax.set_ylim(bottom=0)
    ax.grid(True, alpha=0.35)
    ax.legend(fontsize=8, loc="lower right")

    plt.tight_layout()
    path = f"{output_prefix}_iv.png"
    plt.savefig(path, dpi=150, bbox_inches="tight")
    plt.close(fig)
    return path


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="I-V Curve Tracer — Siglent SPD3303X + SDM3045X",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Device modes:
  diode   — standard diode I-V, CH1 sweep 0–1.5 V
  zener   — Zener / TVS diode, CH1 sweep 0–5.1 V  (reverse: swap leads)
  led     — LED, CH1 sweep 0–3.5 V  (adjust --v-stop for blue/UV LEDs)
  bjt     — BJT NPN family of curves; CH1=V_CE, CH2=base via R_base
  mosfet  — N-channel MOSFET family; CH1=V_DS, CH2=V_GS

Safety:
  --i-limit is a hard current limit on CH1. If CC mode is detected the sweep
  stops immediately at that point to protect the device.

  --dry-run prints the voltage sequence without connecting to instruments.

Examples:
  python iv_tracer.py --device led --v-stop 3.2
  python iv_tracer.py --device zener --v-stop 6.0 --i-limit 0.05
  python iv_tracer.py --device bjt --r-base 4700 --base-current-ma 1
  python iv_tracer.py --device mosfet --n-curves 6 --v-stop 8.0
  python iv_tracer.py --dry-run --device bjt
""",
    )

    parser.add_argument("--device", choices=["diode", "zener", "led", "bjt", "mosfet"],
                        default="diode",
                        help="Device type (default: diode)")
    parser.add_argument("--v-start", type=float, default=0.0,
                        help="Sweep start voltage (default: 0)")
    parser.add_argument("--v-stop",  type=float, default=None,
                        help="Sweep stop voltage (default: device-dependent)")
    parser.add_argument("--v-step",  type=float, default=None,
                        help="Voltage step size (default: device-dependent)")
    parser.add_argument("--i-limit", type=float, default=0.1,
                        help="Current limit on CH1 in amps (default: 0.1 A = 100 mA)")
    parser.add_argument("--base-current-ma", type=float, default=10.0,
                        help="BJT: maximum base current in mA (default: 10)")
    parser.add_argument("--n-curves", type=int, default=5,
                        help="BJT/MOSFET: number of curves in family (default: 5)")
    parser.add_argument("--r-base", type=float, default=1000.0,
                        help="BJT: base series resistor in ohms (default: 1000)")
    parser.add_argument("--settle-ms", type=float, default=100.0,
                        help="Settle time per step in milliseconds (default: 100)")
    parser.add_argument("--spd-host", default=DEFAULT_SPD_HOST,
                        help=f"SPD3303X IP address (default: {DEFAULT_SPD_HOST})")
    parser.add_argument("--dmm-host", default=DEFAULT_DMM_HOST,
                        help=f"SDM3045X IP address (default: {DEFAULT_DMM_HOST})")
    parser.add_argument("--use-dmm",  action="store_true",
                        help="Use DMM for current measurement instead of SPD sense "
                             "(higher accuracy at µA levels; requires series connection)")
    parser.add_argument("--output", default=None,
                        help="Output filename prefix (default: timestamped)")
    parser.add_argument("--dry-run", action="store_true",
                        help="Print voltage sequence without applying to instruments")

    args = parser.parse_args()

    # Apply device-dependent defaults
    dev = args.device
    if args.v_stop is None:
        args.v_stop = DEVICE_DEFAULTS[dev]["v_stop"]
    if args.v_step is None:
        args.v_step = DEVICE_DEFAULTS[dev]["v_step"]

    if args.output is None:
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        args.output = f"iv_{dev}_{ts}"

    print(f"IV Tracer — {dev.upper()}")
    print(f"  Output prefix : {args.output}")
    print(f"  V sweep       : {args.v_start:.3f} – {args.v_stop:.3f} V, step {args.v_step:.3f} V")
    print(f"  I limit (CH1) : {args.i_limit*1000:.0f} mA")
    if dev == "bjt":
        print(f"  R_base        : {args.r_base:.0f} Ω")
        print(f"  Max I_B       : {args.base_current_ma:.1f} mA")
        print(f"  N curves      : {args.n_curves}")
    elif dev == "mosfet":
        print(f"  N curves      : {args.n_curves}")

    if args.dry_run:
        # Dry run — no instruments needed
        if dev in ("diode", "zener", "led"):
            run_diode_sweep(None, None, args)
        elif dev == "bjt":
            run_bjt_sweep(None, args)
        else:
            run_mosfet_sweep(None, args)
        return

    # Connect instruments
    psu: SPD3303X | None = None
    dmm: SDM3000X | None = None

    try:
        print(f"\nConnecting to SPD3303X via inventory'} ...", end=" ", flush=True)
        psu = connect(args.spd_host or 'spd')
        print(f"OK  ({psu.identify().strip()})")

        if args.use_dmm:
            print(f"Connecting to SDM3045X via inventory'} ...", end=" ", flush=True)
            dmm = connect(args.dmm_host or 'sdm')
            print(f"OK  ({dmm.identify().strip()})")
            dmm.configure_idc()

        # Safety: ensure all channels are off at start
        psu.disable_all()

        # Run sweep
        if dev in ("diode", "zener", "led"):
            result = run_diode_sweep(psu, dmm, args)
            voltages = result["voltages"]
            currents = result["currents"]

            if not voltages:
                print("No data collected.")
                return

            csv_path = save_csv_diode(voltages, currents, args.output)
            txt_path = save_txt_diode(voltages, currents, dev, args.output)
            png_path = plot_diode(voltages, currents, dev, args.output)

        elif dev == "bjt":
            curves = run_bjt_sweep(psu, args)
            if not curves:
                print("No data collected.")
                return

            csv_path = save_csv_bjt(curves, args.output)
            txt_path = save_txt_bjt(curves, args.r_base, args.output)
            png_path = plot_bjt(curves, args.output)

        else:  # mosfet
            curves = run_mosfet_sweep(psu, args)
            if not curves:
                print("No data collected.")
                return

            csv_path = save_csv_mosfet(curves, args.output)
            txt_path = save_txt_mosfet(curves, args.output)
            png_path = plot_mosfet(curves, args.output)

        print(f"\n[RESULTS]")
        print(f"  Plot   → {png_path}")
        print(f"  CSV    → {csv_path}")
        print(f"  Report → {txt_path}")
        print()
        with open(txt_path) as fh:
            print(fh.read())

    except KeyboardInterrupt:
        print("\nInterrupted by user — disabling all outputs.")
        if psu is not None:
            try:
                psu.disable_all()
            except Exception:
                pass
        sys.exit(0)
    except ConnectionRefusedError as exc:
        print(f"\nCannot connect: {exc}")
        print("Check that the instrument is powered on and SCPI/LAN is enabled.")
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
        if psu is not None:
            try:
                psu.disable_all()
                psu.close()
            except Exception:
                pass
        if dmm is not None:
            try:
                dmm.close()
            except Exception:
                pass


if __name__ == "__main__":
    main()
