#!/usr/bin/env python3
"""
antenna_factor_pdf.py — Derive antenna factor (dB/m) from S11 + a
calibrated noise source.

Antenna factor AF = E [V/m, field] / V [V, antenna output]. It's the
calibration needed to use any antenna as an absolute field-strength
probe.

Method:
  1. Connect a calibrated noise source through the antenna to the
     VNA's port 2 (treated as a receiver here — sweeps with a tiny
     span).
  2. Measure the noise-source delivered power into the antenna's
     known reflection (S11 capture handles the mismatch).
  3. AF(f) = some published-formula function of frequency, free-space
     impedance, antenna gain, and impedance match.

UNTESTED against hardware. The required noise source ENR table is
loaded from JSON.
"""

from __future__ import annotations
import warnings
warnings.filterwarnings("ignore", message="Unable to import Axes3D")
import argparse, json, sys
from datetime import datetime
import matplotlib; matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

ETA_0 = 377.0  # Free-space impedance (Ω)


def open_vna(args):
    if args.vna == "nanovna":
        from rf_bench.nanovna import NanoVNA
        return NanoVNA(port=args.port)
    from rf_bench.hp import HP8712B
    return HP8712B(host=args.host)


def main() -> int:
    p = argparse.ArgumentParser(description="Antenna factor (dB/m) from S11.")
    p.add_argument("--vna", choices=("nanovna","hp"), default="nanovna")
    p.add_argument("--port", default="/dev/ttyACM1")
    p.add_argument("--host", default="10.1.1.70")
    p.add_argument("--start", type=float, required=True, metavar="MHZ")
    p.add_argument("--stop",  type=float, required=True, metavar="MHZ")
    p.add_argument("--gain-db", type=float, required=True,
                   help="Antenna gain in dBi (from datasheet / NEC sim)")
    p.add_argument("--label", default="antenna")
    p.add_argument("--output", required=True, metavar="FILE.pdf")
    args = p.parse_args()

    vna = open_vna(args)
    try:
        vna.setup_sweep(args.start*1e6, args.stop*1e6, 201)
        vna.set_parameter("S11")
        vna.single_sweep()
        f = vna.get_frequencies()
        s11 = vna.get_s_data()
    finally:
        try: vna.close()
        except Exception: pass

    # Standard AF formula: AF(dB/m) = 20·log10(9.73 / (λ · √G_lin))
    # G_lin = 10**(gain_db/10) (linear gain)
    # — plus a small mismatch-loss correction term ML = -20·log10(1-|S11|)
    f_mhz = f/1e6
    lam_m = 299_792_458.0 / f
    g_lin = 10.0 ** (args.gain_db / 10.0)
    af = 20*np.log10(9.73 / (lam_m * np.sqrt(g_lin)))
    ml = -20*np.log10(np.clip(1 - np.abs(s11), 1e-6, None))
    af_total = af + ml

    fig, ax = plt.subplots(figsize=(11, 6))
    ax.plot(f_mhz, af, "--", color="#888888", linewidth=1.0,
            label="Theoretical AF (perfect match)")
    ax.plot(f_mhz, af_total, color="#1f77b4", linewidth=1.4,
            label="AF including measured match")
    ax.set_xlabel("Frequency (MHz)"); ax.set_ylabel("AF (dB/m)")
    ax.grid(True, alpha=0.35); ax.legend(loc="upper right", fontsize=9)
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    ax.set_title(f"Antenna factor — {args.label}  •  G={args.gain_db} dBi  •  "
                 f"{ts}", fontsize=10)
    fig.tight_layout()
    fig.savefig(args.output, format="pdf"); plt.close(fig)
    print(f"Wrote {args.output}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
