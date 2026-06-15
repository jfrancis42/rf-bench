#!/usr/bin/env python3
"""
Thermal Resistance (θ) Meter — SPD3303X + SDM3045X

Applies stepped power dissipation to a DUT via the SPD3303X, measures case
temperature (via thermocouple on SDM or manual entry), waits for thermal
equilibrium at each power level, and computes θ_ja or θ_ca (°C/W).

NOTE: SDM3045X does not support thermocouple temperature measurement.
      This script will attempt SCPI temperature reads and fall back to
      prompting for manual temperature entry.  For automated operation use
      an SDM3055 or SDM3065X.

Usage:
  python thermal_rth.py --power-steps "0.5,1,2,5" --log rth.csv --plot
  python thermal_rth.py --power-steps "1,2,5,10" --psu 10.1.1.56 --dmm 10.1.1.63
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

from rf_bench.siglent import SDM3000X, SPD3303X  # noqa: E402
from rf_bench import connect

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

DEFAULT_PSU_HOST   = None  # Now uses inventory
DEFAULT_DMM_HOST   = None  # Now uses inventory
DEFAULT_PSU_CH     = 1
EQUIL_RATE_C_MIN   = 0.1    # equilibrium threshold: < 0.1 °C/min
EQUIL_POLL_S       = 15     # seconds between temperature checks
EQUIL_TIMEOUT_S    = 600    # max wait for equilibrium (10 min)
DEFAULT_POWER_STEPS = "0.5,1,2,5"

_running = True
_temp_warning_shown = False


def _sigint_handler(sig, frame):
    global _running
    _running = False
    print("\n  [Ctrl+C — powering off and exiting ...]")


signal.signal(signal.SIGINT, _sigint_handler)

# ---------------------------------------------------------------------------
# Temperature measurement
# ---------------------------------------------------------------------------

def read_temperature(dmm: SDM3000X) -> float | None:
    """Try SCPI temperature; fall back to None on failure."""
    global _temp_warning_shown
    try:
        return float(dmm.measure_temperature())
    except Exception:
        if not _temp_warning_shown:
            print("\n  NOTE: SDM3045X does not support thermocouple input.")
            print("        Use SDM3055 or SDM3065X for automatic temperature logging.")
            print("        Falling back to manual temperature entry.\n")
            _temp_warning_shown = True
        return None


def get_temperature(dmm: SDM3000X) -> float | None:
    """Get temperature: try DMM first, then prompt user."""
    t = read_temperature(dmm)
    if t is not None:
        return t
    try:
        raw = input("  Enter temperature (°C): ").strip()
        return float(raw) if raw else None
    except (ValueError, EOFError):
        return None


# ---------------------------------------------------------------------------
# Wait for thermal equilibrium
# ---------------------------------------------------------------------------

def wait_equilibrium(dmm: SDM3000X, power_w: float) -> float | None:
    """
    Poll temperature until rate of change < EQUIL_RATE_C_MIN (°C/min).
    Returns final temperature or None on timeout/interrupt.
    """
    temps: list[float] = []
    times: list[float] = []
    t_start = time.time()

    print(f"  Waiting for equilibrium at {power_w:.2f} W ...")

    while _running:
        elapsed = time.time() - t_start
        if elapsed > EQUIL_TIMEOUT_S:
            print(f"  [TIMEOUT: equilibrium not reached in {EQUIL_TIMEOUT_S}s]")
            break

        t_val = get_temperature(dmm)
        if t_val is None:
            time.sleep(EQUIL_POLL_S)
            continue

        now = time.time()
        temps.append(t_val)
        times.append(now)

        if len(temps) >= 2:
            dt_min = (times[-1] - times[-2]) / 60.0
            rate   = abs(temps[-1] - temps[-2]) / max(dt_min, 1e-6)
            print(f"    T={t_val:.2f} °C  dT/dt={rate:.3f} °C/min", end='\r', flush=True)

            if rate < EQUIL_RATE_C_MIN:
                print(f"\n  Equilibrium: T={t_val:.2f} °C")
                return t_val

        time.sleep(EQUIL_POLL_S)

    return temps[-1] if temps else None


# ---------------------------------------------------------------------------
# Plot
# ---------------------------------------------------------------------------

def save_plot(power_steps: list[float], temps: list[float],
              ambient_t: float, output_prefix: str) -> str:
    """Plot ΔT and θ vs. power."""
    p_arr  = np.array(power_steps)
    t_arr  = np.array(temps)
    dt_arr = t_arr - ambient_t
    rth    = dt_arr / np.maximum(p_arr, 1e-9)  # °C/W

    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(11, 5))

    ax1.plot(p_arr, dt_arr, 'o-', color='tomato', linewidth=1.5, markersize=6)
    ax1.set_xlabel("Power Dissipated (W)", fontsize=10)
    ax1.set_ylabel("ΔT = T_case − T_ambient (°C)", fontsize=10)
    ax1.set_title("Temperature Rise vs. Power", fontsize=10)
    ax1.grid(True, alpha=0.3)

    # Fit linear θ through origin: ΔT = θ * P
    if len(p_arr) >= 2:
        theta_fit, _ = np.polyfit(p_arr, dt_arr, 1, cov=True)[:2]
        theta_lin = float(theta_fit[0])
        p_fit = np.linspace(0, p_arr.max(), 100)
        ax1.plot(p_fit, theta_lin * p_fit, '--', color='royalblue',
                 linewidth=1, label=f"θ = {theta_lin:.2f} °C/W")
        ax1.legend(fontsize=9)

    ax2.plot(p_arr, rth, 's--', color='royalblue', linewidth=1.5, markersize=6)
    ax2.axhline(float(np.mean(rth)), color='gray', linewidth=0.8, linestyle=':',
                label=f"Mean θ = {float(np.mean(rth)):.2f} °C/W")
    ax2.set_xlabel("Power Dissipated (W)", fontsize=10)
    ax2.set_ylabel("θ (°C/W)", fontsize=10)
    ax2.set_title("Thermal Resistance vs. Power", fontsize=10)
    ax2.legend(fontsize=9)
    ax2.grid(True, alpha=0.3)

    plt.suptitle("Thermal Resistance Measurement", fontsize=11)
    plt.tight_layout()

    path = f"{output_prefix}_rth.png"
    plt.savefig(path, dpi=150, bbox_inches='tight')
    plt.close(fig)
    return path


# ---------------------------------------------------------------------------
# Main measurement
# ---------------------------------------------------------------------------

def run_rth(psu: SPD3303X, dmm: SDM3000X, args: argparse.Namespace) -> None:
    """Stepped power dissipation thermal resistance measurement."""
    power_steps = [float(p) for p in args.power_steps.split(',')]
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    prefix = args.log.rsplit('.', 1)[0] if args.log else f"rth_{ts}"

    log_file   = None
    log_writer = None
    if args.log:
        log_file = open(args.log, 'w', newline='')
        fieldnames = ['timestamp', 'power_w', 'voltage_v', 'current_a',
                      'temperature_c', 'delta_t_c', 'theta_cw']
        log_writer = csv.DictWriter(log_file, fieldnames=fieldnames)
        log_writer.writeheader()

    print(f"\n  Power steps : {power_steps} W")
    print(f"  PSU channel : CH{DEFAULT_PSU_CH}")
    if args.log:
        print(f"  Log         : {args.log}")

    # Measure ambient temperature at P=0
    print("\n  Measuring ambient temperature (DUT unpowered) ...")
    psu.output_off(DEFAULT_PSU_CH)
    time.sleep(2)
    ambient_t = get_temperature(dmm)
    if ambient_t is None:
        print("  ERROR: Could not obtain ambient temperature.")
        return
    print(f"  Ambient T = {ambient_t:.2f} °C")

    results: list[tuple[float, float]] = []  # (power_w, temp_c)

    try:
        for p_target in power_steps:
            if not _running:
                break

            # Apply power: use constant-current mode (set V high, limit I)
            # P = V * I; with V fixed at e.g. 5V, I_target = P/V
            # Better: set up both V and I, measure actual P = V_meas * I_meas
            v_set   = max(1.0, min(p_target, 30.0))   # rough V for P ~ v_set * 1A
            i_set   = p_target / max(v_set, 0.1)
            i_set   = min(i_set, 3.2)

            psu.set_voltage(DEFAULT_PSU_CH, v_set)
            psu.set_current(DEFAULT_PSU_CH, i_set)
            psu.output_on(DEFAULT_PSU_CH)

            # Wait a moment then measure actual power
            time.sleep(2)
            v_meas = psu.measure_voltage(DEFAULT_PSU_CH)
            i_meas = psu.measure_current(DEFAULT_PSU_CH)
            p_actual = v_meas * i_meas

            print(f"\n  Power: V={v_meas:.3f} V  I={i_meas:.4f} A  P={p_actual:.3f} W")

            t_equil = wait_equilibrium(dmm, p_actual)
            if t_equil is None:
                print(f"  [skipping step — no temperature reading]")
                psu.output_off(DEFAULT_PSU_CH)
                continue

            delta_t = t_equil - ambient_t
            theta   = delta_t / max(p_actual, 1e-6)
            results.append((p_actual, t_equil))

            print(f"  ΔT = {delta_t:.2f} °C   θ = {theta:.2f} °C/W")

            if log_writer:
                log_writer.writerow({
                    'timestamp':     datetime.now().isoformat(),
                    'power_w':       f"{p_actual:.4f}",
                    'voltage_v':     f"{v_meas:.4f}",
                    'current_a':     f"{i_meas:.5f}",
                    'temperature_c': f"{t_equil:.3f}",
                    'delta_t_c':     f"{delta_t:.3f}",
                    'theta_cw':      f"{theta:.3f}",
                })
                log_file.flush()

    finally:
        psu.output_off(DEFAULT_PSU_CH)
        if log_file:
            log_file.close()

    if len(results) < 2:
        print("\n  Not enough data points for θ analysis.")
        return

    p_vals = [r[0] for r in results]
    t_vals = [r[1] for r in results]

    mean_theta = float(np.mean([(t - ambient_t) / max(p, 1e-9)
                                for p, t in zip(p_vals, t_vals)]))
    print(f"\n  Mean θ = {mean_theta:.2f} °C/W  (ambient = {ambient_t:.1f} °C)")

    if args.plot:
        png = save_plot(p_vals, t_vals, ambient_t, prefix)
        print(f"  Plot → {png}")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Thermal resistance (θ) meter — SPD3303X + SDM3045X",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
NOTE: SDM3045X does not support thermocouple input.  The script will prompt for
manual temperature entry.  Use SDM3055 or SDM3065X for automatic temperature logging.

Examples:
  python thermal_rth.py --power-steps "0.5,1,2,5"
  python thermal_rth.py --power-steps "1,2,5,10" --log rth.csv --plot
""",
    )
    parser.add_argument("--psu",          default=DEFAULT_PSU_HOST, metavar="HOST",
                        help=f"SPD3303X IP address (default {DEFAULT_PSU_HOST})")
    parser.add_argument("--dmm",          default=DEFAULT_DMM_HOST, metavar="HOST",
                        help=f"SDM3045X IP address (default {DEFAULT_DMM_HOST})")
    parser.add_argument("--power-steps",  default=DEFAULT_POWER_STEPS, metavar="LIST",
                        help=f"Comma-separated power levels in watts (default {DEFAULT_POWER_STEPS})")
    parser.add_argument("--log",          default=None, metavar="FILE",
                        help="CSV log file path")
    parser.add_argument("--plot",         action="store_true",
                        help="Save θ-vs-power plot to PNG when done")

    args = parser.parse_args()

    psu = dmm = None
    try:
        print(f"Connecting to SPD3303X via inventory'} ...")
        psu = connect(args.psu or 'spd')
        print(f"  {psu.identify()}")

        print(f"Connecting to SDM3045X via inventory'} ...")
        dmm = connect(args.dmm or 'sdm')
        print(f"  {dmm.identify()}")

        run_rth(psu, dmm, args)

    except ConnectionRefusedError as exc:
        print(f"\nCannot connect: {exc}")
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
        for inst in (psu, dmm):
            if inst is not None:
                try:
                    inst.disconnect()
                except Exception:
                    pass


if __name__ == "__main__":
    main()
