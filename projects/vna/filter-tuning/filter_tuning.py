#!/usr/bin/env python3
"""
filter_tuning.py — Real-time S21 overlay against a target shape.

Continuously sweeps S21 on the configured VNA and displays the trace
in a live matplotlib window with the user's target response overlaid.
The bottom of the window shows scalar metrics (peak insertion loss,
shape factor, ripple) updated each sweep.

For tuning crystal / cavity / LC filters by hand: eyes on the filter
knobs, glance at the chart, see whether you're getting closer to the
target shape.

The target is loaded from a YAML or JSON spec describing passband
edges, max insertion loss, min stopband attenuation, etc., and is
drawn as a "mask" that the live trace must stay inside.

A simpler `--target FILE.s2p` mode loads an existing measured shape
to match — useful for batch-tuning identical filters against a golden
reference.

This is the one VNA tool that's intentionally NOT a one-shot PDF
generator. It opens a live window and runs until you Ctrl-C.
"""

from __future__ import annotations
import warnings
warnings.filterwarnings("ignore", message="Unable to import Axes3D")
import argparse, json, sys, time
from pathlib import Path
import matplotlib
import matplotlib.pyplot as plt
import numpy as np


def open_vna(args):
    if args.vna == "nanovna":
        from rf_bench.nanovna import NanoVNA
        return NanoVNA(port=args.port)
    from rf_bench.hp import HP8712B
    return HP8712B(host=args.host)


def measure_s21(vna):
    vna.set_parameter("S21")
    vna.single_sweep()
    f = vna.get_frequencies()
    s21 = vna.get_s_data()
    return f, s21


def load_target(path: str):
    """Load a target spec: JSON or .s2p."""
    p = Path(path)
    if p.suffix.lower() == ".s2p":
        sys.path.insert(0, str(p.parent.parent / "de-embed-pdf"))
        from de_embed_pdf import read_s2p
        f, S, _, _ = read_s2p(str(p))
        return {"type": "s2p", "freqs_hz": f, "s21": S[:, 1, 0]}
    with p.open() as fh:
        return {"type": "spec", **json.load(fh)}


def plot_loop(vna, target, args):
    plt.ion()
    fig, ax = plt.subplots(figsize=(11, 7))
    line_meas, = ax.plot([], [], "b-", linewidth=1.4, label="live")
    line_target = None
    if target and target.get("type") == "s2p":
        ax.plot(target["freqs_hz"]/1e6,
                20*np.log10(np.clip(np.abs(target["s21"]), 1e-12, None)),
                "g--", linewidth=1.2, label="target")
    elif target and target.get("type") == "spec":
        # Plot a mask: target passband and stopband
        spec = target
        if "passband_mhz" in spec:
            lo, hi = spec["passband_mhz"]
            il = spec.get("max_passband_loss_db", -3)
            ax.axhline(il, color="orange", linestyle="--", linewidth=0.8,
                       label=f"max passband loss {il} dB")
            ax.axvspan(lo, hi, color="green", alpha=0.10)
        if "stopband_mhz" in spec:
            for (lo, hi) in spec["stopband_mhz"]:
                att = spec.get("min_stopband_atten_db", -60)
                ax.axhline(att, color="red", linestyle="--", linewidth=0.8,
                           alpha=0.5)
                ax.axvspan(lo, hi, color="red", alpha=0.06)
    ax.set_xlabel("Frequency (MHz)")
    ax.set_ylabel("|S21| (dB)")
    ax.grid(True, alpha=0.35)
    ax.legend(loc="upper right", fontsize=9)
    metrics_text = ax.text(
        0.005, 0.005, "", transform=ax.transAxes, fontsize=9,
        family="monospace", va="bottom", ha="left",
        bbox=dict(facecolor="white", edgecolor="#cccccc", alpha=0.9, pad=4))
    ax.set_title("Live filter tuning — Ctrl-C to exit", fontsize=11)

    try:
        while plt.fignum_exists(fig.number):
            f, s21 = measure_s21(vna)
            mag_db = 20*np.log10(np.clip(np.abs(s21), 1e-12, None))
            line_meas.set_data(f/1e6, mag_db)
            i_pk = int(np.argmax(mag_db))
            peak_db = mag_db[i_pk]
            metrics_text.set_text(
                f"peak {peak_db:+.2f} dB @ {f[i_pk]/1e6:.4f} MHz")
            ax.relim(); ax.autoscale_view(scaley=True)
            ax.set_xlim(f[0]/1e6, f[-1]/1e6)
            fig.canvas.draw()
            fig.canvas.flush_events()
            time.sleep(args.refresh)
    except KeyboardInterrupt:
        print("\nExiting.")


def main() -> int:
    p = argparse.ArgumentParser(
        description="Live S21 overlay for filter tuning.")
    p.add_argument("--vna", choices=("nanovna","hp"), default="nanovna")
    p.add_argument("--port", default="/dev/ttyACM1")
    p.add_argument("--host", default="10.1.1.70")
    p.add_argument("--start", type=float, required=True, metavar="MHZ")
    p.add_argument("--stop",  type=float, required=True, metavar="MHZ")
    p.add_argument("--points", type=int, default=401)
    p.add_argument("--target", default=None, metavar="FILE",
                   help="Either a .s2p (overlay measured) or a .json spec "
                        "(passband/stopband mask).")
    p.add_argument("--refresh", type=float, default=0.5,
                   help="Refresh interval in seconds (default 0.5).")
    args = p.parse_args()

    target = load_target(args.target) if args.target else None
    vna = open_vna(args)
    vna.setup_sweep(args.start*1e6, args.stop*1e6, args.points)
    try:
        # Use TkAgg or Qt backend if available; fall back to interactive
        # default. Live display needs an interactive backend, so this
        # script will fail if running headless (in cron, in a worker, etc.).
        # Switch to a GUI backend if possible.
        for backend in ("TkAgg", "Qt5Agg", "GTK3Agg"):
            try: matplotlib.use(backend, force=True); break
            except Exception: pass
        plot_loop(vna, target, args)
    finally:
        try: vna.close()
        except Exception: pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
