#!/usr/bin/env python3
"""
Glitch / Anomaly Trap — SDS2000X unattended overnight capture

Configures the scope in single-trigger mode, waits for each trigger event,
saves every captured waveform to disk with a timestamp, and optionally sends
an SMS alert after N events accumulate.

Usage:
  python scope_glitch.py --channel 1 --threshold 2.5 --above --outdir glitches/
  python scope_glitch.py --threshold 0 --duration 0.01 --alert 10
"""

import argparse
import os
import signal
import sys
import time
from datetime import datetime

import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                '..', 'rf-bench'))

from rf_bench.siglent import SDS2000X  # noqa: E402
from rf_bench import connect

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

DEFAULT_SCOPE_HOST = None  # Now uses inventory
DEFAULT_CHANNEL    = 1
DEFAULT_THRESHOLD  = 0.0    # V
DEFAULT_DURATION   = 0.01   # capture window in seconds (10 ms)
DEFAULT_OUTDIR     = "glitches"
TRIGGER_POLL_S     = 0.1    # seconds between trigger-status polls

_running = True


def _sigint_handler(sig, frame):
    global _running
    _running = False
    print("\n  [Ctrl+C received — stopping capture ...]")


signal.signal(signal.SIGINT, _sigint_handler)

# ---------------------------------------------------------------------------
# SMS alert (voipms proxy — best effort, non-fatal)
# ---------------------------------------------------------------------------

def send_sms_alert(n_events: int, outdir: str) -> None:
    """Send SMS via the local voip.ms proxy.  Non-fatal on failure."""
    try:
        import urllib.request
        import urllib.parse
        import json
        import pathlib

        creds_file = pathlib.Path.home() / "Dropbox/build/creds/voipms-rest.txt"
        if not creds_file.exists():
            return

        lines = creds_file.read_text().strip().splitlines()
        if len(lines) < 3:
            return
        url, user, password = lines[0].strip(), lines[1].strip(), lines[2].strip()

        msg = f"scope_glitch: {n_events} events captured in {outdir}"
        payload = json.dumps({"to": user, "message": msg}).encode()

        req = urllib.request.Request(
            f"{url}/sms", data=payload,
            headers={'Content-Type': 'application/json'},
            method='POST',
        )
        import base64
        cred = base64.b64encode(f"{user}:{password}".encode()).decode()
        req.add_header('Authorization', f'Basic {cred}')

        with urllib.request.urlopen(req, timeout=10) as resp:
            print(f"  [SMS sent: {resp.status}]")
    except Exception as exc:
        print(f"  [SMS failed: {exc}]")


# ---------------------------------------------------------------------------
# Capture loop
# ---------------------------------------------------------------------------

def run_glitch_trap(scope: SDS2000X, args: argparse.Namespace) -> None:
    """Main unattended capture loop."""
    os.makedirs(args.outdir, exist_ok=True)
    slope    = 'rising' if args.above else 'falling'
    n_events = 0

    print(f"\n  Channel   : CH{args.channel}")
    print(f"  Threshold : {args.threshold:+.3f} V  ({slope})")
    print(f"  Duration  : {args.duration*1000:.1f} ms per capture")
    print(f"  Output    : {args.outdir}/")
    if args.alert:
        print(f"  SMS alert : every {args.alert} events")
    print("\n  Waiting for triggers ... (Ctrl+C to stop)\n")

    scope.set_trigger_edge(f"C{args.channel}", args.threshold, slope=slope)

    while _running:
        try:
            scope.arm_trigger()   # SINGLE trigger mode + :RUN
            # Poll until trigger fires or interrupted
            triggered = False
            t_arm = time.time()
            while _running:
                status = scope.get_trigger_status()
                if status in ('STOP', 'TD'):   # trigger done
                    triggered = True
                    break
                if time.time() - t_arm > 30.0:
                    break   # timeout — re-arm
                time.sleep(TRIGGER_POLL_S)

            if not triggered or not _running:
                continue

            waveform, sr = scope.capture_waveform(args.channel)
            ts_str = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
            fname  = os.path.join(args.outdir, f"glitch_{ts_str}.npz")
            np.savez_compressed(
                fname,
                waveform=waveform,
                sample_rate=np.array([sr]),
                timestamp=np.array([time.time()]),
            )
            n_events += 1
            peak_v = float(np.max(np.abs(waveform)))
            print(f"  [{n_events:5d}]  {ts_str}  peak={peak_v:.3f} V  → {fname}")

            if args.alert and n_events % args.alert == 0:
                send_sms_alert(n_events, args.outdir)

        except Exception as exc:
            print(f"  [error: {exc}]")
            time.sleep(1.0)

    print(f"\n  Total events captured: {n_events}")
    print(f"  Files in: {args.outdir}/")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Glitch / anomaly trap — SDS2000X unattended capture",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python scope_glitch.py --channel 1 --threshold 2.5 --above --outdir glitches/
  python scope_glitch.py --threshold 0 --above --duration 0.005 --alert 5
  python scope_glitch.py --threshold -1.0 --below --outdir undervolt/
""",
    )
    parser.add_argument("--scope",    default=DEFAULT_SCOPE_HOST, metavar="HOST",
                        help=f"SDS2000X IP address (default {DEFAULT_SCOPE_HOST})")
    parser.add_argument("--channel",  type=int, default=DEFAULT_CHANNEL, metavar="N",
                        help=f"Scope channel (default {DEFAULT_CHANNEL})")
    parser.add_argument("--threshold", type=float, default=DEFAULT_THRESHOLD, metavar="V",
                        help=f"Trigger threshold in V (default {DEFAULT_THRESHOLD})")

    polarity = parser.add_mutually_exclusive_group()
    polarity.add_argument("--above", dest='above', action='store_true', default=True,
                          help="Trigger on rising edge (default)")
    polarity.add_argument("--below", dest='above', action='store_false',
                          help="Trigger on falling edge")

    parser.add_argument("--duration", type=float, default=DEFAULT_DURATION, metavar="S",
                        help=f"Capture window in seconds (default {DEFAULT_DURATION})")
    parser.add_argument("--outdir",   default=DEFAULT_OUTDIR, metavar="DIR",
                        help=f"Output directory (default {DEFAULT_OUTDIR})")
    parser.add_argument("--alert",    type=int, default=None, metavar="N",
                        help="Send SMS after every N events (requires voipms-rest.txt)")

    args = parser.parse_args()

    print(f"Connecting to SDS2000X via inventory ...")
    scope = None
    try:
        scope = connect(args.scope or 'sds')
        print(f"  {scope.identify()}")
        run_glitch_trap(scope, args)
    except ConnectionRefusedError as exc:
        print(f"\nCannot connect to scope: {exc}")
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
        if scope is not None:
            try:
                scope.disconnect()
            except Exception:
                pass


if __name__ == "__main__":
    main()
