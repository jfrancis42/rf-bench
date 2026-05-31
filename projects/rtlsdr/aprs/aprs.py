#!/usr/bin/env -S python3 -u
"""
APRS Direct Receive

Receives APRS 1200-baud AFSK packets directly from 144.390 MHz via RTL-SDR,
decodes them with direwolf, and cross-references each callsign with the
govt-data /callsigns API and the aprs-server PostgreSQL database.

Produces three outputs:
  1. Live console: decoded packets with FCC callsign enrichment
  2. SQLite log: all heard packets with rssi_db and heard_locally flag
  3. Cross-reference report: compare heard-locally vs. APRS-IS (--compare)

Requirements:
  - direwolf installed (pacman -S direwolf)
  - RTL-SDR dongle + 144 MHz antenna (vertical dipole or co-linear)

Usage:
    python aprs.py
    python aprs.py --gain 40 --freq 144390
    python aprs.py --compare                # compare local vs APRS-IS coverage
    python aprs.py --no-enrich --no-compare # raw packet log only
"""

import argparse
import json
import os
import re
import select
import signal
import sqlite3
import subprocess
import sys
import tempfile
import threading
import time
from datetime import datetime, timezone
from urllib.request import urlopen, Request
from urllib.error import URLError

from rf_bench.rtlsdr import RTLSDR, RTLSDRError

# ---------------------------------------------------------------------------
# Defaults
# ---------------------------------------------------------------------------

DEFAULT_FREQ_KHZ     = 144_390
DEFAULT_SAMPLE_RATE  = 24_000    # rtl_fm audio output rate for direwolf
DEFAULT_GAIN         = 40
DEFAULT_DB_PATH      = "aprs_local.db"
GOVTDATA_HOST        = "10.1.0.20"
GOVTDATA_PORT        = 8091
APRSDB_HOST          = "10.1.0.20"
APRSDB_NAME          = "aprs"

_running = True

def _sigint(_sig, _frame):
    global _running
    _running = False

signal.signal(signal.SIGINT, _sigint)


# ---------------------------------------------------------------------------
# SQLite schema
# ---------------------------------------------------------------------------

CREATE_SQL = """
CREATE TABLE IF NOT EXISTS callsign_info (
    callsign    TEXT PRIMARY KEY,
    name        TEXT,
    address     TEXT,
    license     TEXT,
    enriched_at REAL
);

CREATE TABLE IF NOT EXISTS packets (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp   REAL NOT NULL,
    callsign    TEXT NOT NULL,
    path        TEXT,
    packet_type TEXT,
    data        TEXT,
    rssi_db     REAL,
    raw         TEXT
);

CREATE INDEX IF NOT EXISTS pkt_time     ON packets(timestamp);
CREATE INDEX IF NOT EXISTS pkt_callsign ON packets(callsign);
"""


def open_db(path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(path, check_same_thread=False)
    conn.executescript(CREATE_SQL)
    conn.commit()
    return conn


# ---------------------------------------------------------------------------
# Callsign enrichment from govt-data
# ---------------------------------------------------------------------------

_enrich_cache: dict = {}
_enrich_lock  = threading.Lock()
ENRICH_TTL    = 3600


def enrich_callsign(callsign: str, conn: sqlite3.Connection) -> dict:
    """Look up an amateur callsign via govt-data /callsigns API."""
    # Strip SSID if present
    base = callsign.split("-")[0].upper()
    now  = time.time()

    with _enrich_lock:
        if base in _enrich_cache:
            ts, data = _enrich_cache[base]
            if now - ts < ENRICH_TTL:
                return data

    row = conn.execute(
        "SELECT name, address, license, enriched_at FROM callsign_info WHERE callsign=?",
        (base,)
    ).fetchone()
    if row and row[3] and (now - row[3] < ENRICH_TTL):
        data = {"name": row[0], "address": row[1], "license": row[2]}
        with _enrich_lock:
            _enrich_cache[base] = (now, data)
        return data

    try:
        url = f"http://{GOVTDATA_HOST}:{GOVTDATA_PORT}/callsigns?callsign={base}"
        req = Request(url, headers={"Accept": "application/json"})
        with urlopen(req, timeout=2.0) as resp:
            payload = json.loads(resp.read())
        if isinstance(payload, list) and payload:
            r = payload[0]
        elif isinstance(payload, dict):
            r = payload
        else:
            raise ValueError("empty")
        data = {
            "name":    r.get("entity_name") or r.get("name"),
            "address": f"{r.get('po_box') or r.get('city')}, {r.get('state')}".strip(", "),
            "license": r.get("license_class") or r.get("operator_class"),
        }
    except Exception:
        data = {"name": None, "address": None, "license": None}

    with _enrich_lock:
        _enrich_cache[base] = (now, data)

    conn.execute(
        """INSERT INTO callsign_info(callsign, name, address, license, enriched_at)
           VALUES(?,?,?,?,?)
           ON CONFLICT(callsign) DO UPDATE SET
             name=excluded.name,
             address=excluded.address,
             license=excluded.license,
             enriched_at=excluded.enriched_at""",
        (base, data["name"], data["address"], data["license"], now)
    )
    conn.commit()
    return data


# ---------------------------------------------------------------------------
# Packet parser (direwolf output format)
# ---------------------------------------------------------------------------

# Direwolf output line examples:
# Decoded[1] 0:00:02 W0ABC-9>APX203,WIDE1-1,WIDE2-1:!3957.00N/10502.00W>
# [0.3] W0ABC-9>APX203,WIDE1-1,WIDE2-1:!3957.00N/10502.00W>...

_DECODED_RE = re.compile(
    r'(?:Decoded\[\d+\]\s+[\d:]+\s+|^\[\S+\]\s*)'
    r'(?P<from>[A-Z0-9-]+)>(?P<to>[A-Z0-9-]+)(?:,(?P<path>[^:]+))?:(?P<data>.*)',
    re.IGNORECASE
)


def parse_direwolf_line(line: str) -> dict | None:
    """Parse a single direwolf output line into a packet dict."""
    m = _DECODED_RE.match(line.strip())
    if not m:
        return None
    from_call = m.group("from").upper()
    to_addr   = m.group("to").upper()
    path      = m.group("path") or ""
    data      = m.group("data") or ""

    pkt_type = "unknown"
    if data.startswith("!") or data.startswith("="):
        pkt_type = "position"
    elif data.startswith(">"):
        pkt_type = "status"
    elif data.startswith(":"):
        pkt_type = "message"
    elif data.startswith("`") or data.startswith("'"):
        pkt_type = "mic-e"
    elif data.startswith("T#"):
        pkt_type = "telemetry"
    elif data.startswith("_"):
        pkt_type = "weather"

    return {
        "callsign": from_call,
        "to":       to_addr,
        "path":     path,
        "type":     pkt_type,
        "data":     data[:200],
        "raw":      line.strip(),
    }


# ---------------------------------------------------------------------------
# APRS-IS database comparison
# ---------------------------------------------------------------------------

def compare_aprs_is(conn: sqlite3.Connection, lookback_s: float = 3600.0) -> None:
    """
    Compare locally heard callsigns against the APRS-IS-sourced aprs-server DB.
    Prints a report showing:
      - Heard locally AND on APRS-IS (gated)
      - Heard locally, NOT on APRS-IS (un-gated)
      - On APRS-IS but not heard locally (out of range or internet-only)
    """
    try:
        import psycopg2
    except ImportError:
        print("psycopg2 not installed; install it to enable APRS-IS comparison.")
        return

    cutoff = time.time() - lookback_s

    local_rows = conn.execute(
        "SELECT DISTINCT callsign FROM packets WHERE timestamp > ?",
        (cutoff,)
    ).fetchall()
    local_calls = {r[0].split("-")[0] for r in local_rows}

    try:
        pg = psycopg2.connect(host=APRSDB_HOST, dbname=APRSDB_NAME,
                              connect_timeout=5)
        cur = pg.cursor()
        cur.execute(
            "SELECT DISTINCT callsign FROM aprs_packets "
            "WHERE received_at > NOW() - INTERVAL %s",
            (f"{int(lookback_s)} seconds",)
        )
        is_calls = {r[0].split("-")[0] for r in cur.fetchall()}
        pg.close()
    except Exception as exc:
        print(f"Could not connect to aprs-server DB: {exc}")
        return

    gated      = sorted(local_calls & is_calls)
    local_only = sorted(local_calls - is_calls)
    is_only    = sorted(is_calls    - local_calls)

    print(f"\n=== APRS Coverage Comparison (last {int(lookback_s/60)} min) ===")
    print(f"Heard locally:     {len(local_calls)}")
    print(f"On APRS-IS:        {len(is_calls)}")
    print(f"\nGated (both):      {len(gated)}")
    if gated:
        print("  " + "  ".join(gated[:20]) + ("..." if len(gated) > 20 else ""))
    print(f"\nLocal only (un-gated): {len(local_only)}")
    for cs in local_only[:10]:
        print(f"  {cs}")
    if len(local_only) > 10:
        print(f"  ... ({len(local_only)-10} more)")
    print(f"\nAPRS-IS only (out of range): {len(is_only)}")
    print()


# ---------------------------------------------------------------------------
# Main receive loop
# ---------------------------------------------------------------------------

def main():
    ap = argparse.ArgumentParser(description="APRS direct-RF receive via RTL-SDR")
    ap.add_argument("--freq",      type=float, default=DEFAULT_FREQ_KHZ,
                    help="Receive frequency in kHz (default: %(default)s)")
    ap.add_argument("--gain",      type=float, default=DEFAULT_GAIN,
                    help="Receiver gain in dB (default: %(default)s)")
    ap.add_argument("--db",        default=DEFAULT_DB_PATH,
                    help="SQLite log path (default: %(default)s)")
    ap.add_argument("--no-enrich", action="store_true",
                    help="Disable FCC callsign lookup")
    ap.add_argument("--compare",   action="store_true",
                    help="Print APRS-IS coverage comparison after receiving")
    ap.add_argument("--duration",  type=float, default=0,
                    help="Stop after N seconds (0 = run forever)")
    ap.add_argument("--serial",    help="RTL-SDR serial number")
    args = ap.parse_args()

    conn = open_db(args.db)

    freq_hz = int(args.freq * 1000)
    print(f"APRS receive on {args.freq:.3f} kHz  gain={args.gain} dB")
    print("Decoding via rtl_fm | direwolf.  Ctrl-C to stop.")

    # Build the rtl_fm | direwolf pipeline.
    # rtl_fm outputs raw 16-bit signed PCM to stdout; direwolf reads it on stdin.
    # We write a minimal direwolf config so the pipeline works regardless of
    # whatever ADEVICE is set in the user's ~/direwolf.conf.
    dw_conf = tempfile.NamedTemporaryFile(
        mode="w", suffix=".conf", prefix="rfbench_dw_", delete=False
    )
    dw_conf.write(
        f"ADEVICE stdin null\n"
        f"CHANNEL 0\n"
        f"MYCALL N0CALL\n"
        f"MODEM 1200\n"
    )
    dw_conf.flush()
    dw_conf_path = dw_conf.name

    rtl_cmd = [
        "rtl_fm",
        "-f", str(freq_hz),
        "-M", "fm",
        "-s", str(DEFAULT_SAMPLE_RATE),
        "-r", str(DEFAULT_SAMPLE_RATE),
        "-g", str(args.gain),
        "-",
    ]
    dw_cmd = [
        "direwolf",
        "-c", dw_conf_path,
        "-r", str(DEFAULT_SAMPLE_RATE),
        "-b", "16",
        "-n", "1",
        "-t", "0",    # no color codes
        "-",
    ]

    try:
        rtlfm = subprocess.Popen(
            rtl_cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
        )
        dw = subprocess.Popen(
            dw_cmd,
            stdin=rtlfm.stdout,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )
    except FileNotFoundError as exc:
        print(f"Error: {exc}. Install rtl-sdr and direwolf (pacman -S rtl-sdr direwolf).",
              file=sys.stderr)
        os.unlink(dw_conf_path)
        sys.exit(1)

    start_time = time.time()
    total_pkts = 0

    try:
        while _running:
            if args.duration > 0 and (time.time() - start_time) > args.duration:
                break
            if dw.poll() is not None:
                print("direwolf exited unexpectedly.", file=sys.stderr)
                break

            line = dw.stdout.readline()
            if not line:
                time.sleep(0.1)
                continue

            pkt = parse_direwolf_line(line)
            if not pkt:
                continue

            total_pkts += 1
            now = time.time()

            conn.execute(
                "INSERT INTO packets(timestamp,callsign,path,packet_type,data,rssi_db,raw)"
                " VALUES(?,?,?,?,?,?,?)",
                (now, pkt["callsign"], pkt["path"], pkt["type"], pkt["data"], None, pkt["raw"])
            )
            conn.commit()

            # Console output
            ts  = datetime.fromtimestamp(now, tz=timezone.utc).strftime("%H:%M:%S")
            msg = f"[{ts}] {pkt['callsign']:10s} {pkt['type']:10s} {pkt['data'][:60]}"

            if not args.no_enrich:
                def _print_enriched(cs=pkt["callsign"], m=msg):
                    info = enrich_callsign(cs, conn)
                    name = info.get("name") or ""
                    if name:
                        print(f"{m}  ({name})")
                    else:
                        print(m)
                threading.Thread(target=_print_enriched, daemon=True).start()
            else:
                print(msg)

    finally:
        rtlfm.terminate()
        dw.terminate()
        try:
            rtlfm.wait(timeout=2)
            dw.wait(timeout=2)
        except subprocess.TimeoutExpired:
            rtlfm.kill()
            dw.kill()
        try:
            os.unlink(dw_conf_path)
        except OSError:
            pass

    print(f"\nDone. {total_pkts} packets decoded.")

    if args.compare:
        compare_aprs_is(conn)


if __name__ == "__main__":
    main()
