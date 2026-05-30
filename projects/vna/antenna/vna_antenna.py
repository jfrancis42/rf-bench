#!/usr/bin/env python3
"""
Antenna Feed-Point Impedance Analyzer — HP 8712B VNA

Requires HP 8712B VNA and rf-bench-drivers-hp. The HP 8712B is not currently
connected — requires KISS-488 Ethernet-GPIB adapter.

Measures S11 (complex) from a calibrated VNA Port 1.  Derives the full set of
antenna impedance parameters from the reflection coefficient Γ = S11:

  Z(f) = R(f) + jX(f) = Z0 × (1 + Γ) / (1 − Γ)    [Z0 = 50 Ω]
  |Γ(f)|   — reflection coefficient magnitude
  VSWR(f)  = (1 + |Γ|) / (1 − |Γ|)
  RL(f)    = −20·log10(|Γ|)  in dB  (return loss, positive = good)

Self-resonant frequencies are found where X(f) crosses zero.  The crossing
direction (+ → − = series resonance; − → + = anti-resonance) is noted.

Plots
-----
  Top    : VSWR vs frequency, log Y axis.  Reference lines at 1.5:1, 2:1, 3:1.
  Middle : R (resistance) and X (reactance) vs frequency.
  Bottom : Smith chart with Z locus coloured by frequency (blue → red).
           Chart is drawn manually: unit circle, constant-R and constant-X
           circles/arcs for standard normalised values.

The output VSWR table format is backwards-compatible with rf-bench-antenna-analyzer
(same column headers) so the two tools' outputs can be compared directly.

Options
-------
  --start KHZ   (default 1800, bottom of 160 m band)
  --stop KHZ    (default 30000, top of 10 m / HF coverage)
  --points N    (default 401)
  --power DBM   (default -10)
  --use-cal     enable stored SOLT calibration
  --host HOST
  --prefix TEXT

Output files
------------
  {prefix}.png   — 3-panel plot + Smith chart
  {prefix}.txt   — text table with VSWR, R, X, RL and resonance annotations
  {prefix}.json  — full numerical data (compatible with rf-bench-antenna-analyzer)
"""

import argparse
import json
import sys
from datetime import datetime

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.cm as cm
import numpy as np

from rf_bench.hp import HP8712B
from rf_bench.utils import (
    format_freq,
    format_freq_short,
    rl_to_vswr,
)

# ---------------------------------------------------------------------------
# Defaults
# ---------------------------------------------------------------------------

DEFAULT_HOST      = "10.1.1.70"
DEFAULT_START_KHZ = 1_800
DEFAULT_STOP_KHZ  = 30_000
DEFAULT_POINTS    = 401
DEFAULT_POWER_DBM = -10.0
Z0                = 50.0

VNA_MIN_HZ = 300_000
VNA_MAX_HZ = 1_300_000_000

# VSWR threshold lines on plot
VSWR_LINES = [1.5, 2.0, 3.0]
VSWR_COLORS = {1.5: 'green', 2.0: 'orange', 3.0: 'red'}

# Smith chart constant-R and constant-X normalised values to draw
SMITH_R_CIRCLES  = [0.0, 0.25, 0.5, 1.0, 2.0, 5.0, 10.0]
SMITH_X_ARCS     = [0.25, 0.5, 1.0, 2.0, 5.0]   # positive and negative arcs drawn

# Amateur radio HF bands (kHz) for resonance annotation
HF_BANDS = [
    (1800, 2000,   "160m"),
    (3500, 4000,   "80m"),
    (7000, 7300,   "40m"),
    (10100, 10150, "30m"),
    (14000, 14350, "20m"),
    (18068, 18168, "17m"),
    (21000, 21450, "15m"),
    (24890, 24990, "12m"),
    (28000, 29700, "10m"),
]


# ---------------------------------------------------------------------------
# Measurement
# ---------------------------------------------------------------------------

def measure_s11(vna: HP8712B, start_hz: float, stop_hz: float,
                points: int, power_dbm: float, use_cal: bool
                ) -> tuple[np.ndarray, np.ndarray]:
    """
    Measure S11 as a complex array.

    Returns (freqs_hz, gamma) where gamma is complex (S11 = Γ).
    Uses get_s_data() for the highest-accuracy complex retrieval.
    """
    print(f"  Setting up sweep: {format_freq_short(start_hz)} – "
          f"{format_freq_short(stop_hz)}, {points} pts, {power_dbm:+.0f} dBm")

    vna.setup_sweep(start_hz, stop_hz, points)
    vna.set_power(power_dbm)
    vna.set_parameter("S11")

    if use_cal:
        vna.correction_on()
        print("  Calibration correction: ON")
    else:
        vna.correction_off()
        print("  Calibration correction: OFF  (results may include port mismatch)")

    vna.set_format("MLOG")
    ok = vna.single_sweep()
    if not ok:
        print("  WARNING: sweep OPC timeout — data may be incomplete")

    freqs_hz = vna.get_frequencies()
    gamma    = vna.get_s_data()   # complex S11

    return freqs_hz, gamma


# ---------------------------------------------------------------------------
# Analysis
# ---------------------------------------------------------------------------

def gamma_to_impedance(gamma: np.ndarray, z0: float = Z0) -> np.ndarray:
    """Z = Z0 × (1 + Γ) / (1 − Γ), complex array."""
    denom = 1.0 - gamma
    # Guard against |Γ| = 1 (open/short termination)
    denom = np.where(np.abs(denom) < 1e-10, 1e-10 + 0j, denom)
    return z0 * (1.0 + gamma) / denom


def gamma_to_vswr_array(gamma: np.ndarray) -> np.ndarray:
    """VSWR = (1 + |Γ|) / (1 − |Γ|), clamped at 999."""
    mag = np.abs(gamma)
    mag = np.clip(mag, 0.0, 1.0 - 1e-6)
    return (1.0 + mag) / (1.0 - mag)


def gamma_to_rl_db(gamma: np.ndarray) -> np.ndarray:
    """Return loss = −20·log10(|Γ|) in dB (positive = good match)."""
    mag = np.abs(gamma)
    mag = np.clip(mag, 1e-10, None)
    return -20.0 * np.log10(mag)


def find_resonances(freqs_hz: np.ndarray, z_ohm: np.ndarray
                    ) -> list[dict]:
    """
    Find self-resonant frequencies where X(f) crosses zero.

    Returns a list of dicts: {freq_hz, r_ohm, vswr, type}
    where type is 'series' (X: + → −, R typically low) or
    'parallel' (X: − → +, R typically high).
    """
    x = z_ohm.imag
    crossings = np.where(np.diff(np.sign(x)))[0]
    resonances = []
    for i in crossings:
        # Linear interpolation for better frequency precision
        x0, x1 = x[i], x[i + 1]
        f0, f1 = freqs_hz[i], freqs_hz[i + 1]
        frac = -x0 / (x1 - x0 + 1e-30)
        f_res  = float(f0 + frac * (f1 - f0))
        r_res  = float(z_ohm.real[i] + frac * (z_ohm.real[i + 1] - z_ohm.real[i]))
        # VSWR at resonance (use R only since X ≈ 0)
        gamma_res = abs((r_res - Z0) / (r_res + Z0 + 1e-30))
        vswr_res  = (1 + gamma_res) / max(1 - gamma_res, 1e-6)
        crossing_type = 'series' if x0 > 0 else 'parallel'
        resonances.append({
            "freq_hz":    f_res,
            "r_ohm":      r_res,
            "vswr":       vswr_res,
            "type":       crossing_type,
        })
    return resonances


# ---------------------------------------------------------------------------
# Smith chart drawing
# ---------------------------------------------------------------------------

def draw_smith_chart(ax) -> None:
    """
    Draw a Smith chart grid on the given axes.

    Plots constant-resistance circles and constant-reactance arcs (clipped to
    the unit disk) using normalised impedance coordinates.  The centre of the
    chart is the (0+j0) reflection point (Γ = 0, Z = Z0).

    Γ = (z_norm − 1) / (z_norm + 1)   where z_norm = Z / Z0

    Constant-R circles: centre = (R/(R+1), 0), radius = 1/(R+1)
    Constant-X arcs:    centre = (1, 1/X),     radius = 1/|X|   (clipped to |Γ| ≤ 1)
    """
    # Outer unit circle (|Γ| = 1 boundary)
    theta = np.linspace(0, 2 * np.pi, 361)
    ax.plot(np.cos(theta), np.sin(theta), 'k-', linewidth=1.2, zorder=2)

    chart_style = dict(linewidth=0.6, color='#aaaaaa', zorder=1)

    # --- Constant-R circles ---
    for r in SMITH_R_CIRCLES:
        cx = r / (r + 1.0)
        rad = 1.0 / (r + 1.0)
        t = np.linspace(0, 2 * np.pi, 361)
        gx = cx + rad * np.cos(t)
        gy = rad * np.sin(t)
        # Clip to unit disk
        inside = gx**2 + gy**2 <= 1.0 + 1e-6
        # Break into segments at clipping boundary
        ax.plot(gx[inside], gy[inside], **chart_style)
        # Label the real axis crossing
        if r > 0:
            gx_label = (r - 1.0) / (r + 1.0)
            ax.text(gx_label, -0.03, f'{r}',
                    fontsize=5, ha='center', color='#888888', zorder=3)

    # --- Constant-X arcs (positive and negative) ---
    for x_sign in [1.0, -1.0]:
        for x in SMITH_X_ARCS:
            xv  = x_sign * x
            cy  = 1.0 / xv
            rad = abs(cy)
            # Parametric arc: Γ = (1 + j·radius·e^(jt) - 1)... just sample finely
            t   = np.linspace(0, 2 * np.pi, 721)
            gx  = 1.0 + rad * np.cos(t)
            gy  = cy  + rad * np.sin(t)
            inside = gx**2 + gy**2 <= 1.0 + 1e-6
            if np.any(inside):
                ax.plot(gx[inside], gy[inside], **chart_style)

    # Real axis (reactance = 0)
    ax.axhline(0, color='#aaaaaa', linewidth=0.6, zorder=1)

    # Mark key points
    ax.plot(0, 0, 'k+', markersize=5, zorder=4)     # Z = Z0 (50 Ω)
    ax.plot(-1, 0, 'ks', markersize=3, zorder=4)    # open circuit
    ax.plot(1, 0, 'ks', markersize=3, zorder=4)     # short circuit

    ax.set_xlim(-1.05, 1.05)
    ax.set_ylim(-1.05, 1.05)
    ax.set_aspect('equal')
    ax.axis('off')


# ---------------------------------------------------------------------------
# Plotting
# ---------------------------------------------------------------------------

def plot_results(freqs_hz: np.ndarray, gamma: np.ndarray,
                 z_ohm: np.ndarray, vswr: np.ndarray, rl_db: np.ndarray,
                 resonances: list[dict],
                 output_prefix: str) -> str:
    """Generate 4-panel figure (VSWR, R+X, Smith chart).  Returns file path."""
    freqs_mhz = freqs_hz / 1e6
    ts        = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    # Figure layout: 3 rows, 2 cols.  Left column: VSWR, R+X.  Right: Smith chart.
    fig = plt.figure(figsize=(14, 12))
    ax_vswr  = fig.add_subplot(3, 2, 1)
    ax_rx    = fig.add_subplot(3, 2, 3, sharex=ax_vswr)
    ax_rl    = fig.add_subplot(3, 2, 5, sharex=ax_vswr)
    ax_smith = fig.add_subplot(1, 2, 2)

    # ----------------------------------------------------------------
    # Panel 1: VSWR
    # ----------------------------------------------------------------
    ax_vswr.semilogy(freqs_mhz, vswr, color='#1f77b4', linewidth=1.2, label='VSWR')
    for v, col in VSWR_COLORS.items():
        ax_vswr.axhline(v, color=col, linestyle='--', linewidth=0.8,
                        alpha=0.7, label=f'{v:.1f}:1')
    # Resonance markers on VSWR panel
    for res in resonances:
        ax_vswr.axvline(res["freq_hz"] / 1e6, color='purple', linestyle=':',
                        linewidth=0.7, alpha=0.7)
        ax_vswr.annotate(
            f'{format_freq_short(res["freq_hz"])}\n{res["type"][:3]}',
            xy=(res["freq_hz"] / 1e6, res["vswr"]),
            fontsize=5.5, color='purple',
            xytext=(0, 5), textcoords='offset points',
        )
    ax_vswr.set_ylim(0.9, min(50.0, np.max(vswr) * 1.5))
    ax_vswr.set_ylabel("VSWR", fontsize=9)
    ax_vswr.set_title(
        f"Antenna Impedance — HP 8712B VNA  |  {ts}\n"
        f"Sweep: {format_freq_short(freqs_hz[0])} – {format_freq_short(freqs_hz[-1])}  |  "
        f"{len(freqs_hz)} points",
        fontsize=9,
    )
    ax_vswr.grid(True, which='both', alpha=0.3)
    ax_vswr.legend(fontsize=7, loc='upper right')
    ax_vswr.tick_params(labelsize=8)

    # ----------------------------------------------------------------
    # Panel 2: R and X
    # ----------------------------------------------------------------
    ax_rx.plot(freqs_mhz, z_ohm.real, color='#d62728', linewidth=1.2, label='R (Ω)')
    ax_rx.plot(freqs_mhz, z_ohm.imag, color='#2ca02c', linewidth=1.2, label='X (Ω)')
    ax_rx.axhline(0,  color='k', linewidth=0.5, alpha=0.5)
    ax_rx.axhline(50, color='#d62728', linewidth=0.5, linestyle=':', alpha=0.5)
    for res in resonances:
        ax_rx.axvline(res["freq_hz"] / 1e6, color='purple', linestyle=':',
                      linewidth=0.7, alpha=0.7)
    ax_rx.set_ylabel("Impedance (Ω)", fontsize=9)
    ax_rx.grid(True, alpha=0.3)
    ax_rx.legend(fontsize=7, loc='upper right')
    ax_rx.tick_params(labelsize=8)

    # ----------------------------------------------------------------
    # Panel 3: Return loss
    # ----------------------------------------------------------------
    ax_rl.plot(freqs_mhz, rl_db, color='#ff7f0e', linewidth=1.2, label='Return loss')
    ax_rl.axhline(6.0,  color='red',   linestyle='--', linewidth=0.7, alpha=0.7,
                  label='6 dB (3:1 VSWR)')
    ax_rl.axhline(9.5,  color='darkorange', linestyle='--', linewidth=0.7, alpha=0.7,
                  label='9.5 dB (2:1 VSWR)')
    ax_rl.axhline(14.0, color='green', linestyle='--', linewidth=0.7, alpha=0.7,
                  label='14 dB (1.5:1 VSWR)')
    for res in resonances:
        ax_rl.axvline(res["freq_hz"] / 1e6, color='purple', linestyle=':',
                      linewidth=0.7, alpha=0.7)
    ax_rl.set_xlabel("Frequency (MHz)", fontsize=9)
    ax_rl.set_ylabel("Return Loss (dB)", fontsize=9)
    ax_rl.grid(True, alpha=0.3)
    ax_rl.legend(fontsize=7, loc='lower right')
    ax_rl.tick_params(labelsize=8)

    # ----------------------------------------------------------------
    # Smith chart (right half of figure)
    # ----------------------------------------------------------------
    draw_smith_chart(ax_smith)

    # Plot the Z locus coloured by frequency (blue → red via jet)
    n_pts  = len(gamma)
    colors = cm.jet(np.linspace(0, 1, n_pts))

    # Normalise Z to Smith chart Γ coordinates
    gx = gamma.real
    gy = gamma.imag

    for i in range(n_pts - 1):
        ax_smith.plot([gx[i], gx[i + 1]], [gy[i], gy[i + 1]],
                      color=colors[i], linewidth=1.2, zorder=5)

    # Mark resonances on Smith chart
    for res in resonances:
        idx = int(np.argmin(np.abs(freqs_hz - res["freq_hz"])))
        ax_smith.plot(gx[idx], gy[idx], 'o', color='purple',
                      markersize=5, zorder=6)
        ax_smith.annotate(
            f'{format_freq_short(res["freq_hz"])}',
            xy=(gx[idx], gy[idx]),
            xytext=(4, 4), textcoords='offset points',
            fontsize=5.5, color='purple', zorder=7,
        )

    # Colourbar for frequency
    sm = cm.ScalarMappable(
        cmap='jet',
        norm=plt.Normalize(vmin=freqs_hz[0] / 1e6, vmax=freqs_hz[-1] / 1e6)
    )
    sm.set_array([])
    cbar = fig.colorbar(sm, ax=ax_smith, fraction=0.04, pad=0.02)
    cbar.set_label("Frequency (MHz)", fontsize=7)
    cbar.ax.tick_params(labelsize=6)

    ax_smith.set_title("Smith Chart (Z locus, blue→red = low→high f)", fontsize=8)

    plt.tight_layout()
    path = f"{output_prefix}.png"
    plt.savefig(path, dpi=150, bbox_inches='tight')
    plt.close(fig)
    return path


# ---------------------------------------------------------------------------
# Text + JSON
# ---------------------------------------------------------------------------

def save_txt(freqs_hz: np.ndarray, vswr: np.ndarray,
             z_ohm: np.ndarray, rl_db: np.ndarray,
             resonances: list[dict], output_prefix: str) -> str:
    """
    Write text table.  VSWR column format matches rf-bench-antenna-analyzer
    output for backwards compatibility.
    """
    path = f"{output_prefix}.txt"
    ts   = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    sep  = "=" * 80

    lines = [
        sep,
        "  ANTENNA FEED-POINT IMPEDANCE REPORT — HP 8712B VNA",
        f"  Generated  : {ts}",
        f"  Sweep      : {format_freq(freqs_hz[0])} – {format_freq(freqs_hz[-1])}",
        f"  Points     : {len(freqs_hz)}",
        f"  Reference Z: {Z0:.0f} Ω",
        sep,
    ]

    # Resonance table
    if resonances:
        lines += [
            "",
            "  SELF-RESONANCES (X = 0 crossings)",
            "  -----------------------------------",
            f"  {'Frequency':>16}  {'Type':>10}  {'R (Ω)':>8}  {'VSWR':>7}",
            "  " + "-" * 48,
        ]
        for res in resonances:
            band_tag = ""
            for blo, bhi, bname in HF_BANDS:
                if blo * 1e3 <= res["freq_hz"] <= bhi * 1e3:
                    band_tag = f"  [{bname}]"
                    break
            lines.append(
                f"  {format_freq(res['freq_hz']):>16}  "
                f"{res['type']:>10}  "
                f"{res['r_ohm']:>8.1f}  "
                f"{res['vswr']:>7.2f}{band_tag}"
            )
    else:
        lines += ["", "  No self-resonances found within sweep range."]

    # VSWR ≤ 2:1 windows for HF bands
    lines += [
        "",
        "  VSWR ≤ 2.0 WINDOWS (HF AMATEUR BANDS)",
        "  ----------------------------------------",
    ]
    for blo, bhi, bname in HF_BANDS:
        blo_hz = blo * 1e3
        bhi_hz = bhi * 1e3
        if freqs_hz[0] > bhi_hz or freqs_hz[-1] < blo_hz:
            continue
        band_mask = (freqs_hz >= blo_hz) & (freqs_hz <= bhi_hz)
        if not np.any(band_mask):
            continue
        band_vswr = vswr[band_mask]
        band_freq = freqs_hz[band_mask]
        low_vswr  = band_vswr <= 2.0
        if np.any(low_vswr):
            f_usable_lo = float(band_freq[low_vswr][0])
            f_usable_hi = float(band_freq[low_vswr][-1])
            min_vswr    = float(np.min(band_vswr[low_vswr]))
            lines.append(
                f"  {bname:>5}: {format_freq(f_usable_lo)} – "
                f"{format_freq(f_usable_hi)}  "
                f"(min VSWR {min_vswr:.2f})"
            )
        else:
            min_vswr = float(np.min(band_vswr))
            lines.append(
                f"  {bname:>5}: VSWR > 2.0 throughout  (best {min_vswr:.2f})"
            )

    # Data table — backwards-compatible with rf-bench-antenna-analyzer
    lines += [
        "",
        sep,
        f"  {'Frequency':>16}  {'VSWR':>7}  {'RL (dB)':>9}  {'R (Ω)':>8}  {'X (Ω)':>9}",
        "  " + "-" * 58,
    ]

    step = max(1, len(freqs_hz) // 100)
    for i in range(0, len(freqs_hz), step):
        lines.append(
            f"  {format_freq(freqs_hz[i]):>16}  "
            f"{vswr[i]:>7.2f}  "
            f"{rl_db[i]:>9.2f}  "
            f"{z_ohm.real[i]:>8.1f}  "
            f"{z_ohm.imag[i]:>+9.1f}"
        )

    text = "\n".join(lines) + "\n"
    with open(path, "w") as fh:
        fh.write(text)
    return path


def save_json(freqs_hz: np.ndarray, gamma: np.ndarray,
              z_ohm: np.ndarray, vswr: np.ndarray, rl_db: np.ndarray,
              resonances: list[dict], args, output_prefix: str) -> str:
    """Write JSON data.  Returns path."""
    path = f"{output_prefix}.json"

    def _clean(arr):
        return [x if np.isfinite(x) else None for x in arr.tolist()]

    data = {
        "timestamp":  datetime.now().isoformat(),
        "instrument": "HP 8712B",
        "host":       args.host,
        "start_hz":   float(freqs_hz[0]),
        "stop_hz":    float(freqs_hz[-1]),
        "points":     len(freqs_hz),
        "power_dbm":  args.power,
        "use_cal":    args.use_cal,
        "z0_ohm":     Z0,
        "resonances": [
            {
                "freq_hz":  r["freq_hz"],
                "r_ohm":    r["r_ohm"],
                "vswr":     r["vswr"],
                "type":     r["type"],
            } for r in resonances
        ],
        "freqs_hz":       freqs_hz.tolist(),
        "vswr":           _clean(vswr),
        "return_loss_db": _clean(rl_db),
        "r_ohm":          _clean(z_ohm.real),
        "x_ohm":          _clean(z_ohm.imag),
        "gamma_real":     _clean(gamma.real),
        "gamma_imag":     _clean(gamma.imag),
    }

    with open(path, "w") as jf:
        json.dump(data, jf, indent=2)
    return path


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Antenna feed-point impedance analyzer — HP 8712B VNA",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Measures S11 (complex) from Port 1, derives Z, VSWR, and return loss.
Plots VSWR, R+X vs frequency, and Smith chart.  Output is backwards-compatible
with rf-bench-antenna-analyzer (same VSWR table format).

Setup:
  HP 8712B Port 1 → coax → antenna feed point
  Use stored SOLT calibration (--use-cal) for most accurate results.
  Calibration plane is at the Port 1 connector.

Examples:
  python vna_antenna.py                              # 160–10 m HF
  python vna_antenna.py --start 3500 --stop 4000    # 80 m band only
  python vna_antenna.py --start 1800 --stop 30000 --use-cal --prefix dipole_40m
  python vna_antenna.py --start 144000 --stop 148000 --points 401  # 2 m
""",
    )

    parser.add_argument("--start",   type=float, default=DEFAULT_START_KHZ,
                        metavar="KHZ", help=f"Start frequency kHz (default {DEFAULT_START_KHZ})")
    parser.add_argument("--stop",    type=float, default=DEFAULT_STOP_KHZ,
                        metavar="KHZ", help=f"Stop frequency kHz (default {DEFAULT_STOP_KHZ})")
    parser.add_argument("--points",  type=int,   default=DEFAULT_POINTS,
                        metavar="N",   help=f"Sweep points, 1–801 (default {DEFAULT_POINTS})")
    parser.add_argument("--power",   type=float, default=DEFAULT_POWER_DBM,
                        metavar="DBM", help=f"Stimulus power dBm (default {DEFAULT_POWER_DBM})")
    parser.add_argument("--host",    default=DEFAULT_HOST, metavar="HOST",
                        help=f"HP 8712B / KISS-488 host (default {DEFAULT_HOST})")
    parser.add_argument("--use-cal", action="store_true",
                        help="Enable stored SOLT calibration correction (recommended)")
    parser.add_argument("--prefix",  default=None, metavar="TEXT",
                        help="Output file prefix (default: timestamped)")

    args = parser.parse_args()

    if args.prefix is None:
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        args.prefix = f"vna_antenna_{ts}"

    if args.points < 1 or args.points > 801:
        print("Error: --points must be 1–801 (HP 8712B maximum is 801)")
        sys.exit(1)

    start_hz = max(args.start * 1_000.0, float(VNA_MIN_HZ))
    stop_hz  = min(args.stop  * 1_000.0, float(VNA_MAX_HZ))

    if start_hz >= stop_hz:
        print("Error: --start must be less than --stop")
        sys.exit(1)

    if not args.use_cal:
        print("Warning: --use-cal not specified.  Results will include port connector "
              "mismatch.  For accurate antenna impedance, run a SOLT cal first.")

    print("Antenna Feed-Point Impedance Analyzer — HP 8712B VNA")
    print(f"  Sweep      : {format_freq_short(start_hz)} – {format_freq_short(stop_hz)}")
    print(f"  Points     : {args.points}")
    print(f"  Power      : {args.power:+.0f} dBm")
    print(f"  Calibration: {'ON (SOLT)' if args.use_cal else 'OFF (raw)'}")
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
        freqs_hz, gamma = measure_s11(
            vna, start_hz, stop_hz, args.points, args.power, args.use_cal
        )

        # --- Derived parameters ---
        z_ohm  = gamma_to_impedance(gamma)
        vswr   = gamma_to_vswr_array(gamma)
        rl_db  = gamma_to_rl_db(gamma)

        # Summary statistics
        min_vswr_idx = int(np.argmin(vswr))
        print(f"\n  Best VSWR    : {vswr[min_vswr_idx]:.2f}:1  "
              f"@ {format_freq_short(freqs_hz[min_vswr_idx])}")
        print(f"  Best RL      : {rl_db[min_vswr_idx]:.1f} dB")
        print(f"  Z at best RL : {z_ohm.real[min_vswr_idx]:.1f} "
              f"{z_ohm.imag[min_vswr_idx]:+.1f}j Ω")

        # --- Resonances ---
        resonances = find_resonances(freqs_hz, z_ohm)
        if resonances:
            print(f"\n  Self-resonances found: {len(resonances)}")
            for res in resonances:
                band_tag = ""
                for blo, bhi, bname in HF_BANDS:
                    if blo * 1e3 <= res["freq_hz"] <= bhi * 1e3:
                        band_tag = f"  [{bname}]"
                        break
                print(f"    {format_freq_short(res['freq_hz']):>12}  "
                      f"{res['type']:10}  R = {res['r_ohm']:.1f} Ω  "
                      f"VSWR = {res['vswr']:.2f}{band_tag}")
        else:
            print("\n  No self-resonances found in sweep range")

        # --- Save outputs ---
        print("\n[SAVING RESULTS]")

        txt_path = save_txt(freqs_hz, vswr, z_ohm, rl_db, resonances, args.prefix)
        print(f"  Text  → {txt_path}")

        json_path = save_json(freqs_hz, gamma, z_ohm, vswr, rl_db,
                              resonances, args, args.prefix)
        print(f"  JSON  → {json_path}")

        try:
            png_path = plot_results(
                freqs_hz, gamma, z_ohm, vswr, rl_db, resonances, args.prefix
            )
            print(f"  Plot  → {png_path}")
        except Exception as exc:
            print(f"  Plot failed: {exc}")

        # Print VSWR ≤ 2.0 windows for bands in sweep range
        print("\n[VSWR ≤ 2.0 WINDOWS]")
        found_any = False
        for blo, bhi, bname in HF_BANDS:
            blo_hz = blo * 1e3
            bhi_hz = bhi * 1e3
            if freqs_hz[0] > bhi_hz or freqs_hz[-1] < blo_hz:
                continue
            band_mask = (freqs_hz >= blo_hz) & (freqs_hz <= bhi_hz)
            if not np.any(band_mask):
                continue
            band_vswr = vswr[band_mask]
            band_freq = freqs_hz[band_mask]
            low_vswr  = band_vswr <= 2.0
            if np.any(low_vswr):
                found_any = True
                f_lo = float(band_freq[low_vswr][0])
                f_hi = float(band_freq[low_vswr][-1])
                print(f"  {bname:>5}: {format_freq_short(f_lo)} – "
                      f"{format_freq_short(f_hi)}")
        if not found_any:
            print("  No VSWR ≤ 2.0 windows found in sweep range.")

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
