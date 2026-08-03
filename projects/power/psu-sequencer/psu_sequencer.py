#!/usr/bin/env python3
"""
Power-On/Power-Off Sequencer — SPD3303X

Executes multi-channel power sequences with precise timing.
Reads sequence from a JSON file.  Supports repeat/cycle mode
and overcurrent abort.

Usage:
  python psu_sequencer.py --sequence fpga.json
  python psu_sequencer.py --sequence board.json --cycles 10 --dwell 2.0
  python psu_sequencer.py --sequence test.json --abort-ma 500

Sequence JSON format:
  {"name": "My Board", "steps": [
    {"t_ms": 0,   "ch": 1, "action": "on",  "volts": 1.0, "ilim_a": 0.5},
    {"t_ms": 10,  "ch": 2, "action": "on",  "volts": 3.3, "ilim_a": 1.0},
    {"t_ms": 500, "ch": 2, "action": "off"},
    {"t_ms": 510, "ch": 1, "action": "off"}
  ]}
"""

import argparse
import json
import os
import signal
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                '..', 'rf-bench'))

from rf_bench.siglent import SPD3303X  # noqa: E402
from rf_bench import connect

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

DEFAULT_PSU_HOST = None  # Now uses inventory
DEFAULT_CYCLES   = 1
DEFAULT_DWELL    = 1.0    # seconds between cycles

_running = True


def _sigint_handler(sig, frame):
    global _running
    _running = False
    print("\n  [Ctrl+C received — completing current step and powering off ...]")


signal.signal(signal.SIGINT, _sigint_handler)

# ---------------------------------------------------------------------------
# Sequence validation
# ---------------------------------------------------------------------------

def load_sequence(path: str) -> dict:
    """Load and validate a sequence JSON file."""
    with open(path) as fh:
        seq = json.load(fh)

    if 'steps' not in seq or not isinstance(seq['steps'], list):
        raise ValueError("Sequence JSON must have a 'steps' list.")

    for i, step in enumerate(seq['steps']):
        if 'ch' not in step or step['ch'] not in (1, 2, 3):
            raise ValueError(f"Step {i}: 'ch' must be 1, 2, or 3.")
        if 'action' not in step or step['action'] not in ('on', 'off'):
            raise ValueError(f"Step {i}: 'action' must be 'on' or 'off'.")
        if 't_ms' not in step:
            raise ValueError(f"Step {i}: missing 't_ms'.")
        if step['action'] == 'on':
            if 'volts' not in step:
                raise ValueError(f"Step {i}: 'on' action requires 'volts'.")
            if 'ilim_a' not in step:
                raise ValueError(f"Step {i}: 'on' action requires 'ilim_a'.")

    # Sort by time
    seq['steps'] = sorted(seq['steps'], key=lambda s: s['t_ms'])
    return seq


# ---------------------------------------------------------------------------
# Single cycle execution
# ---------------------------------------------------------------------------

def execute_cycle(psu: SPD3303X, steps: list[dict],
                  abort_ma: float | None, cycle_num: int) -> bool:
    """
    Execute one power sequence cycle.

    Returns True if cycle completed normally, False if aborted (overcurrent or SIGINT).
    """
    t_start = time.monotonic()
    step_idx = 0
    all_off  = set()   # channels currently off

    print(f"\n  Cycle {cycle_num} — executing {len(steps)} steps")

    while _running:
        now_ms = (time.monotonic() - t_start) * 1000.0

        # Check if any remaining steps are due
        while step_idx < len(steps) and steps[step_idx]['t_ms'] <= now_ms:
            step = steps[step_idx]
            ch   = step['ch']
            act  = step['action']

            if act == 'on':
                volts = float(step['volts'])
                ilim  = float(step['ilim_a'])
                psu.set_voltage(ch, volts)
                psu.set_current(ch, ilim)
                psu.output_on(ch)
                all_off.discard(ch)
                print(f"  t={now_ms:6.0f} ms  CH{ch} ON  {volts:.3f} V  lim={ilim:.3f} A")
            else:
                psu.output_off(ch)
                all_off.add(ch)
                print(f"  t={now_ms:6.0f} ms  CH{ch} OFF")

            step_idx += 1

        # All steps done?
        if step_idx >= len(steps):
            break

        # Overcurrent check
        if abort_ma is not None:
            for ch in (1, 2):
                if ch in all_off:
                    continue
                try:
                    i_ma = psu.measure_current(ch) * 1000.0
                    if i_ma > abort_ma:
                        print(f"\n  ABORT: CH{ch} current {i_ma:.1f} mA > limit {abort_ma:.1f} mA")
                        _all_off(psu)
                        return False
                except Exception:
                    pass

        time.sleep(0.001)   # 1 ms tick

    return True


def _all_off(psu: SPD3303X) -> None:
    """Emergency power-off all channels."""
    for ch in (1, 2, 3):
        try:
            psu.output_off(ch)
        except Exception:
            pass


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Power-on/power-off sequencer — SPD3303X",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Sequence JSON format:
  {"name": "FPGA board", "steps": [
    {"t_ms": 0,   "ch": 1, "action": "on",  "volts": 1.0, "ilim_a": 0.5},
    {"t_ms": 10,  "ch": 2, "action": "on",  "volts": 3.3, "ilim_a": 1.0},
    {"t_ms": 500, "ch": 2, "action": "off"},
    {"t_ms": 510, "ch": 1, "action": "off"}
  ]}

Examples:
  python psu_sequencer.py --sequence fpga.json
  python psu_sequencer.py --sequence board.json --cycles 100 --dwell 2.0
  python psu_sequencer.py --sequence test.json --abort-ma 250
""",
    )
    parser.add_argument("--psu",       default=DEFAULT_PSU_HOST, metavar="HOST",
                        help=f"SPD3303X IP address (default {DEFAULT_PSU_HOST})")
    parser.add_argument("--sequence",  required=True, metavar="FILE",
                        help="Power sequence JSON file (required)")
    parser.add_argument("--cycles",    type=int, default=DEFAULT_CYCLES, metavar="N",
                        help=f"Number of cycles to execute (default {DEFAULT_CYCLES})")
    parser.add_argument("--dwell",     type=float, default=DEFAULT_DWELL, metavar="S",
                        help=f"Delay between cycles in seconds (default {DEFAULT_DWELL})")
    parser.add_argument("--abort-ma",  type=float, default=None, metavar="MA",
                        help="Abort and power off if any channel exceeds this current (mA)")

    args = parser.parse_args()

    # Load sequence
    try:
        seq = load_sequence(args.sequence)
    except (FileNotFoundError, json.JSONDecodeError, ValueError) as exc:
        print(f"Error loading sequence: {exc}")
        sys.exit(1)

    steps = seq['steps']
    name  = seq.get('name', args.sequence)
    total_ms = max(s['t_ms'] for s in steps) if steps else 0

    print(f"Sequence    : {name}")
    print(f"Steps       : {len(steps)}")
    print(f"Duration    : {total_ms} ms")
    print(f"Cycles      : {args.cycles}")
    if args.abort_ma:
        print(f"Abort limit : {args.abort_ma} mA")

    print(f"\nConnecting to SPD3303X via inventory ...")
    psu = None
    try:
        psu = connect(args.psu or 'spd')
        print(f"  {psu.identify()}")

        # Initial state — all off
        _all_off(psu)

        for cycle in range(1, args.cycles + 1):
            if not _running:
                break
            ok = execute_cycle(psu, steps, args.abort_ma, cycle)
            if not ok:
                break
            if cycle < args.cycles and _running:
                print(f"  [dwell {args.dwell:.1f} s]")
                time.sleep(args.dwell)

        print(f"\n  Done — powering off all channels.")

    except ConnectionRefusedError as exc:
        print(f"\nCannot connect to PSU: {exc}")
        sys.exit(1)
    except OSError as exc:
        print(f"\nNetwork error: {exc}")
        sys.exit(1)
    except Exception as exc:
        import traceback
        print(f"\nUnexpected error: {exc}")
        traceback.print_exc()
    finally:
        if psu is not None:
            _all_off(psu)
            try:
                psu.disconnect()
            except Exception:
                pass


if __name__ == "__main__":
    main()
