#!/usr/bin/env python3
"""
de_embed_fixture.py — Capture a fixture's S-params for later de-embedding.

Workflow companion to `../de-embed-pdf/`. The de-embed-pdf project
needs two .s2p files: one for the measurement and one for the fixture
alone. This tool guides you through capturing the fixture .s2p:

  1. Bridge the DUT pads on the fixture with a precision THRU (a 0-Ω
     resistor at HF/VHF or a short jumper).
  2. Run this script — it captures S11+S21 (and prompts for the DUT
     reversal so we also get S22+S12).
  3. Saves the result as `<label>_fixture.s2p`, which you then feed
     to de-embed-pdf along with your real measurement.

For symmetric fixtures (input launch identical to output launch),
the de-embed-pdf script will use the port-reversed mirror of this
file for the output side. For asymmetric fixtures, you may want to
capture each launch separately with this tool.
"""

from __future__ import annotations
import warnings
warnings.filterwarnings("ignore", message="Unable to import Axes3D")
import argparse, sys, subprocess
from pathlib import Path


def main() -> int:
    p = argparse.ArgumentParser(
        description="Capture a fixture's S-params via sparams-pdf.")
    p.add_argument("--vna", choices=("nanovna","hp"), default="nanovna")
    p.add_argument("--port", default="/dev/ttyACM1")
    p.add_argument("--host", default="10.1.1.70")
    p.add_argument("--start", type=float, required=True, metavar="MHZ")
    p.add_argument("--stop",  type=float, required=True, metavar="MHZ")
    p.add_argument("--points", type=int, default=401)
    p.add_argument("--average", type=int, default=4,
                   help="Higher than usual default; fixture cal needs "
                        "low noise.")
    p.add_argument("--power", type=float, default=None)
    p.add_argument("--label", required=True,
                   help="Used as base filename for the output .s2p / PDF.")
    p.add_argument("--out-dir", default=".")
    p.add_argument("--no-prompt", action="store_true")
    args = p.parse_args()

    print("Fixture characterisation workflow")
    print("  1. Place the fixture in its measurement position.")
    print("  2. Replace the DUT with a precision THRU (0-Ω resistor "
          "or solid bridge).")
    print("  3. The script will then run sparams-pdf to capture both")
    print("     directions; it expects you to flip the fixture between "
          "passes A and B (same as sparams-pdf normally does for the")
    print("     DUT).")
    print()
    if not args.no_prompt:
        try: input("Press Enter when the THRU is installed... ")
        except EOFError: pass

    base = f"{args.out_dir}/{args.label.replace(' ','_')}_fixture"
    sparams = (Path(__file__).resolve().parent.parent /
               "sparams-pdf" / "sparams_pdf.py")
    cmd = [
        sys.executable, str(sparams),
        "--vna", args.vna,
        "--port", args.port,
        "--host", args.host,
        "--start", str(args.start),
        "--stop",  str(args.stop),
        "--points", str(args.points),
        "--average", str(args.average),
        "--label", f"{args.label} fixture cal",
        "--output", f"{base}.pdf",
        "--touchstone", f"{base}.s2p",
    ]
    if args.power is not None: cmd += ["--power", str(args.power)]
    if args.no_prompt: cmd += ["--no-prompt"]
    print(f"  Running: {' '.join(cmd)}")
    return subprocess.call(cmd)


if __name__ == "__main__":
    sys.exit(main())
