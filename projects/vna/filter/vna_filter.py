#!/usr/bin/env python3
"""
Filter Characterizer — HP 8712B VNA

Requires HP 8712B VNA and rf-bench-drivers-hp. The HP 8712B is not currently
connected — requires KISS-488 Ethernet-GPIB adapter.

Unlike rf-bench-scalar-vna which measures only magnitude, this tool adds phase
and group delay using the HP 8712B's vector measurement capability.

Measures:
  S11 (return loss / reflection)
  S21 (insertion loss + phase)
  Group delay τ(f) = -dφ/dω

Automatically annotates:
  -3 dB passband edges (from S21)
  -40 dB stopband entry (from S21)
  Peak group delay and its frequency
  Group delay variation across passband (max − min)

Output files
------------
  {prefix}.png   — 3-panel plot (S11+S21, phase, group delay)
  {prefix}.txt   — text report with annotated parameters
  {prefix}.json  — full numerical data for post-processing

Usage
-----
  python vna_filter.py
  python vna_filter.py --start 1000 --stop 50000 --prefix lpf_40m
  python vna_filter.py --start 1000 --stop 500000 --smooth --use-cal
  python vna_filter.py --points 801 --power -10 --prefix bpf_20m
"""

import argparse
import json
import sys
from datetime import datetime

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np

from rf_bench.hp import HP8712B
from rf_bench.utils import (
    format_freq,
    format_freq_short,
)

# ---------------------------------------------------------------------------
# Defaults
# ---------------------------------------------------------------------------

DEFAULT_HOST      = "10.1.1.70"
DEFAULT_START_KHZ = 300
DEFAULT_STOP_KHZ  = 1_300_000
DEFAULT_POINTS    = 801
DEFAULT_POWER_DBM = -10.0

VNA_MIN_HZ = 300_000
VNA_MAX_HZ = 1_300_000_000

# Savitzky-Golay parameters for group delay smoothing
SG_WINDOW = 11   # must be odd; applied only with --smooth
SG_POLY   = 3


# ---------------------------------------------------------------------------
# Measurement
# ---------------------------------------------------------------------------

def measure_s11(vna: HP8712B, start_hz: float, stop_hz: float,
                points: int, power_dbm: float, use_cal: bool
                ) -> tuple[np.ndarray, np.ndarray]:
    """Return (freqs_hz, s11_db)."""
    vna.setup_sweep(start_hz, stop_hz, points)
    vna.set_power(power_dbm)
    vna.set_parameter("S11")
    if use_cal:
        vna.correction_on()
    else:
        vna.correction_off()
    vna.set_format("MLOG")
    ok = vna.single_sweep()
    if not ok:
        print("  WARNING: S11 sweep OPC timeout")
    freqs_hz = vna.get_frequencies()
    s11_db   = vna.get_trace_db()
    return freqs_hz, s11_db


def measure_s21_mag_phase(vna: HP8712B, start_hz: float, stop_hz: float,
                          points: int, power_dbm: float, use_cal: bool
                          ) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Return (freqs_hz, s21_db, s21_phase_deg)."""
    vna.setup_sweep(start_hz, stop_hz, points)
    vna.set_power(power_dbm)
    vna.set_parameter("S21")
    if use_cal:
        vna.correction_on()
    else:
        vna.correction_off()

    vna.set_format("MLOG")
    ok = vna.single_sweep()
    if not ok:
        print("  WARNING: S21 magnitude sweep OPC timeout")
    freqs_hz = vna.get_frequencies()
    s21_db   = vna.get_trace_db()

    vna.set_format("PHAS")
    ok = vna.single_sweep()
    if not ok:
        print("  WARNING: S21 phase sweep OPC timeout")
    s21_phase_deg = vna.get_trace_phase()

    return freqs_hz, s21_db, s21_phase_deg


# ---------------------------------------------------------------------------
# Analysis
# ---------------------------------------------------------------------------

def compute_group_delay_ns(freqs_hz: np.ndarray, phase_deg: np.ndarray
                           ) -> np.ndarray:
    """
    Group delay τ(f) = -dφ/dω in nanoseconds.
    Phase is unwrapped before differentiation.
    """
    phase_unwrapped = np.unwrap(np.deg2rad(phase_deg))
    omega = 2.0 * np.pi * freqs_hz
    tau_s = -np.gradient(phase_unwrapped, omega)
    return tau_s * 1e9


def savitzky_golay(y: np.ndarray, window: int, poly: int) -> np.ndarray:
    """
    Apply a Savitzky-Golay smoothing filter.
    Falls back gracefully if scipy is unavailable.
    """
    try:
        from scipy.signal import savgol_filter
        return savgol_filter(y, window_length=window, polyorder=poly)
    except ImportError:
        # Simple moving average fallback
        kernel = np.ones(window) / window
        return np.convolve(y, kernel, mode='same')


def find_passband_edges_3db(freqs_hz: np.ndarray, s21_db: np.ndarray
                             ) -> tuple[float | None, float | None, float]:
    """
    Find the -3 dB passband edges from S21.

    The passband is defined relative to the maximum of S21 (which may be
    below 0 dB if there is insertion loss).  Returns
    (f_low_hz, f_high_hz, peak_s21_db).
    """
    peak_db  = float(np.max(s21_db))
    thresh   = peak_db - 3.0
    crossings = np.where(np.diff((s21_db >= thresh).astype(int)))[0]

    f_low  = None
    f_high = None

    if len(crossings) >= 1:
        # Linear interpolation to refine crossing
        i = crossings[0]
        if i + 1 < len(freqs_hz):
            frac  = (thresh - s21_db[i]) / (s21_db[i + 1] - s21_db[i] + 1e-30)
            f_low = float(freqs_hz[i] + frac * (freqs_hz[i + 1] - freqs_hz[i]))

    if len(crossings) >= 2:
        i = crossings[-1]
        if i + 1 < len(freqs_hz):
            frac   = (thresh - s21_db[i]) / (s21_db[i + 1] - s21_db[i] + 1e-30)
            f_high = float(freqs_hz[i] + frac * (freqs_hz[i + 1] - freqs_hz[i]))

    return f_low, f_high, peak_db


def find_stopband_40db(freqs_hz: np.ndarray, s21_db: np.ndarray,
                       f_low: float | None, f_high: float | None
                       ) -> tuple[float | None, float | None]:
    """
    Find the -40 dB stopband edges (first frequency where S21 drops below
    −40 dB below the passband peak, outside the passband).

    Returns (f_stop_low, f_stop_high) — either may be None.
    """
    peak_db = float(np.max(s21_db))
    thresh  = peak_db - 40.0

    f_stop_low  = None
    f_stop_high = None

    # Search below passband lower edge
    if f_low is not None:
        below_mask = freqs_hz < f_low
        if np.any(below_mask):
            idxs = np.where(below_mask & (s21_db < thresh))[0]
            if len(idxs) > 0:
                # Highest frequency below f_low where S21 < threshold
                f_stop_low = float(freqs_hz[idxs[-1]])

    # Search above passband upper edge
    if f_high is not None:
        above_mask = freqs_hz > f_high
        if np.any(above_mask):
            idxs = np.where(above_mask & (s21_db < thresh))[0]
            if len(idxs) > 0:
                f_stop_high = float(freqs_hz[idxs[0]])

    return f_stop_low, f_stop_high


def group_delay_stats_in_passband(freqs_hz: np.ndarray, gd_ns: np.ndarray,
                                   f_low: float | None, f_high: float | None
                                   ) -> dict:
    """
    Compute group delay statistics within the passband.
    Returns dict with peak_ns, peak_freq_hz, variation_ns (max-min in passband).
    """
    peak_gd_ns   = float(np.nanmax(gd_ns))
    peak_gd_idx  = int(np.nanargmax(gd_ns))
    peak_gd_freq = float(freqs_hz[peak_gd_idx])

    gd_var_ns = None
    if f_low is not None and f_high is not None:
        pb_mask = (freqs_hz >= f_low) & (freqs_hz <= f_high)
        if np.any(pb_mask):
            pb_gd = gd_ns[pb_mask]
            valid  = pb_gd[np.isfinite(pb_gd)]
            if len(valid) > 1:
                gd_var_ns = float(np.max(valid) - np.min(valid))

    return {
        "peak_ns":   peak_gd_ns,
        "peak_freq_hz": peak_gd_freq,
        "variation_ns": gd_var_ns,
    }


# ---------------------------------------------------------------------------
# Plotting
# ---------------------------------------------------------------------------

def plot_results(freqs_hz: np.ndarray,
                 s11_db: np.ndarray,
                 s21_db: np.ndarray,
                 s21_phase_deg: np.ndarray,
                 gd_ns: np.ndarray,
                 gd_ns_smooth: np.ndarray | None,
                 f_low: float | None, f_high: float | None,
                 f_stop_low: float | None, f_stop_high: float | None,
                 gd_stats: dict,
                 output_prefix: str) -> str:
    """Generate 3-panel plot.  Returns saved file path."""
    freqs_mhz = freqs_hz / 1e6
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    fig, axes = plt.subplots(3, 1, figsize=(11, 12), sharex=True)

    # --- Panel 1: S11 and S21 magnitude ---
    ax1 = axes[0]
    ax1.plot(freqs_mhz, s11_db, color='#d62728', linewidth=1.2,
             label='S11 (return loss)')
    ax1.plot(freqs_mhz, s21_db, color='#1f77b4', linewidth=1.2,
             label='S21 (insertion loss)')

    ax1.axhline(-3.0,  color='gray',  linestyle='--', linewidth=0.7, alpha=0.6)
    ax1.axhline(-40.0, color='gray',  linestyle=':',  linewidth=0.7, alpha=0.6)

    # Passband shading and edge markers
    if f_low is not None:
        ax1.axvline(f_low / 1e6, color='green', linestyle='--', linewidth=1.0,
                    alpha=0.8, label=f'-3 dB: {format_freq_short(f_low)}')
    if f_high is not None:
        ax1.axvline(f_high / 1e6, color='green', linestyle='--', linewidth=1.0,
                    alpha=0.8, label=f'-3 dB: {format_freq_short(f_high)}')
    if f_low is not None and f_high is not None:
        ax1.axvspan(f_low / 1e6, f_high / 1e6, alpha=0.06, color='blue',
                    label='Passband')

    if f_stop_low is not None:
        ax1.axvline(f_stop_low / 1e6, color='darkorange', linestyle='-.',
                    linewidth=0.9, alpha=0.8,
                    label=f'-40 dB: {format_freq_short(f_stop_low)}')
    if f_stop_high is not None:
        ax1.axvline(f_stop_high / 1e6, color='darkorange', linestyle='-.',
                    linewidth=0.9, alpha=0.8,
                    label=f'-40 dB: {format_freq_short(f_stop_high)}')

    bw_str = ""
    if f_low is not None and f_high is not None:
        bw_hz = f_high - f_low
        bw_str = f"  BW-3dB: {format_freq_short(bw_hz)}"

    ax1.set_ylabel("Level (dB)", fontsize=10)
    ax1.set_title(
        f"Filter Characterization — HP 8712B VNA  |  {ts}{bw_str}\n"
        f"Sweep: {format_freq_short(freqs_hz[0])} – {format_freq_short(freqs_hz[-1])}  |  "
        f"{len(freqs_hz)} points",
        fontsize=10,
    )
    ax1.grid(True, alpha=0.35)
    ax1.legend(fontsize=7, loc='lower right')
    ax1.tick_params(labelsize=9)

    # --- Panel 2: S21 phase ---
    ax2 = axes[1]
    phase_unwrapped = np.degrees(np.unwrap(np.radians(s21_phase_deg)))
    ax2.plot(freqs_mhz, s21_phase_deg,    color='darkorange', linewidth=0.8,
             alpha=0.5, label='Phase (wrapped)')
    ax2.plot(freqs_mhz, phase_unwrapped,  color='#d62728',    linewidth=1.2,
             label='Phase (unwrapped)')
    if f_low is not None:
        ax2.axvline(f_low / 1e6,  color='green', linestyle='--', linewidth=0.8, alpha=0.7)
    if f_high is not None:
        ax2.axvline(f_high / 1e6, color='green', linestyle='--', linewidth=0.8, alpha=0.7)
    ax2.set_ylabel("S21 Phase (deg)", fontsize=10)
    ax2.grid(True, alpha=0.35)
    ax2.legend(fontsize=8, loc='upper right')
    ax2.tick_params(labelsize=9)

    # --- Panel 3: Group delay ---
    ax3 = axes[2]
    valid = np.isfinite(gd_ns)
    ax3.plot(freqs_mhz[valid], gd_ns[valid], color='#9467bd',
             linewidth=0.8, alpha=0.5 if gd_ns_smooth is not None else 1.0,
             label='Group delay (raw)')

    if gd_ns_smooth is not None:
        valid_s = np.isfinite(gd_ns_smooth)
        ax3.plot(freqs_mhz[valid_s], gd_ns_smooth[valid_s], color='#9467bd',
                 linewidth=1.5, label='Group delay (smoothed)')

    # Peak annotation
    if np.isfinite(gd_stats["peak_ns"]):
        ax3.plot(gd_stats["peak_freq_hz"] / 1e6, gd_stats["peak_ns"],
                 'r*', markersize=10,
                 label=f'Peak: {gd_stats["peak_ns"]:.1f} ns '
                       f'@ {format_freq_short(gd_stats["peak_freq_hz"])}')

    if gd_stats["variation_ns"] is not None:
        ax3.annotate(
            f'Passband GD variation:\n{gd_stats["variation_ns"]:.1f} ns p-p',
            xy=(0.02, 0.97), xycoords='axes fraction',
            fontsize=8, verticalalignment='top',
            bbox=dict(boxstyle='round', facecolor='lavender', alpha=0.8),
        )

    if f_low is not None:
        ax3.axvline(f_low / 1e6,  color='green', linestyle='--', linewidth=0.8, alpha=0.7)
    if f_high is not None:
        ax3.axvline(f_high / 1e6, color='green', linestyle='--', linewidth=0.8, alpha=0.7)

    ax3.set_xlabel("Frequency (MHz)", fontsize=10)
    ax3.set_ylabel("Group Delay (ns)", fontsize=10)
    ax3.set_title("Group Delay (S21)", fontsize=10)
    ax3.grid(True, alpha=0.35)
    ax3.legend(fontsize=8, loc='upper right')
    ax3.tick_params(labelsize=9)

    plt.tight_layout()
    path = f"{output_prefix}.png"
    plt.savefig(path, dpi=150, bbox_inches='tight')
    plt.close(fig)
    return path


# ---------------------------------------------------------------------------
# Text + JSON
# ---------------------------------------------------------------------------

def save_txt(freqs_hz: np.ndarray, s11_db: np.ndarray,
             s21_db: np.ndarray, s21_phase_deg: np.ndarray,
             gd_ns: np.ndarray,
             f_low: float | None, f_high: float | None,
             f_stop_low: float | None, f_stop_high: float | None,
             gd_stats: dict, peak_db: float, output_prefix: str) -> str:
    """Write text report.  Returns path."""
    path = f"{output_prefix}.txt"
    ts   = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    sep  = "=" * 72

    lines = [
        sep,
        "  FILTER CHARACTERIZATION REPORT — HP 8712B VNA",
        f"  Generated : {ts}",
        f"  Sweep     : {format_freq(freqs_hz[0])} – {format_freq(freqs_hz[-1])}",
        f"  Points    : {len(freqs_hz)}",
        sep,
        "",
        "  PASSBAND (S21 −3 dB relative to passband peak)",
        "  -----------------------------------------------",
    ]

    if f_low is not None and f_high is not None:
        bw_hz = f_high - f_low
        fc_hz = (f_low + f_high) / 2.0
        lines += [
            f"  Lower edge (-3 dB)  : {format_freq(f_low)}",
            f"  Upper edge (-3 dB)  : {format_freq(f_high)}",
            f"  -3 dB bandwidth     : {format_freq(bw_hz)}",
            f"  Centre frequency    : {format_freq(fc_hz)}",
        ]
    else:
        lines.append("  Passband edges: could not determine from sweep data")

    lines += [
        f"  Passband insertion  : {peak_db:.2f} dB  (worst-case in passband)",
        "",
        "  STOPBAND (S21 −40 dB relative to passband peak)",
        "  ------------------------------------------------",
    ]

    if f_stop_low is not None:
        lines.append(f"  Lower stopband start: {format_freq(f_stop_low)}")
    else:
        lines.append("  Lower stopband: not reached within sweep")
    if f_stop_high is not None:
        lines.append(f"  Upper stopband start: {format_freq(f_stop_high)}")
    else:
        lines.append("  Upper stopband: not reached within sweep")

    lines += [
        "",
        "  GROUP DELAY",
        "  -----------",
        f"  Peak group delay    : {gd_stats['peak_ns']:.2f} ns  "
        f"@ {format_freq(gd_stats['peak_freq_hz'])}",
    ]
    if gd_stats["variation_ns"] is not None:
        lines.append(f"  GD variation (passband): {gd_stats['variation_ns']:.2f} ns p-p")
    else:
        lines.append("  GD variation: passband not determined")

    lines += [
        "",
        sep,
        "",
        f"  {'Frequency':>16}  {'S11 (dB)':>10}  {'S21 (dB)':>10}  "
        f"{'Phase (deg)':>12}  {'GD (ns)':>10}",
        "  " + "-" * 64,
    ]

    step = max(1, len(freqs_hz) // 80)
    for i in range(0, len(freqs_hz), step):
        gd_str  = f"{gd_ns[i]:+9.2f}" if np.isfinite(gd_ns[i]) else "       N/A"
        lines.append(
            f"  {format_freq(freqs_hz[i]):>16}  "
            f"{s11_db[i]:+10.3f}  "
            f"{s21_db[i]:+10.3f}  "
            f"{s21_phase_deg[i]:+12.2f}  "
            f"{gd_str}"
        )

    text = "\n".join(lines) + "\n"
    with open(path, "w") as fh:
        fh.write(text)
    return path


def save_json(freqs_hz: np.ndarray, s11_db: np.ndarray,
              s21_db: np.ndarray, s21_phase_deg: np.ndarray,
              gd_ns: np.ndarray, gd_ns_smooth: np.ndarray | None,
              f_low: float | None, f_high: float | None,
              f_stop_low: float | None, f_stop_high: float | None,
              gd_stats: dict, peak_db: float, args, output_prefix: str) -> str:
    """Write JSON data file.  Returns path."""
    path = f"{output_prefix}.json"

    def _clean(arr):
        return [x if np.isfinite(x) else None for x in arr.tolist()]

    data = {
        "timestamp":      datetime.now().isoformat(),
        "instrument":     "HP 8712B",
        "host":           args.host,
        "start_hz":       float(freqs_hz[0]),
        "stop_hz":        float(freqs_hz[-1]),
        "points":         len(freqs_hz),
        "power_dbm":      args.power,
        "use_cal":        args.use_cal,
        "smooth":         args.smooth,
        "passband": {
            "f_low_hz":     f_low,
            "f_high_hz":    f_high,
            "bw_hz":        (f_high - f_low) if (f_low and f_high) else None,
            "peak_db":      peak_db,
        },
        "stopband": {
            "f_stop_low_hz":  f_stop_low,
            "f_stop_high_hz": f_stop_high,
        },
        "group_delay": {
            "peak_ns":      gd_stats["peak_ns"] if np.isfinite(gd_stats["peak_ns"]) else None,
            "peak_freq_hz": gd_stats["peak_freq_hz"],
            "variation_passband_ns": gd_stats["variation_ns"],
        },
        "freqs_hz":       freqs_hz.tolist(),
        "s11_db":         _clean(s11_db),
        "s21_db":         _clean(s21_db),
        "s21_phase_deg":  _clean(s21_phase_deg),
        "group_delay_ns": _clean(gd_ns),
    }
    if gd_ns_smooth is not None:
        data["group_delay_ns_smooth"] = _clean(gd_ns_smooth)

    with open(path, "w") as jf:
        json.dump(data, jf, indent=2)
    return path


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Filter characterizer — HP 8712B VNA (S11, S21, group delay)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Unlike rf-bench-scalar-vna which measures only magnitude, this tool adds phase
and group delay using the HP 8712B's vector measurement capability.

Setup:
  HP 8712B Port 1 → filter input
  HP 8712B Port 2 → filter output

Examples:
  python vna_filter.py                              # full VNA range
  python vna_filter.py --start 1000 --stop 50000   # HF LPF
  python vna_filter.py --start 1000 --stop 500000 --smooth --use-cal
  python vna_filter.py --points 801 --prefix bpf_14mhz
""",
    )

    parser.add_argument("--start",     type=float, default=DEFAULT_START_KHZ,
                        metavar="KHZ", help=f"Start frequency kHz (default {DEFAULT_START_KHZ})")
    parser.add_argument("--stop",      type=float, default=DEFAULT_STOP_KHZ,
                        metavar="KHZ", help=f"Stop frequency kHz (default {DEFAULT_STOP_KHZ})")
    parser.add_argument("--points",    type=int,   default=DEFAULT_POINTS,
                        metavar="N",   help=f"Sweep points, 1–801 (default {DEFAULT_POINTS})")
    parser.add_argument("--power",     type=float, default=DEFAULT_POWER_DBM,
                        metavar="DBM", help=f"Stimulus power dBm (default {DEFAULT_POWER_DBM})")
    parser.add_argument("--smooth",    action="store_true",
                        help=f"Apply Savitzky-Golay smoothing to group delay "
                             f"(window={SG_WINDOW}, poly={SG_POLY})")
    parser.add_argument("--use-cal",   action="store_true",
                        help="Enable stored VNA calibration correction")
    parser.add_argument("--host",      default=DEFAULT_HOST, metavar="HOST",
                        help=f"HP 8712B / KISS-488 host (default {DEFAULT_HOST})")
    parser.add_argument("--prefix",    default=None, metavar="TEXT",
                        help="Output file prefix (default: timestamped)")

    args = parser.parse_args()

    if args.prefix is None:
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        args.prefix = f"vna_filter_{ts}"

    if args.points < 1 or args.points > 801:
        print("Error: --points must be 1–801 (HP 8712B maximum is 801)")
        sys.exit(1)

    start_hz = max(args.start * 1_000.0, float(VNA_MIN_HZ))
    stop_hz  = min(args.stop  * 1_000.0, float(VNA_MAX_HZ))

    if start_hz >= stop_hz:
        print("Error: --start must be less than --stop")
        sys.exit(1)

    print("Filter Characterizer — HP 8712B VNA")
    print(f"  Sweep      : {format_freq_short(start_hz)} – {format_freq_short(stop_hz)}")
    print(f"  Points     : {args.points}")
    print(f"  Power      : {args.power:+.0f} dBm")
    print(f"  Calibration: {'ON' if args.use_cal else 'OFF'}")
    print(f"  Smoothing  : {'ON (S-G)' if args.smooth else 'OFF'}")
    print(f"  Host       : {args.host}")
    print()

    vna = None
    try:
        print(f"Connecting to HP 8712B @ {args.host} ...")
        vna = HP8712B(host=args.host)
        idn = vna.identify()
        print(f"  IDN: {idn}")

        # --- S11 measurement ---
        print("\n[S11 MEASUREMENT]")
        freqs_hz, s11_db = measure_s11(
            vna, start_hz, stop_hz, args.points, args.power, args.use_cal
        )
        print(f"  S11 range: {np.min(s11_db):.1f} to {np.max(s11_db):.1f} dB")

        # --- S21 measurement ---
        print("\n[S21 MEASUREMENT]")
        freqs_hz, s21_db, s21_phase_deg = measure_s21_mag_phase(
            vna, start_hz, stop_hz, args.points, args.power, args.use_cal
        )
        print(f"  S21 range: {np.min(s21_db):.1f} to {np.max(s21_db):.1f} dB")

        # --- Group delay ---
        gd_ns       = compute_group_delay_ns(freqs_hz, s21_phase_deg)
        gd_ns_smooth = None
        if args.smooth:
            gd_ns_smooth = savitzky_golay(gd_ns, SG_WINDOW, SG_POLY)

        # --- Passband analysis ---
        f_low, f_high, peak_db = find_passband_edges_3db(freqs_hz, s21_db)
        if f_low is not None and f_high is not None:
            print(f"\n  -3 dB passband: {format_freq_short(f_low)} – "
                  f"{format_freq_short(f_high)}  "
                  f"(BW = {format_freq_short(f_high - f_low)})")
        else:
            print("\n  -3 dB passband edges: not found in sweep range")

        f_stop_low, f_stop_high = find_stopband_40db(freqs_hz, s21_db, f_low, f_high)
        if f_stop_low is not None:
            print(f"  -40 dB lower stopband: {format_freq_short(f_stop_low)}")
        if f_stop_high is not None:
            print(f"  -40 dB upper stopband: {format_freq_short(f_stop_high)}")

        gd_active = gd_ns_smooth if gd_ns_smooth is not None else gd_ns
        gd_stats  = group_delay_stats_in_passband(freqs_hz, gd_active, f_low, f_high)
        print(f"\n  Peak group delay: {gd_stats['peak_ns']:.1f} ns  "
              f"@ {format_freq_short(gd_stats['peak_freq_hz'])}")
        if gd_stats["variation_ns"] is not None:
            print(f"  GD variation in passband: {gd_stats['variation_ns']:.1f} ns p-p")

        # --- Save outputs ---
        print("\n[SAVING RESULTS]")

        txt_path = save_txt(
            freqs_hz, s11_db, s21_db, s21_phase_deg, gd_ns,
            f_low, f_high, f_stop_low, f_stop_high, gd_stats, peak_db,
            args.prefix
        )
        print(f"  Text  → {txt_path}")

        json_path = save_json(
            freqs_hz, s11_db, s21_db, s21_phase_deg, gd_ns, gd_ns_smooth,
            f_low, f_high, f_stop_low, f_stop_high, gd_stats, peak_db,
            args, args.prefix
        )
        print(f"  JSON  → {json_path}")

        try:
            png_path = plot_results(
                freqs_hz, s11_db, s21_db, s21_phase_deg,
                gd_ns, gd_ns_smooth,
                f_low, f_high, f_stop_low, f_stop_high, gd_stats,
                args.prefix
            )
            print(f"  Plot  → {png_path}")
        except Exception as exc:
            print(f"  Plot failed: {exc}")

    except KeyboardInterrupt:
        print("\nInterrupted.")
        sys.exit(0)
    except ConnectionRefusedError as exc:
        print(f"\nCannot connect to HP 8712B @ {args.host}: {exc}")
        print("Check KISS-488 adapter power and network connection.")
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
        if vna is not None:
            try:
                vna.correction_off()
                vna.close()
            except Exception:
                pass


if __name__ == "__main__":
    main()
