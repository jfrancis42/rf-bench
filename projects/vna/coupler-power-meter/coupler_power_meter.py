#!/usr/bin/env python3
"""
coupler_power_meter.py — Absolute power via VNA + directional coupler + SSA xref.

Method:
  1. Drive SDG into a directional coupler.
  2. Coupled port goes to SSA (absolute dBm via marker).
  3. Through port goes to VNA's S21 input (relative dB).
  4. Sweep across the band; build per-frequency offset table.
  5. Save as JSON; downstream projects load it and convert VNA S21
     to absolute dBm.

Companion to `../vs-ssa-cross-check/`, but uses an explicit coupler
factor and reports the through-arm calibrated power directly. Useful
when you need to drive a DUT at a known absolute level via the VNA's
S21 reference signal.

UNTESTED.
"""

from __future__ import annotations
import warnings
warnings.filterwarnings("ignore", message="Unable to import Axes3D")
import argparse, json, socket, sys, time
from datetime import datetime
import numpy as np


def open_vna(args):
    if args.vna == "nanovna":
        from rf_bench.nanovna import NanoVNA
        return NanoVNA(port=args.port)
    from rf_bench.hp import HP8712B
    return HP8712B(host=args.host)


def ssa_marker_at(host, port, f_hz, span=5000, rbw=100):
    with socket.socket() as s:
        s.connect((host, port)); s.settimeout(5.0)
        def cmd(c): s.sendall((c+"\n").encode())
        def qry(c):
            cmd(c); return s.recv(1024).decode().strip()
        cmd(f":FREQ:CENT {f_hz}"); cmd(f":FREQ:SPAN {span}")
        cmd(f":BAND {rbw}"); cmd(":CALC:MARK1:STAT ON")
        cmd(":CALC:MARK1:MAX"); time.sleep(0.5)
        return float(qry(":CALC:MARK1:Y?"))


def main() -> int:
    p = argparse.ArgumentParser(
        description="Build absolute-power calibration via coupler + SSA xref.")
    p.add_argument("--vna", choices=("nanovna","hp"), default="nanovna")
    p.add_argument("--port", default="/dev/ttyACM1")
    p.add_argument("--host", default="10.1.1.70")
    p.add_argument("--ssa-host", required=True)
    p.add_argument("--ssa-port", type=int, default=5025)
    p.add_argument("--coupler-db", type=float, required=True,
                   help="Coupler coupling factor (e.g. 10 for 10-dB coupler)")
    p.add_argument("--start", type=float, required=True, metavar="MHZ")
    p.add_argument("--stop",  type=float, required=True, metavar="MHZ")
    p.add_argument("--n", type=int, default=21)
    p.add_argument("--output", required=True, metavar="FILE.json")
    args = p.parse_args()

    vna = open_vna(args)
    freqs = np.linspace(args.start*1e6, args.stop*1e6, args.n)
    rows = []
    try:
        for f in freqs:
            print(f"  {f/1e6:.4f} MHz…")
            vna.setup_sweep(f-1e3, f+1e3, 2)
            vna.set_parameter("S21")
            vna.single_sweep()
            s21_db = float(20*np.log10(np.abs(vna.get_s_data()).mean()))
            try:
                ssa_dbm = ssa_marker_at(args.ssa_host, args.ssa_port, f)
            except Exception as exc:
                print(f"    SSA error: {exc}"); ssa_dbm = float("nan")
            through_dbm = ssa_dbm + args.coupler_db
            # offset(f) = through_dbm − s21_db   (so absolute = s21_db + offset)
            offset = through_dbm - s21_db
            rows.append({"f_hz": float(f), "vna_db": s21_db,
                         "ssa_dbm": ssa_dbm, "through_dbm": through_dbm,
                         "offset_db": offset})
    finally:
        try: vna.close()
        except Exception: pass

    with open(args.output, "w") as fh:
        json.dump({"coupler_db": args.coupler_db,
                   "timestamp": datetime.now().isoformat(timespec="seconds"),
                   "points": rows}, fh, indent=2)
    print(f"Wrote {args.output}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
