#!/usr/bin/env python3
"""
nec_verify.py — Compare measured S11 against an NEC-2 / 4nec2 simulation.

Loads:
  - A Touchstone .s1p of the measured antenna
  - An NEC-2-output frequency-sweep file (4nec2 / xnecview / cocoaNEC
    all produce compatible text dumps with Re/Im or |Z|/phase columns).

Reads the simulated impedance, converts to S11 at the user's Z₀,
and plots measured vs simulated side-by-side. Disagreement
diagnoses model error — wrong height, wire size, missing ground,
etc.

UNTESTED. Parses the most common 4nec2 .nec output table — a more
robust parser is left to a future iteration.
"""

from __future__ import annotations
import warnings
warnings.filterwarnings("ignore", message="Unable to import Axes3D")
import argparse, sys
from datetime import datetime
import matplotlib; matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parent.parent / "vector-fit-spice"))
from vector_fit_spice import read_touchstone


def parse_nec_z(path: str) -> tuple[np.ndarray, np.ndarray]:
    """
    Parse a NEC-2-style frequency table. Expected: lines with at least
    [freq_mhz, R, X] columns. The function tries a few common formats.
    """
    freqs = []; zs = []
    with open(path) as fh:
        for line in fh:
            parts = line.split()
            if len(parts) < 3: continue
            try:
                f_mhz = float(parts[0]); r = float(parts[1]); x = float(parts[2])
            except ValueError:
                continue
            freqs.append(f_mhz*1e6); zs.append(complex(r, x))
    if not freqs:
        raise RuntimeError(f"No [freq, R, X] rows parsed from {path}")
    return np.array(freqs), np.array(zs, dtype=np.complex128)


def main() -> int:
    p = argparse.ArgumentParser(
        description="Measured vs NEC-simulated S11 overlay.")
    p.add_argument("--measured", required=True, metavar="MEAS.s1p")
    p.add_argument("--nec", required=True, metavar="NEC.txt",
                   help="NEC-2 frequency table (cols: f_MHz R X ...)")
    p.add_argument("--z0", type=float, default=50.0)
    p.add_argument("--label", default="antenna")
    p.add_argument("--output", required=True, metavar="FILE.pdf")
    args = p.parse_args()

    try:
        f_meas, s11_meas, _ = read_touchstone(args.measured, "S11")
    except FileNotFoundError as exc:
        print(f"File not found: {exc.filename}", file=sys.stderr); return 1
    f_nec, z_nec = parse_nec_z(args.nec)
    s11_nec = (z_nec - args.z0) / (z_nec + args.z0)

    fig, axes = plt.subplots(2, 1, figsize=(11, 8), sharex=True)
    axes[0].plot(f_meas/1e6, 20*np.log10(np.clip(np.abs(s11_meas), 1e-12, None)),
                 color="#1f77b4", linewidth=1.4, label="measured")
    axes[0].plot(f_nec/1e6, 20*np.log10(np.clip(np.abs(s11_nec), 1e-12, None)),
                 "--", color="#d62728", linewidth=1.2, label="NEC simulation")
    axes[0].set_ylabel("|S11| (dB)")
    axes[0].grid(True, alpha=0.35); axes[0].legend(loc="upper right", fontsize=9)

    axes[1].plot(f_meas/1e6, np.degrees(np.angle(s11_meas)),
                 color="#1f77b4", linewidth=1.4, label="measured")
    axes[1].plot(f_nec/1e6, np.degrees(np.angle(s11_nec)),
                 "--", color="#d62728", linewidth=1.2, label="NEC")
    axes[1].set_xlabel("Frequency (MHz)"); axes[1].set_ylabel("∠S11 (°)")
    axes[1].grid(True, alpha=0.35); axes[1].legend(loc="upper right", fontsize=9)
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    fig.suptitle(f"NEC verify — {args.label}  •  Z₀={args.z0:g} Ω  •  {ts}",
                 fontsize=10)
    fig.tight_layout(rect=(0,0,1,0.95))
    fig.savefig(args.output, format="pdf"); plt.close(fig)
    print(f"Wrote {args.output}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
