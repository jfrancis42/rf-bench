#!/usr/bin/env python3
"""
Flipper Zero IR Receiver Bandpass Mapper

Maps the Flipper IR receiver's demodulator bandpass by sweeping the scope AWG
carrier frequency from 30-60 kHz in configurable steps. At each frequency the
AWG drives an IR LED at the Flipper; if the Flipper decodes a NEC burst the
frequency is marked as "pass".

Output: decode_success vs. carrier_hz plot and CSV log.

Usage:
  python ir_rx_response.py --start 30 --stop 60 --step 0.5
  python ir_rx_response.py --scope 10.1.1.58 --start 28 --stop 65
"""

import argparse
import csv
import os
import signal
import sys
import time
from datetime import datetime

import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                '..', 'rf-bench'))
from rf_bench.flipper import FlipperZero
from rf_bench.siglent import SDS2000X
from rf_bench import connect

# ---------------------------------------------------------------------------
# Defaults
# ---------------------------------------------------------------------------
DEFAULT_SCOPE_HOST = None  # Now uses inventory
DEFAULT_SERIAL     = "/dev/ttyACM0"
DEFAULT_START_KHZ  = 30.0
DEFAULT_STOP_KHZ   = 60.0
DEFAULT_STEP_KHZ   = 0.5
AWG_DUTY_PCT       = 33.0    # 33% duty cycle, typical IR carrier
AWG_AMPLITUDE_VPP  = 3.3     # Vpp into IR LED

_running = True


def _sigint_handler(sig, frame):
    global _running
    _running = False
    print("\n  [Ctrl+C -- stopping sweep]")


signal.signal(signal.SIGINT, _sigint_handler)


# ---------------------------------------------------------------------------
# Sweep
# ---------------------------------------------------------------------------

def sweep_rx_response(fz: FlipperZero, scope: SDS2000X,
                      start_hz: float, stop_hz: float,
                      step_hz: float) -> list:
    """
    Sweep AWG frequency, attempt NEC decode at each step.
    Returns list of {freq_hz, decode_success, rssi_hint} dicts.
    """
    freqs = np.arange(start_hz, stop_hz + step_hz, step_hz)
    results = []

    print(f"\n[RX BANDPASS SWEEP]")
    print(f"  Range: {start_hz/1e3:.1f} - {stop_hz/1e3:.1f} kHz  "
          f"step={step_hz/1e3:.2f} kHz  points={len(freqs)}")
    print(f"  AWG: {AWG_AMPLITUDE_VPP:.1f} Vpp, {AWG_DUTY_PCT:.0f}% duty")
    print(f"  {'Freq (kHz)':>12}  {'Result':>8}  {'Progress':>10}")
    print("  " + "-" * 36)

    for i, freq_hz in enumerate(freqs):
        if not _running:
            break

        # Set AWG frequency and duty cycle
        scope.set_awg_frequency(1, float(freq_hz))
        scope.set_awg_duty_cycle(1, AWG_DUTY_PCT)
        scope.awg_output_on(1)
        time.sleep(0.05)

        # Attempt decode
        decoded = fz.ir_receive(timeout_s=0.8)
        success = (decoded is not None
                   and decoded.get("protocol") not in (None, "Unknown", ""))

        results.append({"freq_hz": float(freq_hz), "decode_success": success})
        mark = "PASS" if success else "FAIL"
        pct  = 100.0 * (i + 1) / len(freqs)
        print(f"  {freq_hz/1e3:>12.2f}  {mark:>8}  {pct:>9.1f}%", end='\r', flush=True)

    scope.awg_output_off(1)
    print()
    return results


# ---------------------------------------------------------------------------
# Analysis
# ---------------------------------------------------------------------------

def analyze(results: list) -> dict:
    """Find center frequency and -3 dB bandwidth of the passband."""
    freqs   = np.array([r["freq_hz"] for r in results])
    success = np.array([1 if r["decode_success"] else 0 for r in results])

    if not np.any(success):
        return {"center_hz": None, "passband_low_hz": None, "passband_high_hz": None}

    passing_freqs = freqs[success == 1]
    center_hz     = float(np.median(passing_freqs))
    low_hz        = float(passing_freqs[0])
    high_hz       = float(passing_freqs[-1])
    bw_hz         = high_hz - low_hz

    print(f"\n  Passband low  : {low_hz/1e3:.2f} kHz")
    print(f"  Passband high : {high_hz/1e3:.2f} kHz")
    print(f"  Center        : {center_hz/1e3:.2f} kHz")
    print(f"  Bandwidth     : {bw_hz/1e3:.2f} kHz")
    return {"center_hz": center_hz, "passband_low_hz": low_hz,
            "passband_high_hz": high_hz, "bw_hz": bw_hz}


# ---------------------------------------------------------------------------
# Output
# ---------------------------------------------------------------------------

def save_csv(results: list, path: str) -> None:
    with open(path, "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=["freq_hz", "decode_success"])
        w.writeheader()
        w.writerows(results)
    print(f"  CSV  -> {path}")


def save_plot(results: list, analysis: dict, output_prefix: str) -> None:
    freqs   = [r["freq_hz"] / 1e3 for r in results]
    success = [1 if r["decode_success"] else 0 for r in results]

    fig, ax = plt.subplots(figsize=(10, 4))
    ax.bar(freqs, success, width=(freqs[1] - freqs[0]) * 0.8 if len(freqs) > 1 else 0.4,
           color='steelblue', edgecolor='navy')

    if analysis.get("center_hz"):
        ax.axvline(analysis["center_hz"] / 1e3, color='red', linestyle='--', linewidth=1.5,
                   label=f"Center {analysis['center_hz']/1e3:.1f} kHz")
        ax.axvline(analysis["passband_low_hz"] / 1e3, color='orange',
                   linestyle=':', linewidth=1, label="Passband edges")
        ax.axvline(analysis["passband_high_hz"] / 1e3, color='orange', linestyle=':', linewidth=1)
        ax.legend(fontsize=9)

    ax.set_xlabel("Carrier Frequency (kHz)")
    ax.set_ylabel("Decode Success")
    ax.set_yticks([0, 1])
    ax.set_yticklabels(["Fail", "Pass"])
    ax.set_title("Flipper Zero IR Receiver Bandpass Response")
    ax.grid(True, axis='x', alpha=0.4)

    plt.tight_layout()
    path = f"{output_prefix}_rx_response.png"
    plt.savefig(path, dpi=150, bbox_inches='tight')
    plt.close(fig)
    print(f"  Plot -> {path}")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Map Flipper IR receiver bandpass by sweeping AWG carrier frequency",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python ir_rx_response.py
  python ir_rx_response.py --start 28 --stop 65 --step 0.25
""",
    )
    parser.add_argument("--scope",  default=DEFAULT_SCOPE_HOST, metavar="HOST",
                        help=f"Scope IP (default {DEFAULT_SCOPE_HOST})")
    parser.add_argument("--serial", default=DEFAULT_SERIAL, metavar="PORT",
                        help=f"Flipper serial port (default {DEFAULT_SERIAL})")
    parser.add_argument("--start",  type=float, default=DEFAULT_START_KHZ, metavar="KHZ",
                        help=f"Start frequency kHz (default {DEFAULT_START_KHZ})")
    parser.add_argument("--stop",   type=float, default=DEFAULT_STOP_KHZ, metavar="KHZ",
                        help=f"Stop frequency kHz (default {DEFAULT_STOP_KHZ})")
    parser.add_argument("--step",   type=float, default=DEFAULT_STEP_KHZ, metavar="KHZ",
                        help=f"Step size kHz (default {DEFAULT_STEP_KHZ})")
    parser.add_argument("--output", default=None, metavar="PREFIX",
                        help="Output filename prefix")

    args = parser.parse_args()
    if args.output is None:
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        args.output = f"ir_rx_response_{ts}"

    try:
        print(f"Connecting to Flipper via inventory ...")
        fz = FlipperZero(args.serial)
        print(f"  {fz.identify()}")

        print(f"Connecting to scope via inventory ...")
        scope = connect(args.scope or 'sds')
        print(f"  {scope.identify()}")

        results = sweep_rx_response(
            fz, scope,
            start_hz=args.start * 1e3,
            stop_hz=args.stop * 1e3,
            step_hz=args.step * 1e3,
        )

        if results:
            analysis = analyze(results)
            save_csv(results, f"{args.output}_rx_response.csv")
            save_plot(results, analysis, args.output)

    except KeyboardInterrupt:
        pass
    except Exception as exc:
        import traceback
        print(f"\nError: {exc}")
        traceback.print_exc()
        sys.exit(1)
    finally:
        try:
            scope.awg_output_off(1)
        except Exception:
            pass


if __name__ == "__main__":
    main()
