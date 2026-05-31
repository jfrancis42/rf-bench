#!/usr/bin/env python3
"""
ADS-B Local Receiver

Decodes Mode S / ADS-B transmissions at 1090 MHz from aircraft overhead using
an RTL-SDR dongle.  Cross-references each ICAO hex address with the govt-data
aircraft API to enrich raw position data with N-number, aircraft type, and
registered owner.  Logs to SQLite and serves live JSON over HTTP.

Requires an RTL-SDR dongle and a 1090 MHz antenna (or wideband antenna).
A 1090 MHz bandpass filter before the LNA significantly improves decode rate.

Usage:
    python adsb.py
    python adsb.py --port 8080 --gain 40 --no-enrich
    python adsb.py --dump-only               # raw Mode S hex to stdout, no HTTP
    python adsb.py --csv aircraft.csv        # append position fixes to CSV
"""

import argparse
import json
import math
import os
import signal
import sqlite3
import sys
import threading
import time
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Optional
from urllib.request import urlopen, Request
from urllib.error import URLError

import numpy as np
import pyModeS as pms
from pyModeS.position import airborne_position_with_ref

from rf_bench.rtlsdr import RTLSDR, RTLSDRError

# ---------------------------------------------------------------------------
# Defaults
# ---------------------------------------------------------------------------

DEFAULT_FREQ_HZ      = 1_090_000_000
DEFAULT_SAMPLE_RATE  = 2_000_000   # 2 MS/s — standard for ADS-B decoding
DEFAULT_GAIN         = 40          # dB; typical for ADS-B with an LNA
DEFAULT_HTTP_PORT    = 8090
DEFAULT_DB_PATH      = "adsb.db"
GOVTDATA_HOST        = "10.1.0.20"
GOVTDATA_PORT        = 8091
ENRICH_CACHE_TTL     = 3600        # seconds before re-querying govt-data

# Minimum RSSI delta from noise floor to report (rough demodulation threshold)
SIGNAL_THRESHOLD_DB  = 10.0

_running = True

def _sigint(_sig, _frame):
    global _running
    _running = False

signal.signal(signal.SIGINT, _sigint)


# ---------------------------------------------------------------------------
# SQLite schema
# ---------------------------------------------------------------------------

CREATE_SQL = """
CREATE TABLE IF NOT EXISTS aircraft (
    icao_hex    TEXT PRIMARY KEY,
    callsign    TEXT,
    n_number    TEXT,
    type_code   TEXT,
    owner       TEXT,
    enriched_at REAL
);

CREATE TABLE IF NOT EXISTS positions (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp   REAL NOT NULL,
    icao_hex    TEXT NOT NULL,
    lat         REAL,
    lon         REAL,
    alt_ft      INTEGER,
    speed_kt    REAL,
    heading     REAL,
    vert_rate   INTEGER,
    rssi_db     REAL
);

CREATE INDEX IF NOT EXISTS pos_time ON positions(timestamp);
CREATE INDEX IF NOT EXISTS pos_icao ON positions(icao_hex);
"""


def open_db(path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(path, check_same_thread=False)
    conn.executescript(CREATE_SQL)
    conn.commit()
    return conn


# ---------------------------------------------------------------------------
# govt-data enrichment
# ---------------------------------------------------------------------------

_enrich_cache: dict = {}
_enrich_lock  = threading.Lock()
_db_lock      = threading.Lock()  # serialize all SQLite access across threads


def enrich_icao(icao_hex: str, conn: sqlite3.Connection) -> dict:
    """Return registration info for an ICAO hex address from govt-data or cache."""
    now = time.time()
    with _enrich_lock:
        if icao_hex in _enrich_cache:
            cached_at, data = _enrich_cache[icao_hex]
            if now - cached_at < ENRICH_CACHE_TTL:
                return data

    # Check SQLite first
    with _db_lock:
        row = conn.execute(
            "SELECT n_number, type_code, owner, enriched_at FROM aircraft WHERE icao_hex=?",
            (icao_hex,)
        ).fetchone()
    if row and row[3] and (now - row[3] < ENRICH_CACHE_TTL):
        data = {"n_number": row[0], "type_code": row[1], "owner": row[2]}
        with _enrich_lock:
            _enrich_cache[icao_hex] = (now, data)
        return data

    # Query govt-data
    try:
        url = f"http://{GOVTDATA_HOST}:{GOVTDATA_PORT}/aircraft/hex/{icao_hex}"
        req = Request(url, headers={"Accept": "application/json"})
        with urlopen(req, timeout=2.0) as resp:
            payload = json.loads(resp.read())
        data = {
            "n_number":  payload.get("n_number"),
            "type_code": payload.get("type_designator") or payload.get("aircraft_type"),
            "owner":     payload.get("registrant_name"),
        }
    except (URLError, json.JSONDecodeError, KeyError, Exception):
        data = {"n_number": None, "type_code": None, "owner": None}

    with _enrich_lock:
        _enrich_cache[icao_hex] = (now, data)

    with _db_lock:
        conn.execute(
            """INSERT INTO aircraft(icao_hex, n_number, type_code, owner, enriched_at)
               VALUES(?,?,?,?,?)
               ON CONFLICT(icao_hex) DO UPDATE SET
                 n_number=excluded.n_number,
                 type_code=excluded.type_code,
                 owner=excluded.owner,
                 enriched_at=excluded.enriched_at""",
            (icao_hex, data["n_number"], data["type_code"], data["owner"], now)
        )
        conn.commit()
    return data


# ---------------------------------------------------------------------------
# Mode S demodulation from IQ
# ---------------------------------------------------------------------------

def demodulate_modes(iq: np.ndarray) -> list[str]:
    """
    Demodulate Mode S messages from raw IQ samples.

    Uses AM envelope detection with purely relative preamble matching
    (same approach as rtl_adsb): high samples at indices 0,2,7,9 must each
    exceed every adjacent low sample.  No global normalization needed.

    At 2 MS/s (0.5 µs/sample), Mode S preamble pulses land at:
      samples 0, 2 (first pair) and 7, 9 (second pair, offset 3.5/4.5 µs).

    Returns list of hex strings for all candidates (CRC filtering happens
    in process_message via pyModeS).
    """
    mag = np.abs(iq).astype(np.float32)
    if len(mag) < 16 + 112 * 2:
        return []

    messages = []
    n = len(mag)
    i = 0
    end = n - 16 - 112 * 2

    while i < end:
        p0  = mag[i]
        p1  = mag[i+1]
        p2  = mag[i+2]
        p3  = mag[i+3]
        p4  = mag[i+4]
        p5  = mag[i+5]
        p6  = mag[i+6]
        p7  = mag[i+7]
        p8  = mag[i+8]
        p9  = mag[i+9]
        p10 = mag[i+10]
        p11 = mag[i+11]
        p12 = mag[i+12]
        p13 = mag[i+13]
        p14 = mag[i+14]
        p15 = mag[i+15]

        # Each "high" sample must exceed every "low" sample it borders.
        # Mirrors the rtl_adsb preamble() sequential comparison logic.
        if (p0  > p1  and
            p2  > p1  and p2 > p3 and p2 > p4 and p2 > p5 and p2 > p6 and
            p7  > p6  and p7 > p8 and
            p9  > p8  and p9 > p10 and p9 > p11 and p9 > p12 and
            p9  > p13 and p9 > p14 and p9 > p15):

            bits = []
            start = i + 16
            for b in range(112):
                s0 = start + b * 2
                s1 = s0 + 1
                bits.append('1' if mag[s0] > mag[s1] else '0')

            hex_str = hex(int(''.join(bits), 2))[2:].upper().zfill(28)
            messages.append(hex_str)
            i += 16
        else:
            i += 1

    return messages


# ---------------------------------------------------------------------------
# State tracker
# ---------------------------------------------------------------------------

class Aircraft:
    __slots__ = ('icao', 'callsign', 'lat', 'lon', 'alt_ft',
                 'speed_kt', 'heading', 'vert_rate',
                 'last_seen', 'msg_count', 'rssi_db',
                 'n_number', 'type_code', 'owner')

    def __init__(self, icao: str):
        self.icao       = icao
        self.callsign   = None
        self.lat        = None
        self.lon        = None
        self.alt_ft     = None
        self.speed_kt   = None
        self.heading    = None
        self.vert_rate  = None
        self.last_seen  = time.time()
        self.msg_count  = 0
        self.rssi_db    = None
        self.n_number   = None
        self.type_code  = None
        self.owner      = None

    def to_dict(self) -> dict:
        return {
            "icao":       self.icao,
            "callsign":   self.callsign,
            "n_number":   self.n_number,
            "type_code":  self.type_code,
            "owner":      self.owner,
            "lat":        self.lat,
            "lon":        self.lon,
            "alt_ft":     self.alt_ft,
            "speed_kt":   self.speed_kt,
            "heading":    self.heading,
            "vert_rate":  self.vert_rate,
            "last_seen":  self.last_seen,
            "msg_count":  self.msg_count,
            "rssi_db":    self.rssi_db,
        }


_aircraft: dict[str, Aircraft] = {}
_aircraft_lock = threading.Lock()
STALE_TIMEOUT = 60.0   # remove aircraft not seen for 60 s


def process_message(hex_msg: str, conn: sqlite3.Connection,
                    enrich: bool, rssi_db: float, csv_fh=None) -> None:
    """Parse a Mode S hex message and update aircraft state (pyModeS v3 API)."""
    if len(hex_msg) < 14:
        return

    try:
        d = pms.decode(hex_msg)
    except Exception:
        return

    if not d.get("crc_valid"):
        return

    df   = d.get("df")
    icao = d.get("icao")

    # Only process DF17 (ADS-B) and DF18 (TIS-B) for position/identity
    if df not in (17, 18, 20, 21):
        return
    if not icao:
        return
    icao = icao.upper()

    with _aircraft_lock:
        if icao not in _aircraft:
            _aircraft[icao] = Aircraft(icao)
        ac = _aircraft[icao]
        ac.last_seen = time.time()
        ac.msg_count += 1
        ac.rssi_db   = rssi_db

    # Decode ADS-B (DF17/18)
    if df in (17, 18):
        tc = d.get("typecode")
        if tc is None:
            return

        try:
            if 1 <= tc <= 4:
                cs = (d.get("callsign") or "").strip()
                if cs:
                    ac.callsign = cs
            elif 9 <= tc <= 18 or 20 <= tc <= 22:
                alt = d.get("altitude")
                if alt is not None:
                    ac.alt_ft = int(alt)
                cpr_lat = d.get("cpr_lat")
                cpr_lon = d.get("cpr_lon")
                cpr_fmt = d.get("cpr_format")
                if cpr_lat is not None and cpr_lon is not None and cpr_fmt is not None:
                    try:
                        lat, lon = airborne_position_with_ref(
                            cpr_fmt, cpr_lat, cpr_lon, 39.7, -104.9
                        )
                        ac.lat, ac.lon = lat, lon
                        _log_position(conn, ac, csv_fh)
                    except Exception:
                        pass
            elif tc == 19:
                spd = d.get("groundspeed") or d.get("airspeed")
                hdg = d.get("track") or d.get("heading")
                vr  = d.get("vertical_rate")
                if spd is not None: ac.speed_kt  = round(spd)
                if hdg is not None: ac.heading   = round(hdg)
                if vr  is not None: ac.vert_rate = int(vr)
        except Exception:
            pass

    # Enrich from govt-data (background, throttled)
    if enrich and ac.n_number is None and ac.msg_count in (1, 5, 20):
        def _do_enrich(i=icao, a=ac):
            info = enrich_icao(i, conn)
            a.n_number  = info.get("n_number")
            a.type_code = info.get("type_code")
            a.owner     = info.get("owner")
        threading.Thread(target=_do_enrich, daemon=True).start()


def _log_position(conn: sqlite3.Connection, ac: Aircraft, csv_fh=None) -> None:
    now = time.time()
    with _db_lock:
        conn.execute(
            "INSERT INTO positions(timestamp,icao_hex,lat,lon,alt_ft,speed_kt,heading,vert_rate,rssi_db)"
            " VALUES(?,?,?,?,?,?,?,?,?)",
            (now, ac.icao, ac.lat, ac.lon, ac.alt_ft, ac.speed_kt, ac.heading, ac.vert_rate, ac.rssi_db)
        )
        conn.commit()
    if csv_fh:
        ts = datetime.fromtimestamp(now, tz=timezone.utc).isoformat()
        csv_fh.write(f"{ts},{ac.icao},{ac.callsign or ''},{ac.lat:.5f},{ac.lon:.5f},"
                     f"{ac.alt_ft or ''},{ac.speed_kt or ''},{ac.heading or ''}\n")
        csv_fh.flush()


def prune_stale() -> None:
    now = time.time()
    with _aircraft_lock:
        stale = [k for k, v in _aircraft.items() if now - v.last_seen > STALE_TIMEOUT]
        for k in stale:
            del _aircraft[k]


# ---------------------------------------------------------------------------
# HTTP server
# ---------------------------------------------------------------------------

class Handler(BaseHTTPRequestHandler):
    def log_message(self, *_):
        pass

    def do_GET(self):
        if self.path in ("/aircraft", "/aircraft/"):
            with _aircraft_lock:
                data = [v.to_dict() for v in _aircraft.values()]
            data.sort(key=lambda x: x["last_seen"], reverse=True)
            self._json(data)
        elif self.path.startswith("/aircraft/") and len(self.path) > 10:
            icao = self.path.split("/")[-1].upper()
            with _aircraft_lock:
                ac = _aircraft.get(icao)
            if ac:
                self._json(ac.to_dict())
            else:
                self.send_error(404)
        elif self.path in ("/", "/status"):
            with _aircraft_lock:
                count = len(_aircraft)
            self._json({"aircraft_count": count, "status": "ok"})
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

def main():
    ap = argparse.ArgumentParser(description="ADS-B local receiver via RTL-SDR")
    ap.add_argument("--gain",       type=float, default=DEFAULT_GAIN,
                    help="Receiver gain in dB (default: %(default)s)")
    ap.add_argument("--port",       type=int,   default=DEFAULT_HTTP_PORT,
                    help="HTTP server port (default: %(default)s)")
    ap.add_argument("--db",         default=DEFAULT_DB_PATH,
                    help="SQLite database path (default: %(default)s)")
    ap.add_argument("--no-enrich",  action="store_true",
                    help="Disable govt-data callsign enrichment")
    ap.add_argument("--dump-only",  action="store_true",
                    help="Print raw hex messages to stdout, no HTTP server")
    ap.add_argument("--csv",        metavar="FILE",
                    help="Append position fixes to CSV file")
    ap.add_argument("--serial",     help="RTL-SDR serial number (default: first device)")
    ap.add_argument("--block-size", type=int, default=131_072,
                    help="IQ block size (default: %(default)s)")
    args = ap.parse_args()

    conn = open_db(args.db)
    csv_fh = open(args.csv, "a") if args.csv else None

    if not args.dump_only:
        srv = HTTPServer(("", args.port), Handler)
        t = threading.Thread(target=srv.serve_forever, daemon=True)
        t.start()
        print(f"HTTP: http://localhost:{args.port}/aircraft")

    total_msgs = 0
    try:
        with RTLSDR(serial=args.serial) as sdr:
            sdr.set_center_freq(DEFAULT_FREQ_HZ)
            sdr.set_sample_rate(DEFAULT_SAMPLE_RATE)
            sdr.set_gain(args.gain)
            print(f"Tuned to {DEFAULT_FREQ_HZ/1e6:.1f} MHz  "
                  f"gain={sdr.identify()['gain']} dB  "
                  f"ppm={sdr.identify()['ppm_correction']}")
            print("Listening... Ctrl-C to stop.")

            last_prune = time.time()

            for block in sdr.stream_iq(block_size=args.block_size):
                if not _running:
                    break

                # Rough signal level for RSSI annotation
                rssi_db = float(20 * np.log10(np.mean(np.abs(block)) + 1e-10))

                messages = demodulate_modes(block)
                for hex_msg in messages:
                    total_msgs += 1
                    if args.dump_only:
                        print(hex_msg)
                    else:
                        process_message(hex_msg, conn,
                                        enrich=not args.no_enrich,
                                        rssi_db=rssi_db,
                                        csv_fh=csv_fh)

                if time.time() - last_prune > 10.0:
                    prune_stale()
                    last_prune = time.time()
                    if not args.dump_only:
                        with _aircraft_lock:
                            count = len(_aircraft)
                        print(f"\r{count} aircraft  {total_msgs} messages", end="", flush=True)

            sdr.stop_stream()

    except RTLSDRError as exc:
        print(f"RTL-SDR error: {exc}", file=sys.stderr)
        sys.exit(1)
    finally:
        if csv_fh:
            csv_fh.close()
        if not args.dump_only:
            print()
        print(f"Done. {total_msgs} messages decoded.")


if __name__ == "__main__":
    main()
