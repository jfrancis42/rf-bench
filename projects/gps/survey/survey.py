#!/usr/bin/env python3
"""
GPS Position Precision Surveyor

Collects GPS fixes for a configurable duration and computes a best-estimate
position with 1-sigma uncertainty in metres.  Useful for establishing a
known reference point before antenna range or path-loss measurements.

Usage:
    python survey.py                        # 5-minute survey, localhost gpsd
    python survey.py --duration 3600        # 1-hour survey
    python survey.py --host 10.1.0.20       # remote gpsd
    python survey.py --out survey.csv       # save samples
    python survey.py --require-3d           # only accept 3D fixes
"""

import argparse
import csv
import math
import signal
import sys
import time

from rf_bench.gpsd import GPSD, GPSDNoFixError

_running = True


def _sigint(*_):
    global _running
    _running = False


signal.signal(signal.SIGINT, _sigint)


# ── math helpers ──────────────────────────────────────────────────────────────

def haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    R = 6_371_000.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def stdev(values: list) -> float:
    n = len(values)
    if n < 2:
        return 0.0
    mean = sum(values) / n
    return math.sqrt(sum((v - mean) ** 2 for v in values) / (n - 1))


# ── main ──────────────────────────────────────────────────────────────────────

def main() -> None:
    ap = argparse.ArgumentParser(
        description="GPS position precision surveyor — collects fixes and reports "
                    "best-estimate position with 1-sigma scatter."
    )
    ap.add_argument("--duration", type=float, default=300.0,
                    help="Survey duration in seconds (default: 300)")
    ap.add_argument("--interval", type=float, default=1.0,
                    help="Minimum sample interval in seconds (default: 1)")
    ap.add_argument("--host", default="localhost",
                    help="gpsd hostname (default: localhost)")
    ap.add_argument("--port", type=int, default=2947,
                    help="gpsd port (default: 2947)")
    ap.add_argument("--out", metavar="FILE",
                    help="Save raw samples to CSV file")
    ap.add_argument("--require-3d", action="store_true",
                    help="Only accept 3D fixes (with altitude)")
    args = ap.parse_args()

    print("GPS Position Precision Surveyor")
    print(f"  Duration : {args.duration:.0f} s")
    print(f"  Interval : {args.interval:.1f} s")
    print(f"  gpsd     : {args.host}:{args.port}")
    print()

    csv_file = None
    writer = None
    if args.out:
        csv_file = open(args.out, "w", newline="")
        writer = csv.writer(csv_file)
        writer.writerow([
            "time_utc", "lat_deg", "lon_deg", "alt_m",
            "hdop", "vdop", "pdop", "fix_mode",
            "sats_used", "sats_visible",
        ])

    samples = []

    try:
        with GPSD(host=args.host, port=args.port) as gps:
            print("Waiting for GPS fix …", end="", flush=True)
            try:
                gps.wait_for_fix(timeout=60, require_3d=args.require_3d)
                print(" OK")
            except GPSDNoFixError as exc:
                print(f"\nNo fix: {exc}", file=sys.stderr)
                sys.exit(1)

            deadline = time.monotonic() + args.duration
            last_sample = 0.0

            while _running and time.monotonic() < deadline:
                now = time.monotonic()
                if now - last_sample >= args.interval:
                    fix = gps.get_fix()
                    if fix.has_fix and (not args.require_3d or fix.has_3d_fix):
                        samples.append(fix)
                        if writer:
                            writer.writerow([
                                fix.time_utc, fix.latitude, fix.longitude,
                                fix.altitude_m, fix.hdop, fix.vdop, fix.pdop,
                                fix.fix_mode, fix.satellites_used,
                                fix.satellites_visible,
                            ])
                    elapsed = args.duration - (deadline - now)
                    pct = elapsed / args.duration * 100
                    print(
                        f"\r  [{pct:5.1f}%]  lat={fix.latitude:.6f}  "
                        f"lon={fix.longitude:.6f}  "
                        f"hdop={str(fix.hdop or '?'):5s}  "
                        f"sats={fix.satellites_used or '?'}  "
                        f"n={len(samples)}   ",
                        end="", flush=True,
                    )
                    last_sample = now
                time.sleep(0.1)

    finally:
        if csv_file:
            csv_file.close()

    print(f"\n\nSurvey complete — {len(samples)} fixes")

    if not samples:
        print("No valid fixes collected.", file=sys.stderr)
        sys.exit(1)

    lats = [s.latitude for s in samples]
    lons = [s.longitude for s in samples]
    alts = [s.altitude_m for s in samples if s.altitude_m is not None]
    hdops = [s.hdop for s in samples if s.hdop is not None]
    vdops = [s.vdop for s in samples if s.vdop is not None]

    mean_lat = sum(lats) / len(lats)
    mean_lon = sum(lons) / len(lons)
    mean_alt = sum(alts) / len(alts) if alts else None
    mean_hdop = sum(hdops) / len(hdops) if hdops else None
    mean_vdop = sum(vdops) / len(vdops) if vdops else None

    # Convert position scatter to metres using haversine N/E decomposition
    north_m = [
        haversine_m(mean_lat, mean_lon, lat, mean_lon) * (1 if lat >= mean_lat else -1)
        for lat in lats
    ]
    east_m = [
        haversine_m(mean_lat, mean_lon, mean_lat, lon) * (1 if lon >= mean_lon else -1)
        for lon in lons
    ]

    sigma_n = stdev(north_m)
    sigma_e = stdev(east_m)
    sigma_2d = math.sqrt(sigma_n ** 2 + sigma_e ** 2)
    sigma_alt = stdev([a - mean_alt for a in alts]) if len(alts) >= 2 else None

    max_n = max(abs(v) for v in north_m)
    max_e = max(abs(v) for v in east_m)

    print("=" * 54)
    print("Best-estimate position:")
    print(f"  Latitude   : {mean_lat:.7f}°")
    print(f"  Longitude  : {mean_lon:.7f}°")
    if mean_alt is not None:
        print(f"  Altitude   : {mean_alt:.2f} m  ({mean_alt * 3.28084:.1f} ft) MSL")
    print()
    print("Position scatter (1σ, N samples - 1):")
    print(f"  North      : ±{sigma_n:.2f} m  (max {max_n:.2f} m)")
    print(f"  East       : ±{sigma_e:.2f} m  (max {max_e:.2f} m)")
    print(f"  2D CEP     : ±{sigma_2d:.2f} m")
    if sigma_alt is not None:
        print(f"  Vertical   : ±{sigma_alt:.2f} m")
    print()
    if mean_hdop is not None:
        print(f"Mean HDOP   : {mean_hdop:.2f}")
    if mean_vdop is not None:
        print(f"Mean VDOP   : {mean_vdop:.2f}")
    print(f"Fixes used  : {len(samples)}")
    if args.out:
        print(f"Saved to    : {args.out}")
    print("=" * 54)


if __name__ == "__main__":
    main()
