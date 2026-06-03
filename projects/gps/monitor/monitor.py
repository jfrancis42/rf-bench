#!/usr/bin/env python3
"""
GPS Fix Quality Monitor

Real-time terminal display of GPS fix quality: mode, satellite count,
dilution of precision, position, speed, heading, error estimates, and
a live scatter plot of recent position deviations in metres.

Usage:
    python monitor.py
    python monitor.py --host 10.1.0.20
    python monitor.py --history 120     # keep 120 s of scatter history
"""

import argparse
import collections
import math
import signal
import sys
import time

from rf_bench.gpsd import GPSD, FIX_2D, FIX_3D

_running = True


def _sigint(*_):
    global _running
    _running = False


signal.signal(signal.SIGINT, _sigint)


# ── helpers ───────────────────────────────────────────────────────────────────

def haversine_m(lat1: float, lon1: float,
                lat2: float, lon2: float) -> float:
    R = 6_371_000.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def dop_bar(dop, width: int = 12) -> str:
    """Horizontal bar: green below 2, yellow 2–5, red above 5."""
    if dop is None:
        return "─" * width + "  ?"
    filled = min(width, int(dop / 10 * width))
    bar = "█" * filled + "░" * (width - filled)
    return f"{bar}  {dop:.1f}"


def stdev(values: list) -> float:
    n = len(values)
    if n < 2:
        return 0.0
    m = sum(values) / n
    return math.sqrt(sum((v - m) ** 2 for v in values) / (n - 1))


FIX_LABELS = {0: "UNKNOWN ", 1: "NO FIX  ", 2: "2D FIX  ", 3: "3D FIX  "}
COMPASS = ["N", "NNE", "NE", "ENE", "E", "ESE", "SE", "SSE",
           "S", "SSW", "SW", "WSW", "W", "WNW", "NW", "NNW"]


def compass(b: float) -> str:
    return COMPASS[round(b / 22.5) % 16]


# ── ASCII scatter plot ────────────────────────────────────────────────────────

def scatter_plot(north_m: list, east_m: list,
                 cols: int = 41, rows: int = 13) -> list:
    """
    Return a list of strings forming a north-up scatter grid.
    Origin (0,0) is the mean position; axes are in metres.
    """
    if not north_m:
        return [" " * cols] * rows

    all_vals = north_m + east_m
    span = max(abs(v) for v in all_vals) or 1.0
    scale = span * 1.1  # 10% padding

    grid = [["·"] * cols for _ in range(rows)]

    # Axes
    cx, cy = cols // 2, rows // 2
    for c in range(cols):
        grid[cy][c] = "─"
    for r in range(rows):
        grid[r][cx] = "│"
    grid[cy][cx] = "┼"

    # Points
    for n, e in zip(north_m, east_m):
        col = int((e / scale + 1) / 2 * (cols - 1))
        row = int((1 - n / scale) / 2 * (rows - 1))
        col = max(0, min(cols - 1, col))
        row = max(0, min(rows - 1, row))
        grid[row][col] = "+"

    # Latest point
    if north_m:
        e, n = east_m[-1], north_m[-1]
        col = int((e / scale + 1) / 2 * (cols - 1))
        row = int((1 - n / scale) / 2 * (rows - 1))
        col = max(0, min(cols - 1, col))
        row = max(0, min(rows - 1, row))
        grid[row][col] = "●"

    lines = ["".join(row) for row in grid]
    # Labels
    lbl = f"{scale:.1f}m"
    lines[0] = f"N+{lbl:<{cols-3}}"
    lines[-1] = f"S-{lbl:<{cols-3}}"
    return lines


# ── render ────────────────────────────────────────────────────────────────────

def render(fix, gps, connected: bool, stale: bool,
           north_hist: list, east_hist: list) -> None:
    print("\033[2J\033[H", end="")  # clear screen, home cursor

    # Status bar
    conn_str = "CONNECTED" if connected else "DISCONNECTED"
    stale_str = " STALE" if stale else ""
    print(f"  GPS Fix Quality Monitor          [{conn_str}{stale_str}]")
    print(f"  {'─'*52}")

    mode_str = FIX_LABELS.get(fix.fix_mode, f"MODE {fix.fix_mode}")
    print(f"  Fix mode   : {mode_str}    "
          f"Sats: {fix.satellites_used or '?'} used / "
          f"{fix.satellites_visible or '?'} visible")
    if fix.time_utc:
        print(f"  Time UTC   : {fix.time_utc}")
    print()

    # Position
    if fix.has_fix:
        print(f"  Latitude   : {fix.latitude:+.6f}°   "
              f"(±{fix.error_lat_m:.1f} m)" if fix.error_lat_m else
              f"  Latitude   : {fix.latitude:+.6f}°")
        print(f"  Longitude  : {fix.longitude:+.6f}°   "
              f"(±{fix.error_lon_m:.1f} m)" if fix.error_lon_m else
              f"  Longitude  : {fix.longitude:+.6f}°")
        if fix.altitude_m is not None:
            alt_err = f"  (±{fix.error_alt_m:.1f} m)" if fix.error_alt_m else ""
            print(f"  Altitude   : {fix.altitude_m:.2f} m  "
                  f"({fix.altitude_ft:.0f} ft){alt_err}")
        if fix.speed_ms is not None:
            print(f"  Speed      : {fix.speed_kmh:.1f} km/h  "
                  f"({fix.speed_knots:.1f} kn  {fix.speed_mph:.1f} mph)")
        if fix.heading is not None:
            print(f"  Heading    : {fix.heading:.1f}°  ({compass(fix.heading)})")
    else:
        print(f"  (awaiting fix)")
    print()

    # DOP bars
    print(f"  HDOP  {dop_bar(fix.hdop)}")
    print(f"  VDOP  {dop_bar(fix.vdop)}")
    print(f"  PDOP  {dop_bar(fix.pdop)}")
    print()

    # Scatter stats + plot side by side
    if len(north_hist) >= 2:
        sn = stdev(list(north_hist))
        se = stdev(list(east_hist))
        s2d = math.sqrt(sn ** 2 + se ** 2)
        print(f"  Scatter (1σ, last {len(north_hist)} fixes):"
              f"  N ±{sn:.2f} m  E ±{se:.2f} m  2D ±{s2d:.2f} m")

    if north_hist:
        plot_lines = scatter_plot(list(north_hist), list(east_hist))
        for line in plot_lines:
            print(f"  {line}")

    print()
    print("  Ctrl-C to exit")


# ── main ──────────────────────────────────────────────────────────────────────

def main() -> None:
    ap = argparse.ArgumentParser(
        description="Real-time GPS fix quality monitor"
    )
    ap.add_argument("--host", default="localhost",
                    help="gpsd hostname (default: localhost)")
    ap.add_argument("--port", type=int, default=2947,
                    help="gpsd port (default: 2947)")
    ap.add_argument("--interval", type=float, default=1.0,
                    help="Display refresh interval in seconds (default: 1)")
    ap.add_argument("--history", type=int, default=60,
                    help="Number of fixes to keep in scatter history (default: 60)")
    args = ap.parse_args()

    north_hist: collections.deque = collections.deque(maxlen=args.history)
    east_hist: collections.deque = collections.deque(maxlen=args.history)
    ref_lat = ref_lon = None
    last_render = 0.0

    with GPSD(host=args.host, port=args.port) as gps:
        while _running:
            now = time.monotonic()
            if now - last_render >= args.interval:
                fix = gps.get_fix()

                if fix.has_fix:
                    if ref_lat is None:
                        ref_lat, ref_lon = fix.latitude, fix.longitude

                    n = haversine_m(ref_lat, ref_lon, fix.latitude, ref_lon) * (
                        1 if fix.latitude >= ref_lat else -1
                    )
                    e = haversine_m(ref_lat, ref_lon, ref_lat, fix.longitude) * (
                        1 if fix.longitude >= ref_lon else -1
                    )
                    north_hist.append(n)
                    east_hist.append(e)

                render(fix, gps,
                       connected=gps.is_connected,
                       stale=gps.is_stale,
                       north_hist=north_hist,
                       east_hist=east_hist)
                last_render = now
            time.sleep(0.1)

    print()


if __name__ == "__main__":
    main()
