#!/usr/bin/env python3
"""
sparams_pdf.py — Full 2-port S-parameters via DUT-reversal trick.

The NanoVNA is a 1.5-port VNA: it measures S11 and S21 in a single
capture, but it cannot do S12 or S22 directly because it has no
reverse-direction stimulus. Workaround: capture S11+S21 in the
"forward" orientation, then physically flip the DUT and capture
again — the new S11 is the original S22 and the new S21 is the
original S12.

The HP 8712B, when its KISS-488 adapter is online, will do all four
S-parameters in a single capture. The script also runs against it
unchanged via `--vna hp` for a sanity cross-check or when speed
matters (HP is faster on full 2-port sweeps).

Output
------
  - Single-page PDF with 4 magnitude panels (|S11|, |S21|, |S12|, |S22|)
    + 4 phase panels (∠S11, ∠S21, ∠S12, ∠S22) in a 4×2 grid
  - Touchstone .s2p file (magnitude-angle format) with one row per
    sweep point — the standard interchange format for ADS, AWR, QUCS,
    scikit-rf, etc.

Why no calibration step here?
-----------------------------
This script trusts the calibration that's already loaded on the VNA.
For the NanoVNA, run a full SOLT (or at least 1-port OSL + THRU) and
load it into a flash slot before running this script.

For *every* NanoVNA capture you take here, the SAME calibration
applies in both orientations only if you swap the DUT *without
swapping any cabling between Port 1, Port 2, and the SOLT plane*.
If you have to re-route cables to physically reverse a heavy DUT, the
calibration is invalidated and the result is no longer trustworthy.
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime
from typing import Optional

# Suppress mixed-install matplotlib Axes3D import warning (harmless;
# happens when system-package and pip-installed matplotlib are both present).
import warnings
warnings.filterwarnings("ignore", message="Unable to import Axes3D")

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np


DEFAULT_VNA      = "nanovna"
DEFAULT_PORT     = "/dev/ttyACM1"
DEFAULT_HP_HOST  = "10.1.1.70"
DEFAULT_POINTS   = 401


def open_vna(args):
    if args.vna == "nanovna":
        from rf_bench.nanovna import NanoVNA
        return NanoVNA(port=args.port), "nanovna"
    elif args.vna == "hp":
        from rf_bench.hp import HP8712B
        return HP8712B(host=args.host), "hp"
    else:
        raise ValueError(f"--vna must be 'nanovna' or 'hp', got {args.vna!r}")


def maybe_set_power(vna, dbm, vna_kind):
    if dbm is None:
        return
    try:
        vna.set_power(float(dbm))
        print(f"  Source power : {dbm:+.1f} dBm")
    except NotImplementedError:
        print(f"  Source power : --power ignored ({vna_kind} has no dBm setpoint)")


def measure_pass(vna, start_hz, stop_hz, points, averaging):
    """Return (freqs, s11, s21) — complex arrays length `points`."""
    vna.setup_sweep(start_hz, stop_hz, points)
    vna.set_parameter("S11")
    vna.single_sweep()
    freqs = vna.get_frequencies()
    s11 = vna.average_s_data(averaging) if averaging > 1 else vna.get_s_data()

    vna.set_parameter("S21")
    vna.single_sweep()
    s21 = vna.average_s_data(averaging) if averaging > 1 else vna.get_s_data()

    if not (len(freqs) == len(s11) == len(s21)):
        raise RuntimeError(
            f"Mismatched array lengths "
            f"(freqs={len(freqs)} s11={len(s11)} s21={len(s21)})"
        )
    return freqs, s11, s21


def measure_full_hp(vna, start_hz, stop_hz, points, averaging):
    """
    HP 8712B path: capture all 4 S-params in one sitting (no DUT flip).

    This uses the swappable-API `set_parameter("S12")` and "S22" which
    the HP supports natively and the NanoVNA refuses with
    NotImplementedError.
    """
    vna.setup_sweep(start_hz, stop_hz, points)
    out = {}
    for p in ("S11", "S21", "S12", "S22"):
        vna.set_parameter(p)
        vna.single_sweep()
        if p == "S11":
            freqs = vna.get_frequencies()
        out[p] = (vna.average_s_data(averaging)
                  if averaging > 1 else vna.get_s_data())
    return freqs, out["S11"], out["S21"], out["S12"], out["S22"]


def prompt(message: str, no_prompt: bool):
    if no_prompt:
        print(f"  [no-prompt] skipping: {message}")
        return
    try:
        input(f"  {message} (press Enter to continue) ")
    except EOFError:
        print(f"  [no stdin] continuing: {message}")


# ---------------------------------------------------------------------------
# Touchstone writer
# ---------------------------------------------------------------------------

def write_touchstone(path: str, freqs_hz: np.ndarray,
                     s11, s21, s12, s22,
                     comment_lines: list[str] | None = None) -> None:
    """
    Write a .s2p file in MA (magnitude-angle, degrees) format at 50 Ω.

    Standard column order for 2-port Touchstone:
        f  |S11| ∠S11  |S21| ∠S21  |S12| ∠S12  |S22| ∠S22

    Note the (S21, S12) ordering — that's the Touchstone v1 convention,
    not (S12, S21). Tools that read .s2p expect it this way.
    """
    with open(path, "w") as fh:
        fh.write("! Touchstone .s2p, generated by sparams_pdf.py\n")
        fh.write(f"! Date: {datetime.now().isoformat(timespec='seconds')}\n")
        if comment_lines:
            for line in comment_lines:
                fh.write(f"! {line}\n")
        fh.write("# Hz S MA R 50\n")
        for i in range(len(freqs_hz)):
            row = [
                float(freqs_hz[i]),
                float(np.abs(s11[i])), float(np.degrees(np.angle(s11[i]))),
                float(np.abs(s21[i])), float(np.degrees(np.angle(s21[i]))),
                float(np.abs(s12[i])), float(np.degrees(np.angle(s12[i]))),
                float(np.abs(s22[i])), float(np.degrees(np.angle(s22[i]))),
            ]
            fh.write(" ".join(f"{v:.6e}" for v in row) + "\n")


# ---------------------------------------------------------------------------
# Plot
# ---------------------------------------------------------------------------

def plot_pdf(freqs_hz, s11, s21, s12, s22, label, driver_name, idn,
             reversal_used: bool, output_path: str):
    freqs_mhz = freqs_hz / 1e6
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    fig, axes = plt.subplots(4, 2, figsize=(12, 14), sharex=True)

    panels = (
        ("S11", s11, "#1f77b4"),
        ("S21", s21, "#2ca02c"),
        ("S12", s12, "#ff7f0e"),
        ("S22", s22, "#d62728"),
    )
    for i, (name, s, color) in enumerate(panels):
        mag = 20.0 * np.log10(np.clip(np.abs(s), 1e-12, None))
        phase = np.degrees(np.unwrap(np.angle(s)))

        axes[i, 0].plot(freqs_mhz, mag, color=color, linewidth=1.2)
        axes[i, 0].set_ylabel(f"|{name}| (dB)")
        axes[i, 0].grid(True, which="both", alpha=0.35)

        axes[i, 1].plot(freqs_mhz, phase, color=color, linewidth=1.2)
        axes[i, 1].set_ylabel(f"∠{name} (°)")
        axes[i, 1].grid(True, which="both", alpha=0.35)

    axes[3, 0].set_xlabel("Frequency (MHz)")
    axes[3, 1].set_xlabel("Frequency (MHz)")

    suptitle = [
        f"2-port S-parameters — {label}",
        f"{freqs_mhz[0]:.4f} – {freqs_mhz[-1]:.4f} MHz  •  "
        f"{len(freqs_hz)} points  •  {driver_name}",
    ]
    if reversal_used:
        suptitle.append("Method: DUT-reversal (pass A: S11+S21; pass B: DUT "
                        "flipped → reported as S22+S12)")
    else:
        suptitle.append("Method: native 4-S-param capture")
    suptitle.append(ts)
    if idn:
        suptitle.append(idn[:120])
    fig.suptitle("\n".join(suptitle), fontsize=10)

    fig.tight_layout(rect=(0, 0, 1, 0.96))
    fig.savefig(output_path, format="pdf")
    plt.close(fig)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> int:
    p = argparse.ArgumentParser(
        description="Full 2-port S-parameters PDF + Touchstone .s2p export.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument("--vna",   choices=("nanovna", "hp"), default=DEFAULT_VNA)
    p.add_argument("--port",  default=DEFAULT_PORT)
    p.add_argument("--host",  default=DEFAULT_HP_HOST)
    p.add_argument("--start", type=float, required=True, metavar="MHZ")
    p.add_argument("--stop",  type=float, required=True, metavar="MHZ")
    p.add_argument("--points", type=int, default=DEFAULT_POINTS, metavar="N")
    p.add_argument("--average", type=int, default=2, metavar="N")
    p.add_argument("--power", type=float, default=None, metavar="DBM")
    p.add_argument("--save-A", default=None, metavar="FILE.npz",
                   help="(NanoVNA path) After pass A, save and exit. Use "
                        "--load-A FILE on a separate run to combine.")
    p.add_argument("--load-A", default=None, metavar="FILE.npz",
                   help="(NanoVNA path) Load pass A from --save-A NPZ.")
    p.add_argument("--no-prompt", action="store_true",
                   help="Don't pause for the DUT reversal (use only when "
                        "the swap is automated via relays).")
    p.add_argument("--label", default="2-port DUT")
    p.add_argument("--output", required=True, metavar="FILE.pdf",
                   help="Output PDF path")
    p.add_argument("--touchstone", default=None, metavar="FILE.s2p",
                   help="Optional Touchstone .s2p output path (default: "
                        "same basename as --output with .s2p extension)")
    args = p.parse_args()

    if args.start <= 0 or args.stop <= 0 or args.stop <= args.start:
        print("Error: --start and --stop must be positive with stop > start")
        return 1
    if args.points < 2 or args.average < 1:
        print("Error: --points must be ≥ 2 and --average must be ≥ 1")
        return 1
    if args.save_A and args.load_A:
        print("Error: --save-A and --load-A are mutually exclusive")
        return 1

    if args.touchstone is None:
        # Derive default Touchstone path from the PDF path
        if args.output.lower().endswith(".pdf"):
            args.touchstone = args.output[:-4] + ".s2p"
        else:
            args.touchstone = args.output + ".s2p"

    print(f"S-parameters PDF — {args.label}")
    print(f"  Driver       : {args.vna}")
    print(f"  Sweep        : {args.start:.4f} – {args.stop:.4f} MHz, "
          f"{args.points} points, average={args.average}")
    print(f"  PDF          : {args.output}")
    print(f"  Touchstone   : {args.touchstone}")

    vna = None
    try:
        vna, vna_kind = open_vna(args)
        idn = vna.identify()
        print(f"  IDN          : {idn[:120]}")
        maybe_set_power(vna, args.power, vna_kind)

        reversal_used = False

        if vna_kind == "hp":
            print("  Mode         : native 4-S-param capture (HP)")
            freqs_hz, s11, s21, s12, s22 = measure_full_hp(
                vna, args.start * 1e6, args.stop * 1e6,
                args.points, args.average,
            )
        else:
            reversal_used = True
            print("  Mode         : NanoVNA DUT-reversal (two passes)")
            # Pass A — forward orientation
            if args.load_A:
                print(f"  Loading pass A from {args.load_A}")
                data = np.load(args.load_A)
                freqs_hz = data["freqs_hz"]
                s11      = data["s11"]
                s21      = data["s21"]
            else:
                prompt("Connect DUT in its FORWARD orientation "
                       "(port 1 → DUT in → DUT out → port 2). "
                       "Pass A: capturing S11 + S21.",
                       no_prompt=args.no_prompt)
                freqs_hz, s11, s21 = measure_pass(
                    vna, args.start * 1e6, args.stop * 1e6,
                    args.points, args.average,
                )

            if args.save_A:
                np.savez(args.save_A, freqs_hz=freqs_hz, s11=s11, s21=s21)
                print(f"  Saved pass A → {args.save_A}")
                print(f"  Re-run with --load-A {args.save_A} after "
                      "physically reversing the DUT to capture pass B.")
                return 0

            # Pass B — reversed orientation
            prompt("Now PHYSICALLY REVERSE the DUT in place "
                   "(port 1 → DUT out → DUT in → port 2). "
                   "Do NOT move the port-1 and port-2 cables — only "
                   "the DUT itself. Pass B: capturing S11_rev + S21_rev.",
                   no_prompt=args.no_prompt)
            freqs_hz2, s11_rev, s21_rev = measure_pass(
                vna, args.start * 1e6, args.stop * 1e6,
                args.points, args.average,
            )
            if not np.allclose(freqs_hz, freqs_hz2):
                print("  WARNING: frequency arrays differ between passes A "
                      "and B; results may be inconsistent.")

            # Map: pass-B S11 → original S22, pass-B S21 → original S12
            s22 = s11_rev
            s12 = s21_rev

        # Console summary
        for name, s in (("S11", s11), ("S21", s21),
                        ("S12", s12), ("S22", s22)):
            mag = 20.0 * np.log10(np.clip(np.abs(s), 1e-12, None))
            i_pk = int(np.argmax(np.abs(s)))
            i_dp = int(np.argmin(np.abs(s)))
            print(f"  {name}          : "
                  f"max {mag[i_pk]:+.2f} dB @ {freqs_hz[i_pk]/1e6:.4f} MHz, "
                  f"min {mag[i_dp]:+.2f} dB @ {freqs_hz[i_dp]/1e6:.4f} MHz")

        write_touchstone(
            args.touchstone, freqs_hz, s11, s21, s12, s22,
            comment_lines=[
                f"DUT: {args.label}",
                f"Method: {'native HP' if not reversal_used else 'NanoVNA DUT-reversal'}",
                f"Sweep: {args.start} – {args.stop} MHz, "
                f"{args.points} points, average {args.average}",
                f"IDN: {idn[:120]}",
            ],
        )
        print(f"  Wrote .s2p   → {args.touchstone}")

        plot_pdf(
            freqs_hz, s11, s21, s12, s22,
            label=args.label,
            driver_name=args.vna.upper(),
            idn=idn,
            reversal_used=reversal_used,
            output_path=args.output,
        )
        print(f"  Wrote PDF    → {args.output}")
        return 0

    except KeyboardInterrupt:
        print("\nInterrupted.")
        return 130
    except Exception as exc:
        print(f"\nFailed: {exc}", file=sys.stderr)
        return 1
    finally:
        if vna is not None:
            try:
                vna.close()
            except Exception:
                pass


if __name__ == "__main__":
    sys.exit(main())
