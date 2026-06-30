#!/usr/bin/env python3
"""
q_cross_check.py — Three Q methods compared side-by-side.

A resonator's Q can be extracted three different ways:

  1. **3 dB bandwidth method:** Q = f0 / BW3dB on |S11| or |S21|
  2. **Lorentzian fit:** least-squares fit of A / (1 + ((f-f0)/Γ)^2)
  3. **Q-circle method:** fit a circle to Γ(f) on the Smith chart and
     extract Q from the half-power arc.

For high-Q resonators measured cleanly, all three agree. Where they
disagree, the measurement is suspect. This script implements all
three and reports them side-by-side with the disagreement quantified.

Pure post-processor on a Touchstone .s2p.
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


def q_bw3db(freqs_hz, mag):
    """Method 1: 3 dB bandwidth on a magnitude trace."""
    mag_db = 20*np.log10(np.clip(mag, 1e-12, None))
    i_pk = int(np.argmax(mag_db))
    peak = mag_db[i_pk]
    thresh = peak - 3.0
    # Walk left/right
    i_lo = i_pk
    while i_lo > 0 and mag_db[i_lo] >= thresh: i_lo -= 1
    i_hi = i_pk
    while i_hi < len(mag_db)-1 and mag_db[i_hi] >= thresh: i_hi += 1
    if i_lo == 0 or i_hi == len(mag_db)-1:
        return None, None, None
    # Linear-interp the bandwidth edges
    def _interp(i, di):
        x0, x1 = freqs_hz[i], freqs_hz[i+di]
        y0, y1 = mag_db[i],   mag_db[i+di]
        if y1==y0: return float(x0)
        return float(x0 + (thresh-y0)*(x1-x0)/(y1-y0))
    f_lo = _interp(i_lo, +1)
    f_hi = _interp(i_hi-1, +1)
    f0 = freqs_hz[i_pk]
    bw = f_hi - f_lo
    if bw <= 0: return None, None, None
    return f0/bw, f0, bw


def q_lorentzian(freqs_hz, mag):
    """Method 2: fit |H(f)|^2 = A / (1 + ((f-f0)/gamma)^2)."""
    from scipy.optimize import curve_fit
    p = mag**2
    i_pk = int(np.argmax(p))
    def _lor(f, A, f0, gamma):
        return A / (1.0 + ((f - f0)/gamma)**2)
    p0 = [p.max(), freqs_hz[i_pk], (freqs_hz[-1]-freqs_hz[0]) / 50.0]
    try:
        popt, _ = curve_fit(_lor, freqs_hz, p, p0=p0, maxfev=20000)
        A, f0, gamma = popt
        if gamma <= 0: return None, None, None
        return f0/(2*gamma), f0, 2*gamma
    except Exception:
        return None, None, None


def q_smith_circle(freqs_hz, gamma_arr):
    """
    Method 3: fit a least-squares circle to Γ in the complex plane,
    derive Q from the angular sweep range across the circle.
    """
    # Algebraic circle fit: minimize Σ (xi² + yi² - 2axi - 2byi - c)²
    x, y = gamma_arr.real, gamma_arr.imag
    A = np.column_stack([2*x, 2*y, np.ones_like(x)])
    b = x**2 + y**2
    sol, *_ = np.linalg.lstsq(A, b, rcond=None)
    cx, cy, c0 = sol
    R = np.sqrt(c0 + cx**2 + cy**2)
    if R <= 0: return None, None, None
    # Find the half-circle "matched" arc — Q is the slope of the
    # phase d∠Γ/df at the resonant frequency divided by 2.
    # Use the slope around the closest-to-center sample.
    centred = gamma_arr - (cx + 1j*cy)
    phases = np.unwrap(np.angle(centred))
    # Linear fit phase vs freq, take slope
    slope = np.polyfit(freqs_hz, phases, 1)[0]
    if slope == 0: return None, None, None
    # Q = f0 · |dφ/df| / 2 for a 1-port reflection on the Smith chart
    i_pk = int(np.argmax(np.abs(centred)))
    f0 = float(freqs_hz[i_pk])
    Q = abs(f0 * slope / 2.0)
    return Q, f0, None


def plot_pdf(freqs_hz, parameter, h, results, label, output):
    freqs_mhz = freqs_hz / 1e6
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    fig, axes = plt.subplots(2, 2, figsize=(11, 8))
    mag_db = 20*np.log10(np.clip(np.abs(h), 1e-12, None))
    axes[0, 0].plot(freqs_mhz, mag_db, color="#1f77b4", linewidth=1.4)
    axes[0, 0].set_xlabel("Frequency (MHz)")
    axes[0, 0].set_ylabel(f"|{parameter}| (dB)")
    axes[0, 0].set_title("Magnitude")
    axes[0, 0].grid(True, alpha=0.35)
    # Mark f0 from method 1 if available
    for name, color in (("bw3db", "green"), ("lorentzian", "orange"),
                        ("smith", "red")):
        r = results.get(name)
        if r and r[1] is not None:
            axes[0, 0].axvline(r[1]/1e6, color=color, linestyle="--",
                               linewidth=0.8, alpha=0.7,
                               label=f"{name} f0")
    axes[0, 0].legend(loc="lower right", fontsize=7)

    # Smith chart
    axes[0, 1].plot(h.real, h.imag, color="#1f77b4", linewidth=1.2)
    theta = np.linspace(0, 2*np.pi, 256)
    axes[0, 1].plot(np.cos(theta), np.sin(theta), "k-", linewidth=0.6)
    axes[0, 1].axhline(0, color="#aaaaaa", linewidth=0.4)
    axes[0, 1].axvline(0, color="#aaaaaa", linewidth=0.4)
    axes[0, 1].set_xlim(-1.1, 1.1); axes[0, 1].set_ylim(-1.1, 1.1)
    axes[0, 1].set_aspect("equal")
    axes[0, 1].set_title(f"Γ trajectory ({parameter})")
    axes[0, 1].axis("off")

    # Phase
    axes[1, 0].plot(freqs_mhz, np.degrees(np.unwrap(np.angle(h))),
                    color="#9467bd", linewidth=1.2)
    axes[1, 0].set_xlabel("Frequency (MHz)")
    axes[1, 0].set_ylabel(f"∠{parameter} (°, unwrap)")
    axes[1, 0].set_title("Phase")
    axes[1, 0].grid(True, alpha=0.35)

    # Results panel
    axes[1, 1].axis("off")
    lines = ["Q extraction (three methods)", ""]
    for name, descr in (("bw3db", "3 dB BW   "),
                        ("lorentzian", "Lorentzian"),
                        ("smith", "Smith circle")):
        r = results.get(name)
        if r and r[0] is not None:
            f0_str = f"{r[1]/1e6:.4f} MHz" if r[1] is not None else "—"
            lines.append(f"  {descr}: Q = {r[0]:>8.0f}     f0 = {f0_str}")
        else:
            lines.append(f"  {descr}: extraction failed")
    # Disagreement
    qs = [r[0] for r in results.values() if r and r[0] is not None]
    if len(qs) >= 2:
        lines.append("")
        lines.append(f"Spread: max/min = {max(qs)/min(qs):.2f}× ; "
                     f"std/mean = {np.std(qs)/np.mean(qs)*100:.1f}%")
    axes[1, 1].text(0.02, 0.95, "\n".join(lines), va="top", ha="left",
                    fontsize=10, family="monospace",
                    bbox=dict(facecolor="white", edgecolor="#ccc", pad=6))

    fig.suptitle(f"Q-extraction cross-check — {label}  •  {ts}", fontsize=10)
    fig.tight_layout(rect=(0, 0, 1, 0.95))
    fig.savefig(output, format="pdf")
    plt.close(fig)


def main() -> int:
    p = argparse.ArgumentParser(
        description="Three-method Q extraction cross-check from .s2p.")
    p.add_argument("--input", required=True, metavar="DUT.s2p")
    p.add_argument("--parameter", default="S21",
                   choices=("S11", "S12", "S21", "S22"))
    p.add_argument("--label", default="resonator")
    p.add_argument("--output", required=True, metavar="FILE.pdf")
    args = p.parse_args()
    try:
        freqs, H, _ = read_touchstone(args.input, args.parameter)
    except FileNotFoundError as exc:
        print(f"File not found: {exc.filename}", file=sys.stderr); return 1
    mag = np.abs(H)
    results = {
        "bw3db":     q_bw3db(freqs, mag),
        "lorentzian": q_lorentzian(freqs, mag),
        "smith":     q_smith_circle(freqs, H),
    }
    print(f"Q-cross-check — {args.label}")
    for name, r in results.items():
        if r and r[0] is not None:
            f0_str = f"{r[1]/1e6:.4f} MHz" if r[1] is not None else "n/a"
            print(f"  {name:<12s}: Q = {r[0]:.0f}   f0 = {f0_str}")
        else:
            print(f"  {name:<12s}: failed")
    plot_pdf(freqs, args.parameter, H, results, args.label, args.output)
    print(f"  Wrote PDF    → {args.output}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
