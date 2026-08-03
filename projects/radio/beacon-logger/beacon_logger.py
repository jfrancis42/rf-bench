#!/usr/bin/env python3
"""
VHF/UHF Beacon Logger

Tunes the IC-9700 to a fixed frequency and continuously logs S-meter
readings to SQLite.  Useful for:

  - Tracking tropospheric ducting events (2m or 70cm beacons)
  - Monitoring APRS, ISS downlink, or weak-signal propagation beacons
  - Logging satellite visibility windows (signal-present histogram)
  - Characterising long-term propagation paths to a known transmitter

GPS is optional.  Without GPS the output is a signal-strength time series;
with GPS it adds lat/lon/alt to each row for mobile/portable operation.

Usage:
    # Log W6YX 2m beacon at 144.283 MHz, 30-day run:
    python beacon_logger.py --freq 144283 --label "W6YX 2m" --duration 2592000

    # Log ISS APRS downlink with GPS, alert SMS when S9 or better:
    python beacon_logger.py --freq 145825 --label "ISS" --gps --alert-dbm -63

    # Monitor 70cm EME frequency, USB mode, 10-second interval:
    python beacon_logger.py --freq 432000 --mode usb --interval 10

    # View live data via HTTP:
    python beacon_logger.py --freq 144283 --http

Output:
    beacon_<label>_<timestamp>.db  — SQLite with one row per measurement
"""

import argparse
import json
import sqlite3
import sys
import threading
import time
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, HTTPServer

from rf_bench.icom import IC9700
from rf_bench import connect

DEFAULT_RIG_HOST  = "localhost"
DEFAULT_RIG_PORT  = 4532
DEFAULT_INTERVAL  = 5.0     # seconds between measurements
DEFAULT_HTTP_PORT = 8088


# ── SQLite helpers ────────────────────────────────────────────────────────────

def open_db(path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(path, check_same_thread=False)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS beacon (
            id          INTEGER PRIMARY KEY,
            ts_utc      TEXT    NOT NULL,
            ts_unix     REAL    NOT NULL,
            signal_dbm  REAL,
            lat         REAL,
            lon         REAL,
            alt_m       REAL,
            hdop        REAL,
            notes       TEXT
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_ts ON beacon (ts_unix)")
    conn.commit()
    return conn


def insert_row(conn, signal_dbm, gps_fix=None, notes=None):
    now = datetime.now(timezone.utc)
    lat = lon = alt_m = hdop = None
    if gps_fix and gps_fix.has_fix:
        lat   = gps_fix.latitude
        lon   = gps_fix.longitude
        alt_m = gps_fix.altitude_m
        hdop  = gps_fix.hdop
    conn.execute(
        "INSERT INTO beacon (ts_utc, ts_unix, signal_dbm, lat, lon, alt_m, hdop, notes) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (now.isoformat(), now.timestamp(), signal_dbm, lat, lon, alt_m, hdop, notes),
    )
    conn.commit()


# ── HTTP server ───────────────────────────────────────────────────────────────

_http_state: dict = {}


class _Handler(BaseHTTPRequestHandler):
    def log_message(self, *_):
        pass

    def do_GET(self):
        if self.path in ("/", "/data"):
            body = json.dumps(_http_state, indent=2).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        else:
            self.send_response(404)
            self.end_headers()


def _start_http(port: int):
    srv = HTTPServer(("", port), _Handler)
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    return srv


# ── SMS alert (via voip.ms proxy, same pattern as other projects) ─────────────

def _send_sms(message: str):
    try:
        import subprocess
        sms_script = __import__("pathlib").Path.home() / "Dropbox/build/money/sms.py"
        subprocess.run(["python3", str(sms_script), message], timeout=15)
    except Exception as e:
        print(f"  [SMS failed: {e}]")


# ── main logging loop ─────────────────────────────────────────────────────────

def run(args):
    label_safe = args.label.replace(" ", "_").replace("/", "-")
    ts_start   = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    db_path    = args.out or f"beacon_{label_safe}_{ts_start}.db"

    conn = open_db(db_path)
    print(f"Logging to {db_path}")

    # Optional GPS
    gps = None
    if args.gps:
        try:
            from rf_bench.gpsd import GPSD
            gps = GPSD()
            print("GPS connected.")
        except Exception as e:
            print(f"GPS unavailable ({e}); continuing without GPS.")

    # Optional HTTP
    if args.http:
        _start_http(args.http_port)
        print(f"HTTP live data at http://localhost:{args.http_port}/data")

    # Radio
    radio = IC9700(host=args.rig_host, port=args.rig_port)
    freq_hz = args.freq * 1000.0          # kHz → Hz
    radio.set_frequency(freq_hz)
    radio.set_mode(args.mode)
    radio.set_agc("slow")

    print(f"Monitoring {args.freq:.3f} kHz  mode={args.mode.upper()}")
    print(f"Interval {args.interval} s  label='{args.label}'")
    if args.alert_dbm is not None:
        print(f"Alert threshold: {args.alert_dbm:.1f} dBm")
    print("Press Ctrl-C to stop.\n")

    deadline     = time.monotonic() + args.duration if args.duration else None
    alert_sent   = False
    n            = 0
    peak_dbm     = -999.0
    sum_dbm      = 0.0

    try:
        while True:
            if deadline and time.monotonic() >= deadline:
                break

            signal_dbm = radio.get_strength_settled()
            gps_fix    = gps.get_fix() if gps else None
            insert_row(conn, signal_dbm, gps_fix)
            n += 1
            sum_dbm  += signal_dbm
            peak_dbm  = max(peak_dbm, signal_dbm)

            # Update HTTP state
            _http_state.update({
                "label":       args.label,
                "freq_khz":    args.freq,
                "mode":        args.mode,
                "signal_dbm":  round(signal_dbm, 1),
                "peak_dbm":    round(peak_dbm, 1),
                "mean_dbm":    round(sum_dbm / n, 1),
                "samples":     n,
                "timestamp":   datetime.now(timezone.utc).isoformat(),
                "lat":         gps_fix.latitude  if (gps_fix and gps_fix.has_fix) else None,
                "lon":         gps_fix.longitude if (gps_fix and gps_fix.has_fix) else None,
            })

            # Console
            gps_str = ""
            if gps_fix and gps_fix.has_fix:
                gps_str = f"  GPS {gps_fix.latitude:.5f},{gps_fix.longitude:.5f}"
            print(f"[{datetime.now().strftime('%H:%M:%S')}] "
                  f"{signal_dbm:+.1f} dBm  peak {peak_dbm:+.1f}  "
                  f"n={n}{gps_str}")

            # Alert
            if args.alert_dbm is not None and signal_dbm >= args.alert_dbm and not alert_sent:
                msg = (f"Beacon alert: {args.label} at {args.freq:.3f} kHz "
                       f"now {signal_dbm:.1f} dBm (≥ {args.alert_dbm:.1f} dBm threshold)")
                print(f"  >>> ALERT: {msg}")
                _send_sms(msg)
                alert_sent = True
            elif args.alert_dbm is not None and signal_dbm < args.alert_dbm:
                alert_sent = False   # re-arm when signal drops back

            time.sleep(args.interval)

    except KeyboardInterrupt:
        print("\nStopped.")
    finally:
        radio.close()
        if gps:
            gps.close()
        conn.close()

    # Summary
    if n:
        print(f"\n{'─'*40}")
        print(f"Samples : {n}")
        print(f"Peak    : {peak_dbm:+.1f} dBm")
        print(f"Mean    : {sum_dbm/n:+.1f} dBm")
        print(f"DB      : {db_path}")


# ── CLI ───────────────────────────────────────────────────────────────────────

def main():
    p = argparse.ArgumentParser(
        description="VHF/UHF beacon / propagation signal logger for IC-9700"
    )
    p.add_argument("--freq",       type=float, required=True,
                   help="Receive frequency in kHz (e.g. 144283 for 144.283 MHz)")
    p.add_argument("--mode",       default="usb",
                   choices=["usb","lsb","cw","cwr","fm","am","dv"],
                   help="Demodulation mode (default: usb)")
    p.add_argument("--label",      default="beacon",
                   help="Human-readable label for this beacon (used in filename and DB)")
    p.add_argument("--interval",   type=float, default=DEFAULT_INTERVAL,
                   help=f"Seconds between measurements (default {DEFAULT_INTERVAL})")
    p.add_argument("--duration",   type=float, default=None,
                   help="Total run time in seconds (default: run until Ctrl-C)")
    p.add_argument("--alert-dbm",  type=float, default=None, dest="alert_dbm",
                   help="Send SMS alert when signal reaches this level (dBm)")
    p.add_argument("--gps",        action="store_true",
                   help="Tag each reading with GPS position via gpsd")
    p.add_argument("--http",       action="store_true",
                   help="Serve live JSON at http://localhost:PORT/data")
    p.add_argument("--http-port",  type=int, default=DEFAULT_HTTP_PORT, dest="http_port",
                   help=f"HTTP server port (default {DEFAULT_HTTP_PORT})")
    p.add_argument("--out",        default=None,
                   help="Output SQLite file path (default: beacon_<label>_<ts>.db)")
    p.add_argument("--rig-host",   default=DEFAULT_RIG_HOST, dest="rig_host")
    p.add_argument("--rig-port",   type=int, default=DEFAULT_RIG_PORT, dest="rig_port")
    args = p.parse_args()
    run(args)


if __name__ == "__main__":
    main()
