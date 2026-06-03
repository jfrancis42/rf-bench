#!/usr/bin/env python3
"""
Flipper Zero IR Code Discoverer

Systematically transmits all command codes (0-255) for a given IR protocol
and device address. User watches the target device and presses Enter to flag
interesting responses. Prints a summary of flagged codes at the end.

Usage:
  python ir_discover.py --protocol NEC --address 0x07
  python ir_discover.py --protocol SIRC --address 0x01 --delay 0.1
  python ir_discover.py --protocol RC5 --address 0x00 --delay 0.08
"""

import argparse
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
DEFAULT_SERIAL   = "/dev/ttyACM0"
DEFAULT_PROTOCOL = "NEC"
DEFAULT_DELAY    = 0.08    # seconds between codes
SUPPORTED_PROTOS = ["NEC", "SIRC", "RC5", "Samsung32"]

_running = True


def _sigint_handler(sig, frame):
    global _running
    _running = False
    print("\n  [Ctrl+C -- stopping scan]")


signal.signal(signal.SIGINT, _sigint_handler)


# ---------------------------------------------------------------------------
# Discovery loop
# ---------------------------------------------------------------------------

def discover(fz: FlipperZero, protocol: str, address: int,
             delay_s: float) -> list:
    """
    Send all 256 command codes. Return list of flagged (code, label) tuples.
    Press Enter at any time to flag the current code.
    """
    flagged = []
    print(f"\n[DISCOVERY]  protocol={protocol}  address=0x{address:02X}")
    print("  Sending codes 0x00-0xFF. Press Enter to FLAG the current code.")
    print("  Press Ctrl+C to stop early.\n")

    import select
    import termios
    import tty

    # Put stdin in non-blocking mode
    old_settings = termios.tcgetattr(sys.stdin)
    try:
        tty.setcbreak(sys.stdin.fileno())

        for code in range(256):
            if not _running:
                break

            sys.stdout.write(f"\r  Sending 0x{code:02X} ({code:3d}/255) ... "
                             f"flagged: {len(flagged)}")
            sys.stdout.flush()

            fz.ir_transmit(protocol, address, code)

            # Sleep with non-blocking stdin check
            t_end = time.time() + delay_s
            while time.time() < t_end:
                rlist, _, _ = select.select([sys.stdin], [], [], 0.01)
                if rlist:
                    ch = sys.stdin.read(1)
                    if ch in ('\n', '\r', ' '):
                        label = f"0x{code:02X}"
                        flagged.append((code, label))
                        sys.stdout.write(f"\n  *** FLAGGED: code=0x{code:02X} ({code}) ***\n")
                        sys.stdout.flush()
                        break

    finally:
        termios.tcsetattr(sys.stdin, termios.TCSADRAIN, old_settings)

    print()
    return flagged


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Systematically send all IR command codes and flag interesting responses",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python ir_discover.py --protocol NEC --address 0x07
  python ir_discover.py --protocol SIRC --address 0x01 --delay 0.1
  python ir_discover.py --protocol Samsung32 --address 0x07 --delay 0.08
""",
    )
    parser.add_argument("--protocol", default=DEFAULT_PROTOCOL,
                        choices=SUPPORTED_PROTOS,
                        help=f"IR protocol (default {DEFAULT_PROTOCOL})")
    parser.add_argument("--address",  required=True,
                        help="Device address in hex (e.g. 0x07)")
    parser.add_argument("--delay",    type=float, default=DEFAULT_DELAY, metavar="S",
                        help=f"Delay between codes in seconds (default {DEFAULT_DELAY})")
    parser.add_argument("--serial",   default=DEFAULT_SERIAL, metavar="PORT",
                        help=f"Flipper serial port (default {DEFAULT_SERIAL})")

    args = parser.parse_args()

    try:
        address = int(args.address, 16) if args.address.startswith("0x") else int(args.address)
    except ValueError:
        print(f"Error: invalid address '{args.address}'. Use hex (0x07) or decimal.")
        sys.exit(1)

    try:
        print(f"Connecting to Flipper @ {args.serial} ...")
        fz = FlipperZero(args.serial)
        print(f"  {fz.identify()}")

        flagged = discover(fz, args.protocol, address, args.delay)

        print("\n" + "=" * 60)
        print(f"SCAN COMPLETE  protocol={args.protocol}  address=0x{address:02X}")
        if flagged:
            print(f"\nFlagged {len(flagged)} codes:")
            for code, label in flagged:
                print(f"  0x{code:02X}  ({code:3d})  {label}")
        else:
            print("No codes flagged.")
        print("=" * 60)

    except KeyboardInterrupt:
        pass
    except Exception as exc:
        import traceback
        print(f"\nError: {exc}")
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
