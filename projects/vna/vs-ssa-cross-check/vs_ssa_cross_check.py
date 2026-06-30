#!/usr/bin/env python3
"""
vs_ssa_cross_check.py — Cross-cal NanoVNA dBFS → SSA dBm absolute.

The NanoVNA returns relative S21 (a ratio). Many ham measurements
need ABSOLUTE power in dBm. The SSA3032X has calibrated dBm
readings. By driving the same RF path through a directional coupler
to both the SSA and the NanoVNA simultaneously (or sequentially with
identical drive level), we derive a per-frequency offset:

  offset(f) = P_SSA(f) [dBm]  −  20·log10(|S21_NanoVNA(f)|)

Save offset(f) as a CSV. Downstream projects load it and add the
offset to NanoVNA S21 readings to get absolute dBm.

Setup
-----
                ┌── SSA3032X (absolute reference)
                │
  SDG ─── coupler ─── NanoVNA port 2 (calibrated as a relative through arm)
                │
                └── 50-Ω load on unused port

UNTESTED against the real coupler / SSA chain. The SCPI command
forms here follow Siglent's standard SSA syntax; the SDG drive can
be set via any of the existing Siglent driver tools.
"""

from __future__ import annotations
import warnings
warnings.filterwarnings("ignore", message="Unable to import Axes3D")
import argparse, csv, socket, sys, time
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


def query_ssa_at_freq(host, port, freq_hz, span_hz=1e4, rbw_hz=100):
    """Set SSA to span around freq_hz, take a marker reading in dBm."""
    with socket.socket() as s:
        s.connect((host, port)); s.settimeout(5.0)
        def cmd(c): s.sendall((c+"\n").encode())
        def qry(c):
            cmd(c); return s.recv(1024).decode().strip()
        cmd(f":FREQ:CENT {freq_hz}")
        cmd(f":FREQ:SPAN {span_hz}")
        cmd(f":BAND {rbw_hz}")
        cmd(f":CALC:MARK1:STAT ON")
        cmd(f":CALC:MARK1:MAX")
        time.sleep(0.5)
        return float(qry(":CALC:MARK1:Y?"))


def main() -> int:
    p = argparse.ArgumentParser(
        description="VNA-vs-SSA dBm cross-cal trim table.")
    p.add_argument("--vna", choices=("nanovna","hp"), default="nanovna")
    p.add_argument("--port", default="/dev/ttyACM1")
    p.add_argument("--host", default="10.1.1.70")
    p.add_argument("--ssa-host", required=True)
    p.add_argument("--ssa-port", type=int, default=5025)
    p.add_argument("--start", type=float, required=True, metavar="MHZ")
    p.add_argument("--stop",  type=float, required=True, metavar="MHZ")
    p.add_argument("--n", type=int, default=21,
                   help="Number of cal frequencies (default 21).")
    p.add_argument("--output", required=True, metavar="FILE.csv")
    p.add_argument("--plot", default=None, metavar="FILE.pdf")
    args = p.parse_args()

    freqs = np.linspace(args.start*1e6, args.stop*1e6, args.n)
    vna = open_vna(args)
    rows = []
    try:
        for f in freqs:
            print(f"  Cal at {f/1e6:.4f} MHz…")
            # Set a 2-point sweep around this freq, capture S21
            vna.setup_sweep(f-1e3, f+1e3, 2)
            vna.set_parameter("S21")
            vna.single_sweep()
            s21 = vna.get_s_data()
            vna_db = float(20*np.log10(np.abs(s21).mean()))
            # SSA marker
            try:
                ssa_dbm = query_ssa_at_freq(args.ssa_host, args.ssa_port, f)
            except Exception as exc:
                print(f"    SSA query failed: {exc}"); ssa_dbm = float("nan")
            offset = ssa_dbm - vna_db
            rows.append((f, vna_db, ssa_dbm, offset))
    finally:
        try: vna.close()
        except Exception: pass

    with open(args.output, "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["freq_hz","vna_s21_db","ssa_dbm","offset_db"])
        for r in rows: w.writerow(r)
    print(f"Wrote {args.output}")
    if args.plot:
        f_mhz = np.array([r[0] for r in rows])/1e6
        off = np.array([r[3] for r in rows])
        fig, ax = plt.subplots(figsize=(11, 5))
        ax.plot(f_mhz, off, "o-", color="#1f77b4")
        ax.set_xlabel("Frequency (MHz)"); ax.set_ylabel("Offset (dB)")
        ax.grid(True, alpha=0.35)
        ax.set_title("VNA-vs-SSA cross-cal offset"); fig.tight_layout()
        fig.savefig(args.plot, format="pdf"); plt.close(fig)
        print(f"Wrote {args.plot}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
