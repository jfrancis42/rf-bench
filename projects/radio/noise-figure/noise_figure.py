#!/usr/bin/env python3
"""
Noise Figure Measurement — Y-Factor Technique

Measures the noise figure of an LNA, preamp, or receive chain using a calibrated
noise source (HP 346B, NC346, DIY avalanche diode, etc.) with a known ENR.

The operator manually toggles the noise source when prompted.  No automated
switching is assumed.

Connection:
  Standard:    Noise source → DUT → SSA RF In
  Calibration: Noise source → SSA RF In  (no DUT; use --baseline)

Usage:
  python noise_figure.py --enr 15.4
  python noise_figure.py --enr 6.0 --freq 14000
  python noise_figure.py --enr 15.4 --sweep --start 1000 --stop 60000 --points 20
  python noise_figure.py --enr 6.0 --baseline
"""

import argparse
import json
import os
import sys
import time
from datetime import datetime
from math import log10

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np

from rf_bench.siglent import SSA3000X                     # noqa: E402
from rf_bench.utils import (                               # noqa: E402
    format_freq, format_freq_short, thermal_noise_floor,
    cascaded_noise_figure,
)
from rf_bench import connect

# ---------------------------------------------------------------------------
# Defaults
# ---------------------------------------------------------------------------

DEFAULT_SSA_HOST    = None  # Now uses inventory
DEFAULT_FREQ_KHZ    = 14_000      # 14 MHz (40 m)
DEFAULT_BANDWIDTH   = 100_000     # 100 kHz RBW for noise measurement
DEFAULT_GAIN        = 20.0        # dB; assumed DUT gain for de-embedding
DEFAULT_START_KHZ   = 1_000
DEFAULT_STOP_KHZ    = 60_000
DEFAULT_SWEEP_PTS   = 20

CAL_FILE = os.path.expanduser("~/.noise_figure_ssa_cal.json")

# Reference temperature for Y-factor (IEEE 296, 290 K standard)
T_REF_K = 290.0


# ---------------------------------------------------------------------------
# Y-factor core measurement
# ---------------------------------------------------------------------------

def _configure_zero_span(ssa: SSA3000X, freq_hz: float, bw_hz: float) -> None:
    """Set SSA to zero-span mode at freq_hz with RBW and VBW = bw_hz."""
    ssa._send(f':FREQ:CENT {freq_hz:.0f}')
    ssa._send(':FREQ:SPAN 0')
    ssa._send(f':SENS:BAND:RES {bw_hz:.0f}')
    ssa._send(f':SENS:BAND:VID {bw_hz:.0f}')
    ssa._send(':INIT:CONT OFF')


def _measure_noise_power(ssa: SSA3000X) -> float:
    """
    Trigger a single zero-span sweep and return the average power in dBm.

    The trace is averaged in linear power (not dB) to get the true mean.
    """
    ssa._send(':INIT:IMM')
    ssa._query('*OPC?')
    trace = ssa.get_trace()  # np.ndarray of dBm values
    # Average in linear then convert back — correct for noise power averaging
    linear = 10.0 ** (trace / 10.0)
    avg_linear = float(np.mean(linear))
    return 10.0 * log10(avg_linear)


def measure_y_factor(ssa: SSA3000X, freq_hz: float, bw_hz: float,
                     prompt_prefix: str = "") -> dict:
    """
    Perform a single-frequency Y-factor measurement.

    Prompts the operator to connect/toggle the noise source.

    Returns:
      p_hot_dbm   — noise power with source ON (dBm)
      p_cold_dbm  — noise power with source OFF (dBm)
      y_linear    — Y = P_hot / P_cold (linear ratio)
      nf_system_db — NF of system at measurement port
    """
    _configure_zero_span(ssa, freq_hz, bw_hz)

    tag = f"[{prompt_prefix}] " if prompt_prefix else ""

    print(f"  {tag}Connect noise source ON → DUT → SSA.")
    input("  Press Enter when ready... ")
    p_hot_dbm = _measure_noise_power(ssa)
    print(f"  P_hot = {p_hot_dbm:.2f} dBm")

    print(f"  {tag}Turn noise source OFF (leave DUT connected).")
    input("  Press Enter when ready... ")
    p_cold_dbm = _measure_noise_power(ssa)
    print(f"  P_cold = {p_cold_dbm:.2f} dBm")

    y_linear = 10.0 ** ((p_hot_dbm - p_cold_dbm) / 10.0)
    return dict(p_hot_dbm=p_hot_dbm, p_cold_dbm=p_cold_dbm, y_linear=y_linear)


def compute_nf(enr_db: float, y_linear: float) -> float:
    """
    Compute noise figure from ENR and Y-factor.

    NF = 10*log10(ENR_linear / (Y - 1))

    Returns NF in dB, or +inf if Y <= 1 (invalid measurement).
    """
    enr_linear = 10.0 ** (enr_db / 10.0)
    if y_linear <= 1.0:
        print("  WARNING: Y <= 1.  Check connections — noise source may not be toggling.")
        return float('inf')
    return 10.0 * log10(enr_linear / (y_linear - 1.0))


def deembed_ssa_nf(nf_system_db: float, nf_ssa_db: float, gain_dut_db: float) -> float:
    """
    Remove SSA NF from a cascaded system NF using Friis' formula.

    F_dut = F_system − (F_ssa − 1) / G_dut

    Returns NF_dut in dB, or nan if result is invalid (DUT NF > system NF).
    """
    f_system = 10.0 ** (nf_system_db / 10.0)
    f_ssa    = 10.0 ** (nf_ssa_db    / 10.0)
    g_dut    = 10.0 ** (gain_dut_db  / 10.0)
    f_dut    = f_system - (f_ssa - 1.0) / g_dut
    if f_dut <= 0.0:
        return float('nan')
    return 10.0 * log10(f_dut)


# ---------------------------------------------------------------------------
# Baseline calibration
# ---------------------------------------------------------------------------

def run_baseline(ssa: SSA3000X, freq_hz: float, bw_hz: float, enr_db: float) -> float:
    """
    Measure SSA self-NF (noise source → SSA directly, no DUT).

    Saves result to CAL_FILE.  Returns nf_ssa in dB.
    """
    print(f"\n[BASELINE CALIBRATION — noise source → SSA directly, no DUT]")
    print(f"  ENR = {enr_db:.2f} dB   freq = {format_freq_short(freq_hz)}   "
          f"BW = {format_freq_short(bw_hz)}")

    result = measure_y_factor(ssa, freq_hz, bw_hz, prompt_prefix="CAL")
    nf_ssa = compute_nf(enr_db, result['y_linear'])

    print(f"\n  Y-factor  = {result['y_linear']:.4f}  ({result['p_hot_dbm'] - result['p_cold_dbm']:.2f} dB)")
    print(f"  SSA NF    = {nf_ssa:.2f} dB")

    cal_data = {
        "timestamp":    datetime.now().isoformat(),
        "freq_hz":      freq_hz,
        "bw_hz":        bw_hz,
        "enr_db":       enr_db,
        "nf_ssa_db":    nf_ssa,
        "p_hot_dbm":    result['p_hot_dbm'],
        "p_cold_dbm":   result['p_cold_dbm'],
        "y_linear":     result['y_linear'],
    }
    with open(CAL_FILE, "w") as fh:
        json.dump(cal_data, fh, indent=2)
    print(f"  Saved → {CAL_FILE}")

    return nf_ssa


def load_baseline() -> float | None:
    """Load SSA NF from calibration file.  Returns None if not available."""
    if not os.path.exists(CAL_FILE):
        return None
    try:
        with open(CAL_FILE) as fh:
            cal = json.load(fh)
        nf_ssa = float(cal["nf_ssa_db"])
        ts     = cal.get("timestamp", "unknown")
        print(f"  Loaded SSA baseline NF = {nf_ssa:.2f} dB  (from {ts})")
        return nf_ssa
    except Exception as exc:
        print(f"  Warning: could not load baseline cal: {exc}")
        return None


# ---------------------------------------------------------------------------
# Single-frequency measurement
# ---------------------------------------------------------------------------

def measure_single(ssa: SSA3000X, freq_hz: float, bw_hz: float,
                   enr_db: float, nf_ssa_db: float | None,
                   gain_db: float) -> dict:
    """
    Full Y-factor measurement at a single frequency.

    Returns a result dict.
    """
    print(f"\n[SINGLE-FREQUENCY NF MEASUREMENT]")
    print(f"  Frequency : {format_freq(freq_hz)}")
    print(f"  ENR       : {enr_db:.2f} dB")
    print(f"  BW (RBW)  : {format_freq_short(bw_hz)}")
    if nf_ssa_db is not None:
        print(f"  SSA NF    : {nf_ssa_db:.2f} dB  (will de-embed)")
        print(f"  DUT gain  : {gain_db:.1f} dB  (assumed)")

    result = measure_y_factor(ssa, freq_hz, bw_hz)
    nf_system = compute_nf(enr_db, result['y_linear'])

    nf_dut = None
    if nf_ssa_db is not None and not np.isinf(nf_system):
        nf_dut = deembed_ssa_nf(nf_system, nf_ssa_db, gain_db)

    print(f"\n  Y-factor    = {result['y_linear']:.4f}  "
          f"({result['p_hot_dbm'] - result['p_cold_dbm']:.2f} dB)")
    print(f"  NF (system) = {nf_system:.2f} dB")
    if nf_dut is not None:
        if np.isnan(nf_dut):
            print("  NF (DUT)   = N/A  (de-embedding failed — check gain estimate)")
        else:
            print(f"  NF (DUT)    = {nf_dut:.2f} dB  (de-embedded SSA NF)")

    return dict(
        freq_hz=freq_hz,
        p_hot_dbm=result['p_hot_dbm'],
        p_cold_dbm=result['p_cold_dbm'],
        y_linear=result['y_linear'],
        nf_system_db=nf_system,
        nf_dut_db=nf_dut,
        enr_db=enr_db,
        bw_hz=bw_hz,
    )


# ---------------------------------------------------------------------------
# Frequency sweep
# ---------------------------------------------------------------------------

def measure_sweep(ssa: SSA3000X, freqs_hz: np.ndarray, bw_hz: float,
                  enr_db: float, nf_ssa_db: float | None,
                  gain_db: float) -> list[dict]:
    """
    Y-factor sweep across multiple frequencies.

    Prompts once at the start; the operator is expected to leave the noise
    source connected and toggle it when prompted at each frequency point.
    For efficiency, the script asks the operator to toggle only once per
    point (hot → cold at each frequency).
    """
    n = len(freqs_hz)
    print(f"\n[FREQUENCY SWEEP — {n} points, "
          f"{format_freq_short(freqs_hz[0])} – {format_freq_short(freqs_hz[-1])}]")
    print(f"  ENR = {enr_db:.2f} dB   BW = {format_freq_short(bw_hz)}")
    print(f"\n  At each frequency the script will ask you to toggle the noise source.")
    input("  Connect noise source → DUT → SSA.  Press Enter to begin... ")

    results = []

    for i, freq_hz in enumerate(freqs_hz):
        pct = (i + 1) / n * 100
        print(f"\n  [{i+1}/{n}  {pct:.0f}%]  {format_freq(freq_hz)}")

        _configure_zero_span(ssa, freq_hz, bw_hz)

        # Hot measurement
        print("    Noise source ON →", end=" ", flush=True)
        input("Press Enter... ")
        p_hot_dbm = _measure_noise_power(ssa)
        print(f"    P_hot  = {p_hot_dbm:.2f} dBm")

        # Cold measurement
        print("    Noise source OFF →", end=" ", flush=True)
        input("Press Enter... ")
        p_cold_dbm = _measure_noise_power(ssa)
        print(f"    P_cold = {p_cold_dbm:.2f} dBm")

        y_linear  = 10.0 ** ((p_hot_dbm - p_cold_dbm) / 10.0)
        nf_system = compute_nf(enr_db, y_linear)

        nf_dut = None
        if nf_ssa_db is not None and not np.isinf(nf_system):
            nf_dut = deembed_ssa_nf(nf_system, nf_ssa_db, gain_db)

        nf_display = f"NF_sys={nf_system:.2f} dB"
        if nf_dut is not None and not np.isnan(nf_dut):
            nf_display += f"  NF_dut={nf_dut:.2f} dB"

        print(f"    Y={y_linear:.3f}  {nf_display}")

        results.append(dict(
            freq_hz=float(freq_hz),
            p_hot_dbm=p_hot_dbm,
            p_cold_dbm=p_cold_dbm,
            y_linear=y_linear,
            nf_system_db=nf_system,
            nf_dut_db=nf_dut,
            enr_db=enr_db,
            bw_hz=bw_hz,
        ))

    return results


# ---------------------------------------------------------------------------
# Plotting
# ---------------------------------------------------------------------------

def plot_single(result: dict, output_prefix: str) -> str:
    """Bar chart for a single-frequency measurement."""
    freq_hz    = result['freq_hz']
    nf_sys     = result['nf_system_db']
    nf_dut     = result.get('nf_dut_db')
    has_dut    = nf_dut is not None and not np.isnan(nf_dut)

    labels  = ['NF System']
    heights = [nf_sys]
    colors  = ['#1f77b4']

    if has_dut:
        labels.append('NF DUT\n(de-embedded)')
        heights.append(nf_dut)
        colors.append('#ff7f0e')

    fig, ax = plt.subplots(figsize=(6, 5))
    bars = ax.bar(labels, heights, color=colors, width=0.4, edgecolor='black', linewidth=0.8)

    for bar, val in zip(bars, heights):
        ax.text(bar.get_x() + bar.get_width() / 2, bar.get_height() + 0.1,
                f"{val:.2f} dB", ha='center', va='bottom', fontsize=10, fontweight='bold')

    ax.set_ylabel("Noise Figure (dB)", fontsize=10)
    ax.set_title(
        f"Noise Figure — {format_freq(freq_hz)}\n"
        f"ENR={result['enr_db']:.1f} dB  BW={format_freq_short(result['bw_hz'])}  "
        f"Y={result['y_linear']:.4f}\n"
        f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        fontsize=9,
    )
    ax.grid(True, axis='y', alpha=0.35)
    ax.set_ylim(bottom=0, top=max(heights) * 1.4)
    ax.tick_params(labelsize=9)

    plt.tight_layout()
    path = f"{output_prefix}_nf.png"
    plt.savefig(path, dpi=150, bbox_inches='tight')
    plt.close(fig)
    return path


def plot_sweep(results: list[dict], output_prefix: str) -> str:
    """Line plot of NF vs frequency for a sweep."""
    freqs_mhz  = np.array([r['freq_hz'] for r in results]) / 1e6
    nf_sys     = np.array([r['nf_system_db'] for r in results])
    nf_dut_raw = [r.get('nf_dut_db') for r in results]
    has_dut    = any(v is not None and not np.isnan(v) for v in nf_dut_raw)

    nrows = 2 if has_dut else 1
    fig, axes = plt.subplots(nrows, 1, figsize=(10, 4 * nrows), sharex=True)
    if nrows == 1:
        axes = [axes]

    enr_db = results[0]['enr_db']
    bw_hz  = results[0]['bw_hz']

    # --- System NF panel ---
    ax = axes[0]
    valid = ~np.isinf(nf_sys) & ~np.isnan(nf_sys)
    if np.any(valid):
        ax.plot(freqs_mhz[valid], nf_sys[valid], 'o-', color='#1f77b4',
                linewidth=1.5, markersize=5, label='NF System')

        nf_min = float(np.nanmin(nf_sys[valid]))
        nf_max = float(np.nanmax(nf_sys[valid]))
        nf_med = float(np.nanmedian(nf_sys[valid]))
        ax.axhline(nf_med, color='gray', linestyle='--', linewidth=0.8,
                   label=f'Median {nf_med:.2f} dB')

        textstr = (f"Min: {nf_min:.2f} dB\n"
                   f"Max: {nf_max:.2f} dB\n"
                   f"Median: {nf_med:.2f} dB")
        ax.text(0.02, 0.97, textstr, transform=ax.transAxes, fontsize=8,
                verticalalignment='top',
                bbox=dict(boxstyle='round', facecolor='wheat', alpha=0.8))

    ax.set_ylabel("NF System (dB)", fontsize=10)
    ax.set_title(
        f"Noise Figure Sweep — {format_freq_short(results[0]['freq_hz'])} – "
        f"{format_freq_short(results[-1]['freq_hz'])}\n"
        f"ENR={enr_db:.1f} dB  BW={format_freq_short(bw_hz)}  "
        f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        fontsize=10,
    )
    ax.grid(True, alpha=0.35)
    ax.legend(fontsize=8)
    ax.tick_params(labelsize=9)

    # --- DUT NF panel (de-embedded) ---
    if has_dut:
        ax2 = axes[1]
        nf_dut = np.array([r['nf_dut_db'] if r.get('nf_dut_db') is not None
                           else float('nan') for r in results])
        valid2 = ~np.isnan(nf_dut) & ~np.isinf(nf_dut)

        if np.any(valid2):
            ax2.plot(freqs_mhz[valid2], nf_dut[valid2], 's-', color='#ff7f0e',
                     linewidth=1.5, markersize=5, label='NF DUT (de-embedded)')

            nf2_min = float(np.nanmin(nf_dut[valid2]))
            nf2_max = float(np.nanmax(nf_dut[valid2]))
            nf2_med = float(np.nanmedian(nf_dut[valid2]))
            ax2.axhline(nf2_med, color='gray', linestyle='--', linewidth=0.8,
                        label=f'Median {nf2_med:.2f} dB')

            textstr2 = (f"Min: {nf2_min:.2f} dB\n"
                        f"Max: {nf2_max:.2f} dB\n"
                        f"Median: {nf2_med:.2f} dB")
            ax2.text(0.02, 0.97, textstr2, transform=ax2.transAxes, fontsize=8,
                     verticalalignment='top',
                     bbox=dict(boxstyle='round', facecolor='lightyellow', alpha=0.8))

        ax2.set_ylabel("NF DUT (dB)", fontsize=10)
        ax2.set_xlabel("Frequency (MHz)", fontsize=10)
        ax2.set_title("DUT Noise Figure (SSA NF de-embedded via Friis)", fontsize=10)
        ax2.grid(True, alpha=0.35)
        ax2.legend(fontsize=8)
        ax2.tick_params(labelsize=9)
    else:
        axes[-1].set_xlabel("Frequency (MHz)", fontsize=10)

    plt.tight_layout()
    path = f"{output_prefix}_nf.png"
    plt.savefig(path, dpi=150, bbox_inches='tight')
    plt.close(fig)
    return path


# ---------------------------------------------------------------------------
# Text report
# ---------------------------------------------------------------------------

def save_txt(results: list[dict], output_prefix: str,
             nf_ssa_db: float | None, gain_db: float) -> str:
    """Write a text table of results."""
    path = f"{output_prefix}_nf.txt"
    ts   = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    enr  = results[0]['enr_db']
    bw   = results[0]['bw_hz']
    has_dut = any(r.get('nf_dut_db') is not None for r in results)
    sep  = "=" * 80

    lines = [
        sep,
        "  NOISE FIGURE MEASUREMENT REPORT  (Y-Factor Method)",
        f"  Generated  : {ts}",
        f"  ENR        : {enr:.2f} dB",
        f"  BW (RBW)   : {format_freq_short(bw)}",
    ]
    if nf_ssa_db is not None:
        lines.append(f"  SSA NF     : {nf_ssa_db:.2f} dB  (de-embedding active)")
        lines.append(f"  DUT gain   : {gain_db:.1f} dB  (assumed)")
    else:
        lines.append("  SSA NF     : not calibrated (run --baseline for de-embedding)")
    lines += [sep, ""]

    if len(results) > 1:
        nf_sys_arr = np.array([r['nf_system_db'] for r in results])
        valid = ~np.isinf(nf_sys_arr) & ~np.isnan(nf_sys_arr)
        if np.any(valid):
            lines += [
                f"  NF System min : {np.nanmin(nf_sys_arr[valid]):.2f} dB",
                f"  NF System max : {np.nanmax(nf_sys_arr[valid]):.2f} dB",
                f"  NF System med : {np.nanmedian(nf_sys_arr[valid]):.2f} dB",
                "",
            ]

    # Table header
    if has_dut:
        lines.append(
            f"{'Frequency':>14}  {'P_hot':>9}  {'P_cold':>9}  "
            f"{'Y':>6}  {'NF_sys':>8}  {'NF_dut':>8}"
        )
        lines.append("-" * 70)
    else:
        lines.append(
            f"{'Frequency':>14}  {'P_hot':>9}  {'P_cold':>9}  "
            f"{'Y':>6}  {'NF_sys':>8}"
        )
        lines.append("-" * 58)

    for r in results:
        freq_str  = format_freq(r['freq_hz'])
        hot_str   = f"{r['p_hot_dbm']:+7.2f} dBm"
        cold_str  = f"{r['p_cold_dbm']:+7.2f} dBm"
        y_str     = f"{r['y_linear']:.4f}"
        nfsys_str = f"{r['nf_system_db']:+7.2f} dB" if not np.isinf(r['nf_system_db']) else "  invalid"
        if has_dut:
            v = r.get('nf_dut_db')
            nfdut_str = (f"{v:+7.2f} dB"
                         if v is not None and not np.isnan(v) and not np.isinf(v)
                         else "      N/A")
            lines.append(
                f"{freq_str:>14}  {hot_str}  {cold_str}  "
                f"{y_str:>6}  {nfsys_str}  {nfdut_str}"
            )
        else:
            lines.append(
                f"{freq_str:>14}  {hot_str}  {cold_str}  "
                f"{y_str:>6}  {nfsys_str}"
            )

    text = "\n".join(lines) + "\n"
    with open(path, "w") as fh:
        fh.write(text)
    return path


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Noise Figure Measurement — Y-Factor Technique",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Setup (standard measurement):
  Noise source ON/OFF → DUT → SSA RF In

Setup (baseline calibration, --baseline):
  Noise source ON/OFF → SSA RF In  (no DUT)

Examples:
  python noise_figure.py --enr 15.4
  python noise_figure.py --enr 6.0 --freq 14000
  python noise_figure.py --enr 15.4 --sweep --start 1000 --stop 60000 --points 20
  python noise_figure.py --enr 6.0 --baseline
  python noise_figure.py --enr 15.4 --gain 20 --freq 100000
""",
    )

    parser.add_argument("--enr",       type=float, required=True,
                        metavar="DB",  help="Noise source ENR in dB (REQUIRED)")
    parser.add_argument("--ssa",       default=DEFAULT_SSA_HOST, metavar="HOST",
                        help=f"SSA IP address (default {DEFAULT_SSA_HOST})")
    parser.add_argument("--freq",      type=float, default=DEFAULT_FREQ_KHZ,
                        metavar="KHZ", help=f"Single measurement frequency in kHz "
                                            f"(default {DEFAULT_FREQ_KHZ})")
    parser.add_argument("--sweep",     action="store_true",
                        help="Perform frequency sweep instead of single-frequency measurement")
    parser.add_argument("--start",     type=float, default=DEFAULT_START_KHZ,
                        metavar="KHZ", help=f"Sweep start frequency in kHz "
                                            f"(default {DEFAULT_START_KHZ})")
    parser.add_argument("--stop",      type=float, default=DEFAULT_STOP_KHZ,
                        metavar="KHZ", help=f"Sweep stop frequency in kHz "
                                            f"(default {DEFAULT_STOP_KHZ})")
    parser.add_argument("--points",    type=int, default=DEFAULT_SWEEP_PTS,
                        metavar="N",   help=f"Number of frequency points in sweep "
                                            f"(default {DEFAULT_SWEEP_PTS})")
    parser.add_argument("--bandwidth", type=float, default=DEFAULT_BANDWIDTH,
                        metavar="HZ",  help=f"Noise measurement bandwidth / RBW in Hz "
                                            f"(default {DEFAULT_BANDWIDTH})")
    parser.add_argument("--baseline",  action="store_true",
                        help="Measure SSA NF baseline (noise source → SSA, no DUT)")
    parser.add_argument("--gain",      type=float, default=DEFAULT_GAIN,
                        metavar="DB",  help=f"DUT gain in dB for de-embedding "
                                            f"(default {DEFAULT_GAIN})")
    parser.add_argument("--output",    default=None, metavar="PREFIX",
                        help="Output filename prefix (default: timestamped)")

    args = parser.parse_args()

    if args.output is None:
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        args.output = f"noise_figure_{ts}"

    freq_hz  = args.freq  * 1_000.0
    bw_hz    = args.bandwidth
    enr_db   = args.enr
    gain_db  = args.gain

    ssa = None
    try:
        print(f"Connecting to SSA via inventory ...")
        ssa = connect(args.ssa or 'ssa')
        print(f"  {ssa.identify()}")

        # --- Baseline calibration mode ---
        if args.baseline:
            nf_ssa = run_baseline(ssa, freq_hz, bw_hz, enr_db)
            print(f"\nBaseline NF_ssa = {nf_ssa:.2f} dB  — saved to {CAL_FILE}")
            return

        # Load prior SSA baseline if available
        print("\nChecking for SSA baseline calibration ...")
        nf_ssa_db = load_baseline()
        if nf_ssa_db is None:
            print("  No baseline found.  NF_system will be reported without de-embedding.")
            print("  Run with --baseline first (noise source → SSA directly) to enable de-embedding.")

        # --- Measurement ---
        if args.sweep:
            freqs_hz = np.geomspace(args.start * 1_000.0, args.stop * 1_000.0, args.points)
            results  = measure_sweep(ssa, freqs_hz, bw_hz, enr_db, nf_ssa_db, gain_db)
        else:
            single  = measure_single(ssa, freq_hz, bw_hz, enr_db, nf_ssa_db, gain_db)
            results = [single]

        # --- Save outputs ---
        print("\n[SAVING RESULTS]")

        txt_path = save_txt(results, args.output, nf_ssa_db, gain_db)
        print(f"Text   → {txt_path}")

        json_data = {
            "timestamp": datetime.now().isoformat(),
            "ssa_host":  args.ssa,
            "enr_db":    enr_db,
            "bw_hz":     bw_hz,
            "gain_db":   gain_db,
            "nf_ssa_db": nf_ssa_db,
            "sweep":     args.sweep,
            "results":   [
                {
                    "freq_hz":       r['freq_hz'],
                    "p_hot_dbm":     r['p_hot_dbm'],
                    "p_cold_dbm":    r['p_cold_dbm'],
                    "y_linear":      r['y_linear'],
                    "nf_system_db":  (r['nf_system_db']
                                      if not np.isinf(r['nf_system_db']) else None),
                    "nf_dut_db":     (r['nf_dut_db']
                                      if r.get('nf_dut_db') is not None
                                         and not np.isnan(r['nf_dut_db']) else None),
                }
                for r in results
            ],
        }
        json_path = f"{args.output}_nf.json"
        with open(json_path, "w") as jf:
            json.dump(json_data, jf, indent=2)
        print(f"JSON   → {json_path}")

        try:
            if args.sweep:
                png_path = plot_sweep(results, args.output)
            else:
                png_path = plot_single(results[0], args.output)
            print(f"Plot   → {png_path}")
        except Exception as exc:
            print(f"Plot failed: {exc}")

        # Summary
        print("\n[SUMMARY]")
        for r in results:
            line = f"  {format_freq(r['freq_hz']):>16}  NF_sys={r['nf_system_db']:.2f} dB"
            if r.get('nf_dut_db') is not None and not np.isnan(r['nf_dut_db']):
                line += f"  NF_dut={r['nf_dut_db']:.2f} dB"
            print(line)

    except KeyboardInterrupt:
        print("\nInterrupted.")
        sys.exit(0)
    except ConnectionRefusedError as exc:
        print(f"\nCannot connect to SSA: {exc}")
        print("Verify the SSA is powered on and SCPI/LAN is enabled.")
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
        if ssa is not None:
            try:
                # Restore SSA to continuous sweep with a 100 kHz span
                ssa._send(':FREQ:SPAN 100000')
                ssa._send(':INIT:CONT ON')
                ssa.disconnect()
            except Exception:
                pass


if __name__ == "__main__":
    main()
