#!/usr/bin/env python3
"""
Flipper Zero TPMS Tire Pressure Monitor Decoder

Decodes TPMS (Tire Pressure Monitoring System) broadcasts at 315/433.92 MHz.
Supports Schrader (Ford/GM) and Continental (VW/Audi) protocols.
Logs pressure and temperature to SQLite.

--learn mode prompts user to drive past slowly while capturing sensor IDs.
--alert PSI triggers an SMS via ~/Dropbox/build/money/sms.py when any
  tire pressure drops below the threshold.

Usage:
  python tpms.py --freq 315 --duration 60
  python tpms.py --freq 433.92 --learn
  python tpms.py --freq 315 --alert 30 --duration 0
"""

import argparse
import json
import os
import signal
import sqlite3
import subprocess
import sys
import time
from datetime import datetime

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                '..', 'rf-bench'))
from rf_bench.flipper import FlipperZero

# ---------------------------------------------------------------------------
# Defaults
# ---------------------------------------------------------------------------
DEFAULT_FREQ_MHZ = 315.0
DEFAULT_DURATION = 60
DEFAULT_DB       = "tpms.db"
DEFAULT_SERIAL   = "/dev/ttyACM0"
SMS_SCRIPT       = os.path.expanduser("~/Dropbox/build/money/sms.py")

_running = True
_known_sensors: dict = {}   # sensor_id -> {"position": str, "id": str}


def _sigint_handler(sig, frame):
    global _running
    _running = False
    print("\n  [Ctrl+C]")


signal.signal(signal.SIGINT, _sigint_handler)


# ---------------------------------------------------------------------------
# Database
# ---------------------------------------------------------------------------

def open_db(path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(path)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS tpms_readings (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            ts          TEXT NOT NULL,
            sensor_id   TEXT NOT NULL,
            protocol    TEXT NOT NULL,
            pressure_psi REAL,
            temp_c      REAL,
            battery_ok  INTEGER,
            position    TEXT,
            raw_bits    TEXT
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_ts ON tpms_readings(ts)")
    conn.commit()
    return conn


def log_reading(conn: sqlite3.Connection, r: dict) -> None:
    conn.execute(
        "INSERT INTO tpms_readings(ts,sensor_id,protocol,pressure_psi,temp_c,"
        "battery_ok,position,raw_bits) VALUES(?,?,?,?,?,?,?,?)",
        (datetime.now().isoformat(), r["sensor_id"], r["protocol"],
         r.get("pressure_psi"), r.get("temp_c"), r.get("battery_ok"),
         r.get("position"), r.get("raw_bits")),
    )
    conn.commit()


# ---------------------------------------------------------------------------
# Decoders
# ---------------------------------------------------------------------------

def bits_to_int(bits: list, msb: bool = True) -> int:
    if msb:
        return sum(bits[i] << (len(bits) - 1 - i) for i in range(len(bits)))
    return sum(bits[i] << i for i in range(len(bits)))


def extract_bits(raw: str) -> list:
    for line in raw.splitlines():
        line = line.strip()
        if line.startswith("Data:"):
            data = line.split(":", 1)[1].strip().replace(" ", "")
            try:
                val = int(data, 16)
                n   = len(data) * 4
                return [(val >> (n - 1 - i)) & 1 for i in range(n)]
            except ValueError:
                if all(c in "01" for c in data):
                    return [int(b) for b in data]
    return []


def decode_schrader(bits: list) -> dict | None:
    """
    Schrader TPMS (common on Ford/GM, 315 MHz).
    64 bits: [preamble:8][sensor_id:32][flags:4][pressure8:8][temp8:8][checksum:8]
    Pressure: bits * 0.25 PSI. Temperature: bits - 40 C.
    """
    if len(bits) < 64:
        return None
    sensor_id   = bits_to_int(bits[8:40])
    pressure_raw = bits_to_int(bits[44:52])
    temp_raw     = bits_to_int(bits[52:60])
    battery_ok   = (bits[42] == 0)
    pressure_psi = pressure_raw * 0.25
    temp_c       = temp_raw - 40.0

    if not (0 <= pressure_psi <= 100 and -40 <= temp_c <= 120):
        return None

    return {
        "protocol":     "Schrader",
        "sensor_id":    f"schrader_{sensor_id:08X}",
        "pressure_psi": round(pressure_psi, 2),
        "temp_c":       round(temp_c, 1),
        "battery_ok":   int(battery_ok),
        "raw_bits":     "".join(str(b) for b in bits[:64]),
    }


def decode_continental(bits: list) -> dict | None:
    """
    Continental TPMS (VW/Audi, 433.92 MHz).
    72 bits: [preamble:8][sensor_id:28][pressure8:8][temp8:8][flags:8][crc:8][stop:4]
    Pressure: bits * 0.2 PSI. Temperature: bits - 50 C.
    """
    if len(bits) < 72:
        return None
    sensor_id    = bits_to_int(bits[8:36])
    pressure_raw = bits_to_int(bits[36:44])
    temp_raw     = bits_to_int(bits[44:52])
    battery_low  = (bits[54] == 1)
    pressure_psi = pressure_raw * 0.2
    temp_c       = temp_raw - 50.0

    if not (0 <= pressure_psi <= 100 and -50 <= temp_c <= 120):
        return None

    return {
        "protocol":     "Continental",
        "sensor_id":    f"continental_{sensor_id:07X}",
        "pressure_psi": round(pressure_psi, 2),
        "temp_c":       round(temp_c, 1),
        "battery_ok":   int(not battery_low),
        "raw_bits":     "".join(str(b) for b in bits[:72]),
    }


def try_decode(raw: str) -> dict | None:
    bits = extract_bits(raw)
    if not bits:
        return None
    for decoder in (decode_schrader, decode_continental):
        r = decoder(bits)
        if r:
            return r
    return None


# ---------------------------------------------------------------------------
# Alerting
# ---------------------------------------------------------------------------

def send_sms_alert(sensor_id: str, pressure_psi: float, threshold_psi: float) -> None:
    if not os.path.exists(SMS_SCRIPT):
        print(f"  [ALERT] Low tire pressure: {sensor_id} = {pressure_psi:.1f} PSI "
              f"(threshold {threshold_psi:.0f} PSI) -- SMS script not found")
        return
    msg = (f"TPMS ALERT: sensor {sensor_id} "
           f"pressure={pressure_psi:.1f} PSI (low, threshold={threshold_psi:.0f})")
    try:
        subprocess.run([sys.executable, SMS_SCRIPT, msg], timeout=10)
    except Exception as exc:
        print(f"  SMS failed: {exc}")


# ---------------------------------------------------------------------------
# Learn mode
# ---------------------------------------------------------------------------

def learn_mode(fz: FlipperZero, freq_hz: float, duration_s: float = 120) -> None:
    """Capture sensor IDs; prompt user to label each tire position."""
    seen: dict = {}
    print(f"\n[LEARN MODE]  Drive slowly past sensor.  Capturing for {duration_s:.0f} s ...")
    t_start = time.time()

    while _running and (time.time() - t_start) < duration_s:
        raw = fz.subghz_get_raw(int(freq_hz), duration_s=2.0)
        if not raw:
            continue
        r = try_decode(raw)
        if not r or r["sensor_id"] in seen:
            continue
        seen[r["sensor_id"]] = r
        print(f"\n  Found: {r['sensor_id']}  {r['pressure_psi']:.1f} PSI  {r['temp_c']:.1f} C")

    if not seen:
        print("  No sensors found.")
        return

    print(f"\n  Found {len(seen)} sensor(s). Assign tire positions:")
    positions = ["FL (front-left)", "FR (front-right)", "RL (rear-left)", "RR (rear-right)",
                 "spare", "other"]

    for sid, r in seen.items():
        print(f"\n  Sensor: {sid}")
        for i, pos in enumerate(positions):
            print(f"    {i+1}. {pos}")
        try:
            choice = int(input("  Enter number (0 to skip): ").strip())
            if 1 <= choice <= len(positions):
                _known_sensors[sid] = {"id": sid, "position": positions[choice - 1]}
        except (ValueError, EOFError):
            pass

    # Save to JSON
    known_path = "tpms_known_sensors.json"
    with open(known_path, "w") as fh:
        json.dump(_known_sensors, fh, indent=2)
    print(f"\n  Saved {len(_known_sensors)} sensors -> {known_path}")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Decode TPMS tire pressure sensor broadcasts",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python tpms.py --freq 315 --duration 60
  python tpms.py --freq 433.92 --learn
  python tpms.py --freq 315 --alert 28 --duration 0
""",
    )
    parser.add_argument("--freq",     type=float, default=DEFAULT_FREQ_MHZ, metavar="MHZ",
                        help=f"Frequency MHz (default {DEFAULT_FREQ_MHZ})")
    parser.add_argument("--duration", type=float, default=DEFAULT_DURATION, metavar="S",
                        help=f"Duration seconds; 0=forever (default {DEFAULT_DURATION})")
    parser.add_argument("--db",       default=DEFAULT_DB, metavar="FILE",
                        help=f"SQLite DB (default {DEFAULT_DB})")
    parser.add_argument("--learn",    action="store_true",
                        help="Learn mode: capture sensor IDs and assign positions")
    parser.add_argument("--alert",    type=float, default=None, metavar="PSI",
                        help="SMS alert threshold in PSI")
    parser.add_argument("--serial",   default=DEFAULT_SERIAL, metavar="PORT",
                        help=f"Flipper serial port (default {DEFAULT_SERIAL})")

    args = parser.parse_args()

    # Load known sensors if file exists
    known_path = "tpms_known_sensors.json"
    if os.path.exists(known_path):
        with open(known_path) as fh:
            _known_sensors.update(json.load(fh))
        print(f"Loaded {len(_known_sensors)} known sensors from {known_path}")

    conn = open_db(args.db)

    try:
        print(f"Connecting to Flipper @ {args.serial} ...")
        fz = FlipperZero(args.serial)
        print(f"  {fz.identify()}")

        if args.learn:
            learn_mode(fz, args.freq * 1e6)
            return

        freq_hz = args.freq * 1e6
        t_start = time.time()
        print(f"\n[TPMS MONITOR @ {args.freq:.3f} MHz]")
        print(f"  {'Time':>10}  {'Sensor ID':>28}  {'Proto':>12}  "
              f"{'PSI':>6}  {'Temp C':>7}  {'Bat':>4}")
        print("  " + "-" * 74)

        while _running:
            elapsed = time.time() - t_start
            if args.duration > 0 and elapsed >= args.duration:
                break

            raw = fz.subghz_get_raw(int(freq_hz), duration_s=2.0)
            if not raw:
                continue
            r = try_decode(raw)
            if not r:
                continue

            # Enrich with known position
            if r["sensor_id"] in _known_sensors:
                r["position"] = _known_sensors[r["sensor_id"]].get("position", "")

            log_reading(conn, r)

            ts_short = datetime.now().strftime("%H:%M:%S")
            pos_str  = r.get("position", "")
            label    = f"{r['sensor_id']} {pos_str}"
            print(f"  {ts_short:>10}  {label:>28}  {r['protocol']:>12}  "
                  f"{r.get('pressure_psi', 0):>6.1f}  "
                  f"{r.get('temp_c', 0):>7.1f}  "
                  f"{'OK' if r.get('battery_ok') else 'LO':>4}")

            if args.alert and r.get("pressure_psi", 999) < args.alert:
                send_sms_alert(r["sensor_id"], r["pressure_psi"], args.alert)

    except KeyboardInterrupt:
        pass
    except Exception as exc:
        import traceback
        print(f"\nError: {exc}")
        traceback.print_exc()
    finally:
        conn.close()


if __name__ == "__main__":
    main()
