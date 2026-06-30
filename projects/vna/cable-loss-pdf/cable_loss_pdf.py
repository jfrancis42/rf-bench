#!/usr/bin/env python3
"""
cable_loss_pdf.py — S21 → cable-loss PDF chart, NanoVNA or HP 8712B.

Measure the insertion loss of a coaxial feedline as a function of
frequency by connecting it port-to-port as a THRU. Plots:

  - Total loss (dB) vs frequency
  - Loss per 100 ft (or per 100 m), if --length is given
  - Optional comparison curve against a published cable type
    (e.g. RG-58, LMR-400) for the same length

Setup
-----
    VNA Port 1 ── coax under test ── VNA Port 2  (S21 THRU)

Calibrate THRU across the same sweep range first. Without
calibration the trace includes port-to-port reference loss.

Math
----
    Total loss(f) = -20·log10(|S21(f)|)        dB
    Loss/100 ft   = Total loss · 100 / length_ft
    Loss/100 m    = Total loss · 100 / length_m
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


# Manufacturer-published matched loss for common coax types, in dB/100 ft at
# a list of (frequency MHz, loss dB/100ft) breakpoints. Curves are
# log-linearly interpolated against sqrt(frequency) — the standard model
# below the cable's cutoff. Sources are the manufacturer data sheets.
CABLE_LIBRARY: dict[str, list[tuple[float, float]]] = {
    "RG-58":   [(10, 1.6), (50, 3.8),  (100, 5.4),  (200, 7.8),  (400, 11.5),
                (700, 16.0), (900, 18.5)],
    "RG-8X":   [(10, 1.0), (50, 2.5),  (100, 3.8),  (200, 5.5),  (400, 8.0),
                (700, 11.0), (900, 13.0)],
    "RG-213":  [(10, 0.6), (50, 1.4),  (100, 2.0),  (200, 2.9),  (400, 4.3),
                (700, 5.9), (900, 6.9)],
    "LMR-240": [(10, 0.7), (50, 1.6),  (100, 2.3),  (200, 3.3),  (400, 4.8),
                (900, 7.3), (1500, 9.6), (2000, 11.2)],
    "LMR-400": [(10, 0.4), (50, 0.9),  (100, 1.3),  (200, 1.8),  (400, 2.7),
                (900, 4.1), (1500, 5.4), (2000, 6.3)],
    "LMR-600": [(10, 0.24), (50, 0.55), (100, 0.79), (200, 1.13), (400, 1.62),
                (900, 2.50), (1500, 3.30), (2000, 3.87)],
    "9913":    [(10, 0.42), (50, 0.95), (100, 1.32), (200, 1.85), (400, 2.65),
                (900, 4.10), (1500, 5.45)],
    "Heliax-1/2": [(10, 0.16), (100, 0.50), (450, 1.10), (900, 1.60),
                   (1500, 2.10), (2000, 2.50)],
}

DEFAULT_TARGET_DB_PER_100FT = None   # no target line unless --target given


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

def measure_s21_loss(vna, start_hz: float, stop_hz: float,
                     points: int, averaging: int) -> tuple[np.ndarray, np.ndarray]:
    """Return (freqs_hz, loss_db). loss_db is positive for lossy DUT."""
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
    loss_db = -20.0 * np.log10(np.clip(np.abs(s21), 1e-12, None))
    return freqs, loss_db


# ---------------------------------------------------------------------------
# Cable library helper
# ---------------------------------------------------------------------------

def estimate_cable_loss(cable_name: str, freqs_hz: np.ndarray) -> np.ndarray:
    """Linearly interpolate published loss-per-100ft against sqrt(MHz)."""
    if cable_name not in CABLE_LIBRARY:
        raise ValueError(
            f"Unknown cable {cable_name!r}. "
            f"Known: {', '.join(sorted(CABLE_LIBRARY))}"
        )
    table = CABLE_LIBRARY[cable_name]
    f_mhz = np.array([row[0] for row in table], dtype=np.float64)
    db    = np.array([row[1] for row in table], dtype=np.float64)
    fq_mhz = freqs_hz / 1e6
    # loss ∝ sqrt(f) (skin effect) for matched-line coax below cutoff
    return np.interp(np.sqrt(fq_mhz), np.sqrt(f_mhz), db,
                     left=db[0], right=db[-1])


# ---------------------------------------------------------------------------
# Plot
# ---------------------------------------------------------------------------

def plot_pdf(freqs_hz: np.ndarray, loss_db: np.ndarray,
             length_ft: Optional[float], length_m: Optional[float],
             compare_cable: Optional[str],
             target_db_per_100ft: Optional[float],
             label: str, driver_name: str, idn: str,
             output_path: str) -> None:
    freqs_mhz = freqs_hz / 1e6
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    have_norm = length_ft is not None or length_m is not None
    n_panels = 2 if have_norm else 1
    fig, axes = plt.subplots(n_panels, 1, figsize=(11, 4.5 * n_panels),
                             sharex=True)
    if n_panels == 1:
        axes = [axes]

    # ── Panel 1: total loss ──────────────────────────────────────────────
    ax0 = axes[0]
    ax0.plot(freqs_mhz, loss_db, color="#1f77b4", linewidth=1.4,
             label="Measured total loss")

    i_lo, i_hi = 0, len(freqs_mhz) - 1
    ax0.plot(freqs_mhz[i_lo], loss_db[i_lo], "o", color="#1f77b4", markersize=5)
    ax0.plot(freqs_mhz[i_hi], loss_db[i_hi], "o", color="#1f77b4", markersize=5)
    ax0.annotate(
        f"{loss_db[i_lo]:.2f} dB @ {freqs_mhz[i_lo]:.3f} MHz",
        xy=(freqs_mhz[i_lo], loss_db[i_lo]),
        xytext=(8, 8), textcoords="offset points",
        fontsize=8, color="#1f5fa6",
    )
    ax0.annotate(
        f"{loss_db[i_hi]:.2f} dB @ {freqs_mhz[i_hi]:.3f} MHz",
        xy=(freqs_mhz[i_hi], loss_db[i_hi]),
        xytext=(-8, 8), textcoords="offset points",
        fontsize=8, color="#1f5fa6", ha="right",
    )

    ax0.set_ylabel("Total loss (dB)")
    ax0.grid(True, which="both", alpha=0.35)
    ax0.legend(loc="upper left", fontsize=8, framealpha=0.92)
    title_lines = [
        f"Coax Cable Loss — {label}",
        f"{freqs_mhz[0]:.3f} – {freqs_mhz[-1]:.3f} MHz  •  {len(freqs_hz)} points  "
        f"•  {driver_name}  •  {ts}",
    ]
    if idn:
        title_lines.append(idn[:120])
    ax0.set_title("\n".join(title_lines), fontsize=10)

    # ── Panel 2: normalised loss per 100 ft / per 100 m ─────────────────
    if have_norm:
        ax1 = axes[1]
        if length_ft is not None:
            scale = 100.0 / float(length_ft)
            unit  = "ft"
        else:
            scale = 100.0 / float(length_m)
            unit  = "m"
        per100 = loss_db * scale
        ax1.plot(freqs_mhz, per100, color="#1f77b4", linewidth=1.4,
                 label=f"Measured  ({length_ft or length_m:g} {unit} run)")

        # Optional published-curve overlay
        if compare_cable:
            est_per_100ft = estimate_cable_loss(compare_cable, freqs_hz)
            est_curve = est_per_100ft if unit == "ft" else est_per_100ft * 3.28084
            ax1.plot(freqs_mhz, est_curve, color="#d62728", linewidth=1.2,
                     linestyle="--", alpha=0.85,
                     label=f"{compare_cable} (mfr. published)")

        # Optional pass/fail target
        if target_db_per_100ft is not None:
            tgt = target_db_per_100ft if unit == "ft" else target_db_per_100ft * 3.28084
            ax1.axhline(tgt, color="#ff7f0e", linestyle=":", linewidth=1.0,
                        label=f"Target ≤ {target_db_per_100ft:.2f} dB/100 ft")

        ax1.set_xlabel("Frequency (MHz)")
        ax1.set_ylabel(f"Loss (dB / 100 {unit})")
        ax1.grid(True, which="both", alpha=0.35)
        ax1.legend(loc="upper left", fontsize=8, framealpha=0.92)
    else:
        axes[0].set_xlabel("Frequency (MHz)")

    axes[-1].xaxis.set_major_locator(mticker.MaxNLocator(nbins=10))

    fig.tight_layout()
    fig.savefig(output_path, format="pdf")
    plt.close(fig)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> int:
    p = argparse.ArgumentParser(
        description="S21 → cable-loss PDF chart (THRU, port 1 → port 2).",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument("--vna",   choices=("nanovna", "hp"), default=DEFAULT_VNA)
    p.add_argument("--port",  default=DEFAULT_PORT)
    p.add_argument("--host",  default=DEFAULT_HP_HOST)
    p.add_argument("--start", type=float, required=True, metavar="MHZ")
    p.add_argument("--stop",  type=float, required=True, metavar="MHZ")
    p.add_argument("--points", type=int, default=DEFAULT_POINTS, metavar="N")
    p.add_argument("--average", type=int, default=1, metavar="N")
    p.add_argument("--power", type=float, default=None, metavar="DBM")
    p.add_argument("--length-ft", type=float, default=None, metavar="FT",
                   help="Cable length in feet (enables per-100-ft panel)")
    p.add_argument("--length-m", type=float, default=None, metavar="M",
                   help="Cable length in metres (enables per-100-m panel)")
    p.add_argument("--compare", default=None, metavar="CABLE",
                   help=f"Overlay published curve for cable type. "
                        f"Known: {', '.join(sorted(CABLE_LIBRARY))}")
    p.add_argument("--target", type=float, default=None, metavar="DB",
                   help="Target pass/fail line in dB/100 ft (e.g. --target 3.0)")
    p.add_argument("--label", default="cable run")
    p.add_argument("--output", required=True, metavar="FILE.pdf")
    args = p.parse_args()

    if args.start <= 0 or args.stop <= 0 or args.stop <= args.start:
        print("Error: --start and --stop must be positive with stop > start (MHz)")
        return 1
    if args.points < 2 or args.average < 1:
        print("Error: --points must be ≥ 2 and --average must be ≥ 1")
        return 1
    if args.length_ft is not None and args.length_m is not None:
        print("Error: pass either --length-ft or --length-m, not both")
        return 1

    start_hz = args.start * 1e6
    stop_hz  = args.stop  * 1e6

    print(f"Cable loss PDF — {args.label}")
    print(f"  Driver       : {args.vna}")
    print(f"  Sweep        : {args.start:.3f} – {args.stop:.3f} MHz, "
          f"{args.points} points, average={args.average}")
    if args.length_ft is not None:
        print(f"  Length       : {args.length_ft:g} ft")
    elif args.length_m is not None:
        print(f"  Length       : {args.length_m:g} m")
    if args.compare:
        print(f"  Comparing to : {args.compare}")
    print(f"  Output       : {args.output}")

    vna = None
    try:
        vna, idn = open_vna(args)
        print(f"  IDN          : {idn[:120]}")
        maybe_set_power(vna, args.power, args.vna)

        freqs_hz, loss_db = measure_s21_loss(
            vna, start_hz, stop_hz, args.points, args.average,
        )

        i_lo, i_mid, i_hi = 0, len(loss_db) // 2, len(loss_db) - 1
        print(f"  Loss @ {freqs_hz[i_lo]/1e6:7.3f} MHz : {loss_db[i_lo]:5.2f} dB")
        print(f"  Loss @ {freqs_hz[i_mid]/1e6:7.3f} MHz : {loss_db[i_mid]:5.2f} dB")
        print(f"  Loss @ {freqs_hz[i_hi]/1e6:7.3f} MHz : {loss_db[i_hi]:5.2f} dB")
        if args.length_ft:
            print(f"  Per 100 ft   @ stop : "
                  f"{loss_db[i_hi] * 100.0 / args.length_ft:5.2f} dB")
        elif args.length_m:
            print(f"  Per 100 m    @ stop : "
                  f"{loss_db[i_hi] * 100.0 / args.length_m:5.2f} dB")

        plot_pdf(
            freqs_hz, loss_db,
            length_ft=args.length_ft, length_m=args.length_m,
            compare_cable=args.compare,
            target_db_per_100ft=args.target,
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
