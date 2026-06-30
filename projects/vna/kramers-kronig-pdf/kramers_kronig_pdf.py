#!/usr/bin/env python3
"""
kramers_kronig_pdf.py — Causality check via Kramers-Kronig relations.

The real and imaginary parts of any causal frequency-domain response
are Hilbert transforms of each other. Measure both; reconstruct one
from the other; the residual error is a diagnostic:

  - near zero        → measurement is consistent with causality
  - non-zero, broad  → calibration error introducing non-causal response
  - non-zero, peaked → real DUT non-causality (gain, externally pumped)
                       or numerical issue near a sharp resonance

This is a pure post-processor that takes a Touchstone .s2p, picks one
S-parameter (default S21), and computes the Hilbert-transform
reconstruction. Plots the measured Re / Im components against the
reconstructed Re / Im and reports an RMS residual.

Useful especially for verifying that a SOLT calibration produced
clean output — a 5 % causality residual means the calibration is
introducing more error than the DUT does.
"""

from __future__ import annotations

import warnings
warnings.filterwarnings("ignore", message="Unable to import Axes3D")

import argparse
import sys
from datetime import datetime

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

# Reuse Touchstone reader from vector-fit-spice
sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parent.parent / "vector-fit-spice"))
from vector_fit_spice import read_touchstone


def hilbert_reconstruct(re_part: np.ndarray, im_part: np.ndarray):
    """
    Reconstruct the imaginary part from the real part (and vice versa)
    using a discrete Hilbert transform on the supplied frequency-domain
    samples.

    Returns (im_from_re, re_from_im).
    """
    n = len(re_part)
    # Build the analytic signal in the time domain
    from scipy.signal import hilbert
    re_recon = hilbert(im_part).imag
    im_recon = -hilbert(re_part).imag
    return im_recon, re_recon


def plot_pdf(freqs_hz, h_meas, im_recon, re_recon, rms_re, rms_im, parameter,
             label, output):
    freqs_mhz = freqs_hz / 1e6
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    fig, axes = plt.subplots(3, 1, figsize=(11, 11), sharex=True)
    axes[0].plot(freqs_mhz, h_meas.real, "--", color="#888888",
                 linewidth=1.0, label="Re measured")
    axes[0].plot(freqs_mhz, re_recon, color="#1f77b4", linewidth=1.4,
                 label="Re from Hilbert(Im)")
    axes[0].set_ylabel(f"Re {parameter}")
    axes[0].grid(True, which="both", alpha=0.35)
    axes[0].legend(loc="upper right", fontsize=8)

    axes[1].plot(freqs_mhz, h_meas.imag, "--", color="#888888",
                 linewidth=1.0, label="Im measured")
    axes[1].plot(freqs_mhz, im_recon, color="#2ca02c", linewidth=1.4,
                 label="Im from Hilbert(Re)")
    axes[1].set_ylabel(f"Im {parameter}")
    axes[1].grid(True, which="both", alpha=0.35)
    axes[1].legend(loc="upper right", fontsize=8)

    axes[2].plot(freqs_mhz, h_meas.real - re_recon, color="#d62728",
                 linewidth=1.0, label=f"Re residual (RMS {rms_re:.4f})")
    axes[2].plot(freqs_mhz, h_meas.imag - im_recon, color="#9467bd",
                 linewidth=1.0, label=f"Im residual (RMS {rms_im:.4f})")
    axes[2].axhline(0, color="#888888", linewidth=0.6)
    axes[2].set_xlabel("Frequency (MHz)")
    axes[2].set_ylabel("residual")
    axes[2].grid(True, which="both", alpha=0.35)
    axes[2].legend(loc="upper right", fontsize=8)
    fig.suptitle(
        f"Kramers-Kronig causality check — {label}\n"
        f"Parameter: {parameter}  •  {freqs_mhz[0]:.4f} – "
        f"{freqs_mhz[-1]:.4f} MHz  •  {ts}", fontsize=10)
    fig.tight_layout(rect=(0, 0, 1, 0.95))
    fig.savefig(output, format="pdf")
    plt.close(fig)


def main() -> int:
    p = argparse.ArgumentParser(
        description="Kramers-Kronig causality check on a Touchstone S-param.")
    p.add_argument("--input", required=True, metavar="DUT.s2p")
    p.add_argument("--parameter", default="S21",
                   choices=("S11", "S12", "S21", "S22"))
    p.add_argument("--label", default="DUT")
    p.add_argument("--output", required=True, metavar="FILE.pdf")
    args = p.parse_args()

    try:
        freqs, H, _ = read_touchstone(args.input, args.parameter)
    except FileNotFoundError as exc:
        print(f"File not found: {exc.filename}", file=sys.stderr); return 1

    im_recon, re_recon = hilbert_reconstruct(H.real, H.imag)
    res_re = H.real - re_recon
    res_im = H.imag - im_recon
    rms_re = float(np.sqrt(np.mean(res_re**2)))
    rms_im = float(np.sqrt(np.mean(res_im**2)))
    rel_re = rms_re / max(np.std(H.real), 1e-12)
    rel_im = rms_im / max(np.std(H.imag), 1e-12)

    print(f"Kramers-Kronig — {args.label}")
    print(f"  Parameter    : {args.parameter}")
    print(f"  Re residual  : RMS {rms_re:.4e}  (= {rel_re*100:.1f}% of "
          f"signal std)")
    print(f"  Im residual  : RMS {rms_im:.4e}  (= {rel_im*100:.1f}% of "
          f"signal std)")
    if max(rel_re, rel_im) < 0.05:
        print("  Verdict      : CAUSAL — consistent with a passive, "
              "causal DUT")
    elif max(rel_re, rel_im) < 0.2:
        print("  Verdict      : possible calibration error (~5–20%)")
    else:
        print("  Verdict      : NON-CAUSAL — bad cal, active DUT, "
              "or strong noise")

    plot_pdf(freqs, H, im_recon, re_recon, rms_re, rms_im,
             args.parameter, args.label, args.output)
    print(f"  Wrote PDF    → {args.output}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
