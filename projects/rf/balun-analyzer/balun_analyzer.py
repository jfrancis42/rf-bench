#!/usr/bin/env python3
"""
Balun / Common-Mode Choke Analyzer — Siglent SSA3032X Plus + RB3X25

Measures choking impedance of baluns and common-mode chokes across frequency.

Key concept: unlike antenna measurement where low VSWR is good, here we WANT
high impedance (high reflection).  The reflection bridge measures how closely
the DUT looks like an open circuit.  We derive |Z| from the reflection coefficient:

    Γ = 10^(−RL_dB / 20)        (from the SSA)
    |Z| = 50 × (1 + Γ) / (1 − Γ)   (impedance magnitude, Ω, 50 Ω system)

This gives only magnitude — complex Z requires a full VNA.  But |Z| vs frequency
is the primary design metric for HF chokes.

Calibration: connect open circuit to DUT port = "100% reflection" baseline.
This is the same as the antenna analyzer open-circuit calibration.

Setup: connect choke between DUT port and ground.
  - Common-mode measurement: far end of choke is open-circuited (floating)
  - Differential-mode measurement: far end connected to ground

Usage:
  python balun_analyzer.py                    # HF sweep (1–30 MHz, default)
  python balun_analyzer.py --hf               # same
  python balun_analyzer.py --vhf              # 30–300 MHz
  python balun_analyzer.py --start 1000 --stop 30000
  python balun_analyzer.py --calibrate        # calibrate open circuit
  python balun_analyzer.py --compare prev.json   # overlay comparison
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
from rf_bench import connect
    format_freq, format_freq_short, nearest_rbw,
)

# ---------------------------------------------------------------------------
# Defaults
# ---------------------------------------------------------------------------

DEFAULT_SSA_HOST    = None  # Now uses inventory
DEFAULT_INSTRUMENT_PORT = 5025
DEFAULT_START_KHZ   = 1_000        # 1 MHz
DEFAULT_STOP_KHZ    = 30_000       # 30 MHz
DEFAULT_POINTS      = 301
DEFAULT_TG_LEVEL    = 0.0          # dBm; 0 dBm = max TG output = best SNR
DEFAULT_CAL_FILE    = os.path.expanduser("~/.balun_cal.npz")
SYSTEM_Z0           = 50.0         # Ω; reference impedance

# Impedance reference lines drawn on the plot
IMPEDANCE_REFS = [
    (500,   "500 Ω (minimum useful)"),
    (1_000, "1 kΩ"),
    (5_000, "5 kΩ"),
    (10_000,"10 kΩ"),
]

# Band shortcuts
BAND_PRESETS = {
    "hf":  (1_000,   30_000,   "HF (1–30 MHz)"),
    "vhf": (30_000,  300_000,  "VHF (30–300 MHz)"),
    "uhf": (300_000, 1_000_000,"UHF (300 MHz–1 GHz)"),
}


# ---------------------------------------------------------------------------
# Impedance math — local, not in rf_bench.utils
# ---------------------------------------------------------------------------

def rl_to_gamma(rl_db: np.ndarray) -> np.ndarray:
    """Return loss (positive dB) → reflection coefficient magnitude Γ."""
    return np.power(10.0, -np.abs(rl_db) / 20.0)


def gamma_to_impedance(gamma: np.ndarray, z0: float = SYSTEM_Z0) -> np.ndarray:
    """
    Γ → |Z| in ohms (scalar, assumes purely real, 50 Ω reference).

    Γ = (Z − Z0) / (Z + Z0)  →  Z = Z0 · (1 + Γ) / (1 − Γ)

    This gives magnitude only.  Near Γ=1 (open circuit), |Z| → ∞.
    Near Γ=0 (matched), |Z| = 50 Ω.
    Clamp Γ < 0.999 to avoid divide-by-zero.
    """
    gamma_clamped = np.clip(gamma, 0.0, 0.999)
    return z0 * (1.0 + gamma_clamped) / (1.0 - gamma_clamped)


# ---------------------------------------------------------------------------
# Calibration file I/O
# ---------------------------------------------------------------------------

def save_cal(path: str, open_trace: np.ndarray, host: str,
             start_hz: int, stop_hz: int, points: int):
    """Save open-circuit calibration trace to .npz."""
    meta = json.dumps({
        "timestamp": datetime.now().isoformat(),
        "host":      host,
        "start_hz":  start_hz,
        "stop_hz":   stop_hz,
        "points":    points,
    })
    np.savez(path,
             open_trace=open_trace,
             _meta=np.array([meta]))
    print(f"Calibration saved → {path}")


def load_cal(path: str) -> tuple[np.ndarray, dict]:
    """Load open-circuit calibration.  Returns (trace, meta)."""
    data = np.load(path, allow_pickle=False)
    meta: dict = {}
    if "_meta" in data.files:
        try:
            meta = json.loads(str(data["_meta"][0]))
        except (json.JSONDecodeError, IndexError):
            pass
    if "open_trace" not in data.files:
        raise ValueError(f"{path} contains no 'open_trace' array")
    return data["open_trace"], meta


# ---------------------------------------------------------------------------
# Sweep and measurement
# ---------------------------------------------------------------------------

def calibrate(ssa: SSA3000X, start_hz: int, stop_hz: int,
              points: int) -> np.ndarray:
    """Sweep with open circuit and return the calibration trace."""
    rbw = ssa.setup_band(start_hz, stop_hz, points)
    print(f"\n[CALIBRATION] RBW={rbw/1000:.0f} kHz ...", end=" ", flush=True)
    ok = ssa.single_sweep()
    trace = ssa.get_trace()
    print(f"done ({len(trace)} pts)" + ("" if ok else " [WARN: *OPC timeout]"))
    return trace


def measure_choke(ssa: SSA3000X, start_hz: int, stop_hz: int, points: int,
                  cal_trace: np.ndarray | None) -> dict:
    """
    Measure choking impedance.  Returns a dict with:
      freqs_hz, trace_dbm, rl_db, gamma, impedance_ohm
    """
    rbw = ssa.setup_band(start_hz, stop_hz, points)
    print(f"\n[MEASUREMENT] RBW={rbw/1000:.0f} kHz ...", end=" ", flush=True)
    ok = ssa.single_sweep()
    trace = ssa.get_trace()
    print(f"done ({len(trace)} pts)" + ("" if ok else " [WARN: *OPC timeout]"))

    freqs = np.linspace(start_hz, stop_hz, len(trace))

    if cal_trace is not None:
        cal = cal_trace
        if len(cal) != len(trace):
            cal = np.interp(np.linspace(0, 1, len(trace)),
                            np.linspace(0, 1, len(cal)), cal)
        rl_db = cal - trace
    else:
        print("  WARNING: no calibration — return loss values are estimates only.")
        rl_db = -trace

    # Return loss should be positive (reflected power); clamp negatives to 0
    rl_db = np.clip(rl_db, 0.0, 80.0)
    gamma = rl_to_gamma(rl_db)
    z_mag = gamma_to_impedance(gamma)

    peak_idx  = int(np.argmax(z_mag))
    peak_z    = float(z_mag[peak_idx])
    peak_freq = float(freqs[peak_idx])

    print(f"  Peak |Z|  : {peak_z:.0f} Ω @ {format_freq(peak_freq)}")
    print(f"  |Z| at start: {z_mag[0]:.0f} Ω  at stop: {z_mag[-1]:.0f} Ω")

    return dict(
        freqs_hz       = freqs,
        trace_dbm      = trace,
        rl_db          = rl_db,
        gamma          = gamma,
        impedance_ohm  = z_mag,
        calibrated     = cal_trace is not None,
        peak_z         = peak_z,
        peak_freq      = peak_freq,
    )


# ---------------------------------------------------------------------------
# Plotting
# ---------------------------------------------------------------------------

def generate_plot(result: dict, output_prefix: str,
                  compare_data: dict | None = None) -> str:
    """Plot choking impedance |Z| vs frequency on log Y scale."""
    freqs_mhz = result['freqs_hz'] / 1e6
    z_mag     = result['impedance_ohm']

    fig, ax = plt.subplots(figsize=(10, 5))

    # Reference lines
    for z_ref, label in IMPEDANCE_REFS:
        ax.axhline(z_ref, color='gray', linestyle='--', linewidth=0.8, alpha=0.5)
        ax.text(freqs_mhz[-1], z_ref * 1.08, label,
                fontsize=7, ha='right', va='bottom', color='gray', alpha=0.8)

    # Comparison trace
    if compare_data is not None:
        cmp_f   = np.array(compare_data['freqs_hz']) / 1e6
        cmp_z   = np.array(compare_data['impedance_ohm'])
        cmp_lbl = compare_data.get('label', 'Reference')
        ax.semilogy(cmp_f, cmp_z, color='gray', linewidth=1.2,
                    linestyle='--', alpha=0.7, label=cmp_lbl)

    # Main trace
    ax.semilogy(freqs_mhz, z_mag, color='#1f77b4', linewidth=1.8,
                label=f"|Z| (measured{'— calibrated' if result['calibrated'] else '— UNCAL'})")

    # Peak annotation
    pz   = result['peak_z']
    pf   = result['peak_freq'] / 1e6
    ax.plot(pf, pz, 'r*', markersize=14,
            label=f'Peak: {pz:.0f} Ω @ {format_freq_short(result["peak_freq"])}')
    ax.annotate(
        f'{pz:.0f} Ω\n@ {format_freq_short(result["peak_freq"])}',
        xy=(pf, pz),
        xytext=(pf, pz * 2.0),
        fontsize=8,
        ha='center',
        arrowprops=dict(arrowstyle='->', color='red', lw=1.2),
        color='red',
    )

    cal_note = "calibrated" if result['calibrated'] else "UNCALIBRATED"
    ax.set_xlabel("Frequency (MHz)", fontsize=10)
    ax.set_ylabel("Choking Impedance |Z| (Ω)", fontsize=10)
    ax.set_title(
        f"Balun / Common-Mode Choke Impedance — {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
        f"{format_freq_short(result['freqs_hz'][0])} – "
        f"{format_freq_short(result['freqs_hz'][-1])}  |  {cal_note}",
        fontsize=10,
    )
    ax.set_xlim(freqs_mhz[0], freqs_mhz[-1])
    ax.set_ylim(10, max(100_000, float(np.max(z_mag)) * 3))
    ax.grid(True, which='both', alpha=0.3)
    ax.legend(fontsize=9)
    ax.tick_params(labelsize=9)

    plt.tight_layout()
    path = f"{output_prefix}_choke.png"
    plt.savefig(path, dpi=150, bbox_inches='tight')
    plt.close(fig)
    return path


# ---------------------------------------------------------------------------
# Text report
# ---------------------------------------------------------------------------

def save_txt(result: dict, output_prefix: str) -> str:
    """Write text report.  Returns the path."""
    path = f"{output_prefix}_choke.txt"
    freqs = result['freqs_hz']
    z     = result['impedance_ohm']
    rl    = result['rl_db']
    ts    = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    sep   = "=" * 70
    lines = [
        sep,
        "  BALUN / COMMON-MODE CHOKE IMPEDANCE REPORT",
        f"  Generated   : {ts}",
        f"  Frequency   : {format_freq(freqs[0])} – {format_freq(freqs[-1])}",
        f"  Calibrated  : {'yes' if result['calibrated'] else 'NO — values are estimates'}",
        sep, "",
        f"  Peak |Z|    : {result['peak_z']:.0f} Ω  @ {format_freq(result['peak_freq'])}",
        f"  |Z| at start: {z[0]:.0f} Ω  ({format_freq(freqs[0])})",
        f"  |Z| at stop : {z[-1]:.0f} Ω  ({format_freq(freqs[-1])})",
        "",
    ]

    # Band effectiveness summary
    lines.append("  Band Effectiveness:")
    # HF bands of interest (MHz start/stop, name)
    check_bands = [
        (1.8, 2.0, "160m"), (3.5, 4.0, "80m"), (7.0, 7.3, "40m"),
        (10.1, 10.15, "30m"), (14.0, 14.35, "20m"), (18.07, 18.17, "17m"),
        (21.0, 21.45, "15m"), (24.89, 24.99, "12m"), (28.0, 29.7, "10m"),
    ]
    for bstart_mhz, bstop_mhz, bname in check_bands:
        bstart_hz = bstart_mhz * 1e6
        bstop_hz  = bstop_mhz  * 1e6
        if bstart_hz > freqs[-1] or bstop_hz < freqs[0]:
            continue
        # Find indices within band
        mask = (freqs >= bstart_hz) & (freqs <= bstop_hz)
        if not np.any(mask):
            continue
        z_band = z[mask]
        z_min  = float(np.min(z_band))
        z_med  = float(np.median(z_band))
        if z_min >= 5_000:
            quality = "Excellent (≥5 kΩ min)"
        elif z_min >= 1_000:
            quality = "Good (≥1 kΩ min)"
        elif z_min >= 500:
            quality = "Fair (≥500 Ω min)"
        else:
            quality = "Poor (<500 Ω min)"
        lines.append(
            f"    {bname:<6}  min={z_min:>6.0f} Ω  med={z_med:>6.0f} Ω  {quality}"
        )

    lines += ["", f"  {'Frequency':>16}  {'|Z|':>10}  {'RL':>8}  {'Γ':>6}"]
    lines.append("  " + "-" * 48)
    step = max(1, len(freqs) // 40)
    for i in range(0, len(freqs), step):
        gamma_val = float(result['gamma'][i])
        lines.append(
            f"  {format_freq(freqs[i]):>16}  "
            f"{z[i]:>8.0f} Ω  "
            f"{rl[i]:>6.1f} dB  "
            f"{gamma_val:>6.4f}"
        )

    text = "\n".join(lines) + "\n"
    with open(path, "w") as fh:
        fh.write(text)
    return path


def save_json_result(result: dict, output_prefix: str,
                     start_hz: int, stop_hz: int, ssa_host: str,
                     compare_file: str | None) -> str:
    """Save full measurement data as JSON for future --compare use."""
    path = f"{output_prefix}_choke.json"
    data = {
        "timestamp":      datetime.now().isoformat(),
        "ssa_host":       ssa_host,
        "start_hz":       start_hz,
        "stop_hz":        stop_hz,
        "calibrated":     result['calibrated'],
        "peak_z_ohm":     result['peak_z'],
        "peak_freq_hz":   result['peak_freq'],
        "label":          f"{datetime.now().strftime('%Y-%m-%d')}",
        "freqs_hz":       result['freqs_hz'].tolist(),
        "impedance_ohm":  result['impedance_ohm'].tolist(),
        "rl_db":          result['rl_db'].tolist(),
        "gamma":          result['gamma'].tolist(),
    }
    if compare_file:
        data["compared_with"] = compare_file
    with open(path, "w") as jf:
        json.dump(data, jf, indent=2)
    return path


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Balun / Common-Mode Choke Impedance Analyzer",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Setup:
  SSA TG Out ──── RB3X25 TG port
  RB3X25 SA port ──── SSA RF In
  RB3X25 DUT port ──── one end of choke
  Far end of choke: OPEN for common-mode measurement
                    GROUNDED for differential-mode measurement

Calibration (open circuit):
  RB3X25 DUT port ──── OPEN (nothing connected)

Interpretation:
  High impedance (>1 kΩ) = choke is effective at blocking common-mode current.
  Low impedance (<500 Ω) = poor choke; common-mode current will flow.
  The peak impedance frequency is where the choke is most effective.

Examples:
  python balun_analyzer.py                     # HF sweep (1–30 MHz)
  python balun_analyzer.py --hf                # same
  python balun_analyzer.py --vhf               # VHF (30–300 MHz)
  python balun_analyzer.py --start 1000 --stop 50000
  python balun_analyzer.py --calibrate
  python balun_analyzer.py --compare prev_choke.json
""",
    )

    parser.add_argument("--start",    type=float, default=None,
                        metavar="KHZ", help="Start frequency in kHz")
    parser.add_argument("--stop",     type=float, default=None,
                        metavar="KHZ", help="Stop frequency in kHz")
    parser.add_argument("--points",   type=int,   default=DEFAULT_POINTS,
                        metavar="N",   help=f"Sweep points (default {DEFAULT_POINTS})")
    parser.add_argument("--hf",       action="store_true",
                        help="HF preset: 1–30 MHz (default if no range specified)")
    parser.add_argument("--vhf",      action="store_true",
                        help="VHF preset: 30–300 MHz")
    parser.add_argument("--uhf",      action="store_true",
                        help="UHF preset: 300 MHz–1 GHz")
    parser.add_argument("--cal-file", default=DEFAULT_CAL_FILE, metavar="FILE",
                        help=f"Calibration file path (default: {DEFAULT_CAL_FILE})")
    parser.add_argument("--calibrate", action="store_true",
                        help="Run open-circuit calibration and save; then exit")
    parser.add_argument("--compare",  default=None, metavar="FILE",
                        help="Overlay a previous measurement JSON for comparison")
    parser.add_argument("--ssa-host", default=DEFAULT_SSA_HOST, metavar="HOST",
                        help=f"SSA IP address (default {DEFAULT_SSA_HOST})")
    parser.add_argument("--output",   default=None, metavar="PREFIX",
                        help="Output filename prefix (default: timestamped)")
    parser.add_argument("--yes",      action="store_true",
                        help="Skip interactive prompts")

    args = parser.parse_args()

    if args.output is None:
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        args.output = f"balun_{ts}"

    # Resolve frequency range
    # Priority: explicit --start/--stop > band shortcuts > default HF
    if args.start is not None or args.stop is not None:
        start_khz = args.start if args.start is not None else DEFAULT_START_KHZ
        stop_khz  = args.stop  if args.stop  is not None else DEFAULT_STOP_KHZ
    elif args.vhf:
        start_khz, stop_khz, band_label = BAND_PRESETS['vhf']
        print(f"Band preset: {band_label}")
    elif args.uhf:
        start_khz, stop_khz, band_label = BAND_PRESETS['uhf']
        print(f"Band preset: {band_label}")
    else:
        # Default or --hf
        start_khz, stop_khz, band_label = BAND_PRESETS['hf']
        if args.hf:
            print(f"Band preset: {band_label}")

    start_hz = int(start_khz * 1_000)
    stop_hz  = int(stop_khz  * 1_000)
    start_hz = max(9_000, start_hz)   # SSA3032X Plus minimum

    if start_hz >= stop_hz:
        print("Error: start frequency must be less than stop frequency")
        sys.exit(1)

    def prompt(msg: str):
        print(msg)
        if not args.yes:
            input("Press Enter when ready...")

    # Load comparison data
    compare_data = None
    if args.compare:
        try:
            with open(args.compare) as cf:
                compare_data = json.load(cf)
            print(f"Loaded comparison: {args.compare}  "
                  f"(peak {compare_data.get('peak_z_ohm', '?'):.0f} Ω "
                  f"@ {format_freq_short(compare_data.get('peak_freq_hz', 0))})")
        except Exception as exc:
            print(f"Warning: could not load comparison file: {exc}")

    ssa = None
    try:
        print(f"Connecting to SSA via inventory'} ...")
        ssa = connect(args.ssa_host or 'ssa')
        print(f"  {ssa.identify()}")

        print(f"Enabling tracking generator ({DEFAULT_TG_LEVEL:+.0f} dBm) ...")
        tg_ok = ssa.enable_tracking_generator(DEFAULT_TG_LEVEL)
        if not tg_ok:
            print("  WARNING: TG state query returned unexpected value — check front panel.")

        # Load calibration
        cal_trace: np.ndarray | None = None
        try:
            cal_trace, cal_meta = load_cal(args.cal_file)
            print(f"Loaded calibration from {args.cal_file}")
            print(f"  Taken: {cal_meta.get('timestamp', 'unknown')}")
        except FileNotFoundError:
            print(f"No calibration file at {args.cal_file}.")

        # ----------------------------------------------------------------
        # Calibration mode
        # ----------------------------------------------------------------
        if args.calibrate:
            prompt(
                "\nCALIBRATION: Connect OPEN circuit to the DUT port of the reflection bridge\n"
                "(disconnect the choke / leave the DUT port floating)."
            )
            cal_trace = calibrate(ssa, start_hz, stop_hz, args.points)
            save_cal(args.cal_file, cal_trace, args.ssa_host, start_hz, stop_hz, args.points)
            print("Calibration complete.  Run without --calibrate to measure a DUT.")
            return

        # ----------------------------------------------------------------
        # Auto-calibrate if no calibration file
        # ----------------------------------------------------------------
        if cal_trace is None:
            prompt(
                "\nNo calibration found.  Connect OPEN circuit to the DUT port of the\n"
                "reflection bridge (leave DUT port floating)."
            )
            cal_trace = calibrate(ssa, start_hz, stop_hz, args.points)
            save_cal(args.cal_file, cal_trace, args.ssa_host, start_hz, stop_hz, args.points)

        # ----------------------------------------------------------------
        # Measurement
        # ----------------------------------------------------------------
        prompt(
            "\nMEASUREMENT: Connect the choke/balun DUT to the reflection bridge.\n"
            "  RB3X25 DUT port ──── one end of choke\n"
            "  Far end of choke:  OPEN for common-mode, GROUNDED for differential-mode"
        )

        result = measure_choke(ssa, start_hz, stop_hz, args.points, cal_trace)

        # ----------------------------------------------------------------
        # Save outputs
        # ----------------------------------------------------------------
        print("\n[SAVING RESULTS]")

        txt_path = save_txt(result, args.output)
        print(f"Text   → {txt_path}")

        json_path = save_json_result(result, args.output, start_hz, stop_hz,
                                     args.ssa_host, args.compare)
        print(f"JSON   → {json_path}")

        try:
            png_path = generate_plot(result, args.output, compare_data)
            print(f"Plot   → {png_path}")
        except Exception as exc:
            print(f"Plot generation failed: {exc}")

        # Summary
        z = result['impedance_ohm']
        print(f"\nPeak |Z|: {result['peak_z']:.0f} Ω  @ {format_freq_short(result['peak_freq'])}")
        print(f"Range:    {np.min(z):.0f} – {np.max(z):.0f} Ω  "
              f"(median {np.median(z):.0f} Ω)")

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
