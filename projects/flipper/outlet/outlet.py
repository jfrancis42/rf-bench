#!/usr/bin/env python3
"""
Flipper Zero 433 MHz Outlet Controller

Learns on/off codes for 433 MHz wireless outlets via Flipper raw capture,
stores in outlets.json, and serves a REST API for remote control.

Subcommands:
  learn --name NAME        capture on and off codes for an outlet
  send  --name NAME --state on|off   transmit a stored code
  serve --port N           start REST daemon

Usage:
  python outlet.py learn --name "Living Room Lamp"
  python outlet.py send  --name "Living Room Lamp" --state on
  python outlet.py serve --port 8096
"""

import argparse
import json
import os
import signal
import sys
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import urlparse

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                '..', 'rf-bench'))
from rf_bench.flipper import FlipperZero

# ---------------------------------------------------------------------------
# Defaults
# ---------------------------------------------------------------------------
DEFAULT_SERIAL    = "/dev/ttyACM0"
DEFAULT_OUTLETS   = "outlets.json"
DEFAULT_PORT      = 8096
DEFAULT_FREQ_MHZ  = 433.92
REPEAT_TX         = 5

_running = True
_fz: FlipperZero = None
_outlets: dict = {}
_outlets_path = DEFAULT_OUTLETS


def _sigint_handler(sig, frame):
    global _running
    _running = False
    print("\n  [Ctrl+C]")
    sys.exit(0)


signal.signal(signal.SIGINT, _sigint_handler)


# ---------------------------------------------------------------------------
# Storage
# ---------------------------------------------------------------------------

def load_outlets(path: str) -> dict:
    if os.path.exists(path):
        with open(path) as fh:
            return json.load(fh)
    return {}


def save_outlets(outlets: dict, path: str) -> None:
    with open(path, "w") as fh:
        json.dump(outlets, fh, indent=2)


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------

def cmd_learn(fz: FlipperZero, outlets: dict, name: str) -> None:
    """Interactively capture ON and OFF codes for an outlet."""
    print(f"\n[LEARN]  outlet='{name}'")
    outlet = outlets.get(name, {"name": name, "freq_hz": DEFAULT_FREQ_MHZ * 1e6})

    for state in ("on", "off"):
        print(f"\n  Press the {state.upper()} button on your outlet remote ...")
        raw = fz.subghz_get_raw(int(outlet["freq_hz"]), duration_s=5.0)
        if not raw:
            print(f"  No signal captured for {state.upper()}. Skipping.")
            continue

        # Extract timings from raw Flipper output
        timings = _parse_raw_timings(raw)
        if timings:
            outlet[state] = {"timings_us": timings, "raw": raw}
            print(f"  Captured {len(timings)} timing edges for {state.upper()}")
        else:
            # Store the raw string for replay
            outlet[state] = {"raw": raw}
            print(f"  Stored raw capture for {state.upper()}")

    outlets[name] = outlet
    print(f"\n  Outlet '{name}' saved.")


def _parse_raw_timings(raw: str) -> list:
    """Extract pulse timings from Flipper raw output."""
    for line in raw.splitlines():
        line = line.strip()
        if line.startswith("RAW_Data:") or line.startswith("Data:"):
            data = line.split(":", 1)[1].strip()
            try:
                return [int(t) for t in data.split()]
            except ValueError:
                pass
    return []


def transmit_outlet(fz: FlipperZero, outlet: dict, state: str) -> bool:
    """Transmit the stored code for an outlet state. Returns True on success."""
    if state not in outlet:
        return False
    entry    = outlet[state]
    freq_hz  = int(outlet.get("freq_hz", DEFAULT_FREQ_MHZ * 1e6))
    timings  = entry.get("timings_us", [])

    if timings:
        fz.subghz_transmit_raw(freq_hz, timings, preset='ook650')
    else:
        # Fall back to subghz_get_raw replay not possible directly;
        # log an error
        print(f"  Warning: no timings stored for {state}; cannot transmit")
        return False
    return True


def cmd_send(fz: FlipperZero, outlets: dict, name: str, state: str) -> None:
    """Send a stored outlet code."""
    if name not in outlets:
        print(f"Error: outlet '{name}' not found. Use 'learn' first.")
        sys.exit(1)
    outlet = outlets[name]
    ok = transmit_outlet(fz, outlet, state)
    if ok:
        print(f"  Sent {state.upper()} to '{name}'")
    else:
        print(f"  Failed to send {state.upper()} to '{name}'")


# ---------------------------------------------------------------------------
# HTTP server
# ---------------------------------------------------------------------------

class OutletHandler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        print(f"  [{self.address_string()}] {fmt % args}")

    def _respond(self, code: int, data: dict) -> None:
        body = json.dumps(data).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", len(body))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        parsed = urlparse(self.path)
        if parsed.path == "/outlets":
            summary = {
                name: {"on": "on" in o, "off": "off" in o}
                for name, o in _outlets.items()
            }
            self._respond(200, summary)
        else:
            self._respond(404, {"ok": False, "error": "not found"})

    def do_POST(self):
        parsed = urlparse(self.path)
        parts  = parsed.path.strip("/").split("/")
        # /outlets/NAME/on  or  /outlets/NAME/off
        if len(parts) == 3 and parts[0] == "outlets" and parts[2] in ("on", "off"):
            name  = parts[1]
            state = parts[2]
            if name not in _outlets:
                self._respond(404, {"ok": False, "error": f"outlet '{name}' not found"})
                return
            ok = transmit_outlet(_fz, _outlets[name], state)
            if ok:
                self._respond(200, {"ok": True, "outlet": name, "state": state})
            else:
                self._respond(500, {"ok": False, "error": f"no timings for {state}"})
        else:
            self._respond(404, {"ok": False, "error": "not found"})


def cmd_serve(port: int, outlets: dict) -> None:
    """Start HTTP REST daemon."""
    global _outlets
    _outlets = outlets
    server = HTTPServer(("", port), OutletHandler)
    print(f"Listening on port {port}")
    print("  GET  /outlets")
    print("  POST /outlets/NAME/on")
    print("  POST /outlets/NAME/off")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    global _fz, _outlets_path

    parser = argparse.ArgumentParser(
        description="Learn and control 433 MHz wireless outlets via Flipper Zero",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python outlet.py learn --name "Desk Lamp"
  python outlet.py send  --name "Desk Lamp" --state on
  python outlet.py serve --port 8096
  curl -X POST http://localhost:8096/outlets/Desk%20Lamp/on
""",
    )
    parser.add_argument("--serial",   default=DEFAULT_SERIAL, metavar="PORT",
                        help=f"Flipper serial port (default {DEFAULT_SERIAL})")
    parser.add_argument("--outlets",  default=DEFAULT_OUTLETS, metavar="FILE",
                        help=f"Outlets JSON file (default {DEFAULT_OUTLETS})")

    sub = parser.add_subparsers(dest="command", required=True)

    lrn = sub.add_parser("learn", help="Capture on/off codes for an outlet")
    lrn.add_argument("--name", required=True, help="Outlet name")

    snd = sub.add_parser("send", help="Transmit a stored code")
    snd.add_argument("--name",  required=True, help="Outlet name")
    snd.add_argument("--state", required=True, choices=["on", "off"], help="State to send")

    srv = sub.add_parser("serve", help="Start REST daemon")
    srv.add_argument("--port", type=int, default=DEFAULT_PORT, metavar="N",
                     help=f"HTTP port (default {DEFAULT_PORT})")

    args = parser.parse_args()
    _outlets_path = args.outlets

    outlets = load_outlets(args.outlets)

    fz = None
    if args.command in ("learn", "send"):
        print(f"Connecting to Flipper @ {args.serial} ...")
        fz = FlipperZero(args.serial)
        print(f"  {fz.identify()}")
        _fz = fz
    elif args.command == "serve":
        print(f"Connecting to Flipper @ {args.serial} ...")
        fz = FlipperZero(args.serial)
        print(f"  {fz.identify()}")
        _fz = fz

    try:
        if args.command == "learn":
            cmd_learn(fz, outlets, args.name)
        elif args.command == "send":
            cmd_send(fz, outlets, args.name, args.state)
        elif args.command == "serve":
            cmd_serve(args.port, outlets)
    except KeyboardInterrupt:
        pass
    except Exception as exc:
        import traceback
        print(f"\nError: {exc}")
        traceback.print_exc()
        sys.exit(1)
    finally:
        save_outlets(outlets, args.outlets)


if __name__ == "__main__":
    main()
