#!/usr/bin/env python3
"""
swr_pdf.py — S11 → VSWR-vs-frequency PDF chart, NanoVNA or HP 8712B.

Connect the antenna under test to VNA port 1. The script does an S11 sweep
across the requested frequency range, derives VSWR from the reflection
coefficient, and writes a single-page PDF chart.

Driver selection
----------------
Both drivers expose the same core method set (see
``rf-bench/README`` "VNA API compatibility"). The default is the
NanoVNA on ``/dev/ttyACM1``; ``--vna hp`` selects the HP 8712B over
KISS-488 instead.

Math
----
  Γ        = S11                                (complex)
  VSWR(f)  = (1 + |Γ|) / (1 − |Γ|)              clamped at 999
  RL(f)    = −20·log10(|Γ|)  dB                 (returned in stats only)

Plot
----
Single-page PDF, one panel:
  - VSWR vs frequency (semilog Y)
  - Reference lines at 1.5:1, 2:1, 3:1
  - Best-VSWR marker
  - Amateur band shading if the sweep covers any of 160 m – 70 cm
  - Title with --label, timestamp, sweep parameters, driver+IDN

Examples
--------
  python swr_pdf.py --start 144 --stop 148  --label "2m HT antenna"   --output 2m.pdf
  python swr_pdf.py --start 430 --stop 450  --label "70cm HT antenna" --output 70cm.pdf
  python swr_pdf.py --start 3   --stop 30   --label "HF antenna"      --output hf.pdf
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime
from typing import Optional

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.ticker as mticker
import numpy as np


DEFAULT_VNA      = "nanovna"
DEFAULT_PORT     = "/dev/ttyACM1"     # NanoVNA-F as enumerated on greybox
DEFAULT_HP_HOST  = "10.1.1.70"        # KISS-488 default
DEFAULT_POINTS   = 401
Z0               = 50.0

VSWR_REFS = [
    (1.5, "green",  "1.5:1"),
    (2.0, "orange", "2.0:1"),
    (3.0, "red",    "3.0:1"),
]

# Amateur radio bands (MHz, MHz, label) used for shading on the plot.
# These are US ITU Region 2 allocations; close enough for visualization
# in IARU R1/R3 too.
AMATEUR_BANDS_MHZ = [
    (1.800,   2.000,   "160m"),
    (3.500,   4.000,   "80m"),
    (5.330,   5.405,   "60m"),
    (7.000,   7.300,   "40m"),
    (10.100, 10.150,   "30m"),
    (14.000, 14.350,   "20m"),
    (18.068, 18.168,   "17m"),
    (21.000, 21.450,   "15m"),
    (24.890, 24.990,   "12m"),
    (28.000, 29.700,   "10m"),
    (50.000, 54.000,   "6m"),
    (144.000, 148.000, "2m"),
    (222.000, 225.000, "1.25m"),
    (420.000, 450.000, "70cm"),
]


# ---------------------------------------------------------------------------
# VNA construction
# ---------------------------------------------------------------------------

def open_vna(args):
    """Return a connected VNA instance (NanoVNA or HP8712B) and its IDN."""
    if args.vna == "nanovna":
        from rf_bench.nanovna import NanoVNA
        vna = NanoVNA(port=args.port)
        idn = vna.identify()
    elif args.vna == "hp":
        from rf_bench.hp import HP8712B
        vna = HP8712B(host=args.host)
        idn = vna.identify()
    else:
        raise ValueError(f"--vna must be 'nanovna' or 'hp', got {args.vna!r}")
    return vna, idn


def maybe_set_power(vna, dbm: Optional[float], vna_kind: str) -> None:
    """Apply --power if the active driver supports it; warn otherwise."""
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

def measure_vswr(vna, start_hz: float, stop_hz: float, points: int,
                 averaging: int) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """
    Return (freqs_hz, gamma, vswr).

    Uses the swappable VNA API: setup_sweep, set_parameter('S11'),
    single_sweep, get_frequencies, get_s_data or average_s_data.
    """
    vna.setup_sweep(start_hz, stop_hz, points)
    vna.set_parameter("S11")
    ok = vna.single_sweep()
    if not ok:
        print("  WARNING: single_sweep() returned False — trace may be stale")

    freqs = vna.get_frequencies()
    if averaging > 1:
        gamma = vna.average_s_data(averaging)
    else:
        gamma = vna.get_s_data()

    if len(freqs) != len(gamma):
        raise RuntimeError(
            f"VNA returned mismatched array lengths "
            f"(freqs={len(freqs)}, gamma={len(gamma)})"
        )

    mag = np.clip(np.abs(gamma), 0.0, 1.0 - 1e-6)
    vswr = (1.0 + mag) / (1.0 - mag)
    return freqs, gamma, vswr


# ---------------------------------------------------------------------------
# Plot
# ---------------------------------------------------------------------------

def plot_pdf(freqs_hz: np.ndarray, vswr: np.ndarray,
             label: str, driver_name: str, idn: str,
             output_path: str) -> None:
    freqs_mhz = freqs_hz / 1e6
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    fig, ax = plt.subplots(figsize=(11, 7.5))

    # --- Amateur band shading (under the trace) ----------------------------
    sweep_lo = float(freqs_mhz[0])
    sweep_hi = float(freqs_mhz[-1])
    band_legend_done = False
    for lo_mhz, hi_mhz, bname in AMATEUR_BANDS_MHZ:
        if hi_mhz < sweep_lo or lo_mhz > sweep_hi:
            continue
        lo = max(lo_mhz, sweep_lo)
        hi = min(hi_mhz, sweep_hi)
        ax.axvspan(
            lo, hi,
            color="#1f77b4", alpha=0.10,
            label="Amateur band" if not band_legend_done else None,
            zorder=0,
        )
        band_legend_done = True
        # Label the band centered on its visible portion, near the top
        ax.text(
            (lo + hi) / 2.0,
            0.97, bname,
            transform=ax.get_xaxis_transform(),
            ha="center", va="top",
            fontsize=8, color="#1f5fa6", alpha=0.7,
        )

    # --- Axis top: max(VSWR) + 1, integer-rounded, capped at 10 ----------
    # Hams read VSWR off integer gridlines. Pick the smallest top that
    # frames the trace: ceil(max VSWR) + 1, never more than 10. Floor at 3
    # so a near-perfect antenna doesn't end up on a cramped 1–2 chart.
    max_vswr = float(np.max(vswr))
    ymax = int(min(10, max(3, np.ceil(max_vswr) + 1)))

    # --- Trace -------------------------------------------------------------
    # Clip plotted VSWR to the chart top so a bad antenna doesn't blow the
    # axis and squash the interesting low-VSWR region. The annotation
    # still reports the true minimum.
    vswr_clipped = np.minimum(vswr, ymax)
    ax.plot(freqs_mhz, vswr_clipped, color="#1f77b4", linewidth=1.4, label="VSWR")

    # --- Reference lines (only those that fit in the visible range) ------
    for value, color, name in VSWR_REFS:
        if value > ymax:
            continue
        ax.axhline(
            value, color=color, linestyle="--", linewidth=0.9, alpha=0.75,
            label=name,
        )

    # --- Best VSWR annotation --------------------------------------------
    i_min = int(np.argmin(vswr))
    best_vswr = float(vswr[i_min])
    best_mhz  = float(freqs_mhz[i_min])
    marker_y = min(best_vswr, ymax)
    ax.plot(best_mhz, marker_y, "o", color="purple", markersize=6, zorder=5)
    ax.annotate(
        f"min VSWR {best_vswr:.2f}:1 @ {best_mhz:.3f} MHz",
        xy=(best_mhz, marker_y),
        xytext=(10, 14), textcoords="offset points",
        fontsize=9, color="purple",
        arrowprops=dict(arrowstyle="->", color="purple", lw=0.8),
    )

    # --- Axes / formatting -----------------------------------------------
    ax.set_xlim(sweep_lo, sweep_hi)
    ax.set_ylim(1.0, ymax)
    ax.yaxis.set_major_locator(mticker.MultipleLocator(1.0))
    ax.yaxis.set_minor_locator(mticker.MultipleLocator(0.2))
    ax.yaxis.set_major_formatter(mticker.FuncFormatter(lambda v, _: f"{v:.0f}"))
    ax.set_xlabel("Frequency (MHz)")
    ax.set_ylabel("VSWR")
    ax.grid(True, which="both", alpha=0.35)
    ax.legend(loc="upper right", fontsize=8, framealpha=0.92)

    title_lines = [
        f"Antenna VSWR — {label}",
        f"{sweep_lo:.3f} – {sweep_hi:.3f} MHz  •  {len(freqs_hz)} points  •  "
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
        description="S11 → VSWR PDF chart for an antenna on VNA port 1.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument("--vna",   choices=("nanovna", "hp"), default=DEFAULT_VNA,
                   help=f"Driver (default: {DEFAULT_VNA})")
    p.add_argument("--port",  default=DEFAULT_PORT,
                   help=f"NanoVNA serial device (default: {DEFAULT_PORT})")
    p.add_argument("--host",  default=DEFAULT_HP_HOST,
                   help=f"HP 8712B KISS-488 host (default: {DEFAULT_HP_HOST})")
    p.add_argument("--start", type=float, required=True, metavar="MHZ",
                   help="Start frequency in MHz")
    p.add_argument("--stop",  type=float, required=True, metavar="MHZ",
                   help="Stop frequency in MHz")
    p.add_argument("--points", type=int, default=DEFAULT_POINTS, metavar="N",
                   help=f"Sweep points (default: {DEFAULT_POINTS}; NanoVNA max 401, HP max 801)")
    p.add_argument("--average", type=int, default=1, metavar="N",
                   help="Software-average N sweeps (default: 1)")
    p.add_argument("--power", type=float, default=None, metavar="DBM",
                   help="Stimulus power dBm (HP only; ignored on NanoVNA)")
    p.add_argument("--label", default="antenna",
                   help='Antenna label for the chart title (default: "antenna")')
    p.add_argument("--output", required=True, metavar="FILE.pdf",
                   help="Output PDF path")
    args = p.parse_args()

    if args.start <= 0 or args.stop <= 0 or args.stop <= args.start:
        print("Error: --start and --stop must be positive with stop > start (MHz)")
        return 1
    if args.points < 2:
        print("Error: --points must be ≥ 2")
        return 1
    if args.average < 1:
        print("Error: --average must be ≥ 1")
        return 1

    start_hz = args.start * 1e6
    stop_hz  = args.stop  * 1e6

    print(f"VSWR PDF — {args.label}")
    print(f"  Driver       : {args.vna}")
    print(f"  Sweep        : {args.start:.3f} – {args.stop:.3f} MHz, "
          f"{args.points} points, average={args.average}")
    print(f"  Output       : {args.output}")

    vna = None
    try:
        vna, idn = open_vna(args)
        print(f"  IDN          : {idn[:120]}")
        maybe_set_power(vna, args.power, args.vna)

        freqs_hz, gamma, vswr = measure_vswr(
            vna, start_hz, stop_hz, args.points, args.average,
        )

        i_min = int(np.argmin(vswr))
        best_vswr = float(vswr[i_min])
        best_mhz  = float(freqs_hz[i_min] / 1e6)
        rl_db_best = float(-20.0 * np.log10(max(abs(gamma[i_min]), 1e-12)))
        print(f"  min VSWR     : {best_vswr:.2f}:1 @ {best_mhz:.3f} MHz  "
              f"(RL ≈ {rl_db_best:.1f} dB)")

        plot_pdf(
            freqs_hz, vswr,
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
