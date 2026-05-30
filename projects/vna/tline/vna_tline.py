#!/usr/bin/env python3
"""
Transmission Line Characterizer — HP 8712B VNA

Requires HP 8712B VNA and rf-bench-drivers-hp. The HP 8712B is not currently
connected — requires KISS-488 Ethernet-GPIB adapter.

Measures S21 (magnitude + phase) across the full VNA span for a coaxial
transmission line of known physical length.  Derives:

  Velocity factor (vf):
    Method 1 — group delay: τ = -dφ/dω over the sweep.  vf = L / (τ_avg × c).
    Method 2 — first S21 null: vf = 2 × f_null × L / c  (λ/2 at null).
    Both are reported; group-delay method is more robust (see note below).

  Propagation loss:
    α (dB/m) = -mean(S21_dB_at_midband) / L
    This is a rough single-frequency figure; the full S21(f) curve shows
    the true frequency-dependent loss.

  Characteristic impedance Z0 (optional, --measure-z0):
    Z0 ≈ √(Zoc × Zsc) where Zoc and Zsc are the input impedance of the line
    with the far end open and short-circuited respectively.  Requires the
    user to physically change the far-end termination between sweeps; the
    script prompts interactively.  The HP 8712B measures S11 (complex) for
    each, and Z0 is estimated from the geometric mean at the midband
    frequency.

  Electrical length (deg):
    φ(f) = phase of S21 — displayed in the phase panel and printed at key
    amateur radio band frequencies within the sweep range.

Note on velocity-factor methods
--------------------------------
The group-delay method:
  τ_group(f) = -dφ/dω  (ω = 2πf, φ in radians)
  vf = L / (c × τ_group_avg)
is preferred because:
  • It does not require finding a null (may fall outside the sweep range for
    short cables).
  • It uses the entire sweep, not a single frequency.
  • It is less sensitive to measurement noise.
The null method is shown as a cross-check.

Output files
------------
  {prefix}.png   — 3-panel plot (S21 magnitude, S21 phase, group delay)
  {prefix}.txt   — text report with key computed parameters
  {prefix}.json  — full numerical data for post-processing

Usage
-----
  python vna_tline.py --length-m 10.0
  python vna_tline.py --length-m 1.52 --start 300 --stop 1300000 --prefix coax_rg58
  python vna_tline.py --length-m 5.0 --measure-z0
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
    SPEED_OF_LIGHT,
)

# ---------------------------------------------------------------------------
# Defaults
# ---------------------------------------------------------------------------

DEFAULT_HOST      = "10.1.1.70"
DEFAULT_START_KHZ = 300
DEFAULT_STOP_KHZ  = 1_300_000
DEFAULT_POINTS    = 401
DEFAULT_POWER_DBM = -10.0

VNA_MIN_HZ = 300_000      # HP 8712B lower limit
VNA_MAX_HZ = 1_300_000_000  # HP 8712B upper limit

# Amateur radio band centre frequencies for annotation (Hz)
BAND_CENTRES = {
    "160m": 1_900_000,
    "80m":  3_700_000,
    "40m":  7_150_000,
    "30m": 10_125_000,
    "20m": 14_175_000,
    "17m": 18_100_000,
    "15m": 21_225_000,
    "12m": 24_940_000,
    "10m": 28_500_000,
    "6m":  50_000_000,
    "2m": 144_500_000,
    "70cm": 432_100_000,
    "33cm": 902_700_000,
    "23cm": 1_296_000_000,
}


# ---------------------------------------------------------------------------
# Measurement helpers
# ---------------------------------------------------------------------------

def measure_s21(vna: HP8712B, start_hz: float, stop_hz: float,
                points: int, power_dbm: float, use_cal: bool = False
                ) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """
    Configure VNA and measure S21 magnitude + phase.

    Returns (freqs_hz, s21_db, s21_phase_deg, s21_complex).
    """
    print(f"  Setting up sweep: {format_freq_short(start_hz)} – "
          f"{format_freq_short(stop_hz)}, {points} pts, {power_dbm:+.0f} dBm")

    vna.setup_sweep(start_hz, stop_hz, points)
    vna.set_power(power_dbm)
    vna.set_parameter("S21")

    if use_cal:
        vna.correction_on()
        print("  Calibration correction: ON")
    else:
        vna.correction_off()

    # --- Magnitude sweep ---
    vna.set_format("MLOG")
    ok = vna.single_sweep()
    if not ok:
        print("  WARNING: sweep OPC timeout — data may be incomplete")
    freqs_hz = vna.get_frequencies()
    s21_db   = vna.get_trace_db()

    # --- Phase sweep ---
    vna.set_format("PHAS")
    ok = vna.single_sweep()
    if not ok:
        print("  WARNING: phase sweep OPC timeout")
    s21_phase_deg = vna.get_trace_phase()

    # --- Complex S-data ---
    vna.set_format("MLOG")  # restore
    s21_complex = np.cos(np.deg2rad(s21_phase_deg)) * 10 ** (s21_db / 20.0) + \
                  1j * np.sin(np.deg2rad(s21_phase_deg)) * 10 ** (s21_db / 20.0)

    return freqs_hz, s21_db, s21_phase_deg, s21_complex


def measure_s11_complex(vna: HP8712B, start_hz: float, stop_hz: float,
                        points: int, power_dbm: float, use_cal: bool = False
                        ) -> tuple[np.ndarray, np.ndarray]:
    """
    Measure S11 (complex) for Z0 estimation.  Returns (freqs_hz, s11_complex).
    """
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
    s11_db = vna.get_trace_db()

    vna.set_format("PHAS")
    ok = vna.single_sweep()
    if not ok:
        print("  WARNING: S11 phase sweep OPC timeout")
    s11_phase_deg = vna.get_trace_phase()

    mag = 10 ** (s11_db / 20.0)
    phi = np.deg2rad(s11_phase_deg)
    s11_complex = mag * (np.cos(phi) + 1j * np.sin(phi))
    return freqs_hz, s11_complex


# ---------------------------------------------------------------------------
# Analysis functions
# ---------------------------------------------------------------------------

def compute_group_delay(freqs_hz: np.ndarray, phase_deg: np.ndarray
                        ) -> np.ndarray:
    """
    Compute group delay τ(f) = -dφ/dω from phase (degrees) vs frequency (Hz).

    Returns τ in seconds (one value per sweep point; first/last filled by
    edge replication).
    """
    phase_rad = np.deg2rad(np.unwrap(np.deg2rad(phase_deg)) * 180.0 / np.pi)
    # Unwrap the raw degree array properly
    phase_unwrapped_rad = np.unwrap(np.deg2rad(phase_deg))
    omega = 2.0 * np.pi * freqs_hz
    d_phi = np.gradient(phase_unwrapped_rad, omega)
    tau = -d_phi   # seconds
    return tau


def velocity_factor_from_group_delay(tau_s: np.ndarray, length_m: float) -> float:
    """
    Estimate velocity factor from median group delay.
    vf = L / (τ_median × c)
    """
    tau_median = float(np.median(tau_s[np.isfinite(tau_s)]))
    if tau_median <= 0:
        return float('nan')
    vf = length_m / (tau_median * SPEED_OF_LIGHT)
    return vf


def find_first_s21_null(freqs_hz: np.ndarray, s21_db: np.ndarray
                        ) -> tuple[float | None, float | None]:
    """
    Find the first local minimum in |S21| (dB) — the first λ/2 null of the
    transmission line.  Returns (null_freq_hz, null_depth_db) or (None, None).
    """
    # Find local minima via sign-change of derivative
    diffs = np.diff(s21_db)
    rising_after = (diffs[:-1] < 0) & (diffs[1:] >= 0)
    null_indices = np.where(rising_after)[0] + 1

    if len(null_indices) == 0:
        return None, None

    # Use the deepest among the first 3 candidates (avoid noise spikes)
    candidates = null_indices[:3]
    deepest = candidates[np.argmin(s21_db[candidates])]
    null_freq = float(freqs_hz[deepest])
    null_depth = float(s21_db[deepest])

    # Sanity: the null should be at least 3 dB below the surrounding average
    avg_nearby = float(np.mean(s21_db[max(0, deepest - 5):deepest + 6]))
    if null_depth > avg_nearby - 3.0:
        return None, None

    return null_freq, null_depth


def velocity_factor_from_null(null_freq_hz: float, length_m: float) -> float:
    """
    vf = 2 × f_null × L / c   (λ/2 null → electrical length = 180° at f_null)
    """
    return 2.0 * null_freq_hz * length_m / SPEED_OF_LIGHT


def estimate_z0(freqs_hz: np.ndarray, s11_oc: np.ndarray, s11_sc: np.ndarray,
                z0_system: float = 50.0) -> tuple[np.ndarray, float]:
    """
    Estimate Z0 from S11 measurements with open and short termination.

    Γoc = s11_oc, Γsc = s11_sc (complex arrays)
    Zin_oc = z0_system × (1 + Γoc) / (1 - Γoc)
    Zin_sc = z0_system × (1 + Γsc) / (1 - Γsc)
    Z0(f) = √(Zin_oc × Zin_sc)     (complex, frequency-by-frequency)

    Returns (z0_vs_freq_ohm, z0_midband_ohm).
    """
    zin_oc = z0_system * (1.0 + s11_oc) / (1.0 - s11_oc)
    zin_sc = z0_system * (1.0 + s11_sc) / (1.0 - s11_sc)
    z0_f = np.sqrt(zin_oc * zin_sc)
    # Midband estimate from the real part (median over centre third of sweep)
    n = len(freqs_hz)
    lo = n // 3
    hi = 2 * n // 3
    z0_mid = float(np.median(np.abs(z0_f[lo:hi].real)))
    return z0_f, z0_mid


# ---------------------------------------------------------------------------
# Plotting
# ---------------------------------------------------------------------------

def plot_results(freqs_hz: np.ndarray, s21_db: np.ndarray,
                 s21_phase_deg: np.ndarray, group_delay_ns: np.ndarray,
                 length_m: float, vf_gd: float, vf_null: float | None,
                 null_freq: float | None, loss_db_per_m: float,
                 output_prefix: str) -> str:
    """Generate 3-panel plot.  Returns the saved file path."""
    freqs_mhz = freqs_hz / 1e6

    fig, axes = plt.subplots(3, 1, figsize=(11, 11), sharex=True)
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    # --- Panel 1: S21 magnitude ---
    ax1 = axes[0]
    ax1.plot(freqs_mhz, s21_db, color='#1f77b4', linewidth=1.2, label='S21 mag')
    ax1.set_ylabel("S21 Magnitude (dB)", fontsize=10)
    ax1.set_title(
        f"Transmission Line Characterizer — {ts}\n"
        f"Length: {length_m:.3f} m  |  "
        f"vf (group delay): {vf_gd:.4f}  |  "
        f"Loss: {loss_db_per_m:.3f} dB/m at midband",
        fontsize=10,
    )
    ax1.grid(True, alpha=0.35)

    if null_freq is not None:
        ax1.axvline(null_freq / 1e6, color='darkorange', linestyle='--',
                    linewidth=1.0, alpha=0.8,
                    label=f'First null: {format_freq_short(null_freq)}')
    ax1.legend(fontsize=8, loc='upper right')
    ax1.tick_params(labelsize=9)

    # --- Panel 2: S21 phase ---
    ax2 = axes[1]
    phase_unwrapped = np.degrees(np.unwrap(np.radians(s21_phase_deg)))
    ax2.plot(freqs_mhz, s21_phase_deg, color='darkorange', linewidth=1.0,
             alpha=0.5, label='Phase (wrapped)')
    ax2.plot(freqs_mhz, phase_unwrapped, color='#d62728', linewidth=1.2,
             label='Phase (unwrapped)')
    ax2.set_ylabel("S21 Phase (deg)", fontsize=10)
    ax2.grid(True, alpha=0.35)
    ax2.legend(fontsize=8, loc='upper right')
    ax2.tick_params(labelsize=9)

    # --- Panel 3: Group delay ---
    ax3 = axes[2]
    gd_valid = np.isfinite(group_delay_ns)
    ax3.plot(freqs_mhz[gd_valid], group_delay_ns[gd_valid],
             color='green', linewidth=1.2, label='Group delay')

    tau_median_ns = float(np.median(group_delay_ns[gd_valid])) if np.any(gd_valid) else np.nan
    if np.isfinite(tau_median_ns):
        ax3.axhline(tau_median_ns, color='gray', linestyle='--', linewidth=0.8,
                    label=f'Median τ = {tau_median_ns:.2f} ns  →  vf = {vf_gd:.4f}')

    if null_freq is not None and vf_null is not None:
        ax3.annotate(
            f'vf (null) = {vf_null:.4f}\nf_null = {format_freq_short(null_freq)}',
            xy=(null_freq / 1e6, tau_median_ns),
            xytext=(null_freq / 1e6 * 1.05, tau_median_ns * 1.2),
            fontsize=7,
            arrowprops=dict(arrowstyle='->', color='darkorange'),
            color='darkorange',
        )

    ax3.set_xlabel("Frequency (MHz)", fontsize=10)
    ax3.set_ylabel("Group Delay (ns)", fontsize=10)
    ax3.set_title("Velocity Factor Diagnostic (Group Delay)", fontsize=10)
    ax3.grid(True, alpha=0.35)
    ax3.legend(fontsize=8, loc='upper right')
    ax3.tick_params(labelsize=9)

    plt.tight_layout()
    path = f"{output_prefix}.png"
    plt.savefig(path, dpi=150, bbox_inches='tight')
    plt.close(fig)
    return path


# ---------------------------------------------------------------------------
# Text + JSON output
# ---------------------------------------------------------------------------

def save_txt(freqs_hz: np.ndarray, s21_db: np.ndarray,
             s21_phase_deg: np.ndarray, group_delay_ns: np.ndarray,
             length_m: float, vf_gd: float, vf_null: float | None,
             null_freq: float | None, loss_db_per_m: float,
             z0_mid: float | None, output_prefix: str) -> str:
    """Write text report.  Returns path."""
    path = f"{output_prefix}.txt"
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    sep = "=" * 72

    lines = [
        sep,
        "  TRANSMISSION LINE CHARACTERIZATION REPORT",
        f"  Generated   : {ts}",
        f"  Cable length: {length_m:.4f} m",
        f"  Sweep       : {format_freq(freqs_hz[0])} – {format_freq(freqs_hz[-1])}",
        f"  Points      : {len(freqs_hz)}",
        sep,
        "",
        "  DERIVED PARAMETERS",
        "  ------------------",
        f"  Velocity factor (group delay) : {vf_gd:.4f}",
    ]

    if vf_null is not None and null_freq is not None:
        lines.append(f"  Velocity factor (first null)  : {vf_null:.4f}  "
                     f"@ {format_freq(null_freq)}")
    else:
        lines.append("  Velocity factor (first null)  : not found in sweep range")

    lines += [
        f"  Propagation loss              : {loss_db_per_m:.4f} dB/m  (midband S21)",
        f"  Total insertion loss @ midband: {loss_db_per_m * length_m:.3f} dB",
    ]

    if z0_mid is not None:
        lines.append(f"  Characteristic impedance (Z0) : {z0_mid:.1f} Ω  "
                     "(open/short method, approx)")

    lines += ["", "  ELECTRICAL LENGTH AT KEY FREQUENCIES", "  ------------------------------------"]

    midband_hz = (freqs_hz[0] + freqs_hz[-1]) / 2.0
    for band, fc_hz in sorted(BAND_CENTRES.items(), key=lambda x: x[1]):
        if freqs_hz[0] <= fc_hz <= freqs_hz[-1]:
            idx = int(np.argmin(np.abs(freqs_hz - fc_hz)))
            lines.append(f"  {band:>5}  {format_freq(fc_hz):>16}  "
                         f"φ = {s21_phase_deg[idx]:+8.1f}°  "
                         f"S21 = {s21_db[idx]:+6.2f} dB")

    lines += ["", sep, "", f"  {'Frequency':>16}  {'S21 (dB)':>10}  {'Phase (deg)':>12}  "
              f"{'Grp Delay (ns)':>15}"]
    lines.append("  " + "-" * 58)

    # Print every 10th point to keep file manageable
    step = max(1, len(freqs_hz) // 80)
    for i in range(0, len(freqs_hz), step):
        tau_str = f"{group_delay_ns[i]:+12.3f}" if np.isfinite(group_delay_ns[i]) else "         N/A"
        lines.append(f"  {format_freq(freqs_hz[i]):>16}  "
                     f"{s21_db[i]:+10.3f}  "
                     f"{s21_phase_deg[i]:+12.2f}  "
                     f"{tau_str}")

    text = "\n".join(lines) + "\n"
    with open(path, "w") as fh:
        fh.write(text)
    return path


def save_json(freqs_hz: np.ndarray, s21_db: np.ndarray,
              s21_phase_deg: np.ndarray, group_delay_ns: np.ndarray,
              length_m: float, vf_gd: float, vf_null: float | None,
              null_freq: float | None, loss_db_per_m: float,
              z0_mid: float | None, args, output_prefix: str) -> str:
    """Write JSON data file.  Returns path."""
    path = f"{output_prefix}.json"

    def _clean(arr):
        return [x if np.isfinite(x) else None for x in arr.tolist()]

    data = {
        "timestamp":       datetime.now().isoformat(),
        "instrument":      "HP 8712B",
        "host":            args.host,
        "cable_length_m":  length_m,
        "start_hz":        float(freqs_hz[0]),
        "stop_hz":         float(freqs_hz[-1]),
        "points":          len(freqs_hz),
        "power_dbm":       args.power,
        "velocity_factor_group_delay": vf_gd if np.isfinite(vf_gd) else None,
        "velocity_factor_null":        vf_null,
        "null_freq_hz":                null_freq,
        "loss_db_per_m":               loss_db_per_m if np.isfinite(loss_db_per_m) else None,
        "z0_ohm":                      z0_mid,
        "freqs_hz":        freqs_hz.tolist(),
        "s21_db":          _clean(s21_db),
        "s21_phase_deg":   _clean(s21_phase_deg),
        "group_delay_ns":  _clean(group_delay_ns),
    }

    with open(path, "w") as jf:
        json.dump(data, jf, indent=2)
    return path


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Transmission line characterizer — HP 8712B VNA",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Setup:
  HP 8712B Port 1 → cable Port A (S21 = forward transmission)
  HP 8712B Port 2 → cable Port B

  For --measure-z0: re-terminate the far end (Port 2 end) as prompted.

Examples:
  python vna_tline.py --length-m 10.0
  python vna_tline.py --length-m 1.52 --stop 200000 --prefix coax_rg58_short
  python vna_tline.py --length-m 5.0 --measure-z0
  python vna_tline.py --length-m 30.5 --points 801 --power -10

Note:
  Velocity factor is computed from group delay (preferred) and also from the
  first S21 null (λ/2 resonance).  Both are shown in the output.
""",
    )

    parser.add_argument("--start",       type=float, default=DEFAULT_START_KHZ,
                        metavar="KHZ",  help=f"Start frequency kHz (default {DEFAULT_START_KHZ})")
    parser.add_argument("--stop",        type=float, default=DEFAULT_STOP_KHZ,
                        metavar="KHZ",  help=f"Stop frequency kHz (default {DEFAULT_STOP_KHZ})")
    parser.add_argument("--points",      type=int,   default=DEFAULT_POINTS,
                        metavar="N",    help=f"Sweep points, 1–801 (default {DEFAULT_POINTS})")
    parser.add_argument("--length-m",    type=float, required=True,
                        metavar="M",    help="Physical cable length in metres (required)")
    parser.add_argument("--measure-z0", action="store_true",
                        help="Measure S11 open/short to estimate Z0 (prompts user)")
    parser.add_argument("--power",       type=float, default=DEFAULT_POWER_DBM,
                        metavar="DBM",  help=f"Stimulus power dBm (default {DEFAULT_POWER_DBM})")
    parser.add_argument("--host",        default=DEFAULT_HOST, metavar="HOST",
                        help=f"HP 8712B / KISS-488 host (default {DEFAULT_HOST})")
    parser.add_argument("--use-cal",     action="store_true",
                        help="Enable stored VNA calibration correction")
    parser.add_argument("--prefix",      default=None, metavar="TEXT",
                        help="Output file prefix (default: timestamped)")

    args = parser.parse_args()

    if args.prefix is None:
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        args.prefix = f"vna_tline_{ts}"

    if args.points < 1 or args.points > 801:
        print(f"Error: --points must be 1–801 (HP 8712B maximum is 801)")
        sys.exit(1)

    start_hz = args.start * 1_000.0
    stop_hz  = args.stop  * 1_000.0

    start_hz = max(start_hz, float(VNA_MIN_HZ))
    stop_hz  = min(stop_hz,  float(VNA_MAX_HZ))

    if start_hz >= stop_hz:
        print("Error: --start must be less than --stop")
        sys.exit(1)

    if args.length_m <= 0:
        print("Error: --length-m must be positive")
        sys.exit(1)

    print(f"Transmission Line Characterizer — HP 8712B VNA")
    print(f"  Cable length : {args.length_m:.4f} m")
    print(f"  Sweep        : {format_freq_short(start_hz)} – {format_freq_short(stop_hz)}")
    print(f"  Points       : {args.points}")
    print(f"  Power        : {args.power:+.0f} dBm")
    print(f"  Calibration  : {'ON' if args.use_cal else 'OFF'}")
    print(f"  Host         : {args.host}")
    print()

    vna = None
    z0_mid = None
    try:
        print(f"Connecting to HP 8712B @ {args.host} ...")
        vna = HP8712B(host=args.host)
        idn = vna.identify()
        print(f"  IDN: {idn}")

        # --- S21 measurement ---
        print("\n[S21 MEASUREMENT]")
        freqs_hz, s21_db, s21_phase_deg, _ = measure_s21(
            vna, start_hz, stop_hz, args.points, args.power, args.use_cal
        )

        # --- Group delay ---
        group_delay_s   = compute_group_delay(freqs_hz, s21_phase_deg)
        group_delay_ns  = group_delay_s * 1e9

        # --- Velocity factor (group delay method) ---
        vf_gd = velocity_factor_from_group_delay(group_delay_s, args.length_m)
        print(f"\n  Velocity factor (group delay): {vf_gd:.4f}")

        # --- Velocity factor (null method) ---
        null_freq, null_depth = find_first_s21_null(freqs_hz, s21_db)
        if null_freq is not None:
            vf_null = velocity_factor_from_null(null_freq, args.length_m)
            print(f"  First S21 null: {format_freq_short(null_freq)}  "
                  f"({null_depth:.1f} dB)  →  vf (null) = {vf_null:.4f}")
        else:
            vf_null = None
            print("  First S21 null: not found in sweep range")

        # --- Propagation loss ---
        mid_idx = len(freqs_hz) // 2
        # Average S21 over centre 10% of sweep (more stable than single-point)
        centre_lo = max(0,              mid_idx - len(freqs_hz) // 20)
        centre_hi = min(len(freqs_hz),  mid_idx + len(freqs_hz) // 20 + 1)
        s21_midband_db = float(np.mean(s21_db[centre_lo:centre_hi]))
        loss_db_per_m  = -s21_midband_db / args.length_m
        print(f"  S21 at midband: {s21_midband_db:.2f} dB  →  "
              f"loss = {loss_db_per_m:.3f} dB/m")

        # --- Optional Z0 measurement ---
        if args.measure_z0:
            print("\n[Z0 MEASUREMENT — open/short method]")
            print("  Switching to S11 measurement.")
            print()
            input("  Connect the FAR END of the cable as OPEN CIRCUIT (leave it unconnected).")
            print("  Measuring S11 with open-circuit termination ...")
            _, s11_oc = measure_s11_complex(vna, start_hz, stop_hz,
                                            args.points, args.power, args.use_cal)

            input("\n  Now connect a SHORT CIRCUIT to the FAR END of the cable.")
            print("  Measuring S11 with short-circuit termination ...")
            _, s11_sc = measure_s11_complex(vna, start_hz, stop_hz,
                                            args.points, args.power, args.use_cal)

            z0_f, z0_mid = estimate_z0(freqs_hz, s11_oc, s11_sc)
            print(f"\n  Estimated Z0 (midband): {z0_mid:.1f} Ω")

        # --- Save outputs ---
        print("\n[SAVING RESULTS]")

        txt_path = save_txt(
            freqs_hz, s21_db, s21_phase_deg, group_delay_ns,
            args.length_m, vf_gd, vf_null, null_freq, loss_db_per_m,
            z0_mid, args.prefix
        )
        print(f"  Text  → {txt_path}")

        json_path = save_json(
            freqs_hz, s21_db, s21_phase_deg, group_delay_ns,
            args.length_m, vf_gd, vf_null, null_freq, loss_db_per_m,
            z0_mid, args, args.prefix
        )
        print(f"  JSON  → {json_path}")

        try:
            png_path = plot_results(
                freqs_hz, s21_db, s21_phase_deg, group_delay_ns,
                args.length_m, vf_gd, vf_null, null_freq, loss_db_per_m,
                args.prefix
            )
            print(f"  Plot  → {png_path}")
        except Exception as exc:
            print(f"  Plot failed: {exc}")

        print("\n[SUMMARY]")
        print(f"  Cable length : {args.length_m:.4f} m")
        print(f"  Velocity factor (group delay): {vf_gd:.4f}")
        if vf_null is not None:
            print(f"  Velocity factor (null method): {vf_null:.4f}")
        print(f"  Loss at midband: {loss_db_per_m:.3f} dB/m  "
              f"({loss_db_per_m * args.length_m:.2f} dB total)")
        if z0_mid is not None:
            print(f"  Z0 (estimated): {z0_mid:.1f} Ω")

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
