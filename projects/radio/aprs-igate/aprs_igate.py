#!/usr/bin/env python3
"""
APRS Igate via IC-9700

Receives APRS packets on 144.390 MHz using the IC-9700's USB audio output
and direwolf as the AX.25 soft-TNC.  Decodes packets, enriches callsigns
via the govt-data /callsigns API, and optionally gates decoded packets to
APRS-IS.

The IC-9700 presents as a USB audio device on Linux (typically
hw:IC-9700,0 or a ALSA device).  Audio is piped through direwolf which
handles AFSK 1200 baud demodulation and AX.25 frame assembly.

Requirements:
    - direwolf installed (pacman -S direwolf or compile from source)
    - IC-9700 USB audio interface active (IC-9700 menu: USB AF Output = AF)
    - rigctld running if using IC-9700 CAT control

Usage:
    # Monitor only (no gating to APRS-IS):
    python aprs_igate.py

    # Gate to APRS-IS with callsign N0GQ-10:
    python aprs_igate.py --gate --callsign N0GQ-10 --passcode 12345

    # Specify audio device:
    python aprs_igate.py --audio-dev "hw:IC-9700,0"

    # Also set IC-9700 frequency via CAT:
    python aprs_igate.py --set-freq

    # Enrich callsigns via govt-data API:
    python aprs_igate.py --enrich

Output:
    Live console + aprs_igate_<timestamp>.db (SQLite)
"""

import argparse
import json
import re
import socket
import sqlite3
import subprocess
import sys
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from rf_bench import connect

APRS_FREQ_KHZ    = 144_390.0
APRS_IS_HOST     = "rotate.aprs2.net"
APRS_IS_PORT     = 14580
GOVTDATA_HOST    = "10.1.0.20"
GOVTDATA_PORT    = 8091
DEFAULT_RIG_HOST = "localhost"
DEFAULT_RIG_PORT = 4532


# ── SQLite ────────────────────────────────────────────────────────────────────

def open_db(path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(path, check_same_thread=False)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS packets (
            id          INTEGER PRIMARY KEY,
            ts_utc      TEXT,
            ts_unix     REAL,
            raw         TEXT,
            callsign    TEXT,
            path        TEXT,
            info        TEXT,
            lat         REAL,
            lon         REAL,
            comment     TEXT,
            fcc_name    TEXT,
            fcc_class   TEXT,
            gated       INTEGER DEFAULT 0
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_call ON packets (callsign)")
    conn.commit()
    return conn


# ── Callsign enrichment ───────────────────────────────────────────────────────

_enrich_cache: dict = {}

def enrich_callsign(callsign: str) -> dict:
    base = callsign.split("-")[0].upper()
    if base in _enrich_cache:
        return _enrich_cache[base]
    try:
        with socket.create_connection((GOVTDATA_HOST, GOVTDATA_PORT), timeout=3) as s:
            req = (f"GET /callsigns/{base} HTTP/1.1\r\n"
                   f"Host: {GOVTDATA_HOST}:{GOVTDATA_PORT}\r\nConnection: close\r\n\r\n")
            s.sendall(req.encode())
            data = b""
            while chunk := s.recv(4096):
                data += chunk
        body = data.split(b"\r\n\r\n", 1)[-1]
        info = json.loads(body)
        result = {
            "name":      info.get("name_first", "") + " " + info.get("name_last", ""),
            "fcc_class": info.get("operator_class", ""),
            "city":      info.get("po_city", ""),
            "state":     info.get("state", ""),
        }
        _enrich_cache[base] = result
        return result
    except Exception:
        _enrich_cache[base] = {}
        return {}


# ── APRS packet parser (minimal) ─────────────────────────────────────────────

_COORD_RE = re.compile(
    r"(\d{2})(\d{2}\.\d+)([NS]).(\d{3})(\d{2}\.\d+)([EW])"
)

def parse_position(info: str):
    m = _COORD_RE.search(info)
    if not m:
        return None, None
    lat_deg, lat_min, lat_ns, lon_deg, lon_min, lon_ew = m.groups()
    lat = int(lat_deg) + float(lat_min) / 60.0
    lon = int(lon_deg) + float(lon_min) / 60.0
    if lat_ns == "S":
        lat = -lat
    if lon_ew == "W":
        lon = -lon
    return lat, lon


# ── APRS-IS gating ────────────────────────────────────────────────────────────

class APRSISGate:
    def __init__(self, callsign: str, passcode: int):
        self._call = callsign
        self._pass = passcode
        self._sock = None
        self._lock = threading.Lock()

    def connect(self):
        s = socket.create_connection((APRS_IS_HOST, APRS_IS_PORT), timeout=10)
        banner = s.recv(1024)
        login  = f"user {self._call} pass {self._pass} vers aprs-igate 1.0\r\n"
        s.sendall(login.encode())
        time.sleep(0.5)
        self._sock = s

    def gate(self, raw_packet: str):
        if not self._sock:
            return
        line = raw_packet.strip() + "\r\n"
        with self._lock:
            try:
                self._sock.sendall(line.encode())
            except OSError:
                self._sock = None   # reconnect on next gate() call

    def close(self):
        if self._sock:
            try:
                self._sock.close()
            except OSError:
                pass


# ── direwolf subprocess reader ────────────────────────────────────────────────

def parse_direwolf_line(line: str):
    """
    direwolf outputs packets in several formats.  We care about the
    decoded packet lines that look like:
        [0.3] N0GQ-9>APRS,WIDE2-1:!3945.15N/10445.78W>...
    Returns (callsign, path, info) or None.
    """
    # Strip direwolf channel prefix [N.N]
    m = re.match(r"\[\d+\.\d+\]\s+(.+)", line)
    if not m:
        return None
    packet = m.group(1).strip()
    if ">" not in packet or ":" not in packet:
        return None
    header, info = packet.split(":", 1)
    if ">" not in header:
        return None
    callsign, path = header.split(">", 1)
    return callsign.strip(), path.strip(), info.strip()


def run_direwolf(audio_dev: str):
    """Start direwolf and return the subprocess."""
    # direwolf reads audio from ALSA, outputs decoded packets to stdout
    cmd = [
        "direwolf",
        "-a", audio_dev,    # ALSA audio device
        "-r", "48000",      # sample rate (IC-9700 USB audio = 48 kHz)
        "-t", "0",          # no text colours (easier to parse)
        "-q", "hd",         # suppress heard/dup messages, keep decoded packets
    ]
    proc = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        text=True,
        bufsize=1,
    )
    return proc


# ── main loop ─────────────────────────────────────────────────────────────────

def main():
    p = argparse.ArgumentParser(description="IC-9700 APRS igate")
    p.add_argument("--freq",       type=float, default=APRS_FREQ_KHZ,
                   help="Receive frequency in kHz (default %(default)s)")
    p.add_argument("--audio-dev",  default="plughw:IC-9700,0", dest="audio_dev",
                   help="ALSA audio device (default plughw:IC-9700,0)")
    p.add_argument("--gate",       action="store_true",
                   help="Gate decoded packets to APRS-IS")
    p.add_argument("--callsign",   default="N0GQ-10",
                   help="Station callsign for APRS-IS login (default N0GQ-10)")
    p.add_argument("--passcode",   type=int, default=0,
                   help="APRS-IS passcode")
    p.add_argument("--enrich",     action="store_true",
                   help="Enrich callsigns via govt-data API (10.1.0.20:8091)")
    p.add_argument("--set-freq",   action="store_true", dest="set_freq",
                   help="Set IC-9700 frequency and mode via CAT before starting")
    p.add_argument("--rig-host",   default=DEFAULT_RIG_HOST, dest="rig_host")
    p.add_argument("--rig-port",   type=int, default=DEFAULT_RIG_PORT, dest="rig_port")
    p.add_argument("--out",        default=None,
                   help="SQLite output path (default: aprs_igate_<ts>.db)")
    args = p.parse_args()

    ts      = datetime.now().strftime("%Y%m%d_%H%M%S")
    db_path = args.out or f"aprs_igate_{ts}.db"
    conn    = open_db(db_path)

    # Optional: set IC-9700 frequency/mode via CAT
    if args.set_freq:
        try:
            from rf_bench.icom import IC9700
            radio = IC9700(host=args.rig_host, port=args.rig_port)
            radio.set_frequency(args.freq * 1000.0)
            radio.set_mode("fm")
            radio.close()
            print(f"IC-9700 tuned to {args.freq:.3f} kHz FM")
        except Exception as e:
            print(f"CAT control failed ({e}); continuing without tuning.")

    # Optional APRS-IS gate
    gate = None
    if args.gate:
        gate = APRSISGate(args.callsign, args.passcode)
        try:
            gate.connect()
            print(f"APRS-IS connected as {args.callsign}")
        except Exception as e:
            print(f"APRS-IS connection failed ({e}); gating disabled.")
            gate = None

    print(f"Listening on {args.audio_dev}  ({args.freq:.3f} kHz)")
    print(f"Logging to {db_path}")
    print("Press Ctrl-C to stop.\n")

    try:
        proc = run_direwolf(args.audio_dev)
    except FileNotFoundError:
        print("ERROR: direwolf not found.  Install: pacman -S direwolf")
        sys.exit(1)

    try:
        for raw_line in proc.stdout:
            raw_line = raw_line.rstrip()
            if not raw_line:
                continue

            parsed = parse_direwolf_line(raw_line)
            if not parsed:
                continue

            callsign, path, info = parsed
            lat, lon = parse_position(info)

            fcc_name = fcc_class = None
            if args.enrich:
                enc = enrich_callsign(callsign)
                fcc_name  = enc.get("name", "").strip() or None
                fcc_class = enc.get("fcc_class") or None

            now = datetime.now(timezone.utc)
            gated = 0
            if gate:
                gate.gate(f"{callsign}>{path}:{info}")
                gated = 1

            conn.execute(
                "INSERT INTO packets "
                "(ts_utc, ts_unix, raw, callsign, path, info, lat, lon, "
                " fcc_name, fcc_class, gated) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                (now.isoformat(), now.timestamp(),
                 raw_line, callsign, path, info,
                 lat, lon, fcc_name, fcc_class, gated),
            )
            conn.commit()

            # Console display
            pos_str = ""
            if lat is not None:
                pos_str = f"  {lat:.4f},{lon:.4f}"
            enr_str = f"  [{fcc_name}]" if fcc_name else ""
            gate_str = " [GATED]" if gated else ""
            print(f"[{now.strftime('%H:%M:%S')}] "
                  f"{callsign:>10} > {path:<20} "
                  f"{pos_str}{enr_str}{gate_str}")

    except KeyboardInterrupt:
        print("\nStopped.")
    finally:
        proc.terminate()
        proc.wait()
        if gate:
            gate.close()
        conn.close()


if __name__ == "__main__":
    main()
