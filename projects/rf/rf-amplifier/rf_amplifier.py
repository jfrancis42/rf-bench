#!/usr/bin/env python3
"""
RF Amplifier Analyzer — Siglent SDG1062X + SSA3032X Plus

Measures RF amplifier gain, flatness, harmonic content, and 1 dB compression
point.  Two source modes:

  --source sdg  (default)  SDG CH1 → DUT input → SSA RF In
                           Frequency range: up to 60 MHz
  --source tg              SSA tracking generator → DUT input → SSA RF In
                           Frequency range: 9 kHz – 3.2 GHz

Usage:
  python rf_amplifier.py
  python rf_amplifier.py --start 1000 --stop 30000 --points 200
  python rf_amplifier.py --source tg --start 1000 --stop 500000
  python rf_amplifier.py --p1db --p1db-freq 14000
  python rf_amplifier.py --harmonics
  python rf_amplifier.py --p1db --harmonics --output lna_test
"""

import argparse
import json
import os
import sys
import time
from datetime import datetime

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np

# ---------------------------------------------------------------------------
# Siglent shared drivers
# ---------------------------------------------------------------------------

from rf_bench.siglent import SSA3000X, SDG1000X          # noqa: E402
from rf_bench.utils import (                              # noqa: E402
    format_freq, format_freq_short, nearest_rbw,
)

# ---------------------------------------------------------------------------
# Defaults
# ---------------------------------------------------------------------------

DEFAULT_SSA_HOST   = "10.1.1.60"
DEFAULT_SDG_HOST   = "10.1.1.55"
DEFAULT_INSTRUMENT_PORT = 5025
DEFAULT_START_KHZ  = 1_000       # 1 MHz
DEFAULT_STOP_KHZ   = 30_000      # 30 MHz
DEFAULT_POINTS     = 200
DEFAULT_INPUT_DBM  = -20.0
DEFAULT_TG_LEVEL   = 0.0         # dBm; SSA TG output when source=tg

# SDG CH1 source: 100 kHz span for narrow-band measurement
MEAS_SPAN_HZ       = 100_000     # 100 kHz span around signal frequency
MEAS_SETTLE_S      = 0.05        # settle time after SDG level/freq change

# P1dB sweep parameters
P1DB_SWEEP_START   = -40.0       # dBm
P1DB_SWEEP_STOP    = 0.0         # dBm
P1DB_SWEEP_STEP    = 1.0         # dB


# ---------------------------------------------------------------------------
# Helpers — local to this project
# ---------------------------------------------------------------------------

def _nearest_rbw_for_span(span_hz: float, points: int) -> int:
    """Select an appropriate RBW for the given span and point count."""
    target = max(1_000, span_hz / points * 3)
    return nearest_rbw(target)


def _measure_peak_dbm(ssa: SSA3000X, center_hz: float, span_hz: float = MEAS_SPAN_HZ,
                      points: int = 201) -> float:
    """
    Configure SSA with a narrow span around center_hz, run a single sweep,
    and return the peak power in dBm.
    """
    start_hz = int(center_hz - span_hz / 2)
    stop_hz  = int(center_hz + span_hz / 2)
    start_hz = max(9_000, start_hz)   # SSA minimum 9 kHz
    ssa.setup_band(start_hz, stop_hz, points)
    ssa.single_sweep()
    trace = ssa.get_trace()
    return float(np.max(trace))


def _setup_tg_sweep(ssa: SSA3000X, start_hz: int, stop_hz: int, points: int) -> int:
    """Enable TG, configure band, and return the RBW set."""
    tg_ok = ssa.enable_tracking_generator(DEFAULT_TG_LEVEL)
    if not tg_ok:
        print("  WARNING: TG state query returned unexpected value — check front panel.")
    return ssa.setup_band(start_hz, stop_hz, points)


# ---------------------------------------------------------------------------
# Gain sweep
# ---------------------------------------------------------------------------

def gain_sweep_sdg(ssa: SSA3000X, sdg: SDG1000X,
                   freqs_hz: np.ndarray, input_dbm: float,
                   harmonics: bool = False) -> dict:
    """
    Sweep gain using SDG CH1 as the source.

    Returns a dict with:
      freqs_hz        - frequency array (Hz)
      gain_db         - gain at each frequency (dB)
      output_dbm      - measured output power at each frequency (dBm)
      h2_dbm          - 2nd harmonic level (dBm), or NaN if not measured
      h3_dbm          - 3rd harmonic level (dBm), or NaN if not measured
    """
    n = len(freqs_hz)
    gain_db    = np.full(n, np.nan)
    output_dbm = np.full(n, np.nan)
    h2_dbm     = np.full(n, np.nan)
    h3_dbm     = np.full(n, np.nan)

    print(f"\n[GAIN SWEEP — SDG source, {input_dbm:+.0f} dBm input]")
    print(f"  {n} points from {format_freq_short(freqs_hz[0])} "
          f"to {format_freq_short(freqs_hz[-1])}")

    sdg.set_sine(1, freqs_hz[0], input_dbm)
    sdg.output_on(1)
    time.sleep(0.2)

    for i, freq_hz in enumerate(freqs_hz):
        sdg.set_sine(1, freq_hz, input_dbm)
        time.sleep(MEAS_SETTLE_S)

        out = _measure_peak_dbm(ssa, freq_hz)
        gain_db[i]    = out - input_dbm
        output_dbm[i] = out

        # Harmonics: measure 2nd and 3rd harmonic with SSA narrow span
        if harmonics:
            f2 = 2.0 * freq_hz
            f3 = 3.0 * freq_hz
            ssa_max = 3_200_000_000.0  # SSA3032X Plus max freq
            if f2 <= ssa_max:
                h2_dbm[i] = _measure_peak_dbm(ssa, f2)
            if f3 <= ssa_max:
                h3_dbm[i] = _measure_peak_dbm(ssa, f3)

        # Progress indicator: every 10% or every 10 points
        if (i + 1) % max(1, n // 10) == 0 or i == n - 1:
            pct = (i + 1) / n * 100
            print(f"  [{pct:3.0f}%] {format_freq_short(freq_hz):>10}  "
                  f"gain={gain_db[i]:+.1f} dB  out={output_dbm[i]:.1f} dBm",
                  flush=True)

    sdg.output_off(1)

    return dict(
        freqs_hz=freqs_hz,
        gain_db=gain_db,
        output_dbm=output_dbm,
        h2_dbm=h2_dbm,
        h3_dbm=h3_dbm,
    )


def gain_sweep_tg(ssa: SSA3000X,
                  start_hz: int, stop_hz: int, points: int,
                  input_dbm: float) -> dict:
    """
    Sweep gain using SSA tracking generator as the source.

    The TG level is set to DEFAULT_TG_LEVEL (0 dBm).  Gain is computed as
    output_trace − TG_level.  Returns same structure as gain_sweep_sdg
    (no harmonic data in TG mode — sweep is broadband, not narrowband).
    """
    print(f"\n[GAIN SWEEP — TG source, TG={DEFAULT_TG_LEVEL:+.0f} dBm]")
    print(f"  {points} points from {format_freq_short(start_hz)} "
          f"to {format_freq_short(stop_hz)}")

    _setup_tg_sweep(ssa, start_hz, stop_hz, points)
    ok    = ssa.single_sweep()
    trace = ssa.get_trace()
    if not ok:
        print("  WARNING: *OPC timeout — sweep data may be incomplete.")

    actual_pts = len(trace)
    freqs_hz   = np.linspace(start_hz, stop_hz, actual_pts)
    gain_db    = trace - DEFAULT_TG_LEVEL
    output_dbm = trace

    print(f"  done ({actual_pts} pts)  "
          f"gain min/max: {np.min(gain_db):.1f}/{np.max(gain_db):.1f} dB")

    return dict(
        freqs_hz=freqs_hz,
        gain_db=gain_db,
        output_dbm=output_dbm,
        h2_dbm=np.full(actual_pts, np.nan),
        h3_dbm=np.full(actual_pts, np.nan),
    )


# ---------------------------------------------------------------------------
# 1 dB compression
# ---------------------------------------------------------------------------

def p1db_sweep(ssa: SSA3000X, sdg: SDG1000X,
               freq_hz: float,
               start_dbm: float = P1DB_SWEEP_START,
               stop_dbm:  float = P1DB_SWEEP_STOP,
               step_dbm:  float = P1DB_SWEEP_STEP) -> dict:
    """
    Sweep input power at a fixed frequency to find the 1 dB compression point.

    Returns a dict with:
      freq_hz      - measurement frequency (Hz)
      input_dbm    - input power array (dBm)
      output_dbm   - measured output power at each input level (dBm)
      gain_db      - gain at each point (dB)
      small_signal_gain  - gain at lowest measurable input power (dB)
      p1db_input   - input power at P1dB (dBm), or None if not reached
      p1db_output  - output power at P1dB (dBm), or None
    """
    input_powers = np.arange(start_dbm, stop_dbm + step_dbm / 2, step_dbm)
    n = len(input_powers)

    output_dbm = np.full(n, np.nan)
    gain_db    = np.full(n, np.nan)

    print(f"\n[P1dB SWEEP @ {format_freq_short(freq_hz)}]")
    print(f"  Sweeping {start_dbm:+.0f} to {stop_dbm:+.0f} dBm in {step_dbm:.0f} dB steps")

    sdg.set_sine(1, freq_hz, input_powers[0])
    sdg.output_on(1)
    time.sleep(0.2)

    for i, pin in enumerate(input_powers):
        sdg.set_level(1, pin)
        time.sleep(MEAS_SETTLE_S)

        pout           = _measure_peak_dbm(ssa, freq_hz)
        output_dbm[i]  = pout
        gain_db[i]     = pout - pin

        print(f"  Pin={pin:+5.1f} dBm  Pout={pout:+5.1f} dBm  G={gain_db[i]:+.1f} dB",
              flush=True)

    sdg.output_off(1)

    # Determine small-signal gain from the first few points where gain is stable
    # Find the first 5 points that are valid
    valid = ~np.isnan(gain_db)
    if np.sum(valid) >= 3:
        small_sig = float(np.median(gain_db[valid][:5]))
    else:
        small_sig = float(np.nanmedian(gain_db))

    # Find P1dB: first point where gain has dropped by 1 dB from small-signal value
    p1db_input  = None
    p1db_output = None
    for i in range(len(gain_db)):
        if not np.isnan(gain_db[i]) and gain_db[i] <= small_sig - 1.0:
            # Interpolate between the previous point and this one for better accuracy
            if i > 0 and not np.isnan(gain_db[i - 1]):
                # Linear interpolation
                g0, g1 = gain_db[i - 1], gain_db[i]
                p0, p1 = input_powers[i - 1], input_powers[i]
                target = small_sig - 1.0
                frac   = (target - g0) / (g1 - g0)
                p1db_input  = float(p0 + frac * (p1 - p0))
                p1db_output = float(p1db_input + target)
            else:
                p1db_input  = float(input_powers[i])
                p1db_output = float(output_dbm[i])
            break

    if p1db_input is not None:
        print(f"  P1dB input  = {p1db_input:+.1f} dBm")
        print(f"  P1dB output = {p1db_output:+.1f} dBm")
        print(f"  Small-signal gain = {small_sig:.1f} dB")
    else:
        print(f"  P1dB not reached in this input range (max input = {stop_dbm:+.0f} dBm)")
        print(f"  Small-signal gain = {small_sig:.1f} dB")

    return dict(
        freq_hz=freq_hz,
        input_dbm=input_powers,
        output_dbm=output_dbm,
        gain_db=gain_db,
        small_signal_gain=small_sig,
        p1db_input=p1db_input,
        p1db_output=p1db_output,
    )


# ---------------------------------------------------------------------------
# Plotting
# ---------------------------------------------------------------------------

def plot_gain(sweep: dict, output_prefix: str, source: str, input_dbm: float) -> str:
    """Generate gain vs frequency plot.  Returns the saved file path."""
    freqs_mhz = sweep['freqs_hz'] / 1e6
    gain_db   = sweep['gain_db']
    h2_dbm    = sweep['h2_dbm']
    h3_dbm    = sweep['h3_dbm']

    has_harmonics = not np.all(np.isnan(h2_dbm))

    nrows = 2 if has_harmonics else 1
    fig, axes = plt.subplots(nrows, 1, figsize=(10, 4 * nrows), sharex=True)
    if nrows == 1:
        axes = [axes]

    # --- Gain panel ---
    ax = axes[0]
    valid = ~np.isnan(gain_db)
    ax.plot(freqs_mhz[valid], gain_db[valid], color='#1f77b4', linewidth=1.5,
            label='Gain')

    if np.any(valid):
        gmin = float(np.nanmin(gain_db))
        gmax = float(np.nanmax(gain_db))
        gmed = float(np.nanmedian(gain_db))
        flatness = gmax - gmin

        ax.axhline(gmed, color='gray', linestyle='--', linewidth=0.8,
                   label=f'Median {gmed:+.1f} dB')
        ax.axhline(gmax, color='green', linestyle=':', linewidth=0.8, alpha=0.7)
        ax.axhline(gmin, color='red',   linestyle=':', linewidth=0.8, alpha=0.7)

        # Annotation box
        textstr = (f"Min: {gmin:+.1f} dB\n"
                   f"Max: {gmax:+.1f} dB\n"
                   f"Flatness: {flatness:.1f} dB p-p\n"
                   f"Median: {gmed:+.1f} dB")
        ax.text(0.02, 0.97, textstr, transform=ax.transAxes,
                fontsize=8, verticalalignment='top',
                bbox=dict(boxstyle='round', facecolor='wheat', alpha=0.8))

    src_label = f"SDG CH1, {input_dbm:+.0f} dBm" if source == 'sdg' else "SSA TG (broadband)"
    ax.set_ylabel("Gain (dB)", fontsize=10)
    ax.set_title(
        f"RF Amplifier Gain  —  {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
        f"Source: {src_label}  |  "
        f"{format_freq_short(sweep['freqs_hz'][0])} – {format_freq_short(sweep['freqs_hz'][-1])}",
        fontsize=10,
    )
    ax.grid(True, alpha=0.35)
    ax.legend(fontsize=8, loc='upper right')
    ax.tick_params(labelsize=9)

    # --- Harmonics panel ---
    if has_harmonics:
        ax2 = axes[1]
        valid2 = ~np.isnan(h2_dbm)
        valid3 = ~np.isnan(h3_dbm)
        if np.any(valid2):
            ax2.plot(freqs_mhz[valid2], h2_dbm[valid2],
                     color='darkorange', linewidth=1.2, label='2nd harmonic')
        if np.any(valid3):
            ax2.plot(freqs_mhz[valid3], h3_dbm[valid3],
                     color='red', linewidth=1.2, label='3rd harmonic')

        # Output fundamental for reference
        out_valid = ~np.isnan(sweep['output_dbm'])
        if np.any(out_valid):
            ax2.plot(freqs_mhz[out_valid], sweep['output_dbm'][out_valid],
                     color='#1f77b4', linewidth=1.0, linestyle='--',
                     alpha=0.6, label='Fundamental (output)')

        ax2.set_ylabel("Level (dBm)", fontsize=10)
        ax2.set_xlabel("Frequency (MHz)", fontsize=10)
        ax2.set_title("Harmonic Content", fontsize=10)
        ax2.grid(True, alpha=0.35)
        ax2.legend(fontsize=8)
        ax2.tick_params(labelsize=9)
    else:
        axes[-1].set_xlabel("Frequency (MHz)", fontsize=10)

    plt.tight_layout()
    path = f"{output_prefix}_gain.png"
    plt.savefig(path, dpi=150, bbox_inches='tight')
    plt.close(fig)
    return path


def plot_p1db(p1db_result: dict, output_prefix: str) -> str:
    """Generate P1dB (gain compression) plot.  Returns the saved file path."""
    input_dbm  = p1db_result['input_dbm']
    gain_db    = p1db_result['gain_db']
    output_dbm = p1db_result['output_dbm']
    ssg        = p1db_result['small_signal_gain']
    p1db_in    = p1db_result['p1db_input']
    p1db_out   = p1db_result['p1db_output']
    freq_hz    = p1db_result['freq_hz']

    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(8, 8), sharex=True)

    valid = ~np.isnan(gain_db)

    # --- Gain vs input power panel ---
    ax1.plot(input_dbm[valid], gain_db[valid], 'o-', color='#1f77b4',
             markersize=4, linewidth=1.5, label='Measured gain')
    ax1.axhline(ssg,       color='green', linestyle='--', linewidth=1.0,
                label=f'Small-signal gain ({ssg:.1f} dB)')
    ax1.axhline(ssg - 1.0, color='red',   linestyle='--', linewidth=1.0,
                label=f'P1dB level ({ssg - 1.0:.1f} dB)')

    if p1db_in is not None:
        ax1.axvline(p1db_in, color='darkorange', linestyle='-.',
                    linewidth=1.2, label=f'P1dB = {p1db_in:+.1f} dBm in')
        ax1.plot(p1db_in, ssg - 1.0, 'r*', markersize=14,
                 label=f'P1dB = {p1db_in:+.1f} dBm in / {p1db_out:+.1f} dBm out')

    ax1.set_ylabel("Gain (dB)", fontsize=10)
    ax1.set_title(
        f"1 dB Compression Point @ {format_freq_short(freq_hz)}\n"
        f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        fontsize=10,
    )
    ax1.grid(True, alpha=0.35)
    ax1.legend(fontsize=8)
    ax1.tick_params(labelsize=9)

    # --- Output power vs input power panel ---
    out_valid = ~np.isnan(output_dbm)
    ax2.plot(input_dbm[out_valid], output_dbm[out_valid], 's-', color='darkorange',
             markersize=4, linewidth=1.5, label='Measured Pout')

    # Ideal linear extension
    if np.any(valid) and np.sum(valid) >= 2:
        # Use first 5 points for the linear reference
        n_lin = min(5, np.sum(valid))
        lin_idx = np.where(valid)[0][:n_lin]
        ideal_out = input_dbm + ssg
        ax2.plot(input_dbm, ideal_out, 'k--', linewidth=1.0, alpha=0.5,
                 label='Ideal linear (small-signal gain)')

    if p1db_in is not None and p1db_out is not None:
        ax2.axvline(p1db_in, color='darkorange', linestyle='-.', linewidth=1.2)
        ax2.plot(p1db_in, p1db_out, 'r*', markersize=14,
                 label=f'P1dB = {p1db_in:+.1f} dBm in\n        {p1db_out:+.1f} dBm out')

    ax2.set_xlabel("Input Power (dBm)", fontsize=10)
    ax2.set_ylabel("Output Power (dBm)", fontsize=10)
    ax2.set_title("Output Power vs Input Power", fontsize=10)
    ax2.grid(True, alpha=0.35)
    ax2.legend(fontsize=8)
    ax2.tick_params(labelsize=9)

    plt.tight_layout()
    path = f"{output_prefix}_p1db.png"
    plt.savefig(path, dpi=150, bbox_inches='tight')
    plt.close(fig)
    return path


# ---------------------------------------------------------------------------
# Text report
# ---------------------------------------------------------------------------

def save_gain_txt(sweep: dict, output_prefix: str,
                  source: str, input_dbm: float) -> str:
    """Write a text table of the gain sweep results."""
    path = f"{output_prefix}_gain.txt"
    freqs  = sweep['freqs_hz']
    gain   = sweep['gain_db']
    output = sweep['output_dbm']
    h2     = sweep['h2_dbm']
    h3     = sweep['h3_dbm']

    has_h = not np.all(np.isnan(h2))
    valid  = ~np.isnan(gain)

    ts  = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    sep = "=" * 78
    lines = [
        sep,
        "  RF AMPLIFIER GAIN SWEEP REPORT",
        f"  Generated : {ts}",
        f"  Source    : {'SDG CH1, ' + f'{input_dbm:+.0f} dBm' if source == 'sdg' else 'SSA Tracking Generator'}",
        f"  Frequency : {format_freq(freqs[0])} – {format_freq(freqs[-1])}",
        f"  Points    : {len(freqs)}",
        sep,
        "",
    ]

    if np.any(valid):
        gmin     = float(np.nanmin(gain))
        gmax     = float(np.nanmax(gain))
        gmed     = float(np.nanmedian(gain))
        flatness = gmax - gmin
        fmin_idx = int(np.nanargmin(gain))
        fmax_idx = int(np.nanargmax(gain))
        lines += [
            f"  Gain (min)  : {gmin:+.2f} dB  @ {format_freq(freqs[fmin_idx])}",
            f"  Gain (max)  : {gmax:+.2f} dB  @ {format_freq(freqs[fmax_idx])}",
            f"  Gain (med)  : {gmed:+.2f} dB",
            f"  Flatness    : {flatness:.2f} dB p-p",
            "",
        ]

    # Table header
    if has_h:
        lines.append(
            f"{'Frequency':>16}  {'Gain':>8}  {'Pout':>8}  {'H2':>8}  {'H3':>8}"
        )
        lines.append("-" * 56)
    else:
        lines.append(f"{'Frequency':>16}  {'Gain':>8}  {'Pout':>8}")
        lines.append("-" * 36)

    for i in range(len(freqs)):
        freq_str = format_freq(freqs[i])
        g_str    = f"{gain[i]:+7.2f} dB"   if not np.isnan(gain[i])   else "      N/A"
        p_str    = f"{output[i]:+6.1f} dBm" if not np.isnan(output[i]) else "     N/A"
        if has_h:
            h2_str = f"{h2[i]:+6.1f} dBm" if not np.isnan(h2[i]) else "     N/A"
            h3_str = f"{h3[i]:+6.1f} dBm" if not np.isnan(h3[i]) else "     N/A"
            lines.append(f"{freq_str:>16}  {g_str}  {p_str}  {h2_str}  {h3_str}")
        else:
            lines.append(f"{freq_str:>16}  {g_str}  {p_str}")

    text = "\n".join(lines) + "\n"
    with open(path, "w") as fh:
        fh.write(text)
    return path


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="RF Amplifier Analyzer — gain, flatness, harmonics, P1dB",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Setup:
  SDG mode (default): SDG CH1 OUT → DUT input → SSA RF In
  TG mode (--source tg): SSA TG OUT → DUT input → SSA RF In

Examples:
  python rf_amplifier.py                              # HF gain sweep (SDG)
  python rf_amplifier.py --start 1000 --stop 200000  # up to 200 MHz
  python rf_amplifier.py --source tg --stop 3200000  # full SSA range with TG
  python rf_amplifier.py --p1db --p1db-freq 14000    # P1dB on 40m
  python rf_amplifier.py --harmonics                 # measure 2nd/3rd harmonics
  python rf_amplifier.py --p1db --harmonics --input-dbm -30
""",
    )

    parser.add_argument("--start",       type=float, default=DEFAULT_START_KHZ,
                        metavar="KHZ",  help=f"Start frequency in kHz (default {DEFAULT_START_KHZ})")
    parser.add_argument("--stop",        type=float, default=DEFAULT_STOP_KHZ,
                        metavar="KHZ",  help=f"Stop frequency in kHz (default {DEFAULT_STOP_KHZ})")
    parser.add_argument("--points",      type=int,   default=DEFAULT_POINTS,
                        metavar="N",    help=f"Sweep points (default {DEFAULT_POINTS})")
    parser.add_argument("--input-dbm",   type=float, default=DEFAULT_INPUT_DBM,
                        metavar="DBM",  help=f"SDG input level in dBm (default {DEFAULT_INPUT_DBM})")
    parser.add_argument("--source",      choices=["sdg", "tg"], default="sdg",
                        help="Signal source: sdg (SDG function gen) or tg (SSA tracking gen)")
    parser.add_argument("--p1db",        action="store_true",
                        help="Measure 1 dB compression point (SDG mode only)")
    parser.add_argument("--p1db-freq",   type=float, default=None,
                        metavar="KHZ",  help="Frequency for P1dB measurement (default: sweep midpoint)")
    parser.add_argument("--harmonics",   action="store_true",
                        help="Measure 2nd and 3rd harmonic levels at each frequency (SDG mode only)")
    parser.add_argument("--sdg-host",    default=DEFAULT_SDG_HOST, metavar="HOST",
                        help=f"SDG IP address (default {DEFAULT_SDG_HOST})")
    parser.add_argument("--ssa-host",    default=DEFAULT_SSA_HOST, metavar="HOST",
                        help=f"SSA IP address (default {DEFAULT_SSA_HOST})")
    parser.add_argument("--output",      default=None, metavar="PREFIX",
                        help="Output filename prefix (default: timestamped)")

    args = parser.parse_args()

    if args.output is None:
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        args.output = f"rf_amplifier_{ts}"

    start_hz = int(args.start * 1_000)
    stop_hz  = int(args.stop  * 1_000)

    if start_hz >= stop_hz:
        print("Error: --start must be less than --stop")
        sys.exit(1)

    if args.source == "sdg" and stop_hz > 60_000_000:
        print(f"Warning: SDG1062X maximum frequency is 60 MHz. "
              f"Requested stop {format_freq_short(stop_hz)} exceeds this.")
        print("Consider --source tg for frequencies above 60 MHz.")

    if args.p1db and args.source == "tg":
        print("Error: --p1db requires --source sdg (broadband TG cannot sweep input power)")
        sys.exit(1)

    if args.harmonics and args.source == "tg":
        print("Warning: --harmonics has no effect in TG mode (broadband sweep)")
        args.harmonics = False

    p1db_freq_hz = None
    if args.p1db:
        if args.p1db_freq is not None:
            p1db_freq_hz = args.p1db_freq * 1_000
        else:
            p1db_freq_hz = (start_hz + stop_hz) / 2.0
        print(f"P1dB frequency: {format_freq_short(p1db_freq_hz)}")

    # Build logarithmically spaced frequency array for SDG mode; linear for TG
    if args.source == "sdg":
        freqs_hz = np.geomspace(start_hz, stop_hz, args.points)
    else:
        freqs_hz = np.linspace(start_hz, stop_hz, args.points)

    # Connect instruments
    ssa = sdg = None
    try:
        print(f"Connecting to SSA @ {args.ssa_host} ...")
        ssa = SSA3000X(args.ssa_host)
        print(f"  {ssa.identify()}")

        if args.source == "sdg" or args.p1db:
            print(f"Connecting to SDG @ {args.sdg_host} ...")
            sdg = SDG1000X(args.sdg_host)
            print(f"  {sdg.identify()}")

        # Ensure TG is off when using SDG mode
        if args.source == "sdg":
            ssa.disable_tracking_generator()
        else:
            ssa.enable_tracking_generator(DEFAULT_TG_LEVEL)

        # --- Gain sweep ---
        if args.source == "sdg":
            sweep = gain_sweep_sdg(ssa, sdg, freqs_hz, args.input_dbm,
                                   harmonics=args.harmonics)
        else:
            sweep = gain_sweep_tg(ssa, start_hz, stop_hz, args.points, args.input_dbm)

        # --- P1dB sweep ---
        p1db_result = None
        if args.p1db:
            p1db_result = p1db_sweep(ssa, sdg, p1db_freq_hz)

        # --- Outputs ---
        print("\n[SAVING RESULTS]")

        txt_path = save_gain_txt(sweep, args.output, args.source, args.input_dbm)
        print(f"Text   → {txt_path}")

        # JSON (for post-processing / re-plotting)
        json_path = f"{args.output}_gain.json"
        json_data = {
            "timestamp":  datetime.now().isoformat(),
            "ssa_host":   args.ssa_host,
            "sdg_host":   args.sdg_host if args.source == "sdg" else None,
            "source":     args.source,
            "input_dbm":  args.input_dbm,
            "start_hz":   start_hz,
            "stop_hz":    stop_hz,
            "freqs_hz":   sweep['freqs_hz'].tolist(),
            "gain_db":    [x if not np.isnan(x) else None for x in sweep['gain_db']],
            "output_dbm": [x if not np.isnan(x) else None for x in sweep['output_dbm']],
        }
        if p1db_result:
            json_data["p1db"] = {
                "freq_hz":          p1db_result['freq_hz'],
                "small_signal_gain": p1db_result['small_signal_gain'],
                "p1db_input_dbm":   p1db_result['p1db_input'],
                "p1db_output_dbm":  p1db_result['p1db_output'],
                "input_dbm":        p1db_result['input_dbm'].tolist(),
                "output_dbm":       [x if not np.isnan(x) else None
                                     for x in p1db_result['output_dbm']],
                "gain_db":          [x if not np.isnan(x) else None
                                     for x in p1db_result['gain_db']],
            }
        with open(json_path, "w") as jf:
            json.dump(json_data, jf, indent=2)
        print(f"JSON   → {json_path}")

        try:
            png_path = plot_gain(sweep, args.output, args.source, args.input_dbm)
            print(f"Plot   → {png_path}")
        except Exception as exc:
            print(f"Gain plot failed: {exc}")

        if p1db_result:
            try:
                p1db_png = plot_p1db(p1db_result, args.output)
                print(f"P1dB   → {p1db_png}")
            except Exception as exc:
                print(f"P1dB plot failed: {exc}")

        # Print summary
        valid = ~np.isnan(sweep['gain_db'])
        if np.any(valid):
            print(f"\nGain: {np.nanmin(sweep['gain_db']):+.1f} to "
                  f"{np.nanmax(sweep['gain_db']):+.1f} dB  "
                  f"(flatness {np.nanmax(sweep['gain_db']) - np.nanmin(sweep['gain_db']):.1f} dB p-p)")
        if p1db_result and p1db_result['p1db_input'] is not None:
            print(f"P1dB:  {p1db_result['p1db_input']:+.1f} dBm in  /  "
                  f"{p1db_result['p1db_output']:+.1f} dBm out  "
                  f"@ {format_freq_short(p1db_result['freq_hz'])}")

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
        if ssa is not None:
            try:
                ssa.disable_tracking_generator()
                ssa.disconnect()
            except Exception:
                pass
        if sdg is not None:
            try:
                sdg.output_off_all()
                sdg.close()
            except Exception:
                pass


if __name__ == "__main__":
    main()
