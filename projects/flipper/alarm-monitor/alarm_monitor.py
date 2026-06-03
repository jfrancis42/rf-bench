#!/usr/bin/env python3
"""
Flipper Zero EV1527/PT2262 Wireless Alarm Monitor

Decodes EV1527/PT2262 fixed-code wireless alarm sensors (door/window/PIR)
at 433 MHz. Named sensor registry in JSON. Logs trigger events to SQLite.
Prints alert on trigger with sensor name. HTTP webhook on trigger if
--webhook URL is given.

Usage:
  python alarm_monitor.py --registry sensors.json
  python alarm_monitor.py --freq 433.92 --webhook http://homeassistant:8123/api/webhook/alarm
  python alarm_monitor.py --duration 0
"""

import argparse
import json
import os
import signal
import sqlite3
import sys
import time
import urllib.request
from datetime import datetime

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                '..', 'rf-bench'))
from rf_bench.flipper import FlipperZero

# ---------------------------------------------------------------------------
# Defaults
# ---------------------------------------------------------------------------
DEFAULT_FREQ_MHZ  = 433.92
DEFAULT_DB        = "alarm_events.db"
DEFAULT_REGISTRY  = "sensors.json"
DEFAULT_SERIAL    = "/dev/ttyACM0"
DEFAULT_DURATION  = 0   # forever

_running = True


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
        CREATE TABLE IF NOT EXISTS events (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            ts          TEXT NOT NULL,
            code        TEXT NOT NULL,
            sensor_name TEXT,
            event_type  TEXT,
            raw_bits    TEXT
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_ts ON events(ts)")
    conn.commit()
    return conn


def log_event(conn: sqlite3.Connection, code: str, sensor_name: str,
              event_type: str, raw_bits: str) -> None:
    conn.execute(
        "INSERT INTO events(ts,code,sensor_name,event_type,raw_bits) VALUES(?,?,?,?,?)",
        (datetime.now().isoformat(), code, sensor_name, event_type, raw_bits),
    )
    conn.commit()


# ---------------------------------------------------------------------------
# Sensor registry
# ---------------------------------------------------------------------------

def load_registry(path: str) -> dict:
    """
    Registry format:
    {"sensors": {"CODE24BIT": {"name": "Front Door", "type": "door"}}}
    """
    if os.path.exists(path):
        with open(path) as fh:
            return json.load(fh)
    # Create skeleton
    return {
        "sensors": {},
        "_note": "Add sensors: {\"CODE24BIT\": {\"name\": \"Front Door\", \"type\": \"door\"}}"
    }


def save_registry(reg: dict, path: str) -> None:
    with open(path, "w") as fh:
        json.dump(reg, fh, indent=2)


# ---------------------------------------------------------------------------
# Decoder
# ---------------------------------------------------------------------------

def decode_ev1527(raw: str) -> dict | None:
    """
    EV1527/PT2262: 24-bit fixed OOK code.
    [ID:20][DATA:4]  -- first 20 bits are address, last 4 are data/button bits.
    Returns {code, address, data, raw_bits} or None.
    """
    bits = []
    for line in raw.splitlines():
        line = line.strip()
        if line.startswith("Code:"):
            code_str = line.split(":", 1)[1].strip()
            # Flipper may report as decimal or hex
            try:
                if code_str.startswith("0x") or code_str.startswith("0X"):
                    val = int(code_str, 16)
                else:
                    val = int(code_str)
                # 24-bit code
                bits = [(val >> (23 - i)) & 1 for i in range(24)]
            except ValueError:
                pass
            break
        if line.startswith("Data:"):
            data_str = line.split(":", 1)[1].strip().replace(" ", "")
            try:
                val = int(data_str, 16)
                n = len(data_str) * 4
                bits = [(val >> (n - 1 - i)) & 1 for i in range(min(n, 24))]
            except ValueError:
                if all(c in "01" for c in data_str):
                    bits = [int(b) for b in data_str[:24]]
            break

    if len(bits) < 24:
        return None

    address_bits = bits[:20]
    data_bits    = bits[20:24]
    address      = sum(address_bits[i] << (19 - i) for i in range(20))
    data         = sum(data_bits[i] << (3 - i) for i in range(4))
    code         = f"{address:05X}{data:01X}"

    return {
        "code":     code,
        "address":  address,
        "data":     data,
        "raw_bits": "".join(str(b) for b in bits[:24]),
    }


# ---------------------------------------------------------------------------
# Webhook
# ---------------------------------------------------------------------------

def send_webhook(url: str, payload: dict) -> None:
    body = json.dumps(payload).encode()
    req  = urllib.request.Request(url, data=body,
                                   headers={"Content-Type": "application/json"},
                                   method="POST")
    try:
        with urllib.request.urlopen(req, timeout=5) as resp:
            _ = resp.read()
    except Exception as exc:
        print(f"  Webhook failed: {exc}")


# ---------------------------------------------------------------------------
# Monitor loop
# ---------------------------------------------------------------------------

def monitor_loop(fz: FlipperZero, conn: sqlite3.Connection, reg: dict,
                 freq_hz: float, duration_s: float, webhook_url: str | None) -> None:
    t_start = time.time()
    sensors = reg.get("sensors", {})
    print(f"\n[MONITORING @ {freq_hz/1e6:.4f} MHz]  {len(sensors)} sensors registered  "
          f"duration={'forever' if duration_s == 0 else f'{duration_s:.0f}s'}")
    print(f"  {'Time':>10}  {'Code':>8}  {'Sensor Name':>24}  {'Type':>10}  {'Data':>4}")
    print("  " + "-" * 62)

    while _running:
        elapsed = time.time() - t_start
        if duration_s > 0 and elapsed >= duration_s:
            break

        raw = fz.subghz_get_raw(int(freq_hz), duration_s=2.0)
        if not raw:
            continue

        decoded = decode_ev1527(raw)
        if not decoded:
            continue

        code        = decoded["code"]
        sensor_info = sensors.get(code, {})
        name        = sensor_info.get("name", "Unknown")
        event_type  = sensor_info.get("type", "unknown")
        is_known    = code in sensors

        log_event(conn, code, name, event_type, decoded["raw_bits"])

        ts_short = datetime.now().strftime("%H:%M:%S")
        alert_mark = "*** " if is_known else "    "
        print(f"  {ts_short:>10}  {code:>8}  {name:>24}  "
              f"{event_type:>10}  {decoded['data']:>4X}  {alert_mark}")

        if is_known and webhook_url:
            payload = {
                "ts":         datetime.now().isoformat(),
                "code":       code,
                "sensor":     name,
                "event_type": event_type,
                "data":       decoded["data"],
            }
            send_webhook(webhook_url, payload)

        # Auto-register new sensors
        if not is_known:
            sensors[code] = {"name": f"Sensor_{code}", "type": "unknown"}
            save_registry(reg, DEFAULT_REGISTRY)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Monitor EV1527/PT2262 wireless alarm sensors",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python alarm_monitor.py
  python alarm_monitor.py --webhook http://ha:8123/api/webhook/alarm
  python alarm_monitor.py --registry my_sensors.json --duration 0
""",
    )
    parser.add_argument("--freq",     type=float, default=DEFAULT_FREQ_MHZ, metavar="MHZ",
                        help=f"Frequency MHz (default {DEFAULT_FREQ_MHZ})")
    parser.add_argument("--db",       default=DEFAULT_DB, metavar="FILE",
                        help=f"SQLite DB (default {DEFAULT_DB})")
    parser.add_argument("--registry", default=DEFAULT_REGISTRY, metavar="FILE",
                        help=f"Sensor registry JSON (default {DEFAULT_REGISTRY})")
    parser.add_argument("--webhook",  default=None, metavar="URL",
                        help="HTTP webhook URL for trigger events")
    parser.add_argument("--duration", type=float, default=DEFAULT_DURATION, metavar="S",
                        help="Run duration; 0=forever (default 0)")
    parser.add_argument("--serial",   default=DEFAULT_SERIAL, metavar="PORT",
                        help=f"Flipper serial port (default {DEFAULT_SERIAL})")

    args = parser.parse_args()

    reg  = load_registry(args.registry)
    conn = open_db(args.db)
    print(f"Registry: {args.registry}  ({len(reg.get('sensors', {}))} sensors)")
    print(f"Database: {args.db}")

    try:
        print(f"Connecting to Flipper @ {args.serial} ...")
        fz = FlipperZero(args.serial)
        print(f"  {fz.identify()}")
        monitor_loop(fz, conn, reg, args.freq * 1e6, args.duration, args.webhook)
    except KeyboardInterrupt:
        pass
    except Exception as exc:
        import traceback
        print(f"\nError: {exc}")
        traceback.print_exc()
    finally:
        save_registry(reg, args.registry)
        conn.close()


if __name__ == "__main__":
    main()
