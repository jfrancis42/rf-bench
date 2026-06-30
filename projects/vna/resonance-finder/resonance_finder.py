#!/usr/bin/env python3
"""
resonance_finder.py — Auto-find S11 dips, fit Q, output table + PDF.

Sweep S11 across a wide range, detect every local minimum in |S11|
(i.e. every resonance), and characterise each one:

  - Resonant frequency f0 (point of deepest |S11|)
  - -3 dB bandwidth around f0 (return-loss method: where the dip rises
    3 dB above the minimum)
  - Loaded Q = f0 / BW3dB

Use cases
---------
  - Tuning traps in trap dipoles / verticals
  - Characterising helical resonators
  - Crystal motional parameters (rough estimate; for proper xtal Q
    you want a fancier fixture and the HP)
  - Hunting "Where the heck is this antenna resonant?" on a homebrew
    rig where you don't have a guess

Outputs
-------
  - Console table
  - PDF chart with each resonance labelled with f0 / BW / Q
  - Optional CSV with the raw resonance list
"""

from __future__ import annotations

import argparse
import csv
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
    s11_db = 20.0 * np.log10(np.clip(np.abs(gamma), 1e-12, None))
    return freqs, gamma, s11_db


# ---------------------------------------------------------------------------
# Peak / dip detection
# ---------------------------------------------------------------------------

def find_resonances(freqs_hz: np.ndarray, s11_db: np.ndarray,
                    min_depth_db: float, min_separation_mhz: float):
    """
    Find all local minima of s11_db deeper than -min_depth_db, separated by
    at least min_separation_mhz from one another.

    Returns a list of dicts with f0_mhz, depth_db, bw3db_mhz, q, lo, hi.
    """
    freqs_mhz = freqs_hz / 1e6
    n = len(s11_db)
    if n < 5:
        return []

    # Discrete local minima: s[i] < s[i-1] and s[i] < s[i+1]
    is_min = np.zeros(n, dtype=bool)
    is_min[1:-1] = (s11_db[1:-1] < s11_db[:-2]) & (s11_db[1:-1] < s11_db[2:])

    # Filter on absolute depth (more negative = deeper)
    is_min &= s11_db <= -float(min_depth_db)

    candidates = np.where(is_min)[0].tolist()
    # Suppress neighbours within min_separation
    selected = []
    for idx in sorted(candidates, key=lambda i: s11_db[i]):
        if all(abs(freqs_mhz[idx] - freqs_mhz[j]) >= min_separation_mhz
               for j in selected):
            selected.append(idx)
    selected.sort()

    resonances = []
    for idx in selected:
        depth = float(s11_db[idx])
        threshold = depth + 3.0  # 3 dB up from the dip (less negative)

        # Walk left
        j_lo = idx
        while j_lo > 0 and s11_db[j_lo] <= threshold:
            j_lo -= 1
        if s11_db[j_lo] <= threshold:
            f_lo_mhz = float(freqs_mhz[j_lo])
        else:
            x0, x1 = freqs_mhz[j_lo], freqs_mhz[j_lo + 1]
            y0, y1 = s11_db[j_lo], s11_db[j_lo + 1]
            f_lo_mhz = float(x0 + (threshold - y0) * (x1 - x0) / (y1 - y0)
                             if y1 != y0 else x0)

        # Walk right
        j_hi = idx
        while j_hi < n - 1 and s11_db[j_hi] <= threshold:
            j_hi += 1
        if s11_db[j_hi] <= threshold:
            f_hi_mhz = float(freqs_mhz[j_hi])
        else:
            x0, x1 = freqs_mhz[j_hi - 1], freqs_mhz[j_hi]
            y0, y1 = s11_db[j_hi - 1], s11_db[j_hi]
            f_hi_mhz = float(x0 + (threshold - y0) * (x1 - x0) / (y1 - y0)
                             if y1 != y0 else x1)

        f0_mhz = float(freqs_mhz[idx])
        bw3 = f_hi_mhz - f_lo_mhz
        q = (f0_mhz / bw3) if bw3 > 0 else float("nan")

        resonances.append({
            "f0_mhz": f0_mhz,
            "depth_db": depth,
            "bw3db_mhz": bw3,
            "q": q,
            "lo_mhz": f_lo_mhz,
            "hi_mhz": f_hi_mhz,
        })

    resonances.sort(key=lambda r: r["f0_mhz"])
    return resonances


# ---------------------------------------------------------------------------
# Plot
# ---------------------------------------------------------------------------

def plot_pdf(freqs_hz, s11_db, resonances, label, driver_name, idn, output_path):
    freqs_mhz = freqs_hz / 1e6
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    fig, ax = plt.subplots(figsize=(11, 7.5))

    ax.plot(freqs_mhz, s11_db, color="#1f77b4", linewidth=1.2, label="|S11|")
    ax.set_xlim(float(freqs_mhz[0]), float(freqs_mhz[-1]))
    ax.invert_yaxis()  # negative dB grows downward; flip so dips point UP
    ax.set_xlabel("Frequency (MHz)")
    ax.set_ylabel("|S11| (dB)  —  dips pointing up")
    ax.grid(True, which="both", alpha=0.35)

    for k, r in enumerate(resonances, start=1):
        ax.plot(r["f0_mhz"], r["depth_db"], "v", color="red", markersize=7,
                zorder=5)
        ax.axvspan(r["lo_mhz"], r["hi_mhz"], color="red", alpha=0.07, zorder=0)
        ax.annotate(
            f"#{k}\nf0 = {r['f0_mhz']:.4f} MHz\n"
            f"depth {r['depth_db']:.1f} dB\n"
            f"BW = {r['bw3db_mhz']*1e3:.1f} kHz\n"
            f"Q = {r['q']:.0f}" if not np.isnan(r['q'])
            else f"#{k}\nf0 = {r['f0_mhz']:.4f} MHz\n"
                 f"depth {r['depth_db']:.1f} dB\nBW unresolved",
            xy=(r["f0_mhz"], r["depth_db"]),
            xytext=(8, -8), textcoords="offset points",
            fontsize=7, color="red",
            arrowprops=dict(arrowstyle="->", color="red", lw=0.6),
            bbox=dict(facecolor="white", edgecolor="red", alpha=0.85, pad=2),
        )

    title_lines = [
        f"Resonance Finder — {label}",
        f"{freqs_mhz[0]:.3f} – {freqs_mhz[-1]:.3f} MHz  •  "
        f"{len(freqs_hz)} points  •  {len(resonances)} resonance(s)  •  "
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
        description="Auto-find S11 dips and characterise Q.",
    )
    p.add_argument("--vna",   choices=("nanovna", "hp"), default=DEFAULT_VNA)
    p.add_argument("--port",  default=DEFAULT_PORT)
    p.add_argument("--host",  default=DEFAULT_HP_HOST)
    p.add_argument("--start", type=float, required=True, metavar="MHZ")
    p.add_argument("--stop",  type=float, required=True, metavar="MHZ")
    p.add_argument("--points", type=int, default=DEFAULT_POINTS, metavar="N")
    p.add_argument("--average", type=int, default=2, metavar="N")
    p.add_argument("--power", type=float, default=None, metavar="DBM")
    p.add_argument("--min-depth", type=float, default=6.0, metavar="DB",
                   help="Only count dips deeper than this in dB (default 6.0)")
    p.add_argument("--min-separation", type=float, default=0.0, metavar="MHZ",
                   help="Minimum frequency separation between dips (default: "
                        "auto = 1%% of sweep span)")
    p.add_argument("--label", default="DUT")
    p.add_argument("--output", required=True, metavar="FILE.pdf")
    p.add_argument("--csv", default=None, metavar="FILE.csv",
                   help="Optional CSV output of the resonance list")
    args = p.parse_args()

    if args.start <= 0 or args.stop <= 0 or args.stop <= args.start:
        print("Error: --start and --stop must be positive with stop > start (MHz)")
        return 1
    if args.points < 2 or args.average < 1:
        print("Error: --points must be ≥ 2 and --average must be ≥ 1")
        return 1
    if args.min_depth <= 0:
        print("Error: --min-depth must be > 0 dB")
        return 1

    sep_mhz = args.min_separation
    if sep_mhz <= 0:
        sep_mhz = (args.stop - args.start) * 0.01

    print(f"Resonance Finder — {args.label}")
    print(f"  Driver       : {args.vna}")
    print(f"  Sweep        : {args.start:.3f} – {args.stop:.3f} MHz, "
          f"{args.points} points, average={args.average}")
    print(f"  Min depth    : {args.min_depth:g} dB")
    print(f"  Min sep      : {sep_mhz:g} MHz")
    print(f"  Output       : {args.output}")

    vna = None
    try:
        vna, idn = open_vna(args)
        print(f"  IDN          : {idn[:120]}")
        maybe_set_power(vna, args.power, args.vna)

        freqs_hz, gamma, s11_db = measure_s11(
            vna, args.start * 1e6, args.stop * 1e6, args.points, args.average,
        )

        resonances = find_resonances(
            freqs_hz, s11_db,
            min_depth_db=args.min_depth,
            min_separation_mhz=sep_mhz,
        )

        if not resonances:
            print("  No resonances found with the given thresholds.")
        else:
            print()
            print(f"  {'#':>3}  {'f0 (MHz)':>12}  {'depth (dB)':>10}  "
                  f"{'BW3dB (kHz)':>11}  {'Q':>7}")
            print(f"  {'-'*3}  {'-'*12}  {'-'*10}  {'-'*11}  {'-'*7}")
            for k, r in enumerate(resonances, start=1):
                q_str = "n/a" if np.isnan(r["q"]) else f"{r['q']:.0f}"
                print(f"  {k:>3}  {r['f0_mhz']:>12.4f}  "
                      f"{r['depth_db']:>10.1f}  "
                      f"{r['bw3db_mhz']*1e3:>11.1f}  "
                      f"{q_str:>7}")

        if args.csv:
            with open(args.csv, "w", newline="") as fh:
                w = csv.writer(fh)
                w.writerow(["index", "f0_mhz", "depth_db", "bw3db_mhz", "Q",
                            "lo_3db_mhz", "hi_3db_mhz"])
                for k, r in enumerate(resonances, start=1):
                    w.writerow([k, r["f0_mhz"], r["depth_db"],
                                r["bw3db_mhz"], r["q"],
                                r["lo_mhz"], r["hi_mhz"]])
            print(f"  Wrote CSV    → {args.csv}")

        plot_pdf(
            freqs_hz, s11_db, resonances,
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
