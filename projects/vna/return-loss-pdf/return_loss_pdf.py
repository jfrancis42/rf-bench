#!/usr/bin/env python3
"""
return_loss_pdf.py — S11 → return-loss PDF chart, NanoVNA or HP 8712B.

Companion to swr_pdf.py. The two scripts measure the same thing — S11 —
but plot it in different units:

  - swr_pdf : VSWR (linear, lower-bounded at 1.0). Bad for sub-2:1
              detail because the entire well-matched band sits between
              1 and 2.
  - return_loss_pdf : Return loss in dB (logarithmic). Same data;
                      VSWR 1.5:1 ≈ 14 dB, 1.2:1 ≈ 21 dB, 1.05:1 ≈ 32 dB.
                      Far more sensitive when fine-tuning a match.

Math
----
  Γ        = S11                                (complex)
  RL(f)    = -20·log10(|Γ|)                     dB  (positive number)
  VSWR(f)  = (1 + |Γ|) / (1 - |Γ|)              for the labelled axis

Plot
----
Single panel, return loss in dB on Y (higher is better, like a tunnel),
with a secondary axis labelled in equivalent VSWR.
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
DEFAULT_PORT     = "/dev/ttyACM1"
DEFAULT_HP_HOST  = "10.1.1.70"
DEFAULT_POINTS   = 401

# VSWR → RL dB equivalents to mark as reference lines.
RL_REFS = [
    ( 9.5, "red",    "VSWR 2.0:1"),
    (14.0, "orange", "VSWR 1.5:1"),
    (20.0, "green",  "VSWR 1.22:1"),
    (26.0, "blue",   "VSWR 1.10:1"),
]

# Amateur radio bands (MHz, MHz, label) used for shading on the plot.
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


def vswr_from_rl(rl_db: float) -> float:
    """Convert return loss (dB, positive) to VSWR."""
    gamma = 10.0 ** (-rl_db / 20.0)
    return (1.0 + gamma) / (1.0 - gamma)


def plot_pdf(freqs_hz, gamma, label, driver_name, idn, output_path,
             ymax_db: float = 40.0):
    freqs_mhz = freqs_hz / 1e6
    sweep_lo = float(freqs_mhz[0])
    sweep_hi = float(freqs_mhz[-1])
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    mag = np.clip(np.abs(gamma), 1e-6, 1.0 - 1e-6)
    rl_db = -20.0 * np.log10(mag)

    fig, ax = plt.subplots(figsize=(11, 7.5))

    band_legend_done = False
    for lo_mhz, hi_mhz, bname in AMATEUR_BANDS_MHZ:
        if hi_mhz < sweep_lo or lo_mhz > sweep_hi:
            continue
        lo = max(lo_mhz, sweep_lo)
        hi = min(hi_mhz, sweep_hi)
        ax.axvspan(
            lo, hi, color="#1f77b4", alpha=0.10,
            label="Amateur band" if not band_legend_done else None, zorder=0,
        )
        band_legend_done = True
        ax.text(
            (lo + hi) / 2.0, 0.97, bname,
            transform=ax.get_xaxis_transform(),
            ha="center", va="top", fontsize=8, color="#1f5fa6", alpha=0.7,
        )

    rl_clipped = np.minimum(rl_db, ymax_db)
    ax.plot(freqs_mhz, rl_clipped, color="#1f77b4", linewidth=1.4,
            label="Return loss")

    for db_val, color, name in RL_REFS:
        if db_val > ymax_db:
            continue
        ax.axhline(db_val, color=color, linestyle="--", linewidth=0.9,
                   alpha=0.75, label=name)

    # Best (deepest) return loss
    i_max = int(np.argmax(rl_db))
    best_rl = float(rl_db[i_max])
    best_mhz = float(freqs_mhz[i_max])
    best_vswr = vswr_from_rl(best_rl)
    marker_y = min(best_rl, ymax_db)
    ax.plot(best_mhz, marker_y, "o", color="purple", markersize=6, zorder=5)
    ax.annotate(
        f"best RL {best_rl:.1f} dB  (VSWR {best_vswr:.2f}:1)\n@ {best_mhz:.3f} MHz",
        xy=(best_mhz, marker_y),
        xytext=(10, -22), textcoords="offset points",
        fontsize=9, color="purple",
        arrowprops=dict(arrowstyle="->", color="purple", lw=0.8),
    )

    ax.set_xlim(sweep_lo, sweep_hi)
    ax.set_ylim(0.0, ymax_db)
    ax.yaxis.set_major_locator(mticker.MultipleLocator(5.0))
    ax.yaxis.set_minor_locator(mticker.MultipleLocator(1.0))
    ax.set_xlabel("Frequency (MHz)")
    ax.set_ylabel("Return loss (dB) — higher is better")
    ax.grid(True, which="both", alpha=0.35)
    ax.legend(loc="lower right", fontsize=8, framealpha=0.92)

    # Secondary axis: equivalent VSWR
    def rl_to_vswr_array(rl_arr):
        rl_arr = np.asarray(rl_arr, dtype=float)
        g = 10.0 ** (-rl_arr / 20.0)
        g = np.clip(g, 0.0, 1.0 - 1e-9)
        return (1.0 + g) / (1.0 - g)

    def vswr_to_rl_array(vswr_arr):
        vswr_arr = np.asarray(vswr_arr, dtype=float)
        vswr_arr = np.clip(vswr_arr, 1.0 + 1e-9, None)
        g = (vswr_arr - 1.0) / (vswr_arr + 1.0)
        return -20.0 * np.log10(g)

    sec = ax.secondary_yaxis("right", functions=(rl_to_vswr_array, vswr_to_rl_array))
    sec.set_ylabel("Equivalent VSWR")
    # Useful VSWR-axis ticks: 1.05, 1.1, 1.2, 1.5, 2, 3, 5
    vswr_ticks = [1.05, 1.1, 1.2, 1.5, 2.0, 3.0]
    sec.set_yticks(vswr_ticks)
    sec.yaxis.set_major_formatter(mticker.FuncFormatter(lambda v, _: f"{v:.2f}:1"))

    title_lines = [
        f"Return Loss — {label}",
        f"{sweep_lo:.3f} – {sweep_hi:.3f} MHz  •  {len(freqs_hz)} points  •  "
        f"{driver_name}  •  {ts}",
    ]
    if idn:
        title_lines.append(idn[:120])
    ax.set_title("\n".join(title_lines), fontsize=10)

    fig.tight_layout()
    fig.savefig(output_path, format="pdf")
    plt.close(fig)


def main() -> int:
    p = argparse.ArgumentParser(
        description="S11 → return-loss (dB) PDF for the DUT on VNA port 1.",
    )
    p.add_argument("--vna",   choices=("nanovna", "hp"), default=DEFAULT_VNA)
    p.add_argument("--port",  default=DEFAULT_PORT)
    p.add_argument("--host",  default=DEFAULT_HP_HOST)
    p.add_argument("--start", type=float, required=True, metavar="MHZ")
    p.add_argument("--stop",  type=float, required=True, metavar="MHZ")
    p.add_argument("--points", type=int, default=DEFAULT_POINTS, metavar="N")
    p.add_argument("--average", type=int, default=1, metavar="N")
    p.add_argument("--power", type=float, default=None, metavar="DBM")
    p.add_argument("--ymax", type=float, default=40.0, metavar="DB",
                   help="Y-axis top in dB (default 40)")
    p.add_argument("--label", default="antenna")
    p.add_argument("--output", required=True, metavar="FILE.pdf")
    args = p.parse_args()

    if args.start <= 0 or args.stop <= 0 or args.stop <= args.start:
        print("Error: --start and --stop must be positive with stop > start (MHz)")
        return 1
    if args.points < 2 or args.average < 1:
        print("Error: --points must be ≥ 2 and --average must be ≥ 1")
        return 1

    print(f"Return-loss PDF — {args.label}")
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
        mag = np.clip(np.abs(gamma), 1e-6, 1.0 - 1e-6)
        rl_db = -20.0 * np.log10(mag)
        i = int(np.argmax(rl_db))
        print(f"  best RL      : {rl_db[i]:.1f} dB @ {freqs_hz[i]/1e6:.3f} MHz  "
              f"(VSWR {vswr_from_rl(rl_db[i]):.2f}:1)")

        plot_pdf(
            freqs_hz, gamma,
            label=args.label,
            driver_name=args.vna.upper(),
            idn=idn,
            output_path=args.output,
            ymax_db=args.ymax,
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
