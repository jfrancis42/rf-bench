#!/usr/bin/env python3
"""
toroid_sniff.py — Characterise a wound toroid: Al, Q, recommend mix.

Wind N turns through a toroid, connect the leads to the centre pins of
a series-through fixture, sweep S21, and the script derives:

  - Z(f)   = 2·Z0·(1 - S21)/S21              series-through model
  - R(f), X(f) = Re Z, Im Z
  - L_eff(f) = X(f) / (2π·f)                 effective series inductance
  - Q(f)   = X(f) / R(f)                     unloaded Q at frequency
  - Al(N)   = L_dc / N²                       µH/N² at the lowest sweep
                                              frequency (closest to DC,
                                              least core loss)

It also prints which Amidon / Fair-Rite mix the measured Q peak is
*consistent with*, based on the published Q-vs-frequency sweet spots:

  - Mix 61 (NiZn)  : optimum ~10–50 MHz
  - Mix 43 (NiZn)  : optimum ~1–30 MHz  (most-used HF balun mix)
  - Mix 31 (NiZn)  : optimum ~0.5–10 MHz (low-band chokes)
  - Mix 77 (MnZn)  : optimum ~10 kHz – 1 MHz
  - Mix 2 (powdered iron, red)    : 1–30 MHz, low loss but lower µ
  - Mix 6 (powdered iron, yellow) : 10–90 MHz

Setup
-----
    VNA Port 1 ── [SMA centre → toroid → SMA centre] ── VNA Port 2
                  (shield common; toroid is the series element)

Calibrate THRU (and ideally OSL on port 1) before measuring.

Caveats
-------
This is a series-through small-signal measurement at near-zero drive.
Real RF transformer / balun cores are characterised at much higher
power and over their hysteresis loop; mix recommendations from this
script are useful for "did I wind the right core" sanity-checks, not
for power-handling specs.
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


MIXES = [
    # (name, optimum_lo_mhz, optimum_hi_mhz, family)
    ("Mix 77",  0.010,   1.0,    "ferrite-MnZn"),
    ("Mix 31",  0.5,    10.0,    "ferrite-NiZn-LF"),
    ("Mix 43",  1.0,    30.0,    "ferrite-NiZn-MF"),
    ("Mix 61", 10.0,    50.0,    "ferrite-NiZn-HF"),
    ("Mix 2",   1.0,    30.0,    "powdered-iron-red"),
    ("Mix 6",  10.0,    90.0,    "powdered-iron-yellow"),
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


def measure_s21(vna, start_hz, stop_hz, points, averaging):
    vna.setup_sweep(start_hz, stop_hz, points)
    vna.set_parameter("S21")
    ok = vna.single_sweep()
    if not ok:
        print("  WARNING: single_sweep() returned False — trace may be stale")
    freqs = vna.get_frequencies()
    s21 = vna.average_s_data(averaging) if averaging > 1 else vna.get_s_data()
    if len(freqs) != len(s21):
        raise RuntimeError(
            f"VNA returned mismatched array lengths "
            f"(freqs={len(freqs)}, s21={len(s21)})"
        )
    return freqs, s21


# ---------------------------------------------------------------------------
# Mix recommendation
# ---------------------------------------------------------------------------

def suggest_mixes(q_peak_freq_mhz: float) -> list[str]:
    """Return names of mixes whose published optimum range contains the Q peak."""
    return [
        f"{name} ({family})"
        for name, lo, hi, family in MIXES
        if lo <= q_peak_freq_mhz <= hi
    ]


# ---------------------------------------------------------------------------
# Plot
# ---------------------------------------------------------------------------

def plot_pdf(freqs_hz, z, n_turns, l_dc_uH, al_nH_per_n2, mix_suggestions,
             label, driver_name, idn, output_path):
    freqs_mhz = freqs_hz / 1e6
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    r = z.real
    x = z.imag
    mag = np.abs(z)
    omega = 2.0 * np.pi * freqs_hz
    # Effective series inductance L(f) = X / ω, only meaningful where X > 0
    l_eff_uH = np.where(x > 0, x / omega * 1e6, np.nan)
    # Q = X/R, only meaningful where R > 0
    q = np.where(r > 0, x / r, np.nan)

    i_qmax = int(np.nanargmax(q))
    q_peak = float(q[i_qmax])
    f_qpeak_mhz = float(freqs_mhz[i_qmax])

    fig, axes = plt.subplots(3, 1, figsize=(11, 11), sharex=True)

    # ── Panel 1: |Z|, R, X ────────────────────────────────────────────
    ax = axes[0]
    ax.plot(freqs_mhz, mag, color="#1f77b4", linewidth=1.4, label="|Z|")
    ax.plot(freqs_mhz, r,   color="#d62728", linewidth=1.0, label="R")
    ax.plot(freqs_mhz, x,   color="#2ca02c", linewidth=1.0, label="X")
    ax.axhline(0, color="#888888", linewidth=0.6)
    ax.set_ylabel("Z (Ω)")
    ax.grid(True, which="both", alpha=0.35)
    ax.legend(loc="upper right", fontsize=8, framealpha=0.92)
    title_lines = [
        f"Toroid Characterisation — {label}  ({n_turns} turns)",
        f"{freqs_mhz[0]:.3f} – {freqs_mhz[-1]:.3f} MHz  •  "
        f"{len(freqs_hz)} points  •  {driver_name}  •  {ts}",
    ]
    if idn:
        title_lines.append(idn[:120])
    ax.set_title("\n".join(title_lines), fontsize=10)

    # ── Panel 2: L_eff ───────────────────────────────────────────────
    ax = axes[1]
    ax.semilogx(freqs_mhz, l_eff_uH, color="#1f77b4", linewidth=1.4,
                label="L_eff (µH)")
    ax.set_ylabel("Effective inductance (µH)")
    ax.grid(True, which="both", alpha=0.35)
    if l_dc_uH is not None:
        ax.axhline(l_dc_uH, color="#888888", linestyle=":", linewidth=1.0,
                   label=f"DC L₀ = {l_dc_uH:.3f} µH")
    ax.legend(loc="upper right", fontsize=8, framealpha=0.92)

    # ── Panel 3: Q ────────────────────────────────────────────────────
    ax = axes[2]
    ax.plot(freqs_mhz, q, color="#9467bd", linewidth=1.4, label="Q = X/R")
    ax.plot(f_qpeak_mhz, q_peak, "o", color="purple", markersize=7, zorder=5)
    ax.annotate(
        f"Q peak {q_peak:.0f} @ {f_qpeak_mhz:.3f} MHz",
        xy=(f_qpeak_mhz, q_peak), xytext=(10, 8), textcoords="offset points",
        fontsize=9, color="purple",
        arrowprops=dict(arrowstyle="->", color="purple", lw=0.8),
    )
    ax.set_xlabel("Frequency (MHz)")
    ax.set_ylabel("Q")
    ax.grid(True, which="both", alpha=0.35)
    ax.legend(loc="upper right", fontsize=8, framealpha=0.92)

    # Text-block summary at the bottom-left of panel 3
    summary = [
        f"Turns         : {n_turns}",
    ]
    if l_dc_uH is not None:
        summary.append(f"L (start of sweep) : {l_dc_uH:.3f} µH")
    if al_nH_per_n2 is not None:
        summary.append(f"Al = L/N²     : {al_nH_per_n2:.1f} nH/N²")
    summary.append(f"Q peak        : {q_peak:.0f} @ {f_qpeak_mhz:.3f} MHz")
    if mix_suggestions:
        summary.append("Mix consistent: " + ", ".join(mix_suggestions))
    else:
        summary.append("Mix consistent: (Q-peak frequency outside common mix ranges)")
    ax.text(
        0.005, 0.005, "\n".join(summary),
        transform=ax.transAxes, fontsize=8, family="monospace",
        va="bottom", ha="left",
        bbox=dict(facecolor="white", edgecolor="#cccccc", alpha=0.9, pad=4),
    )

    fig.tight_layout()
    fig.savefig(output_path, format="pdf")
    plt.close(fig)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> int:
    p = argparse.ArgumentParser(
        description="Series-through toroid characterisation: L, Q, mix.",
    )
    p.add_argument("--vna",   choices=("nanovna", "hp"), default=DEFAULT_VNA)
    p.add_argument("--port",  default=DEFAULT_PORT)
    p.add_argument("--host",  default=DEFAULT_HP_HOST)
    p.add_argument("--start", type=float, required=True, metavar="MHZ")
    p.add_argument("--stop",  type=float, required=True, metavar="MHZ")
    p.add_argument("--points", type=int, default=DEFAULT_POINTS, metavar="N")
    p.add_argument("--average", type=int, default=4, metavar="N")
    p.add_argument("--power", type=float, default=None, metavar="DBM")
    p.add_argument("--turns", type=int, required=True, metavar="N",
                   help="Number of turns wound on the toroid")
    p.add_argument("--label", default="toroid")
    p.add_argument("--output", required=True, metavar="FILE.pdf")
    args = p.parse_args()

    if args.start <= 0 or args.stop <= 0 or args.stop <= args.start:
        print("Error: --start and --stop must be positive with stop > start (MHz)")
        return 1
    if args.points < 2 or args.average < 1:
        print("Error: --points must be ≥ 2 and --average must be ≥ 1")
        return 1
    if args.turns < 1:
        print("Error: --turns must be ≥ 1")
        return 1

    print(f"Toroid Sniff — {args.label}")
    print(f"  Driver       : {args.vna}")
    print(f"  Turns        : {args.turns}")
    print(f"  Sweep        : {args.start:.3f} – {args.stop:.3f} MHz, "
          f"{args.points} points, average={args.average}")
    print(f"  Output       : {args.output}")

    vna = None
    try:
        vna, idn = open_vna(args)
        print(f"  IDN          : {idn[:120]}")
        maybe_set_power(vna, args.power, args.vna)

        freqs_hz, s21 = measure_s21(
            vna, args.start * 1e6, args.stop * 1e6,
            args.points, args.average,
        )
        s21_safe = np.where(np.abs(s21) < 1e-9, 1e-9 + 0j, s21)
        z = 2.0 * Z0 * (1.0 - s21_safe) / s21_safe

        # Compute L at the lowest sweep frequency (closest to DC; least loss)
        omega0 = 2.0 * np.pi * float(freqs_hz[0])
        x0 = float(z[0].imag)
        if x0 > 0:
            l_dc_uH = (x0 / omega0) * 1e6
            al_nH_per_n2 = (l_dc_uH * 1000.0) / (args.turns ** 2)
        else:
            l_dc_uH = None
            al_nH_per_n2 = None

        r = z.real
        x = z.imag
        q = np.where(r > 0, x / r, np.nan)
        with np.errstate(invalid="ignore"):
            i_qmax = int(np.nanargmax(q))
        q_peak = float(q[i_qmax])
        f_qpeak_mhz = float(freqs_hz[i_qmax]) / 1e6

        mix_suggestions = suggest_mixes(f_qpeak_mhz)

        print(f"  L at f_start : "
              f"{l_dc_uH:.3f} µH" if l_dc_uH is not None
              else "  L at f_start : reactance is non-positive, can't estimate")
        if al_nH_per_n2 is not None:
            print(f"  Al           : {al_nH_per_n2:.1f} nH/N²")
        print(f"  Q peak       : {q_peak:.0f} @ {f_qpeak_mhz:.3f} MHz")
        if mix_suggestions:
            print(f"  Mix(es) consistent with Q peak: " + ", ".join(mix_suggestions))
        else:
            print("  Mix(es) consistent with Q peak: none in common library "
                  "(Q peak outside 0.01–90 MHz)")

        plot_pdf(
            freqs_hz, z, args.turns, l_dc_uH, al_nH_per_n2, mix_suggestions,
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
