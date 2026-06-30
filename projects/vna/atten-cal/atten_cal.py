#!/usr/bin/env python3
"""
atten_cal.py — Per-code per-frequency calibration of a digital attenuator.

For each control code of a digital step attenuator (PE43602, HMC472,
RFSA3013, etc.), capture S21 and record actual attenuation vs
frequency. Build a 2-D correction table that downstream projects can
load to get true-dB-accurate attenuation.

Requires Bus Pirate (or equivalent SPI/I2C controller) to talk to the
attenuator. The attenuator-control glue here is a placeholder; adapt
to your specific control chain.

UNTESTED against hardware. The output is a JSON 2-D table indexed
by code and frequency.
"""

from __future__ import annotations
import warnings
warnings.filterwarnings("ignore", message="Unable to import Axes3D")
import argparse, json, sys
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


def set_attenuator_code(args, code):
    """
    Placeholder. Real implementations should talk to the attenuator
    over SPI / I2C / parallel via Bus Pirate or another bridge.

    The default body just prints + waits so you can manually set it.
    """
    print(f"  Set attenuator to code 0x{code:02x} ({code})… ", end="", flush=True)
    if args.manual:
        try: input("press Enter when set")
        except EOFError: pass
    else:
        print("(no auto-control configured; rerun with --manual)")


def main() -> int:
    p = argparse.ArgumentParser(
        description="Per-code, per-frequency calibration of a step atten.")
    p.add_argument("--vna", choices=("nanovna","hp"), default="nanovna")
    p.add_argument("--port", default="/dev/ttyACM1")
    p.add_argument("--host", default="10.1.1.70")
    p.add_argument("--start", type=float, required=True, metavar="MHZ")
    p.add_argument("--stop",  type=float, required=True, metavar="MHZ")
    p.add_argument("--code-start", type=int, default=0)
    p.add_argument("--code-stop",  type=int, default=63,
                   help="Last code to test (inclusive)")
    p.add_argument("--code-step",  type=int, default=1)
    p.add_argument("--manual", action="store_true",
                   help="Pause and prompt at each code instead of auto-setting")
    p.add_argument("--label", default="step attenuator")
    p.add_argument("--output", required=True, metavar="FILE.json")
    p.add_argument("--plot", default=None, metavar="FILE.pdf")
    args = p.parse_args()

    codes = list(range(args.code_start, args.code_stop+1, args.code_step))
    vna = open_vna(args)
    vna.setup_sweep(args.start*1e6, args.stop*1e6, 101)
    vna.set_parameter("S21")
    table = {}
    try:
        for code in codes:
            set_attenuator_code(args, code)
            vna.single_sweep()
            f = vna.get_frequencies()
            s21 = vna.get_s_data()
            atten_db = -20*np.log10(np.clip(np.abs(s21), 1e-12, None))
            table[str(code)] = {
                "freq_hz": f.tolist(),
                "atten_db": atten_db.tolist(),
            }
    finally:
        try: vna.close()
        except Exception: pass

    with open(args.output, "w") as fh:
        json.dump({"label": args.label,
                   "timestamp": datetime.now().isoformat(timespec="seconds"),
                   "table": table}, fh)
    print(f"Wrote {args.output}")

    if args.plot:
        fig, ax = plt.subplots(figsize=(11, 6))
        for code, entry in table.items():
            f = np.array(entry["freq_hz"])/1e6
            atten = np.array(entry["atten_db"])
            ax.plot(f, atten, linewidth=0.8, label=f"code {code}")
        ax.set_xlabel("Frequency (MHz)"); ax.set_ylabel("Attenuation (dB)")
        ax.grid(True, alpha=0.35)
        ax.legend(loc="upper right", fontsize=6, ncol=4)
        ax.set_title(f"Atten cal — {args.label}")
        fig.tight_layout(); fig.savefig(args.plot, format="pdf"); plt.close(fig)
        print(f"Wrote {args.plot}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
