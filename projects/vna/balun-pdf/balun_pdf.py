#!/usr/bin/env python3
"""
balun_pdf.py — Balun amplitude+phase balance + insertion loss PDF.

A balun's quality is described by three frequency-dependent numbers:

  1. Input return loss        (how well it matches Z0 on the unbalanced side)
  2. Through loss             (how much signal it actually passes per leg)
  3. Amplitude/phase balance  (how equal the two output legs are)

This script measures all three using a two-pass S11+S21 workflow on a
single 2-port VNA: each output leg is measured against the input port
in turn, with the *other* leg terminated in a 50-Ω load. The script
saves the first pass to disk, then prompts you to swap the connection
before the second pass.

Setup
-----
Treat the balun as a 3-port device with ports labelled IN, A, B.

  Pass 1 (leg A):
      VNA Port 1 ── IN
      VNA Port 2 ── A
      50-Ω load  ── B

  Pass 2 (leg B):
      VNA Port 1 ── IN
      VNA Port 2 ── B           (swap from leg A)
      50-Ω load  ── A           (swap with what was on port 2)

The script saves S11+S21 from pass 1 to a temporary NPZ. After you
swap, it captures pass 2 and combines:

  Amplitude balance = 20·log10(|S21_A| / |S21_B|)        dB
  Phase     balance = ∠S21_A − ∠S21_B                    deg, unwrapped
  Insertion loss    = -10·log10(|S21_A|² + |S21_B|²)     dB  (combined)

Targets
-------
A "good" wideband 1:1 or 4:1 balun across HF runs:
  - Return loss             ≥ 14 dB (VSWR ≤ 1.5:1)
  - Insertion loss          ≤ 0.5 dB
  - Amplitude balance       ≤ ±0.5 dB
  - Phase balance           ≤ ±5°  (around the nominal — 180° for a 1:1
                                    centre-tap balun, 0° for a Guanella)
"""

from __future__ import annotations

import argparse
import os
import sys
from datetime import datetime
from typing import Optional

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.ticker as mticker
import numpy as np


DEFAULT_VNA      = "nanovna"
DEFAULT_PORT     = "/dev/ttyACM1"
DEFAULT_HP_HOST  = "10.1.1.70"
DEFAULT_POINTS   = 401


def open_vna(args):
    if args.vna == "nanovna":
        from rf_bench.nanovna import NanoVNA
        vna = NanoVNA(port=args.port)
    elif args.vna == "hp":
        from rf_bench.hp import HP8712B
        vna = HP8712B(host=args.host)
    else:
        raise ValueError(f"--vna must be 'nanovna' or 'hp', got {args.vna!r}")
    return vna, vna.identify()


def maybe_set_power(vna, dbm: Optional[float], vna_kind: str) -> None:
    if dbm is None:
        return
    try:
        vna.set_power(float(dbm))
        print(f"  Source power : {dbm:+.1f} dBm")
    except NotImplementedError:
        print(f"  Source power : --power ignored ({vna_kind} has no dBm setpoint)")


def measure_pass(vna, start_hz, stop_hz, points, averaging):
    """Return (freqs, s11, s21) — both complex arrays length `points`."""
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


# ---------------------------------------------------------------------------
# Plot
# ---------------------------------------------------------------------------

def plot_pdf(freqs_hz, s11_a, s21_a, s11_b, s21_b,
             nominal_phase_deg: float,
             label, driver_name, idn, output_path):
    freqs_mhz = freqs_hz / 1e6
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    # Quantities of interest
    rl_a = -20.0 * np.log10(np.clip(np.abs(s11_a), 1e-12, None))
    rl_b = -20.0 * np.log10(np.clip(np.abs(s11_b), 1e-12, None))
    rl_in = (rl_a + rl_b) / 2.0   # average of the two passes

    il_a = -20.0 * np.log10(np.clip(np.abs(s21_a), 1e-12, None))
    il_b = -20.0 * np.log10(np.clip(np.abs(s21_b), 1e-12, None))
    # Combined insertion loss assumes the two legs are summed coherently
    # into the load; for a balun's stated "insertion loss" it's the
    # per-leg average less 3 dB (because each leg carries half the power).
    il_per_leg = (il_a + il_b) / 2.0
    il_total = il_per_leg - 3.0   # 3 dB credit for two-leg combination

    amp_bal_db = 20.0 * np.log10(
        np.clip(np.abs(s21_a), 1e-12, None) /
        np.clip(np.abs(s21_b), 1e-12, None)
    )
    phase_a = np.unwrap(np.angle(s21_a))
    phase_b = np.unwrap(np.angle(s21_b))
    phase_bal_deg = np.degrees(phase_a - phase_b) - nominal_phase_deg
    # Wrap residual into [-180, 180]
    phase_bal_deg = (phase_bal_deg + 180.0) % 360.0 - 180.0

    fig, axes = plt.subplots(4, 1, figsize=(11, 13), sharex=True)

    # ── Return loss ─────────────────────────────────────────────────────
    ax = axes[0]
    ax.plot(freqs_mhz, rl_in, color="#1f77b4", linewidth=1.4,
            label="Input RL (avg of A/B passes)")
    ax.axhline(14, color="orange", linestyle="--", linewidth=0.8,
               label="14 dB (VSWR 1.5:1)")
    ax.axhline(20, color="green",  linestyle="--", linewidth=0.8,
               label="20 dB (VSWR 1.22:1)")
    ax.set_ylabel("Return loss (dB)")
    ax.grid(True, which="both", alpha=0.35)
    ax.legend(loc="lower right", fontsize=8, framealpha=0.92)
    title_lines = [
        f"Balun Performance — {label}  (nominal phase Δ = {nominal_phase_deg:g}°)",
        f"{freqs_mhz[0]:.3f} – {freqs_mhz[-1]:.3f} MHz  •  "
        f"{len(freqs_hz)} points  •  {driver_name}  •  {ts}",
    ]
    if idn:
        title_lines.append(idn[:120])
    ax.set_title("\n".join(title_lines), fontsize=10)

    # ── Insertion loss ──────────────────────────────────────────────────
    ax = axes[1]
    ax.plot(freqs_mhz, il_a, color="#d62728", linewidth=1.0,
            label="Leg A (raw S21)")
    ax.plot(freqs_mhz, il_b, color="#2ca02c", linewidth=1.0,
            label="Leg B (raw S21)")
    ax.plot(freqs_mhz, il_total, color="#1f77b4", linewidth=1.6,
            label="Effective insertion loss (combined)")
    ax.axhline(0.5, color="orange", linestyle="--", linewidth=0.8,
               label="0.5 dB target")
    ax.set_ylabel("Insertion loss (dB)")
    ax.grid(True, which="both", alpha=0.35)
    ax.legend(loc="upper right", fontsize=8, framealpha=0.92)
    ax.invert_yaxis()   # less loss = higher on the plot

    # ── Amplitude balance ───────────────────────────────────────────────
    ax = axes[2]
    ax.plot(freqs_mhz, amp_bal_db, color="#9467bd", linewidth=1.4,
            label="|S21_A| / |S21_B|")
    for v in (-0.5, 0.5):
        ax.axhline(v, color="orange", linestyle="--", linewidth=0.8)
    ax.axhline(0, color="#888888", linewidth=0.6)
    ax.set_ylabel("Amplitude balance (dB)")
    ax.grid(True, which="both", alpha=0.35)
    ax.legend(loc="upper right", fontsize=8, framealpha=0.92)

    # ── Phase balance ───────────────────────────────────────────────────
    ax = axes[3]
    ax.plot(freqs_mhz, phase_bal_deg, color="#8c564b", linewidth=1.4,
            label=f"∠S21_A − ∠S21_B  − {nominal_phase_deg:g}°")
    for v in (-5.0, 5.0):
        ax.axhline(v, color="orange", linestyle="--", linewidth=0.8)
    ax.axhline(0, color="#888888", linewidth=0.6)
    ax.set_xlabel("Frequency (MHz)")
    ax.set_ylabel("Phase balance (°)")
    ax.grid(True, which="both", alpha=0.35)
    ax.legend(loc="upper right", fontsize=8, framealpha=0.92)

    fig.tight_layout()
    fig.savefig(output_path, format="pdf")
    plt.close(fig)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def prompt_or_skip(message: str, no_prompt: bool):
    if no_prompt:
        print(f"  [no-prompt] skipping: {message}")
        return
    try:
        input(f"  {message} (press Enter to continue) ")
    except EOFError:
        print(f"  [no stdin] continuing: {message}")


def main() -> int:
    p = argparse.ArgumentParser(
        description="Balun amplitude/phase balance + insertion loss PDF.",
    )
    p.add_argument("--vna",   choices=("nanovna", "hp"), default=DEFAULT_VNA)
    p.add_argument("--port",  default=DEFAULT_PORT)
    p.add_argument("--host",  default=DEFAULT_HP_HOST)
    p.add_argument("--start", type=float, required=True, metavar="MHZ")
    p.add_argument("--stop",  type=float, required=True, metavar="MHZ")
    p.add_argument("--points", type=int, default=DEFAULT_POINTS, metavar="N")
    p.add_argument("--average", type=int, default=2, metavar="N")
    p.add_argument("--power", type=float, default=None, metavar="DBM")
    p.add_argument("--phase-180", action="store_true",
                   help="Centre-tap balun (1:1 voltage; legs are 180° "
                        "out of phase). Default is 0° (Guanella current "
                        "balun where both legs are in-phase).")
    p.add_argument("--save-A", default=None, metavar="FILE.npz",
                   help="After pass A, save and exit. Use --load-A FILE "
                        "on a separate run to combine.")
    p.add_argument("--load-A", default=None, metavar="FILE.npz",
                   help="Load pass A from a previous --save-A run and "
                        "measure only pass B.")
    p.add_argument("--no-prompt", action="store_true",
                   help="Don't pause between passes (use only when both "
                        "connections are made externally e.g. with relays).")
    p.add_argument("--label", default="balun")
    p.add_argument("--output", required=True, metavar="FILE.pdf")
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

    nominal_phase_deg = 180.0 if args.phase_180 else 0.0

    print(f"Balun PDF — {args.label}")
    print(f"  Driver       : {args.vna}")
    print(f"  Sweep        : {args.start:.3f} – {args.stop:.3f} MHz, "
          f"{args.points} points, average={args.average}")
    print(f"  Nominal phase: {nominal_phase_deg:g}°  "
          f"({'centre-tap voltage' if args.phase_180 else 'current'} balun)")
    print(f"  Output       : {args.output}")

    vna = None
    try:
        vna, idn = open_vna(args)
        print(f"  IDN          : {idn[:120]}")
        maybe_set_power(vna, args.power, args.vna)

        # ── Pass A ────────────────────────────────────────────────────────
        if args.load_A:
            print(f"  Loading pass A from {args.load_A}")
            data = np.load(args.load_A)
            freqs_hz = data["freqs_hz"]
            s11_a = data["s11"]
            s21_a = data["s21"]
        else:
            prompt_or_skip(
                "Connect IN→port1, A→port2, B→50Ω load. "
                "Pass A is about to run.",
                no_prompt=args.no_prompt,
            )
            print("  Measuring pass A …")
            freqs_hz, s11_a, s21_a = measure_pass(
                vna, args.start * 1e6, args.stop * 1e6,
                args.points, args.average,
            )

        if args.save_A:
            np.savez(args.save_A, freqs_hz=freqs_hz, s11=s11_a, s21=s21_a)
            print(f"  Saved pass A → {args.save_A}")
            print(f"  Re-run with --load-A {args.save_A} after swapping to leg B.")
            return 0

        # ── Pass B ────────────────────────────────────────────────────────
        prompt_or_skip(
            "Swap: now connect B→port2, A→50Ω load. Pass B about to run.",
            no_prompt=args.no_prompt,
        )
        print("  Measuring pass B …")
        freqs_hz2, s11_b, s21_b = measure_pass(
            vna, args.start * 1e6, args.stop * 1e6,
            args.points, args.average,
        )
        if not np.allclose(freqs_hz, freqs_hz2):
            print("  WARNING: frequency arrays differ between passes A and B; "
                  "results may be inconsistent.")

        # ── Summary ───────────────────────────────────────────────────────
        rl_in = -20.0 * np.log10(np.clip(
            (np.abs(s11_a) + np.abs(s11_b)) / 2.0, 1e-12, None))
        amp_bal = 20.0 * np.log10(
            np.clip(np.abs(s21_a), 1e-12, None) /
            np.clip(np.abs(s21_b), 1e-12, None))
        il_per_leg = -10.0 * np.log10(
            np.clip(np.abs(s21_a)**2 + np.abs(s21_b)**2, 1e-12, None))

        i_min_rl = int(np.argmin(rl_in))
        i_worst_amp = int(np.argmax(np.abs(amp_bal)))
        i_worst_il = int(np.argmax(il_per_leg))
        print(f"  Worst RL     : {rl_in[i_min_rl]:.1f} dB @ "
              f"{freqs_hz[i_min_rl]/1e6:.3f} MHz")
        print(f"  Worst IL     : {il_per_leg[i_worst_il]:.2f} dB @ "
              f"{freqs_hz[i_worst_il]/1e6:.3f} MHz")
        print(f"  Worst amp Δ  : {amp_bal[i_worst_amp]:+.2f} dB @ "
              f"{freqs_hz[i_worst_amp]/1e6:.3f} MHz")

        plot_pdf(
            freqs_hz, s11_a, s21_a, s11_b, s21_b,
            nominal_phase_deg=nominal_phase_deg,
            label=args.label,
            driver_name=args.vna.upper(),
            idn=idn,
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
