#!/usr/bin/env python3
"""
filter_pdf.py — S21 → filter response PDF, NanoVNA or HP 8712B.

Sweep S21 of a filter under test, auto-detect the passband and rolloffs,
and write a single-page PDF with the response plus a metrics block:

  - Center frequency (-3 dB centroid)
  - -3 dB / -6 dB / -20 dB / -40 dB / -60 dB bandwidths (when achievable)
  - Passband insertion loss (median of the in-band trace)
  - Passband ripple (peak-to-peak in the -3 dB region)
  - Stopband floor (deepest measured S21 outside the -20 dB band)
  - Shape factor (-60 dB BW / -6 dB BW), when measurable

Setup
-----
    VNA Port 1 ── filter under test ── VNA Port 2  (S21)

Calibrate THRU and reflection on both ports before measuring. With
correction enabled the trace removes the cabling+adapter loss; without
it, those losses count as filter insertion loss.

The detector treats the trace as a single passband. Multi-passband or
all-stop filters need manual interpretation.
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
    s21_db = 20.0 * np.log10(np.clip(np.abs(s21), 1e-12, None))
    return freqs, s21_db


# ---------------------------------------------------------------------------
# Filter analysis
# ---------------------------------------------------------------------------

def find_bandwidth(freqs_mhz: np.ndarray, s21_db: np.ndarray,
                   peak_db: float, peak_idx: int,
                   drop_db: float) -> Optional[tuple[float, float, float]]:
    """
    Find -drop_db bandwidth around the peak. Returns (f_lo, f_center, f_hi)
    in MHz, or None if the -drop_db threshold is never crossed on one side.
    """
    threshold = peak_db - drop_db

    # Walk left until we drop below threshold
    i_lo = peak_idx
    while i_lo > 0 and s21_db[i_lo] >= threshold:
        i_lo -= 1
    if s21_db[i_lo] >= threshold:
        return None  # threshold never crossed on the left
    # Linearly interpolate between i_lo and i_lo+1 to find the precise edge
    x0, x1 = freqs_mhz[i_lo], freqs_mhz[i_lo + 1]
    y0, y1 = s21_db[i_lo], s21_db[i_lo + 1]
    if y1 == y0:
        f_lo = x1
    else:
        f_lo = x0 + (threshold - y0) * (x1 - x0) / (y1 - y0)

    # Walk right
    i_hi = peak_idx
    while i_hi < len(s21_db) - 1 and s21_db[i_hi] >= threshold:
        i_hi += 1
    if s21_db[i_hi] >= threshold:
        return None
    x0, x1 = freqs_mhz[i_hi - 1], freqs_mhz[i_hi]
    y0, y1 = s21_db[i_hi - 1], s21_db[i_hi]
    if y1 == y0:
        f_hi = x0
    else:
        f_hi = x0 + (threshold - y0) * (x1 - x0) / (y1 - y0)

    return f_lo, 0.5 * (f_lo + f_hi), f_hi


def analyze_filter(freqs_hz: np.ndarray, s21_db: np.ndarray) -> dict:
    """Return a dict of filter metrics."""
    freqs_mhz = freqs_hz / 1e6

    peak_idx = int(np.argmax(s21_db))
    peak_db = float(s21_db[peak_idx])

    metrics = {
        "peak_db": peak_db,
        "peak_freq_mhz": float(freqs_mhz[peak_idx]),
        "bandwidths": {},
        "shape_factor_60_6": None,
        "passband_ripple_db": None,
        "stopband_floor_db": None,
        "stopband_floor_freq_mhz": None,
    }

    for drop in (3.0, 6.0, 20.0, 40.0, 60.0):
        bw = find_bandwidth(freqs_mhz, s21_db, peak_db, peak_idx, drop)
        if bw:
            f_lo, f_c, f_hi = bw
            metrics["bandwidths"][drop] = {
                "lo_mhz": f_lo, "center_mhz": f_c, "hi_mhz": f_hi,
                "bw_mhz": f_hi - f_lo,
            }

    # Shape factor (-60 / -6 dB)
    if 6.0 in metrics["bandwidths"] and 60.0 in metrics["bandwidths"]:
        bw6 = metrics["bandwidths"][6.0]["bw_mhz"]
        bw60 = metrics["bandwidths"][60.0]["bw_mhz"]
        if bw6 > 0:
            metrics["shape_factor_60_6"] = bw60 / bw6

    # Passband ripple — peak-to-peak inside the -3 dB band, if found
    if 3.0 in metrics["bandwidths"]:
        f_lo = metrics["bandwidths"][3.0]["lo_mhz"]
        f_hi = metrics["bandwidths"][3.0]["hi_mhz"]
        in_band = (freqs_mhz >= f_lo) & (freqs_mhz <= f_hi)
        if np.any(in_band):
            passband = s21_db[in_band]
            metrics["passband_ripple_db"] = float(passband.max() - passband.min())

    # Stopband floor — deepest sample outside the -20 dB band (if found),
    # otherwise outside the -6 dB band.
    if 20.0 in metrics["bandwidths"]:
        f_lo = metrics["bandwidths"][20.0]["lo_mhz"]
        f_hi = metrics["bandwidths"][20.0]["hi_mhz"]
        out_band = (freqs_mhz < f_lo) | (freqs_mhz > f_hi)
        if np.any(out_band):
            i = int(np.argmin(np.where(out_band, s21_db, 0.0)))
            metrics["stopband_floor_db"] = float(s21_db[i])
            metrics["stopband_floor_freq_mhz"] = float(freqs_mhz[i])
    elif 6.0 in metrics["bandwidths"]:
        f_lo = metrics["bandwidths"][6.0]["lo_mhz"]
        f_hi = metrics["bandwidths"][6.0]["hi_mhz"]
        out_band = (freqs_mhz < f_lo) | (freqs_mhz > f_hi)
        if np.any(out_band):
            i = int(np.argmin(np.where(out_band, s21_db, 0.0)))
            metrics["stopband_floor_db"] = float(s21_db[i])
            metrics["stopband_floor_freq_mhz"] = float(freqs_mhz[i])

    return metrics


# ---------------------------------------------------------------------------
# Plot
# ---------------------------------------------------------------------------

BW_STYLES = {
    3.0:  ("#1f77b4", "-3 dB"),
    6.0:  ("#2ca02c", "-6 dB"),
    20.0: ("#ff7f0e", "-20 dB"),
    40.0: ("#d62728", "-40 dB"),
    60.0: ("#8c564b", "-60 dB"),
}


def plot_pdf(freqs_hz, s21_db, metrics, label, driver_name, idn, output_path):
    freqs_mhz = freqs_hz / 1e6
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    fig, ax = plt.subplots(figsize=(11, 7.5))

    ax.plot(freqs_mhz, s21_db, color="#1f77b4", linewidth=1.4, label="|S21|")

    peak_db = metrics["peak_db"]
    peak_f  = metrics["peak_freq_mhz"]
    ax.plot(peak_f, peak_db, "o", color="purple", markersize=6, zorder=5)
    ax.annotate(
        f"peak {peak_db:+.2f} dB @ {peak_f:.4f} MHz",
        xy=(peak_f, peak_db), xytext=(10, 10), textcoords="offset points",
        fontsize=9, color="purple",
        arrowprops=dict(arrowstyle="->", color="purple", lw=0.8),
    )

    for drop, info in metrics["bandwidths"].items():
        color, name = BW_STYLES.get(drop, ("#666666", f"-{drop:g} dB"))
        ax.axhline(peak_db - drop, color=color, linestyle="--", linewidth=0.8,
                   alpha=0.7)
        ax.axvspan(info["lo_mhz"], info["hi_mhz"], color=color, alpha=0.06,
                   zorder=0)
        # Label the BW band along the top of the chart
        ax.text(
            (info["lo_mhz"] + info["hi_mhz"]) / 2.0, peak_db - drop,
            f"  {name}: BW {info['bw_mhz']:.4f} MHz",
            fontsize=8, color=color, va="bottom", ha="center",
        )

    if metrics["stopband_floor_freq_mhz"] is not None:
        ax.plot(metrics["stopband_floor_freq_mhz"], metrics["stopband_floor_db"],
                "v", color="#444444", markersize=6, zorder=5)
        ax.annotate(
            f"stopband floor {metrics['stopband_floor_db']:.1f} dB @ "
            f"{metrics['stopband_floor_freq_mhz']:.4f} MHz",
            xy=(metrics["stopband_floor_freq_mhz"], metrics["stopband_floor_db"]),
            xytext=(10, -14), textcoords="offset points",
            fontsize=8, color="#444444",
            arrowprops=dict(arrowstyle="->", color="#444444", lw=0.6),
        )

    ax.set_xlim(float(freqs_mhz[0]), float(freqs_mhz[-1]))
    ax.set_xlabel("Frequency (MHz)")
    ax.set_ylabel("|S21| (dB)")
    ax.grid(True, which="both", alpha=0.35)
    ax.legend(loc="upper right", fontsize=8, framealpha=0.92)

    # Metrics block (top-left text)
    lines = [
        f"Peak       : {peak_db:+.2f} dB @ {peak_f:.4f} MHz",
    ]
    for drop in (3.0, 6.0, 20.0, 40.0, 60.0):
        if drop in metrics["bandwidths"]:
            b = metrics["bandwidths"][drop]
            lines.append(
                f"-{drop:>2.0f} dB BW : {b['bw_mhz']:9.4f} MHz   "
                f"({b['lo_mhz']:.4f} – {b['hi_mhz']:.4f})"
            )
        else:
            lines.append(f"-{drop:>2.0f} dB BW : not crossed in sweep range")
    if metrics["passband_ripple_db"] is not None:
        lines.append(f"Ripple PP  : {metrics['passband_ripple_db']:.2f} dB "
                     f"(within -3 dB BW)")
    if metrics["shape_factor_60_6"] is not None:
        lines.append(f"Shape factor (-60/-6) : "
                     f"{metrics['shape_factor_60_6']:.2f}")
    if metrics["stopband_floor_db"] is not None:
        lines.append(f"Stopband   : {metrics['stopband_floor_db']:+.1f} dB "
                     f"@ {metrics['stopband_floor_freq_mhz']:.3f} MHz")
    ax.text(
        0.005, 0.005, "\n".join(lines),
        transform=ax.transAxes, fontsize=8, family="monospace",
        va="bottom", ha="left",
        bbox=dict(facecolor="white", edgecolor="#cccccc", alpha=0.9, pad=4),
    )

    title_lines = [
        f"Filter Response — {label}",
        f"{freqs_mhz[0]:.4f} – {freqs_mhz[-1]:.4f} MHz  •  {len(freqs_hz)} points  "
        f"•  {driver_name}  •  {ts}",
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
        description="S21 → filter response PDF with auto-annotated bandwidths.",
    )
    p.add_argument("--vna",   choices=("nanovna", "hp"), default=DEFAULT_VNA)
    p.add_argument("--port",  default=DEFAULT_PORT)
    p.add_argument("--host",  default=DEFAULT_HP_HOST)
    p.add_argument("--start", type=float, required=True, metavar="MHZ")
    p.add_argument("--stop",  type=float, required=True, metavar="MHZ")
    p.add_argument("--points", type=int, default=DEFAULT_POINTS, metavar="N")
    p.add_argument("--average", type=int, default=1, metavar="N")
    p.add_argument("--power", type=float, default=None, metavar="DBM")
    p.add_argument("--label", default="filter")
    p.add_argument("--output", required=True, metavar="FILE.pdf")
    args = p.parse_args()

    if args.start <= 0 or args.stop <= 0 or args.stop <= args.start:
        print("Error: --start and --stop must be positive with stop > start (MHz)")
        return 1
    if args.points < 2 or args.average < 1:
        print("Error: --points must be ≥ 2 and --average must be ≥ 1")
        return 1

    print(f"Filter PDF — {args.label}")
    print(f"  Driver       : {args.vna}")
    print(f"  Sweep        : {args.start:.4f} – {args.stop:.4f} MHz, "
          f"{args.points} points, average={args.average}")
    print(f"  Output       : {args.output}")

    vna = None
    try:
        vna, idn = open_vna(args)
        print(f"  IDN          : {idn[:120]}")
        maybe_set_power(vna, args.power, args.vna)

        freqs_hz, s21_db = measure_s21(
            vna, args.start * 1e6, args.stop * 1e6, args.points, args.average,
        )
        metrics = analyze_filter(freqs_hz, s21_db)

        print(f"  Peak         : {metrics['peak_db']:+.2f} dB @ "
              f"{metrics['peak_freq_mhz']:.4f} MHz")
        for drop in (3.0, 6.0, 20.0, 60.0):
            if drop in metrics["bandwidths"]:
                b = metrics["bandwidths"][drop]
                print(f"  -{drop:>2.0f} dB BW    : {b['bw_mhz']:.4f} MHz "
                      f"({b['lo_mhz']:.4f} – {b['hi_mhz']:.4f})")
        if metrics["passband_ripple_db"] is not None:
            print(f"  Passband PP  : {metrics['passband_ripple_db']:.2f} dB")
        if metrics["shape_factor_60_6"] is not None:
            print(f"  Shape factor : {metrics['shape_factor_60_6']:.2f}")
        if metrics["stopband_floor_db"] is not None:
            print(f"  Stopband     : {metrics['stopband_floor_db']:+.1f} dB @ "
                  f"{metrics['stopband_floor_freq_mhz']:.3f} MHz")

        plot_pdf(
            freqs_hz, s21_db, metrics,
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
