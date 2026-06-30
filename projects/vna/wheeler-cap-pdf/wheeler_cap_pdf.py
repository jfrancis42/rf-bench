#!/usr/bin/env python3
"""
wheeler_cap_pdf.py — Antenna radiation efficiency via Wheeler-cap method.

The Wheeler cap method separates an antenna's *radiation* resistance
from its *ohmic* (loss) resistance:

  1. Measure the antenna's Q in free space:   Q_free   = ω₀ / Δω_free
  2. Surround the antenna with a tight conducting cap that suppresses
     radiation but preserves the near-field; measure Q again:
                                                Q_cap    = ω₀ / Δω_cap
  3. Radiation efficiency:
        η = 1 − (Q_free / Q_cap)              (when Q_cap < Q_free)

The cap shorts out the radiation resistance, leaving only ohmic
losses → lower total resistance → higher Q. The ratio of Q's gives
how much of the original resistance was radiation (= the useful part).

This script takes two Touchstone .s1p / .s2p captures of the antenna
S11 (one in free space, one with the Wheeler cap installed) and:

  - locates the resonance in each (X = 0 crossing or |Γ| minimum)
  - computes Q each via the 3 dB bandwidth method on |S11|
  - reports radiation efficiency η

Fixture
-------
The Wheeler cap is just a conducting box / can / sphere large enough
that it doesn't touch the antenna but small enough that there's no
room for far-field radiation. Empirically: cap diameter ≤ λ/(2π).

For HF antennas this means physically large caps (5–10 m for an 80 m
antenna). Practical only for VHF/UHF and small electrically-short
antennas. The classic test is for short mobile antennas (102" whips,
short helicals).
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


def q_from_s11(freqs, s11):
    """3-dB bandwidth Q from |S11| dip."""
    mag_db = 20*np.log10(np.clip(np.abs(s11), 1e-12, None))
    i_pk = int(np.argmin(mag_db))   # dip = most-negative |S11| in dB
    peak = mag_db[i_pk]
    thresh = peak + 3.0
    i_lo, i_hi = i_pk, i_pk
    while i_lo > 0 and mag_db[i_lo] <= thresh: i_lo -= 1
    while i_hi < len(mag_db)-1 and mag_db[i_hi] <= thresh: i_hi += 1
    f0 = freqs[i_pk]
    def _interp(i, di):
        x0, x1 = freqs[i], freqs[i+di]
        y0, y1 = mag_db[i], mag_db[i+di]
        if y1 == y0: return float(x0)
        return float(x0 + (thresh-y0)*(x1-x0)/(y1-y0))
    try:
        f_lo = _interp(i_lo, +1); f_hi = _interp(i_hi-1, +1)
        bw = f_hi - f_lo
        if bw <= 0: raise ValueError
        return float(f0/bw), float(f0)
    except Exception:
        return None, float(f0)


def plot_pdf(freqs_free, s11_free, freqs_cap, s11_cap,
             q_free, q_cap, f0, eff, label, output):
    f_mhz_f = freqs_free/1e6
    f_mhz_c = freqs_cap/1e6
    fig, ax = plt.subplots(figsize=(11, 6.5))
    ax.plot(f_mhz_f, 20*np.log10(np.clip(np.abs(s11_free), 1e-12, None)),
            color="#1f77b4", linewidth=1.4,
            label=f"free space  Q={q_free:.0f}" if q_free else "free space")
    ax.plot(f_mhz_c, 20*np.log10(np.clip(np.abs(s11_cap), 1e-12, None)),
            color="#d62728", linewidth=1.4,
            label=f"with cap    Q={q_cap:.0f}" if q_cap else "with cap")
    ax.set_xlabel("Frequency (MHz)")
    ax.set_ylabel("|S11| (dB)")
    ax.grid(True, alpha=0.35)
    ax.legend(loc="upper right", fontsize=9)
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    eff_str = (f"radiation efficiency η = {eff*100:.1f} %"
               if eff is not None else "η: not computable")
    ax.set_title(f"Wheeler-cap efficiency — {label}\n"
                 f"f₀ ≈ {f0/1e6:.4f} MHz   •   {eff_str}\n"
                 f"{ts}", fontsize=10)
    fig.tight_layout(); fig.savefig(output, format="pdf"); plt.close(fig)


def main() -> int:
    p = argparse.ArgumentParser(
        description="Wheeler-cap antenna efficiency from two .s1p / .s2p.")
    p.add_argument("--free-space", required=True, metavar="FREE.s2p",
                   help="Touchstone of the antenna in free space.")
    p.add_argument("--with-cap",  required=True, metavar="CAP.s2p",
                   help="Touchstone of the antenna inside the Wheeler cap.")
    p.add_argument("--label", default="antenna")
    p.add_argument("--output", required=True, metavar="FILE.pdf")
    args = p.parse_args()

    try:
        f_free, s11_free, _ = read_touchstone(args.free_space, "S11")
        f_cap, s11_cap, _   = read_touchstone(args.with_cap, "S11")
    except FileNotFoundError as exc:
        print(f"File not found: {exc.filename}", file=sys.stderr); return 1

    q_free, f0_free = q_from_s11(f_free, s11_free)
    q_cap, f0_cap   = q_from_s11(f_cap, s11_cap)
    f0 = f0_free or f0_cap

    if q_free and q_cap and q_cap > q_free:
        eff = 1.0 - (q_free / q_cap)
    elif q_free and q_cap and q_cap == q_free:
        eff = 0.0
    else:
        eff = None

    print(f"Wheeler-cap — {args.label}")
    print(f"  Q free        : "
          + (f"{q_free:.0f}" if q_free else "extraction failed"))
    print(f"  Q with cap    : "
          + (f"{q_cap:.0f}" if q_cap else "extraction failed"))
    if eff is not None:
        print(f"  Efficiency η  : {eff*100:.1f} %")
    else:
        print("  Efficiency η  : not computable "
              "(check resonance alignment and cap size)")

    plot_pdf(f_free, s11_free, f_cap, s11_cap,
             q_free, q_cap, f0, eff, args.label, args.output)
    print(f"  Wrote PDF     → {args.output}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
