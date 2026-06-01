#!/usr/bin/env -S python3 -u
"""
ACARS Receiver

Decodes ACARS (Aircraft Communications Addressing and Reporting System)
messages on VHF using an RTL-SDR dongle and acarsdec.  Monitors up to 8
frequencies simultaneously.

Common North American ACARS frequencies:
  131.550 MHz (primary), 131.525, 131.725, 130.025, 129.125,
  130.450, 130.825, 131.125

Each message carries a 2-character label, flight ID, aircraft tail number,
and free text.  Labels identify the message type: H1=position/ADS-C,
Q0=acknowledgement, _d=empty, S1=fuel/weight, etc.

Logs to SQLite and serves live JSON over HTTP.

Usage:
    python acars.py
    python acars.py --freqs 131.550 131.525 131.725 130.025
    python acars.py --gain 40 --port 8093
    python acars.py --dump-only              # print to stdout, no HTTP or DB
    python acars.py --filter H1,S1,S2        # only log these label types
"""

import argparse
import json
import os
import signal
import socket
import sqlite3
import subprocess
import sys
import threading
import time
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Optional

# ---------------------------------------------------------------------------
# ACARS label reference (subset of common labels)
# ---------------------------------------------------------------------------

LABEL_NAMES = {
    "H1": "Position/ADS-C", "H2": "ADS-C handoff",
    "S1": "Fuel/Weights", "S2": "Fuel/Weights",
    "Q0": "ACK", "QD": "ACK",
    "_d": "Empty",
    "AA": "ATC data", "AB": "ATC",
    "B1": "ATC uplink", "B2": "ATC uplink",
    "B6": "ATC downlink", "B7": "ATC downlink",
    "10": "Wx/ATIS", "12": "Wx",
    "20": "D-ATIS", "21": "D-ATIS",
    "44": "Dispatch",
    "5U": "ADS-B squitter",
    "A0": "SATCOM init",
    "F3": "Engine data",
    "G1": "Gate/ground",
    "M1": "Met/Wx",
    "SA": "Datalink init",
    "SQ": "ACARS logon",
    "08": "Telex",
    "30": "Position",
    "7A": "Cabin",
    "7B": "Crew",
}

# Common North American ACARS VHF frequencies (MHz)
DEFAULT_FREQS = ["131.550", "131.525", "131.725", "130.025", "129.125"]

DEFAULT_GAIN      = 40
DEFAULT_UDP_PORT  = 5555
DEFAULT_HTTP_PORT = 8093
DEFAULT_DB_PATH   = "acars.db"
MSG_TTL_S         = 3600    # keep last hour in live view

# ---------------------------------------------------------------------------
# SQLite schema
# ---------------------------------------------------------------------------

CREATE_SQL = """
CREATE TABLE IF NOT EXISTS messages (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp   REAL NOT NULL,
    freq_mhz    REAL,
    level_db    REAL,
    error       INTEGER,
    mode        TEXT,
    label       TEXT,
    block_id    TEXT,
    tail        TEXT,
    flight      TEXT,
    msgno       TEXT,
    text        TEXT,
    libacars    TEXT   -- JSON blob of libacars-decoded content if present
);

CREATE INDEX IF NOT EXISTS msg_time   ON messages(timestamp);
CREATE INDEX IF NOT EXISTS msg_flight ON messages(flight);
CREATE INDEX IF NOT EXISTS msg_tail   ON messages(tail);
CREATE INDEX IF NOT EXISTS msg_label  ON messages(label);
"""

_db_path: str = ""


def open_db(path: str) -> sqlite3.Connection:
    global _db_path
    _db_path = path
    conn = sqlite3.connect(path)
    conn.executescript(CREATE_SQL)
    conn.commit()
    return conn


# ---------------------------------------------------------------------------
# Live message buffer (last N messages, in-memory)
# ---------------------------------------------------------------------------

_messages: list[dict] = []
_messages_lock = threading.Lock()
MAX_LIVE_MSGS = 500


def _store_live(msg: dict) -> None:
    with _messages_lock:
        _messages.append(msg)
        if len(_messages) > MAX_LIVE_MSGS:
            del _messages[0]


# ---------------------------------------------------------------------------
# Message processing
# ---------------------------------------------------------------------------

def _label_name(label: Optional[str]) -> str:
    if not label:
        return "Unknown"
    return LABEL_NAMES.get(label, label)


def process_acars_json(raw: bytes, conn: Optional[sqlite3.Connection],
                       label_filter: Optional[set],
                       csv_fh=None) -> Optional[dict]:
    """Parse one JSON blob from acarsdec UDP output."""
    try:
        d = json.loads(raw)
    except json.JSONDecodeError:
        return None

    # acarsdec wraps messages in an outer key; unwrap if needed
    if "acars" in d:
        msg = d["acars"]
        outer = d
    else:
        msg = d
        outer = {}

    label  = msg.get("label") or ""
    tail   = (msg.get("tail") or "").strip()
    flight = (msg.get("flight") or "").strip()
    text   = (msg.get("text") or "").strip()
    freq   = float(msg.get("freq", 0))
    level  = msg.get("level")
    error  = int(msg.get("error", 0))
    mode   = msg.get("mode", "")
    block  = msg.get("block_id", "")
    msgno  = msg.get("msgno", "")
    ts     = float(msg.get("timestamp", time.time()))

    # libacars decoded content (e.g. position from H1 messages)
    libacars_raw = None
    if "libacars" in msg:
        libacars_raw = json.dumps(msg["libacars"])
    elif "libacars" in outer:
        libacars_raw = json.dumps(outer["libacars"])

    if label_filter and label not in label_filter:
        return None

    result = {
        "timestamp":  ts,
        "freq_mhz":   freq,
        "level_db":   level,
        "error":      error,
        "mode":       mode,
        "label":      label,
        "label_name": _label_name(label),
        "block_id":   block,
        "tail":       tail,
        "flight":     flight,
        "msgno":      msgno,
        "text":       text,
        "libacars":   json.loads(libacars_raw) if libacars_raw else None,
    }

    if conn:
        conn.execute(
            """INSERT INTO messages
               (timestamp,freq_mhz,level_db,error,mode,label,block_id,
                tail,flight,msgno,text,libacars)
               VALUES(?,?,?,?,?,?,?,?,?,?,?,?)""",
            (ts, freq, level, error, mode, label, block,
             tail, flight, msgno, text, libacars_raw)
        )
        conn.commit()

    if csv_fh:
        dt = datetime.fromtimestamp(ts, tz=timezone.utc).isoformat()
        csv_fh.write(f"{dt},{freq},{label},{tail},{flight},{text[:80]!r}\n")
        csv_fh.flush()

    return result


# ---------------------------------------------------------------------------
# HTTP API
# ---------------------------------------------------------------------------

class Handler(BaseHTTPRequestHandler):
    def log_message(self, *_):
        pass

    def do_GET(self):
        if self.path in ("/messages", "/messages/"):
            with _messages_lock:
                data = list(_messages)
            self._json(data)
        elif self.path.startswith("/flight/"):
            flight = self.path.split("/")[-1].upper()
            with _messages_lock:
                data = [m for m in _messages if m.get("flight") == flight]
            self._json(data)
        elif self.path.startswith("/tail/"):
            tail = self.path.split("/")[-1].upper()
            with _messages_lock:
                data = [m for m in _messages if m.get("tail") == tail]
            self._json(data)
        elif self.path == "/status":
            with _messages_lock:
                n = len(_messages)
            self._json({"message_count": n, "status": "ok"})
        else:
            self.send_error(404)

    def _json(self, obj):
        body = json.dumps(obj, default=str).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", len(body))
        self.end_headers()
        self.wfile.write(body)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

_running = True


def _sigint(_sig, _frame):
    global _running
    _running = False


signal.signal(signal.SIGINT, _sigint)
os.environ.setdefault("PYTHONUNBUFFERED", "1")


def main():
    ap = argparse.ArgumentParser(description="ACARS receiver via RTL-SDR + acarsdec")
    ap.add_argument("--freqs",     nargs="+", default=DEFAULT_FREQS, metavar="MHZ",
                    help="ACARS frequencies in MHz (default: 5 common NA freqs)")
    ap.add_argument("--gain",      type=float, default=DEFAULT_GAIN,
                    help="Tuner gain in dB (default: %(default)s)")
    ap.add_argument("--port",      type=int,   default=DEFAULT_HTTP_PORT,
                    help="HTTP server port (default: %(default)s)")
    ap.add_argument("--udp-port",  type=int,   default=DEFAULT_UDP_PORT,
                    help="UDP port for acarsdec JSON (default: %(default)s)")
    ap.add_argument("--db",        default=DEFAULT_DB_PATH,
                    help="SQLite database path (default: %(default)s)")
    ap.add_argument("--dump-only", action="store_true",
                    help="Print decoded messages to stdout, no HTTP or DB")
    ap.add_argument("--csv",       metavar="FILE",
                    help="Append decoded messages to CSV file")
    ap.add_argument("--filter",    metavar="LABELS",
                    help="Comma-separated label filter, e.g. H1,S1,S2")
    ap.add_argument("--ppm",       type=int, default=0,
                    help="RTL-SDR frequency correction in ppm (default: 0)")
    ap.add_argument("--no-empty",  action="store_true",
                    help="Skip empty messages (label _d, Q0, etc.)")
    args = ap.parse_args()

    label_filter: Optional[set] = None
    if args.filter:
        label_filter = set(args.filter.split(","))
    if args.no_empty:
        skip = {"_d", "Q0", "QD"}
        label_filter = (label_filter - skip) if label_filter else None

    conn   = open_db(args.db) if not args.dump_only else None
    csv_fh = open(args.csv, "a") if args.csv else None

    # acarsdec subprocess — monitors all freqs simultaneously
    acd_cmd = [
        "acarsdec",
        "--rtlsdr", "0",
        "-g", str(args.gain),
        "-p", str(args.ppm),
        "--output", f"json:udp:host=127.0.0.1,port={args.udp_port}",
    ] + args.freqs

    # Bind the UDP socket BEFORE starting acarsdec so no early packets are dropped
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind(("127.0.0.1", args.udp_port))
    sock.settimeout(1.0)

    try:
        acd_proc = subprocess.Popen(acd_cmd,
                                    stdout=subprocess.DEVNULL,
                                    stderr=subprocess.DEVNULL)
    except FileNotFoundError:
        print("acarsdec not found. Install: yay -S acarsdec-git", file=sys.stderr)
        sys.exit(1)

    time.sleep(1.5)
    if acd_proc.poll() is not None:
        print(f"acarsdec exited immediately (code {acd_proc.returncode}).",
              file=sys.stderr)
        sys.exit(1)

    if not args.dump_only:
        srv = HTTPServer(("", args.port), Handler)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        print(f"HTTP: http://localhost:{args.port}/messages")

    freq_str = "  ".join(f"{f} MHz" for f in args.freqs)
    print(f"ACARS listening on: {freq_str}")
    print(f"Gain: {args.gain} dB  Ctrl-C to stop.\n")

    total = 0

    try:
        while _running:
            if acd_proc.poll() is not None:
                print(f"\nacarsdec exited (code {acd_proc.returncode}).",
                      file=sys.stderr)
                break

            try:
                raw, _ = sock.recvfrom(65536)
            except socket.timeout:
                continue

            result = process_acars_json(raw, conn, label_filter, csv_fh)
            if result is None:
                continue

            total += 1
            _store_live(result)

            if args.dump_only or True:  # always show console output
                ts     = datetime.fromtimestamp(result["timestamp"],
                                                tz=timezone.utc).strftime("%H:%M:%S")
                freq   = f"{result['freq_mhz']:.3f}"
                label  = result["label"] or "--"
                lname  = result["label_name"][:14]
                tail   = (result["tail"] or "-------").ljust(7)
                flight = (result["flight"] or "").ljust(7)
                text   = (result["text"] or "")[:60]
                lvl    = f"{result['level_db']:+.0f}" if result["level_db"] else "  "
                print(f"[{ts}] {freq}  {lvl:>4}dB  {label:2s} {lname:14s}  "
                      f"{tail}  {flight}  {text}")

    except OSError as exc:
        if _running:
            print(f"\nUDP error: {exc}", file=sys.stderr)
    finally:
        sock.close()
        acd_proc.terminate()
        try:
            acd_proc.wait(timeout=3)
        except subprocess.TimeoutExpired:
            acd_proc.kill()
        if csv_fh:
            csv_fh.close()
        if conn:
            conn.close()
        print(f"\nDone. {total} messages decoded.")


if __name__ == "__main__":
    main()
