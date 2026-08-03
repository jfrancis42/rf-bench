#!/usr/bin/env python3
"""
Varactor/varicap diode characterizer — Siglent SPD3303X + SDG1000X + SDS2000X

Sweeps DC reverse-bias voltage and measures complex impedance of a varactor
at a fixed RF frequency using the series-injection circuit.  Extracts C(V)
and Q(V) at the actual operating frequency.

Physical circuit (connect before running):

    SDG CH1 → 50 Ω ref resistor → RF bypass cap (100 nF) → Varactor anode
                                                                   │
                                              RF choke (1 mH) ─── SPD CH1 (+)
         Scope CH1 ↑              Scope CH2 ↑
      (before ref R)          (after ref R, before varactor)
    Varactor cathode → GND = SPD CH1 (−) = Scope GND

The RF choke keeps the DC bias out of the RF path.
The bypass cap keeps DC off the SDG output.

Usage examples:
  python varactor.py --freq 14000 --vmin 1 --vmax 15 --vstep 0.5
  python varactor.py --freq 7000 --vmin 0.5 --vmax 12 --vstep 1.0
  python varactor.py --freq 21000 --vmin 2 --vmax 20 --vstep 0.5
"""

import argparse
import cmath
import json
import math
import os
import sys
import time
from datetime import datetime

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np

# ---------------------------------------------------------------------------
# Shared drivers
# ---------------------------------------------------------------------------

from rf_bench.siglent import SPD3303X, SDG1000X, SDS2000X        # noqa: E402
from rf_bench.utils import (                                       # noqa: E402
    complex_impedance_series, format_freq, format_freq_short,
    dbm_to_vpp,
)
from rf_bench import connect

# ---------------------------------------------------------------------------
# Defaults
# ---------------------------------------------------------------------------

DEFAULT_PSU_HOST   = None  # Now uses inventory
DEFAULT_SDG_HOST   = None  # Now uses inventory
DEFAULT_SCOPE_HOST = None  # Now uses inventory

DEFAULT_FREQ_KHZ   = 14_000      # 14 MHz (20 m)
DEFAULT_VMIN       = 1.0         # minimum bias voltage (V)
DEFAULT_VMAX       = 15.0        # maximum bias voltage (V)
DEFAULT_VSTEP      = 0.5         # voltage step (V)
DEFAULT_ZREF_OHM   = 50.0        # series reference resistor (Ω)
DEFAULT_PSU_CH     = 1

PSU_MAX_VOLTAGE    = 30.0        # V — absolute cap (SPD CH1/2 max)
PSU_CURRENT_LIMIT  = 0.010       # A — 10 mA; varactors need no current
SDG_LEVEL_DBM      = -20.0       # RF test level (about 20 mVpp — safe for varactor)
SETTLE_S           = 0.20        # wait after PSU voltage change
CAPTURE_S          = 0.10        # scope capture duration per measurement


# ---------------------------------------------------------------------------
# Measurement
# ---------------------------------------------------------------------------

def measure_one(sdg: SDG1000X, scope: SDS2000X,
                freq_hz: float, z_ref_ohm: float) -> complex:
    """
    Capture CH1 and CH2 and return the complex impedance of the varactor
    at freq_hz using the series injection circuit.
    """
    ch1, sr = scope.capture_audio(channel=1, duration_s=CAPTURE_S)
    ch2, _  = scope.capture_audio(channel=2, duration_s=CAPTURE_S)
    return complex_impedance_series(ch1, ch2, sr,
                                    z_ref_ohm=z_ref_ohm,
                                    freq_hz=freq_hz)


def extract_cv(z: complex, freq_hz: float) -> tuple[float, float, float, str]:
    """
    Extract C (farads), R_series (ohms), Q and a status string from Z.

    Returns (C_F, R_series_ohm, Q, status).
    For a capacitor, Z.imag should be negative.
    """
    r_series = z.real
    x = z.imag

    if x >= 0:
        # Inductive (resonance crossing or parasitic dominates at this frequency)
        c_f = float("nan")
        q   = float("nan")
        status = "INDUCTIVE"
    else:
        # Capacitive (normal for reverse-biased varactor)
        c_f = -1.0 / (2.0 * math.pi * freq_hz * x)
        # Q = |X| / R_series; guard against zero R_series
        if r_series > 0.0:
            q = abs(x) / r_series
        else:
            q = float("nan")
        status = "OK"

    return c_f, r_series, q, status


# ---------------------------------------------------------------------------
# Sweep
# ---------------------------------------------------------------------------

def run_sweep(psu: SPD3303X, sdg: SDG1000X, scope: SDS2000X,
              args) -> list[dict]:
    """
    Sweep bias voltage and measure varactor C and Q at each point.

    Returns a list of measurement dicts.
    """
    freq_hz = args.freq * 1_000.0
    v_points = np.arange(args.vmin, args.vmax + args.vstep / 2.0, args.vstep)
    n = len(v_points)

    print(f"\n[VARACTOR C(V) / Q(V) SWEEP]")
    print(f"  Frequency  : {format_freq_short(freq_hz)}")
    print(f"  Bias range : {args.vmin:.1f} V – {args.vmax:.1f} V  step {args.vstep:.2f} V")
    print(f"  Points     : {n}")
    print(f"  Z_ref      : {args.z_ref:.0f} Ω")
    print(f"  SDG level  : {SDG_LEVEL_DBM:+.0f} dBm  "
          f"(≈ {dbm_to_vpp(SDG_LEVEL_DBM)*1000:.0f} mVpp)")
    print()

    # Configure PSU
    psu.set_voltage(args.psu_ch, args.vmin)
    psu.set_current(args.psu_ch, PSU_CURRENT_LIMIT)
    psu.enable(args.psu_ch)
    time.sleep(SETTLE_S)

    # Configure SDG and enable RF
    sdg.set_sine(1, freq_hz, SDG_LEVEL_DBM)
    sdg.output_on(1)
    time.sleep(0.1)

    # Header
    print(f"  {'V_bias':>7}  {'C(pF)':>9}  {'R_s(Ω)':>9}  {'Q':>7}  Status")
    print("  " + "-" * 50)

    results = []

    for i, v_set in enumerate(v_points):
        # Clamp to PSU max
        v_set = min(float(v_set), PSU_MAX_VOLTAGE)

        psu.set_voltage(args.psu_ch, v_set)
        time.sleep(SETTLE_S)

        # Read actual voltage
        v_actual = psu.measure_voltage(args.psu_ch)

        # Impedance measurement
        z = measure_one(sdg, scope, freq_hz, args.z_ref)
        c_f, r_series, q, status = extract_cv(z, freq_hz)

        c_pf = c_f * 1e12 if math.isfinite(c_f) else float("nan")

        # Print row
        c_str = f"{c_pf:>9.2f}" if math.isfinite(c_pf) else "       N/A"
        r_str = f"{r_series:>9.2f}" if math.isfinite(r_series) else "       N/A"
        q_str = f"{q:>7.1f}"        if math.isfinite(q)        else "    N/A"
        print(f"  {v_actual:>7.3f}  {c_str}  {r_str}  {q_str}  {status}",
              flush=True)

        results.append({
            "v_set_v":      float(v_set),
            "v_actual_v":   float(v_actual),
            "z_real_ohm":   float(z.real),
            "z_imag_ohm":   float(z.imag),
            "c_f":          float(c_f)  if math.isfinite(c_f) else None,
            "c_pf":         float(c_pf) if math.isfinite(c_pf) else None,
            "r_series_ohm": float(r_series),
            "q":            float(q)    if math.isfinite(q)    else None,
            "status":       status,
        })

    return results


# ---------------------------------------------------------------------------
# Tuning ratio summary
# ---------------------------------------------------------------------------

def compute_tuning_ratio(results: list[dict]) -> float | None:
    """
    Return Cmax / Cmin from valid measurements, or None if insufficient data.
    """
    c_vals = [r["c_pf"] for r in results
              if r["c_pf"] is not None and r["c_pf"] > 0]
    if len(c_vals) < 2:
        return None
    return max(c_vals) / min(c_vals)


# ---------------------------------------------------------------------------
# Plotting
# ---------------------------------------------------------------------------

def plot_results(results: list[dict], output_prefix: str,
                 freq_hz: float, tuning_ratio: float | None) -> str:
    """Generate C(V) and Q(V) plot.  Returns saved file path."""
    # Filter for valid capacitance measurements
    valid = [r for r in results if r["c_pf"] is not None and r["c_pf"] > 0]
    inductive = [r for r in results if r["status"] == "INDUCTIVE"]

    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(9, 7), sharex=True)

    ts_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    # --- C(V) panel ---
    if valid:
        v_arr = [r["v_actual_v"] for r in valid]
        c_arr = [r["c_pf"]       for r in valid]
        ax1.plot(v_arr, c_arr, 'o-', color='#1f77b4', linewidth=1.8,
                 markersize=5, label='C (pF)')

        # Annotate tuning ratio
        if tuning_ratio is not None:
            c_max = max(c_arr)
            c_min = min(c_arr)
            v_cmax = v_arr[c_arr.index(c_max)]
            v_cmin = v_arr[c_arr.index(c_min)]
            textstr = (f"Cmax = {c_max:.2f} pF  @ {v_cmax:.2f} V\n"
                       f"Cmin = {c_min:.2f} pF  @ {v_cmin:.2f} V\n"
                       f"Tuning ratio = {tuning_ratio:.2f}:1")
            ax1.text(0.97, 0.97, textstr, transform=ax1.transAxes,
                     fontsize=8, verticalalignment='top', horizontalalignment='right',
                     bbox=dict(boxstyle='round', facecolor='lightyellow', alpha=0.85))

    # Mark inductive/invalid points
    if inductive:
        v_bad = [r["v_actual_v"] for r in inductive]
        ax1.scatter(v_bad, [0] * len(v_bad), marker='x', color='red', s=60,
                    zorder=5, label='Inductive / invalid')

    ax1.set_ylabel("Capacitance (pF)", fontsize=10)
    ax1.set_title(
        f"Varactor C(V) / Q(V)  —  {format_freq_short(freq_hz)}"
        f"  —  {ts_str}",
        fontsize=10,
    )
    ax1.grid(True, alpha=0.35)
    ax1.legend(fontsize=8)
    ax1.tick_params(labelsize=9)

    # --- Q(V) panel ---
    q_valid = [r for r in results if r["q"] is not None and math.isfinite(r["q"])]
    if q_valid:
        v_q = [r["v_actual_v"] for r in q_valid]
        q_arr = [r["q"]         for r in q_valid]
        ax2.plot(v_q, q_arr, 's-', color='darkorange', linewidth=1.8,
                 markersize=5, label='Q')

        q_med = float(np.median(q_arr))
        ax2.axhline(q_med, color='gray', linestyle='--', linewidth=0.8,
                    label=f'Median Q = {q_med:.1f}')

    ax2.set_xlabel("Reverse bias voltage (V)", fontsize=10)
    ax2.set_ylabel("Quality factor Q", fontsize=10)
    ax2.set_title("Q vs Bias Voltage", fontsize=10)
    ax2.grid(True, alpha=0.35)
    ax2.legend(fontsize=8)
    ax2.tick_params(labelsize=9)

    plt.tight_layout()
    path = f"{output_prefix}.png"
    plt.savefig(path, dpi=150, bbox_inches='tight')
    plt.close(fig)
    return path


# ---------------------------------------------------------------------------
# Text report
# ---------------------------------------------------------------------------

def save_txt(results: list[dict], output_prefix: str,
             freq_hz: float, z_ref: float,
             tuning_ratio: float | None) -> str:
    """Write tabular text report."""
    path = f"{output_prefix}.txt"
    ts   = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    sep  = "=" * 70

    lines = [
        sep,
        "  VARACTOR C(V) / Q(V) CHARACTERIZATION",
        f"  Generated  : {ts}",
        f"  Frequency  : {format_freq(freq_hz)}",
        f"  Z_ref      : {z_ref:.0f} Ω",
        f"  SDG level  : {SDG_LEVEL_DBM:+.0f} dBm",
        sep,
        "",
    ]

    if tuning_ratio is not None:
        c_vals = [r["c_pf"] for r in results if r["c_pf"] is not None]
        c_max = max(c_vals)
        c_min = min(c_vals)
        lines += [
            f"  Cmax         : {c_max:.3f} pF",
            f"  Cmin         : {c_min:.3f} pF",
            f"  Tuning ratio : {tuning_ratio:.3f}:1",
            "",
        ]

    lines.append(
        f"  {'V_set':>6}  {'V_actual':>8}  {'C(pF)':>10}  "
        f"{'R_s(Ω)':>9}  {'Q':>7}  Status"
    )
    lines.append("  " + "-" * 60)

    for r in results:
        c_str  = f"{r['c_pf']:>10.3f}"       if r['c_pf']   is not None else "       N/A"
        rs_str = f"{r['r_series_ohm']:>9.2f}"
        q_str  = f"{r['q']:>7.1f}"            if r['q']      is not None else "    N/A"
        lines.append(
            f"  {r['v_set_v']:>6.2f}  {r['v_actual_v']:>8.3f}  "
            f"{c_str}  {rs_str}  {q_str}  {r['status']}"
        )

    text = "\n".join(lines) + "\n"
    with open(path, "w") as fh:
        fh.write(text)
    return path


# ---------------------------------------------------------------------------
# JSON output
# ---------------------------------------------------------------------------

def save_json(results: list[dict], output_prefix: str,
              args, tuning_ratio: float | None) -> str:
    """Save full measurement data as JSON."""
    path = f"{output_prefix}.json"
    data = {
        "timestamp":     datetime.now().isoformat(),
        "freq_hz":       args.freq * 1_000.0,
        "freq_khz":      args.freq,
        "vmin_v":        args.vmin,
        "vmax_v":        args.vmax,
        "vstep_v":       args.vstep,
        "z_ref_ohm":     args.z_ref,
        "sdg_level_dbm": SDG_LEVEL_DBM,
        "psu_host":      args.psu,
        "sdg_host":      args.sdg,
        "scope_host":    args.scope,
        "tuning_ratio":  tuning_ratio,
        "measurements":  results,
    }
    with open(path, "w") as jf:
        json.dump(data, jf, indent=2)
    return path


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Varactor/varicap C(V) and Q(V) characterizer",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Circuit (connect before running):
  SDG CH1 → 50Ω ref resistor → 100nF bypass cap → Varactor anode
                                                          │
                                     1 mH RF choke → SPD CH1 (+)
       Scope CH1 ↑            Scope CH2 ↑
    (source side)        (before varactor)
  Varactor cathode → GND = SPD CH1(−) = Scope GND

Examples:
  python varactor.py --freq 14000 --vmin 1 --vmax 15 --vstep 0.5
  python varactor.py --freq 7000 --vmin 0.5 --vmax 12 --vstep 1.0
  python varactor.py --freq 21000 --vmin 2 --vmax 20 --vstep 0.5
""",
    )

    parser.add_argument("--psu",    default=DEFAULT_PSU_HOST,   metavar="HOST",
                        help=f"SPD3303X IP address (default {DEFAULT_PSU_HOST})")
    parser.add_argument("--sdg",    default=DEFAULT_SDG_HOST,   metavar="HOST",
                        help=f"SDG1000X IP address (default {DEFAULT_SDG_HOST})")
    parser.add_argument("--scope",  default=DEFAULT_SCOPE_HOST, metavar="HOST",
                        help=f"SDS2000X IP address (default {DEFAULT_SCOPE_HOST})")

    parser.add_argument("--freq",   type=float, default=DEFAULT_FREQ_KHZ, metavar="KHZ",
                        help=f"Test frequency in kHz (default {DEFAULT_FREQ_KHZ})")
    parser.add_argument("--vmin",   type=float, default=DEFAULT_VMIN,     metavar="V",
                        help=f"Minimum bias voltage in V (default {DEFAULT_VMIN})")
    parser.add_argument("--vmax",   type=float, default=DEFAULT_VMAX,     metavar="V",
                        help=f"Maximum bias voltage in V (default {DEFAULT_VMAX})")
    parser.add_argument("--vstep",  type=float, default=DEFAULT_VSTEP,    metavar="V",
                        help=f"Voltage step in V (default {DEFAULT_VSTEP})")
    parser.add_argument("--z-ref",  type=float, default=DEFAULT_ZREF_OHM, metavar="OHM",
                        dest="z_ref",
                        help=f"Series reference resistor in ohms (default {DEFAULT_ZREF_OHM})")
    parser.add_argument("--psu-ch", type=int,   default=DEFAULT_PSU_CH,   metavar="CH",
                        dest="psu_ch",
                        help=f"PSU channel for bias (default {DEFAULT_PSU_CH})")
    parser.add_argument("--output", default=None, metavar="PREFIX",
                        help="Output file prefix (default: timestamped)")

    args = parser.parse_args()

    # Validate
    if args.vmin < 0:
        print("Error: --vmin must be >= 0 (reverse bias, positive value)")
        sys.exit(1)
    if args.vmax <= args.vmin:
        print("Error: --vmax must be greater than --vmin")
        sys.exit(1)
    if args.vmax > PSU_MAX_VOLTAGE:
        print(f"Warning: --vmax {args.vmax} V exceeds PSU max ({PSU_MAX_VOLTAGE} V). "
              f"Clamping to {PSU_MAX_VOLTAGE} V.")
        args.vmax = PSU_MAX_VOLTAGE
    if args.vstep <= 0:
        print("Error: --vstep must be positive")
        sys.exit(1)
    if args.freq <= 0:
        print("Error: --freq must be positive")
        sys.exit(1)

    if args.output is None:
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        args.output = f"varactor_{int(args.freq)}kHz_{ts}"

    freq_hz = args.freq * 1_000.0

    # Connect instruments
    psu = sdg = scope = None
    try:
        print(f"Connecting to SPD3303X via inventory ...")
        psu = connect(args.psu or 'spd')
        print(f"  {psu.identify()}")

        print(f"Connecting to SDG1000X via inventory ...")
        sdg = connect(args.sdg or 'sdg')
        print(f"  {sdg.identify()}")

        print(f"Connecting to SDS2000X via inventory ...")
        scope = connect(args.scope or 'sds')
        print(f"  {scope.identify()}")

        # Run the sweep; PSU is disabled in the finally block
        results = run_sweep(psu, sdg, scope, args)

        # --- Compute summary ---
        tuning_ratio = compute_tuning_ratio(results)
        n_valid = sum(1 for r in results if r["status"] == "OK")
        n_inductive = sum(1 for r in results if r["status"] == "INDUCTIVE")

        if tuning_ratio is not None:
            print(f"\nTuning ratio: {tuning_ratio:.2f}:1  "
                  f"({n_valid} valid, {n_inductive} inductive)")
        else:
            print(f"\nNo valid capacitance measurements ({n_inductive} inductive).")
            print("Check circuit — is the varactor forward-biased or shorted?")

        # --- Save outputs ---
        print("\n[SAVING RESULTS]")

        txt_path = save_txt(results, args.output, freq_hz, args.z_ref, tuning_ratio)
        print(f"Text  → {txt_path}")

        json_path = save_json(results, args.output, args, tuning_ratio)
        print(f"JSON  → {json_path}")

        try:
            png_path = plot_results(results, args.output, freq_hz, tuning_ratio)
            print(f"Plot  → {png_path}")
        except Exception as exc:
            print(f"Plot failed: {exc}")

    except KeyboardInterrupt:
        print("\nInterrupted.")
        sys.exit(0)
    except ConnectionRefusedError as exc:
        print(f"\nCannot connect to instrument: {exc}")
        print("Verify instruments are powered on and SCPI/LAN is enabled.")
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
        if sdg is not None:
            try:
                sdg.output_off_all()
                sdg.close()
            except Exception:
                pass
        if psu is not None:
            try:
                psu.disable_all()
                psu.close()
            except Exception:
                pass
        if scope is not None:
            try:
                scope.close()
            except Exception:
                pass


if __name__ == "__main__":
    main()
