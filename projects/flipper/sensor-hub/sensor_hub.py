#!/usr/bin/env python3
"""
Flipper Zero 433 MHz Sensor Hub

Receives 433 MHz OOK broadcast packets from consumer weather sensors.
Decodes Oregon Scientific v3 and Nexus/Fine Offset/AcuRite protocols inline.
Logs temperature/humidity/battery to SQLite and serves current readings via HTTP.

Usage:
  python sensor_hub.py --freq 433.92 --port 8095
  python sensor_hub.py --db sensors.db --port 8095
  python sensor_hub.py --freq 433.92 --duration 0
"""

import argparse
import json
import os
import signal
import sqlite3
import sys
import time
from datetime import datetime
from http.server import BaseHTTPRequestHandler, HTTPServer
from threading import Thread

import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                '..', 'rf-bench'))
from rf_bench.flipper import FlipperZero

# ---------------------------------------------------------------------------
# Defaults
# ---------------------------------------------------------------------------
DEFAULT_FREQ_MHZ = 433.92
DEFAULT_PORT     = 8095
DEFAULT_DB       = "sensor_hub.db"
DEFAULT_SERIAL   = "/dev/ttyACM0"

_running = True
_latest_readings: dict = {}   # sensor_id -> latest reading dict


def _sigint_handler(sig, frame):
    global _running
    _running = False
    print("\n  [Ctrl+C -- shutting down]")


signal.signal(signal.SIGINT, _sigint_handler)


# ---------------------------------------------------------------------------
# Database
# ---------------------------------------------------------------------------

def open_db(path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(path, check_same_thread=False)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS readings (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            ts          TEXT    NOT NULL,
            sensor_id   TEXT    NOT NULL,
            protocol    TEXT    NOT NULL,
            channel     INTEGER,
            temp_c      REAL,
            humidity    INTEGER,
            battery_ok  INTEGER,
            raw_bits    TEXT
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_ts ON readings(ts)")
    conn.commit()
    return conn


def log_reading(conn: sqlite3.Connection, reading: dict) -> None:
    conn.execute(
        "INSERT INTO readings(ts,sensor_id,protocol,channel,temp_c,humidity,battery_ok,raw_bits)"
        " VALUES(?,?,?,?,?,?,?,?)",
        (datetime.now().isoformat(), reading["sensor_id"], reading["protocol"],
         reading.get("channel"), reading.get("temp_c"), reading.get("humidity"),
         reading.get("battery_ok"), reading.get("raw_bits")),
    )
    conn.commit()


# ---------------------------------------------------------------------------
# Decoders
# ---------------------------------------------------------------------------

def parse_raw_bits(raw: str) -> list:
    """Extract bit list from Flipper raw output (pulse widths -> OOK bits)."""
    # Simplified: look for a "Data:" line with hex or binary
    bits = []
    for line in raw.splitlines():
        line = line.strip()
        if line.startswith("Data:"):
            data = line.split(":", 1)[1].strip()
            # Try hex
            try:
                val = int(data.replace(" ", ""), 16)
                n_bits = len(data.replace(" ", "")) * 4
                bits = [(val >> (n_bits - 1 - i)) & 1 for i in range(n_bits)]
                break
            except ValueError:
                pass
            # Try binary string
            if all(c in "01" for c in data.replace(" ", "")):
                bits = [int(b) for b in data.replace(" ", "")]
                break
    return bits


def decode_nexus(bits: list) -> dict | None:
    """
    Nexus/Fine Offset/AcuRite protocol.
    36 bits: [ID:8][CH:2][0:1][BAT:1][0:4][TEMP12:12][HUM8:8]
    """
    if len(bits) < 36:
        return None
    sensor_id = sum(bits[i] << (7 - i) for i in range(8))
    channel   = sum(bits[8 + i] << (1 - i) for i in range(2))
    battery   = bits[11]
    # Temperature: 12 bits, 2's complement, 0.1 C
    raw_temp  = sum(bits[16 + i] << (11 - i) for i in range(12))
    if raw_temp & 0x800:
        raw_temp -= 4096
    temp_c    = raw_temp * 0.1
    humidity  = sum(bits[28 + i] << (7 - i) for i in range(8))
    if not (0 <= humidity <= 100 and -50 <= temp_c <= 70):
        return None
    return {
        "protocol":   "Nexus",
        "sensor_id":  f"nexus_{sensor_id:02X}",
        "channel":    channel,
        "temp_c":     round(temp_c, 1),
        "humidity":   humidity,
        "battery_ok": battery,
        "raw_bits":   "".join(str(b) for b in bits[:36]),
    }


def decode_oregon_v3(bits: list) -> dict | None:
    """
    Oregon Scientific v3 preamble + nibble sync.
    Simplified: check sync and extract sensor ID, temp, humidity from nibbles.
    Supports THGN132N (sensor type 0xEC40) and similar.
    """
    if len(bits) < 96:
        return None

    # Convert bits to nibbles (4-bit groups)
    nibbles = []
    for i in range(0, len(bits) - 3, 4):
        n = sum(bits[i + j] << j for j in range(4))  # LSB first
        nibbles.append(n)

    if len(nibbles) < 12:
        return None

    # Sensor type: nibbles 0-3 (first 2 bytes)
    sensor_type = (nibbles[0] | (nibbles[1] << 4) |
                   (nibbles[2] << 8) | (nibbles[3] << 12))
    channel = nibbles[4] & 0x0F
    rolling = nibbles[5] | (nibbles[6] << 4)
    battery = (nibbles[7] >> 2) & 1

    # Temperature: nibbles 8-10, BCD, *0.1
    temp_raw = nibbles[8] * 10 + nibbles[9] + nibbles[10] * 100
    sign     = (nibbles[11] >> 3) & 1
    temp_c   = temp_raw * 0.1 * (-1 if sign else 1)

    humidity = nibbles[12] * 10 + nibbles[13] if len(nibbles) > 13 else None

    if not (-50 <= temp_c <= 70):
        return None

    return {
        "protocol":   "Oregon_v3",
        "sensor_id":  f"oregon_{sensor_type:04X}_{rolling:02X}",
        "channel":    channel,
        "temp_c":     round(temp_c, 1),
        "humidity":   humidity,
        "battery_ok": battery,
        "raw_bits":   "".join(str(b) for b in bits[:96]),
    }


def try_decode(raw: str) -> dict | None:
    """Try all decoders; return first successful parse or None."""
    bits = parse_raw_bits(raw)
    if not bits:
        return None
    for decoder in (decode_nexus, decode_oregon_v3):
        result = decoder(bits)
        if result:
            return result
    return None


# ---------------------------------------------------------------------------
# HTTP server
# ---------------------------------------------------------------------------

class SensorHandler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        pass  # suppress access log noise

    def do_GET(self):
        if self.path == "/sensors":
            body = json.dumps(_latest_readings, indent=2).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", len(body))
            self.end_headers()
            self.wfile.write(body)
        else:
            self.send_response(404)
            self.end_headers()


# ---------------------------------------------------------------------------
# Main receive loop
# ---------------------------------------------------------------------------

def receive_loop(fz: FlipperZero, conn: sqlite3.Connection,
                 freq_hz: float, duration_s: float) -> None:
    t_start = time.time()
    print(f"\n[LISTENING @ {freq_hz/1e6:.4f} MHz]  "
          f"duration={'forever' if duration_s == 0 else f'{duration_s:.0f}s'}")
    print(f"  {'Time':>10}  {'Sensor ID':>24}  {'Proto':>12}  "
          f"{'Temp (C)':>10}  {'Hum%':>6}  {'Bat':>4}")
    print("  " + "-" * 74)

    while _running:
        elapsed = time.time() - t_start
        if duration_s > 0 and elapsed >= duration_s:
            break

        raw = fz.subghz_get_raw(int(freq_hz), duration_s=2.0)
        if not raw:
            continue

        reading = try_decode(raw)
        if not reading:
            continue

        log_reading(conn, reading)
        _latest_readings[reading["sensor_id"]] = reading

        ts_short = datetime.now().strftime("%H:%M:%S")
        print(f"  {ts_short:>10}  {reading['sensor_id']:>24}  "
              f"{reading['protocol']:>12}  "
              f"{reading.get('temp_c', '--'):>10}  "
              f"{reading.get('humidity', '--'):>6}  "
              f"{'OK' if reading.get('battery_ok') else 'LO':>4}")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Receive and decode 433 MHz weather sensor broadcasts",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python sensor_hub.py --freq 433.92 --port 8095
  python sensor_hub.py --duration 0 --db wx.db
  curl http://localhost:8095/sensors
""",
    )
    parser.add_argument("--freq",     type=float, default=DEFAULT_FREQ_MHZ, metavar="MHZ",
                        help=f"Frequency in MHz (default {DEFAULT_FREQ_MHZ})")
    parser.add_argument("--port",     type=int, default=DEFAULT_PORT, metavar="N",
                        help=f"HTTP port (default {DEFAULT_PORT})")
    parser.add_argument("--db",       default=DEFAULT_DB, metavar="FILE",
                        help=f"SQLite DB file (default {DEFAULT_DB})")
    parser.add_argument("--duration", type=float, default=0, metavar="S",
                        help="Run duration; 0=forever (default 0)")
    parser.add_argument("--serial",   default=DEFAULT_SERIAL, metavar="PORT",
                        help=f"Flipper serial port (default {DEFAULT_SERIAL})")

    args = parser.parse_args()

    conn = open_db(args.db)
    print(f"Database: {args.db}")

    # Start HTTP server in background thread
    httpd = HTTPServer(("", args.port), SensorHandler)
    t = Thread(target=httpd.serve_forever, daemon=True)
    t.start()
    print(f"HTTP server: http://localhost:{args.port}/sensors")

    try:
        print(f"Connecting to Flipper @ {args.serial} ...")
        fz = FlipperZero(args.serial)
        print(f"  {fz.identify()}")
        receive_loop(fz, conn, args.freq * 1e6, args.duration)
    except KeyboardInterrupt:
        pass
    except Exception as exc:
        import traceback
        print(f"\nError: {exc}")
        traceback.print_exc()
    finally:
        httpd.shutdown()
        conn.close()
        print("Stopped.")


if __name__ == "__main__":
    main()
