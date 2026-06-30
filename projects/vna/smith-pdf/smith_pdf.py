#!/usr/bin/env python3
"""
smith_pdf.py — S11 → Smith-chart PDF, NanoVNA or HP 8712B.

Single-panel Smith chart of S11 vs frequency on VNA port 1, written to a
single-page PDF. Companion to ``swr_pdf.py`` — same swappable VNA API,
same defaults, just a different view of the same complex S11 trace.

The Smith chart plots Γ = S11 directly in the complex reflection plane:

  - Unit circle bounds                  |Γ| = 1 (open / shorted / lossless reactive)
  - Centre point                        Γ = 0, Z = Z0 (50 Ω, perfect match)
  - Constant-resistance circles         centre = (R/(R+1), 0),  radius = 1/(R+1)
  - Constant-reactance arcs             centre = (1, 1/X),      radius = 1/|X|
  - The Γ locus, colour-graded blue→red over frequency
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime
from typing import Optional

# Suppress mixed-install matplotlib Axes3D import warning (harmless;
# happens when system-package and pip-installed matplotlib are both present).
import warnings
warnings.filterwarnings("ignore", message="Unable to import Axes3D")

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.cm as cm
import numpy as np


DEFAULT_VNA      = "nanovna"
DEFAULT_PORT     = "/dev/ttyACM1"
DEFAULT_HP_HOST  = "10.1.1.70"
DEFAULT_POINTS   = 401
Z0               = 50.0

# Normalised constant-R / constant-X values to draw on the chart. These
# are the standard textbook gridlines.
SMITH_R_CIRCLES = [0.0, 0.2, 0.5, 1.0, 2.0, 5.0, 10.0]
SMITH_X_ARCS    = [0.2, 0.5, 1.0, 2.0, 5.0]   # drawn for ±X


# ---------------------------------------------------------------------------
# VNA construction
# ---------------------------------------------------------------------------

def open_vna(args):
    if args.vna == "nanovna":
        from rf_bench.nanovna import NanoVNA
        vna = NanoVNA(port=args.port)
    elif args.vna == "hp":
        from rf_bench.hp import HP8712B
        vna = HP8712B(host=args.host)
    else:
        raise ValueError(f"--vna must be 'nanovna' or 'hp', got {args.vna!r}")
    return vna, vna.identify()


def maybe_set_power(vna, dbm: Optional[float], vna_kind: str) -> None:
    if dbm is None:
        return
    try:
        vna.set_power(float(dbm))
        print(f"  Source power : {dbm:+.1f} dBm")
    except NotImplementedError:
        print(f"  Source power : --power ignored ({vna_kind} has no dBm setpoint)")


# ---------------------------------------------------------------------------
# Measurement
# ---------------------------------------------------------------------------

def measure_s11(vna, start_hz: float, stop_hz: float,
                points: int, averaging: int) -> tuple[np.ndarray, np.ndarray]:
    vna.setup_sweep(start_hz, stop_hz, points)
    vna.set_parameter("S11")
    ok = vna.single_sweep()
    if not ok:
        print("  WARNING: single_sweep() returned False — trace may be stale")
    freqs = vna.get_frequencies()
    gamma = vna.average_s_data(averaging) if averaging > 1 else vna.get_s_data()
    if len(freqs) != len(gamma):
        raise RuntimeError(
            f"VNA returned mismatched array lengths "
            f"(freqs={len(freqs)}, gamma={len(gamma)})"
        )
    return freqs, gamma


# ---------------------------------------------------------------------------
# Smith chart
# ---------------------------------------------------------------------------

def draw_smith_grid(ax) -> None:
    """Draw the unit circle, constant-R circles, and constant-X arcs."""
    theta = np.linspace(0, 2 * np.pi, 721)
    ax.plot(np.cos(theta), np.sin(theta), "k-", linewidth=1.3, zorder=2)

    grid = dict(linewidth=0.6, color="#aaaaaa", zorder=1)

    # Constant-R circles
    for r in SMITH_R_CIRCLES:
        cx  = r / (r + 1.0)
        rad = 1.0 / (r + 1.0)
        t   = np.linspace(0, 2 * np.pi, 721)
        gx  = cx + rad * np.cos(t)
        gy  = rad * np.sin(t)
        inside = gx ** 2 + gy ** 2 <= 1.0 + 1e-6
        ax.plot(gx[inside], gy[inside], **grid)
        if r > 0:
            ax.text(
                (r - 1.0) / (r + 1.0), -0.025, f"{r:g}",
                fontsize=6, ha="center", va="top",
                color="#666666", zorder=3,
            )

    # Constant-X arcs (positive and negative)
    for x_sign in (1.0, -1.0):
        for x in SMITH_X_ARCS:
            xv  = x_sign * x
            cy  = 1.0 / xv
            rad = abs(cy)
            t   = np.linspace(0, 2 * np.pi, 1441)
            gx  = 1.0 + rad * np.cos(t)
            gy  = cy  + rad * np.sin(t)
            inside = gx ** 2 + gy ** 2 <= 1.0 + 1e-6
            ax.plot(gx[inside], gy[inside], **grid)
            # Label X near the unit circle (where the arc intersects |Γ| = 1)
            # Skip 0 (handled by real axis) and label small/medium values only.
            if abs(xv) in (0.5, 1.0, 2.0):
                # Intersection of constant-X arc with unit circle:
                # Γ = (Z - 1)/(Z + 1) with Z = R + jX, find on |Γ| = 1 boundary
                # at R = 0 → Γ = (jX - 1)/(jX + 1). Compute and label.
                z = 0.0 + 1j * xv
                g = (z - 1.0) / (z + 1.0)
                offset_x = 0.025 * np.sign(g.real or 1.0)
                offset_y = 0.025 * np.sign(g.imag or 1.0)
                ax.text(
                    float(g.real) + offset_x,
                    float(g.imag) + offset_y,
                    f"{xv:+g}j",
                    fontsize=6, ha="center", va="center",
                    color="#666666", zorder=3,
                )

    # Real axis
    ax.axhline(0, color="#aaaaaa", linewidth=0.6, zorder=1)

    # Key reference points
    ax.plot(0,  0, "k+", markersize=7, zorder=4)   # Z = Z0
    ax.plot(-1, 0, "ks", markersize=4, zorder=4)   # open
    ax.plot(1,  0, "ks", markersize=4, zorder=4)   # short
    ax.text(0.0, 0.05, "50 Ω",  fontsize=6, ha="center", color="#444444", zorder=4)
    ax.text(-1.0, 0.05, "OPEN", fontsize=6, ha="center", color="#444444", zorder=4)
    ax.text(1.0, 0.05, "SHORT", fontsize=6, ha="center", color="#444444", zorder=4)

    ax.set_xlim(-1.10, 1.10)
    ax.set_ylim(-1.10, 1.10)
    ax.set_aspect("equal")
    ax.axis("off")


def plot_pdf(freqs_hz: np.ndarray, gamma: np.ndarray,
             label: str, driver_name: str, idn: str,
             output_path: str) -> None:
    sweep_lo_mhz = float(freqs_hz[0] / 1e6)
    sweep_hi_mhz = float(freqs_hz[-1] / 1e6)
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    fig, ax = plt.subplots(figsize=(9.5, 9.5))
    draw_smith_grid(ax)

    # Plot the Γ locus, coloured by frequency (blue → red)
    n = len(gamma)
    colors = cm.jet(np.linspace(0, 1, n))
    gx = gamma.real
    gy = gamma.imag
    for i in range(n - 1):
        ax.plot(
            [gx[i], gx[i + 1]], [gy[i], gy[i + 1]],
            color=colors[i], linewidth=1.4, zorder=5,
        )

    # Mark endpoints
    ax.plot(gx[0],  gy[0],  "o", color=colors[0],  markersize=7,
            markeredgecolor="k", zorder=6)
    ax.plot(gx[-1], gy[-1], "o", color=colors[-1], markersize=7,
            markeredgecolor="k", zorder=6)
    ax.annotate(
        f"{sweep_lo_mhz:.3f} MHz",
        xy=(gx[0], gy[0]),
        xytext=(8, 8), textcoords="offset points",
        fontsize=7, color="#202020",
        arrowprops=dict(arrowstyle="->", color="#202020", lw=0.6),
    )
    ax.annotate(
        f"{sweep_hi_mhz:.3f} MHz",
        xy=(gx[-1], gy[-1]),
        xytext=(8, -12), textcoords="offset points",
        fontsize=7, color="#202020",
        arrowprops=dict(arrowstyle="->", color="#202020", lw=0.6),
    )

    # Colourbar for frequency
    sm = cm.ScalarMappable(
        cmap="jet",
        norm=plt.Normalize(vmin=sweep_lo_mhz, vmax=sweep_hi_mhz),
    )
    sm.set_array([])
    cbar = fig.colorbar(sm, ax=ax, fraction=0.04, pad=0.02)
    cbar.set_label("Frequency (MHz)", fontsize=8)
    cbar.ax.tick_params(labelsize=7)

    title_lines = [
        f"Smith Chart — {label}",
        f"{sweep_lo_mhz:.3f} – {sweep_hi_mhz:.3f} MHz  •  {n} points  •  "
        f"{driver_name}  •  {ts}",
    ]
    if idn:
        title_lines.append(idn[:120])
    ax.set_title("\n".join(title_lines), fontsize=10)

    fig.tight_layout()
    fig.savefig(output_path, format="pdf")
    plt.close(fig)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> int:
    p = argparse.ArgumentParser(
        description="S11 → Smith-chart PDF for the antenna/DUT on VNA port 1.",
    )
    p.add_argument("--vna",   choices=("nanovna", "hp"), default=DEFAULT_VNA)
    p.add_argument("--port",  default=DEFAULT_PORT, help=f"(default: {DEFAULT_PORT})")
    p.add_argument("--host",  default=DEFAULT_HP_HOST, help=f"(default: {DEFAULT_HP_HOST})")
    p.add_argument("--start", type=float, required=True, metavar="MHZ")
    p.add_argument("--stop",  type=float, required=True, metavar="MHZ")
    p.add_argument("--points", type=int, default=DEFAULT_POINTS, metavar="N")
    p.add_argument("--average", type=int, default=1, metavar="N")
    p.add_argument("--power", type=float, default=None, metavar="DBM")
    p.add_argument("--label", default="DUT")
    p.add_argument("--output", required=True, metavar="FILE.pdf")
    args = p.parse_args()

    if args.start <= 0 or args.stop <= 0 or args.stop <= args.start:
        print("Error: --start and --stop must be positive with stop > start (MHz)")
        return 1
    if args.points < 2 or args.average < 1:
        print("Error: --points must be ≥ 2 and --average must be ≥ 1")
        return 1

    print(f"Smith PDF — {args.label}")
    print(f"  Driver       : {args.vna}")
    print(f"  Sweep        : {args.start:.3f} – {args.stop:.3f} MHz, "
          f"{args.points} points, average={args.average}")
    print(f"  Output       : {args.output}")

    vna = None
    try:
        vna, idn = open_vna(args)
        print(f"  IDN          : {idn[:120]}")
        maybe_set_power(vna, args.power, args.vna)

        freqs_hz, gamma = measure_s11(
            vna, args.start * 1e6, args.stop * 1e6, args.points, args.average,
        )

        mag = np.abs(gamma)
        print(f"  |Γ| min/mean/max : {mag.min():.3f} / {mag.mean():.3f} / {mag.max():.3f}")

        plot_pdf(
            freqs_hz, gamma,
            label=args.label,
            driver_name=args.vna.upper(),
            idn=idn,
            output_path=args.output,
        )
        print(f"  Wrote PDF    → {args.output}")
        return 0

    except KeyboardInterrupt:
        print("\nInterrupted.")
        return 130
    except Exception as exc:
        print(f"\nFailed: {exc}", file=sys.stderr)
        return 1
    finally:
        if vna is not None:
            try:
                vna.close()
            except Exception:
                pass


if __name__ == "__main__":
    sys.exit(main())
