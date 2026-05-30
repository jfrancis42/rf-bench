#!/usr/bin/env python3
"""
PSU Characterizer — SPD3303X + ET5406A+ + SDM3045X + SDS2504X Plus

Characterizes a power supply or voltage regulator:
  - Load regulation    : V_out vs I_load sweep
  - Efficiency         : P_out / P_in vs I_load
  - Output ripple      : Vpp at full load (scope, AC-coupled)
  - Transient response : Load step voltage deviation (scope)

The ET5406A+ programmable load is required for load-sweep tests.
Without it the script falls back to static measurements only.

Physical connections:
  DUT output (+) ──── ET5406A+ load V+
  DUT output (−) ──── ET5406A+ load V−
  DUT output (+/−) ── SDM3045X voltage sense
  DUT output (+/−) ── Scope CH1 (ripple & transient capture)

When using SPD3303X as the DUT source (pass-through variable supply):
  SPD CH1 output → DUT input (or directly as the DUT)
  Measure input power from SPD: P_in = SPD.measure_voltage(1) × SPD.measure_current(1)

Usage:
  python psu_characterizer.py                           # full test (all modes)
  python psu_characterizer.py --mode load-reg           # load regulation only
  python psu_characterizer.py --mode efficiency         # efficiency sweep
  python psu_characterizer.py --mode ripple             # ripple capture only
  python psu_characterizer.py --mode transient          # load step response
  python psu_characterizer.py --v-set 3.3 --i-max 1.5  # 3.3 V, 1.5 A max load
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

from rf_bench.siglent import SPD3303X, SDM3000X, SDS2000X                 # noqa: E402

# ---------------------------------------------------------------------------
# ET5406A+ load — optional; graceful degradation if unavailable
# ---------------------------------------------------------------------------

from rf_bench.yertai import ET5406A, ET5406AError

# ---------------------------------------------------------------------------
# Defaults
# ---------------------------------------------------------------------------

DEFAULT_SPD_HOST   = "10.1.1.56"
DEFAULT_DMM_HOST   = "10.1.1.63"
DEFAULT_SCOPE_HOST = "10.1.1.58"
DEFAULT_LOAD_PORT  = "/dev/ttyUSB0"

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _connect_load(port: str):
    """Connect to ET5406A+ load.  Returns load object or raises RuntimeError."""
    try:
        return ET5406A(port)
    except ET5406AError as exc:
        raise RuntimeError(f"Cannot connect to ET5406A+ on {port}: {exc}") from exc


def _safe_load_off(load) -> None:
    if load is None:
        return
    try:
        load.off()
    except Exception:
        pass


def _safe_psu_off(psu: SPD3303X | None) -> None:
    if psu is None:
        return
    try:
        psu.disable_all()
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Load regulation sweep
# ---------------------------------------------------------------------------

def run_load_regulation(load, psu: SPD3303X, dmm: SDM3000X, args) -> dict:
    """
    Sweep load current from i_min to i_max in i_points steps.
    Measures V_out at each step.  Returns result dict.
    """
    i_min    = args.i_min
    i_max    = args.i_max
    n_points = args.i_points
    v_set    = args.v_set
    ch       = args.spd_channel

    i_steps = np.linspace(i_min, i_max, n_points)

    print(f"\n[LOAD REGULATION]  V_set={v_set:.3f} V  "
          f"I={i_min:.3f}–{i_max:.3f} A  {n_points} points")
    print(f"  {'I_load':>8}  {'V_out':>9}  {'P_out':>8}  {'P_in':>8}  {'Reg':>6}")
    print("  " + "-" * 50)

    load_currents:  list[float] = []
    v_out_vals:     list[float] = []
    p_out_vals:     list[float] = []
    p_in_vals:      list[float] = []

    # Set PSU to v_set
    psu.set_voltage(ch, v_set)
    psu.set_current(ch, i_max * 1.1 + 0.1)  # headroom
    psu.enable(ch)

    load.mode = "CC"

    try:
        # No-load baseline
        load.CC_current = max(i_min, 0.001)
        load.on()
        time.sleep(0.5)

        v_noload = dmm.measure_vdc()

        for i_step in i_steps:
            load.CC_current = max(i_step, 0.001)
            time.sleep(0.5)  # settle

            v_out = dmm.measure_vdc()
            i_meas = i_step  # ET54 CC is accurate; use set value
            p_out  = v_out * i_meas

            # Input power from SPD (SPD acts as DUT power source)
            p_in = psu.measure_power(ch)

            reg_pct = (v_noload - v_out) / v_noload * 100.0 if v_noload > 0 else 0.0

            load_currents.append(i_step)
            v_out_vals.append(v_out)
            p_out_vals.append(p_out)
            p_in_vals.append(p_in)

            print(f"  {i_step:>8.3f}  {v_out:>8.4f}  {p_out:>7.3f}W  "
                  f"{p_in:>7.3f}W  {reg_pct:>5.2f}%")

        load.off()

    finally:
        load.off()
        psu.disable(ch)

    # Regulation summary
    if v_out_vals:
        v_fullload    = v_out_vals[-1]
        regulation_pct = (v_noload - v_fullload) / v_noload * 100.0 if v_noload > 0 else 0.0
        print(f"\n  V_noload   = {v_noload:.4f} V")
        print(f"  V_fullload = {v_fullload:.4f} V  ({v_fullload - v_noload:+.4f} V)")
        print(f"  Regulation = {regulation_pct:.3f}%")

    return {
        "load_currents": load_currents,
        "v_out":         v_out_vals,
        "p_out":         p_out_vals,
        "p_in":          p_in_vals,
        "v_noload":      v_noload,
    }


# ---------------------------------------------------------------------------
# Efficiency
# ---------------------------------------------------------------------------

def compute_efficiency(load_reg_data: dict) -> list[float]:
    """Compute efficiency % from load regulation data.  Returns list per point."""
    eta = []
    for p_out, p_in in zip(load_reg_data["p_out"], load_reg_data["p_in"]):
        if p_in > 0.001:
            eta.append(p_out / p_in * 100.0)
        else:
            eta.append(0.0)
    return eta


# ---------------------------------------------------------------------------
# Ripple measurement (scope)
# ---------------------------------------------------------------------------

def run_ripple(scope: SDS2000X, psu: SPD3303X, load,
               dmm: SDM3000X, args) -> dict:
    """
    Capture output ripple at full load using the oscilloscope.
    Returns dict with vpp, vrms, waveform, sample_rate.
    """
    ch      = args.spd_channel
    i_load  = args.i_max
    v_set   = args.v_set
    dur_s   = args.ripple_duration_s

    print(f"\n[RIPPLE]  V={v_set:.3f} V  I_load={i_load:.3f} A  "
          f"capture={dur_s:.3f} s")

    psu.set_voltage(ch, v_set)
    psu.set_current(ch, i_load * 1.1 + 0.1)
    psu.enable(ch)

    load.mode = "CC"
    load.CC_current = i_load
    load.on()
    time.sleep(1.0)  # settle

    try:
        # Capture with auto-range (scope will pick Vdiv)
        # Use a small Vdiv since ripple is usually mV scale
        wave, fs = scope.capture_audio(channel=1, duration_s=dur_s, vdiv=0.01)

        vpp  = float(np.ptp(wave))
        vrms = float(np.std(wave))  # AC RMS (std dev with no DC offset assumed)
        v_dc = dmm.measure_vdc()

        print(f"  V_DC   = {v_dc:.4f} V")
        print(f"  V_pp   = {vpp*1000:.3f} mV")
        print(f"  V_rms  = {vrms*1000:.3f} mV (AC)")

    finally:
        load.off()
        psu.disable(ch)

    return {
        "wave":   wave,
        "fs":     fs,
        "vpp":    vpp,
        "vrms":   vrms,
        "v_dc":   v_dc,
        "i_load": i_load,
    }


# ---------------------------------------------------------------------------
# Transient response (scope)
# ---------------------------------------------------------------------------

def run_transient(scope: SDS2000X, psu: SPD3303X, load,
                  dmm: SDM3000X, args) -> dict:
    """
    Measure load step response: switch ET54 from i1 to i2, capture scope.
    Returns dict with waveform data.

    Strategy:
      - Set scope to trigger on edge (external trigger or auto)
      - Apply i1 load, then switch to i2
      - Capture at high sample rate
      - Compute overshoot, undershoot, settling time
    """
    ch  = args.spd_channel
    i1  = args.transient_i1
    i2  = args.transient_i2
    dur = 0.05  # 50 ms capture window

    print(f"\n[TRANSIENT]  V={args.v_set:.3f} V  "
          f"I_step {i1:.3f}→{i2:.3f} A")

    psu.set_voltage(ch, args.v_set)
    psu.set_current(ch, i2 * 1.1 + 0.1)
    psu.enable(ch)

    load.mode = "CC"
    load.CC_current = i1
    load.on()
    time.sleep(0.5)

    # Capture steady state at i1 first (baseline voltage)
    v_before = dmm.measure_vdc()

    # Arm scope for capture at auto-trigger, then switch load
    load.CC_current = i2
    time.sleep(0.02)  # small pause to let ET54 transition settle
    wave, fs = scope.capture_audio(channel=1, duration_s=dur, vdiv=0.02)

    v_after = dmm.measure_vdc()
    load.off()
    psu.disable(ch)

    # Analysis: find undershoot / overshoot in waveform
    if len(wave) > 0:
        v_min  = float(np.min(wave))
        v_max  = float(np.max(wave))
        v_mean = float(np.mean(wave))
        undershoot_mv = (v_mean - v_min) * 1000.0
        overshoot_mv  = (v_max - v_mean) * 1000.0
    else:
        v_min = v_max = v_mean = undershoot_mv = overshoot_mv = 0.0

    print(f"  V_before = {v_before:.4f} V  V_after = {v_after:.4f} V")
    print(f"  Waveform: min={v_min*1000:.2f} mV  max={v_max*1000:.2f} mV  "
          f"mean={v_mean*1000:.2f} mV")
    print(f"  Undershoot: {undershoot_mv:.2f} mV  Overshoot: {overshoot_mv:.2f} mV")

    return {
        "wave":           wave,
        "fs":             fs,
        "v_before":       v_before,
        "v_after":        v_after,
        "undershoot_mv":  undershoot_mv,
        "overshoot_mv":   overshoot_mv,
        "i1":             i1,
        "i2":             i2,
    }


# ---------------------------------------------------------------------------
# Output: CSV
# ---------------------------------------------------------------------------

def save_csv_load_reg(data: dict, efficiency: list[float], output_prefix: str) -> str:
    path = f"{output_prefix}_load_reg.csv"
    with open(path, "w", newline="") as f:
        w = csv_module.writer(f)
        w.writerow(["i_load_a", "v_out_v", "p_out_w", "p_in_w", "efficiency_pct"])
        for i, v, po, pi, eta in zip(data["load_currents"], data["v_out"],
                                      data["p_out"], data["p_in"], efficiency):
            w.writerow([f"{i:.6f}", f"{v:.6f}", f"{po:.6f}", f"{pi:.6f}", f"{eta:.2f}"])
    return path


# ---------------------------------------------------------------------------
# Output: plots
# ---------------------------------------------------------------------------

def plot_load_regulation(data: dict, output_prefix: str) -> str:
    fig, ax = plt.subplots(figsize=(8, 5))
    ax.plot(data["load_currents"], data["v_out"],
            color="#1f77b4", linewidth=1.8, marker="o", markersize=3)

    if data["load_currents"]:
        v_noload   = data.get("v_noload", data["v_out"][0])
        v_fullload = data["v_out"][-1]
        reg = (v_noload - v_fullload) / v_noload * 100.0 if v_noload > 0 else 0.0
        ax.axhline(v_noload, color="green", linestyle="--", linewidth=0.9, alpha=0.6,
                   label=f"V_noload={v_noload:.4f} V")
        ax.axhline(v_fullload, color="darkorange", linestyle="--", linewidth=0.9, alpha=0.6,
                   label=f"V_fullload={v_fullload:.4f} V")
        ax.set_title(f"Load Regulation — Regulation={reg:.3f}%  "
                     f"({datetime.now().strftime('%Y-%m-%d %H:%M')})")
    else:
        ax.set_title("Load Regulation")

    ax.set_xlabel("Load Current (A)")
    ax.set_ylabel("Output Voltage (V)")
    ax.grid(True, alpha=0.35)
    ax.legend(fontsize=9)
    plt.tight_layout()

    path = f"{output_prefix}_load_reg.png"
    plt.savefig(path, dpi=150, bbox_inches="tight")
    plt.close(fig)
    return path


def plot_efficiency(data: dict, efficiency: list[float], output_prefix: str) -> str:
    fig, ax = plt.subplots(figsize=(8, 5))
    ax.plot(data["load_currents"], efficiency,
            color="#2ca02c", linewidth=1.8, marker="o", markersize=3)
    ax.set_xlabel("Load Current (A)")
    ax.set_ylabel("Efficiency (%)")
    ax.set_title(f"Efficiency vs Load  ({datetime.now().strftime('%Y-%m-%d %H:%M')})")
    ax.set_ylim(0, 105)
    ax.grid(True, alpha=0.35)
    if efficiency:
        peak_eta = max(efficiency)
        peak_i   = data["load_currents"][efficiency.index(peak_eta)]
        ax.annotate(f"Peak {peak_eta:.1f}%\n@ {peak_i:.3f} A",
                    xy=(peak_i, peak_eta),
                    xytext=(peak_i + (max(data["load_currents"]) - min(data["load_currents"])) * 0.05,
                            peak_eta - 5),
                    fontsize=8, arrowprops=dict(arrowstyle="->", lw=0.8))
    plt.tight_layout()

    path = f"{output_prefix}_efficiency.png"
    plt.savefig(path, dpi=150, bbox_inches="tight")
    plt.close(fig)
    return path


def plot_ripple(ripple_data: dict, output_prefix: str) -> str:
    wave = ripple_data["wave"]
    fs   = ripple_data["fs"]
    if len(wave) == 0:
        return ""

    t_ms = np.arange(len(wave)) / fs * 1000.0

    fig, ax = plt.subplots(figsize=(10, 4))
    ax.plot(t_ms, wave * 1000, color="#1f77b4", linewidth=0.8)
    ax.set_xlabel("Time (ms)")
    ax.set_ylabel("Voltage (mV)")
    vpp = ripple_data["vpp"] * 1000
    vrms = ripple_data["vrms"] * 1000
    ax.set_title(f"Output Ripple — Vpp={vpp:.2f} mV  Vrms={vrms:.2f} mV  "
                 f"@ I={ripple_data['i_load']:.2f} A  "
                 f"({datetime.now().strftime('%Y-%m-%d %H:%M')})")
    ax.grid(True, alpha=0.35)
    plt.tight_layout()

    path = f"{output_prefix}_ripple.png"
    plt.savefig(path, dpi=150, bbox_inches="tight")
    plt.close(fig)
    return path


def plot_transient(transient_data: dict, output_prefix: str) -> str:
    wave = transient_data["wave"]
    fs   = transient_data["fs"]
    if len(wave) == 0:
        return ""

    t_ms = np.arange(len(wave)) / fs * 1000.0

    fig, ax = plt.subplots(figsize=(10, 4))
    ax.plot(t_ms, wave * 1000, color="#d62728", linewidth=0.8)
    ax.set_xlabel("Time (ms)")
    ax.set_ylabel("Voltage deviation (mV)")
    undershoot = transient_data["undershoot_mv"]
    overshoot  = transient_data["overshoot_mv"]
    i1 = transient_data["i1"]
    i2 = transient_data["i2"]
    ax.set_title(f"Load Step Transient — {i1:.2f}→{i2:.2f} A  "
                 f"Undershoot={undershoot:.1f} mV  Overshoot={overshoot:.1f} mV  "
                 f"({datetime.now().strftime('%Y-%m-%d %H:%M')})")
    ax.grid(True, alpha=0.35)
    plt.tight_layout()

    path = f"{output_prefix}_transient.png"
    plt.savefig(path, dpi=150, bbox_inches="tight")
    plt.close(fig)
    return path


# ---------------------------------------------------------------------------
# Output: text summary
# ---------------------------------------------------------------------------

def save_txt_summary(load_reg_data: dict | None, efficiency: list[float],
                     ripple_data: dict | None, transient_data: dict | None,
                     args, output_prefix: str) -> str:
    path = f"{output_prefix}_psu.txt"
    ts   = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    sep  = "=" * 65

    lines = [
        sep,
        "  PSU CHARACTERIZATION SUMMARY",
        f"  Generated    : {ts}",
        f"  Mode         : {args.mode}",
        f"  V_set        : {args.v_set:.3f} V",
        f"  SPD channel  : CH{args.spd_channel}",
        sep, "",
    ]

    if load_reg_data and load_reg_data.get("load_currents"):
        v_noload   = load_reg_data.get("v_noload", load_reg_data["v_out"][0])
        v_fullload = load_reg_data["v_out"][-1]
        i_fullload = load_reg_data["load_currents"][-1]
        reg = (v_noload - v_fullload) / v_noload * 100.0 if v_noload > 0 else 0.0
        lines += [
            "  LOAD REGULATION:",
            f"    V_noload         : {v_noload:.4f} V",
            f"    V @ {i_fullload:.3f} A       : {v_fullload:.4f} V",
            f"    Drop             : {(v_noload-v_fullload)*1000:.2f} mV",
            f"    Regulation       : {reg:.3f}%",
            "",
        ]

    if efficiency:
        peak_eta = max(efficiency)
        lines += [
            "  EFFICIENCY:",
            f"    Peak efficiency  : {peak_eta:.1f}%",
        ]
        if load_reg_data and load_reg_data.get("load_currents"):
            peak_i = load_reg_data["load_currents"][efficiency.index(peak_eta)]
            p_out  = load_reg_data["p_out"][efficiency.index(peak_eta)]
            lines.append(f"    at I_load        : {peak_i:.3f} A  ({p_out:.2f} W)")
        lines.append("")

    if ripple_data:
        lines += [
            "  OUTPUT RIPPLE:",
            f"    V_pp             : {ripple_data['vpp']*1000:.3f} mV",
            f"    V_rms (AC)       : {ripple_data['vrms']*1000:.3f} mV",
            f"    Measured at      : {ripple_data['i_load']:.3f} A",
            f"    V_DC (DMM)       : {ripple_data['v_dc']:.4f} V",
            "",
        ]

    if transient_data:
        lines += [
            "  TRANSIENT RESPONSE:",
            f"    Load step        : {transient_data['i1']:.3f}→{transient_data['i2']:.3f} A",
            f"    Undershoot       : {transient_data['undershoot_mv']:.2f} mV",
            f"    Overshoot        : {transient_data['overshoot_mv']:.2f} mV",
            f"    V_before step    : {transient_data['v_before']:.4f} V",
            f"    V_after step     : {transient_data['v_after']:.4f} V",
            "",
        ]

    text = "\n".join(lines) + "\n"
    with open(path, "w") as fh:
        fh.write(text)
    return path


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="PSU Characterizer — SPD3303X + ET5406A+ + SDM3045X + SDS2504X Plus",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Modes:
  load-reg   — Load regulation: V_out vs I_load sweep (requires ET5406A+)
  efficiency — Efficiency: P_out/P_in vs I_load (requires ET5406A+)
  ripple     — Output ripple: scope Vpp/Vrms at full load (requires scope + ET5406A+)
  transient  — Load step response: scope capture of voltage deviation (requires both)
  full       — Run all available tests (default)

Without ET5406A+, only static measurements are possible.

Examples:
  python psu_characterizer.py --v-set 5.0 --i-max 3.0
  python psu_characterizer.py --mode load-reg --v-set 3.3 --i-max 1.0 --i-points 30
  python psu_characterizer.py --mode ripple --ripple-duration-s 0.05
  python psu_characterizer.py --mode transient --transient-i1 0.1 --transient-i2 2.5
""",
    )

    parser.add_argument("--mode", default="full",
                        choices=["load-reg", "efficiency", "ripple", "transient", "full"],
                        help="Test mode (default: full — run all available)")
    parser.add_argument("--spd-channel", type=int, default=1,
                        help="SPD3303X channel to use as DUT (1 or 2, default: 1)")
    parser.add_argument("--v-set",     type=float, default=5.0,
                        help="DUT output voltage setpoint in V (default: 5.0)")
    parser.add_argument("--i-min",     type=float, default=0.0,
                        help="Load sweep start current in A (default: 0)")
    parser.add_argument("--i-max",     type=float, default=3.0,
                        help="Load sweep end current in A (default: 3.0)")
    parser.add_argument("--i-points",  type=int,   default=20,
                        help="Load sweep steps (default: 20)")
    parser.add_argument("--transient-i1", type=float, default=0.1,
                        help="Transient test light load in A (default: 0.1)")
    parser.add_argument("--transient-i2", type=float, default=2.0,
                        help="Transient test heavy load in A (default: 2.0)")
    parser.add_argument("--ripple-duration-s", type=float, default=0.1,
                        help="Scope capture duration for ripple in seconds (default: 0.1)")
    parser.add_argument("--load-port",   default=DEFAULT_LOAD_PORT,
                        help=f"ET5406A+ serial port (default: {DEFAULT_LOAD_PORT})")
    parser.add_argument("--spd-host",    default=DEFAULT_SPD_HOST,
                        help=f"SPD3303X IP (default: {DEFAULT_SPD_HOST})")
    parser.add_argument("--dmm-host",    default=DEFAULT_DMM_HOST,
                        help=f"SDM3045X IP (default: {DEFAULT_DMM_HOST})")
    parser.add_argument("--scope-host",  default=DEFAULT_SCOPE_HOST,
                        help=f"SDS2504X Plus IP (default: {DEFAULT_SCOPE_HOST})")
    parser.add_argument("--output",      default=None,
                        help="Output filename prefix (default: timestamped)")

    args = parser.parse_args()

    if args.output is None:
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        args.output = f"psu_{ts}"

    print(f"PSU Characterizer — mode: {args.mode.upper()}")
    print(f"  V_set         : {args.v_set:.3f} V")
    print(f"  SPD CH{args.spd_channel}       : {args.spd_host}")
    print(f"  I range       : {args.i_min:.3f} – {args.i_max:.3f} A  ({args.i_points} points)")
    print(f"  Output prefix : {args.output}")

    psu   = None
    dmm   = None
    scope = None
    load  = None

    load_reg_data:  dict | None  = None
    efficiency:     list[float]  = []
    ripple_data:    dict | None  = None
    transient_data: dict | None  = None

    do_load_tests   = args.mode in ("load-reg", "efficiency", "ripple", "transient", "full")
    do_scope_tests  = args.mode in ("ripple", "transient", "full")

    try:
        # Connect PSU
        print(f"\nConnecting to SPD3303X @ {args.spd_host} ...", end=" ", flush=True)
        psu = SPD3303X(args.spd_host)
        print(f"OK  ({psu.identify().strip()})")
        psu.disable_all()

        # Connect DMM
        print(f"Connecting to SDM3045X @ {args.dmm_host} ...", end=" ", flush=True)
        dmm = SDM3000X(args.dmm_host)
        print(f"OK  ({dmm.identify().strip()})")

        # Connect ET5406A+ load
        print(f"Connecting to ET5406A+ @ {args.load_port} ...", end=" ", flush=True)
        try:
            load = _connect_load(args.load_port)
            load.off()
            print("OK")
        except RuntimeError as exc:
            print(f"FAILED ({exc})")
            print("  Load-dependent tests will be skipped.")
            load = None

        # Connect scope for ripple/transient
        if do_scope_tests:
            print(f"Connecting to SDS2504X Plus @ {args.scope_host} ...", end=" ", flush=True)
            try:
                scope = SDS2000X(args.scope_host)
                print(f"OK  ({scope.identify().strip()})")
            except Exception as exc:
                print(f"FAILED ({exc})")
                print("  Ripple and transient tests will be skipped.")
                scope = None

        # Determine what tests can run
        can_load = (load is not None)
        can_scope = (scope is not None and can_load)

        run_load_reg  = can_load  and args.mode in ("load-reg", "efficiency", "full")
        run_efficiency = can_load and args.mode in ("efficiency", "full")
        run_ripple    = can_scope and args.mode in ("ripple", "full")
        run_trans     = can_scope and args.mode in ("transient", "full")

        if not can_load:
            print("\nNOTE: ET5406A+ not available — skipping all load-sweep tests.")
            print("      Connect the load and retry, or check USB driver for CH340.")

        # --- Load regulation and efficiency ---
        if run_load_reg:
            load_reg_data = run_load_regulation(load, psu, dmm, args)
            if run_efficiency and load_reg_data:
                efficiency = compute_efficiency(load_reg_data)

        # --- Ripple ---
        if run_ripple:
            ripple_data = run_ripple(scope, psu, load, dmm, args)

        # --- Transient ---
        if run_trans:
            transient_data = run_transient(scope, psu, load, dmm, args)

        # --- Save outputs ---
        print(f"\n[SAVING RESULTS]")
        saved_files = []

        if load_reg_data and load_reg_data.get("load_currents"):
            eff = efficiency if efficiency else [0.0] * len(load_reg_data["load_currents"])
            csv_path = save_csv_load_reg(load_reg_data, eff, args.output)
            png_lr   = plot_load_regulation(load_reg_data, args.output)
            saved_files += [csv_path, png_lr]
            print(f"  Load reg plot  → {png_lr}")
            print(f"  Load reg CSV   → {csv_path}")

            if efficiency:
                png_eff = plot_efficiency(load_reg_data, efficiency, args.output)
                saved_files.append(png_eff)
                print(f"  Efficiency     → {png_eff}")

        if ripple_data and len(ripple_data.get("wave", [])) > 0:
            png_ripple = plot_ripple(ripple_data, args.output)
            if png_ripple:
                saved_files.append(png_ripple)
                print(f"  Ripple plot    → {png_ripple}")

        if transient_data and len(transient_data.get("wave", [])) > 0:
            png_trans = plot_transient(transient_data, args.output)
            if png_trans:
                saved_files.append(png_trans)
                print(f"  Transient plot → {png_trans}")

        txt_path = save_txt_summary(load_reg_data, efficiency,
                                     ripple_data, transient_data,
                                     args, args.output)
        saved_files.append(txt_path)
        print(f"  Summary        → {txt_path}")
        print()
        with open(txt_path) as fh:
            print(fh.read())

    except KeyboardInterrupt:
        print("\nInterrupted — disabling load and PSU.")
        _safe_load_off(load)
        _safe_psu_off(psu)
        sys.exit(0)
    except ConnectionRefusedError as exc:
        print(f"\nCannot connect to instrument: {exc}")
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
        _safe_load_off(load)
        _safe_psu_off(psu)
        for inst in (dmm, scope):
            if inst is not None:
                try:
                    inst.close()
                except Exception:
                    pass


if __name__ == "__main__":
    main()
