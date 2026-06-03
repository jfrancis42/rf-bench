#!/usr/bin/env python3
"""
relay_solt.py — Automated SOLT calibration for HP 8712B VNA

Drives an XL9535 I2C relay board (via Bus Pirate) to step through SOLT
calibration standards automatically.  Instead of manually swapping cables
for each standard, all standards are permanently wired to relays and the
script switches between them.

Standard relay assignment (defaults, fully configurable):
    Port 1: relay 0 = OPEN, relay 1 = SHORT, relay 2 = LOAD (50 Ω), relay 3 = DUT
    Port 2: relay 4 = OPEN, relay 5 = SHORT, relay 6 = LOAD (50 Ω), relay 7 = DUT
    THRU  : relay 3 + relay 7 closed simultaneously (connects P1 to P2)

GPIB calibration sequence (HP 8712B):
    CALIS11A → port-1 OPEN
    CALIS11B → port-1 SHORT
    CALIL1   → port-1 LOAD
    CALIS22A → port-2 OPEN
    CALIS22B → port-2 SHORT
    CALIL2   → port-2 LOAD
    CALT     → THRU
    SAVC     → save / complete calibration

Usage:
    python relay_solt.py [options]
    python relay_solt.py --dry-run
    python relay_solt.py --one-port --save-cal solt_cal.json
    python relay_solt.py --dut
"""

import argparse
import json
import time

from rf_bench.hp import HP8712B
from rf_bench.buspirate import BusPirate
from rf_bench.relay import XL9535

# ---------------------------------------------------------------------------
# Defaults
# ---------------------------------------------------------------------------

DEFAULT_VNA         = "10.1.1.70"
DEFAULT_BP          = "/dev/ttyUSB1"
DEFAULT_ADDR        = 0x20
DEFAULT_START_HZ    = 300e3        # 300 kHz (HP 8712B minimum)
DEFAULT_STOP_HZ     = 1.3e9       # 1.3 GHz (HP 8712B maximum)
DEFAULT_POINTS      = 801
DEFAULT_SETTLE_MS   = 200          # ms to wait after relay switch before GPIB command
DEFAULT_VNA_WAIT_MS = 500          # ms to wait after GPIB command for VNA to process

# Default relay assignments
DEFAULT_P1_OPEN  = 0
DEFAULT_P1_SHORT = 1
DEFAULT_P1_LOAD  = 2
DEFAULT_P1_DUT   = 3
DEFAULT_P2_OPEN  = 4
DEFAULT_P2_SHORT = 5
DEFAULT_P2_LOAD  = 6
DEFAULT_P2_DUT   = 7


# ---------------------------------------------------------------------------
# Cal step helpers
# ---------------------------------------------------------------------------

def _relay_mask(relay_nums):
    """Build a bitmask from a list of relay indices."""
    mask = 0
    for n in relay_nums:
        mask |= (1 << n)
    return mask


def _do_step(label, relay_indices, gpib_cmd, relay_board, vna, settle_ms, dry_run):
    """
    Execute one calibration step: switch relay, wait, send GPIB command.

    Parameters
    ----------
    label        : str   Human-readable name of the standard (e.g. "port-1 OPEN")
    relay_indices: list  Relay numbers to close (use set_all for THRU, close_only for single)
    gpib_cmd     : str   GPIB command string to send to the VNA
    relay_board  : XL9535 or None (None in dry-run mode)
    vna          : HP8712B or None (None in dry-run mode)
    settle_ms    : int   Settle time in milliseconds
    dry_run      : bool  If True, print actions instead of executing
    """
    mask = _relay_mask(relay_indices)
    relay_str = ", ".join(f"relay {n}" for n in relay_indices)
    print(f"  Switching to {label} ({relay_str}, mask=0x{mask:02X}) ...")

    if not dry_run:
        relay_board.set_all(mask)
        time.sleep(settle_ms / 1000.0)

    print(f"  GPIB: {gpib_cmd}")

    if not dry_run:
        vna.send(gpib_cmd)
        time.sleep(DEFAULT_VNA_WAIT_MS / 1000.0)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    ap = argparse.ArgumentParser(
        description="Automated SOLT calibration for HP 8712B VNA via relay board",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Full 2-port SOLT calibration (default settings):
  python relay_solt.py

  # 1-port only, save calibration state to file:
  python relay_solt.py --one-port --save-cal solt_p1.json

  # Dry run to verify relay wiring before connecting instruments:
  python relay_solt.py --dry-run

  # After calibration, connect DUT automatically:
  python relay_solt.py --dut

  # Custom frequency range (FM band check, in Hz):
  python relay_solt.py --start 88e6 --stop 108e6 --points 401
""",
    )

    # Instrument connections
    ap.add_argument("--vna",        default=DEFAULT_VNA,
                    metavar="HOST", help=f"HP 8712B IP address (default {DEFAULT_VNA})")
    ap.add_argument("--bp",         default=DEFAULT_BP,
                    metavar="PORT", help=f"Bus Pirate serial port (default {DEFAULT_BP})")
    ap.add_argument("--addr",       default=DEFAULT_ADDR, type=lambda x: int(x, 0),
                    metavar="ADDR", help=f"XL9535 I2C address (default 0x{DEFAULT_ADDR:02X})")

    # Sweep settings
    ap.add_argument("--start",      default=DEFAULT_START_HZ, type=float,
                    metavar="FREQ", help=f"Start frequency Hz (default {DEFAULT_START_HZ:.0f})")
    ap.add_argument("--stop",       default=DEFAULT_STOP_HZ,  type=float,
                    metavar="FREQ", help=f"Stop frequency Hz (default {DEFAULT_STOP_HZ:.0f})")
    ap.add_argument("--points",     default=DEFAULT_POINTS,   type=int,
                    metavar="N",    help=f"Sweep points (default {DEFAULT_POINTS})")

    # Relay assignments
    ap.add_argument("--p1-open",    default=DEFAULT_P1_OPEN,  type=int, metavar="N",
                    help=f"Relay for port-1 OPEN  (default {DEFAULT_P1_OPEN})")
    ap.add_argument("--p1-short",   default=DEFAULT_P1_SHORT, type=int, metavar="N",
                    help=f"Relay for port-1 SHORT (default {DEFAULT_P1_SHORT})")
    ap.add_argument("--p1-load",    default=DEFAULT_P1_LOAD,  type=int, metavar="N",
                    help=f"Relay for port-1 LOAD  (default {DEFAULT_P1_LOAD})")
    ap.add_argument("--p1-dut",     default=DEFAULT_P1_DUT,   type=int, metavar="N",
                    help=f"Relay for port-1 DUT / THRU end (default {DEFAULT_P1_DUT})")
    ap.add_argument("--p2-open",    default=DEFAULT_P2_OPEN,  type=int, metavar="N",
                    help=f"Relay for port-2 OPEN  (default {DEFAULT_P2_OPEN})")
    ap.add_argument("--p2-short",   default=DEFAULT_P2_SHORT, type=int, metavar="N",
                    help=f"Relay for port-2 SHORT (default {DEFAULT_P2_SHORT})")
    ap.add_argument("--p2-load",    default=DEFAULT_P2_LOAD,  type=int, metavar="N",
                    help=f"Relay for port-2 LOAD  (default {DEFAULT_P2_LOAD})")
    ap.add_argument("--p2-dut",     default=DEFAULT_P2_DUT,   type=int, metavar="N",
                    help=f"Relay for port-2 DUT / THRU end (default {DEFAULT_P2_DUT})")

    # Timing
    ap.add_argument("--settle-ms",  default=DEFAULT_SETTLE_MS, type=int, metavar="MS",
                    help=f"Settle time after relay switch (default {DEFAULT_SETTLE_MS} ms)")

    # Modes
    ap.add_argument("--save-cal",   default=None, metavar="FILE",
                    help="Save calibration state JSON after completion")
    ap.add_argument("--one-port",   action="store_true",
                    help="1-port S11 calibration only (skip port-2 and THRU)")
    ap.add_argument("--dut",        action="store_true",
                    help="After calibration, switch to DUT position and wait")
    ap.add_argument("--dry-run",    action="store_true",
                    help="Print relay commands without executing (wiring verification)")

    args = ap.parse_args()

    # ------------------------------------------------------------------
    # Banner
    # ------------------------------------------------------------------
    print("rf-bench-relay-solt — automated SOLT calibration fixture")
    print(f"  VNA:     {args.vna}  ({args.start/1e6:.3f} MHz – {args.stop/1e6:.3f} MHz, {args.points} pts)")
    print(f"  Bus Pirate: {args.bp}  I2C addr 0x{args.addr:02X}")
    if args.one_port:
        print("  Mode:    1-port (S11 only)")
    else:
        print("  Mode:    2-port full SOLT")
    if args.dry_run:
        print("  *** DRY RUN — no hardware will be touched ***")
    print()

    # ------------------------------------------------------------------
    # Connect to hardware (unless dry-run)
    # ------------------------------------------------------------------
    relay_board = None
    bp_ctx      = None
    vna_ctx     = None

    if not args.dry_run:
        print("Connecting to Bus Pirate and XL9535 relay board ...")
        bp_ctx = BusPirate(args.bp)
        bp_ctx.set_pullups(True)
        bp_ctx.i2c_configure(speed_hz=100_000)
        relay_board = XL9535(bp_ctx, i2c_addr=args.addr,
                             active_high=True, num_relays=8)
        # __init__ already calls configure_outputs() and all_off()
        print("  Relay board: OK — all relays off")

        print(f"Connecting to HP 8712B at {args.vna} ...")
        vna_ctx = HP8712B(args.vna)
        print("  VNA: connected")

        print(f"  Setting sweep: {args.start/1e6:.3f}–{args.stop/1e6:.3f} MHz, {args.points} points ...")
        vna_ctx.setup_sweep(args.start, args.stop, args.points)
        print()

    # ------------------------------------------------------------------
    # SOLT calibration sequence
    # ------------------------------------------------------------------
    print("Starting SOLT calibration sequence ...")
    print()

    # Port-1 standards
    print("=== Port 1 calibration ===")
    _do_step("port-1 OPEN",  [args.p1_open],  "CALIS11A",
             relay_board, vna_ctx, args.settle_ms, args.dry_run)
    _do_step("port-1 SHORT", [args.p1_short], "CALIS11B",
             relay_board, vna_ctx, args.settle_ms, args.dry_run)
    _do_step("port-1 LOAD",  [args.p1_load],  "CALIL1",
             relay_board, vna_ctx, args.settle_ms, args.dry_run)
    print()

    # Port-2 standards + THRU (2-port mode only)
    if not args.one_port:
        print("=== Port 2 calibration ===")
        _do_step("port-2 OPEN",  [args.p2_open],  "CALIS22A",
                 relay_board, vna_ctx, args.settle_ms, args.dry_run)
        _do_step("port-2 SHORT", [args.p2_short], "CALIS22B",
                 relay_board, vna_ctx, args.settle_ms, args.dry_run)
        _do_step("port-2 LOAD",  [args.p2_load],  "CALIL2",
                 relay_board, vna_ctx, args.settle_ms, args.dry_run)
        print()

        print("=== THRU ===")
        # THRU: close both DUT relays simultaneously to connect port 1 to port 2
        _do_step("THRU (P1-DUT + P2-DUT)",
                 [args.p1_dut, args.p2_dut], "CALT",
                 relay_board, vna_ctx, args.settle_ms, args.dry_run)
        print()

    # Save calibration to VNA memory
    print("Saving calibration to VNA memory ...")
    if args.dry_run:
        print("  GPIB: SAVC")
    else:
        vna_ctx.send("SAVC")
        time.sleep(1.0)   # SAVC can take a moment

    print()
    print("Calibration complete.")
    print()

    # ------------------------------------------------------------------
    # Connect DUT (optional)
    # ------------------------------------------------------------------
    if args.dut:
        dut_relays = [args.p1_dut, args.p2_dut]
        dut_mask   = _relay_mask(dut_relays)
        print(f"Connecting DUT (relay {args.p1_dut} + relay {args.p2_dut}, mask=0x{dut_mask:02X}) ...")
        if not args.dry_run:
            relay_board.set_all(dut_mask)
        print("DUT connected — ready to measure.")
        print()

    # ------------------------------------------------------------------
    # Save calibration state JSON (optional)
    # ------------------------------------------------------------------
    if args.save_cal:
        state = {
            "vna":    args.vna,
            "start_hz": args.start,
            "stop_hz":  args.stop,
            "points":   args.points,
            "one_port": args.one_port,
            "relays": {
                "p1_open":  args.p1_open,
                "p1_short": args.p1_short,
                "p1_load":  args.p1_load,
                "p1_dut":   args.p1_dut,
                "p2_open":  args.p2_open,
                "p2_short": args.p2_short,
                "p2_load":  args.p2_load,
                "p2_dut":   args.p2_dut,
            },
            "settle_ms": args.settle_ms,
        }
        with open(args.save_cal, "w") as f:
            json.dump(state, f, indent=2)
        print(f"Calibration state saved to: {args.save_cal}")

    # ------------------------------------------------------------------
    # Cleanup
    # ------------------------------------------------------------------
    if not args.dry_run:
        if not args.dut:
            # Safe state: all relays off unless --dut left them connected
            relay_board.all_off()
        bp_ctx.i2c_exit()
        vna_ctx.close()


if __name__ == "__main__":
    main()
