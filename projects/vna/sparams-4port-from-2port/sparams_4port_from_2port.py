#!/usr/bin/env python3
"""
sparams_4port_from_2port.py — Build a 4-port .s4p from six 2-port captures.

A 2-port VNA can characterise a 4-port DUT by capturing pairwise
S-parameters with the unused ports terminated in matched (50-Ω)
loads. Six pair captures cover all entries of the 4×4 S-matrix:

  ports (1,2): captures S11, S12, S21, S22 → goes into rows/cols 1,2
  ports (1,3): captures S11_a, S13, S31, S33
  ports (1,4): captures S11_b, S14, S41, S44_a
  ports (2,3): captures S22_a, S23, S32, S33_a
  ports (2,4): captures S22_b, S24, S42, S44_b
  ports (3,4): captures S33_b, S34, S43, S44_c

The diagonal terms (S11, S22, S33, S44) appear in multiple captures;
we average them for noise reduction. The off-diagonal terms each
appear in exactly one capture.

UNTESTED. The operator instruction is: feed 6 .s2p files (one per
port pair) and label which ports each capture used.
"""

from __future__ import annotations
import warnings
warnings.filterwarnings("ignore", message="Unable to import Axes3D")
import argparse, sys
from datetime import datetime
import numpy as np

sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parent.parent / "de-embed-pdf"))
from de_embed_pdf import read_s2p
sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parent.parent / "mixed-mode-pdf"))
from mixed_mode_pdf import write_s4p


def main() -> int:
    p = argparse.ArgumentParser(
        description="Stitch six 2-port captures into a 4-port .s4p.")
    p.add_argument("--p12", required=True, metavar="P12.s2p",
                   help=".s2p captured with ports 1+2 of the DUT")
    p.add_argument("--p13", required=True, metavar="P13.s2p")
    p.add_argument("--p14", required=True, metavar="P14.s2p")
    p.add_argument("--p23", required=True, metavar="P23.s2p")
    p.add_argument("--p24", required=True, metavar="P24.s2p")
    p.add_argument("--p34", required=True, metavar="P34.s2p")
    p.add_argument("--output", required=True, metavar="OUT.s4p")
    args = p.parse_args()

    inputs = [(args.p12, 1, 2), (args.p13, 1, 3), (args.p14, 1, 4),
              (args.p23, 2, 3), (args.p24, 2, 4), (args.p34, 3, 4)]
    freqs_ref, _, z0_ref, _ = read_s2p(args.p12)
    n = len(freqs_ref)
    S4 = np.zeros((n, 4, 4), dtype=np.complex128)
    diag_sum = [np.zeros(n, dtype=np.complex128) for _ in range(4)]
    diag_cnt = [0]*4

    for path, ia, ib in inputs:
        f, S, z0, _ = read_s2p(path)
        if not np.allclose(f, freqs_ref):
            print(f"Error: freq array mismatch in {path}", file=sys.stderr)
            return 1
        ia0, ib0 = ia-1, ib-1
        # Off-diagonal terms (unique to this capture)
        S4[:, ia0, ib0] = S[:, 0, 1]   # S(ia, ib) = local S12
        S4[:, ib0, ia0] = S[:, 1, 0]   # S(ib, ia) = local S21
        # Diagonal terms (averaged across all captures involving each port)
        diag_sum[ia0] += S[:, 0, 0]; diag_cnt[ia0] += 1
        diag_sum[ib0] += S[:, 1, 1]; diag_cnt[ib0] += 1

    for i in range(4):
        S4[:, i, i] = diag_sum[i] / max(diag_cnt[i], 1)

    write_s4p(args.output, freqs_ref, S4, z0_ref, comment_lines=[
        "4-port .s4p assembled from six 2-port .s2p captures",
        f"Inputs: p12={args.p12} p13={args.p13} p14={args.p14}",
        f"        p23={args.p23} p24={args.p24} p34={args.p34}",
    ])
    print(f"Wrote {args.output}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
