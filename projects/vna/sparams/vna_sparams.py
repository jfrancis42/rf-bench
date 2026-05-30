#!/usr/bin/env python3
"""
vna_sparams.py — HP 8712B Full S-Parameter Suite with SOLT Calibration

Requires HP 8712B VNA and rf-bench-drivers-hp. The HP 8712B is not currently
connected — requires KISS-488 Ethernet-GPIB adapter.

Measures all four S-parameters (S11, S21, S12, S22), or any requested subset.
For each parameter, captures magnitude (dB) and phase (degrees).  Optionally
runs an interactive SOLT calibration sequence before measurement.

Outputs:
  {prefix}.png    — 2×2 magnitude grid + 2×2 phase grid (separate figures)
  {prefix}.txt    — tabulated frequency / mag / phase for each parameter
  {prefix}.json   — all data in JSON for post-processing
  {prefix}.s2p    — Touchstone S2P file (S11 S21 S12 S22, real+imag)

Usage:
  python vna_sparams.py
  python vna_sparams.py --params S11,S21 --calibrate
  python vna_sparams.py --start 1000 --stop 500000 --points 801
  python vna_sparams.py --use-cal --output dut_filter
"""

import argparse
import json
import sys
import time
from datetime import datetime

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np

from rf_bench.hp import HP8712B

# ---------------------------------------------------------------------------
# Defaults
# ---------------------------------------------------------------------------

DEFAULT_HOST       = "10.1.1.70"
DEFAULT_START_KHZ  = 300          # HP 8712B minimum: 300 kHz
DEFAULT_STOP_KHZ   = 1_300_000    # HP 8712B maximum: 1.3 GHz
DEFAULT_POINTS     = 401
DEFAULT_POWER_DBM  = -10.0
DEFAULT_AVERAGES   = 0

ALL_PARAMS = ["S11", "S21", "S12", "S22"]

# ---------------------------------------------------------------------------
# SOLT calibration helpers
# ---------------------------------------------------------------------------

SOLT_STEPS = [
    ("OPEN",  "Connect OPEN standard to PORT 1"),
    ("SHORT", "Connect SHORT standard to PORT 1"),
    ("LOAD",  "Connect LOAD (50 Ω) standard to PORT 1"),
    ("THRU",  "Connect THRU between PORT 1 and PORT 2"),
]


def run_solt_calibration(vna: HP8712B) -> None:
    """
    Interactive SOLT calibration sequence.

    Prompts the user to connect each standard, then triggers a sweep for
    each step.  The HP 8712B stores the cal data internally; after completion
    call correction_on() to apply it.

    Note: The HP 8712B 2-port SOLT cal commands (:SENS:CORR:COLL:*) should
    be verified against the HP 8712B Network Analyzer Programmer's Guide.
    This sequence follows the general HP VNA SOLT flow.
    """
    print("\n[SOLT CALIBRATION]")
    print("Follow each prompt, then press ENTER to acquire the standard.")
    print()

    for standard, instruction in SOLT_STEPS:
        print(f"  {instruction}")
        input("  Press ENTER when ready... ")
        # Acquire calibration standard — command syntax per HP 8712B manual
        vna.send(f":SENS:CORR:COLL:{standard}")   # Verify against HP 8712B manual
        ok = vna.single_sweep()
        if not ok:
            print(f"  WARNING: sweep timed out during {standard} acquisition")
        else:
            print(f"  {standard} acquired.")
        print()

    # Apply the calibration
    vna.send(":SENS:CORR:COLL:SAVE")              # Verify against HP 8712B manual
    print("  Calibration applied.")
    vna.correction_on()
    print("  Error correction ON.")


# ---------------------------------------------------------------------------
# Measurement
# ---------------------------------------------------------------------------

def measure_sparams(vna: HP8712B, params: list, start_hz: float,
                    stop_hz: float, points: int, power_dbm: float,
                    averages: int) -> dict:
    """
    Measure magnitude and phase for each requested S-parameter.

    Returns a dict:
      freqs_hz     — np.ndarray (Hz)
      data         — dict keyed by param name, each with 'mag_db', 'phase_deg', 'complex'
    """
    vna.setup_sweep(start_hz, stop_hz, points)
    vna.set_power(power_dbm)
    vna.set_averaging(averages)

    # Capture frequency axis once
    vna.set_parameter(params[0])
    vna.set_format("MLOG")
    vna.single_sweep()
    freqs_hz = vna.get_frequencies()

    result = {"freqs_hz": freqs_hz, "data": {}}

    for param in params:
        print(f"  Measuring {param} ...", end="", flush=True)
        vna.set_parameter(param)

        # Magnitude
        vna.set_format("MLOG")
        ok = vna.single_sweep()
        if not ok:
            print(f" WARN: sweep timeout on {param} magnitude")
        mag_db = vna.get_trace_db()

        # Phase
        vna.set_format("PHAS")
        ok = vna.single_sweep()
        if not ok:
            print(f" WARN: sweep timeout on {param} phase")
        phase_deg = vna.get_trace_phase()

        # Complex (raw S-data for Touchstone)
        s_complex = vna.get_s_data()

        result["data"][param] = {
            "mag_db":    mag_db,
            "phase_deg": phase_deg,
            "complex":   s_complex,
        }
        print(f" done  (peak {np.max(mag_db):+.1f} dB, "
              f"range {np.min(mag_db):.1f}…{np.max(mag_db):.1f} dB)")

    return result


# ---------------------------------------------------------------------------
# Touchstone .s2p output
# ---------------------------------------------------------------------------

def save_s2p(result: dict, prefix: str, params_measured: list) -> str:
    """
    Save a Touchstone S2P file.

    Uses real/imag format (RI) with 50 Ω reference.  Missing S-parameters
    are written as 0+0j.
    """
    path = f"{prefix}.s2p"
    freqs = result["freqs_hz"]
    n = len(freqs)

    # Build arrays for all four S-params; default to 0+0j if not measured
    def get_cpx(p):
        if p in result["data"]:
            return result["data"][p]["complex"]
        return np.zeros(n, dtype=complex)

    s11 = get_cpx("S11")
    s21 = get_cpx("S21")
    s12 = get_cpx("S12")
    s22 = get_cpx("S22")

    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with open(path, "w") as f:
        f.write(f"! HP 8712B S-parameters  {ts}\n")
        f.write(f"! Measured params: {', '.join(params_measured)}\n")
        f.write("# Hz S RI R 50\n")
        f.write("! freq  Re(S11) Im(S11)  Re(S21) Im(S21)  Re(S12) Im(S12)  Re(S22) Im(S22)\n")
        for i in range(n):
            f.write(f"{freqs[i]:.6e}"
                    f"  {s11[i].real: .8e}  {s11[i].imag: .8e}"
                    f"  {s21[i].real: .8e}  {s21[i].imag: .8e}"
                    f"  {s12[i].real: .8e}  {s12[i].imag: .8e}"
                    f"  {s22[i].real: .8e}  {s22[i].imag: .8e}\n")
    return path


# ---------------------------------------------------------------------------
# Text output
# ---------------------------------------------------------------------------

def save_txt(result: dict, prefix: str, params: list,
             start_hz: float, stop_hz: float, points: int,
             power_dbm: float, averages: int, host: str,
             use_cal: bool) -> str:
    """Save tabulated data as plain text."""
    path = f"{prefix}.txt"
    freqs = result["freqs_hz"]
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    with open(path, "w") as f:
        f.write(f"HP 8712B S-Parameter Measurement\n")
        f.write(f"{'='*60}\n")
        f.write(f"Date/time  : {ts}\n")
        f.write(f"Instrument : {host}\n")
        f.write(f"Start      : {start_hz/1e6:.6f} MHz\n")
        f.write(f"Stop       : {stop_hz/1e6:.6f} MHz\n")
        f.write(f"Points     : {points}\n")
        f.write(f"Power      : {power_dbm:.1f} dBm\n")
        f.write(f"Averages   : {averages if averages > 1 else 'off'}\n")
        f.write(f"Cal        : {'on' if use_cal else 'off'}\n")
        f.write(f"Params     : {', '.join(params)}\n\n")

        # Header
        hdr = f"{'Freq (MHz)':>14}"
        for p in params:
            hdr += f"  {p+' mag (dB)':>14}  {p+' phase (°)':>14}"
        f.write(hdr + "\n")
        f.write("-" * len(hdr) + "\n")

        for i in range(len(freqs)):
            row = f"{freqs[i]/1e6:>14.6f}"
            for p in params:
                d = result["data"][p]
                row += (f"  {d['mag_db'][i]:>14.4f}"
                        f"  {d['phase_deg'][i]:>14.4f}")
            f.write(row + "\n")
    return path


# ---------------------------------------------------------------------------
# Plots
# ---------------------------------------------------------------------------

def plot_magnitude(result: dict, params: list, prefix: str,
                   start_hz: float, stop_hz: float) -> str:
    """2×2 grid of magnitude plots."""
    freqs_mhz = result["freqs_hz"] / 1e6
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    fig, axes = plt.subplots(2, 2, figsize=(14, 9))
    fig.suptitle(f"HP 8712B — S-Parameter Magnitude\n"
                 f"{start_hz/1e6:.4f} – {stop_hz/1e6:.0f} MHz  |  {ts}",
                 fontsize=11)

    grid_params = ["S11", "S21", "S12", "S22"]
    for idx, param in enumerate(grid_params):
        ax = axes[idx // 2][idx % 2]
        if param in result["data"]:
            ax.plot(freqs_mhz, result["data"][param]["mag_db"], color="steelblue",
                    linewidth=0.8)
            peak = np.max(result["data"][param]["mag_db"])
            min_ = np.min(result["data"][param]["mag_db"])
            ax.set_title(f"{param}  (peak {peak:+.1f} dB, min {min_:+.1f} dB)",
                         fontsize=9)
        else:
            ax.text(0.5, 0.5, "not measured", transform=ax.transAxes,
                    ha="center", va="center", color="gray")
            ax.set_title(param, fontsize=9)

        ax.set_xlabel("Frequency (MHz)", fontsize=8)
        ax.set_ylabel("Magnitude (dB)", fontsize=8)
        ax.grid(True, alpha=0.4)
        ax.tick_params(labelsize=8)

    fig.tight_layout()
    path = f"{prefix}_mag.png"
    fig.savefig(path, dpi=150, bbox_inches="tight")
    plt.close(fig)
    return path


def plot_phase(result: dict, params: list, prefix: str,
               start_hz: float, stop_hz: float) -> str:
    """2×2 grid of phase plots."""
    freqs_mhz = result["freqs_hz"] / 1e6
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    fig, axes = plt.subplots(2, 2, figsize=(14, 9))
    fig.suptitle(f"HP 8712B — S-Parameter Phase\n"
                 f"{start_hz/1e6:.4f} – {stop_hz/1e6:.0f} MHz  |  {ts}",
                 fontsize=11)

    grid_params = ["S11", "S21", "S12", "S22"]
    for idx, param in enumerate(grid_params):
        ax = axes[idx // 2][idx % 2]
        if param in result["data"]:
            ax.plot(freqs_mhz, result["data"][param]["phase_deg"],
                    color="darkorange", linewidth=0.8)
            ax.set_title(f"{param} Phase", fontsize=9)
        else:
            ax.text(0.5, 0.5, "not measured", transform=ax.transAxes,
                    ha="center", va="center", color="gray")
            ax.set_title(param, fontsize=9)

        ax.set_xlabel("Frequency (MHz)", fontsize=8)
        ax.set_ylabel("Phase (degrees)", fontsize=8)
        ax.set_ylim(-185, 185)
        ax.grid(True, alpha=0.4)
        ax.tick_params(labelsize=8)

    fig.tight_layout()
    path = f"{prefix}_phase.png"
    fig.savefig(path, dpi=150, bbox_inches="tight")
    plt.close(fig)
    return path


# ---------------------------------------------------------------------------
# main()
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="HP 8712B Full S-Parameter Suite with SOLT Calibration",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Setup:
  2-port DUT connected to HP 8712B PORT 1 and PORT 2.
  For SOLT calibration, have calibration standards (Open, Short, Load, Thru) ready.

Examples:
  python vna_sparams.py                                 # all 4 params, no cal
  python vna_sparams.py --params S11,S21 --calibrate   # 2-param with SOLT cal
  python vna_sparams.py --use-cal --output dut_filter  # apply stored cal
  python vna_sparams.py --start 1000 --stop 500000 --points 801
""",
    )

    parser.add_argument("--start",      type=float, default=DEFAULT_START_KHZ,
                        metavar="KHZ",
                        help=f"Start frequency in kHz (default {DEFAULT_START_KHZ})")
    parser.add_argument("--stop",       type=float, default=DEFAULT_STOP_KHZ,
                        metavar="KHZ",
                        help=f"Stop frequency in kHz (default {DEFAULT_STOP_KHZ})")
    parser.add_argument("--points",     type=int,   default=DEFAULT_POINTS,
                        metavar="N",
                        help=f"Sweep points, 1–801 (default {DEFAULT_POINTS})")
    parser.add_argument("--params",     type=str,   default="S11,S21,S12,S22",
                        metavar="LIST",
                        help="Comma-separated S-params to measure (default: S11,S21,S12,S22)")
    parser.add_argument("--power",      type=float, default=DEFAULT_POWER_DBM,
                        metavar="DBM",
                        help=f"Stimulus power in dBm (default {DEFAULT_POWER_DBM})")
    parser.add_argument("--averages",   type=int,   default=DEFAULT_AVERAGES,
                        metavar="N",
                        help="Number of averages (0 = off, default 0)")
    parser.add_argument("--calibrate",  action="store_true",
                        help="Run interactive SOLT calibration before measurement")
    parser.add_argument("--use-cal",    action="store_true",
                        help="Enable stored calibration correction before measurement")
    parser.add_argument("--host",       default=DEFAULT_HOST,
                        metavar="HOST",
                        help=f"KISS-488 IP address (default {DEFAULT_HOST})")
    parser.add_argument("--prefix",     default=None, metavar="TEXT",
                        help="Output filename prefix (default: timestamped)")

    args = parser.parse_args()

    if args.prefix is None:
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        args.prefix = f"vna_sparams_{ts}"

    # Parse and validate params
    params = [p.strip().upper() for p in args.params.split(",")]
    invalid = [p for p in params if p not in ALL_PARAMS]
    if invalid:
        print(f"Error: unknown S-parameter(s): {invalid}")
        print(f"Valid: {ALL_PARAMS}")
        sys.exit(1)

    start_hz = args.start * 1_000.0
    stop_hz  = args.stop  * 1_000.0
    if start_hz >= stop_hz:
        print("Error: --start must be less than --stop")
        sys.exit(1)
    if start_hz < 300_000:
        print(f"Warning: HP 8712B minimum is 300 kHz; clamping start to 300 kHz")
        start_hz = 300_000.0
    if stop_hz > 1_300_000_000:
        print(f"Warning: HP 8712B maximum is 1.3 GHz; clamping stop to 1.3 GHz")
        stop_hz = 1_300_000_000.0
    if args.points > 801:
        print(f"Warning: HP 8712B maximum is 801 points; clamping to 801")
        args.points = 801

    print(f"HP 8712B S-Parameter Suite")
    print(f"  Host       : {args.host}")
    print(f"  Sweep      : {start_hz/1e6:.4f} – {stop_hz/1e6:.0f} MHz, {args.points} pts")
    print(f"  Power      : {args.power:.1f} dBm")
    print(f"  Averages   : {args.averages if args.averages > 1 else 'off'}")
    print(f"  Params     : {', '.join(params)}")
    print(f"  Calibrate  : {'yes (SOLT)' if args.calibrate else 'no'}")
    print(f"  Use cal    : {args.use_cal}")
    print(f"  Prefix     : {args.prefix}")
    print()

    vna = None
    try:
        print(f"Connecting to HP 8712B @ {args.host} ...")
        vna = HP8712B(host=args.host)
        idn = vna.identify()
        print(f"  {idn}")

        if args.calibrate:
            run_solt_calibration(vna)
        elif args.use_cal:
            vna.correction_on()
            print(f"  Correction: {'ON' if vna.is_correction_on() else 'OFF (not available?)'}")

        print("\n[MEASURING]")
        result = measure_sparams(vna, params, start_hz, stop_hz,
                                 args.points, args.power, args.averages)

        # ---- Save outputs ----
        print("\n[SAVING RESULTS]")

        txt_path = save_txt(result, args.prefix, params,
                            start_hz, stop_hz, args.points,
                            args.power, args.averages, args.host,
                            args.use_cal or args.calibrate)
        print(f"Text   → {txt_path}")

        # JSON
        json_path = f"{args.prefix}.json"
        json_data = {
            "timestamp":   datetime.now().isoformat(),
            "host":        args.host,
            "start_hz":    start_hz,
            "stop_hz":     stop_hz,
            "points":      args.points,
            "power_dbm":   args.power,
            "averages":    args.averages,
            "params":      params,
            "calibrated":  args.calibrate or args.use_cal,
            "freqs_hz":    result["freqs_hz"].tolist(),
            "data": {
                p: {
                    "mag_db":    result["data"][p]["mag_db"].tolist(),
                    "phase_deg": result["data"][p]["phase_deg"].tolist(),
                    "complex_re": result["data"][p]["complex"].real.tolist(),
                    "complex_im": result["data"][p]["complex"].imag.tolist(),
                }
                for p in params
            },
        }
        with open(json_path, "w") as jf:
            json.dump(json_data, jf, indent=2)
        print(f"JSON   → {json_path}")

        # Touchstone S2P
        s2p_path = save_s2p(result, args.prefix, params)
        print(f"S2P    → {s2p_path}")

        # Plots
        try:
            mag_path = plot_magnitude(result, params, args.prefix, start_hz, stop_hz)
            print(f"Mag    → {mag_path}")
        except Exception as exc:
            print(f"Magnitude plot failed: {exc}")

        try:
            ph_path = plot_phase(result, params, args.prefix, start_hz, stop_hz)
            print(f"Phase  → {ph_path}")
        except Exception as exc:
            print(f"Phase plot failed: {exc}")

        # Summary
        print("\n[SUMMARY]")
        for p in params:
            d = result["data"][p]
            print(f"  {p}: {np.min(d['mag_db']):+.1f} dB min, "
                  f"{np.max(d['mag_db']):+.1f} dB max, "
                  f"{np.mean(d['mag_db']):+.1f} dB mean")

    except KeyboardInterrupt:
        print("\nInterrupted.")
        sys.exit(0)
    except ConnectionRefusedError as exc:
        print(f"\nCannot connect to HP 8712B: {exc}")
        print("Verify KISS-488 adapter is powered and at the correct IP.")
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
        if vna is not None:
            try:
                vna.marker_off()
                vna.close()
            except Exception:
                pass


if __name__ == "__main__":
    main()
