#!/usr/bin/env python3
"""
impedance_pdf.py — S11 → R, X, |Z|, VSWR, Smith locus, NanoVNA or HP 8712B.

Multi-panel diagnostic PDF for any one-port impedance measurement:
antennas, matching networks, filters terminated in 50 Ω, balun input
ports, you name it. This supersedes the legacy `antenna/` and
`impedance/` projects (both of which were HP-only stubs that did
different subsets of the same job).

Quantities derived from the calibrated S11 = Γ:

    Z(f)    = Z0 · (1 + Γ) / (1 - Γ)              complex Ω
    R(f), X(f) = Re Z, Im Z
    |Z|(f)   = sqrt(R² + X²)
    ∠Z(f)    = atan2(X, R)                          °
    VSWR(f)  = (1 + |Γ|) / (1 - |Γ|)
    RL(f)    = -20·log10(|Γ|)                       dB

Optional resonance hunting (`--resonances`): X(f) zero-crossings, with
the closest sweep point reported. Series resonance: X→0 with R small;
parallel resonance: X→0 with R large.

Setup
-----
    VNA Port 1 ──BNC / SMA──→ DUT (antenna, network, etc.)

1-port SOLT calibration over the same sweep range first. Without
calibration, the connector reflection contaminates the entire trace.
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
import matplotlib.ticker as mticker
import numpy as np


DEFAULT_VNA      = "nanovna"
DEFAULT_PORT     = "/dev/ttyACM1"
DEFAULT_HP_HOST  = "10.1.1.70"
DEFAULT_POINTS   = 401
Z0               = 50.0

SMITH_R_CIRCLES = [0.0, 0.2, 0.5, 1.0, 2.0, 5.0, 10.0]
SMITH_X_ARCS    = [0.2, 0.5, 1.0, 2.0, 5.0]


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


def measure_s11(vna, start_hz, stop_hz, points, averaging):
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


def gamma_to_impedance(gamma: np.ndarray) -> np.ndarray:
    """Z = Z0 · (1 + Γ) / (1 - Γ). Clamps Γ near ±1 to avoid /0."""
    g = gamma.copy()
    near_one = np.abs(1.0 - g) < 1e-9
    g[near_one] = 1.0 - 1e-9 + 0j
    return Z0 * (1.0 + g) / (1.0 - g)


def find_x_zero_crossings(freqs_hz: np.ndarray, r: np.ndarray,
                          x: np.ndarray) -> list[dict]:
    """
    Locate every X = 0 crossing (interpolated between samples) and report
    the corresponding R there. Returns a list of dicts sorted by frequency.
    """
    out = []
    for i in range(len(x) - 1):
        if x[i] == 0.0:
            kind = ("series" if abs(r[i]) <= Z0 * 5 else "parallel")
            out.append(dict(f_hz=float(freqs_hz[i]),
                            r_ohm=float(r[i]),
                            kind=kind))
        elif x[i] * x[i + 1] < 0.0:
            t = -x[i] / (x[i + 1] - x[i])
            f_cross = float(freqs_hz[i] + t * (freqs_hz[i + 1] - freqs_hz[i]))
            r_cross = float(r[i] + t * (r[i + 1] - r[i]))
            kind = ("series" if abs(r_cross) <= Z0 * 5 else "parallel")
            out.append(dict(f_hz=f_cross, r_ohm=r_cross, kind=kind))
    return out


# ---------------------------------------------------------------------------
# Smith chart helper (lifted from smith-pdf and trimmed)
# ---------------------------------------------------------------------------

def draw_smith_grid(ax) -> None:
    theta = np.linspace(0, 2 * np.pi, 721)
    ax.plot(np.cos(theta), np.sin(theta), "k-", linewidth=1.0, zorder=2)
    grid = dict(linewidth=0.5, color="#bbbbbb", zorder=1)

    for r in SMITH_R_CIRCLES:
        cx  = r / (r + 1.0)
        rad = 1.0 / (r + 1.0)
        t   = np.linspace(0, 2 * np.pi, 721)
        gx  = cx + rad * np.cos(t)
        gy  = rad * np.sin(t)
        inside = gx ** 2 + gy ** 2 <= 1.0 + 1e-6
        ax.plot(gx[inside], gy[inside], **grid)
    for sign in (1.0, -1.0):
        for xv in SMITH_X_ARCS:
            xs = sign * xv
            cy  = 1.0 / xs
            rad = abs(cy)
            t   = np.linspace(0, 2 * np.pi, 1441)
            gx  = 1.0 + rad * np.cos(t)
            gy  = cy  + rad * np.sin(t)
            inside = gx ** 2 + gy ** 2 <= 1.0 + 1e-6
            ax.plot(gx[inside], gy[inside], **grid)
    ax.axhline(0, color="#bbbbbb", linewidth=0.5, zorder=1)
    ax.plot(0,  0, "k+", markersize=6, zorder=4)
    ax.plot(-1, 0, "ks", markersize=3, zorder=4)
    ax.plot(1,  0, "ks", markersize=3, zorder=4)
    ax.set_xlim(-1.10, 1.10)
    ax.set_ylim(-1.10, 1.10)
    ax.set_aspect("equal")
    ax.axis("off")


# ---------------------------------------------------------------------------
# Plot
# ---------------------------------------------------------------------------

def plot_pdf(freqs_hz, gamma, label, driver_name, idn, output_path,
             resonances=None, smith_panel=True):
    freqs_mhz = freqs_hz / 1e6
    z         = gamma_to_impedance(gamma)
    r, x      = z.real, z.imag
    mag_z     = np.abs(z)
    phase_z   = np.degrees(np.arctan2(x, r))
    mag_g     = np.clip(np.abs(gamma), 0.0, 1.0 - 1e-6)
    vswr      = (1.0 + mag_g) / (1.0 - mag_g)
    rl_db     = -20.0 * np.log10(np.clip(mag_g, 1e-12, None))
    ts        = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    # Layout: top row spans R/X + |Z|; bottom row VSWR + Smith (if enabled)
    if smith_panel:
        fig = plt.figure(figsize=(13, 11))
        gs = fig.add_gridspec(3, 2, height_ratios=[1, 1, 1.4],
                              hspace=0.32, wspace=0.20)
        ax_rx     = fig.add_subplot(gs[0, :])
        ax_zphase = fig.add_subplot(gs[1, :], sharex=ax_rx)
        ax_vswr   = fig.add_subplot(gs[2, 0])
        ax_smith  = fig.add_subplot(gs[2, 1])
    else:
        fig, (ax_rx, ax_zphase, ax_vswr) = plt.subplots(
            3, 1, figsize=(11, 11), sharex=True)
        ax_smith = None

    # ── Panel 1: R + X ───────────────────────────────────────────────────
    ax_rx.plot(freqs_mhz, r, color="#d62728", linewidth=1.3,
               label="R (resistance)")
    ax_rx.plot(freqs_mhz, x, color="#2ca02c", linewidth=1.3,
               label="X (reactance: +ind / -cap)")
    ax_rx.axhline(0, color="#888888", linewidth=0.6)
    ax_rx.axhline(50, color="#1f77b4", linewidth=0.6, linestyle=":")
    ax_rx.set_ylabel("R, X (Ω)")
    ax_rx.grid(True, which="both", alpha=0.35)
    ax_rx.legend(loc="upper right", fontsize=8, framealpha=0.92)

    title_lines = [
        f"Impedance — {label}",
        f"{freqs_mhz[0]:.4f} – {freqs_mhz[-1]:.4f} MHz  •  "
        f"{len(freqs_hz)} points  •  {driver_name}  •  {ts}",
    ]
    if idn:
        title_lines.append(idn[:120])
    ax_rx.set_title("\n".join(title_lines), fontsize=10)

    if resonances:
        for res in resonances:
            ax_rx.axvline(res["f_hz"] / 1e6, color="#9467bd", linestyle="--",
                          linewidth=0.7, alpha=0.7)

    # ── Panel 2: |Z| + ∠Z ────────────────────────────────────────────────
    ax_zphase.semilogy(freqs_mhz, mag_z, color="#1f77b4", linewidth=1.3,
                       label="|Z|")
    ax_zphase.set_ylabel("|Z| (Ω, log)")
    ax_zphase.grid(True, which="both", alpha=0.35)
    ax_zphase.legend(loc="upper left", fontsize=8, framealpha=0.92)
    ax_zphase_r = ax_zphase.twinx()
    ax_zphase_r.plot(freqs_mhz, phase_z, color="#ff7f0e", linewidth=1.1,
                     alpha=0.85, label="∠Z")
    ax_zphase_r.set_ylabel("∠Z (°)")
    ax_zphase_r.set_ylim(-95, 95)
    ax_zphase_r.legend(loc="upper right", fontsize=8, framealpha=0.92)

    # ── Panel 3: VSWR + RL (twin axis) ───────────────────────────────────
    ax_vswr.plot(freqs_mhz, np.minimum(vswr, 10), color="#1f77b4",
                 linewidth=1.3, label="VSWR")
    for v, color in ((1.5, "green"), (2.0, "orange"), (3.0, "red")):
        ax_vswr.axhline(v, color=color, linestyle="--", linewidth=0.8,
                        alpha=0.75)
    ax_vswr.set_xlabel("Frequency (MHz)")
    ax_vswr.set_ylabel("VSWR")
    ax_vswr.set_ylim(1.0, 10.0)
    ax_vswr.yaxis.set_major_locator(mticker.MultipleLocator(1.0))
    ax_vswr.grid(True, which="both", alpha=0.35)
    ax_vswr.legend(loc="upper right", fontsize=8, framealpha=0.92)

    # Best-VSWR annotation
    i_min = int(np.argmin(vswr))
    ax_vswr.plot(freqs_mhz[i_min], min(vswr[i_min], 10), "o",
                 color="purple", markersize=5, zorder=5)
    ax_vswr.annotate(
        f"min VSWR {vswr[i_min]:.2f}:1  (RL {rl_db[i_min]:.1f} dB)\n"
        f"@ {freqs_mhz[i_min]:.4f} MHz",
        xy=(freqs_mhz[i_min], min(vswr[i_min], 10)),
        xytext=(10, 10), textcoords="offset points",
        fontsize=8, color="purple",
        arrowprops=dict(arrowstyle="->", color="purple", lw=0.7),
    )

    # ── Smith chart ──────────────────────────────────────────────────────
    if ax_smith is not None:
        draw_smith_grid(ax_smith)
        n = len(gamma)
        colors = plt.cm.jet(np.linspace(0, 1, n))
        gx = gamma.real
        gy = gamma.imag
        for i in range(n - 1):
            ax_smith.plot(
                [gx[i], gx[i + 1]], [gy[i], gy[i + 1]],
                color=colors[i], linewidth=1.4, zorder=5,
            )
        ax_smith.plot(gx[0], gy[0], "o", color=colors[0], markersize=6,
                      markeredgecolor="k", zorder=6)
        ax_smith.plot(gx[-1], gy[-1], "o", color=colors[-1], markersize=6,
                      markeredgecolor="k", zorder=6)
        ax_smith.annotate(f"{freqs_mhz[0]:.3f} MHz",
                          xy=(gx[0], gy[0]),
                          xytext=(6, 6), textcoords="offset points",
                          fontsize=7, color="#202020")
        ax_smith.annotate(f"{freqs_mhz[-1]:.3f} MHz",
                          xy=(gx[-1], gy[-1]),
                          xytext=(6, -10), textcoords="offset points",
                          fontsize=7, color="#202020")
        ax_smith.set_title("Smith — Γ locus, blue → red", fontsize=9)

    fig.savefig(output_path, format="pdf", bbox_inches="tight")
    plt.close(fig)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> int:
    p = argparse.ArgumentParser(
        description="S11 → R + jX, |Z|, VSWR, Smith — multi-panel PDF.",
    )
    p.add_argument("--vna",   choices=("nanovna", "hp"), default=DEFAULT_VNA)
    p.add_argument("--port",  default=DEFAULT_PORT)
    p.add_argument("--host",  default=DEFAULT_HP_HOST)
    p.add_argument("--start", type=float, required=True, metavar="MHZ")
    p.add_argument("--stop",  type=float, required=True, metavar="MHZ")
    p.add_argument("--points", type=int, default=DEFAULT_POINTS, metavar="N")
    p.add_argument("--average", type=int, default=2, metavar="N")
    p.add_argument("--power", type=float, default=None, metavar="DBM")
    p.add_argument("--resonances", action="store_true",
                   help="Locate X = 0 crossings (series / parallel resonances)")
    p.add_argument("--no-smith", action="store_true",
                   help="Drop the Smith-chart panel (default: include)")
    p.add_argument("--label", default="DUT")
    p.add_argument("--output", required=True, metavar="FILE.pdf")
    args = p.parse_args()

    if args.start <= 0 or args.stop <= 0 or args.stop <= args.start:
        print("Error: --start and --stop must be positive with stop > start")
        return 1
    if args.points < 2 or args.average < 1:
        print("Error: --points must be ≥ 2 and --average must be ≥ 1")
        return 1

    print(f"Impedance PDF — {args.label}")
    print(f"  Driver       : {args.vna}")
    print(f"  Sweep        : {args.start:.4f} – {args.stop:.4f} MHz, "
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
        z   = gamma_to_impedance(gamma)
        mag_g = np.clip(np.abs(gamma), 0.0, 1.0 - 1e-6)
        vswr = (1.0 + mag_g) / (1.0 - mag_g)

        i_min = int(np.argmin(vswr))
        print(f"  Best VSWR    : {vswr[i_min]:.2f}:1 @ "
              f"{freqs_hz[i_min]/1e6:.4f} MHz")
        print(f"  At best:     R = {z[i_min].real:6.1f} Ω, "
              f"X = {z[i_min].imag:+6.1f} Ω, "
              f"|Z| = {abs(z[i_min]):6.1f} Ω")

        resonances = None
        if args.resonances:
            resonances = find_x_zero_crossings(freqs_hz, z.real, z.imag)
            if resonances:
                print()
                print(f"  Found {len(resonances)} X=0 crossing(s):")
                print(f"    {'#':>2}  {'f (MHz)':>11}  {'R (Ω)':>8}  kind")
                for k, res in enumerate(resonances, 1):
                    print(f"    {k:>2}  {res['f_hz']/1e6:>11.4f}  "
                          f"{res['r_ohm']:>8.1f}  {res['kind']}")
            else:
                print("  No X = 0 crossings inside the sweep.")

        plot_pdf(
            freqs_hz, gamma,
            label=args.label,
            driver_name=args.vna.upper(),
            idn=idn,
            output_path=args.output,
            resonances=resonances,
            smith_panel=not args.no_smith,
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
