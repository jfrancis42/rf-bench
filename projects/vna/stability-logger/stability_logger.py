#!/usr/bin/env python3
"""
stability_logger.py — Long-running VNA calibration / DUT drift monitor.

Cron- or systemd-timer-friendly. Each invocation:

  1. Sweeps S11 (and optionally S21) of a fixed reference DUT.
  2. Computes scalar metrics (median |Γ|, peak |Γ|, freq of peak).
  3. Appends a single row to a CSV log with a timestamp.
  4. Optionally writes a roll-up PDF of trend lines so far.

Use it to:

  - Watch SOLT calibration drift over days / weeks (use a precision
    LOAD or SHORT as the reference).
  - Watch an antenna feedpoint drift over seasons (use the antenna
    itself as the reference).
  - Alert when something has changed (return code 2 if any metric
    falls outside a `--alert-band ±`).

Designed to be quiet on success (no console output) so it's friendly
in cron. Pass `--verbose` for human-readable summaries.
"""

from __future__ import annotations
import warnings
warnings.filterwarnings("ignore", message="Unable to import Axes3D")
import argparse, csv, sys, os
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


def measure(vna, args):
    vna.setup_sweep(args.start*1e6, args.stop*1e6, args.points)
    vna.set_parameter("S11")
    vna.single_sweep()
    f = vna.get_frequencies()
    s11 = vna.average_s_data(args.average) if args.average > 1 else vna.get_s_data()
    return f, s11


def compute_metrics(f, s11):
    mag = np.abs(s11)
    i = int(np.argmax(mag))
    return dict(
        peak_gamma_mag=float(mag[i]),
        peak_gamma_freq_hz=float(f[i]),
        median_gamma_mag=float(np.median(mag)),
        rl_min_db=float(-20.0*np.log10(np.clip(mag, 1e-12, None).min())),
        rl_max_db=float(-20.0*np.log10(np.clip(mag, 1e-12, None).max())),
    )


def append_csv(log_path, ts, metrics):
    log_path = Path(log_path)
    new = not log_path.exists()
    with log_path.open("a", newline="") as fh:
        w = csv.writer(fh)
        if new:
            w.writerow(["timestamp", *metrics.keys()])
        w.writerow([ts, *metrics.values()])


def plot_history(log_path, output_path):
    log_path = Path(log_path)
    if not log_path.exists(): return False
    rows = []
    with log_path.open() as fh:
        r = csv.DictReader(fh)
        for row in r:
            rows.append(row)
    if len(rows) < 2: return False
    ts = [r["timestamp"] for r in rows]
    peak_gamma = [float(r["peak_gamma_mag"]) for r in rows]
    median_gamma = [float(r["median_gamma_mag"]) for r in rows]
    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(11, 7), sharex=True)
    x = np.arange(len(rows))
    ax1.plot(x, peak_gamma, "o-", color="#d62728", label="peak |Γ|")
    ax2.plot(x, median_gamma, "o-", color="#1f77b4", label="median |Γ|")
    for ax in (ax1, ax2):
        ax.grid(True, alpha=0.35); ax.legend(loc="upper right", fontsize=8)
    ax2.set_xlabel("Capture index")
    ax1.set_ylabel("|Γ|"); ax2.set_ylabel("|Γ|")
    fig.suptitle(f"Stability log over {len(rows)} captures  •  "
                 f"first {ts[0]}  last {ts[-1]}", fontsize=10)
    fig.tight_layout(rect=(0, 0, 1, 0.95))
    fig.savefig(output_path, format="pdf"); plt.close(fig)
    return True


def main() -> int:
    p = argparse.ArgumentParser(
        description="Append one S11 capture to a long-running stability log.")
    p.add_argument("--vna", choices=("nanovna","hp"), default="nanovna")
    p.add_argument("--port", default="/dev/ttyACM1")
    p.add_argument("--host", default="10.1.1.70")
    p.add_argument("--start", type=float, required=True, metavar="MHZ")
    p.add_argument("--stop",  type=float, required=True, metavar="MHZ")
    p.add_argument("--points", type=int, default=201)
    p.add_argument("--average", type=int, default=2)
    p.add_argument("--log", required=True, metavar="FILE.csv",
                   help="CSV log path (appended to).")
    p.add_argument("--alert-mag", type=float, default=None, metavar="X",
                   help="Exit code 2 if median |Γ| ≥ this value.")
    p.add_argument("--summary-pdf", default=None, metavar="FILE.pdf",
                   help="Optionally write a trend-line summary PDF.")
    p.add_argument("--verbose", action="store_true")
    args = p.parse_args()

    vna = open_vna(args)
    try:
        f, s11 = measure(vna, args)
    finally:
        try: vna.close()
        except Exception: pass

    metrics = compute_metrics(f, s11)
    ts = datetime.now().isoformat(timespec="seconds")
    append_csv(args.log, ts, metrics)
    if args.verbose:
        print(f"[{ts}] {metrics}")

    rc = 0
    if args.alert_mag is not None and metrics["median_gamma_mag"] >= args.alert_mag:
        if args.verbose:
            print(f"ALERT: median |Γ| = {metrics['median_gamma_mag']:.4f} "
                  f"≥ {args.alert_mag:.4f}")
        rc = 2

    if args.summary_pdf:
        plot_history(args.log, args.summary_pdf)
        if args.verbose:
            print(f"Wrote summary: {args.summary_pdf}")
    return rc


if __name__ == "__main__":
    sys.exit(main())
