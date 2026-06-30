#!/usr/bin/env python3
"""
wideband_rl_browser.py — Wideband return-loss sweep + interactive HTML.

Runs a long multi-segment sweep across the full VNA range (or a user-
chosen wide span) and writes a self-contained HTML page that shows the
trace as a Plotly chart (interactive zoom / hover / save-as-PNG).

Useful for ongoing "what changed?" type monitoring — leave the
HTML page open in a browser; rerun the script when something seems
off; reload to compare.

The Plotly HTML is fully self-contained — opens in any browser
without an internet connection.
"""

from __future__ import annotations
import warnings
warnings.filterwarnings("ignore", message="Unable to import Axes3D")
import argparse, sys, json
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
        description="Wideband S11 sweep + Plotly HTML viewer.")
    p.add_argument("--vna", choices=("nanovna","hp"), default="nanovna")
    p.add_argument("--port", default="/dev/ttyACM1")
    p.add_argument("--host", default="10.1.1.70")
    p.add_argument("--start", type=float, default=0.05, metavar="MHZ")
    p.add_argument("--stop",  type=float, default=900.0, metavar="MHZ")
    p.add_argument("--seg-points", type=int, default=401)
    p.add_argument("--n-segments", type=int, default=None)
    p.add_argument("--average", type=int, default=1)
    p.add_argument("--output", required=True, metavar="FILE.html")
    args = p.parse_args()

    n_seg = args.n_segments or max(1, int(np.ceil(
        (args.stop - args.start) / 100.0)))
    edges = np.linspace(args.start, args.stop, n_seg + 1)
    vna = open_vna(args)
    freqs_all = []; s11_all = []
    try:
        for i in range(n_seg):
            lo, hi = edges[i], edges[i+1]
            print(f"  Seg {i+1}/{n_seg}: {lo:.3f}–{hi:.3f} MHz")
            vna.setup_sweep(lo*1e6, hi*1e6, args.seg_points)
            vna.set_parameter("S11")
            vna.single_sweep()
            f = vna.get_frequencies()
            s11 = (vna.average_s_data(args.average) if args.average > 1
                   else vna.get_s_data())
            if i > 0: f, s11 = f[1:], s11[1:]
            freqs_all.append(f); s11_all.append(s11)
    finally:
        try: vna.close()
        except Exception: pass

    freqs = np.concatenate(freqs_all)
    s11 = np.concatenate(s11_all)
    rl_db = -20*np.log10(np.clip(np.abs(s11), 1e-12, None))
    f_mhz = freqs/1e6
    ts = datetime.now().isoformat(timespec="seconds")

    # Plotly HTML — self-contained, no CDN
    try:
        import plotly.graph_objects as go
        fig = go.Figure(go.Scatter(x=f_mhz.tolist(), y=rl_db.tolist(),
                                   mode="lines", name="Return loss (dB)"))
        fig.update_layout(
            title=f"Wideband return-loss browser ({ts})",
            xaxis_title="Frequency (MHz)",
            yaxis_title="Return loss (dB)",
            template="plotly_white",
        )
        fig.write_html(args.output, include_plotlyjs=True, full_html=True)
        print(f"Wrote {args.output}")
        return 0
    except ImportError:
        # Plotly not installed — fall back to a static HTML with embedded
        # SVG via matplotlib.
        import matplotlib; matplotlib.use("Agg")
        import matplotlib.pyplot as plt, io
        fig, ax = plt.subplots(figsize=(12, 5))
        ax.plot(f_mhz, rl_db, color="#1f77b4", linewidth=0.8)
        ax.set_xlabel("Frequency (MHz)"); ax.set_ylabel("Return loss (dB)")
        ax.grid(True, alpha=0.35)
        ax.set_title(f"Wideband RL — {ts}", fontsize=11)
        buf = io.StringIO()
        fig.savefig(buf, format="svg"); plt.close(fig)
        with open(args.output, "w") as fh:
            fh.write("<!doctype html><html><body>"
                     "<p>Static fallback (Plotly not installed; install with "
                     "<code>pip install plotly --break-system-packages</code>"
                     " for interactive output)</p>")
            fh.write(buf.getvalue())
            fh.write("</body></html>")
        print(f"Wrote {args.output} (static SVG; install plotly for interactive)")
        return 0


if __name__ == "__main__":
    sys.exit(main())
