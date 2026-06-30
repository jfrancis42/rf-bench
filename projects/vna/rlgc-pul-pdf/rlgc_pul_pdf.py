#!/usr/bin/env python3
"""
rlgc_pul_pdf.py — Per-unit-length R, L, G, C from S-params of two lengths.

For a uniform transmission line, the distributed RLGC parameters
relate to the complex propagation constant γ = α + jβ and the
characteristic impedance Z₀(f) as:

    Z₀ = sqrt((R + jωL) / (G + jωC))
    γ  = sqrt((R + jωL) · (G + jωC))

so given γ and Z₀ at every frequency we can solve for R, L, G, C:

    R + jωL = γ · Z₀
    G + jωC = γ / Z₀

We obtain γ from S-parameters of two known-length samples of the
SAME cable; we obtain Z₀ from a 2-pass open-then-shorted S11
measurement of either sample (same math as `tline-pdf --method
osl-s11`).

Input: two Touchstone .s2p captures of the same cable type at two
different lengths, and (separately) an open/short pair on one
length to get Z₀(f).

Output: PDF panels of R/L/G/C vs frequency, plus a derived
attenuation-and-dispersion summary.

This script is the "deep dive" companion to `../tline-pdf/`. Use that
one when you only need VF and loss; use this one when you need a
full distributed model for SPICE / EM simulation.
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

# Touchstone S2P reader: vector_fit_spice's read_touchstone returns
# only one S-parameter at a time, so we use de-embed's S2P reader to
# get the full matrix instead.
sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parent.parent / "de-embed-pdf"))
from de_embed_pdf import read_s2p as read_s2p_full


def gamma_from_two_lengths(freqs, S_long, S_short, L_long, L_short):
    """
    Extract propagation constant γ from S-parameters of two lengths.

    A classic technique:
      S21_long(f)  ≈ exp(-γ·L_long)
      S21_short(f) ≈ exp(-γ·L_short)
    so
      γ = -ln(S21_long / S21_short) / (L_long - L_short)
    """
    s21_long = S_long[:, 1, 0]
    s21_short = S_short[:, 1, 0]
    safe = np.where(np.abs(s21_short) < 1e-12, 1e-12 + 0j, s21_short)
    ratio = s21_long / safe
    gamma_vec = -np.log(ratio) / (L_long - L_short)
    # Phase unwrap: imag part of γ is β, should grow monotonically
    beta = np.unwrap(gamma_vec.imag)
    alpha = gamma_vec.real
    return alpha + 1j * beta


def z0_from_open_short(freqs, g_open, g_short, Z0_ref=50.0):
    """
    Z₀ = Z_ref · sqrt(Z_open/Z_open_ref · Z_short/Z_short_ref) shortcut.
    Equivalent to sqrt(Z_open · Z_short) where each Z is converted from
    its Γ at port 1.
    """
    eps = 1e-12
    go = np.where(np.abs(1-g_open) < eps, 1-eps+0j, g_open)
    gs = np.where(np.abs(1-g_short) < eps, 1-eps+0j, g_short)
    z_open  = Z0_ref * (1+go)/(1-go)
    z_short = Z0_ref * (1+gs)/(1-gs)
    return np.sqrt(z_open * z_short)


def rlgc_from_gamma_z0(freqs, gamma_vec, z0):
    omega = 2*np.pi*freqs
    R_pjwL = gamma_vec * z0
    G_pjwC = gamma_vec / z0
    R = R_pjwL.real
    L = R_pjwL.imag / omega
    G = G_pjwC.real
    C = G_pjwC.imag / omega
    return R, L, G, C


def plot_pdf(freqs_hz, R, L, G, C, label, output):
    freqs_mhz = freqs_hz/1e6
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    fig, axes = plt.subplots(2, 2, figsize=(11, 8), sharex=True)
    axes[0, 0].plot(freqs_mhz, R, color="#1f77b4"); axes[0, 0].set_title("R (Ω/m)")
    axes[0, 1].plot(freqs_mhz, L*1e9, color="#2ca02c"); axes[0, 1].set_title("L (nH/m)")
    axes[1, 0].plot(freqs_mhz, G*1e6, color="#ff7f0e"); axes[1, 0].set_title("G (µS/m)")
    axes[1, 1].plot(freqs_mhz, C*1e12, color="#d62728"); axes[1, 1].set_title("C (pF/m)")
    for ax in axes.flat:
        ax.set_xlabel("Frequency (MHz)"); ax.grid(True, which="both", alpha=0.35)
    fig.suptitle(f"Per-unit-length RLGC — {label}  •  {ts}", fontsize=10)
    fig.tight_layout(rect=(0, 0, 1, 0.95))
    fig.savefig(output, format="pdf"); plt.close(fig)


def main() -> int:
    p = argparse.ArgumentParser(
        description="Per-unit-length R, L, G, C from two cable lengths.")
    p.add_argument("--long",  required=True, metavar="LONG.s2p",
                   help="Touchstone for the longer cable sample")
    p.add_argument("--short", required=True, metavar="SHORT.s2p",
                   help="Touchstone for the shorter cable sample")
    p.add_argument("--length-long-m",  type=float, required=True)
    p.add_argument("--length-short-m", type=float, required=True)
    p.add_argument("--z0-open",  required=True, metavar="OPEN.s2p",
                   help="Touchstone of long-sample, far-end OPEN, for Z₀")
    p.add_argument("--z0-short", required=True, metavar="SHORT.s2p",
                   help="Touchstone of long-sample, far-end SHORT, for Z₀")
    p.add_argument("--label", default="line")
    p.add_argument("--output", required=True, metavar="FILE.pdf")
    args = p.parse_args()

    if args.length_long_m <= args.length_short_m:
        print("Error: --length-long-m must exceed --length-short-m",
              file=sys.stderr); return 1

    f_l, S_l, _, _ = read_s2p_full(args.long)
    f_s, S_s, _, _ = read_s2p_full(args.short)
    if not np.allclose(f_l, f_s):
        print("Error: frequency arrays must match across all four .s2p files",
              file=sys.stderr); return 1

    gamma_vec = gamma_from_two_lengths(f_l, S_l, S_s,
                                       args.length_long_m,
                                       args.length_short_m)

    # Read open/short captures
    f_o, S_o, _, _ = read_s2p_full(args.z0_open)
    f_sh, S_sh, _, _ = read_s2p_full(args.z0_short)
    if not (np.allclose(f_o, f_l) and np.allclose(f_sh, f_l)):
        print("Error: z0 open/short freq arrays must also match",
              file=sys.stderr); return 1
    z0_vec = z0_from_open_short(f_l, S_o[:, 0, 0], S_sh[:, 0, 0])

    R, L, G, C = rlgc_from_gamma_z0(f_l, gamma_vec, z0_vec)

    print(f"RLGC PUL — {args.label}")
    print(f"  Sweep        : {f_l[0]/1e6:.3f} – {f_l[-1]/1e6:.3f} MHz")
    print(f"  R (median)   : {float(np.median(R)):.4f} Ω/m")
    print(f"  L (median)   : {float(np.median(L))*1e9:.3f} nH/m")
    print(f"  G (median)   : {float(np.median(G))*1e6:.3f} µS/m")
    print(f"  C (median)   : {float(np.median(C))*1e12:.3f} pF/m")
    plot_pdf(f_l, R, L, G, C, args.label, args.output)
    print(f"  Wrote PDF    → {args.output}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
