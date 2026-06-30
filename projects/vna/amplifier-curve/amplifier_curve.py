#!/usr/bin/env python3
"""
amplifier_curve.py — Small-signal S-params of an amplifier vs DC bias.

Steps a Siglent SPD3303X-E across a grid of (Vds, Id) bias points
and at each point captures the amplifier's S-params. Outputs gain
contour PDF and Touchstone files per bias point.

UNTESTED against hardware. Requires the Siglent driver
(rf_bench.siglent.SPD3303X) and a working bias-tee fixture.

Workflow
--------
For each (Vds, Id) point in the grid:
  1. Set SPD3303X channel-1 voltage to Vds.
  2. Wait for current settle; read back actual Id.
  3. Capture S-params via sparams-pdf.
  4. Append (Vds, Id, S21_peak_dB, gain_at_f0) to a CSV.
"""

from __future__ import annotations
import warnings
warnings.filterwarnings("ignore", message="Unable to import Axes3D")
import argparse, csv, subprocess, sys, time
from datetime import datetime
from pathlib import Path
import numpy as np


def main() -> int:
    p = argparse.ArgumentParser(
        description="Amplifier S-params vs bias contour.")
    p.add_argument("--vna", choices=("nanovna","hp"), default="nanovna")
    p.add_argument("--port", default="/dev/ttyACM1")
    p.add_argument("--host", default="10.1.1.70")
    p.add_argument("--psu-host", required=True, metavar="HOST",
                   help="SPD3303X-E IP")
    p.add_argument("--psu-port", type=int, default=5025)
    p.add_argument("--vds", nargs="+", type=float, required=True,
                   help="List of Vds bias values (V)")
    p.add_argument("--start", type=float, required=True, metavar="MHZ")
    p.add_argument("--stop",  type=float, required=True, metavar="MHZ")
    p.add_argument("--f0",    type=float, required=True, metavar="MHZ",
                   help="Frequency at which to report gain")
    p.add_argument("--label", default="amp")
    p.add_argument("--out-dir", default=".")
    args = p.parse_args()

    out = Path(args.out_dir); out.mkdir(parents=True, exist_ok=True)
    csv_path = out / f"{args.label.replace(' ','_')}_bias_curve.csv"

    try:
        from rf_bench.siglent import SPD3303X
    except Exception:
        print("rf_bench.siglent.SPD3303X required", file=sys.stderr); return 1
    psu = SPD3303X(host=args.psu_host)

    sparams = (Path(__file__).resolve().parent.parent /
               "sparams-pdf" / "sparams_pdf.py")
    rows = []
    try:
        for vds in args.vds:
            print(f"\n=== Vds = {vds:.2f} V ===")
            psu.set_voltage(1, float(vds))
            psu.output_on(1)
            time.sleep(1.5)  # settle
            id_actual = psu.measure_current(1)
            print(f"  Id = {id_actual*1e3:.1f} mA")
            label = f"{args.label}_Vds{vds:.2f}V"
            pdf  = out / f"{label}.pdf"
            s2p  = out / f"{label}.s2p"
            rc = subprocess.call([
                sys.executable, str(sparams),
                "--vna", args.vna, "--port", args.port, "--host", args.host,
                "--start", str(args.start), "--stop", str(args.stop),
                "--label", label,
                "--output", str(pdf), "--touchstone", str(s2p),
                "--no-prompt",
            ])
            rows.append((vds, id_actual, str(s2p), str(pdf), rc))
    finally:
        try: psu.output_off(1)
        except Exception: pass

    with csv_path.open("w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["Vds_V","Id_A","s2p","pdf","rc"])
        for r in rows: w.writerow(r)
    print(f"\nWrote {csv_path}  ({len(rows)} bias points)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
