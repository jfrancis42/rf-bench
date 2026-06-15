#!/usr/bin/env python3
"""
Kelvin Contact Resistance Survey — SDM3045X 4-wire mode

Measures contact resistance (mΩ) on each pin/joint in sequence.
Auto-increments pin counter after each stable reading.
Produces end-of-session summary with min/max/mean/σ/fail count.

Usage:
  python dmm_contact.py --count 40
  python dmm_contact.py --threshold 50 --log contacts.csv --labels
"""

import argparse
import csv
import os
import signal
import sys
import time
from datetime import datetime

import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                '..', 'rf-bench'))

from rf_bench.siglent import SDM3000X  # noqa: E402
from rf_bench import connect

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

DEFAULT_DMM_HOST   = None  # Now uses inventory
DEFAULT_THRESHOLD  = 100.0   # mΩ fail threshold
STABLE_COUNT       = 3
STABLE_PCT         = 0.001   # 0.1% stability window
CHANGE_PCT         = 0.05    # 5% change → new component
POLL_INTERVAL_S    = 0.15

_running = True


def _sigint_handler(sig, frame):
    global _running
    _running = False
    print("\n  [Ctrl+C received — printing summary and exiting ...]")


signal.signal(signal.SIGINT, _sigint_handler)

# ---------------------------------------------------------------------------
# Stability detection (shared pattern with dmm_sorter)
# ---------------------------------------------------------------------------

def wait_for_stable(dmm: SDM3000X, pin_num: int) -> float | None:
    """
    Block until a stable 4-wire resistance reading is obtained.
    Returns mΩ value or None if interrupted.
    """
    readings: list[float] = []
    last_val: float | None = None

    print(f"  Pin {pin_num:3d}: Probe now ...", end='', flush=True)

    while _running:
        try:
            r_ohm = dmm.measure_resistance_4w()
        except Exception as exc:
            print(f"\n  [read error: {exc}]", end='')
            time.sleep(POLL_INTERVAL_S)
            continue

        if not np.isfinite(r_ohm) or r_ohm < 0:
            time.sleep(POLL_INTERVAL_S)
            continue

        readings.append(r_ohm)

        # Reset on large change (new contact)
        if len(readings) >= 2:
            ratio = abs(readings[-1] - readings[-2]) / max(abs(readings[-2]), 1e-30)
            if ratio > CHANGE_PCT:
                readings = [readings[-1]]

        # Check stability
        if len(readings) >= STABLE_COUNT:
            window = readings[-STABLE_COUNT:]
            spread = max(window) / max(min(window), 1e-30)
            if spread < (1.0 + STABLE_PCT):
                stable_r_ohm = float(np.mean(window))
                # Avoid re-triggering on same contact
                if last_val is not None:
                    if abs(stable_r_ohm - last_val) / max(abs(last_val), 1e-30) < CHANGE_PCT:
                        time.sleep(POLL_INTERVAL_S)
                        continue
                return stable_r_ohm * 1000.0  # → mΩ

        print('.', end='', flush=True)
        time.sleep(POLL_INTERVAL_S)

    return None


# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------

def print_summary(results: list[dict], threshold_mohm: float) -> None:
    """Print end-of-session statistics."""
    if not results:
        print("\n  No measurements taken.")
        return

    values = np.array([r['mohm'] for r in results])
    fails  = [r for r in results if r['fail']]

    print("\n" + "=" * 64)
    print("  CONTACT RESISTANCE SURVEY SUMMARY")
    print("=" * 64)
    print(f"  Pins measured : {len(results)}")
    print(f"  Threshold     : {threshold_mohm:.1f} mΩ")
    print(f"  Min           : {values.min():.3f} mΩ  (pin {results[int(np.argmin(values))]['pin']})")
    print(f"  Max           : {values.max():.3f} mΩ  (pin {results[int(np.argmax(values))]['pin']})")
    print(f"  Mean          : {values.mean():.3f} mΩ")
    print(f"  Std dev (σ)   : {values.std():.3f} mΩ")
    print(f"  Failures      : {len(fails)} / {len(results)}")
    if fails:
        print("  Failed pins   :", ", ".join(str(r['pin']) for r in fails))
    print("=" * 64)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def run_contact(dmm: SDM3000X, args: argparse.Namespace) -> None:
    """Pin-by-pin contact resistance measurement loop."""
    results: list[dict] = []
    log_file   = None
    log_writer = None

    if args.log:
        log_file = open(args.log, 'w', newline='')
        fieldnames = ['timestamp', 'pin', 'label', 'mohm', 'result']
        log_writer = csv.DictWriter(log_file, fieldnames=fieldnames)
        log_writer.writeheader()

    print(f"\n  Threshold : {args.threshold} mΩ")
    print(f"  Pins      : {args.count if args.count else '∞ (Ctrl+C to end)'}")
    if args.log:
        print(f"  Log       : {args.log}")
    print()

    pin = 1
    try:
        while _running:
            if args.count and pin > args.count:
                break

            mohm = wait_for_stable(dmm, pin)
            if mohm is None:
                break

            label = ""
            if args.labels:
                try:
                    label = input(f"  Label for pin {pin} [{mohm:.3f} mΩ]: ").strip()
                except EOFError:
                    label = ""

            fail   = mohm > args.threshold
            result = "FAIL" if fail else "PASS"
            results.append({'pin': pin, 'label': label, 'mohm': mohm, 'fail': fail})

            print(f"  → {mohm:9.3f} mΩ  {result}"
                  + (f"  [{label}]" if label else ""))
            print('\a', end='', flush=True)

            if log_writer:
                log_writer.writerow({
                    'timestamp': datetime.now().isoformat(),
                    'pin':       pin,
                    'label':     label,
                    'mohm':      f"{mohm:.4f}",
                    'result':    result,
                })
                log_file.flush()

            pin += 1

    finally:
        if log_file:
            log_file.close()

    print_summary(results, args.threshold)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Kelvin contact resistance survey — SDM3045X 4-wire mode",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python dmm_contact.py --count 40
  python dmm_contact.py --threshold 50 --log header.csv --labels
  python dmm_contact.py --count 80 --threshold 200 --log board.csv
""",
    )
    parser.add_argument("--dmm",       default=DEFAULT_DMM_HOST, metavar="HOST",
                        help=f"SDM3045X IP address (default {DEFAULT_DMM_HOST})")
    parser.add_argument("--threshold", type=float, default=DEFAULT_THRESHOLD, metavar="MOHM",
                        help=f"Fail threshold in mΩ (default {DEFAULT_THRESHOLD})")
    parser.add_argument("--log",       default=None, metavar="FILE",
                        help="CSV log file path")
    parser.add_argument("--labels",    action="store_true",
                        help="Prompt for a label (net name) after each reading")
    parser.add_argument("--count",     type=int, default=None, metavar="N",
                        help="Total pins to measure (default: run until Ctrl+C)")

    args = parser.parse_args()

    print(f"Connecting to SDM3045X via inventory'} ...")
    dmm = None
    try:
        dmm = connect(args.dmm or 'sdm')
        print(f"  {dmm.identify()}")
        run_contact(dmm, args)
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
