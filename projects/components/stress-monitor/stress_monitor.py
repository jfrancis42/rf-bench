#!/usr/bin/env python3
"""
Component Stress Monitor — SPD3303X + SDM3045X

Applies a continuous stress voltage while the DMM logs a component parameter
over time.  Primary use: MLCC capacitance vs. DC bias.  Also supports resistor
under power (resistance vs. time), Zener voltage stability, and diode Vf drift.

Usage:
  python stress_monitor.py --mode capacitance --voltage 5.0 --duration 3600
  python stress_monitor.py --mode resistance --voltage 3.3 --duration 7200 --plot
  python stress_monitor.py --mode voltage --voltage 5.1 --threshold-pct 5
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

DEFAULT_PSU_HOST    = None  # Now uses inventory
DEFAULT_DMM_HOST    = None  # Now uses inventory
DEFAULT_PSU_CH      = 1
DEFAULT_MODE        = "capacitance"
DEFAULT_INTERVAL    = 60.0   # seconds between measurements
DEFAULT_DURATION    = 3600   # total run time
DEFAULT_THRESH_PCT  = 20.0   # % drift for SMS alert

_running = True


def _sigint_handler(sig, frame):
    global _running
    _running = False
    print("\n  [Ctrl+C — powering off and saving ...]")


signal.signal(signal.SIGINT, _sigint_handler)

# ---------------------------------------------------------------------------
# DMM dispatch
# ---------------------------------------------------------------------------

def measure(dmm: SDM3000X, mode: str) -> float | None:
    """Take one measurement in the selected mode."""
    try:
        if mode == 'capacitance':
            return dmm.measure_capacitance()
        elif mode == 'resistance':
            return dmm.measure_resistance()
        elif mode == 'voltage':
            return dmm.measure_voltage_dc()
        elif mode == 'diode':
            return dmm.measure_diode()
    except Exception as exc:
        print(f"  [DMM error: {exc}]")
    return None


def units_for_mode(mode: str, value: float) -> str:
    """Format a value with appropriate units for the mode."""
    if mode == 'capacitance':
        if value < 1e-9:
            return f"{value*1e12:.3f} pF"
        elif value < 1e-6:
            return f"{value*1e9:.3f} nF"
        else:
            return f"{value*1e6:.3f} µF"
    elif mode == 'resistance':
        if value < 1e3:
            return f"{value:.3f} Ω"
        elif value < 1e6:
            return f"{value/1e3:.3f} kΩ"
        else:
            return f"{value/1e6:.3f} MΩ"
    elif mode == 'voltage':
        return f"{value:.5f} V"
    elif mode == 'diode':
        return f"{value:.4f} V"
    return f"{value:.6g}"


# ---------------------------------------------------------------------------
# SMS alert
# ---------------------------------------------------------------------------

def send_sms_alert(mode: str, drift_pct: float, current_val: float,
                   initial_val: float) -> None:
    """Send drift alert via voipms proxy.  Non-fatal."""
    try:
        import urllib.request
        import base64
        import json
        import pathlib

        creds_file = pathlib.Path.home() / "Dropbox/build/creds/voipms-rest.txt"
        if not creds_file.exists():
            return
        lines = creds_file.read_text().strip().splitlines()
        if len(lines) < 3:
            return
        url, user, password = lines[0].strip(), lines[1].strip(), lines[2].strip()

        msg = (f"stress_monitor: {mode} drifted {drift_pct:+.1f}%  "
               f"({initial_val:.4g} → {current_val:.4g})")
        payload = json.dumps({"to": user, "message": msg}).encode()
        req = urllib.request.Request(
            f"{url}/sms", data=payload,
            headers={'Content-Type': 'application/json'}, method='POST',
        )
        cred = base64.b64encode(f"{user}:{password}".encode()).decode()
        req.add_header('Authorization', f'Basic {cred}')
        with urllib.request.urlopen(req, timeout=10) as resp:
            print(f"  [SMS: {resp.status}]")
    except Exception as exc:
        print(f"  [SMS failed: {exc}]")


# ---------------------------------------------------------------------------
# Plot
# ---------------------------------------------------------------------------

def save_plot(times: list[float], values: list[float], mode: str,
              initial_val: float, voltage_v: float,
              output_prefix: str) -> str:
    """Plot measured parameter vs. elapsed time."""
    t_arr = (np.array(times) - times[0]) / 3600.0   # → hours
    v_arr = np.array(values)
    drift_pct = (v_arr - initial_val) / max(abs(initial_val), 1e-30) * 100.0

    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(10, 7), sharex=True)

    ax1.plot(t_arr, v_arr, '-', color='royalblue', linewidth=1)
    ax1.set_ylabel(f"{mode.capitalize()} ({mode})", fontsize=9)
    ax1.set_title(f"Stress Monitor — {mode} at {voltage_v:.2f} V bias", fontsize=10)
    ax1.grid(True, alpha=0.3)

    ax2.plot(t_arr, drift_pct, '-', color='tomato', linewidth=1)
    ax2.axhline(0, color='gray', linewidth=0.5)
    ax2.set_xlabel("Elapsed Time (hours)", fontsize=9)
    ax2.set_ylabel("Drift from initial (%)", fontsize=9)
    ax2.grid(True, alpha=0.3)

    plt.tight_layout()
    path = f"{output_prefix}_stress.png"
    plt.savefig(path, dpi=150, bbox_inches='tight')
    plt.close(fig)
    return path


# ---------------------------------------------------------------------------
# Main measurement loop
# ---------------------------------------------------------------------------

def run_stress(psu: SPD3303X, dmm: SDM3000X, args: argparse.Namespace) -> None:
    """Apply stress voltage and log DMM parameter over time."""
    ts     = datetime.now().strftime("%Y%m%d_%H%M%S")
    prefix = args.log.rsplit('.', 1)[0] if args.log else f"stress_{ts}"

    log_file   = None
    log_writer = None
    if args.log:
        log_file = open(args.log, 'w', newline='')
        fieldnames = ['timestamp', 'elapsed_s', 'voltage_v', 'measured', 'drift_pct']
        log_writer = csv.DictWriter(log_file, fieldnames=fieldnames)
        log_writer.writeheader()

    print(f"\n  Mode     : {args.mode}")
    print(f"  Voltage  : {args.voltage} V")
    print(f"  Interval : {args.interval} s")
    print(f"  Duration : {args.duration} s")
    print(f"  Alert at : {args.threshold_pct}% drift")
    if args.log:
        print(f"  Log      : {args.log}")

    # Apply bias voltage
    psu.set_voltage(DEFAULT_PSU_CH, args.voltage)
    psu.set_current(DEFAULT_PSU_CH, 0.1)   # 100 mA limit (safe for most ICs under test)
    psu.output_on(DEFAULT_PSU_CH)
    time.sleep(2)  # settling

    times:  list[float] = []
    values: list[float] = []
    alert_sent = False
    initial_val: float | None = None
    sample = 0

    try:
        t_start = time.time()
        while _running:
            elapsed = time.time() - t_start
            if elapsed >= args.duration:
                break

            val = measure(dmm, args.mode)
            if val is None or not np.isfinite(val):
                time.sleep(args.interval)
                continue

            if initial_val is None:
                initial_val = val

            drift_pct = (val - initial_val) / max(abs(initial_val), 1e-30) * 100.0
            times.append(time.time())
            values.append(val)
            sample += 1

            print(f"  [{sample:5d}]  {elapsed:6.0f}s  {units_for_mode(args.mode, val):>16}"
                  f"  drift={drift_pct:+.2f}%", flush=True)

            if log_writer:
                log_writer.writerow({
                    'timestamp': datetime.now().isoformat(),
                    'elapsed_s': f"{elapsed:.1f}",
                    'voltage_v': f"{args.voltage:.3f}",
                    'measured':  f"{val:.6g}",
                    'drift_pct': f"{drift_pct:.3f}",
                })
                log_file.flush()

            # Drift alert (once per session)
            if not alert_sent and abs(drift_pct) >= args.threshold_pct:
                print(f"\n  ALERT: {args.mode} drifted {drift_pct:+.1f}% from initial!")
                send_sms_alert(args.mode, drift_pct, val, initial_val)
                alert_sent = True

            time.sleep(args.interval)

    finally:
        psu.output_off(DEFAULT_PSU_CH)
        if log_file:
            log_file.close()

    print(f"\n  {sample} samples collected.")

    if len(values) >= 2 and args.plot:
        png = save_plot(times, values, args.mode, initial_val or values[0],
                        args.voltage, prefix)
        print(f"  Plot → {png}")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Component stress monitor — SPD3303X bias + SDM3045X logging",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python stress_monitor.py --mode capacitance --voltage 5.0 --duration 3600
  python stress_monitor.py --mode resistance --voltage 3.3 --interval 30 --plot
  python stress_monitor.py --mode voltage --voltage 5.1 --threshold-pct 5
""",
    )
    parser.add_argument("--psu",           default=DEFAULT_PSU_HOST, metavar="HOST",
                        help=f"SPD3303X IP address (default {DEFAULT_PSU_HOST})")
    parser.add_argument("--dmm",           default=DEFAULT_DMM_HOST, metavar="HOST",
                        help=f"SDM3045X IP address (default {DEFAULT_DMM_HOST})")
    parser.add_argument("--mode",          choices=['capacitance', 'resistance', 'voltage', 'diode'],
                        default=DEFAULT_MODE,
                        help=f"Measurement mode (default {DEFAULT_MODE})")
    parser.add_argument("--voltage",       type=float, required=True, metavar="V",
                        help="Bias voltage to apply (required)")
    parser.add_argument("--interval",      type=float, default=DEFAULT_INTERVAL, metavar="S",
                        help=f"Measurement interval in seconds (default {DEFAULT_INTERVAL})")
    parser.add_argument("--duration",      type=float, default=DEFAULT_DURATION, metavar="S",
                        help=f"Total run time in seconds (default {DEFAULT_DURATION})")
    parser.add_argument("--threshold-pct", type=float, default=DEFAULT_THRESH_PCT, metavar="PCT",
                        help=f"SMS alert on drift > %% (default {DEFAULT_THRESH_PCT})")
    parser.add_argument("--log",           default=None, metavar="FILE",
                        help="CSV log file path")
    parser.add_argument("--plot",          action="store_true",
                        help="Save drift plot to PNG when done")

    args = parser.parse_args()

    psu = dmm = None
    try:
        print(f"Connecting to SPD3303X via inventory ...")
        psu = connect(args.psu or 'spd')
        print(f"  {psu.identify()}")

        print(f"Connecting to SDM3045X via inventory ...")
        dmm = connect(args.dmm or 'sdm')
        print(f"  {dmm.identify()}")

        run_stress(psu, dmm, args)

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
