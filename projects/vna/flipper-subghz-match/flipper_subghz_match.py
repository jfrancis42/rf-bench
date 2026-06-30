#!/usr/bin/env python3
"""
flipper_subghz_match.py — S11 of a Flipper Zero's external Sub-GHz antenna.

The Flipper Zero's external-SMA Sub-GHz module has three regulatory
bands: 300–348, 387–464, 779–928 MHz. This script sweeps S11 across
all three (or a user-chosen subset) on whatever antenna is plugged
into the Flipper, and reports which CC1101 channels in each band
are well-matched.

UNTESTED against hardware. The Flipper itself is not in the chain —
you simply unplug the antenna from the Flipper, plug it into the
VNA's port 1, and run the sweep.

For per-channel pass/fail testing, see `../connector-check/`.
"""

from __future__ import annotations
import warnings
warnings.filterwarnings("ignore", message="Unable to import Axes3D")
import argparse, sys
from datetime import datetime
import matplotlib; matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np


SUBGHZ_BANDS = [
    (300, 348, "300/315/348 MHz region"),
    (387, 464, "433 MHz region (EU/US ISM)"),
    (779, 928, "868/915 MHz region"),
]


def open_vna(args):
    if args.vna == "nanovna":
        from rf_bench.nanovna import NanoVNA
        return NanoVNA(port=args.port)
    from rf_bench.hp import HP8712B
    return HP8712B(host=args.host)


def main() -> int:
    p = argparse.ArgumentParser(
        description="S11 of a Flipper Sub-GHz antenna across all 3 bands.")
    p.add_argument("--vna", choices=("nanovna","hp"), default="nanovna")
    p.add_argument("--port", default="/dev/ttyACM1")
    p.add_argument("--host", default="10.1.1.70")
    p.add_argument("--bands", nargs="+", choices=("low","mid","high","all"),
                   default=["all"])
    p.add_argument("--threshold-db", type=float, default=10.0,
                   help="Pass threshold: RL ≥ N dB (default 10 = VSWR 1.92)")
    p.add_argument("--label", default="Flipper antenna")
    p.add_argument("--output", required=True, metavar="FILE.pdf")
    args = p.parse_args()

    selected = SUBGHZ_BANDS if "all" in args.bands else [
        b for k, b in zip(("low","mid","high"), SUBGHZ_BANDS) if k in args.bands
    ]
    vna = open_vna(args)
    captures = []
    try:
        for lo, hi, lbl in selected:
            print(f"  Sweeping {lo} – {hi} MHz ({lbl})…")
            vna.setup_sweep(lo*1e6, hi*1e6, 201)
            vna.set_parameter("S11")
            vna.single_sweep()
            f = vna.get_frequencies()
            s11 = vna.get_s_data()
            captures.append((lo, hi, lbl, f, s11))
    finally:
        try: vna.close()
        except Exception: pass

    fig, axes = plt.subplots(len(captures), 1, figsize=(11, 3.5*len(captures)),
                             squeeze=False)
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    for ax, (lo, hi, lbl, f, s11) in zip(axes.flat, captures):
        rl = -20*np.log10(np.clip(np.abs(s11), 1e-12, None))
        f_mhz = f/1e6
        ax.plot(f_mhz, rl, color="#1f77b4", linewidth=1.2)
        ax.axhline(args.threshold_db, color="orange", linestyle="--",
                   linewidth=0.8,
                   label=f"threshold {args.threshold_db:.0f} dB")
        i = int(np.argmax(rl))
        ax.plot(f_mhz[i], rl[i], "go", markersize=6,
                label=f"best {rl[i]:.1f} dB @ {f_mhz[i]:.2f} MHz")
        ax.set_title(lbl, fontsize=9)
        ax.set_ylabel("RL (dB)")
        ax.grid(True, alpha=0.35); ax.legend(loc="lower right", fontsize=8)
    axes.flat[-1].set_xlabel("Frequency (MHz)")
    fig.suptitle(f"Flipper Sub-GHz antenna check — {args.label}  •  {ts}",
                 fontsize=10)
    fig.tight_layout(rect=(0,0,1,0.96))
    fig.savefig(args.output, format="pdf"); plt.close(fig)
    print(f"Wrote {args.output}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
