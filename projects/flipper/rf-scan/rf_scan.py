#!/usr/bin/env python3
"""
Flipper Zero Sub-GHz Band Scanner

Sweeps CC1101 RSSI across ISM frequencies 300-928 MHz using subghz_scan_rssi().
Displays a live bar chart using Unicode block characters. Logging mode writes CSV.

Usage:
  python rf_scan.py
  python rf_scan.py --start 400 --stop 500 --step 100 --continuous
  python rf_scan.py --start 300 --stop 928 --log scan.csv
"""

import argparse
import csv
import os
import signal
import sys
import time
from datetime import datetime

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                '..', 'rf-bench'))
from rf_bench.flipper import FlipperZero

# ---------------------------------------------------------------------------
# Defaults
# ---------------------------------------------------------------------------
DEFAULT_SERIAL    = "/dev/ttyACM0"
DEFAULT_START_MHZ = 300.0
DEFAULT_STOP_MHZ  = 928.0
DEFAULT_STEP_KHZ  = 200.0
DEFAULT_DWELL_S   = 0.05
BAR_WIDTH         = 60     # characters per bar chart row
RSSI_MIN          = -120.0
RSSI_MAX          = -20.0

_running = True


def _sigint_handler(sig, frame):
    global _running
    _running = False
    print("\n  [Ctrl+C -- stopping scan]")


signal.signal(signal.SIGINT, _sigint_handler)


# ---------------------------------------------------------------------------
# Display helpers
# ---------------------------------------------------------------------------

BLOCK_CHARS = " ▁▂▃▄▅▆▇█"


def rssi_to_bar(rssi: float, width: int = BAR_WIDTH) -> str:
    """Convert RSSI dBm to Unicode bar string."""
    clamped = max(RSSI_MIN, min(RSSI_MAX, rssi))
    fraction = (clamped - RSSI_MIN) / (RSSI_MAX - RSSI_MIN)
    n_blocks = int(fraction * width)
    remainder = fraction * width - n_blocks
    char_idx = min(int(remainder * 8), 7)
    return "█" * n_blocks + BLOCK_CHARS[char_idx]


def format_freq_mhz(hz: float) -> str:
    mhz = hz / 1e6
    if mhz >= 1000:
        return f"{mhz/1000:.3f} GHz"
    return f"{mhz:.3f} MHz"


# ---------------------------------------------------------------------------
# Scanner
# ---------------------------------------------------------------------------

def run_scan(fz: FlipperZero, start_hz: float, stop_hz: float,
             step_hz: float, dwell_s: float,
             log_file: str | None = None,
             continuous: bool = False) -> None:
    """Sweep and display. If continuous=True, loops until Ctrl+C."""

    csv_writer = None
    csv_fh     = None
    write_header = not (log_file and os.path.exists(log_file))

    if log_file:
        csv_fh     = open(log_file, "a", newline="")
        csv_writer = csv.writer(csv_fh)
        if write_header:
            csv_writer.writerow(["ts", "freq_hz", "rssi_dbm"])

    sweep_count = 0
    try:
        while True:
            if not _running:
                break

            results = fz.subghz_scan_rssi(
                int(start_hz), int(stop_hz), int(step_hz), dwell_s
            )
            sweep_count += 1
            ts = datetime.now().strftime("%H:%M:%S")

            # Terminal display
            os.system("clear")
            print(f"  RF SCAN  {format_freq_mhz(start_hz)} - {format_freq_mhz(stop_hz)}"
                  f"  step={step_hz/1e3:.0f} kHz  sweep={sweep_count}  {ts}")
            print(f"  {'Freq':>14}  {'RSSI':>8}  Bar")
            print("  " + "-" * (30 + BAR_WIDTH))

            for freq_hz, rssi in results:
                bar = rssi_to_bar(rssi)
                print(f"  {format_freq_mhz(freq_hz):>14}  {rssi:>+8.1f}  {bar}")
                if csv_writer:
                    csv_writer.writerow([ts, int(freq_hz), f"{rssi:.1f}"])

            if csv_fh:
                csv_fh.flush()

            if not continuous:
                break

    finally:
        if csv_fh:
            csv_fh.close()


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Sub-GHz RSSI band scanner with Unicode bar chart",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python rf_scan.py
  python rf_scan.py --start 400 --stop 500 --step 100 --continuous
  python rf_scan.py --start 315 --stop 316 --step 10 --dwell 0.5
  python rf_scan.py --log scan.csv --continuous
""",
    )
    parser.add_argument("--start",      type=float, default=DEFAULT_START_MHZ, metavar="MHZ",
                        help=f"Start frequency MHz (default {DEFAULT_START_MHZ})")
    parser.add_argument("--stop",       type=float, default=DEFAULT_STOP_MHZ, metavar="MHZ",
                        help=f"Stop frequency MHz (default {DEFAULT_STOP_MHZ})")
    parser.add_argument("--step",       type=float, default=DEFAULT_STEP_KHZ, metavar="KHZ",
                        help=f"Step size kHz (default {DEFAULT_STEP_KHZ})")
    parser.add_argument("--dwell",      type=float, default=DEFAULT_DWELL_S, metavar="S",
                        help=f"Dwell seconds per step (default {DEFAULT_DWELL_S})")
    parser.add_argument("--log",        default=None, metavar="FILE",
                        help="CSV log file (append mode)")
    parser.add_argument("--continuous", action="store_true",
                        help="Continuously resweep until Ctrl+C")
    parser.add_argument("--serial",     default=DEFAULT_SERIAL, metavar="PORT",
                        help=f"Flipper serial port (default {DEFAULT_SERIAL})")

    args = parser.parse_args()

    try:
        print(f"Connecting to Flipper @ {args.serial} ...")
        fz = FlipperZero(args.serial)
        print(f"  {fz.identify()}")

        n_steps = int((args.stop - args.start) * 1e6 / (args.step * 1e3)) + 1
        est_s   = n_steps * args.dwell
        print(f"  Scan: {args.start:.1f}-{args.stop:.1f} MHz  "
              f"{args.step:.0f} kHz step  {n_steps} points  "
              f"~{est_s:.1f} s/sweep")

        run_scan(fz,
                 start_hz   = args.start * 1e6,
                 stop_hz    = args.stop  * 1e6,
                 step_hz    = args.step  * 1e3,
                 dwell_s    = args.dwell,
                 log_file   = args.log,
                 continuous = args.continuous)

    except KeyboardInterrupt:
        pass
    except Exception as exc:
        import traceback
        print(f"\nError: {exc}")
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
