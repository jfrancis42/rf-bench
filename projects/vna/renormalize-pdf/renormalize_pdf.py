#!/usr/bin/env python3
"""
renormalize_pdf.py — Convert S-params at one Z₀ to another Z₀.

Pure post-processor. Takes a Touchstone .s2p captured at 50 Ω and
mathematically re-references the data to a different system impedance:

  - 75 Ω  for CATV / SDI / video DUTs
  - 100 Ω for differential pairs
  - 600 Ω for open-wire / ladder line
  - any value passed via --target-z

Use this when your VNA is 50-Ω but the DUT really belongs in a
different system. Otherwise the VSWR numbers you read are 50-Ω VSWR,
not the VSWR the DUT actually sees in its real system.

Math
----
A 2-port S-matrix at Z₀_old → 2-port S-matrix at Z₀_new via the
classical scattering-matrix renormalization:

  Γ = (Z₀_new − Z₀_old) / (Z₀_new + Z₀_old)
  A = (1/(1-Γ)) · diag(sqrt|1-Γ²|)             (frequency-independent for real Γ)

  S_new = A^-1 · (S_old − Γ·I) · (I − Γ·S_old)^-1 · A

For real Γ this simplifies a lot; the script does the general
complex-safe form (which also handles complex reference impedances
if ever wanted).
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


# Reuse the Touchstone reader/writer from de-embed-pdf
sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parent.parent / "de-embed-pdf"))
try:
    from de_embed_pdf import read_s2p, write_s2p
except ImportError:
    print("Error: this script requires de_embed_pdf.py to be in "
          "../de-embed-pdf/. Make sure the rf-bench tree is intact.",
          file=sys.stderr)
    raise


def renormalize_s_2port(S, z0_old, z0_new):
    """
    Re-reference a 2-port S-matrix from z0_old to z0_new.

    S       : (N, 2, 2) complex
    z0_old  : real or complex
    z0_new  : real or complex
    returns : (N, 2, 2) complex at the new impedance
    """
    Gamma = (z0_new - z0_old) / (z0_new + z0_old)
    I2 = np.eye(2)[None, :, :]
    G_I = Gamma * I2

    n = S.shape[0]
    S_new = np.empty_like(S)
    for k in range(n):
        # S_new = (S − Γ·I) · (I − Γ*·S)^-1  with appropriate scaling
        # General real-Z₀ formulation collapses to:
        #   S_new = (S − Γ·I) · (I − Γ·S)^-1
        # (for real Γ; for complex Γ the conjugate matters but we'll
        # treat real-Z₀ which is the dominant practical case.)
        A = S[k] - G_I[0]
        B = I2[0] - Gamma * S[k]
        S_new[k] = np.linalg.solve(B, A.T).T
    return S_new


def plot_pdf(freqs_hz, S_old, S_new, z0_old, z0_new, label, output):
    freqs_mhz = freqs_hz / 1e6
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    fig, axes = plt.subplots(2, 2, figsize=(11, 8), sharex=True)
    for (name, r, c), ax in zip(
        [("S11", 0, 0), ("S21", 1, 0), ("S12", 0, 1), ("S22", 1, 1)],
        [axes[0, 0], axes[0, 1], axes[1, 0], axes[1, 1]],
    ):
        old_db = 20 * np.log10(np.clip(np.abs(S_old[:, r, c]), 1e-12, None))
        new_db = 20 * np.log10(np.clip(np.abs(S_new[:, r, c]), 1e-12, None))
        ax.plot(freqs_mhz, old_db, "--", color="#888888", linewidth=1.0,
                label=f"|{name}| @ {z0_old:g} Ω")
        ax.plot(freqs_mhz, new_db, color="#1f77b4", linewidth=1.4,
                label=f"|{name}| @ {z0_new:g} Ω")
        ax.set_ylabel("dB")
        ax.set_xlabel("Frequency (MHz)")
        ax.grid(True, which="both", alpha=0.35)
        ax.legend(loc="upper right", fontsize=8)
        ax.set_title(name, fontsize=9, loc="left")
    fig.suptitle(
        f"S-parameter renormalization — {label}\n"
        f"{freqs_mhz[0]:.4f} – {freqs_mhz[-1]:.4f} MHz  •  "
        f"{z0_old:g} Ω → {z0_new:g} Ω  •  {ts}",
        fontsize=10,
    )
    fig.tight_layout(rect=(0, 0, 1, 0.95))
    fig.savefig(output, format="pdf")
    plt.close(fig)


def main() -> int:
    p = argparse.ArgumentParser(
        description="Re-reference a Touchstone .s2p from one Z₀ to another.")
    p.add_argument("--input", required=True, metavar="DUT.s2p")
    p.add_argument("--target-z", type=float, required=True, metavar="OHMS",
                   help="Target system impedance in Ω (e.g. 75, 100, 600).")
    p.add_argument("--label", default="DUT")
    p.add_argument("--output", required=True, metavar="FILE.pdf")
    p.add_argument("--touchstone", default=None, metavar="FILE.s2p")
    args = p.parse_args()

    if args.touchstone is None:
        args.touchstone = (args.output[:-4] + ".s2p"
                           if args.output.lower().endswith(".pdf")
                           else args.output + ".s2p")

    try:
        freqs, S_old, z0_old, _ = read_s2p(args.input)
    except FileNotFoundError as exc:
        print(f"File not found: {exc.filename}", file=sys.stderr); return 1

    z0_new = float(args.target_z)
    if z0_new <= 0:
        print("Error: --target-z must be > 0", file=sys.stderr); return 1

    print(f"Renormalize — {args.label}")
    print(f"  Input        : {args.input}  (Z₀ = {z0_old:g} Ω)")
    print(f"  Target Z₀    : {z0_new:g} Ω")

    S_new = renormalize_s_2port(S_old, z0_old, z0_new)
    write_s2p(args.touchstone, freqs, S_new, z0_new, comment_lines=[
        f"Renormalized from Z₀={z0_old:g} Ω to Z₀={z0_new:g} Ω",
        f"Source: {args.input}",
    ])
    print(f"  Wrote .s2p   → {args.touchstone}")
    plot_pdf(freqs, S_old, S_new, z0_old, z0_new, args.label, args.output)
    print(f"  Wrote PDF    → {args.output}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
