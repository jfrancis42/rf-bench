#!/usr/bin/env python3
"""
EMI Source Finder — Siglent SSA3000X + SDS2000X Plus MSO

Identifies EMI emission sources by correlating spectrum analyzer peaks with
digital clock harmonics captured via the MSO probe pod.

Workflow:
  1. SSA sweeps the band and finds emission peaks above the noise floor.
  2. MSO captures all active digital clocks simultaneously.
  3. Each captured digital channel is analyzed: if its period is sufficiently
     stable (<5% jitter) it is classified as a clock.
  4. For each SSA peak, check if it matches any harmonic N × f_clock
     (N = 1 … --harmonic-max) within --harmonic-tol-ppm.
  5. Report: "Peak at 48.0 MHz matches 3rd harmonic of D3 (16.012 MHz)"

WARNING — MSO HARDWARE NOT TESTED:
  All MSO digital channel code is implemented from the Siglent SDS Series EN11F SCPI
  programming guide. The MSO probe pod hardware has NOT been physically tested. If
  digital captures return empty data: verify the MSO option is licensed, the pod is
  connected and powered, and the threshold is set correctly for the signal level.

Usage:
  # Full scan: SSA 100 kHz – 500 MHz + MSO D0–D7
  python emi_finder.py

  # SSA only (reconnaissance without scope):
  python emi_finder.py --ssa-only

  # MSO clock measurement only (no SSA):
  python emi_finder.py --mso-only

  # Custom frequency range and channels:
  python emi_finder.py --ssa-start-khz 1000 --ssa-stop-khz 200000 --digital-channels 0,1,2,3

  # Tune sensitivity:
  python emi_finder.py --noise-floor -70 --harmonic-tol-ppm 500

scipy is used for peak finding (find_peaks) and is optional. A simple fallback
peak finder is used when scipy is unavailable.
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
import matplotlib.ticker as mticker
import numpy as np

# ---------------------------------------------------------------------------
# Siglent shared drivers
# ---------------------------------------------------------------------------

from rf_bench.siglent import SSA3000X, SDS2000X                              # noqa: E402
from rf_bench.utils import format_freq, format_freq_short                    # noqa: E402
from rf_bench import connect

# scipy optional — used for spectrum peak finding and Gaussian fit
try:
    from scipy.signal import find_peaks as _scipy_find_peaks
    _SCIPY_OK = True
except ImportError:
    _SCIPY_OK = False

# ---------------------------------------------------------------------------
# Defaults
# ---------------------------------------------------------------------------

SSA_HOST         = "10.1.1.60"
SCOPE_HOST       = "10.1.1.58"
DEFAULT_START_KHZ  = 100
DEFAULT_STOP_KHZ   = 500_000      # 500 MHz
DEFAULT_CHANNELS   = list(range(8))   # D0–D7
DEFAULT_DURATION_S = 0.01             # 10 ms
DEFAULT_THRESHOLD  = "LVCMOS33"
DEFAULT_NOISE_FLOOR_DBM = -80.0
DEFAULT_HARMONIC_MAX    = 20
DEFAULT_HARMONIC_TOL_PPM = 1000.0    # 0.1%
DEFAULT_PEAK_PROMINENCE_DB = 6.0     # dB above surroundings (scipy only)
MIN_PEAK_SEPARATION_BINS   = 5       # bins — simple peak finder

THRESHOLD_CHOICES = ("ttl", "cmos", "lvcmos33", "lvcmos25")


# ---------------------------------------------------------------------------
# Simple peak finder fallback (no scipy)
# ---------------------------------------------------------------------------

def _find_peaks_simple(trace: np.ndarray, height_threshold: float,
                       min_separation_bins: int = MIN_PEAK_SEPARATION_BINS) -> np.ndarray:
    """
    Find local maxima above height_threshold with minimum separation.

    Simple O(n) algorithm: a point is a peak if it is ≥ both neighbors and
    above the threshold. Enforces minimum separation between peaks by keeping
    only the higher of two nearby peaks.
    """
    peaks = []
    n = len(trace)
    for i in range(1, n - 1):
        if trace[i] > height_threshold and trace[i] >= trace[i - 1] and trace[i] >= trace[i + 1]:
            if not peaks or i - peaks[-1] >= min_separation_bins:
                peaks.append(i)
            elif trace[i] > trace[peaks[-1]]:
                peaks[-1] = i   # replace with higher nearby peak
    return np.array(peaks, dtype=int)


def _find_spectrum_peaks(trace: np.ndarray, noise_floor_dbm: float) -> np.ndarray:
    """Return indices of peaks above noise_floor_dbm in the spectrum trace."""
    if _SCIPY_OK:
        peaks, _ = _scipy_find_peaks(
            trace,
            height=noise_floor_dbm,
            prominence=DEFAULT_PEAK_PROMINENCE_DB,
            distance=MIN_PEAK_SEPARATION_BINS,
        )
        return peaks
    return _find_peaks_simple(trace, noise_floor_dbm)


# ---------------------------------------------------------------------------
# SSA sweep
# ---------------------------------------------------------------------------

def sweep_ssa(ssa: SSA3000X, start_hz: float, stop_hz: float,
              noise_floor_dbm: float) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """
    Sweep the SSA over [start_hz, stop_hz] and find emission peaks.

    Returns:
        freqs_hz    — frequency axis (Hz), length = number of trace points
        trace_dbm   — full spectrum trace (dBm)
        peak_freqs  — frequencies of detected peaks (Hz)
        peak_dbm    — amplitudes of detected peaks (dBm)
    """
    print(f"\n[SSA] Sweeping {format_freq_short(start_hz)} – {format_freq_short(stop_hz)} ...",
          end=" ", flush=True)
    rbw = ssa.setup_band(int(start_hz), int(stop_hz))
    print(f"RBW={rbw/1000:.0f} kHz ...", end=" ", flush=True)
    ssa.single_sweep()
    trace_dbm = ssa.get_trace()
    print(f"done  ({len(trace_dbm)} pts)")

    freqs_hz    = np.linspace(start_hz, stop_hz, len(trace_dbm))
    peak_indices = _find_spectrum_peaks(trace_dbm, noise_floor_dbm)
    peak_freqs  = freqs_hz[peak_indices]
    peak_dbm    = trace_dbm[peak_indices]

    # Sort peaks by amplitude, strongest first
    sort_order  = np.argsort(peak_dbm)[::-1]
    peak_freqs  = peak_freqs[sort_order]
    peak_dbm    = peak_dbm[sort_order]

    print(f"       {len(peak_freqs)} peak(s) found above {noise_floor_dbm:.0f} dBm")
    for pf, pd in zip(peak_freqs, peak_dbm):
        print(f"         {format_freq_short(pf):>12}  {pd:+7.1f} dBm")

    return freqs_hz, trace_dbm, peak_freqs, peak_dbm


# ---------------------------------------------------------------------------
# MSO clock measurement
# ---------------------------------------------------------------------------

def measure_clocks(scope: SDS2000X, channels: list[int],
                   duration_s: float, threshold: str | float,
                   max_jitter_frac: float = 0.05) -> dict[int, float]:
    """
    Capture digital channels and identify stable clocks.

    A channel is classified as a clock if its measured period jitter
    (std / mean) is less than max_jitter_frac (default 5%).

    Returns:
        dict mapping channel number → clock frequency in Hz
        (only channels that look like clocks are included)
    """
    pod1_chs = [c for c in channels if c < 8]
    pod2_chs = [c for c in channels if c >= 8]

    print(f"\n[MSO] Capturing D{min(channels)}–D{max(channels)}  "
          f"threshold={threshold}  duration={duration_s*1000:.0f} ms ...",
          end=" ", flush=True)

    scope.digital_enable()
    scope.enable_digital_channels(channels)
    if pod1_chs:
        scope.set_digital_threshold(1, threshold)
    if pod2_chs:
        scope.set_digital_threshold(2, threshold)

    # Set timebase
    tdiv = duration_s / 10.0
    scope.stop()
    time.sleep(0.1)
    scope._cmd(f"TDIV {tdiv:.8f}S")
    scope._cmd("TRMD AUTO")
    scope.run()
    time.sleep(duration_s + 0.5)
    scope.stop()
    time.sleep(0.2)

    traces, sr = scope.capture_all_digital(channels)
    print(f"done  ({len(traces)} channel(s) returned data, sr={sr/1e6:.1f} MHz)")

    if not traces:
        print("  WARNING: no digital data returned — check MSO option, pod connection, threshold")
        return {}

    clock_freqs: dict[int, float] = {}
    for ch, samples in traces.items():
        edges = np.where(np.diff(samples.astype(np.int8)) == 1)[0]
        if len(edges) < 3:
            print(f"  D{ch}: {len(edges)} edge(s) — not a clock (idle or stuck)")
            continue
        periods = np.diff(edges) / sr
        mean_p  = float(np.mean(periods))
        std_p   = float(np.std(periods))
        jitter_frac = std_p / mean_p if mean_p > 0 else 1.0
        freq_hz = 1.0 / mean_p if mean_p > 0 else 0.0
        if jitter_frac < max_jitter_frac:
            clock_freqs[ch] = freq_hz
            print(f"  D{ch}: {format_freq(freq_hz)}  jitter={jitter_frac*100:.2f}%  → CLOCK")
        else:
            print(f"  D{ch}: {format_freq(freq_hz)}  jitter={jitter_frac*100:.1f}%  → irregular/data")

    if not clock_freqs:
        print("  No stable clocks found on any channel.")
    return clock_freqs


# ---------------------------------------------------------------------------
# Harmonic correlation
# ---------------------------------------------------------------------------

def correlate_harmonics(
    peak_freqs: np.ndarray,
    peak_dbm: np.ndarray,
    clock_freqs: dict[int, float],
    harmonic_max: int,
    tol_ppm: float,
) -> list[dict]:
    """
    For each SSA peak, find the best-matching clock harmonic.

    A peak may match multiple clocks / harmonics; we keep the closest match
    (lowest ppm error).  Unmatched peaks are included with channel=None.

    Returns:
        list of dicts, each containing:
            peak_hz, peak_dbm, channel (int or None), clock_hz (or None),
            harmonic (int or None), error_ppm (float or None), label (str)
    """
    results = []
    for peak_f, peak_db in zip(peak_freqs, peak_dbm):
        best: dict | None = None
        best_ppm = float("inf")

        for ch, clk_f in clock_freqs.items():
            for n in range(1, harmonic_max + 1):
                expected   = n * clk_f
                error_ppm  = abs(peak_f - expected) / expected * 1e6
                if error_ppm <= tol_ppm and error_ppm < best_ppm:
                    best_ppm = error_ppm
                    harmonic_label = "FUNDAMENTAL" if n == 1 else f"{n}{'st' if n == 2 else ('nd' if n == 3 else 'th')} harmonic"
                    # Correct English ordinals
                    if n == 1:
                        harmonic_label = "FUNDAMENTAL"
                    elif n == 2:
                        harmonic_label = "2nd harmonic"
                    elif n == 3:
                        harmonic_label = "3rd harmonic"
                    else:
                        harmonic_label = f"{n}th harmonic"
                    best = dict(
                        peak_hz    = float(peak_f),
                        peak_dbm   = float(peak_db),
                        channel    = ch,
                        clock_hz   = clk_f,
                        harmonic   = n,
                        error_ppm  = error_ppm,
                        label      = f"{harmonic_label} of D{ch} ({format_freq(clk_f)})",
                    )

        if best is None:
            results.append(dict(
                peak_hz   = float(peak_f),
                peak_dbm  = float(peak_db),
                channel   = None,
                clock_hz  = None,
                harmonic  = None,
                error_ppm = None,
                label     = "UNMATCHED",
            ))
        else:
            results.append(best)

    return results


# ---------------------------------------------------------------------------
# Terminal report
# ---------------------------------------------------------------------------

def print_correlation_table(matches: list[dict]) -> None:
    """Print correlation results sorted by peak amplitude (strongest first)."""
    if not matches:
        print("\n  No peaks to report.")
        return
    sorted_matches = sorted(matches, key=lambda m: m["peak_dbm"], reverse=True)
    print()
    print(f"  {'Peak frequency':>16}  {'Level':>9}  {'Match'}")
    print(f"  {'-'*16}  {'-'*9}  {'-'*54}")
    for m in sorted_matches:
        freq_str  = format_freq_short(m["peak_hz"])
        dbm_str   = f"{m['peak_dbm']:+.1f} dBm"
        if m["channel"] is not None:
            err_str  = f"{m['error_ppm']:.0f} ppm"
            match_str = f"{m['label']}  (error {err_str})"
        else:
            match_str = "UNMATCHED"
        print(f"  {freq_str:>16}  {dbm_str:>9}  {match_str}")


# ---------------------------------------------------------------------------
# Output files
# ---------------------------------------------------------------------------

def save_json(freqs_hz: np.ndarray, trace_dbm: np.ndarray,
              peak_freqs: np.ndarray, peak_dbm: np.ndarray,
              clock_freqs: dict[int, float],
              matches: list[dict],
              args, path: str) -> None:
    data = {
        "timestamp":     datetime.now().isoformat(),
        "ssa_host":      args.ssa_host,
        "scope_host":    args.scope_host,
        "ssa_start_hz":  args.ssa_start_khz * 1000,
        "ssa_stop_hz":   args.ssa_stop_khz * 1000,
        "noise_floor_dbm": args.noise_floor,
        "harmonic_max":  args.harmonic_max,
        "harmonic_tol_ppm": args.harmonic_tol_ppm,
        "ssa_trace": {
            "freqs_hz":  freqs_hz.tolist() if freqs_hz is not None else [],
            "dbm":       trace_dbm.tolist() if trace_dbm is not None else [],
        },
        "peaks": [
            {"freq_hz": float(f), "dbm": float(d)}
            for f, d in zip(peak_freqs, peak_dbm)
        ],
        "clocks": {
            f"D{ch}": clk_f for ch, clk_f in clock_freqs.items()
        },
        "correlations": matches,
    }
    with open(path, "w") as f:
        json.dump(data, f, indent=2)


def save_txt_report(matches: list[dict], clock_freqs: dict[int, float],
                    args, path: str) -> None:
    ts  = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    sep = "=" * 70
    lines = [
        sep,
        "  EMI EMISSION SOURCE FINDER REPORT",
        f"  Generated   : {ts}",
        f"  SSA         : {args.ssa_host}",
        f"  Scope       : {args.scope_host}",
        f"  SSA range   : {format_freq_short(args.ssa_start_khz*1000)} – "
        f"{format_freq_short(args.ssa_stop_khz*1000)}",
        f"  Noise floor : {args.noise_floor:.0f} dBm",
        f"  Harmonic N  : 1 – {args.harmonic_max}",
        f"  Tolerance   : {args.harmonic_tol_ppm:.0f} ppm",
        sep,
        "",
    ]

    if clock_freqs:
        lines += ["CLOCKS FOUND ON MSO:", "-" * 40]
        for ch, f in sorted(clock_freqs.items()):
            lines.append(f"  D{ch}: {format_freq(f)}")
        lines += [""]
    else:
        lines += ["CLOCKS: none found (--mso-only not set, or no stable clocks)\n"]

    if not matches:
        lines += ["PEAKS: none found above noise floor\n"]
    else:
        sorted_matches = sorted(matches, key=lambda m: m["peak_dbm"], reverse=True)
        lines += ["PEAK CORRELATION (strongest first):", "-" * 70]
        for m in sorted_matches:
            freq_str = format_freq_short(m["peak_hz"])
            dbm_str  = f"{m['peak_dbm']:+.1f} dBm"
            if m["channel"] is not None:
                err_str   = f"{m['error_ppm']:.0f} ppm"
                match_str = f"{m['label']}  error={err_str}"
            else:
                match_str = "UNMATCHED"
            lines.append(f"  {freq_str:>14}  {dbm_str:>9}  {match_str}")
        lines.append("")

        matched   = sum(1 for m in matches if m["channel"] is not None)
        unmatched = len(matches) - matched
        lines += [
            f"Summary: {len(matches)} peaks  matched={matched}  unmatched={unmatched}",
            "",
        ]

    if not _SCIPY_OK:
        lines += ["NOTE: scipy not available — simple peak finder used (no prominence filtering)", ""]

    with open(path, "w") as f:
        f.write("\n".join(lines) + "\n")


# ---------------------------------------------------------------------------
# Plot
# ---------------------------------------------------------------------------

def generate_plot(freqs_hz: np.ndarray, trace_dbm: np.ndarray,
                  peak_freqs: np.ndarray, peak_dbm: np.ndarray,
                  clock_freqs: dict[int, float],
                  matches: list[dict],
                  noise_floor_dbm: float, args, path: str) -> None:

    has_ssa = freqs_hz is not None and trace_dbm is not None
    has_mso = bool(clock_freqs)
    nrows   = (1 if has_ssa else 0) + (1 if has_mso else 0)
    if nrows == 0:
        return

    fig, axes = plt.subplots(nrows, 1, figsize=(14, 5 * nrows + 1))
    if nrows == 1:
        axes = [axes]

    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    fig.suptitle(
        f"EMI Finder — {format_freq_short(args.ssa_start_khz*1000)} – "
        f"{format_freq_short(args.ssa_stop_khz*1000)}\n{ts}",
        fontsize=12,
    )

    ax_idx = 0

    # ---- Top: SSA spectrum ----
    if has_ssa:
        ax = axes[ax_idx]; ax_idx += 1
        freqs_mhz = freqs_hz / 1e6
        ax.plot(freqs_mhz, trace_dbm, color="#1f77b4", linewidth=0.8, alpha=0.9)
        ax.axhline(noise_floor_dbm, color="red", linewidth=1.0,
                   linestyle="--", label=f"Noise floor {noise_floor_dbm:.0f} dBm")

        # Annotate peaks
        match_map = {m["peak_hz"]: m for m in matches}
        for pf, pd in zip(peak_freqs, peak_dbm):
            m = match_map.get(pf)
            color = "#2ca02c" if (m and m["channel"] is not None) else "darkorange"
            ax.plot(pf / 1e6, pd, "v", markersize=8, color=color)
            if m and m["channel"] is not None:
                short_lbl = (f"D{m['channel']} ×{m['harmonic']}" if m["harmonic"] > 1
                             else f"D{m['channel']} fund.")
                ax.annotate(
                    f"{format_freq_short(pf)}\n{short_lbl}",
                    xy=(pf / 1e6, pd),
                    xytext=(0, 12),
                    textcoords="offset points",
                    fontsize=6.5,
                    ha="center",
                    color=color,
                    arrowprops=dict(arrowstyle="-", color=color, lw=0.6),
                )
            else:
                ax.annotate(
                    f"{format_freq_short(pf)}\nUNMATCHED",
                    xy=(pf / 1e6, pd),
                    xytext=(0, 12),
                    textcoords="offset points",
                    fontsize=6.5,
                    ha="center",
                    color=color,
                )

        ax.set_xlabel("Frequency (MHz)", fontsize=9)
        ax.set_ylabel("Level (dBm)", fontsize=9)
        ax.set_title("SSA Spectrum — annotated EMI peaks", fontsize=10)
        ax.grid(True, alpha=0.3)
        ax.legend(fontsize=8)
        ax.set_xlim(freqs_mhz[0], freqs_mhz[-1])
        ax.xaxis.set_major_formatter(mticker.FormatStrFormatter("%.0f"))

    # ---- Bottom: clock bar chart ----
    if has_mso:
        ax = axes[ax_idx]
        ch_labels = [f"D{ch}" for ch in sorted(clock_freqs.keys())]
        freqs_mhz_clocks = [clock_freqs[ch] / 1e6 for ch in sorted(clock_freqs.keys())]
        colors = ["#1f77b4"] * len(ch_labels)

        bars = ax.bar(ch_labels, freqs_mhz_clocks, color=colors, alpha=0.8)
        for bar, freq_mhz in zip(bars, freqs_mhz_clocks):
            ax.text(bar.get_x() + bar.get_width() / 2,
                    bar.get_height() + max(freqs_mhz_clocks) * 0.01,
                    f"{freq_mhz:.3f} MHz",
                    ha="center", va="bottom", fontsize=8)

        ax.set_xlabel("Digital channel", fontsize=9)
        ax.set_ylabel("Clock frequency (MHz)", fontsize=9)
        ax.set_title("MSO clock frequencies identified", fontsize=10)
        ax.grid(True, alpha=0.3, axis="y")

    plt.tight_layout(rect=[0, 0, 1, 0.94])
    plt.savefig(path, dpi=150, bbox_inches="tight")
    plt.close(fig)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="EMI Source Finder — Siglent SSA3000X + SDS2000X Plus MSO",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
MSO HARDWARE WARNING:
  All MSO digital code is from the Siglent EN11F SCPI programming guide.
  This has NOT been tested with physical MSO hardware.  If captures return
  empty data: confirm MSO license, pod connection, and threshold voltage.

Concept:
  SSA finds emission peaks above the noise floor. MSO simultaneously captures
  all active digital clocks. For each SSA peak, the tool checks if it matches
  N × f_clock for any captured clock (N = 1 … --harmonic-max, within
  --harmonic-tol-ppm).  Matched peaks identify the probable EMI source.

  A channel is classified as a clock if period jitter < 5% (--digital-channels
  controls which channels to scan).

Typical workflow:
  1. Run --ssa-only first for a quick spectrum survey.
  2. Connect the MSO pod to the board's oscillator outputs.
  3. Run the full tool to correlate peaks with clocks.

Output files:
  <prefix>_emi.png   — SSA spectrum (annotated peaks) + MSO clock bar chart
  <prefix>_emi.json  — machine-readable full results
  <prefix>_emi.txt   — human-readable correlation report

Examples:
  python emi_finder.py
  python emi_finder.py --ssa-start-khz 10000 --ssa-stop-khz 200000
  python emi_finder.py --digital-channels 0,1,4,5 --threshold lvcmos25
  python emi_finder.py --noise-floor -65 --harmonic-tol-ppm 500
  python emi_finder.py --ssa-only --ssa-stop-khz 100000
  python emi_finder.py --mso-only --digital-channels 0,1,2,3
""",
    )

    parser.add_argument("--ssa-host",   default=SSA_HOST,
                        help=f"Spectrum analyzer IP (default: {SSA_HOST})")
    parser.add_argument("--scope-host", default=SCOPE_HOST,
                        help=f"Oscilloscope IP (default: {SCOPE_HOST})")
    parser.add_argument("--output",     default=None,
                        help="Output filename prefix (default: timestamped)")

    # SSA settings
    sgrp = parser.add_argument_group("SSA sweep")
    sgrp.add_argument("--ssa-start-khz", type=float, default=DEFAULT_START_KHZ,
                      metavar="KHZ",
                      help=f"Sweep start (kHz, default: {DEFAULT_START_KHZ})")
    sgrp.add_argument("--ssa-stop-khz",  type=float, default=DEFAULT_STOP_KHZ,
                      metavar="KHZ",
                      help=f"Sweep stop (kHz, default: {DEFAULT_STOP_KHZ} = 500 MHz)")
    sgrp.add_argument("--noise-floor",   type=float, default=DEFAULT_NOISE_FLOOR_DBM,
                      metavar="DBM",
                      help=f"Only report peaks above this level (default: {DEFAULT_NOISE_FLOOR_DBM} dBm)")

    # MSO settings
    mgrp = parser.add_argument_group("MSO clock capture")
    mgrp.add_argument("--digital-channels", default=",".join(str(c) for c in DEFAULT_CHANNELS),
                      metavar="LIST",
                      help="Comma-separated digital channels to scan (default: 0,1,2,3,4,5,6,7)")
    mgrp.add_argument("--duration-s",    type=float, default=DEFAULT_DURATION_S,
                      metavar="S",
                      help=f"MSO capture duration in seconds (default: {DEFAULT_DURATION_S})")
    mgrp.add_argument("--threshold",     default=DEFAULT_THRESHOLD,
                      choices=THRESHOLD_CHOICES,
                      help=f"Logic threshold standard (default: {DEFAULT_THRESHOLD})")
    mgrp.add_argument("--threshold-v",   type=float, default=None, metavar="V",
                      help="Custom threshold voltage in V (overrides --threshold)")

    # Correlation settings
    cgrp = parser.add_argument_group("harmonic correlation")
    cgrp.add_argument("--harmonic-max",      type=int,   default=DEFAULT_HARMONIC_MAX,
                      help=f"Search up to N × f_clock (default: {DEFAULT_HARMONIC_MAX})")
    cgrp.add_argument("--harmonic-tol-ppm",  type=float, default=DEFAULT_HARMONIC_TOL_PPM,
                      help=f"Harmonic match tolerance in ppm (default: {DEFAULT_HARMONIC_TOL_PPM})")

    # Mode
    mmode = parser.add_argument_group("run mode")
    mmode.add_argument("--ssa-only",  action="store_true",
                       help="Run SSA sweep only — skip MSO capture")
    mmode.add_argument("--mso-only",  action="store_true",
                       help="Run MSO clock capture only — skip SSA sweep")

    args = parser.parse_args()

    if args.ssa_only and args.mso_only:
        print("Error: --ssa-only and --mso-only are mutually exclusive.")
        sys.exit(1)

    # Parse digital channels
    try:
        digital_channels = [int(c.strip()) for c in args.digital_channels.split(",")]
    except ValueError:
        print(f"Error: --digital-channels must be a comma-separated list of integers "
              f"(e.g. '0,1,2,3')")
        sys.exit(1)

    if not digital_channels or any(c < 0 or c > 15 for c in digital_channels):
        print("Error: digital channel numbers must be in 0–15.")
        sys.exit(1)

    # Resolve threshold
    if args.threshold_v is not None:
        threshold: str | float = args.threshold_v
    else:
        threshold = args.threshold.upper()

    if args.output is None:
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        args.output = f"emi_finder_{ts}"

    start_hz = args.ssa_start_khz * 1000.0
    stop_hz  = args.ssa_stop_khz  * 1000.0

    print("EMI Source Finder")
    print(f"  SSA range     : {format_freq_short(start_hz)} – {format_freq_short(stop_hz)}")
    print(f"  Noise floor   : {args.noise_floor:.0f} dBm")
    print(f"  MSO channels  : {digital_channels}")
    print(f"  MSO threshold : {threshold}")
    print(f"  Harmonic max  : {args.harmonic_max}")
    print(f"  Tolerance     : {args.harmonic_tol_ppm:.0f} ppm")
    print(f"  Output        : {args.output}_emi.*")
    if not _SCIPY_OK:
        print("  NOTE: scipy not available — simple peak finder in use")

    # -----------------------------------------------------------------------
    # Measurement
    # -----------------------------------------------------------------------
    freqs_hz   = None
    trace_dbm  = None
    peak_freqs = np.array([])
    peak_dbm   = np.array([])
    clock_freqs: dict[int, float] = {}
    matches: list[dict] = []

    ssa   = None
    scope = None

    try:
        # --- SSA sweep ---
        if not args.mso_only:
            ssa = connect(args.ssa_host or 'ssa')
            idn = ssa.identify()
            print(f"\nSSA IDN: {idn.strip()}")
            if "SSA" not in idn.upper() and "SIGLENT" not in idn.upper():
                print("WARNING: IDN doesn't look like a Siglent SSA — continuing.")
            freqs_hz, trace_dbm, peak_freqs, peak_dbm = sweep_ssa(
                ssa, start_hz, stop_hz, args.noise_floor
            )
            ssa.disconnect()
            ssa = None

        # --- MSO clock capture ---
        if not args.ssa_only:
            scope = connect(args.scope_host or 'sds')
            idn   = scope.identify()
            print(f"\nScope IDN: {idn.strip()}")
            if "SDS" not in idn.upper() and "SIGLENT" not in idn.upper():
                print("WARNING: IDN doesn't look like a Siglent oscilloscope — continuing.")
            clock_freqs = measure_clocks(
                scope, digital_channels, args.duration_s, threshold
            )
            scope.run()
            scope.disconnect()
            scope = None

        # --- Harmonic correlation ---
        if len(peak_freqs) > 0 and clock_freqs:
            print("\n[CORRELATE] Matching peaks to clock harmonics ...")
            matches = correlate_harmonics(
                peak_freqs, peak_dbm, clock_freqs,
                args.harmonic_max, args.harmonic_tol_ppm
            )
        elif len(peak_freqs) > 0 and not clock_freqs:
            # Peaks but no clocks — fill unmatched
            matches = [
                dict(peak_hz=float(f), peak_dbm=float(d), channel=None,
                     clock_hz=None, harmonic=None, error_ppm=None, label="UNMATCHED")
                for f, d in zip(peak_freqs, peak_dbm)
            ]

        # --- Terminal report ---
        print("\n[RESULTS]")
        if clock_freqs:
            print(f"  Clocks found: {len(clock_freqs)}")
            for ch, f in sorted(clock_freqs.items()):
                print(f"    D{ch}: {format_freq(f)}")
        print_correlation_table(matches)

        # --- Save outputs ---
        print()
        json_path = f"{args.output}_emi.json"
        save_json(freqs_hz, trace_dbm, peak_freqs, peak_dbm,
                  clock_freqs, matches, args, json_path)
        print(f"  JSON   → {json_path}")

        txt_path = f"{args.output}_emi.txt"
        save_txt_report(matches, clock_freqs, args, txt_path)
        print(f"  Report → {txt_path}")

        png_path = f"{args.output}_emi.png"
        try:
            generate_plot(freqs_hz, trace_dbm, peak_freqs, peak_dbm,
                          clock_freqs, matches, args.noise_floor, args, png_path)
            print(f"  Plot   → {png_path}")
        except Exception as exc:
            print(f"  Plot generation failed ({exc}) — JSON/text report still saved.")

        print("\nDone.")

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
    except RuntimeError as exc:
        print(f"\nMeasurement error: {exc}")
        sys.exit(1)
    except Exception as exc:
        import traceback
        print(f"\nUnexpected error: {exc}")
        traceback.print_exc()
        sys.exit(1)
    finally:
        if ssa is not None:
            try:
                ssa.disconnect()
            except Exception:
                pass
        if scope is not None:
            try:
                scope.run()
                scope.disconnect()
            except Exception:
                pass


if __name__ == "__main__":
    main()
