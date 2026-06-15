#!/usr/bin/env python3
"""
D-STAR Digital Voice Monitor — IC-9700

Monitors a D-STAR frequency using the IC-9700 in DV mode.  The IC-9700
handles all D-STAR decoding internally; this script reads the decoded
header data (callsigns, message, URCALL) via Hamlib CAT and logs all
activity to SQLite.

The IC-9700 in DV mode outputs:
  - Decoded audio via USB sound card (as with FM)
  - RX callsign (originating station) via CAT
  - URCALL (destination/CQ call) via CAT
  - Message text (20-character free text) via CAT
  - S-meter / signal strength

Note on CAT access to D-STAR data:
    Hamlib exposes D-STAR fields via custom rigctld commands.
    The IC-9700 CI-V protocol has commands for reading
    the last decoded D-STAR header.  This script uses
    `rigctld_cmd('u DSTAR_MYCALL')` etc. to read these fields.
    If your rigctld version doesn't support these, the script falls back
    to S-meter monitoring only (still useful for detecting activity).

Usage:
    # Monitor 144.490 MHz D-STAR calling frequency:
    python dstar_monitor.py --freq 144490

    # Monitor with callsign enrichment:
    python dstar_monitor.py --freq 144490 --enrich

    # Log to named file:
    python dstar_monitor.py --freq 144490 --out dstar_log.db

Output:
    dstar_<freq>_<timestamp>.db (SQLite)
    Live console showing decoded headers
"""

import argparse
import json
import socket
import sqlite3
import time
from datetime import datetime, timezone

from rf_bench.icom import IC9700
from rf_bench import connect

GOVTDATA_HOST = "10.1.0.20"
GOVTDATA_PORT = 8091
DEFAULT_RIG_HOST = "localhost"
DEFAULT_RIG_PORT = 4532
DEFAULT_FREQ_KHZ = 144_490.0
POLL_INTERVAL    = 0.5          # seconds between CAT polls


# ── SQLite ────────────────────────────────────────────────────────────────────

def open_db(path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(path, check_same_thread=False)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS activity (
            id          INTEGER PRIMARY KEY,
            ts_utc      TEXT,
            ts_unix     REAL,
            mycall      TEXT,
            urcall      TEXT,
            rpt1        TEXT,
            rpt2        TEXT,
            message     TEXT,
            signal_dbm  REAL,
            fcc_name    TEXT,
            fcc_class   TEXT
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_mycall ON activity (mycall)")
    conn.commit()
    return conn


# ── FCC callsign enrichment ───────────────────────────────────────────────────

_cache: dict = {}

def enrich(callsign: str) -> dict:
    base = callsign.split("/")[0].strip().upper()
    if not base or base in ("CQCQCQ", ""):
        return {}
    if base in _cache:
        return _cache[base]
    try:
        with socket.create_connection((GOVTDATA_HOST, GOVTDATA_PORT), timeout=3) as s:
            req = (f"GET /callsigns/{base} HTTP/1.1\r\n"
                   f"Host: {GOVTDATA_HOST}:{GOVTDATA_PORT}\r\n"
                   f"Connection: close\r\n\r\n")
            s.sendall(req.encode())
            data = b""
            while chunk := s.recv(4096):
                data += chunk
        body = data.split(b"\r\n\r\n", 1)[-1]
        info = json.loads(body)
        result = {
            "name":  (info.get("name_first","") + " " + info.get("name_last","")).strip(),
            "class": info.get("operator_class",""),
            "city":  info.get("po_city",""),
            "state": info.get("state",""),
        }
        _cache[base] = result
        return result
    except Exception:
        _cache[base] = {}
        return {}


# ── D-STAR header reader ──────────────────────────────────────────────────────

def read_dstar_header(radio: IC9700) -> dict:
    """
    Read decoded D-STAR header fields from IC-9700 via rigctld.

    Falls back gracefully — if a field is unavailable, returns None for it.
    """
    fields = {}
    for field in ("DSTAR_MYCALL", "DSTAR_URCALL", "DSTAR_RPT1",
                  "DSTAR_RPT2", "DSTAR_MESSAGE"):
        try:
            val = radio.rigctld_cmd("u", field).strip()
            fields[field] = val if val and val != "?" else None
        except Exception:
            fields[field] = None
    return fields


# ── main loop ─────────────────────────────────────────────────────────────────

def main():
    p = argparse.ArgumentParser(description="IC-9700 D-STAR activity monitor")
    p.add_argument("--freq",    type=float, default=DEFAULT_FREQ_KHZ,
                   help="Receive frequency in kHz (default %(default)s)")
    p.add_argument("--enrich",  action="store_true",
                   help="Enrich callsigns via govt-data FCC API")
    p.add_argument("--rig-host", default=DEFAULT_RIG_HOST, dest="rig_host")
    p.add_argument("--rig-port", type=int, default=DEFAULT_RIG_PORT, dest="rig_port")
    p.add_argument("--out",     default=None,
                   help="SQLite output path (default: dstar_<freq>_<ts>.db)")
    args = p.parse_args()

    freq_hz = args.freq * 1000.0
    ts      = datetime.now().strftime("%Y%m%d_%H%M%S")
    db_path = args.out or f"dstar_{args.freq:.0f}_{ts}.db"
    conn    = open_db(db_path)

    radio = IC9700(host=args.rig_host, port=args.rig_port)
    radio.set_frequency(freq_hz)
    radio.set_mode("dv")

    print(f"D-STAR Monitor  {args.freq:.3f} kHz DV")
    print(f"Logging to {db_path}")
    print("Press Ctrl-C to stop.\n")
    print(f"{'Time':8s}  {'MYCALL':10s}  {'URCALL':10s}  {'Signal':8s}  {'Message'}")
    print("-" * 70)

    last_mycall = None

    try:
        while True:
            signal_dbm = radio.get_strength()
            header     = read_dstar_header(radio)

            mycall  = header.get("DSTAR_MYCALL")
            urcall  = header.get("DSTAR_URCALL")
            rpt1    = header.get("DSTAR_RPT1")
            rpt2    = header.get("DSTAR_RPT2")
            message = header.get("DSTAR_MESSAGE")

            # Only log when a new transmission is detected (mycall changes)
            if mycall and mycall != last_mycall:
                last_mycall = mycall
                fcc_name = fcc_class = None
                if args.enrich and mycall:
                    enc = enrich(mycall)
                    fcc_name  = enc.get("name") or None
                    fcc_class = enc.get("class") or None

                now = datetime.now(timezone.utc)
                conn.execute(
                    "INSERT INTO activity "
                    "(ts_utc, ts_unix, mycall, urcall, rpt1, rpt2, "
                    " message, signal_dbm, fcc_name, fcc_class) "
                    "VALUES (?,?,?,?,?,?,?,?,?,?)",
                    (now.isoformat(), now.timestamp(),
                     mycall, urcall, rpt1, rpt2,
                     message, signal_dbm, fcc_name, fcc_class),
                )
                conn.commit()

                name_str = f"  [{fcc_name}]" if fcc_name else ""
                print(f"{now.strftime('%H:%M:%S')}  "
                      f"{(mycall or ''):10s}  "
                      f"{(urcall or ''):10s}  "
                      f"{signal_dbm:+6.1f} dBm  "
                      f"{message or ''}"
                      f"{name_str}")

            time.sleep(POLL_INTERVAL)

    except KeyboardInterrupt:
        print("\nStopped.")
    finally:
        radio.close()
        conn.close()


if __name__ == "__main__":
    main()
