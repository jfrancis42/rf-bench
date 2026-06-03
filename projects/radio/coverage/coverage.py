#!/usr/bin/env python3
"""
HF/VHF Signal Strength Coverage Mapper

Logs the S-meter reading from an IC-7300 or FT-891 vs time, optionally
geo-tagged with GPS coordinates.  Useful for:

  - Measuring a repeater's coverage area (drive/walk a route)
  - Mapping the horizontal radiation pattern of an antenna (drive a circle
    around the transmitter, plot signal strength vs azimuth)
  - Finding propagation paths or dead zones

GPS is optional.  Without GPS the output is a signal-strength time series
suitable for stationary monitoring; with GPS it produces a CSV and GPX
that can be overlaid on a map.

Usage:
    python coverage.py --freq 146520 --gps
    python coverage.py --freq 144174 --radio ic9700 --gps --out vhf_map
    python coverage.py --freq 14200 --radio ft891 --gps --out hf_map
    python coverage.py --freq 146520 --gps --duration 3600
    python coverage.py --freq 146520              # no GPS, time series only

Output files (<stem> defaults to 'coverage'):
    <stem>_<timestamp>.csv    — timestamp, lat, lon, S-meter dB, mode
    <stem>_<timestamp>.gpx    — GPX track with signal extension (GPS only)
"""

import argparse
import csv
import math
import signal
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from rf_bench.icom import IC7300, IC9700
from rf_bench.yaesu import FT891

try:
    from rf_bench.gpsd import GPSD, GPSDNoFixError
    _HAS_GPSD = True
except ImportError:
    _HAS_GPSD = False

_running = True


def _sigint(*_):
    global _running
    _running = False


signal.signal(signal.SIGINT, _sigint)

RIGCTLD_HOST = "localhost"
RIGCTLD_PORT = 4532


# ── GPX writer (shared with drivetest) ───────────────────────────────────────

GPX_HEADER = """\
<?xml version="1.0" encoding="UTF-8"?>
<gpx version="1.1" creator="rf-bench-coverage"
     xmlns="http://www.topografix.com/GPX/1/1"
     xmlns:rf="http://rf-bench.local/gpx-extensions">
  <trk>
    <name>{name}</name>
    <trkseg>
"""
GPX_TRKPT = """\
      <trkpt lat="{lat:.6f}" lon="{lon:.6f}">
        <ele>{alt:.1f}</ele>
        <time>{time}</time>
        <extensions>
          <rf:smeter_db>{smeter:.2f}</rf:smeter_db>
        </extensions>
      </trkpt>
"""
GPX_FOOTER = "    </trkseg>\n  </trk>\n</gpx>\n"


class GPXWriter:
    def __init__(self, path: Path, name: str) -> None:
        self._fh = open(path, "w")
        self._fh.write(GPX_HEADER.format(name=name))

    def write_point(self, lat: float, lon: float, alt: float,
                    iso_time: str, smeter_db: float) -> None:
        self._fh.write(GPX_TRKPT.format(
            lat=lat, lon=lon, alt=alt or 0.0,
            time=iso_time, smeter=smeter_db,
        ))
        self._fh.flush()

    def close(self) -> None:
        self._fh.write(GPX_FOOTER)
        self._fh.close()


# ── main ──────────────────────────────────────────────────────────────────────

def main() -> None:
    ap = argparse.ArgumentParser(
        description="IC-7300/FT-891 signal strength coverage mapper with optional GPS"
    )
    ap.add_argument("--freq", type=float, required=True,
                    help="Receive frequency in kHz (e.g. 146520 = 146.520 MHz)")
    ap.add_argument("--mode", default="FM",
                    help="Receive mode: USB, LSB, CW, FM, AM (default: FM)")
    ap.add_argument("--radio", choices=["ic7300", "ic9700", "ft891"], default="ic7300",
                    help="Radio model (default: ic7300)")
    ap.add_argument("--rigctld-host", default=RIGCTLD_HOST,
                    help=f"rigctld hostname (default: {RIGCTLD_HOST})")
    ap.add_argument("--rigctld-port", type=int, default=RIGCTLD_PORT,
                    help=f"rigctld port (default: {RIGCTLD_PORT})")
    ap.add_argument("--interval", type=float, default=1.0,
                    help="Measurement interval in seconds (default: 1)")
    ap.add_argument("--settle", type=float, default=0.5,
                    help="Settle time after tuning in seconds (default: 0.5)")
    ap.add_argument("--duration", type=float, default=0.0,
                    help="Run duration in seconds (0 = until Ctrl-C)")
    ap.add_argument("--out", default="coverage",
                    help="Output file stem (default: coverage)")
    ap.add_argument("--gps", action="store_true",
                    help="Enable GPS geo-tagging via gpsd")
    ap.add_argument("--gps-host", default="localhost",
                    help="gpsd hostname (default: localhost)")
    ap.add_argument("--gps-port", type=int, default=2947,
                    help="gpsd port (default: 2947)")
    ap.add_argument("--gps-wait", type=float, default=30.0,
                    help="Max seconds to wait for GPS fix at startup (default: 30)")
    args = ap.parse_args()

    # GPS setup
    gps = None
    if args.gps:
        if not _HAS_GPSD:
            print("Warning: rf-bench-drivers-gpsd not installed; --gps ignored.",
                  file=sys.stderr)
        else:
            gps = GPSD(host=args.gps_host, port=args.gps_port)
            print(f"Waiting for GPS fix (up to {args.gps_wait:.0f}s) …",
                  end="", flush=True)
            try:
                gps.wait_for_fix(timeout=args.gps_wait)
                print(" OK")
            except GPSDNoFixError:
                print(" (no fix — GPS columns will be blank)")

    # Radio setup
    print(f"Connecting to {args.radio} via rigctld {args.rigctld_host}:{args.rigctld_port} …",
          end="", flush=True)
    try:
        if args.radio == "ft891":
            radio = FT891(host=args.rigctld_host, port=args.rigctld_port)
        elif args.radio == "ic9700":
            radio = IC9700(host=args.rigctld_host, port=args.rigctld_port)
        else:
            radio = IC7300(host=args.rigctld_host, port=args.rigctld_port)
        print(" OK")
    except Exception as exc:
        print(f"\nFailed to connect to radio: {exc}", file=sys.stderr)
        if gps:
            gps.close()
        sys.exit(1)

    radio.set_frequency(args.freq)
    radio.set_mode(args.mode)
    time.sleep(args.settle)

    ts_start = datetime.now(tz=timezone.utc).strftime("%Y%m%d_%H%M%S")
    csv_path = Path(f"{args.out}_{ts_start}.csv")
    gpx_path = Path(f"{args.out}_{ts_start}.gpx") if gps else None

    print(f"\nCoverage mapper: {args.freq:.1f} kHz {args.mode}  "
          f"radio={args.radio}  GPS={'on' if gps else 'off'}")
    print(f"CSV: {csv_path}")
    if gpx_path:
        print(f"GPX: {gpx_path}")
    print()

    gpx = GPXWriter(gpx_path, f"coverage {args.freq:.1f} kHz") if gpx_path else None
    deadline = time.monotonic() + args.duration if args.duration > 0 else float("inf")
    n = 0
    last_meas = 0.0

    try:
        with open(csv_path, "w", newline="") as csv_file:
            writer = csv.writer(csv_file)
            writer.writerow([
                "timestamp_utc", "epoch_s",
                "lat_deg", "lon_deg", "alt_m",
                "gps_fix_mode", "gps_speed_kmh", "gps_heading_deg",
                "freq_khz", "mode", "smeter_db",
            ])

            while _running and time.monotonic() < deadline:
                now = time.monotonic()
                if now - last_meas >= args.interval:
                    try:
                        smeter_db = radio.get_strength_settled()
                    except Exception as exc:
                        print(f"\nRadio read error: {exc}", file=sys.stderr)
                        break

                    ts = datetime.now(tz=timezone.utc).isoformat()
                    epoch_s = time.time()

                    lat = lon = alt = fix_mode = speed = heading = None
                    if gps:
                        fix = gps.get_fix()
                        if fix.has_fix:
                            lat, lon = fix.latitude, fix.longitude
                            alt = fix.altitude_m
                            fix_mode = fix.fix_mode
                            speed = fix.speed_kmh
                            heading = fix.heading

                    writer.writerow([
                        ts, f"{epoch_s:.3f}",
                        f"{lat:.6f}" if lat else "",
                        f"{lon:.6f}" if lon else "",
                        f"{alt:.1f}" if alt is not None else "",
                        fix_mode or "",
                        f"{speed:.1f}" if speed is not None else "",
                        f"{heading:.1f}" if heading is not None else "",
                        f"{args.freq:.1f}",
                        args.mode,
                        f"{smeter_db:.2f}",
                    ])
                    csv_file.flush()

                    if gpx and lat:
                        gpx.write_point(lat, lon, alt or 0.0, ts, smeter_db)

                    n += 1
                    loc_str = (f"{lat:.5f},{lon:.5f}" if lat else "no GPS    ")
                    print(
                        f"\r  {ts[11:19]}  "
                        f"S={smeter_db:+7.1f} dB  "
                        f"loc={loc_str}  n={n}",
                        end="", flush=True,
                    )
                    last_meas = now
                time.sleep(0.05)

    finally:
        radio.close()
        if gpx:
            gpx.close()
        if gps:
            gps.close()

    print(f"\n\nDone — {n} samples.  CSV: {csv_path}")
    if gpx_path:
        print(f"GPX: {gpx_path}")


if __name__ == "__main__":
    main()
