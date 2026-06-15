#!/usr/bin/env python3
"""
sdg_cal.py — SDG1000X self-characterization tool

Uses the SSA3032X Plus to measure the SDG1000X's output level accuracy,
frequency flatness, harmonic content, level linearity, and two-channel
tracking.  Results feed an optional correction table saved to ~/.sdg_cal.json.

Usage examples:
  python sdg_cal.py --level-cal
  python sdg_cal.py --harmonics
  python sdg_cal.py --tracking
  python sdg_cal.py --all
  python sdg_cal.py --level-cal --start 100 --stop 60000 --points 50
  python sdg_cal.py --linearity
  python sdg_cal.py --all --save-correction
"""

import argparse
import json
import math
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

from rf_bench import connect                                    # noqa: E402
from rf_bench.utils import (                                    # noqa: E402
    format_freq, format_freq_short, nearest_rbw,
)

# ---------------------------------------------------------------------------
# Defaults
# ---------------------------------------------------------------------------

# Now uses inventory system - IPs configured in ~/.rf-bench/inventory.yaml
DEFAULT_SSA_HOST       = None
DEFAULT_SDG_HOST       = None

DEFAULT_REF_LEVEL_DBM  = -10.0
DEFAULT_START_KHZ      = 100
DEFAULT_STOP_KHZ       = 60_000
DEFAULT_POINTS         = 40

DEFAULT_LINEARITY_FREQ_KHZ   = 10_000
DEFAULT_LINEARITY_START_DBM  = -40.0
DEFAULT_LINEARITY_STOP_DBM   = 10.0

SSA_MAX_HZ             = 3_200_000_000.0   # SSA3032X Plus
MEAS_SETTLE_S          = 0.08              # settle time after SDG change
HARMONICS_SUBSET       = 10               # max frequency points for harmonics test
CAL_FILE               = os.path.expanduser("~/.sdg_cal.json")


# ---------------------------------------------------------------------------
# SSA measurement helper
# ---------------------------------------------------------------------------

def measure_peak_dbm(ssa: SSA3000X, center_hz: float,
                     span_hz: float = 100_000, points: int = 201) -> float:
    """
    Configure SSA with a narrow span around center_hz, run a single sweep,
    and return the peak power in dBm.
    """
    start = max(9_000, center_hz - span_hz / 2)
    stop  = center_hz + span_hz / 2
    ssa.setup_band(int(start), int(stop), points)
    ssa.single_sweep()
    trace = ssa.get_trace()
    return float(np.max(trace))


# ---------------------------------------------------------------------------
# Test 1: Level flatness calibration
# ---------------------------------------------------------------------------

def run_level_cal(ssa: SSA3000X, sdg: SDG1000X, args) -> dict:
    """
    Sweep SDG CH1 and CH2 across frequencies at a fixed reference level and
    measure actual output with the SSA.  Correction = ref_level - measured.
    """
    freqs_hz = np.geomspace(args.start * 1_000.0, args.stop * 1_000.0, args.points)
    ref_dbm  = args.ref_level
    n        = len(freqs_hz)

    print(f"\n[LEVEL FLATNESS — {ref_dbm:+.0f} dBm ref, "
          f"{format_freq_short(freqs_hz[0])} – {format_freq_short(freqs_hz[-1])}, "
          f"{n} points]")

    ch1_measured   = np.full(n, np.nan)
    ch2_measured   = np.full(n, np.nan)
    ch1_correction = np.full(n, np.nan)
    ch2_correction = np.full(n, np.nan)

    # --- CH1 sweep ---
    print("  CH1 sweep...")
    sdg.set_sine(1, freqs_hz[0], ref_dbm)
    sdg.output_on(1)
    sdg.output_off(2)
    time.sleep(0.2)

    for i, f in enumerate(freqs_hz):
        sdg.set_sine(1, f, ref_dbm)
        time.sleep(MEAS_SETTLE_S)
        meas = measure_peak_dbm(ssa, f)
        ch1_measured[i]   = meas
        ch1_correction[i] = ref_dbm - meas
        if (i + 1) % max(1, n // 8) == 0 or i == n - 1:
            pct = (i + 1) / n * 100
            print(f"  CH1 [{pct:3.0f}%] {format_freq_short(f):>10}  "
                  f"meas={meas:.2f} dBm  corr={ch1_correction[i]:+.2f} dB",
                  flush=True)

    sdg.output_off(1)

    # --- CH2 sweep ---
    print("  CH2 sweep...")
    sdg.set_sine(2, freqs_hz[0], ref_dbm)
    sdg.output_on(2)
    time.sleep(0.2)

    for i, f in enumerate(freqs_hz):
        sdg.set_sine(2, f, ref_dbm)
        time.sleep(MEAS_SETTLE_S)
        meas = measure_peak_dbm(ssa, f)
        ch2_measured[i]   = meas
        ch2_correction[i] = ref_dbm - meas
        if (i + 1) % max(1, n // 8) == 0 or i == n - 1:
            pct = (i + 1) / n * 100
            print(f"  CH2 [{pct:3.0f}%] {format_freq_short(f):>10}  "
                  f"meas={meas:.2f} dBm  corr={ch2_correction[i]:+.2f} dB",
                  flush=True)

    sdg.output_off(2)

    # Summary
    for ch, corr in (("CH1", ch1_correction), ("CH2", ch2_correction)):
        valid = ~np.isnan(corr)
        if np.any(valid):
            print(f"  {ch}: correction range "
                  f"{np.nanmin(corr):+.2f} to {np.nanmax(corr):+.2f} dB  "
                  f"(p-p = {np.nanmax(corr) - np.nanmin(corr):.2f} dB)")

    return dict(
        freqs_hz=freqs_hz,
        ref_dbm=ref_dbm,
        ch1_measured_dbm=ch1_measured,
        ch2_measured_dbm=ch2_measured,
        ch1_correction_db=ch1_correction,
        ch2_correction_db=ch2_correction,
    )


def plot_flatness(data: dict, prefix: str) -> str:
    freqs_mhz = data['freqs_hz'] / 1e6
    ch1 = data['ch1_correction_db']
    ch2 = data['ch2_correction_db']

    fig, ax = plt.subplots(figsize=(10, 5))
    v1 = ~np.isnan(ch1)
    v2 = ~np.isnan(ch2)

    if np.any(v1):
        ax.plot(freqs_mhz[v1], ch1[v1], color='#1f77b4', linewidth=1.5,
                label=f"CH1 (p-p {np.nanmax(ch1)-np.nanmin(ch1):.2f} dB)")
    if np.any(v2):
        ax.plot(freqs_mhz[v2], ch2[v2], color='darkorange', linewidth=1.5,
                label=f"CH2 (p-p {np.nanmax(ch2)-np.nanmin(ch2):.2f} dB)")

    ax.axhline(0, color='gray', linestyle='--', linewidth=0.8, alpha=0.7)
    ax.set_xscale('log')
    ax.set_xlabel("Frequency (MHz)", fontsize=10)
    ax.set_ylabel("Level correction (dB)", fontsize=10)
    ax.set_title(
        f"SDG Level Flatness  @  {data['ref_dbm']:+.0f} dBm  —  "
        f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        fontsize=10,
    )
    ax.grid(True, which='both', alpha=0.25)
    ax.legend(fontsize=9)
    ax.tick_params(labelsize=9)

    plt.tight_layout()
    path = f"{prefix}_flatness.png"
    plt.savefig(path, dpi=150, bbox_inches='tight')
    plt.close(fig)
    return path


def save_flatness_txt(data: dict, prefix: str) -> str:
    path = f"{prefix}_flatness.txt"
    ts   = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    sep  = "=" * 72
    lines = [
        sep,
        "  SDG LEVEL FLATNESS CALIBRATION",
        f"  Generated : {ts}",
        f"  Ref level : {data['ref_dbm']:+.0f} dBm",
        f"  Frequency : {format_freq(data['freqs_hz'][0])} – "
        f"{format_freq(data['freqs_hz'][-1])}",
        f"  Points    : {len(data['freqs_hz'])}",
        sep,
        "",
    ]
    for ch, corr in (("CH1", data['ch1_correction_db']),
                     ("CH2", data['ch2_correction_db'])):
        valid = ~np.isnan(corr)
        if np.any(valid):
            idx_min = int(np.nanargmin(corr))
            idx_max = int(np.nanargmax(corr))
            lines += [
                f"  {ch} correction min: {np.nanmin(corr):+.2f} dB  "
                f"@ {format_freq(data['freqs_hz'][idx_min])}",
                f"  {ch} correction max: {np.nanmax(corr):+.2f} dB  "
                f"@ {format_freq(data['freqs_hz'][idx_max])}",
                f"  {ch} p-p flatness : "
                f"{np.nanmax(corr) - np.nanmin(corr):.2f} dB",
                "",
            ]

    lines.append(
        f"  {'Frequency':>16}  {'CH1 meas':>10}  {'CH1 corr':>10}  "
        f"{'CH2 meas':>10}  {'CH2 corr':>10}"
    )
    lines.append("  " + "-" * 65)

    for i, f in enumerate(data['freqs_hz']):
        def _fmt(v):
            return f"{v:+8.2f} dBm" if not np.isnan(v) else "       N/A"
        def _fmtc(v):
            return f"{v:+8.2f} dB " if not np.isnan(v) else "       N/A"
        lines.append(
            f"  {format_freq(f):>16}  "
            f"{_fmt(data['ch1_measured_dbm'][i])}  "
            f"{_fmtc(data['ch1_correction_db'][i])}  "
            f"{_fmt(data['ch2_measured_dbm'][i])}  "
            f"{_fmtc(data['ch2_correction_db'][i])}"
        )

    with open(path, "w") as fh:
        fh.write("\n".join(lines) + "\n")
    return path


def save_flatness_json(data: dict, prefix: str) -> str:
    path = f"{prefix}_flatness.json"
    out = {
        "test":               "flatness",
        "timestamp":          datetime.now().isoformat(),
        "ref_dbm":            data['ref_dbm'],
        "freqs_hz":           data['freqs_hz'].tolist(),
        "ch1_measured_dbm":   [x if not np.isnan(x) else None
                               for x in data['ch1_measured_dbm']],
        "ch1_correction_db":  [x if not np.isnan(x) else None
                               for x in data['ch1_correction_db']],
        "ch2_measured_dbm":   [x if not np.isnan(x) else None
                               for x in data['ch2_measured_dbm']],
        "ch2_correction_db":  [x if not np.isnan(x) else None
                               for x in data['ch2_correction_db']],
    }
    with open(path, "w") as jf:
        json.dump(out, jf, indent=2)
    return path


# ---------------------------------------------------------------------------
# Test 2: Harmonic content
# ---------------------------------------------------------------------------

def run_harmonics(ssa: SSA3000X, sdg: SDG1000X, args) -> dict:
    """
    Measure 2nd and 3rd harmonic levels (dBc) at a subset of the flatness
    frequencies.
    """
    all_freqs = np.geomspace(args.start * 1_000.0, args.stop * 1_000.0, args.points)
    # Pick a subset (roughly evenly log-spaced)
    n_subset = min(HARMONICS_SUBSET, len(all_freqs))
    idx = np.round(np.linspace(0, len(all_freqs) - 1, n_subset)).astype(int)
    freqs_hz = all_freqs[idx]
    ref_dbm  = args.ref_level
    n        = len(freqs_hz)

    print(f"\n[HARMONIC CONTENT — {ref_dbm:+.0f} dBm, {n} frequency points]")

    fund_dbm = np.full(n, np.nan)
    h2_dbm   = np.full(n, np.nan)
    h3_dbm   = np.full(n, np.nan)
    h2_dbc   = np.full(n, np.nan)
    h3_dbc   = np.full(n, np.nan)

    sdg.set_sine(1, freqs_hz[0], ref_dbm)
    sdg.output_on(1)
    sdg.output_off(2)
    time.sleep(0.2)

    for i, f in enumerate(freqs_hz):
        sdg.set_sine(1, f, ref_dbm)
        time.sleep(MEAS_SETTLE_S)

        # Fundamental
        meas_f = measure_peak_dbm(ssa, f)
        fund_dbm[i] = meas_f

        # 2nd harmonic
        f2 = 2.0 * f
        if f2 <= SSA_MAX_HZ:
            meas_h2 = measure_peak_dbm(ssa, f2)
            h2_dbm[i] = meas_h2
            h2_dbc[i] = meas_h2 - meas_f
        else:
            h2_dbm[i] = np.nan
            h2_dbc[i] = np.nan

        # 3rd harmonic
        f3 = 3.0 * f
        if f3 <= SSA_MAX_HZ:
            meas_h3 = measure_peak_dbm(ssa, f3)
            h3_dbm[i] = meas_h3
            h3_dbc[i] = meas_h3 - meas_f
        else:
            h3_dbm[i] = np.nan
            h3_dbc[i] = np.nan

        h2_str = f"{h2_dbc[i]:+.1f} dBc" if not np.isnan(h2_dbc[i]) else "  N/A (>3.2 GHz)"
        h3_str = f"{h3_dbc[i]:+.1f} dBc" if not np.isnan(h3_dbc[i]) else "  N/A (>3.2 GHz)"
        flag   = "  *** CHECK" if (not np.isnan(h2_dbc[i]) and h2_dbc[i] > -30.0) or \
                                  (not np.isnan(h3_dbc[i]) and h3_dbc[i] > -30.0) else ""
        print(f"  {format_freq_short(f):>10}  fund={meas_f:.1f} dBm  "
              f"H2={h2_str}  H3={h3_str}{flag}",
              flush=True)

    sdg.output_off(1)

    return dict(
        freqs_hz=freqs_hz,
        ref_dbm=ref_dbm,
        fund_dbm=fund_dbm,
        h2_dbm=h2_dbm,
        h3_dbm=h3_dbm,
        h2_dbc=h2_dbc,
        h3_dbc=h3_dbc,
    )


def plot_harmonics(data: dict, prefix: str) -> str:
    freqs_hz = data['freqs_hz']
    h2_dbc   = data['h2_dbc']
    h3_dbc   = data['h3_dbc']
    n        = len(freqs_hz)

    fig, ax = plt.subplots(figsize=(10, 5))

    # Bar chart: H2 and H3 side by side at each frequency
    x = np.arange(n)
    width = 0.35

    h2_vals = np.where(np.isnan(h2_dbc), 0.0, h2_dbc)
    h3_vals = np.where(np.isnan(h3_dbc), 0.0, h3_dbc)

    bars_h2 = ax.bar(x - width / 2, h2_vals, width, label='H2 (dBc)',
                     color='steelblue', alpha=0.8)
    bars_h3 = ax.bar(x + width / 2, h3_vals, width, label='H3 (dBc)',
                     color='darkorange', alpha=0.8)

    # Reference lines
    ax.axhline(-30, color='red',   linestyle='--', linewidth=1.0, alpha=0.7,
               label='−30 dBc threshold')
    ax.axhline(-40, color='green', linestyle=':', linewidth=0.8, alpha=0.7,
               label='−40 dBc target')

    # X-axis labels
    labels = [format_freq_short(f) for f in freqs_hz]
    ax.set_xticks(x)
    ax.set_xticklabels(labels, rotation=35, ha='right', fontsize=7)

    ax.set_ylabel("Harmonic level (dBc)", fontsize=10)
    ax.set_title(
        f"SDG Harmonic Content  —  {data['ref_dbm']:+.0f} dBm  —  "
        f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        fontsize=10,
    )
    ax.grid(True, axis='y', alpha=0.3)
    ax.legend(fontsize=9)
    ax.tick_params(axis='y', labelsize=9)

    plt.tight_layout()
    path = f"{prefix}_harmonics.png"
    plt.savefig(path, dpi=150, bbox_inches='tight')
    plt.close(fig)
    return path


def save_harmonics_txt(data: dict, prefix: str) -> str:
    path = f"{prefix}_harmonics.txt"
    ts   = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    sep  = "=" * 72
    lines = [
        sep,
        "  SDG HARMONIC CONTENT",
        f"  Generated : {ts}",
        f"  SDG level : {data['ref_dbm']:+.0f} dBm",
        sep, "",
    ]

    for arr, name in ((data['h2_dbc'], 'H2'), (data['h3_dbc'], 'H3')):
        valid = arr[~np.isnan(arr)]
        if len(valid):
            worst_idx = int(np.argmax(arr[~np.isnan(arr)]))
            # Index into freqs
            valid_freqs = data['freqs_hz'][~np.isnan(arr)]
            lines += [
                f"  {name} worst : {np.max(valid):.1f} dBc  "
                f"@ {format_freq(valid_freqs[worst_idx])}",
            ]
    lines.append("")

    lines.append(
        f"  {'Frequency':>16}  {'Fund(dBm)':>11}  "
        f"{'H2(dBm)':>9}  {'H2(dBc)':>9}  {'H3(dBm)':>9}  {'H3(dBc)':>9}"
    )
    lines.append("  " + "-" * 72)

    def _f(v):
        return f"{v:+.1f}" if not np.isnan(v) else "  N/A"

    for i, f in enumerate(data['freqs_hz']):
        lines.append(
            f"  {format_freq(f):>16}  "
            f"{_f(data['fund_dbm'][i]):>11}  "
            f"{_f(data['h2_dbm'][i]):>9}  "
            f"{_f(data['h2_dbc'][i]):>9}  "
            f"{_f(data['h3_dbm'][i]):>9}  "
            f"{_f(data['h3_dbc'][i]):>9}"
        )

    with open(path, "w") as fh:
        fh.write("\n".join(lines) + "\n")
    return path


def save_harmonics_json(data: dict, prefix: str) -> str:
    path = f"{prefix}_harmonics.json"

    def _l(arr):
        return [x if not np.isnan(x) else None for x in arr]

    out = {
        "test":      "harmonics",
        "timestamp": datetime.now().isoformat(),
        "ref_dbm":   data['ref_dbm'],
        "freqs_hz":  data['freqs_hz'].tolist(),
        "fund_dbm":  _l(data['fund_dbm']),
        "h2_dbm":    _l(data['h2_dbm']),
        "h3_dbm":    _l(data['h3_dbm']),
        "h2_dbc":    _l(data['h2_dbc']),
        "h3_dbc":    _l(data['h3_dbc']),
    }
    with open(path, "w") as jf:
        json.dump(out, jf, indent=2)
    return path


# ---------------------------------------------------------------------------
# Test 3: Level linearity
# ---------------------------------------------------------------------------

def run_linearity(ssa: SSA3000X, sdg: SDG1000X, args) -> dict:
    """
    Sweep SDG CH1 output level at a fixed frequency and measure actual power
    with the SSA.  Detects the 1 dB compression / roll-off point.
    """
    freq_hz    = args.linearity_freq * 1_000.0
    start_dbm  = args.linearity_start
    stop_dbm   = args.linearity_stop

    # 1 dB steps
    set_levels = np.arange(start_dbm, stop_dbm + 0.5, 1.0)
    n          = len(set_levels)

    print(f"\n[LEVEL LINEARITY @ {format_freq_short(freq_hz)}  "
          f"{start_dbm:+.0f} → {stop_dbm:+.0f} dBm, {n} steps]")

    meas_dbm = np.full(n, np.nan)
    error_db = np.full(n, np.nan)

    sdg.set_sine(1, freq_hz, set_levels[0])
    sdg.output_on(1)
    sdg.output_off(2)
    time.sleep(0.2)

    for i, level in enumerate(set_levels):
        sdg.set_level(1, level)
        time.sleep(MEAS_SETTLE_S)
        meas = measure_peak_dbm(ssa, freq_hz)
        meas_dbm[i] = meas
        error_db[i] = meas - level
        print(f"  set={level:+6.1f} dBm  meas={meas:+6.1f} dBm  "
              f"err={error_db[i]:+.2f} dB",
              flush=True)

    sdg.output_off(1)

    # Find small-signal gain offset from first few valid points
    valid = ~np.isnan(error_db)
    if np.sum(valid) >= 3:
        ss_offset = float(np.median(error_db[valid][:5]))
    else:
        ss_offset = float(np.nanmedian(error_db))

    # Find 1 dB compression: first point where error drops 1 dB below ss_offset
    p1db_set = None
    for i in range(len(error_db)):
        if not np.isnan(error_db[i]) and error_db[i] <= ss_offset - 1.0:
            if i > 0 and not np.isnan(error_db[i - 1]):
                g0, g1 = error_db[i - 1], error_db[i]
                p0, p1 = set_levels[i - 1], set_levels[i]
                target = ss_offset - 1.0
                frac   = (target - g0) / (g1 - g0)
                p1db_set = float(p0 + frac * (p1 - p0))
            else:
                p1db_set = float(set_levels[i])
            break

    if p1db_set is not None:
        print(f"  1 dB compression (set level): {p1db_set:+.1f} dBm")
        print(f"  Small-signal offset: {ss_offset:+.2f} dB")
    else:
        print(f"  1 dB compression not reached in this range.")
        print(f"  Small-signal offset: {ss_offset:+.2f} dB")

    return dict(
        freq_hz=freq_hz,
        set_levels_dbm=set_levels,
        meas_dbm=meas_dbm,
        error_db=error_db,
        ss_offset_db=ss_offset,
        p1db_set_dbm=p1db_set,
    )


def plot_linearity(data: dict, prefix: str) -> str:
    set_lvl = data['set_levels_dbm']
    meas    = data['meas_dbm']
    error   = data['error_db']
    offset  = data['ss_offset_db']
    p1db    = data['p1db_set_dbm']
    freq_hz = data['freq_hz']

    valid   = ~np.isnan(meas)
    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(9, 7), sharex=True)

    # --- Output power vs set level ---
    ax1.plot(set_lvl[valid], meas[valid], 'o-', color='#1f77b4',
             markersize=4, linewidth=1.5, label='Measured output')
    # Ideal (set level + ss_offset)
    ax1.plot(set_lvl, set_lvl + offset, 'k--', linewidth=0.9, alpha=0.5,
             label=f'Ideal (offset {offset:+.2f} dB)')

    if p1db is not None:
        ax1.axvline(p1db, color='red', linestyle='-.', linewidth=1.2,
                    label=f'P1dB set = {p1db:+.1f} dBm')

    ax1.set_ylabel("Measured output (dBm)", fontsize=10)
    ax1.set_title(
        f"SDG Level Linearity @ {format_freq_short(freq_hz)}  —  "
        f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        fontsize=10,
    )
    ax1.grid(True, alpha=0.35)
    ax1.legend(fontsize=8)
    ax1.tick_params(labelsize=9)

    # --- Error vs set level ---
    e_valid = ~np.isnan(error)
    ax2.plot(set_lvl[e_valid], error[e_valid], 's-', color='darkorange',
             markersize=4, linewidth=1.5, label='Error (actual − set)')
    ax2.axhline(offset,       color='gray',  linestyle='--', linewidth=0.8,
                label=f'SS offset ({offset:+.2f} dB)')
    ax2.axhline(offset - 1.0, color='red',   linestyle=':', linewidth=0.8,
                label=f'P1dB threshold ({offset-1.0:+.2f} dB)')

    if p1db is not None:
        ax2.axvline(p1db, color='red', linestyle='-.', linewidth=1.2)

    ax2.set_xlabel("Set level (dBm)", fontsize=10)
    ax2.set_ylabel("Error (dB)", fontsize=10)
    ax2.set_title("Level Error vs Set Level", fontsize=10)
    ax2.grid(True, alpha=0.35)
    ax2.legend(fontsize=8)
    ax2.tick_params(labelsize=9)

    plt.tight_layout()
    path = f"{prefix}_linearity.png"
    plt.savefig(path, dpi=150, bbox_inches='tight')
    plt.close(fig)
    return path


def save_linearity_txt(data: dict, prefix: str) -> str:
    path = f"{prefix}_linearity.txt"
    ts   = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    sep  = "=" * 60
    lines = [
        sep,
        "  SDG LEVEL LINEARITY",
        f"  Generated  : {ts}",
        f"  Frequency  : {format_freq(data['freq_hz'])}",
        f"  SS offset  : {data['ss_offset_db']:+.2f} dB",
        f"  P1dB (set) : "
        + (f"{data['p1db_set_dbm']:+.1f} dBm" if data['p1db_set_dbm'] else "not reached"),
        sep, "",
    ]
    lines.append(f"  {'Set(dBm)':>9}  {'Meas(dBm)':>11}  {'Error(dB)':>10}")
    lines.append("  " + "-" * 35)
    for i, s in enumerate(data['set_levels_dbm']):
        m = data['meas_dbm'][i]
        e = data['error_db'][i]
        m_str = f"{m:+.2f}" if not np.isnan(m) else "  N/A"
        e_str = f"{e:+.2f}" if not np.isnan(e) else "  N/A"
        lines.append(f"  {s:>9.1f}  {m_str:>11}  {e_str:>10}")

    with open(path, "w") as fh:
        fh.write("\n".join(lines) + "\n")
    return path


def save_linearity_json(data: dict, prefix: str) -> str:
    path = f"{prefix}_linearity.json"

    def _l(arr):
        return [x if not np.isnan(x) else None for x in arr]

    out = {
        "test":           "linearity",
        "timestamp":      datetime.now().isoformat(),
        "freq_hz":        data['freq_hz'],
        "set_levels_dbm": data['set_levels_dbm'].tolist(),
        "meas_dbm":       _l(data['meas_dbm']),
        "error_db":       _l(data['error_db']),
        "ss_offset_db":   data['ss_offset_db'],
        "p1db_set_dbm":   data['p1db_set_dbm'],
    }
    with open(path, "w") as jf:
        json.dump(out, jf, indent=2)
    return path


# ---------------------------------------------------------------------------
# Test 4: Two-channel tracking
# ---------------------------------------------------------------------------

def run_tracking(ssa: SSA3000X, sdg: SDG1000X, args) -> dict:
    """
    At each flatness frequency, measure CH1 and CH2 at the same set level
    and record the difference.  Ideal tracking: 0 dB everywhere.
    """
    freqs_hz = np.geomspace(args.start * 1_000.0, args.stop * 1_000.0, args.points)
    ref_dbm  = args.ref_level
    n        = len(freqs_hz)

    print(f"\n[CHANNEL TRACKING — {ref_dbm:+.0f} dBm, {n} points]")
    print("  (measuring CH1 and CH2 alternately at each frequency)\n")

    ch1_dbm  = np.full(n, np.nan)
    ch2_dbm  = np.full(n, np.nan)
    diff_db  = np.full(n, np.nan)

    for i, f in enumerate(freqs_hz):
        # CH1
        sdg.output_off(2)
        sdg.set_sine(1, f, ref_dbm)
        sdg.output_on(1)
        time.sleep(MEAS_SETTLE_S)
        p1 = measure_peak_dbm(ssa, f)
        ch1_dbm[i] = p1

        # CH2
        sdg.output_off(1)
        sdg.set_sine(2, f, ref_dbm)
        sdg.output_on(2)
        time.sleep(MEAS_SETTLE_S)
        p2 = measure_peak_dbm(ssa, f)
        ch2_dbm[i] = p2

        diff_db[i] = p1 - p2

        if (i + 1) % max(1, n // 8) == 0 or i == n - 1:
            pct = (i + 1) / n * 100
            print(f"  [{pct:3.0f}%] {format_freq_short(f):>10}  "
                  f"CH1={p1:.2f} dBm  CH2={p2:.2f} dBm  "
                  f"diff={diff_db[i]:+.2f} dB",
                  flush=True)

    sdg.output_off_all()

    valid = ~np.isnan(diff_db)
    if np.any(valid):
        print(f"\n  Tracking range: "
              f"{np.nanmin(diff_db):+.2f} to {np.nanmax(diff_db):+.2f} dB  "
              f"(p-p {np.nanmax(diff_db) - np.nanmin(diff_db):.2f} dB)")

    return dict(
        freqs_hz=freqs_hz,
        ref_dbm=ref_dbm,
        ch1_dbm=ch1_dbm,
        ch2_dbm=ch2_dbm,
        diff_db=diff_db,
    )


def plot_tracking(data: dict, prefix: str) -> str:
    freqs_mhz = data['freqs_hz'] / 1e6
    diff      = data['diff_db']
    valid     = ~np.isnan(diff)

    fig, ax = plt.subplots(figsize=(10, 4))

    if np.any(valid):
        ax.plot(freqs_mhz[valid], diff[valid], color='#2ca02c', linewidth=1.5,
                label='CH1 − CH2 (dB)')
        ax.axhline(0, color='gray', linestyle='--', linewidth=0.8, alpha=0.7)
        ax.axhline(+0.5, color='orange', linestyle=':', linewidth=0.8, alpha=0.8)
        ax.axhline(-0.5, color='orange', linestyle=':', linewidth=0.8, alpha=0.8,
                   label='±0.5 dB band')

    ax.set_xscale('log')
    ax.set_xlabel("Frequency (MHz)", fontsize=10)
    ax.set_ylabel("CH1 − CH2 (dB)", fontsize=10)
    ax.set_title(
        f"SDG Channel Tracking  @  {data['ref_dbm']:+.0f} dBm  —  "
        f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        fontsize=10,
    )
    ax.grid(True, which='both', alpha=0.25)
    ax.legend(fontsize=9)
    ax.tick_params(labelsize=9)

    plt.tight_layout()
    path = f"{prefix}_tracking.png"
    plt.savefig(path, dpi=150, bbox_inches='tight')
    plt.close(fig)
    return path


def save_tracking_txt(data: dict, prefix: str) -> str:
    path = f"{prefix}_tracking.txt"
    ts   = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    sep  = "=" * 60
    lines = [
        sep,
        "  SDG CHANNEL TRACKING",
        f"  Generated : {ts}",
        f"  Ref level : {data['ref_dbm']:+.0f} dBm",
        sep, "",
    ]
    valid = ~np.isnan(data['diff_db'])
    if np.any(valid):
        lines += [
            f"  Tracking range : "
            f"{np.nanmin(data['diff_db']):+.2f} to "
            f"{np.nanmax(data['diff_db']):+.2f} dB",
            f"  p-p deviation  : "
            f"{np.nanmax(data['diff_db']) - np.nanmin(data['diff_db']):.2f} dB",
            "",
        ]

    lines.append(
        f"  {'Frequency':>16}  {'CH1(dBm)':>10}  "
        f"{'CH2(dBm)':>10}  {'Diff(dB)':>10}"
    )
    lines.append("  " + "-" * 52)

    for i, f in enumerate(data['freqs_hz']):
        def _f(v):
            return f"{v:+.2f}" if not np.isnan(v) else "   N/A"
        lines.append(
            f"  {format_freq(f):>16}  "
            f"{_f(data['ch1_dbm'][i]):>10}  "
            f"{_f(data['ch2_dbm'][i]):>10}  "
            f"{_f(data['diff_db'][i]):>10}"
        )

    with open(path, "w") as fh:
        fh.write("\n".join(lines) + "\n")
    return path


def save_tracking_json(data: dict, prefix: str) -> str:
    path = f"{prefix}_tracking.json"

    def _l(arr):
        return [x if not np.isnan(x) else None for x in arr]

    out = {
        "test":      "tracking",
        "timestamp": datetime.now().isoformat(),
        "ref_dbm":   data['ref_dbm'],
        "freqs_hz":  data['freqs_hz'].tolist(),
        "ch1_dbm":   _l(data['ch1_dbm']),
        "ch2_dbm":   _l(data['ch2_dbm']),
        "diff_db":   _l(data['diff_db']),
    }
    with open(path, "w") as jf:
        json.dump(out, jf, indent=2)
    return path


# ---------------------------------------------------------------------------
# Correction table
# ---------------------------------------------------------------------------

def save_correction_table(flatness_data: dict) -> None:
    """Save correction table to ~/.sdg_cal.json."""
    ch1_pairs = [
        [float(f), float(c)]
        for f, c in zip(flatness_data['freqs_hz'], flatness_data['ch1_correction_db'])
        if not np.isnan(c)
    ]
    ch2_pairs = [
        [float(f), float(c)]
        for f, c in zip(flatness_data['freqs_hz'], flatness_data['ch2_correction_db'])
        if not np.isnan(c)
    ]

    cal = {
        "ch1_correction_dbm": ch1_pairs,
        "ch2_correction_dbm": ch2_pairs,
        "measured_at":        datetime.now().isoformat(),
        "ref_level_dbm":      flatness_data['ref_dbm'],
    }
    with open(CAL_FILE, "w") as jf:
        json.dump(cal, jf, indent=2)
    print(f"  Correction table saved to {CAL_FILE}")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="SDG1000X self-characterization — level flatness, harmonics, "
                    "linearity, channel tracking",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python sdg_cal.py --level-cal
  python sdg_cal.py --harmonics
  python sdg_cal.py --linearity
  python sdg_cal.py --tracking
  python sdg_cal.py --all
  python sdg_cal.py --all --save-correction
  python sdg_cal.py --level-cal --start 100 --stop 60000 --points 50
""",
    )

    # Instruments (now uses inventory - these args are kept for backward compat)
    parser.add_argument("--sdg",  default=DEFAULT_SDG_HOST, metavar="NAME",
                        help="SDG1000X inventory name (default: 'sdg' from inventory)")
    parser.add_argument("--ssa",  default=DEFAULT_SSA_HOST, metavar="NAME",
                        help="SSA3000X inventory name (default: 'ssa' from inventory)")

    # Test selection
    parser.add_argument("--level-cal",  action="store_true",
                        help="Run frequency flatness calibration")
    parser.add_argument("--harmonics",  action="store_true",
                        help="Run harmonic content measurement")
    parser.add_argument("--linearity",  action="store_true",
                        help="Run level accuracy vs set level at a fixed frequency")
    parser.add_argument("--tracking",   action="store_true",
                        help="Run two-channel level tracking (CH1 vs CH2)")
    parser.add_argument("--all",        action="store_true",
                        help="Run all tests")

    # Sweep parameters
    parser.add_argument("--ref-level",  type=float, default=DEFAULT_REF_LEVEL_DBM,
                        metavar="DBM",
                        help=f"Reference set level for flatness cal in dBm "
                             f"(default {DEFAULT_REF_LEVEL_DBM})")
    parser.add_argument("--start",      type=float, default=DEFAULT_START_KHZ,
                        metavar="KHZ",
                        help=f"Start frequency in kHz (default {DEFAULT_START_KHZ})")
    parser.add_argument("--stop",       type=float, default=DEFAULT_STOP_KHZ,
                        metavar="KHZ",
                        help=f"Stop frequency in kHz (default {DEFAULT_STOP_KHZ})")
    parser.add_argument("--points",     type=int,   default=DEFAULT_POINTS,
                        metavar="N",
                        help=f"Number of frequency points (default {DEFAULT_POINTS})")

    # Linearity parameters
    parser.add_argument("--linearity-freq",  type=float,
                        default=DEFAULT_LINEARITY_FREQ_KHZ, metavar="KHZ",
                        dest="linearity_freq",
                        help=f"Frequency for linearity test in kHz "
                             f"(default {DEFAULT_LINEARITY_FREQ_KHZ})")
    parser.add_argument("--linearity-start", type=float,
                        default=DEFAULT_LINEARITY_START_DBM, metavar="DBM",
                        dest="linearity_start",
                        help=f"Start level for linearity in dBm "
                             f"(default {DEFAULT_LINEARITY_START_DBM})")
    parser.add_argument("--linearity-stop",  type=float,
                        default=DEFAULT_LINEARITY_STOP_DBM, metavar="DBM",
                        dest="linearity_stop",
                        help=f"Stop level for linearity in dBm "
                             f"(default {DEFAULT_LINEARITY_STOP_DBM})")

    # Output
    parser.add_argument("--save-correction", action="store_true",
                        help=f"Save correction table to {CAL_FILE}")
    parser.add_argument("--output", default=None, metavar="PREFIX",
                        help="Output file prefix (default: timestamped)")

    args = parser.parse_args()

    if args.all:
        args.level_cal = True
        args.harmonics  = True
        args.linearity  = True
        args.tracking   = True

    if not any([args.level_cal, args.harmonics, args.linearity, args.tracking]):
        parser.error("Specify at least one test: "
                     "--level-cal, --harmonics, --linearity, --tracking, or --all")

    if args.start >= args.stop:
        print("Error: --start must be less than --stop")
        sys.exit(1)

    if args.output is None:
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        args.output = f"sdg_cal_{ts}"

    if args.save_correction and not args.level_cal:
        print("Warning: --save-correction requires --level-cal (or --all).  "
              "Enabling --level-cal.")
        args.level_cal = True

    # Connect instruments
    ssa = sdg = None
    try:
        inst_ssa = args.ssa if args.ssa else 'ssa'
        inst_sdg = args.sdg if args.sdg else 'sdg'

        print(f"Connecting to SSA3000X '{inst_ssa}' via inventory...")
        ssa = connect(inst_ssa)
        print(f"  {ssa.identify()}")

        print(f"Connecting to SDG1000X '{inst_sdg}' via inventory...")
        sdg = connect(inst_sdg)
        print(f"  {sdg.identify()}")

        # Ensure TG is off
        ssa.disable_tracking_generator()

        prefix = args.output

        # --- Level flatness ---
        if args.level_cal:
            flat_data = run_level_cal(ssa, sdg, args)

            print("\n[SAVING FLATNESS RESULTS]")
            p = save_flatness_txt(flat_data, prefix)
            print(f"  Text → {p}")
            p = save_flatness_json(flat_data, prefix)
            print(f"  JSON → {p}")
            try:
                p = plot_flatness(flat_data, prefix)
                print(f"  Plot → {p}")
            except Exception as exc:
                print(f"  Flatness plot failed: {exc}")

            if args.save_correction:
                save_correction_table(flat_data)
        else:
            flat_data = None

        # --- Harmonics ---
        if args.harmonics:
            harm_data = run_harmonics(ssa, sdg, args)

            print("\n[SAVING HARMONICS RESULTS]")
            p = save_harmonics_txt(harm_data, prefix)
            print(f"  Text → {p}")
            p = save_harmonics_json(harm_data, prefix)
            print(f"  JSON → {p}")
            try:
                p = plot_harmonics(harm_data, prefix)
                print(f"  Plot → {p}")
            except Exception as exc:
                print(f"  Harmonics plot failed: {exc}")

        # --- Linearity ---
        if args.linearity:
            lin_data = run_linearity(ssa, sdg, args)

            print("\n[SAVING LINEARITY RESULTS]")
            p = save_linearity_txt(lin_data, prefix)
            print(f"  Text → {p}")
            p = save_linearity_json(lin_data, prefix)
            print(f"  JSON → {p}")
            try:
                p = plot_linearity(lin_data, prefix)
                print(f"  Plot → {p}")
            except Exception as exc:
                print(f"  Linearity plot failed: {exc}")

        # --- Tracking ---
        if args.tracking:
            trk_data = run_tracking(ssa, sdg, args)

            print("\n[SAVING TRACKING RESULTS]")
            p = save_tracking_txt(trk_data, prefix)
            print(f"  Text → {p}")
            p = save_tracking_json(trk_data, prefix)
            print(f"  JSON → {p}")
            try:
                p = plot_tracking(trk_data, prefix)
                print(f"  Plot → {p}")
            except Exception as exc:
                print(f"  Tracking plot failed: {exc}")

        print(f"\nAll outputs saved with prefix: {prefix}")

    except KeyboardInterrupt:
        print("\nInterrupted.")
        sys.exit(0)
    except ConnectionRefusedError as exc:
        print(f"\nCannot connect to instrument: {exc}")
        print("Verify instruments are powered on and SCPI/LAN is enabled.")
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
        if sdg is not None:
            try:
                sdg.output_off_all()
                sdg.close()
            except Exception:
                pass
        if ssa is not None:
            try:
                ssa.disable_tracking_generator()
                ssa.disconnect()
            except Exception:
                pass


if __name__ == "__main__":
    main()
