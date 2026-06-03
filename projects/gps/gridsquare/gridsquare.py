#!/usr/bin/env python3
"""
Maidenhead Grid Square Calculator

Continuously displays the Maidenhead grid locator for the current GPS
position at 4, 6, and 8 character precision.  Optionally shows distance
and bearing to a list of stored waypoints (repeaters, SOTA summits, etc.).

Usage:
    python gridsquare.py
    python gridsquare.py --host 10.1.0.20
    python gridsquare.py --waypoints waypoints.csv
    python gridsquare.py --precision 6     # stop at 6-char locator

Waypoints CSV format (no header row):
    name,lat_deg,lon_deg
    W0CO-R,39.7392,-104.9903
    W1AW,41.7148,-72.7272
"""

import argparse
import csv
import math
import signal
import sys
import time
from pathlib import Path

from rf_bench.gpsd import GPSD, GPSDNoFixError

_running = True


def _sigint(*_):
    global _running
    _running = False


signal.signal(signal.SIGINT, _sigint)


# ── Maidenhead ─────────────────────────────────────────────────────────────────

def maidenhead(lat: float, lon: float, precision: int = 6) -> str:
    """
    Convert decimal-degree coordinates to a Maidenhead grid locator.

    Args:
        lat:       Latitude in decimal degrees (−90 to +90).
        lon:       Longitude in decimal degrees (−180 to +180).
        precision: 4 (field+square), 6 (+subsquare), or 8 (+extended).

    Returns:
        Grid locator string, e.g. ``'DM79mr'``.
    """
    precision = max(4, min(8, (precision // 2) * 2))

    lo = lon + 180.0  # 0–360
    la = lat + 90.0   # 0–180

    result = []

    # Field (letters A–R)
    result.append(chr(ord("A") + int(lo / 20)))
    result.append(chr(ord("A") + int(la / 10)))
    lo %= 20
    la %= 10

    # Square (digits 0–9)
    result.append(str(int(lo / 2)))
    result.append(str(int(la)))
    lo = (lo % 2) * 12  # scale remainder to 0–24
    la = (la % 1) * 24

    if precision >= 6:
        # Subsquare (letters a–x)
        result.append(chr(ord("a") + int(lo)))
        result.append(chr(ord("a") + int(la)))
        lo = (lo % 1) * 10
        la = (la % 1) * 10

    if precision >= 8:
        # Extended (digits 0–9)
        result.append(str(int(lo)))
        result.append(str(int(la)))

    return "".join(result[:precision])


# ── navigation helpers ────────────────────────────────────────────────────────

def haversine_km(lat1: float, lon1: float,
                 lat2: float, lon2: float) -> float:
    R = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def bearing_deg(lat1: float, lon1: float,
                lat2: float, lon2: float) -> float:
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dl = math.radians(lon2 - lon1)
    x = math.sin(dl) * math.cos(p2)
    y = math.cos(p1) * math.sin(p2) - math.sin(p1) * math.cos(p2) * math.cos(dl)
    return (math.degrees(math.atan2(x, y)) + 360) % 360


def compass(bearing: float) -> str:
    dirs = ["N", "NNE", "NE", "ENE", "E", "ESE", "SE", "SSE",
            "S", "SSW", "SW", "WSW", "W", "WNW", "NW", "NNW"]
    return dirs[round(bearing / 22.5) % 16]


# ── waypoint loading ──────────────────────────────────────────────────────────

def load_waypoints(path: str) -> list:
    waypoints = []
    with open(path, newline="") as fh:
        for row in csv.reader(fh):
            if len(row) >= 3:
                try:
                    waypoints.append((row[0].strip(), float(row[1]), float(row[2])))
                except ValueError:
                    pass
    return waypoints


# ── display ───────────────────────────────────────────────────────────────────

FIX_LABELS = {0: "UNKNOWN", 1: "NO FIX", 2: "2D FIX", 3: "3D FIX"}


def render(fix, waypoints: list, precision: int) -> None:
    print("\033[2J\033[H", end="")  # clear screen

    if not fix.has_fix:
        mode_str = FIX_LABELS.get(fix.fix_mode, str(fix.fix_mode))
        print(f"  Fix status : {mode_str}")
        print(f"  Satellites : {fix.satellites_used or '?'} used / "
              f"{fix.satellites_visible or '?'} visible")
        return

    grid4 = maidenhead(fix.latitude, fix.longitude, 4)
    grid6 = maidenhead(fix.latitude, fix.longitude, 6)
    grid8 = maidenhead(fix.latitude, fix.longitude, 8)

    print(f"  Grid  4    : {grid4}")
    if precision >= 6:
        print(f"  Grid  6    : {grid6}")
    if precision >= 8:
        print(f"  Grid  8    : {grid8}")
    print()
    print(f"  Latitude   : {fix.latitude:+.6f}°")
    print(f"  Longitude  : {fix.longitude:+.6f}°")
    if fix.altitude_m is not None:
        print(f"  Altitude   : {fix.altitude_m:.1f} m  ({fix.altitude_ft:.0f} ft)")
    if fix.speed_ms is not None and fix.speed_ms > 0.5:
        print(f"  Speed      : {fix.speed_kmh:.1f} km/h  ({fix.speed_mph:.1f} mph)")
    if fix.heading is not None:
        print(f"  Heading    : {fix.heading:.0f}°  ({compass(fix.heading)})")
    print()
    mode_str = FIX_LABELS.get(fix.fix_mode, str(fix.fix_mode))
    print(f"  Fix        : {mode_str}  "
          f"sats={fix.satellites_used or '?'}/{fix.satellites_visible or '?'}  "
          f"HDOP={fix.hdop or '?'}  VDOP={fix.vdop or '?'}")
    if fix.time_utc:
        print(f"  Time UTC   : {fix.time_utc}")

    if waypoints:
        print()
        print(f"  {'Waypoint':<20s}  {'Grid':8s}  {'Distance':>10s}  {'Bearing':>8s}")
        print(f"  {'-'*20}  {'-'*8}  {'-'*10}  {'-'*8}")
        for name, wlat, wlon in waypoints:
            dist_km = haversine_km(fix.latitude, fix.longitude, wlat, wlon)
            brg = bearing_deg(fix.latitude, fix.longitude, wlat, wlon)
            wgrid = maidenhead(wlat, wlon, min(precision, 6))
            if dist_km >= 1000:
                dist_str = f"{dist_km/1000:.0f} Mm"
            elif dist_km >= 1:
                dist_str = f"{dist_km:.1f} km"
            else:
                dist_str = f"{dist_km*1000:.0f} m"
            print(f"  {name:<20s}  {wgrid:8s}  {dist_str:>10s}  "
                  f"{brg:5.1f}° {compass(brg)}")


# ── main ──────────────────────────────────────────────────────────────────────

def main() -> None:
    ap = argparse.ArgumentParser(
        description="Maidenhead grid square display from live GPS"
    )
    ap.add_argument("--host", default="localhost",
                    help="gpsd hostname (default: localhost)")
    ap.add_argument("--port", type=int, default=2947,
                    help="gpsd port (default: 2947)")
    ap.add_argument("--precision", type=int, choices=[4, 6, 8], default=6,
                    help="Grid locator precision in characters (default: 6)")
    ap.add_argument("--interval", type=float, default=2.0,
                    help="Display refresh interval in seconds (default: 2)")
    ap.add_argument("--waypoints", metavar="FILE",
                    help="CSV file of waypoints: name,lat,lon")
    args = ap.parse_args()

    waypoints = []
    if args.waypoints:
        try:
            waypoints = load_waypoints(args.waypoints)
            print(f"Loaded {len(waypoints)} waypoint(s) from {args.waypoints}")
        except Exception as exc:
            print(f"Warning: could not load waypoints: {exc}", file=sys.stderr)

    with GPSD(host=args.host, port=args.port) as gps:
        print("Waiting for GPS fix …")
        last_render = 0.0
        while _running:
            now = time.monotonic()
            if now - last_render >= args.interval:
                fix = gps.get_fix()
                render(fix, waypoints, args.precision)
                last_render = now
            time.sleep(0.2)

    print()


if __name__ == "__main__":
    main()
