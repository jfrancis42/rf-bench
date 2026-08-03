#!/usr/bin/env python3
"""
Scalar VNA — Siglent SSA3032X Plus + RB3X25 Reflection Bridge

Two-port scalar network analysis:
  S11 — Return loss and VSWR via the reflection bridge (TG + RB3X25)
  S21 — Insertion loss / gain via through connection (TG + through path)

The S11 measurement is identical in principle to the antenna analyzer:
  - Open-circuit calibration captures the 100% reflection baseline.
  - Return loss = cal_trace − dut_trace.
  - VSWR derived from return loss.

The S21 measurement uses a relative reference:
  - Reference: TG Out connected directly to SSA RF In ("through" cal).
  - DUT: TG Out → DUT in → DUT out → SSA RF In.
  - S21_dB = dut_trace − ref_trace (element-wise numpy subtraction).

Both calibration references can be saved to a .npz file for re-use.

Usage:
  python scalar_vna.py                        # S11 + S21 (with prompts)
  python scalar_vna.py --s11                  # S11 only
  python scalar_vna.py --s21                  # S21 only
  python scalar_vna.py --calibrate            # S11 open-circuit calibration only
  python scalar_vna.py --s21 --calibrate      # S21 through-cal only
  python scalar_vna.py --yes                  # skip all prompts
"""

import argparse
import json
import os
import sys
import time
from datetime import datetime

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np

# ---------------------------------------------------------------------------
# Siglent shared drivers
# ---------------------------------------------------------------------------

from rf_bench.siglent import SSA3000X                    # noqa: E402
from rf_bench.utils import (                             # noqa: E402
    rl_to_vswr_v, format_freq, format_freq_short, nearest_rbw,
)
from rf_bench import connect

# ---------------------------------------------------------------------------
# Defaults
# ---------------------------------------------------------------------------

DEFAULT_SSA_HOST    = None  # Now uses inventory
DEFAULT_INSTRUMENT_PORT = 5025
DEFAULT_START_KHZ   = 100          # 100 kHz
DEFAULT_STOP_KHZ    = 200_000      # 200 MHz
DEFAULT_POINTS      = 301
DEFAULT_TG_LEVEL    = 0.0          # dBm; max TG output
DEFAULT_CAL_FILE    = os.path.expanduser("~/.scalar_vna_cal.npz")


# ---------------------------------------------------------------------------
# Calibration file I/O
# ---------------------------------------------------------------------------

def save_cal(path: str, s11_open: np.ndarray | None, s21_ref: np.ndarray | None,
             host: str, start_hz: int, stop_hz: int, points: int):
    """Save calibration traces to .npz.  Either trace may be None."""
    meta = json.dumps({
        "timestamp": datetime.now().isoformat(),
        "host":      host,
        "start_hz":  start_hz,
        "stop_hz":   stop_hz,
        "points":    points,
    })
    arrays: dict = {"_meta": np.array([meta])}
    if s11_open is not None:
        arrays["s11_open"] = s11_open
    if s21_ref is not None:
        arrays["s21_ref"] = s21_ref
    np.savez(path, **arrays)
    print(f"Calibration saved → {path}")


def load_cal(path: str) -> tuple[np.ndarray | None, np.ndarray | None, dict]:
    """
    Load calibration from .npz.

    Returns (s11_open, s21_ref, meta).  Missing traces return as None.
    """
    data = np.load(path, allow_pickle=False)
    meta: dict = {}
    if "_meta" in data.files:
        try:
            meta = json.loads(str(data["_meta"][0]))
        except (json.JSONDecodeError, IndexError):
            pass
    s11_open = data["s11_open"] if "s11_open" in data.files else None
    s21_ref  = data["s21_ref"]  if "s21_ref"  in data.files else None
    return s11_open, s21_ref, meta


# ---------------------------------------------------------------------------
# Sweep helper
# ---------------------------------------------------------------------------

def do_sweep(ssa: SSA3000X, start_hz: int, stop_hz: int, points: int,
             label: str) -> tuple[np.ndarray, np.ndarray, int]:
    """
    Set up the SSA band, run a single sweep, and return
    (freqs_hz, trace_dbm, rbw_hz).
    """
    rbw = ssa.setup_band(start_hz, stop_hz, points)
    print(f"  [{label}]  RBW={rbw/1000:.0f} kHz ...", end=" ", flush=True)
    ok = ssa.single_sweep()
    trace = ssa.get_trace()
    print(f"done ({len(trace)} pts)" + ("" if ok else " [WARN: *OPC timeout]"))
    freqs = np.linspace(start_hz, stop_hz, len(trace))
    return freqs, trace, rbw


# ---------------------------------------------------------------------------
# S11 measurement
# ---------------------------------------------------------------------------

def calibrate_s11(ssa: SSA3000X, start_hz: int, stop_hz: int,
                  points: int) -> np.ndarray:
    """Sweep with open circuit, return the calibration trace."""
    print("\n[S11 CALIBRATION — open circuit]")
    _, trace, _ = do_sweep(ssa, start_hz, stop_hz, points, "open-circuit cal")
    return trace


def measure_s11(ssa: SSA3000X, start_hz: int, stop_hz: int, points: int,
                cal_trace: np.ndarray | None) -> dict:
    """
    Measure S11.  Returns a dict with:
      freqs_hz, trace_dbm, rl_db, vswr
    """
    print("\n[S11 MEASUREMENT]")
    freqs, trace, rbw = do_sweep(ssa, start_hz, stop_hz, points, "S11 DUT")

    # Interpolate calibration if lengths differ
    if cal_trace is not None:
        cal = cal_trace
        if len(cal) != len(trace):
            cal = np.interp(np.linspace(0, 1, len(trace)),
                            np.linspace(0, 1, len(cal)), cal)
        rl_db = cal - trace
    else:
        print("  WARNING: no S11 calibration — values are raw reflected power (not return loss).")
        rl_db = -trace  # uncalibrated: negate raw trace as rough estimate

    rl_db = np.clip(rl_db, 0.0, 80.0)
    vswr  = np.clip(rl_to_vswr_v(rl_db), 1.0, 99.9)

    best_rl_idx = int(np.argmax(rl_db))
    best_vswr   = float(vswr[int(np.argmin(vswr))])
    print(f"  Best RL   : {rl_db[best_rl_idx]:.1f} dB @ {format_freq(freqs[best_rl_idx])}")
    print(f"  Best VSWR : {best_vswr:.2f}:1")

    return dict(
        freqs_hz  = freqs,
        trace_dbm = trace,
        rl_db     = rl_db,
        vswr      = vswr,
        rbw       = rbw,
        calibrated= cal_trace is not None,
    )


# ---------------------------------------------------------------------------
# S21 measurement
# ---------------------------------------------------------------------------

def calibrate_s21(ssa: SSA3000X, start_hz: int, stop_hz: int,
                  points: int) -> np.ndarray:
    """Sweep with through (TG Out directly to SSA RF In), return reference trace."""
    print("\n[S21 CALIBRATION — through reference]")
    _, trace, _ = do_sweep(ssa, start_hz, stop_hz, points, "through ref")
    return trace


def measure_s21(ssa: SSA3000X, start_hz: int, stop_hz: int, points: int,
                ref_trace: np.ndarray | None) -> dict:
    """
    Measure S21.  Returns a dict with:
      freqs_hz, trace_dbm, s21_db
    """
    print("\n[S21 MEASUREMENT]")
    freqs, trace, rbw = do_sweep(ssa, start_hz, stop_hz, points, "S21 DUT")

    if ref_trace is not None:
        ref = ref_trace
        if len(ref) != len(trace):
            ref = np.interp(np.linspace(0, 1, len(trace)),
                            np.linspace(0, 1, len(ref)), ref)
        s21_db = trace - ref
    else:
        print("  WARNING: no S21 reference — showing absolute power (not relative S21).")
        s21_db = trace  # uncalibrated

    print(f"  S21 min: {np.min(s21_db):.1f} dB  max: {np.max(s21_db):.1f} dB  "
          f"median: {np.median(s21_db):.1f} dB")

    return dict(
        freqs_hz  = freqs,
        trace_dbm = trace,
        s21_db    = s21_db,
        rbw       = rbw,
        calibrated= ref_trace is not None,
    )


# ---------------------------------------------------------------------------
# Plotting
# ---------------------------------------------------------------------------

def generate_plot(s11_result: dict | None, s21_result: dict | None,
                  output_prefix: str) -> str:
    """Generate combined S11 / S21 plot.  Returns the saved file path."""
    panels = []
    if s11_result is not None:
        panels.append("s11")
    if s21_result is not None:
        panels.append("s21")

    nrows  = len(panels)
    fig, axes = plt.subplots(nrows, 1, figsize=(10, 4 * nrows))
    if nrows == 1:
        axes = [axes]

    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    fig.suptitle(f"Scalar VNA — {ts}", fontsize=12)

    ax_idx = 0

    if s11_result is not None:
        ax   = axes[ax_idx]; ax_idx += 1
        r    = s11_result
        fmhz = r['freqs_hz'] / 1e6

        # Primary axis: return loss
        rl = r['rl_db']
        ax.plot(fmhz, rl, color='#1f77b4', linewidth=1.5, label='Return Loss (dB)')

        # Reference lines
        for threshold, label, color in [
            (10, '10 dB (2:1 VSWR)', 'darkorange'),
            (14, '14 dB (1.5:1)',    'green'),
            (20, '20 dB (1.22:1)',   'gray'),
        ]:
            ax.axhline(threshold, color=color, linestyle='--', linewidth=0.8,
                       alpha=0.7, label=label)

        # Stats annotation
        if len(rl) > 0:
            textstr = (f"RL max: {np.max(rl):.1f} dB\n"
                       f"RL min: {np.min(rl):.1f} dB\n"
                       f"VSWR best: {float(np.min(r['vswr'])):.2f}:1")
            ax.text(0.98, 0.97, textstr, transform=ax.transAxes,
                    fontsize=8, va='top', ha='right',
                    bbox=dict(boxstyle='round', facecolor='lightblue', alpha=0.8))

        ax.set_ylabel("Return Loss (dB)", fontsize=10)
        ax.set_title(f"S11 — Return Loss  "
                     f"({'calibrated' if r['calibrated'] else 'UNCALIBRATED'})", fontsize=10)
        ax.grid(True, alpha=0.35)
        ax.legend(fontsize=8, loc='lower left')

        # Secondary axis: VSWR
        ax2 = ax.twinx()
        vswr_clipped = np.clip(r['vswr'], 1.0, 10.0)
        ax2.plot(fmhz, vswr_clipped, color='darkorange', linewidth=0.8,
                 linestyle=':', alpha=0.6, label='VSWR')
        ax2.set_ylabel("VSWR", fontsize=9, color='darkorange')
        ax2.set_ylim(1.0, 10.0)
        ax2.tick_params(axis='y', labelcolor='darkorange', labelsize=8)

        ax.set_xlim(fmhz[0], fmhz[-1])
        ax.tick_params(labelsize=9)

    if s21_result is not None:
        ax   = axes[ax_idx]; ax_idx += 1
        r    = s21_result
        fmhz = r['freqs_hz'] / 1e6
        s21  = r['s21_db']

        ax.plot(fmhz, s21, color='#2ca02c', linewidth=1.5, label='S21 (dB)')
        ax.axhline(0,   color='gray',       linestyle='--', linewidth=0.8, alpha=0.5)
        ax.axhline(-3,  color='darkorange', linestyle='--', linewidth=0.8,
                   alpha=0.7, label='−3 dB')
        ax.axhline(-10, color='red',        linestyle='--', linewidth=0.8,
                   alpha=0.7, label='−10 dB')

        if len(s21) > 0:
            textstr = (f"S21 max: {np.max(s21):.1f} dB\n"
                       f"S21 min: {np.min(s21):.1f} dB\n"
                       f"S21 med: {np.median(s21):.1f} dB")
            ax.text(0.98, 0.97, textstr, transform=ax.transAxes,
                    fontsize=8, va='top', ha='right',
                    bbox=dict(boxstyle='round', facecolor='lightgreen', alpha=0.8))

        ax.set_ylabel("S21 (dB)", fontsize=10)
        ax.set_xlabel("Frequency (MHz)", fontsize=10)
        ax.set_title(f"S21 — Insertion Loss / Gain  "
                     f"({'calibrated' if r['calibrated'] else 'UNCALIBRATED'})", fontsize=10)
        ax.grid(True, alpha=0.35)
        ax.legend(fontsize=8)
        ax.set_xlim(fmhz[0], fmhz[-1])
        ax.tick_params(labelsize=9)
    else:
        axes[-1].set_xlabel("Frequency (MHz)", fontsize=10)

    plt.tight_layout(rect=[0, 0, 1, 0.96])
    path = f"{output_prefix}.png"
    plt.savefig(path, dpi=150, bbox_inches='tight')
    plt.close(fig)
    return path


# ---------------------------------------------------------------------------
# Text report
# ---------------------------------------------------------------------------

def save_txt(s11_result: dict | None, s21_result: dict | None,
             output_prefix: str, start_hz: int, stop_hz: int) -> str:
    """Write a text report.  Returns the path."""
    path = f"{output_prefix}.txt"
    ts   = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    sep  = "=" * 72
    lines = [
        sep,
        "  SCALAR VNA REPORT",
        f"  Generated  : {ts}",
        f"  Frequency  : {format_freq(start_hz)} – {format_freq(stop_hz)}",
        sep, "",
    ]

    if s11_result is not None:
        r    = s11_result
        rl   = r['rl_db']
        vswr = r['vswr']
        lines += [
            "S11 — Return Loss / VSWR",
            f"  Calibrated  : {'yes' if r['calibrated'] else 'NO — values are estimates'}",
            f"  RL (max)    : {np.max(rl):.2f} dB  @ {format_freq(r['freqs_hz'][int(np.argmax(rl))])}",
            f"  RL (min)    : {np.min(rl):.2f} dB  @ {format_freq(r['freqs_hz'][int(np.argmin(rl))])}",
            f"  VSWR (best) : {float(np.min(vswr)):.3f}:1  @ {format_freq(r['freqs_hz'][int(np.argmin(vswr))])}",
            f"  VSWR (worst): {float(np.max(vswr)):.2f}:1",
            "",
            f"  {'Frequency':>16}  {'RL':>8}  {'VSWR':>8}",
            "  " + "-" * 36,
        ]
        step = max(1, len(r['freqs_hz']) // 30)
        for i in range(0, len(r['freqs_hz']), step):
            lines.append(
                f"  {format_freq(r['freqs_hz'][i]):>16}  "
                f"{rl[i]:>6.1f} dB  "
                f"{float(vswr[i]):>6.2f}:1"
            )
        lines.append("")

    if s21_result is not None:
        r   = s21_result
        s21 = r['s21_db']
        lines += [
            "S21 — Insertion Loss / Gain",
            f"  Calibrated  : {'yes' if r['calibrated'] else 'NO — showing absolute power'}",
            f"  S21 (max)   : {np.max(s21):.2f} dB  @ {format_freq(r['freqs_hz'][int(np.argmax(s21))])}",
            f"  S21 (min)   : {np.min(s21):.2f} dB  @ {format_freq(r['freqs_hz'][int(np.argmin(s21))])}",
            f"  S21 (median): {np.median(s21):.2f} dB",
            "",
            f"  {'Frequency':>16}  {'S21':>8}",
            "  " + "-" * 28,
        ]
        step = max(1, len(r['freqs_hz']) // 30)
        for i in range(0, len(r['freqs_hz']), step):
            lines.append(
                f"  {format_freq(r['freqs_hz'][i]):>16}  {s21[i]:>6.1f} dB"
            )
        lines.append("")

    text = "\n".join(lines) + "\n"
    with open(path, "w") as fh:
        fh.write(text)
    return path


def save_json(s11_result: dict | None, s21_result: dict | None,
              output_prefix: str, start_hz: int, stop_hz: int, ssa_host: str) -> str:
    """Write a JSON file with the full numerical data."""
    path = f"{output_prefix}.json"
    data: dict = {
        "timestamp":  datetime.now().isoformat(),
        "ssa_host":   ssa_host,
        "start_hz":   start_hz,
        "stop_hz":    stop_hz,
    }
    if s11_result is not None:
        r = s11_result
        data["s11"] = {
            "calibrated": r["calibrated"],
            "freqs_hz":   r["freqs_hz"].tolist(),
            "rl_db":      r["rl_db"].tolist(),
            "vswr":       r["vswr"].tolist(),
        }
    if s21_result is not None:
        r = s21_result
        data["s21"] = {
            "calibrated": r["calibrated"],
            "freqs_hz":   r["freqs_hz"].tolist(),
            "s21_db":     r["s21_db"].tolist(),
        }
    with open(path, "w") as jf:
        json.dump(data, jf, indent=2)
    return path


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Scalar VNA — S11 (return loss/VSWR) + S21 (insertion loss/gain)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Setup for S11 (reflection bridge):
  SSA TG Out ─── RB3X25 TG port
  RB3X25 SA port ─── SSA RF In
  DUT ─── RB3X25 DUT port

Setup for S21 (through/insertion):
  Calibration:  SSA TG Out ─── SSA RF In (through, no DUT)
  Measurement:  SSA TG Out ─── DUT in → DUT out ─── SSA RF In

Examples:
  python scalar_vna.py                         # S11 + S21 (with prompts)
  python scalar_vna.py --s11                   # S11 only
  python scalar_vna.py --s21                   # S21 only
  python scalar_vna.py --calibrate             # S11 open-circuit calibration
  python scalar_vna.py --s21 --calibrate       # S21 through reference only
  python scalar_vna.py --yes                   # unattended (no prompts)
  python scalar_vna.py --start 100 --stop 500000 --points 501
""",
    )

    parser.add_argument("--s11",       action="store_true",
                        help="Measure S11 only")
    parser.add_argument("--s21",       action="store_true",
                        help="Measure S21 only")
    parser.add_argument("--start",     type=float, default=DEFAULT_START_KHZ,
                        metavar="KHZ", help=f"Start frequency in kHz (default {DEFAULT_START_KHZ})")
    parser.add_argument("--stop",      type=float, default=DEFAULT_STOP_KHZ,
                        metavar="KHZ", help=f"Stop frequency in kHz (default {DEFAULT_STOP_KHZ})")
    parser.add_argument("--points",    type=int,   default=DEFAULT_POINTS,
                        metavar="N",   help=f"Sweep points (default {DEFAULT_POINTS})")
    parser.add_argument("--cal-file",  default=DEFAULT_CAL_FILE, metavar="FILE",
                        help=f"Calibration file path (default: {DEFAULT_CAL_FILE})")
    parser.add_argument("--calibrate", action="store_true",
                        help="Run calibration only and save (S11 open-circuit or S21 through)")
    parser.add_argument("--ssa-host",  default=DEFAULT_SSA_HOST, metavar="HOST",
                        help=f"SSA IP address (default {DEFAULT_SSA_HOST})")
    parser.add_argument("--output",    default=None, metavar="PREFIX",
                        help="Output filename prefix (default: timestamped)")
    parser.add_argument("--yes",       action="store_true",
                        help="Skip all interactive prompts")

    args = parser.parse_args()

    # Default: both S11 and S21 unless one is explicitly selected
    do_s11 = args.s11 or (not args.s11 and not args.s21)
    do_s21 = args.s21 or (not args.s11 and not args.s21)

    if args.output is None:
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        args.output = f"scalar_vna_{ts}"

    start_hz = int(args.start * 1_000)
    stop_hz  = int(args.stop  * 1_000)

    if start_hz >= stop_hz:
        print("Error: --start must be less than --stop")
        sys.exit(1)

    start_hz = max(9_000, start_hz)   # SSA3032X Plus minimum

    def prompt(msg: str):
        print(msg)
        if not args.yes:
            input("Press Enter when ready...")

    ssa = None
    try:
        print(f"Connecting to SSA via inventory ...")
        ssa = connect(args.ssa_host or 'ssa')
        print(f"  {ssa.identify()}")

        print(f"Enabling tracking generator ({DEFAULT_TG_LEVEL:+.0f} dBm) ...")
        tg_ok = ssa.enable_tracking_generator(DEFAULT_TG_LEVEL)
        if not tg_ok:
            print("  WARNING: TG state query returned unexpected value — check front panel.")

        # Load existing calibration (ignore errors — we'll prompt to recalibrate if needed)
        s11_cal = s21_cal = None
        cal_meta: dict = {}
        try:
            s11_cal, s21_cal, cal_meta = load_cal(args.cal_file)
            parts = []
            if s11_cal is not None: parts.append("S11")
            if s21_cal is not None: parts.append("S21")
            print(f"Loaded calibration ({', '.join(parts)}) from {args.cal_file}")
            print(f"  Taken: {cal_meta.get('timestamp', 'unknown')}")
        except FileNotFoundError:
            print(f"No calibration file at {args.cal_file} — will prompt to calibrate.")
        except Exception as exc:
            print(f"Could not load calibration: {exc}")

        # ----------------------------------------------------------------
        # Calibration mode: only run cal, save, and exit
        # ----------------------------------------------------------------
        if args.calibrate:
            if do_s11:
                prompt(
                    "\nS11 CALIBRATION: Connect an OPEN circuit to the DUT port "
                    "of the reflection bridge."
                )
                s11_cal = calibrate_s11(ssa, start_hz, stop_hz, args.points)

            if do_s21:
                prompt(
                    "\nS21 CALIBRATION: Connect SSA TG Out DIRECTLY to SSA RF In "
                    "(no DUT, just a cable — this is the through reference)."
                )
                s21_cal = calibrate_s21(ssa, start_hz, stop_hz, args.points)

            save_cal(args.cal_file, s11_cal, s21_cal,
                     args.ssa_host, start_hz, stop_hz, args.points)
            print("Calibration complete.")
            return

        # ----------------------------------------------------------------
        # Measurement: S11
        # ----------------------------------------------------------------
        s11_result = s21_result = None

        if do_s11:
            if s11_cal is None:
                # No calibration available — prompt for it
                prompt(
                    "\nNo S11 calibration found.\n"
                    "Connect an OPEN circuit to the DUT port of the reflection bridge."
                )
                s11_cal = calibrate_s11(ssa, start_hz, stop_hz, args.points)
                save_cal(args.cal_file, s11_cal, s21_cal,
                         args.ssa_host, start_hz, stop_hz, args.points)

            prompt(
                "\nS11 MEASUREMENT: Connect the RB3X25 reflection bridge.\n"
                "  SSA TG Out → RB3X25 TG port\n"
                "  RB3X25 SA port → SSA RF In\n"
                "  DUT → RB3X25 DUT port"
            )
            s11_result = measure_s11(ssa, start_hz, stop_hz, args.points, s11_cal)

        # ----------------------------------------------------------------
        # Measurement: S21
        # ----------------------------------------------------------------
        if do_s21:
            if s21_cal is None:
                # No S21 reference — take one now
                prompt(
                    "\nNo S21 reference calibration found.\n"
                    "Connect SSA TG Out DIRECTLY to SSA RF In (through, no DUT)."
                )
                s21_cal = calibrate_s21(ssa, start_hz, stop_hz, args.points)
                save_cal(args.cal_file, s11_cal, s21_cal,
                         args.ssa_host, start_hz, stop_hz, args.points)

            prompt(
                "\nS21 MEASUREMENT: Connect DUT in the through path.\n"
                "  SSA TG Out → DUT In\n"
                "  DUT Out → SSA RF In"
            )
            s21_result = measure_s21(ssa, start_hz, stop_hz, args.points, s21_cal)

        # ----------------------------------------------------------------
        # Save results
        # ----------------------------------------------------------------
        print("\n[SAVING RESULTS]")

        txt_path = save_txt(s11_result, s21_result, args.output, start_hz, stop_hz)
        print(f"Text   → {txt_path}")

        json_path = save_json(s11_result, s21_result, args.output,
                              start_hz, stop_hz, args.ssa_host)
        print(f"JSON   → {json_path}")

        try:
            png_path = generate_plot(s11_result, s21_result, args.output)
            print(f"Plot   → {png_path}")
        except Exception as exc:
            print(f"Plot generation failed: {exc}")

        # Print brief summary
        if s11_result is not None:
            best_vswr = float(np.min(s11_result['vswr']))
            best_rl   = float(np.max(s11_result['rl_db']))
            print(f"\nS11: best RL = {best_rl:.1f} dB  /  best VSWR = {best_vswr:.2f}:1")
        if s21_result is not None:
            s21 = s21_result['s21_db']
            print(f"S21: {np.min(s21):.1f} dB to {np.max(s21):.1f} dB  "
                  f"(median {np.median(s21):.1f} dB)")

    except KeyboardInterrupt:
        print("\nInterrupted.")
        sys.exit(0)
    except ConnectionRefusedError:
        print(f"\nCannot connect to SSA @ {args.ssa_host}:{DEFAULT_INSTRUMENT_PORT}")
        print("Verify the instrument is powered on and SCPI/LAN is enabled.")
        sys.exit(1)
    except OSError as exc:
        print(f"\nNetwork error: {exc}")
        sys.exit(1)
    except Exception as exc:
        import traceback
        print(f"\nUnexpected error: {exc}")
        traceback.print_exc()
        sys.exit(1)
    finally:
        if ssa is not None:
            try:
                ssa.disable_tracking_generator()
                ssa.disconnect()
            except Exception:
                pass


if __name__ == "__main__":
    main()
