#!/usr/bin/env python3
"""
freq_comb_sweep.py — Capture S21 at a discrete frequency comb.

Standard VNA sweeps step linearly. Some measurements only need
discrete tones: WSPR/FT8 channel verification, harmonic mixer
characterization, comb-based receiver test. This script sweeps the
VNA across a list of tones provided in a CSV / YAML file (or auto-
generated as an arithmetic series).

For each comb tooth, captures S21 with a tiny span; outputs a CSV
of (freq, |S21|_dB, ∠S21°).

UNTESTED. Standard VNA workflow; useful when you don't want the
overhead of a fine linear sweep over a band where you only care
about specific tones.
"""

from __future__ import annotations
import warnings
warnings.filterwarnings("ignore", message="Unable to import Axes3D")
import argparse, csv, sys
from datetime import datetime
import numpy as np


def open_vna(args):
    if args.vna == "nanovna":
        from rf_bench.nanovna import NanoVNA
        return NanoVNA(port=args.port)
    from rf_bench.hp import HP8712B
    return HP8712B(host=args.host)


def main() -> int:
    p = argparse.ArgumentParser(
        description="S21 capture at a list of discrete frequencies.")
    p.add_argument("--vna", choices=("nanovna","hp"), default="nanovna")
    p.add_argument("--port", default="/dev/ttyACM1")
    p.add_argument("--host", default="10.1.1.70")
    src = p.add_mutually_exclusive_group(required=True)
    src.add_argument("--freqs-csv", metavar="FILE.csv",
                     help="CSV file with one frequency in MHz per row.")
    src.add_argument("--comb", nargs=3, type=float,
                     metavar=("START_MHZ","STEP_MHZ","N"),
                     help="Arithmetic comb: start, step, count.")
    p.add_argument("--span", type=float, default=0.001, metavar="MHZ",
                   help="Tiny sweep span around each tone (default 1 kHz).")
    p.add_argument("--average", type=int, default=4)
    p.add_argument("--label", default="comb sweep")
    p.add_argument("--output", required=True, metavar="FILE.csv")
    args = p.parse_args()

    if args.freqs_csv:
        with open(args.freqs_csv) as fh:
            tones = []
            for line in fh:
                line = line.strip()
                if not line or line.startswith("#"): continue
                tones.append(float(line.split(",")[0]) * 1e6)
    else:
        start, step, n = args.comb
        tones = [start*1e6 + step*1e6*i for i in range(int(n))]

    vna = open_vna(args)
    rows = []
    try:
        sp = args.span*1e6
        for f in tones:
            vna.setup_sweep(f-sp/2, f+sp/2, 2)
            vna.set_parameter("S21")
            vna.single_sweep()
            s21 = (vna.average_s_data(args.average) if args.average > 1
                   else vna.get_s_data())
            mag = float(np.abs(s21).mean())
            ph = float(np.angle(s21).mean())
            db = 20*np.log10(max(mag, 1e-12))
            print(f"  {f/1e6:9.4f} MHz   {db:+7.2f} dB   {np.degrees(ph):+7.1f}°")
            rows.append((f, db, np.degrees(ph)))
    finally:
        try: vna.close()
        except Exception: pass

    with open(args.output, "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["freq_hz","s21_db","s21_phase_deg"])
        for r in rows: w.writerow(r)
    print(f"Wrote {args.output}  ({len(rows)} tones)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
