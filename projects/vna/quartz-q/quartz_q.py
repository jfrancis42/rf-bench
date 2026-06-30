#!/usr/bin/env python3
"""
quartz_q.py — Focused S21 transmission Q for a quartz crystal.

`../crystal-bvd-pdf/` does a full BVD fit (Lm/Cm/Rm/C0/Qm) and
needs a wide-enough sweep to identify both series and parallel
resonance. This one is simpler:

  - Sweeps S21 narrowly around the user's `--estimate` series
    resonance.
  - Reports the loaded Q (3-dB BW method) — that's it.
  - Output: PDF with |S21| trace and Q annotation.

For batch sorting crystals where you only care about Q for filter
design (and not Lm / Cm), this is faster than the full BVD fit.
"""

from __future__ import annotations
import warnings
warnings.filterwarnings("ignore", message="Unable to import Axes3D")
import argparse, sys
from datetime import datetime
import matplotlib; matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np


def open_vna(args):
    if args.vna == "nanovna":
        from rf_bench.nanovna import NanoVNA
        return NanoVNA(port=args.port)
    from rf_bench.hp import HP8712B
    return HP8712B(host=args.host)


def measure_s21(vna, lo, hi, points, averaging):
    vna.setup_sweep(lo, hi, points)
    vna.set_parameter("S21")
    vna.single_sweep()
    f = vna.get_frequencies()
    s21 = vna.average_s_data(averaging) if averaging > 1 else vna.get_s_data()
    return f, s21


def q_3db(f, mag):
    mag_db = 20*np.log10(np.clip(mag, 1e-12, None))
    i_pk = int(np.argmax(mag_db))
    peak = mag_db[i_pk]; thresh = peak - 3
    i_lo = i_pk; i_hi = i_pk
    while i_lo > 0 and mag_db[i_lo] >= thresh: i_lo -= 1
    while i_hi < len(mag_db)-1 and mag_db[i_hi] >= thresh: i_hi += 1
    def _interp(i, di):
        x0,x1=f[i],f[i+di]; y0,y1=mag_db[i],mag_db[i+di]
        return float(x0) if y1==y0 else float(x0+(thresh-y0)*(x1-x0)/(y1-y0))
    f_lo = _interp(i_lo, +1); f_hi = _interp(i_hi-1, +1)
    bw = f_hi - f_lo
    if bw <= 0: return None, float(f[i_pk]), None
    return float(f[i_pk]/bw), float(f[i_pk]), float(bw)


def main() -> int:
    p = argparse.ArgumentParser(description="Crystal Q from S21 transmission.")
    p.add_argument("--vna", choices=("nanovna","hp"), default="nanovna")
    p.add_argument("--port", default="/dev/ttyACM1")
    p.add_argument("--host", default="10.1.1.70")
    p.add_argument("--estimate", type=float, required=True, metavar="MHZ")
    p.add_argument("--span-ppm", type=float, default=500.0,
                   help="Sweep span in PPM (default 500 = ±250 ppm).")
    p.add_argument("--points", type=int, default=401)
    p.add_argument("--average", type=int, default=8,
                   help="Higher default than usual; Q matters.")
    p.add_argument("--label", default="crystal")
    p.add_argument("--output", required=True, metavar="FILE.pdf")
    args = p.parse_args()

    fs_est = args.estimate * 1e6
    half = fs_est * args.span_ppm * 1e-6 / 2
    vna = open_vna(args)
    try:
        f, s21 = measure_s21(vna, fs_est-half, fs_est+half,
                             args.points, args.average)
    finally:
        try: vna.close()
        except Exception: pass

    mag = np.abs(s21)
    Q, f0, bw = q_3db(f, mag)
    print(f"Quartz Q — {args.label}")
    if Q is None:
        print("  Q extraction failed (sweep probably too narrow or noisy)")
        return 1
    print(f"  f0           : {f0/1e3:.4f} kHz")
    print(f"  BW3dB        : {bw:.2f} Hz")
    print(f"  Q (loaded)   : {Q:.0f}")
    # PDF
    fig, ax = plt.subplots(figsize=(11, 6.5))
    f_khz = f/1e3
    ax.plot(f_khz, 20*np.log10(np.clip(mag, 1e-12, None)),
            color="#1f77b4", linewidth=1.3)
    ax.axvline(f0/1e3, color="green", linestyle="--", linewidth=0.8,
               label=f"f0 = {f0/1e3:.4f} kHz")
    ax.set_xlabel("Frequency (kHz)")
    ax.set_ylabel("|S21| (dB)")
    ax.grid(True, alpha=0.35); ax.legend(loc="lower right", fontsize=9)
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    ax.set_title(f"Quartz Q — {args.label}\n"
                 f"BW₃dB = {bw:.2f} Hz, Q = {Q:.0f}\n{ts}", fontsize=10)
    fig.tight_layout(); fig.savefig(args.output, format="pdf"); plt.close(fig)
    print(f"  Wrote PDF    → {args.output}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
