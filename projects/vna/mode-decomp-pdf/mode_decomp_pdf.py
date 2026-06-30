#!/usr/bin/env python3
"""
mode_decomp_pdf.py — Mode-decomposition for overmoded waveguide / coax.

Above a cable's TE/TM-mode cutoff frequency, propagation is no longer
single-mode TEM (coax) or single-mode TE10 (rectangular waveguide).
Multiple modes propagate at different phase velocities, producing
periodic ripples in S21 that beat against each other.

This script Fourier-analyses an S21 trace to identify the dominant
mode pair via the spatial frequency of the beat note. The cepstrum
of S21 picks out distinct propagation velocities.

UNTESTED. Mostly a research curiosity at VHF/UHF where most ham coax
is well below mode cutoff. Useful at K-band+ and oversize waveguide.
"""

from __future__ import annotations
import warnings
warnings.filterwarnings("ignore", message="Unable to import Axes3D")
import argparse, sys
from datetime import datetime
import matplotlib; matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parent.parent / "vector-fit-spice"))
from vector_fit_spice import read_touchstone


def mode_decomp(freqs_hz, s21, vf=0.66):
    """
    FFT |S21| (linear, not dB) across frequency. The peaks in the
    spatial Fourier transform correspond to mode-pair beat lengths;
    different propagation velocities show up as distinct peaks.
    """
    n = len(freqs_hz)
    mag = np.abs(s21)
    df = float(freqs_hz[1] - freqs_hz[0])
    # Window to suppress sidelobes
    w = np.hanning(n)
    fft = np.fft.rfft(mag * w)
    # Spatial frequency axis ↔ delay τ ↔ mode propagation difference
    # Δβ. At velocity v, fft peak at τ corresponds to a path of length
    # L = v · τ.
    tau = np.fft.rfftfreq(n, d=df)
    L = vf * 299_792_458.0 * tau / 2.0  # one-way length
    return L, np.abs(fft)


def main() -> int:
    p = argparse.ArgumentParser(
        description="Mode decomposition for overmoded waveguide / coax.")
    p.add_argument("--input", required=True, metavar="DUT.s2p")
    p.add_argument("--parameter", default="S21",
                   choices=("S11","S21","S12","S22"))
    p.add_argument("--vf", type=float, default=0.66)
    p.add_argument("--label", default="DUT")
    p.add_argument("--output", required=True, metavar="FILE.pdf")
    args = p.parse_args()

    try:
        freqs, H, _ = read_touchstone(args.input, args.parameter)
    except FileNotFoundError as exc:
        print(f"File not found: {exc.filename}", file=sys.stderr); return 1

    L, fft = mode_decomp(freqs, H, args.vf)
    fig, ax = plt.subplots(figsize=(11, 6))
    ax.semilogy(L, fft, color="#1f77b4", linewidth=1.1)
    ax.set_xlabel("Equivalent propagation length (m, vf={:.2f})".format(args.vf))
    ax.set_ylabel("|spatial FFT|")
    ax.grid(True, which="both", alpha=0.35)
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    ax.set_title(f"Mode decomposition — {args.label}  •  {args.parameter}  "
                 f"•  {ts}", fontsize=10)
    fig.tight_layout(); fig.savefig(args.output, format="pdf"); plt.close(fig)
    # Top 3 peaks past first 5 cm
    mask = L > 0.05
    Lmsk = L[mask]; fmsk = fft[mask]
    idx = np.argsort(fmsk)[-3:][::-1]
    print(f"Mode decomp — top 3 peaks:")
    for j in idx:
        print(f"  L = {Lmsk[j]:.3f} m   |FFT| = {fmsk[j]:.3e}")
    print(f"Wrote {args.output}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
