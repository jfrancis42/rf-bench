#!/usr/bin/env python3
"""
Flipper Zero IR REST Daemon

HTTP server (~80 lines) exposing IR transmission as a REST API.

Endpoints:
  POST /ir/send     {"protocol":"NEC","address":7,"command":2}
  POST /ir/raw      {"timings_us":[...], "frequency":38000}
  POST /ir/replay   {"device":"TV","button":"POWER"}
  GET  /ir/receive  ?timeout=5

Loads button library from ir_library_db.json in current directory.

Usage:
  python ir_daemon.py --port 8099 --serial /dev/ttyACM0
  python ir_daemon.py --library my_library.json --port 8099
"""

import argparse
import json
import os
import signal
import sys
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import urlparse, parse_qs

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                '..', 'rf-bench'))
from rf_bench.flipper import FlipperZero

# ---------------------------------------------------------------------------
# Defaults
# ---------------------------------------------------------------------------
DEFAULT_PORT    = 8099
DEFAULT_SERIAL  = "/dev/ttyACM0"
DEFAULT_LIBRARY = "ir_library_db.json"

_fz: FlipperZero = None
_lib: dict = {}

_running = True


def _sigint_handler(sig, frame):
    global _running
    _running = False
    print("\n  [Ctrl+C -- shutting down]")
    sys.exit(0)


signal.signal(signal.SIGINT, _sigint_handler)


# ---------------------------------------------------------------------------
# Library
# ---------------------------------------------------------------------------

def load_library(path: str) -> dict:
    if os.path.exists(path):
        with open(path) as fh:
            return json.load(fh)
    return {"devices": {}}


# ---------------------------------------------------------------------------
# HTTP handler
# ---------------------------------------------------------------------------

class IRHandler(BaseHTTPRequestHandler):

    def log_message(self, fmt, *args):
        print(f"  [{self.address_string()}] {fmt % args}")

    def _respond(self, code: int, data: dict) -> None:
        body = json.dumps(data).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", len(body))
        self.end_headers()
        self.wfile.write(body)

    def _read_json(self) -> dict:
        length = int(self.headers.get("Content-Length", 0))
        if length == 0:
            return {}
        return json.loads(self.rfile.read(length))

    def do_GET(self):
        parsed = urlparse(self.path)
        qs = parse_qs(parsed.query)

        if parsed.path == "/ir/receive":
            timeout = float(qs.get("timeout", ["5"])[0])
            try:
                result = _fz.ir_receive(timeout_s=timeout)
                if result:
                    self._respond(200, {"ok": True, "result": result})
                else:
                    self._respond(200, {"ok": False, "error": "timeout"})
            except Exception as exc:
                self._respond(500, {"ok": False, "error": str(exc)})
        else:
            self._respond(404, {"ok": False, "error": "not found"})

    def do_POST(self):
        parsed = urlparse(self.path)
        try:
            body = self._read_json()
        except Exception as exc:
            self._respond(400, {"ok": False, "error": f"JSON parse error: {exc}"})
            return

        if parsed.path == "/ir/send":
            protocol = body.get("protocol", "NEC")
            address  = int(body.get("address", 0))
            command  = int(body.get("command", 0))
            try:
                _fz.ir_transmit(protocol, address, command)
                self._respond(200, {"ok": True})
            except Exception as exc:
                self._respond(500, {"ok": False, "error": str(exc)})

        elif parsed.path == "/ir/raw":
            timings = body.get("timings_us", [])
            freq    = int(body.get("frequency", 38000))
            if not timings:
                self._respond(400, {"ok": False, "error": "timings_us required"})
                return
            try:
                _fz.ir_transmit_raw(timings, frequency=freq)
                self._respond(200, {"ok": True})
            except Exception as exc:
                self._respond(500, {"ok": False, "error": str(exc)})

        elif parsed.path == "/ir/replay":
            device_name = body.get("device", "")
            button_name = body.get("button", "")
            if not device_name or not button_name:
                self._respond(400, {"ok": False, "error": "device and button required"})
                return
            device = _lib.get("devices", {}).get(device_name)
            if device is None:
                self._respond(404, {"ok": False, "error": f"device '{device_name}' not found"})
                return
            btn = device.get("buttons", {}).get(button_name)
            if btn is None:
                available = list(device.get("buttons", {}).keys())
                self._respond(404, {"ok": False,
                                    "error": f"button '{button_name}' not found",
                                    "available": available})
                return
            try:
                if btn.get("type") == "parsed":
                    _fz.ir_transmit(btn["protocol"], btn["address"], btn["command"])
                else:
                    _fz.ir_transmit_raw(btn["timings_us"],
                                        frequency=btn.get("frequency", 38000))
                self._respond(200, {"ok": True})
            except Exception as exc:
                self._respond(500, {"ok": False, "error": str(exc)})

        else:
            self._respond(404, {"ok": False, "error": "not found"})


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    global _fz, _lib

    parser = argparse.ArgumentParser(
        description="Flipper Zero IR REST daemon",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Endpoints:
  POST /ir/send    {"protocol":"NEC","address":7,"command":2}
  POST /ir/raw     {"timings_us":[9000,4500,...], "frequency":38000}
  POST /ir/replay  {"device":"TV","button":"POWER"}
  GET  /ir/receive ?timeout=5

Examples:
  python ir_daemon.py --port 8099
  curl -X POST http://localhost:8099/ir/send -d '{"protocol":"NEC","address":7,"command":2}'
  curl http://localhost:8099/ir/receive?timeout=5
""",
    )
    parser.add_argument("--port",    type=int, default=DEFAULT_PORT, metavar="N",
                        help=f"HTTP port (default {DEFAULT_PORT})")
    parser.add_argument("--library", default=DEFAULT_LIBRARY, metavar="FILE",
                        help=f"Library JSON file (default {DEFAULT_LIBRARY})")
    parser.add_argument("--serial",  default=DEFAULT_SERIAL, metavar="PORT",
                        help=f"Flipper serial port (default {DEFAULT_SERIAL})")

    args = parser.parse_args()

    print(f"Loading library from {args.library} ...")
    _lib = load_library(args.library)
    n_devices = len(_lib.get("devices", {}))
    print(f"  {n_devices} devices loaded")

    print(f"Connecting to Flipper @ {args.serial} ...")
    _fz = FlipperZero(args.serial)
    print(f"  {_fz.identify()}")

    server = HTTPServer(("", args.port), IRHandler)
    print(f"Listening on port {args.port} ...")
    print("  POST /ir/send  POST /ir/raw  POST /ir/replay  GET /ir/receive")

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
        print("Shutdown.")


if __name__ == "__main__":
    main()
