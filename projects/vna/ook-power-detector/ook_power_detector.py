#!/usr/bin/env python3
"""
ook_power_detector.py — Use the VNA as a single-frequency power detector.

A VNA's S21 magnitude is a relative power measurement. If you fix
the sweep to ONE frequency and just sample S21 repeatedly, you've
got a synchronous power detector at that frequency — good for OOK
link tests, transmitter-keying envelopes, AGC behaviour, etc.

This script:

  1. Tunes the VNA to a 2-point sweep around the user's frequency
     (the NanoVNA can't do a 1-point sweep, but 2-point is fine).
  2. Repeatedly captures S21, time-stamps each sample, logs to CSV.
  3. Optionally plots a real-time envelope or just dumps the CSV.

For pulsed RF the time resolution is the sweep cycle, ~50–100 ms on
the NanoVNA. The HP 8712B can do faster single-point CW reads but
this driver doesn't expose that mode yet.
"""

from __future__ import annotations
import warnings
warnings.filterwarnings("ignore", message="Unable to import Axes3D")
import argparse, csv, sys, time
from datetime import datetime
from pathlib import Path
import matplotlib; matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np


def open_vna(args):
    if args.vna == "nanovna":
        from rf_bench.nanovna import NanoVNA
        return NanoVNA(port=args.port)
    from rf_bench.hp import HP8712B
    return HP8712B(host=args.host)


def main() -> int:
    p = argparse.ArgumentParser(
        description="VNA as a single-frequency power detector.")
    p.add_argument("--vna", choices=("nanovna","hp"), default="nanovna")
    p.add_argument("--port", default="/dev/ttyACM1")
    p.add_argument("--host", default="10.1.1.70")
    p.add_argument("--freq", type=float, required=True, metavar="MHZ")
    p.add_argument("--span", type=float, default=0.001, metavar="MHZ",
                   help="Tiny span around --freq (default 1 kHz).")
    p.add_argument("--duration", type=float, default=10.0,
                   help="How long to sample, in seconds (default 10).")
    p.add_argument("--log", required=True, metavar="FILE.csv")
    p.add_argument("--plot", default=None, metavar="FILE.pdf",
                   help="Optional envelope-vs-time PDF.")
    args = p.parse_args()

    vna = open_vna(args)
    f0 = args.freq * 1e6
    sp = args.span * 1e6
    try:
        vna.setup_sweep(f0 - sp/2, f0 + sp/2, 2)
        vna.set_parameter("S21")
        rows = []
        t0 = time.monotonic()
        while True:
            vna.single_sweep()
            s21 = vna.get_s_data()
            t = time.monotonic() - t0
            db = float(20*np.log10(np.clip(np.abs(s21).mean(), 1e-12, None)))
            rows.append((t, db, float(np.abs(s21).mean()), float(np.angle(s21).mean())))
            if t >= args.duration: break
    finally:
        try: vna.close()
        except Exception: pass

    with open(args.log, "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["t_s", "s21_db", "s21_mag", "s21_phase_rad"])
        for r in rows: w.writerow(r)
    print(f"Wrote {args.log}  ({len(rows)} samples)")

    if args.plot:
        t = np.array([r[0] for r in rows])
        db = np.array([r[1] for r in rows])
        fig, ax = plt.subplots(figsize=(11, 5))
        ax.plot(t, db, color="#1f77b4", linewidth=1.0)
        ax.set_xlabel("Time (s)"); ax.set_ylabel("|S21| (dB)")
        ax.grid(True, alpha=0.35)
        ax.set_title(f"Single-frequency power detector @ {args.freq:.4f} MHz")
        fig.tight_layout()
        fig.savefig(args.plot, format="pdf")
        plt.close(fig)
        print(f"Wrote {args.plot}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
