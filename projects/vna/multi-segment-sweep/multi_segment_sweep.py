#!/usr/bin/env python3
"""
multi_segment_sweep.py — Wideband sweep stitching for the NanoVNA.

The NanoVNA caps at 401 points per sweep. For wide spans at fine
resolution, you need many sequential narrower sweeps. This script
automates that:

  1. Splits the requested span into segments of `--seg-points` each.
  2. Sweeps each segment, captures S11+S21 complex data.
  3. Concatenates the results into one Touchstone .s2p.
  4. Writes a PDF preview of the stitched sweep.

The HP 8712B does this natively (8001-point internal sweep on some
firmwares), so `--vna hp` just runs one big sweep without stitching.

Caveat
------
Each segment uses whatever calibration is currently loaded in the
VNA. If the cal was performed across a wider span than each
segment, the residual error in each segment may differ slightly.
For ultimate accuracy, calibrate per segment (manual; not automated
here). Edges between segments may show a small discontinuity that
this script does NOT smooth — it preserves raw data so you can see
it.
"""

from __future__ import annotations
import warnings
warnings.filterwarnings("ignore", message="Unable to import Axes3D")
import argparse, sys
from datetime import datetime
import matplotlib; matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parent.parent / "de-embed-pdf"))
from de_embed_pdf import write_s2p


def open_vna(args):
    if args.vna == "nanovna":
        from rf_bench.nanovna import NanoVNA
        return NanoVNA(port=args.port)
    from rf_bench.hp import HP8712B
    return HP8712B(host=args.host)


def measure_segment(vna, f_lo, f_hi, points, averaging):
    vna.setup_sweep(f_lo, f_hi, points)
    vna.set_parameter("S11")
    vna.single_sweep()
    freqs = vna.get_frequencies()
    s11 = vna.average_s_data(averaging) if averaging > 1 else vna.get_s_data()
    vna.set_parameter("S21")
    vna.single_sweep()
    s21 = vna.average_s_data(averaging) if averaging > 1 else vna.get_s_data()
    return freqs, s11, s21


def plot_pdf(freqs_hz, s11, s21, segment_edges, label, output):
    freqs_mhz = freqs_hz / 1e6
    fig, axes = plt.subplots(2, 1, figsize=(11, 8), sharex=True)
    axes[0].plot(freqs_mhz, 20*np.log10(np.clip(np.abs(s11), 1e-12, None)),
                 color="#1f77b4", linewidth=0.8)
    axes[0].set_ylabel("|S11| (dB)")
    axes[1].plot(freqs_mhz, 20*np.log10(np.clip(np.abs(s21), 1e-12, None)),
                 color="#2ca02c", linewidth=0.8)
    axes[1].set_ylabel("|S21| (dB)")
    axes[1].set_xlabel("Frequency (MHz)")
    for edge in segment_edges[1:-1]:
        for ax in axes:
            ax.axvline(edge/1e6, color="#cccccc", linewidth=0.5)
    for ax in axes:
        ax.grid(True, alpha=0.35)
    fig.suptitle(f"Multi-segment sweep — {label}  •  "
                 f"{freqs_mhz[0]:.3f}–{freqs_mhz[-1]:.3f} MHz  •  "
                 f"{len(segment_edges)-1} segments", fontsize=10)
    fig.tight_layout(rect=(0, 0, 1, 0.95))
    fig.savefig(output, format="pdf"); plt.close(fig)


def main() -> int:
    p = argparse.ArgumentParser(
        description="Stitch many narrow VNA sweeps into one wide-band capture.")
    p.add_argument("--vna", choices=("nanovna", "hp"), default="nanovna")
    p.add_argument("--port", default="/dev/ttyACM1")
    p.add_argument("--host", default="10.1.1.70")
    p.add_argument("--start", type=float, required=True, metavar="MHZ")
    p.add_argument("--stop",  type=float, required=True, metavar="MHZ")
    p.add_argument("--seg-points", type=int, default=401, metavar="N",
                   help="Points per segment (default 401 = NanoVNA max).")
    p.add_argument("--n-segments", type=int, default=None, metavar="N",
                   help="Number of segments (default: auto so each segment "
                        "ends up with seg-points points across an "
                        "equal-width slice).")
    p.add_argument("--average", type=int, default=2)
    p.add_argument("--label", default="wideband sweep")
    p.add_argument("--output", required=True, metavar="FILE.pdf")
    p.add_argument("--touchstone", default=None, metavar="FILE.s2p")
    args = p.parse_args()

    if args.touchstone is None:
        args.touchstone = (args.output[:-4]+".s2p"
                           if args.output.lower().endswith(".pdf")
                           else args.output+".s2p")

    n_seg = args.n_segments or max(1, int(np.ceil(
        (args.stop - args.start) / 100.0)))   # default ~100 MHz per segment
    edges_mhz = np.linspace(args.start, args.stop, n_seg + 1)

    print(f"Multi-segment sweep — {args.label}")
    print(f"  Driver       : {args.vna}")
    print(f"  Total span   : {args.start:.3f} – {args.stop:.3f} MHz")
    print(f"  Segments     : {n_seg} × {args.seg_points} points")
    print(f"  Total points : {n_seg * args.seg_points}")

    vna = open_vna(args)
    try:
        freqs_all = []
        s11_all   = []
        s21_all   = []
        for i in range(n_seg):
            f_lo_mhz, f_hi_mhz = edges_mhz[i], edges_mhz[i+1]
            print(f"  Seg {i+1}/{n_seg}: {f_lo_mhz:.3f} – {f_hi_mhz:.3f} MHz ...",
                  flush=True)
            f, s11, s21 = measure_segment(vna, f_lo_mhz*1e6, f_hi_mhz*1e6,
                                          args.seg_points, args.average)
            # On segments past the first, drop the leading-edge sample to
            # avoid a duplicate at the boundary
            if i > 0:
                f = f[1:]; s11 = s11[1:]; s21 = s21[1:]
            freqs_all.append(f); s11_all.append(s11); s21_all.append(s21)
        freqs = np.concatenate(freqs_all)
        s11   = np.concatenate(s11_all)
        s21   = np.concatenate(s21_all)
    finally:
        try: vna.close()
        except Exception: pass

    # Build the .s2p
    n = len(freqs)
    S = np.zeros((n, 2, 2), dtype=np.complex128)
    S[:, 0, 0] = s11
    S[:, 1, 0] = s21
    # S12 and S22 are not measured here (would need DUT reversal)
    S[:, 0, 1] = 0
    S[:, 1, 1] = 0
    write_s2p(args.touchstone, freqs, S, 50.0, comment_lines=[
        f"Multi-segment stitched sweep ({n_seg} segments)",
        "S12, S22 are zeros — not measured in this single-pass mode",
    ])
    print(f"  Wrote .s2p   → {args.touchstone}")
    plot_pdf(freqs, s11, s21, edges_mhz*1e6, args.label, args.output)
    print(f"  Wrote PDF    → {args.output}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
