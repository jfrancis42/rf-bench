#!/usr/bin/env python3
"""
antenna_pattern.py — Polar radiation pattern via VNA + rotator.

For each angle commanded to a `scpi-rotator` ESP32 (or another
SCPI-controllable rotator), capture S21 from a reference antenna
through the DUT antenna. The angle-vs-magnitude data yields the
radiation pattern.

UNTESTED against the rf-bench scpi-rotator project (which is at
the "built to documentation" stage). The rotator-control glue here
issues SCPI commands `:SERV:POS <degrees>` and `:SERV:POS?` —
adjust to match the actual ESP32 firmware.

Workflow
--------
1. Mount the DUT antenna on a rotator.
2. Position a calibrated reference antenna 1+ wavelength away.
3. SOLT-calibrate the VNA at the reference antenna's connector.
4. Run this script with the desired azimuth sweep parameters.
5. Output: polar plot PDF + CSV of (angle, S21 dB).

Caveats
-------
- Anechoic-chamber-grade results require an anechoic chamber. A
  rooftop or open-field setup will have multipath that distorts the
  pattern, especially at angles away from the boresight.
- The reference antenna's pattern is not de-embedded — the result
  is the *combined* pattern of (DUT × reference). For directional
  references this matters; for isotropic-ish references (a thin
  dipole at the test frequency) it's a small correction.
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


def send_rotator_scpi(host, port, az_deg, settle_s):
    """Send SCPI to a network-connected rotator and wait for move-done."""
    with socket.socket() as s:
        s.connect((host, port))
        s.sendall(f":SERV:POS {az_deg:.2f}\n".encode())
        time.sleep(settle_s)


def main() -> int:
    p = argparse.ArgumentParser(
        description="Polar antenna pattern via VNA S21 + rotator.")
    p.add_argument("--vna", choices=("nanovna","hp"), default="nanovna")
    p.add_argument("--port", default="/dev/ttyACM1")
    p.add_argument("--host", default="10.1.1.70")
    p.add_argument("--rotator-host", required=True, metavar="HOST",
                   help="IP of the scpi-rotator (or compatible) controller")
    p.add_argument("--rotator-port", type=int, default=5025)
    p.add_argument("--freq", type=float, required=True, metavar="MHZ",
                   help="Test frequency (the pattern is plotted at this freq)")
    p.add_argument("--az-start", type=float, default=0)
    p.add_argument("--az-stop",  type=float, default=360)
    p.add_argument("--az-step",  type=float, default=10)
    p.add_argument("--settle",   type=float, default=2.0,
                   help="Seconds to wait after each rotator move")
    p.add_argument("--average",  type=int, default=4)
    p.add_argument("--label", default="antenna under test")
    p.add_argument("--csv", default=None)
    p.add_argument("--output", required=True, metavar="FILE.pdf")
    args = p.parse_args()

    angles = np.arange(args.az_start, args.az_stop+1e-9, args.az_step)
    vna = open_vna(args)
    rows = []
    try:
        vna.setup_sweep(args.freq*1e6 - 1e3, args.freq*1e6 + 1e3, 2)
        vna.set_parameter("S21")
        for az in angles:
            print(f"  AZ {az:6.1f}°…", flush=True)
            send_rotator_scpi(args.rotator_host, args.rotator_port,
                              az, args.settle)
            # Capture
            vna.single_sweep()
            s21 = (vna.average_s_data(args.average) if args.average > 1
                   else vna.get_s_data())
            db = float(20*np.log10(np.clip(np.abs(s21).mean(), 1e-12, None)))
            rows.append((float(az), db))
    finally:
        try: vna.close()
        except Exception: pass

    if args.csv:
        with open(args.csv, "w", newline="") as fh:
            w = csv.writer(fh); w.writerow(["az_deg","s21_db"]); w.writerows(rows)
        print(f"Wrote {args.csv}")

    az_r = np.deg2rad([r[0] for r in rows])
    db = np.array([r[1] for r in rows])
    fig = plt.figure(figsize=(9, 9))
    ax = fig.add_subplot(111, projection="polar")
    ax.plot(az_r, db - db.max(), color="#1f77b4", linewidth=1.4)
    ax.set_theta_zero_location("N"); ax.set_theta_direction(-1)
    ax.set_rlabel_position(135)
    ax.set_title(f"Pattern — {args.label}  @ {args.freq} MHz "
                 f"(normalised to peak)", fontsize=11)
    fig.tight_layout()
    fig.savefig(args.output, format="pdf")
    plt.close(fig)
    print(f"Wrote {args.output}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
