#!/usr/bin/env python3
"""
group_delay_pdf.py — S21 → group delay PDF, NanoVNA or HP 8712B.

Group delay τ_g(f) = −dφ/dω is the time a narrowband signal centred at
f spends propagating through a 2-port DUT. It comes straight from the
complex S21 the VNA already returns:

    φ(f)    = np.unwrap(np.angle(S21(f)))             radians
    ω(f)    = 2π·f                                     rad/s
    τ_g(f)  = −dφ/dω                                   seconds

This is a focused tool for amplifier / cable / line / matching-network
group-delay characterisation. For filter group-delay where you also
want the magnitude response, use `../filter-pdf/` with the
`--group-delay` flag — same math, but co-plotted with |S21|.

Setup
-----
    VNA Port 1 ── DUT ── VNA Port 2  (S21 THRU)

Full SOLT (or at minimum THRU) calibration is essential. Group delay
is a derivative of phase — any phase contamination from cabling
appears as constant offset *and* shape error.

Plot
----
Three-panel PDF sharing a frequency axis:

  - |S21| (dB)              — for context: where IS there a signal?
  - ∠S21 unwrapped (°)       — the underlying phase trace
  - Group delay (ns)         — the actual deliverable

The minimum / mean / maximum / peak-to-peak group-delay over the sweep
(or the user-specified region of interest) is printed and overlaid.
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


def compute_group_delay_ns(freqs_hz: np.ndarray,
                           s21: np.ndarray) -> np.ndarray:
    phase = np.unwrap(np.angle(s21))
    omega = 2.0 * np.pi * freqs_hz
    return -np.gradient(phase, omega) * 1e9


# ---------------------------------------------------------------------------
# Plot
# ---------------------------------------------------------------------------

def plot_pdf(freqs_hz, s21, gd_ns, roi_mhz,
             label, driver_name, idn, output_path):
    freqs_mhz = freqs_hz / 1e6
    s21_db    = 20.0 * np.log10(np.clip(np.abs(s21), 1e-12, None))
    phase_deg = np.degrees(np.unwrap(np.angle(s21)))
    ts        = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    if roi_mhz is not None:
        roi_lo, roi_hi = roi_mhz
        mask = (freqs_mhz >= roi_lo) & (freqs_mhz <= roi_hi)
    else:
        mask = np.ones_like(freqs_mhz, dtype=bool)
        roi_lo, roi_hi = float(freqs_mhz[0]), float(freqs_mhz[-1])

    fig, (ax_mag, ax_phase, ax_gd) = plt.subplots(
        3, 1, figsize=(11, 11), sharex=True)

    # |S21|
    ax_mag.plot(freqs_mhz, s21_db, color="#1f77b4", linewidth=1.4)
    ax_mag.set_ylabel("|S21| (dB)")
    ax_mag.grid(True, which="both", alpha=0.35)
    if roi_mhz is not None:
        ax_mag.axvspan(roi_lo, roi_hi, color="#ff7f0e", alpha=0.08,
                       label="ROI")
        ax_mag.legend(loc="upper right", fontsize=8, framealpha=0.92)
    title_lines = [
        f"Group Delay — {label}",
        f"{freqs_mhz[0]:.4f} – {freqs_mhz[-1]:.4f} MHz  •  "
        f"{len(freqs_hz)} points  •  {driver_name}  •  {ts}",
    ]
    if idn:
        title_lines.append(idn[:120])
    ax_mag.set_title("\n".join(title_lines), fontsize=10)

    # Phase
    ax_phase.plot(freqs_mhz, phase_deg, color="#9467bd", linewidth=1.2)
    ax_phase.set_ylabel("∠S21 unwrapped (°)")
    ax_phase.grid(True, which="both", alpha=0.35)
    if roi_mhz is not None:
        ax_phase.axvspan(roi_lo, roi_hi, color="#ff7f0e", alpha=0.08)

    # Group delay
    ax_gd.plot(freqs_mhz, gd_ns, color="#2ca02c", linewidth=1.1, alpha=0.45,
               label="All samples")
    if roi_mhz is not None:
        ax_gd.plot(freqs_mhz[mask], gd_ns[mask], color="#2ca02c",
                   linewidth=1.6, label=f"ROI ({roi_lo:.3f}–{roi_hi:.3f} MHz)")
        ax_gd.axvspan(roi_lo, roi_hi, color="#ff7f0e", alpha=0.08)
    ax_gd.set_xlabel("Frequency (MHz)")
    ax_gd.set_ylabel("Group delay (ns)")
    ax_gd.grid(True, which="both", alpha=0.35)
    ax_gd.legend(loc="upper right", fontsize=8, framealpha=0.92)

    if np.any(mask):
        gd_seg = gd_ns[mask]
        ax_gd.text(
            0.005, 0.97,
            f"GD over ROI: min {gd_seg.min():.3f}  mean {gd_seg.mean():.3f}  "
            f"max {gd_seg.max():.3f}  p-p {gd_seg.max() - gd_seg.min():.3f} ns",
            transform=ax_gd.transAxes, fontsize=8, family="monospace",
            va="top", ha="left",
            bbox=dict(facecolor="white", edgecolor="#cccccc", alpha=0.9, pad=3),
        )

    fig.tight_layout()
    fig.savefig(output_path, format="pdf")
    plt.close(fig)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> int:
    p = argparse.ArgumentParser(
        description="S21 → group-delay PDF (|S21| / phase / GD panels).",
    )
    p.add_argument("--vna",   choices=("nanovna", "hp"), default=DEFAULT_VNA)
    p.add_argument("--port",  default=DEFAULT_PORT)
    p.add_argument("--host",  default=DEFAULT_HP_HOST)
    p.add_argument("--start", type=float, required=True, metavar="MHZ")
    p.add_argument("--stop",  type=float, required=True, metavar="MHZ")
    p.add_argument("--points", type=int, default=DEFAULT_POINTS, metavar="N")
    p.add_argument("--average", type=int, default=4, metavar="N",
                   help="Software-average N sweeps (default 4; GD is "
                        "derivative-sensitive so more is better)")
    p.add_argument("--power", type=float, default=None, metavar="DBM")
    p.add_argument("--roi", nargs=2, type=float, default=None,
                   metavar=("MHZ_LO", "MHZ_HI"),
                   help="Region of interest in MHz; statistics are computed "
                        "over this range and the ROI is shaded on every panel. "
                        "Default: full sweep.")
    p.add_argument("--label", default="DUT")
    p.add_argument("--output", required=True, metavar="FILE.pdf")
    args = p.parse_args()

    if args.start <= 0 or args.stop <= 0 or args.stop <= args.start:
        print("Error: --start and --stop must be positive with stop > start")
        return 1
    if args.points < 4 or args.average < 1:
        print("Error: --points must be ≥ 4 and --average must be ≥ 1")
        return 1
    if args.roi is not None and args.roi[1] <= args.roi[0]:
        print("Error: --roi must be MHZ_LO MHZ_HI with HI > LO")
        return 1

    print(f"Group-delay PDF — {args.label}")
    print(f"  Driver       : {args.vna}")
    print(f"  Sweep        : {args.start:.4f} – {args.stop:.4f} MHz, "
          f"{args.points} points, average={args.average}")
    if args.roi:
        print(f"  ROI          : {args.roi[0]:.4f} – {args.roi[1]:.4f} MHz")
    print(f"  Output       : {args.output}")

    vna = None
    try:
        vna, idn = open_vna(args)
        print(f"  IDN          : {idn[:120]}")
        maybe_set_power(vna, args.power, args.vna)

        freqs_hz, s21 = measure_s21(
            vna, args.start * 1e6, args.stop * 1e6, args.points, args.average,
        )
        gd_ns = compute_group_delay_ns(freqs_hz, s21)

        if args.roi:
            freqs_mhz = freqs_hz / 1e6
            mask = (freqs_mhz >= args.roi[0]) & (freqs_mhz <= args.roi[1])
            if not np.any(mask):
                print("  ROI is outside the sweep; falling back to full sweep.")
                roi = None
            else:
                roi = tuple(args.roi)
                seg = gd_ns[mask]
                print(f"  ROI GD       : min {seg.min():.3f}, "
                      f"mean {seg.mean():.3f}, max {seg.max():.3f}, "
                      f"p-p {seg.max() - seg.min():.3f} ns")
        else:
            roi = None
            print(f"  Sweep GD     : min {gd_ns.min():.3f}, "
                  f"mean {gd_ns.mean():.3f}, max {gd_ns.max():.3f}, "
                  f"p-p {gd_ns.max() - gd_ns.min():.3f} ns")

        plot_pdf(
            freqs_hz, s21, gd_ns, roi,
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
