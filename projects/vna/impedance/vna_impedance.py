#!/usr/bin/env python3
"""
vna_impedance.py — HP 8712B True RF Impedance Analyzer

Requires HP 8712B VNA and rf-bench-drivers-hp. The HP 8712B is not currently
connected — requires KISS-488 Ethernet-GPIB adapter.

Measures S11 (complex) and converts to impedance Z = R + jX:

    Z(f) = Z0 · (1 + Γ) / (1 - Γ)     where Γ = S11 (complex), Z0 = 50 Ω

Computes:
  - |Z|(f)       — impedance magnitude (Ω), plotted on log scale
  - R(f), X(f)   — resistance and reactance (Ω), plotted on linear scale
  - φ_Z(f)       — impedance phase (degrees)
  - Self-resonant frequency: where X crosses zero (first zero-crossing)

Also plots a Smith chart showing the Γ locus on the complex reflection plane
with constant-R circles and constant-X arcs.

Comparison note: This gives true Z(f) calibrated at the DUT terminals, unlike
rf-bench-rf-impedance (siglent-rf-impedance/) which uses a 50 Ω series
injection circuit and two-channel scope capture.  The series injection
approach is accurate up to ~30 MHz; this VNA approach is valid across the
full HP 8712B range (300 kHz – 1.3 GHz) when properly calibrated.

Outputs:
  {prefix}.png    — 4-panel: |Z| log, R+X linear, phase, Smith chart
  {prefix}.txt    — tabulated frequency / |Z| / R / X / phase
  {prefix}.json   — all data in JSON

Usage:
  python vna_impedance.py
  python vna_impedance.py --start 1000 --stop 200000 --use-cal
  python vna_impedance.py --output inductor_47uh
"""

import argparse
import json
import sys
from datetime import datetime

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
import numpy as np

from rf_bench.hp import HP8712B

# ---------------------------------------------------------------------------
# Defaults
# ---------------------------------------------------------------------------

DEFAULT_HOST      = "10.1.1.70"
DEFAULT_START_KHZ = 300
DEFAULT_STOP_KHZ  = 1_300_000
DEFAULT_POINTS    = 401
DEFAULT_POWER_DBM = -10.0
Z0 = 50.0   # Reference impedance (Ω)

# ---------------------------------------------------------------------------
# Impedance conversion
# ---------------------------------------------------------------------------

def gamma_to_z(gamma: np.ndarray, z0: float = Z0) -> np.ndarray:
    """
    Convert complex reflection coefficient Γ to impedance Z.

        Z = Z0 · (1 + Γ) / (1 - Γ)

    Handles the singularity at Γ = 1 (open circuit → Z → ∞) by returning NaN.
    """
    denom = 1.0 - gamma
    singular = np.abs(denom) < 1e-12
    denom = np.where(singular, np.complex128(1e-12 + 0j), denom)
    z = z0 * (1.0 + gamma) / denom
    z = np.where(singular, np.complex128(np.nan), z)
    return z


def find_self_resonance(freqs_hz: np.ndarray, reactance: np.ndarray) -> float:
    """
    Find self-resonant frequency as the first zero-crossing of reactance.

    Returns frequency in Hz, or NaN if no zero-crossing found.
    """
    # Look for sign changes in X
    signs = np.sign(reactance)
    crossings = np.where(np.diff(signs) != 0)[0]
    if len(crossings) == 0:
        return np.nan
    # Linear interpolation for first crossing
    i = crossings[0]
    x0, x1 = reactance[i], reactance[i + 1]
    f0, f1 = freqs_hz[i], freqs_hz[i + 1]
    # Interpolate: X = 0 between i and i+1
    fsr = f0 - x0 * (f1 - f0) / (x1 - x0)
    return fsr


# ---------------------------------------------------------------------------
# Measurement
# ---------------------------------------------------------------------------

def measure_s11(vna: HP8712B, start_hz: float, stop_hz: float,
                points: int, power_dbm: float) -> dict:
    """Measure S11 as complex array and derive impedance."""
    vna.setup_sweep(start_hz, stop_hz, points)
    vna.set_power(power_dbm)
    vna.set_parameter("S11")

    # Get frequency axis
    vna.set_format("MLOG")
    print("  S11 sweep ...", end="", flush=True)
    ok = vna.single_sweep()
    if not ok:
        print(" WARN: sweep timeout")
    freqs_hz = vna.get_frequencies()

    # Get complex S11
    s11 = vna.get_s_data()
    print(f" done  ({len(freqs_hz)} pts)")

    # Convert to impedance
    z = gamma_to_z(s11, Z0)
    r = z.real
    x = z.imag
    z_mag = np.abs(z)
    z_phase = np.angle(z, deg=True)

    fsr = find_self_resonance(freqs_hz, x)

    return {
        "freqs_hz":  freqs_hz,
        "s11":       s11,
        "z":         z,
        "r":         r,
        "x":         x,
        "z_mag":     z_mag,
        "z_phase":   z_phase,
        "fsr_hz":    fsr,
    }


# ---------------------------------------------------------------------------
# Smith chart helpers
# ---------------------------------------------------------------------------

def draw_smith_chart(ax, title: str = "Smith Chart (Γ plane)") -> None:
    """
    Draw constant-R circles and constant-X arcs on the complex Γ plane.

    All circles/arcs are clipped to the unit circle |Γ| ≤ 1.
    Uses standard Smith chart construction:
        Γ = (z_norm - 1) / (z_norm + 1)   where z_norm = Z/Z0

    Constant-R circles:  center ((r/(r+1)), 0),  radius 1/(r+1)
    Constant-X arcs:     center (1, 1/x),         radius 1/|x|
    """
    # Unit circle boundary
    theta = np.linspace(0, 2 * np.pi, 360)
    ax.plot(np.cos(theta), np.sin(theta), "k-", linewidth=1.0)
    ax.plot([-1, 1], [0, 0], "k-", linewidth=0.5, alpha=0.5)   # real axis

    # Constant-R circles: r = 0, 0.2, 0.5, 1, 2, 5
    r_values = [0, 0.2, 0.5, 1.0, 2.0, 5.0]
    for r in r_values:
        cx = r / (r + 1)
        radius = 1.0 / (r + 1)
        circle_theta = np.linspace(0, 2 * np.pi, 360)
        cx_pts = cx + radius * np.cos(circle_theta)
        cy_pts =       radius * np.sin(circle_theta)
        # Clip to unit circle
        mask = cx_pts**2 + cy_pts**2 <= 1.001
        # Only draw segments inside unit circle — simple masking via NaN
        cx_clipped = np.where(mask, cx_pts, np.nan)
        cy_clipped = np.where(mask, cy_pts, np.nan)
        ax.plot(cx_clipped, cy_clipped, color="gray", linewidth=0.4,
                alpha=0.5, linestyle="--")
        # Label at right edge of circle
        label_x = cx + radius
        if abs(label_x) <= 1.0:
            ax.text(label_x + 0.02, 0.01, f"{r}", fontsize=5,
                    color="dimgray", ha="left")

    # Constant-X arcs: x = ±0.5, ±1, ±2, ±5
    x_values = [0.5, 1.0, 2.0, 5.0]
    for x in x_values:
        for sign in [+1, -1]:
            xv = sign * x
            cx2 = 1.0
            cy2 = 1.0 / xv
            radius2 = abs(1.0 / xv)
            arc_theta = np.linspace(0, 2 * np.pi, 720)
            ax_pts = cx2 + radius2 * np.cos(arc_theta)
            ay_pts = cy2 + radius2 * np.sin(arc_theta)
            mask2 = ax_pts**2 + ay_pts**2 <= 1.001
            ax_clipped = np.where(mask2, ax_pts, np.nan)
            ay_clipped = np.where(mask2, ay_pts, np.nan)
            ax.plot(ax_clipped, ay_clipped, color="steelblue",
                    linewidth=0.4, alpha=0.5, linestyle=":")

    ax.set_xlim(-1.15, 1.15)
    ax.set_ylim(-1.15, 1.15)
    ax.set_aspect("equal")
    ax.set_title(title, fontsize=9)
    ax.axis("off")


# ---------------------------------------------------------------------------
# Text output
# ---------------------------------------------------------------------------

def save_txt(result: dict, prefix: str, start_hz: float, stop_hz: float,
             points: int, power_dbm: float, host: str, use_cal: bool) -> str:
    path = f"{prefix}.txt"
    freqs = result["freqs_hz"]
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    fsr = result["fsr_hz"]
    fsr_str = f"{fsr/1e6:.4f} MHz" if np.isfinite(fsr) else "not found"

    with open(path, "w") as f:
        f.write("HP 8712B RF Impedance Measurement\n")
        f.write("=" * 64 + "\n")
        f.write(f"Date/time  : {ts}\n")
        f.write(f"Instrument : {host}\n")
        f.write(f"Z0         : {Z0:.1f} Ω\n")
        f.write(f"Start      : {start_hz/1e6:.6f} MHz\n")
        f.write(f"Stop       : {stop_hz/1e6:.6f} MHz\n")
        f.write(f"Points     : {points}\n")
        f.write(f"Power      : {power_dbm:.1f} dBm\n")
        f.write(f"Cal        : {'on' if use_cal else 'off'}\n")
        f.write(f"SRF        : {fsr_str}\n\n")

        # Z at SRF
        if np.isfinite(fsr):
            # Interpolate Z magnitude at SRF
            idx = np.argmin(np.abs(freqs - fsr))
            f.write(f"Z at SRF   : |Z| = {result['z_mag'][idx]:.2f} Ω, "
                    f"R = {result['r'][idx]:.2f} Ω\n\n")

        hdr = (f"{'Freq (MHz)':>14}  {'|Z| (Ω)':>12}  "
               f"{'R (Ω)':>12}  {'X (Ω)':>12}  {'Phase (°)':>12}")
        f.write(hdr + "\n")
        f.write("-" * len(hdr) + "\n")

        for i in range(len(freqs)):
            f.write(f"{freqs[i]/1e6:>14.6f}  "
                    f"{result['z_mag'][i]:>12.4f}  "
                    f"{result['r'][i]:>12.4f}  "
                    f"{result['x'][i]:>12.4f}  "
                    f"{result['z_phase'][i]:>12.4f}\n")
    return path


# ---------------------------------------------------------------------------
# Plot
# ---------------------------------------------------------------------------

def plot_results(result: dict, prefix: str, start_hz: float,
                 stop_hz: float) -> str:
    freqs_mhz = result["freqs_hz"] / 1e6
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    fig = plt.figure(figsize=(15, 10))
    fig.suptitle(f"HP 8712B — RF Impedance Z(f)\n"
                 f"{start_hz/1e6:.4f} – {stop_hz/1e6:.0f} MHz  |  {ts}",
                 fontsize=11)

    gs = fig.add_gridspec(2, 2, hspace=0.35, wspace=0.35)
    ax1 = fig.add_subplot(gs[0, 0])   # |Z| log
    ax2 = fig.add_subplot(gs[0, 1])   # R + X linear
    ax3 = fig.add_subplot(gs[1, 0])   # Phase
    ax4 = fig.add_subplot(gs[1, 1])   # Smith chart

    # Panel 1: |Z| on log scale
    z_mag_plot = np.where(result["z_mag"] > 0, result["z_mag"], np.nan)
    ax1.semilogy(freqs_mhz, z_mag_plot, color="steelblue", linewidth=0.9)
    ax1.axhline(Z0, color="gray", linestyle="--", linewidth=0.7, alpha=0.7,
                label="50 Ω")
    fsr = result["fsr_hz"]
    if np.isfinite(fsr):
        ax1.axvline(fsr / 1e6, color="red", linestyle="--", linewidth=0.8,
                    alpha=0.8, label=f"SRF {fsr/1e6:.3f} MHz")
    ax1.set_xlabel("Frequency (MHz)", fontsize=8)
    ax1.set_ylabel("|Z| (Ω, log)", fontsize=8)
    ax1.set_title("|Z| vs Frequency", fontsize=9)
    ax1.legend(fontsize=7)
    ax1.grid(True, which="both", alpha=0.3)
    ax1.tick_params(labelsize=8)

    # Panel 2: R and X linear
    ax2.plot(freqs_mhz, result["r"], color="forestgreen", linewidth=0.8,
             label="R (resistance)")
    ax2.plot(freqs_mhz, result["x"], color="darkorange", linewidth=0.8,
             label="X (reactance)")
    ax2.axhline(0, color="black", linewidth=0.5, alpha=0.6)
    if np.isfinite(fsr):
        ax2.axvline(fsr / 1e6, color="red", linestyle="--", linewidth=0.8,
                    alpha=0.8, label=f"SRF {fsr/1e6:.3f} MHz")
    ax2.set_xlabel("Frequency (MHz)", fontsize=8)
    ax2.set_ylabel("Impedance (Ω)", fontsize=8)
    ax2.set_title("R + jX vs Frequency", fontsize=9)
    ax2.legend(fontsize=7, loc="upper right")
    ax2.grid(True, alpha=0.3)
    ax2.tick_params(labelsize=8)

    # Panel 3: Phase
    ax3.plot(freqs_mhz, result["z_phase"], color="purple", linewidth=0.8)
    ax3.axhline(0, color="black", linewidth=0.5, alpha=0.5)
    ax3.axhline(90, color="gray", linestyle=":", linewidth=0.5, alpha=0.5)
    ax3.axhline(-90, color="gray", linestyle=":", linewidth=0.5, alpha=0.5)
    if np.isfinite(fsr):
        ax3.axvline(fsr / 1e6, color="red", linestyle="--", linewidth=0.8,
                    alpha=0.8, label=f"SRF {fsr/1e6:.3f} MHz")
        ax3.legend(fontsize=7)
    ax3.set_xlabel("Frequency (MHz)", fontsize=8)
    ax3.set_ylabel("Phase of Z (degrees)", fontsize=8)
    ax3.set_title("Impedance Phase vs Frequency", fontsize=9)
    ax3.set_ylim(-100, 100)
    ax3.grid(True, alpha=0.3)
    ax3.tick_params(labelsize=8)

    # Panel 4: Smith chart
    draw_smith_chart(ax4, title="Smith Chart — S11 Locus")
    gamma = result["s11"]
    # Clip to unit circle for display (|Γ| > 1 is non-passive, likely noise)
    inside = np.abs(gamma) <= 1.0
    gamma_plot = gamma[inside]
    if len(gamma_plot) > 0:
        # Color by frequency
        freqs_in = result["freqs_hz"][inside]
        n = len(gamma_plot)
        colors = plt.cm.plasma(np.linspace(0, 1, n))
        ax4.scatter(gamma_plot.real, gamma_plot.imag, c=colors,
                    s=1.5, linewidths=0, zorder=5)
        # Mark start and end
        ax4.plot(gamma_plot[0].real, gamma_plot[0].imag, "go",
                 markersize=5, label=f"{freqs_in[0]/1e6:.3f} MHz")
        ax4.plot(gamma_plot[-1].real, gamma_plot[-1].imag, "r^",
                 markersize=5, label=f"{freqs_in[-1]/1e6:.3f} MHz")
        ax4.legend(fontsize=6, loc="lower left")

    fig.tight_layout()
    path = f"{prefix}.png"
    fig.savefig(path, dpi=150, bbox_inches="tight")
    plt.close(fig)
    return path


# ---------------------------------------------------------------------------
# main()
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="HP 8712B True RF Impedance Analyzer (S11 → Z = R + jX)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Setup:
  DUT connected to HP 8712B PORT 1.
  For accurate results, apply PORT 1 OSL (Open-Short-Load) 1-port calibration
  at the DUT reference plane before measuring.

Examples:
  python vna_impedance.py                              # full band
  python vna_impedance.py --start 1000 --stop 200000  # 1 MHz – 200 MHz
  python vna_impedance.py --use-cal --output inductor
  python vna_impedance.py --start 500 --stop 50000 --points 801
""",
    )

    parser.add_argument("--start",   type=float, default=DEFAULT_START_KHZ,
                        metavar="KHZ",
                        help=f"Start frequency in kHz (default {DEFAULT_START_KHZ})")
    parser.add_argument("--stop",    type=float, default=DEFAULT_STOP_KHZ,
                        metavar="KHZ",
                        help=f"Stop frequency in kHz (default {DEFAULT_STOP_KHZ})")
    parser.add_argument("--points",  type=int,   default=DEFAULT_POINTS,
                        metavar="N",
                        help=f"Sweep points, 1–801 (default {DEFAULT_POINTS})")
    parser.add_argument("--power",   type=float, default=DEFAULT_POWER_DBM,
                        metavar="DBM",
                        help=f"Stimulus power in dBm (default {DEFAULT_POWER_DBM})")
    parser.add_argument("--use-cal", action="store_true",
                        help="Enable stored calibration correction before measurement")
    parser.add_argument("--host",    default=DEFAULT_HOST, metavar="HOST",
                        help=f"KISS-488 IP address (default {DEFAULT_HOST})")
    parser.add_argument("--prefix",  default=None, metavar="TEXT",
                        help="Output filename prefix (default: timestamped)")

    args = parser.parse_args()

    if args.prefix is None:
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        args.prefix = f"vna_impedance_{ts}"

    start_hz = args.start * 1_000.0
    stop_hz  = args.stop  * 1_000.0
    if start_hz >= stop_hz:
        print("Error: --start must be less than --stop")
        sys.exit(1)
    if args.points > 801:
        print("Warning: clamping points to 801")
        args.points = 801

    print("HP 8712B RF Impedance Analyzer")
    print(f"  Host       : {args.host}")
    print(f"  Sweep      : {start_hz/1e6:.4f} – {stop_hz/1e6:.0f} MHz, {args.points} pts")
    print(f"  Power      : {args.power:.1f} dBm")
    print(f"  Use cal    : {args.use_cal}")
    print(f"  Z0         : {Z0:.1f} Ω")
    print(f"  Prefix     : {args.prefix}")
    print()

    vna = None
    try:
        print(f"Connecting to HP 8712B @ {args.host} ...")
        vna = HP8712B(host=args.host)
        print(f"  {vna.identify()}")

        if args.use_cal:
            vna.correction_on()
            print(f"  Correction: {'ON' if vna.is_correction_on() else 'OFF (not available?)'}")

        print("\n[MEASURING]")
        result = measure_s11(vna, start_hz, stop_hz, args.points, args.power)

        fsr = result["fsr_hz"]
        if np.isfinite(fsr):
            print(f"  Self-resonant frequency: {fsr/1e6:.4f} MHz")
        else:
            print("  Self-resonant frequency: not found in sweep range")

        # ---- Save outputs ----
        print("\n[SAVING RESULTS]")

        txt_path = save_txt(result, args.prefix, start_hz, stop_hz,
                            args.points, args.power, args.host, args.use_cal)
        print(f"Text   → {txt_path}")

        json_path = f"{args.prefix}.json"
        fsr_val = float(fsr) if np.isfinite(fsr) else None
        json_data = {
            "timestamp":  datetime.now().isoformat(),
            "host":       args.host,
            "z0_ohm":     Z0,
            "start_hz":   start_hz,
            "stop_hz":    stop_hz,
            "points":     args.points,
            "power_dbm":  args.power,
            "use_cal":    args.use_cal,
            "fsr_hz":     fsr_val,
            "freqs_hz":   result["freqs_hz"].tolist(),
            "s11_re":     result["s11"].real.tolist(),
            "s11_im":     result["s11"].imag.tolist(),
            "z_mag":      [x if np.isfinite(x) else None for x in result["z_mag"]],
            "r":          [x if np.isfinite(x) else None for x in result["r"]],
            "x":          [x if np.isfinite(x) else None for x in result["x"]],
            "z_phase":    [x if np.isfinite(x) else None for x in result["z_phase"]],
        }
        with open(json_path, "w") as jf:
            json.dump(json_data, jf, indent=2)
        print(f"JSON   → {json_path}")

        try:
            png_path = plot_results(result, args.prefix, start_hz, stop_hz)
            print(f"Plot   → {png_path}")
        except Exception as exc:
            print(f"Plot failed: {exc}")

        # Summary
        print("\n[SUMMARY]")
        valid = np.isfinite(result["z_mag"])
        if np.any(valid):
            print(f"  |Z| range : {np.nanmin(result['z_mag']):.2f} – "
                  f"{np.nanmax(result['z_mag']):.2f} Ω")
            print(f"  R range   : {np.nanmin(result['r']):.2f} – "
                  f"{np.nanmax(result['r']):.2f} Ω")
            print(f"  X range   : {np.nanmin(result['x']):.2f} – "
                  f"{np.nanmax(result['x']):.2f} Ω")
        if np.isfinite(fsr):
            idx = np.argmin(np.abs(result["freqs_hz"] - fsr))
            print(f"  SRF       : {fsr/1e6:.4f} MHz  "
                  f"(|Z| = {result['z_mag'][idx]:.2f} Ω at resonance)")

    except KeyboardInterrupt:
        print("\nInterrupted.")
        sys.exit(0)
    except ConnectionRefusedError as exc:
        print(f"\nCannot connect to HP 8712B: {exc}")
        print("Verify KISS-488 adapter is powered and at the correct IP.")
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
                vna.marker_off()
                vna.close()
            except Exception:
                pass


if __name__ == "__main__":
    main()
