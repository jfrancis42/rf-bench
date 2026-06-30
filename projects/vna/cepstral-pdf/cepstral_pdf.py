#!/usr/bin/env python3
"""
cepstral_pdf.py — Cepstral analysis of S11 for cable / fixture diagnosis.

The "cepstrum" is the inverse Fourier transform of the log-magnitude
spectrum. For reflection data, discrete reflections become sharp
peaks in the cepstrum while distributed losses appear as a slowly
decaying baseline. Useful when TDR can't separate two closely-spaced
reflections — the cepstrum often resolves them.

Two complementary cepstra are computed:

  - Real cepstrum: IFFT(log |S11(f)|), often called the "power cepstrum"
  - Complex cepstrum: IFFT(log S11(f)), preserves phase information

The X axis ("quefrency") has units of time, just like a TDR plot.
With a known cable VF, the script converts to distance.
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

C0 = 299_792_458.0


def cepstral(freqs_hz, gamma, vf=0.66, interp=4):
    """Compute real and complex cepstra."""
    n = len(freqs_hz)
    # Window to suppress sidelobes
    w = np.hanning(n)
    g = gamma * w
    # Hermitian-symmetric spectrum from one-sided sweep
    full_len = max(2*n, 64) * interp
    spectrum = np.zeros(full_len, dtype=np.complex128)
    spectrum[:n] = g
    spectrum[full_len-n+1:full_len] = np.conj(g[1:][::-1])

    log_mag = np.log(np.clip(np.abs(spectrum), 1e-12, None))
    log_complex = np.log(spectrum + 1e-12 + 1e-12j)  # branch cut concerns; OK for diag

    real_cep = np.fft.ifft(log_mag).real
    complex_cep_abs = np.abs(np.fft.ifft(log_complex))

    df = float(freqs_hz[1] - freqs_hz[0])
    dt = 1.0 / (df * full_len)
    t = np.arange(full_len) * dt
    half = full_len // 2
    distance_m = vf * C0 * t[:half] / 2.0
    return distance_m, real_cep[:half], complex_cep_abs[:half]


def plot_pdf(distance_m, real_cep, complex_cep, vf, feet, label, output):
    if feet:
        x = distance_m * 3.28084; unit = "ft"
    else:
        x = distance_m; unit = "m"
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(11, 8), sharex=True)
    ax1.plot(x, real_cep, color="#1f77b4", linewidth=1.0)
    ax1.set_ylabel("Real cepstrum")
    ax1.grid(True, alpha=0.35)
    ax2.plot(x, complex_cep, color="#d62728", linewidth=1.0)
    ax2.set_ylabel("|Complex cepstrum|")
    ax2.set_xlabel(f"Quefrency  ({unit} one-way at vf={vf})")
    ax2.grid(True, alpha=0.35)
    # Annotate dominant peaks past first 1 m
    mask = x > (1.0 if not feet else 1.0/3.28084 * 3.28084)
    for ax, c, color in ((ax1, real_cep, "blue"), (ax2, complex_cep, "red")):
        if not np.any(mask): continue
        seg = c[mask]; segx = x[mask]
        i = int(np.argmax(np.abs(seg)))
        ax.axvline(segx[i], color=color, linestyle="--", linewidth=0.7,
                   alpha=0.6, label=f"peak @ {segx[i]:.3f} {unit}")
        ax.legend(loc="upper right", fontsize=8)
    fig.suptitle(f"Cepstral analysis — {label}\nvf={vf}  •  {ts}", fontsize=10)
    fig.tight_layout(rect=(0, 0, 1, 0.95))
    fig.savefig(output, format="pdf"); plt.close(fig)


def main() -> int:
    p = argparse.ArgumentParser(description="Cepstral analysis of S11.")
    p.add_argument("--input", required=True, metavar="DUT.s2p")
    p.add_argument("--parameter", default="S11",
                   choices=("S11", "S12", "S21", "S22"))
    p.add_argument("--vf", type=float, default=0.66)
    p.add_argument("--feet", action="store_true")
    p.add_argument("--interp", type=int, default=4)
    p.add_argument("--label", default="DUT")
    p.add_argument("--output", required=True, metavar="FILE.pdf")
    args = p.parse_args()
    try:
        freqs, H, _ = read_touchstone(args.input, args.parameter)
    except FileNotFoundError as exc:
        print(f"File not found: {exc.filename}", file=sys.stderr); return 1
    d, real_cep, complex_cep = cepstral(freqs, H, args.vf, args.interp)
    print(f"Cepstral — {args.label}")
    print(f"  Trace        : {args.parameter}")
    print(f"  Sweep        : {freqs[0]/1e6:.3f} – {freqs[-1]/1e6:.3f} MHz")
    print(f"  vf           : {args.vf}")
    plot_pdf(d, real_cep, complex_cep, args.vf, args.feet, args.label,
             args.output)
    print(f"  Wrote PDF    → {args.output}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
