#!/usr/bin/env -S python3 -u
"""
AIS Receiver

Decodes AIS (Automatic Identification System) vessel traffic on 161.975 MHz
and 162.025 MHz using an RTL-SDR dongle and rtl_ais.  Both channels are
received simultaneously.

Tracks vessel positions, static data (name, callsign, type, dimensions), and
voyage data (destination, draught).  Logs to SQLite and serves live JSON
over HTTP.

Requires rtl_ais installed (built from https://github.com/dgiardini/rtl-ais).

Usage:
    python ais.py
    python ais.py --gain 40 --port 8092
    python ais.py --dump-only              # NMEA sentences to stdout, no HTTP
    python ais.py --csv vessels.csv        # append position fixes to CSV
"""

import argparse
import json
import signal
import socket
import sqlite3
import sys
import subprocess
import threading
import time
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Optional

from pyais.stream import UDPReceiver
from pyais.messages import (
    MessageType1, MessageType2, MessageType3,  # Class A position
    MessageType5,                              # Class A static/voyage
    MessageType18, MessageType19,              # Class B position
    MessageType21,                             # Aid to navigation
    MessageType24,                             # Class B static
    MessageType24PartA, MessageType24PartB,
)

# ---------------------------------------------------------------------------
# Defaults
# ---------------------------------------------------------------------------

AIS_FREQ_LEFT    = "161.975M"
AIS_FREQ_RIGHT   = "162.025M"
DEFAULT_GAIN     = 40
DEFAULT_UDP_PORT = 10110
DEFAULT_HTTP_PORT = 8092
DEFAULT_DB_PATH  = "ais.db"
VESSEL_TTL_S     = 1800    # remove from live view after 30 min no update

# ---------------------------------------------------------------------------
# SQLite schema
# ---------------------------------------------------------------------------

CREATE_SQL = """
CREATE TABLE IF NOT EXISTS vessels (
    mmsi         INTEGER PRIMARY KEY,
    name         TEXT,
    callsign     TEXT,
    ship_type    INTEGER,
    imo          INTEGER,
    to_bow       INTEGER,
    to_stern     INTEGER,
    to_port      INTEGER,
    to_starboard INTEGER,
    first_seen   REAL,
    last_seen    REAL
);

CREATE TABLE IF NOT EXISTS positions (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp   REAL NOT NULL,
    mmsi        INTEGER NOT NULL,
    lat         REAL,
    lon         REAL,
    speed_kt    REAL,
    heading     INTEGER,
    course      REAL,
    nav_status  INTEGER,
    source      TEXT   -- 'A' class A, 'B' class B
);

CREATE INDEX IF NOT EXISTS pos_time ON positions(timestamp);
CREATE INDEX IF NOT EXISTS pos_mmsi ON positions(mmsi);
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
# Live vessel state (in-memory, main thread only)
# ---------------------------------------------------------------------------

class Vessel:
    __slots__ = ('mmsi', 'name', 'callsign', 'ship_type', 'imo',
                 'lat', 'lon', 'speed_kt', 'heading', 'course',
                 'nav_status', 'source',
                 'to_bow', 'to_stern', 'to_port', 'to_starboard',
                 'last_seen', 'msg_count')

    def __init__(self, mmsi: int):
        self.mmsi        = mmsi
        self.name        = None
        self.callsign    = None
        self.ship_type   = None
        self.imo         = None
        self.lat         = None
        self.lon         = None
        self.speed_kt    = None
        self.heading     = None
        self.course      = None
        self.nav_status  = None
        self.source      = None
        self.to_bow      = None
        self.to_stern    = None
        self.to_port     = None
        self.to_starboard= None
        self.last_seen   = time.time()
        self.msg_count   = 0

    def length_m(self) -> Optional[int]:
        if self.to_bow and self.to_stern:
            return self.to_bow + self.to_stern
        return None

    def to_dict(self) -> dict:
        return {
            "mmsi":        self.mmsi,
            "name":        self.name,
            "callsign":    self.callsign,
            "ship_type":   self.ship_type,
            "imo":         self.imo,
            "lat":         self.lat,
            "lon":         self.lon,
            "speed_kt":    self.speed_kt,
            "heading":     self.heading,
            "course":      self.course,
            "nav_status":  self.nav_status,
            "source":      self.source,
            "length_m":    self.length_m(),
            "last_seen":   self.last_seen,
            "msg_count":   self.msg_count,
        }


_vessels: dict[int, Vessel] = {}
_vessels_lock = threading.Lock()


def prune_stale() -> None:
    cutoff = time.time() - VESSEL_TTL_S
    with _vessels_lock:
        stale = [mmsi for mmsi, v in _vessels.items() if v.last_seen < cutoff]
        for mmsi in stale:
            del _vessels[mmsi]


# ---------------------------------------------------------------------------
# AIS message processing
# ---------------------------------------------------------------------------

SHIP_TYPES = {
    0: "Unknown", 20: "Wing in ground", 30: "Fishing",
    31: "Towing", 32: "Towing (large)", 33: "Dredging",
    34: "Diving", 35: "Military", 36: "Sailing", 37: "Pleasure",
    40: "High speed", 50: "Pilot", 51: "SAR", 52: "Tug",
    53: "Port tender", 54: "Anti-pollution", 55: "Law enforcement",
    60: "Passenger", 70: "Cargo", 80: "Tanker", 90: "Other",
}

NAV_STATUS = {
    0: "Underway (engine)", 1: "Anchored", 2: "Not under command",
    3: "Restricted manoeuvring", 4: "Constrained by draught",
    5: "Moored", 6: "Aground", 7: "Fishing", 8: "Sailing",
    15: "Not defined",
}


def _ship_type_name(t: Optional[int]) -> str:
    if t is None:
        return "Unknown"
    return SHIP_TYPES.get(t // 10 * 10, SHIP_TYPES.get(t, f"Type {t}"))


def process_message(msg, conn: sqlite3.Connection, csv_fh=None,
                    dump_only: bool = False) -> Optional[dict]:
    """Update vessel state from a decoded pyais message.  Returns a log dict."""
    try:
        mmsi = int(msg.mmsi)
    except (AttributeError, TypeError, ValueError):
        return None

    if not (100_000_000 <= mmsi <= 999_999_999) and not (10_000_000 <= mmsi <= 99_999_999):
        return None  # ignore clearly invalid MMSIs

    now = time.time()

    with _vessels_lock:
        if mmsi not in _vessels:
            _vessels[mmsi] = Vessel(mmsi)
        v = _vessels[mmsi]
        v.last_seen = now
        v.msg_count += 1

    result = {"mmsi": mmsi, "type": msg.msg_type}

    # Position messages (1, 2, 3 = Class A; 18, 19 = Class B)
    if isinstance(msg, (MessageType1, MessageType2, MessageType3,
                        MessageType18, MessageType19)):
        lat = float(msg.lat) if msg.lat is not None else None
        lon = float(msg.lon) if msg.lon is not None else None
        spd = float(msg.speed) if hasattr(msg, 'speed') and msg.speed is not None else None
        hdg = int(msg.heading) if hasattr(msg, 'heading') and msg.heading not in (None, 511) else None
        cse = float(msg.course) if hasattr(msg, 'course') and msg.course is not None else None
        nav = int(msg.status) if hasattr(msg, 'status') and msg.status is not None else None
        src = 'A' if isinstance(msg, (MessageType1, MessageType2, MessageType3)) else 'B'

        with _vessels_lock:
            if lat is not None: v.lat       = lat
            if lon is not None: v.lon       = lon
            if spd is not None: v.speed_kt  = spd
            if hdg is not None: v.heading   = hdg
            if cse is not None: v.course    = cse
            if nav is not None: v.nav_status= nav
            v.source = src

        if not dump_only and lat is not None and lon is not None:
            conn.execute(
                "INSERT INTO positions(timestamp,mmsi,lat,lon,speed_kt,heading,course,nav_status,source)"
                " VALUES(?,?,?,?,?,?,?,?,?)",
                (now, mmsi, lat, lon, spd, hdg, cse, nav, src)
            )
            conn.commit()
            if csv_fh:
                ts = datetime.fromtimestamp(now, tz=timezone.utc).isoformat()
                csv_fh.write(f"{ts},{mmsi},{v.name or ''},{lat:.6f},{lon:.6f},"
                             f"{spd or ''},{hdg or ''},{cse or ''}\n")
                csv_fh.flush()

        result.update({"lat": lat, "lon": lon, "speed_kt": spd,
                       "heading": hdg, "nav_status": nav, "source": src})

    # Class A static/voyage (type 5)
    elif isinstance(msg, MessageType5):
        name = msg.shipname.strip() if msg.shipname else None
        call = msg.callsign.strip() if msg.callsign else None
        stype= int(msg.ship_type) if msg.ship_type is not None else None
        imo  = int(msg.imo) if msg.imo else None

        with _vessels_lock:
            if name:  v.name      = name
            if call:  v.callsign  = call
            if stype: v.ship_type = stype
            if imo:   v.imo       = imo
            if msg.to_bow:      v.to_bow       = int(msg.to_bow)
            if msg.to_stern:    v.to_stern     = int(msg.to_stern)
            if msg.to_port:     v.to_port      = int(msg.to_port)
            if msg.to_starboard:v.to_starboard = int(msg.to_starboard)

        if not dump_only:
            conn.execute(
                """INSERT INTO vessels(mmsi,name,callsign,ship_type,imo,
                   to_bow,to_stern,to_port,to_starboard,first_seen,last_seen)
                   VALUES(?,?,?,?,?,?,?,?,?,?,?)
                   ON CONFLICT(mmsi) DO UPDATE SET
                     name=COALESCE(excluded.name, name),
                     callsign=COALESCE(excluded.callsign, callsign),
                     ship_type=COALESCE(excluded.ship_type, ship_type),
                     imo=COALESCE(excluded.imo, imo),
                     to_bow=COALESCE(excluded.to_bow, to_bow),
                     to_stern=COALESCE(excluded.to_stern, to_stern),
                     to_port=COALESCE(excluded.to_port, to_port),
                     to_starboard=COALESCE(excluded.to_starboard, to_starboard),
                     last_seen=excluded.last_seen""",
                (mmsi, name, call, stype, imo,
                 int(msg.to_bow or 0), int(msg.to_stern or 0),
                 int(msg.to_port or 0), int(msg.to_starboard or 0),
                 now, now)
            )
            conn.commit()

        result.update({"name": name, "callsign": call, "ship_type": stype})

    # Class B static part A (name)
    elif isinstance(msg, MessageType24PartA):
        name = msg.shipname.strip() if msg.shipname else None
        with _vessels_lock:
            if name: v.name = name
        result["name"] = name

    # Class B static part B (callsign, type)
    elif isinstance(msg, MessageType24PartB):
        call  = msg.callsign.strip() if hasattr(msg, 'callsign') and msg.callsign else None
        stype = int(msg.ship_type) if hasattr(msg, 'ship_type') and msg.ship_type is not None else None
        with _vessels_lock:
            if call:  v.callsign  = call
            if stype: v.ship_type = stype
        result.update({"callsign": call, "ship_type": stype})

    # Aid to navigation (type 21)
    elif isinstance(msg, MessageType21):
        name = msg.name.strip() if msg.name else None
        with _vessels_lock:
            if name: v.name = name
        result.update({"name": name, "aid_type": getattr(msg, 'aid_type', None)})

    return result


# ---------------------------------------------------------------------------
# HTTP API
# ---------------------------------------------------------------------------

class Handler(BaseHTTPRequestHandler):
    def log_message(self, *_):
        pass

    def do_GET(self):
        if self.path in ("/vessels", "/vessels/"):
            with _vessels_lock:
                data = [v.to_dict() for v in _vessels.values()]
            self._json(sorted(data, key=lambda x: x["last_seen"], reverse=True))
        elif self.path.startswith("/vessel/"):
            mmsi_str = self.path.split("/")[-1]
            try:
                mmsi = int(mmsi_str)
                with _vessels_lock:
                    v = _vessels.get(mmsi)
                if v:
                    self._json(v.to_dict())
                else:
                    self.send_error(404)
            except ValueError:
                self.send_error(400)
        elif self.path == "/status":
            with _vessels_lock:
                count = len(_vessels)
            self._json({"vessel_count": count, "status": "ok"})
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


def main():
    ap = argparse.ArgumentParser(description="AIS receiver via RTL-SDR + rtl_ais")
    ap.add_argument("--gain",       type=float, default=DEFAULT_GAIN,
                    help="Tuner gain in dB (default: %(default)s)")
    ap.add_argument("--port",       type=int,   default=DEFAULT_HTTP_PORT,
                    help="HTTP server port (default: %(default)s)")
    ap.add_argument("--udp-port",   type=int,   default=DEFAULT_UDP_PORT,
                    help="UDP port for rtl_ais NMEA output (default: %(default)s)")
    ap.add_argument("--db",         default=DEFAULT_DB_PATH,
                    help="SQLite database path (default: %(default)s)")
    ap.add_argument("--dump-only",  action="store_true",
                    help="Print NMEA sentences to stdout, no HTTP or DB")
    ap.add_argument("--csv",        metavar="FILE",
                    help="Append position fixes to CSV file")
    ap.add_argument("--ppm",        type=int,   default=0,
                    help="RTL-SDR frequency correction in ppm (default: 0)")
    args = ap.parse_args()

    conn   = open_db(args.db) if not args.dump_only else None
    csv_fh = open(args.csv, "a") if args.csv else None

    # Launch rtl_ais as a subprocess; it sends NMEA via UDP to udp_port
    rtl_cmd = [
        "rtl_ais",
        "-l", AIS_FREQ_LEFT,
        "-r", AIS_FREQ_RIGHT,
        "-g", str(args.gain),
        "-p", str(args.ppm),
        "-h", "127.0.0.1",
        "-P", str(args.udp_port),
        "-n",          # also log NMEA to stderr so we can see it's working
    ]
    # Bind the UDP receiver BEFORE starting rtl_ais so no early packets are dropped
    udp_rx = UDPReceiver("127.0.0.1", args.udp_port)

    try:
        rtl_proc = subprocess.Popen(rtl_cmd, stderr=subprocess.DEVNULL)
    except FileNotFoundError:
        print("rtl_ais not found. Build from https://github.com/dgiardini/rtl-ais",
              file=sys.stderr)
        sys.exit(1)

    time.sleep(1.0)  # give rtl_ais a moment to start up
    if rtl_proc.poll() is not None:
        print(f"rtl_ais exited immediately (code {rtl_proc.returncode}).",
              file=sys.stderr)
        sys.exit(1)

    if not args.dump_only:
        srv = HTTPServer(("", args.port), Handler)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        print(f"HTTP: http://localhost:{args.port}/vessels")

    print(f"Listening on {AIS_FREQ_LEFT} / {AIS_FREQ_RIGHT}"
          f"  gain={args.gain} dB  Ctrl-C to stop.")

    last_prune = time.time()
    total_msgs = 0
    total_vessels = 0

    try:
        for msg in udp_rx:
            if not _running:
                break

            try:
                decoded = msg.decode()
            except Exception:
                continue

            if args.dump_only:
                # Print the raw NMEA and a brief decode summary
                mmsi = getattr(decoded, 'mmsi', None)
                name = getattr(decoded, 'shipname', None) or getattr(decoded, 'name', None)
                lat  = getattr(decoded, 'lat', None)
                lon  = getattr(decoded, 'lon', None)
                parts = [f"T{decoded.msg_type}", f"MMSI:{mmsi}"]
                if name:  parts.append(name.strip())
                if lat is not None: parts.append(f"{lat:.4f},{lon:.4f}")
                print("  ".join(parts))
                total_msgs += 1
                continue

            result = process_message(decoded, conn, csv_fh)
            if result is None:
                continue

            total_msgs += 1

            with _vessels_lock:
                n_vessels = len(_vessels)

            # Console summary line
            mmsi = result["mmsi"]
            with _vessels_lock:
                v = _vessels.get(mmsi)
            if v:
                name_str = (v.name or "").ljust(20)[:20]
                pos_str  = (f"{v.lat:+.4f},{v.lon:+.4f}" if v.lat else "no pos").ljust(18)
                spd_str  = f"{v.speed_kt:.1f}kt" if v.speed_kt is not None else "  ---"
                typ_str  = _ship_type_name(v.ship_type)[:12]
                ts = datetime.now(tz=timezone.utc).strftime("%H:%M:%S")
                print(f"[{ts}] {mmsi}  {name_str}  {pos_str}  {spd_str}  {typ_str}")

            if time.time() - last_prune > 60:
                prune_stale()
                last_prune = time.time()
                with _vessels_lock:
                    n_vessels = len(_vessels)
                print(f"\r  {n_vessels} vessels  {total_msgs} messages", end="", flush=True)

    except OSError as exc:
        if _running:
            print(f"\nUDP receive error: {exc}", file=sys.stderr)
    finally:
        rtl_proc.terminate()
        try:
            rtl_proc.wait(timeout=3)
        except subprocess.TimeoutExpired:
            rtl_proc.kill()
        if csv_fh:
            csv_fh.close()
        if conn:
            conn.close()
        print(f"\nDone. {total_msgs} messages / {len(_vessels)} vessels tracked.")


if __name__ == "__main__":
    main()
