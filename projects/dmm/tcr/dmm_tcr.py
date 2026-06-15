#!/usr/bin/env python3
"""
Temperature Coefficient of Resistance (TCR) Meter — SDM3045X

Alternates between resistance and temperature measurement.
Logs R vs T to CSV, fits linear TCR (ppm/°C), optionally plots.

NOTE: SDM3045X does not natively support thermocouple temperature — the script
attempts a SCPI temperature read and falls back gracefully to manual entry if
the instrument returns an error.  For automatic temperature logging use an
SDM3055 or SDM3065X.

Usage:
  python dmm_tcr.py --duration 600 --interval 5
  python dmm_tcr.py --mode 4wire --log tcr_run.csv --plot
"""

import argparse
import csv
import os
import signal
import sys
import time
from datetime import datetime

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                '..', 'rf-bench'))

from rf_bench.siglent import SDM3000X  # noqa: E402
from rf_bench import connect

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

DEFAULT_DMM_HOST = None  # Now uses inventory
DEFAULT_INTERVAL = 2.0     # seconds between sample pairs
DEFAULT_DURATION = 3600    # total measurement time in seconds

_running = True


def _sigint_handler(sig, frame):
    global _running
    _running = False
    print("\n  [Ctrl+C received — finishing current sample and saving ...]")


signal.signal(signal.SIGINT, _sigint_handler)

# ---------------------------------------------------------------------------
# Temperature read (best-effort)
# ---------------------------------------------------------------------------

_temp_warning_shown = False


def read_temperature(dmm: SDM3000X) -> float | None:
    """
    Try to read temperature from DMM.  Returns None on failure.
    SDM3045X does not support thermocouple — use SDM3055/3065X for automatic T logging.
    """
    global _temp_warning_shown
    try:
        t = dmm.measure_temperature()
        return float(t)
    except Exception:
        if not _temp_warning_shown:
            print("\n  WARNING: Temperature measurement not supported on this DMM model.")
            print("           SDM3045X lacks thermocouple input.  Use SDM3055 or SDM3065X.")
            print("           Falling back to manual temperature entry.\n")
            _temp_warning_shown = True
        return None


def prompt_temperature() -> float | None:
    """Prompt user for temperature value.  Returns None if input is blank."""
    try:
        raw = input("  Enter temperature (°C) [Enter to skip]: ").strip()
        if not raw:
            return None
        return float(raw)
    except (ValueError, EOFError):
        return None


# ---------------------------------------------------------------------------
# TCR fit
# ---------------------------------------------------------------------------

def fit_tcr(temps: list[float], resistances: list[float]) -> dict:
    """
    Fit linear TCR:  R(T) = R0 * (1 + α*(T - T0))
    α in ppm/°C.  Uses least squares via numpy polyfit on ΔR/R0 vs ΔT.
    """
    t_arr = np.array(temps)
    r_arr = np.array(resistances)

    if len(t_arr) < 2:
        return {}

    t0 = t_arr[0]
    r0 = r_arr[0]
    delta_t = t_arr - t0
    delta_r_rel = (r_arr - r0) / r0  # fractional change

    # Linear fit: delta_r_rel = alpha * delta_t
    # polyfit degree 1: y = a*x + b
    coeffs = np.polyfit(delta_t, delta_r_rel, 1)
    alpha_ppm = coeffs[0] * 1e6

    # Polynomial (degree 2) for non-linear materials
    if len(t_arr) >= 4:
        poly_coeffs = np.polyfit(delta_t, delta_r_rel, 2)
    else:
        poly_coeffs = None

    # Residuals
    fitted_linear = np.polyval(coeffs, delta_t)
    residuals = delta_r_rel - fitted_linear
    rms_residual_ppm = float(np.std(residuals) * 1e6)

    return {
        'r0': r0, 't0': t0,
        'alpha_ppm_per_c': alpha_ppm,
        'linear_coeffs': coeffs.tolist(),
        'poly_coeffs': poly_coeffs.tolist() if poly_coeffs is not None else None,
        'rms_residual_ppm': rms_residual_ppm,
    }


# ---------------------------------------------------------------------------
# Plot
# ---------------------------------------------------------------------------

def save_plot(temps: list[float], resistances: list[float],
              fit: dict, output_prefix: str) -> str:
    """Plot R deviation (ppm) vs. temperature."""
    t_arr = np.array(temps)
    r_arr = np.array(resistances)
    r0    = fit.get('r0', r_arr[0])
    t0    = fit.get('t0', t_arr[0])

    delta_r_ppm = (r_arr - r0) / r0 * 1e6

    fig, ax = plt.subplots(figsize=(9, 5))
    ax.scatter(t_arr, delta_r_ppm, s=20, color='royalblue', zorder=3,
               label='Measured ΔR/R₀ (ppm)')

    if 'alpha_ppm_per_c' in fit:
        t_fit  = np.linspace(t_arr.min(), t_arr.max(), 300)
        dt_fit = t_fit - t0
        r_fit  = np.polyval(fit['linear_coeffs'], dt_fit) * 1e6
        ax.plot(t_fit, r_fit, color='tomato', linewidth=1.5,
                label=f"Linear fit: α = {fit['alpha_ppm_per_c']:+.1f} ppm/°C")

        if fit.get('poly_coeffs'):
            r_poly = np.polyval(fit['poly_coeffs'], dt_fit) * 1e6
            ax.plot(t_fit, r_poly, color='seagreen', linewidth=1, linestyle='--',
                    label='Quadratic fit')

    ax.set_xlabel("Temperature (°C)", fontsize=10)
    ax.set_ylabel("ΔR/R₀ (ppm)", fontsize=10)
    ax.set_title("TCR Measurement — Resistance vs. Temperature", fontsize=11)
    ax.legend(fontsize=9)
    ax.grid(True, alpha=0.3)
    plt.tight_layout()

    path = f"{output_prefix}_tcr.png"
    plt.savefig(path, dpi=150, bbox_inches='tight')
    plt.close(fig)
    return path


# ---------------------------------------------------------------------------
# Main measurement loop
# ---------------------------------------------------------------------------

def run_tcr(dmm: SDM3000X, args: argparse.Namespace) -> None:
    """Alternating resistance + temperature measurement loop."""
    use_auto_temp = True
    temps:       list[float] = []
    resistances: list[float] = []
    timestamps:  list[float] = []

    log_file   = None
    log_writer = None
    if args.log:
        log_file = open(args.log, 'w', newline='')
        fieldnames = ['timestamp', 'elapsed_s', 'temperature_c', 'resistance_ohm']
        log_writer = csv.DictWriter(log_file, fieldnames=fieldnames)
        log_writer.writeheader()

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_prefix = args.log.rsplit('.', 1)[0] if args.log else f"tcr_{ts}"

    print(f"\n  Mode    : {args.mode}")
    print(f"  Interval: {args.interval} s")
    print(f"  Duration: {args.duration} s")
    if args.log:
        print(f"  Log     : {args.log}")
    print("\n  Starting measurement... (Ctrl+C to stop early)\n")

    t_start = time.time()
    sample  = 0

    try:
        while _running:
            elapsed = time.time() - t_start
            if elapsed >= args.duration:
                break

            # Resistance
            try:
                r = (dmm.measure_resistance_4w() if args.mode == '4wire'
                     else dmm.measure_resistance())
            except Exception as exc:
                print(f"  [resistance read error: {exc}]")
                time.sleep(args.interval)
                continue

            # Temperature
            t_val = read_temperature(dmm) if use_auto_temp else None
            if t_val is None and use_auto_temp and not _temp_warning_shown:
                pass  # warning already shown on first failure

            if t_val is None:
                # Fall back to manual entry once auto fails
                use_auto_temp = False
                t_val = prompt_temperature()

            if t_val is None:
                # Skip sample if no temperature available
                time.sleep(args.interval)
                continue

            sample += 1
            ts_now = time.time()
            resistances.append(float(r))
            temps.append(float(t_val))
            timestamps.append(ts_now)

            print(f"  [{sample:4d}]  T={t_val:+7.2f} °C  R={r:.6g} Ω"
                  f"  elapsed={elapsed:.0f}s", flush=True)

            if log_writer:
                log_writer.writerow({
                    'timestamp':      datetime.fromtimestamp(ts_now).isoformat(),
                    'elapsed_s':      f"{elapsed:.1f}",
                    'temperature_c':  f"{t_val:.3f}",
                    'resistance_ohm': f"{r:.6g}",
                })
                log_file.flush()

            time.sleep(args.interval)

    finally:
        if log_file:
            log_file.close()

    if len(temps) < 2:
        print("\n  Not enough data for TCR fit.")
        return

    fit = fit_tcr(temps, resistances)
    print(f"\n  TCR fit:")
    print(f"    R0   = {fit['r0']:.6g} Ω  @ T0 = {fit['t0']:.1f} °C")
    print(f"    α    = {fit['alpha_ppm_per_c']:+.1f} ppm/°C  (linear)")
    print(f"    RMS residual = {fit['rms_residual_ppm']:.1f} ppm")

    if args.plot:
        png = save_plot(temps, resistances, fit, output_prefix)
        print(f"\n  Plot saved → {png}")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Temperature Coefficient of Resistance (TCR) meter — SDM3045X",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
NOTE: SDM3045X does not support thermocouple temperature.  Use SDM3055 or SDM3065X
for automatic temperature logging.  This script will fall back to manual entry.

Examples:
  python dmm_tcr.py --duration 600
  python dmm_tcr.py --mode 4wire --interval 5 --log tcr.csv --plot
""",
    )
    parser.add_argument("--dmm",      default=DEFAULT_DMM_HOST, metavar="HOST",
                        help=f"SDM3045X IP address (default {DEFAULT_DMM_HOST})")
    parser.add_argument("--mode",     choices=['2wire', '4wire'], default='2wire',
                        help="Resistance measurement mode (default: 2wire)")
    parser.add_argument("--interval", type=float, default=DEFAULT_INTERVAL, metavar="S",
                        help=f"Sample interval in seconds (default {DEFAULT_INTERVAL})")
    parser.add_argument("--duration", type=float, default=DEFAULT_DURATION, metavar="S",
                        help=f"Total measurement duration in seconds (default {DEFAULT_DURATION})")
    parser.add_argument("--log",      default=None, metavar="FILE",
                        help="CSV log file path")
    parser.add_argument("--plot",     action="store_true",
                        help="Save R-vs-T plot to PNG when done")

    args = parser.parse_args()

    print(f"Connecting to SDM3045X via inventory'} ...")
    dmm = None
    try:
        dmm = connect(args.dmm or 'sdm')
        print(f"  {dmm.identify()}")
        run_tcr(dmm, args)
    except ConnectionRefusedError as exc:
        print(f"\nCannot connect to DMM: {exc}")
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
        if dmm is not None:
            try:
                dmm.disconnect()
            except Exception:
                pass


if __name__ == "__main__":
    main()
