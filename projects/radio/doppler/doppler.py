#!/usr/bin/env python3
"""
Doppler VFO Corrector

Computes the expected Doppler frequency shift caused by your own motion
relative to a fixed transmitter and applies a real-time VFO correction to
the IC-7300 or FT-891 via Hamlib.

Use case: when driving toward or away from a repeater or beacon, your
radial velocity causes an apparent frequency shift of:

    Δf = f_nominal × v_radial / c

At 144 MHz doing 100 km/h directly toward the transmitter the shift is
~13 Hz — negligible for FM, but significant for CW, weak-signal digital
modes (JS8, FT8, WSPR), and narrow SSB.

The script reads your GPS velocity vector and the bearing to a fixed
target station, projects your velocity onto the transmitter–receiver
axis, and updates the VFO offset accordingly.

GPS is required.  The target station's coordinates must be provided.

Usage:
    python doppler.py --freq 145960 --mode FM \\
        --target-lat 39.7392 --target-lon -104.9903   # satellite downlink, IC-9700 (default)
    python doppler.py --freq 144174 --mode USB \\
        --target-lat 39.7392 --target-lon -104.9903 --radio ic7300
    python doppler.py --freq 10140 --mode USB \\
        --target-lat 41.7148 --target-lon -72.7272 --radio ft891 --rigctld-port 4533
"""

import argparse
import math
import signal
import sys
import time
from datetime import datetime, timezone

from rf_bench.icom import IC7300, IC9700
from rf_bench.yaesu import FT891
from rf_bench.gpsd import GPSD, GPSDNoFixError
from rf_bench import connect

_running = True
_C = 299_792_458.0  # m/s


def _sigint(*_):
    global _running
    _running = False


signal.signal(signal.SIGINT, _sigint)

RIGCTLD_HOST = "localhost"
RIGCTLD_PORT = 4532


# ── navigation ────────────────────────────────────────────────────────────────

def bearing_deg(lat1: float, lon1: float,
                lat2: float, lon2: float) -> float:
    """Initial bearing from (lat1,lon1) to (lat2,lon2), degrees true."""
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dl = math.radians(lon2 - lon1)
    x = math.sin(dl) * math.cos(p2)
    y = math.cos(p1) * math.sin(p2) - math.sin(p1) * math.cos(p2) * math.cos(dl)
    return (math.degrees(math.atan2(x, y)) + 360) % 360


def haversine_km(lat1: float, lon1: float,
                 lat2: float, lon2: float) -> float:
    R = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def radial_velocity_ms(speed_ms: float, heading_deg: float,
                       bearing_to_target_deg: float) -> float:
    """
    Component of velocity directed toward the target (positive = approaching).
    speed_ms:              ground speed in m/s
    heading_deg:           GPS course over ground, degrees true
    bearing_to_target_deg: bearing from current position to fixed target
    """
    angle_diff = math.radians(bearing_to_target_deg - heading_deg)
    return speed_ms * math.cos(angle_diff)


def doppler_hz(f_nominal_hz: float, v_radial_ms: float) -> float:
    """
    Classical Doppler shift.  Positive v_radial = approaching source
    → received frequency is higher.
    """
    return f_nominal_hz * v_radial_ms / _C


# ── main ──────────────────────────────────────────────────────────────────────

def main() -> None:
    ap = argparse.ArgumentParser(
        description="Real-time Doppler VFO correction using GPS velocity"
    )
    ap.add_argument("--freq", type=float, required=True,
                    help="Nominal receive frequency in kHz (e.g. 144174)")
    ap.add_argument("--mode", default="USB",
                    help="Receive mode: USB, LSB, CW, FM (default: USB)")
    ap.add_argument("--target-lat", type=float, required=True,
                    help="Target station latitude in decimal degrees")
    ap.add_argument("--target-lon", type=float, required=True,
                    help="Target station longitude in decimal degrees")
    ap.add_argument("--target-name", default="target",
                    help="Name of the target station (display only)")
    ap.add_argument("--radio", choices=["ic7300", "ic9700", "ft891"], default="ic9700",
                    help="Radio model (default: ic9700)")
    ap.add_argument("--rigctld-host", default=RIGCTLD_HOST)
    ap.add_argument("--rigctld-port", type=int, default=RIGCTLD_PORT)
    ap.add_argument("--gps-host", default="localhost")
    ap.add_argument("--gps-port", type=int, default=2947)
    ap.add_argument("--interval", type=float, default=1.0,
                    help="Update interval in seconds (default: 1)")
    ap.add_argument("--min-speed", type=float, default=0.5,
                    help="Minimum speed in m/s before applying correction "
                         "(avoids noise at rest, default: 0.5)")
    ap.add_argument("--dry-run", action="store_true",
                    help="Compute and display corrections but do not send to radio")
    args = ap.parse_args()

    f_nominal_hz = args.freq * 1000.0  # kHz → Hz

    print("Doppler VFO Corrector")
    print(f"  Nominal freq : {f_nominal_hz/1e6:.6f} MHz")
    print(f"  Target       : {args.target_name}  "
          f"({args.target_lat:.5f}, {args.target_lon:.5f})")
    print(f"  Radio        : {args.radio}")
    print(f"  Dry run      : {args.dry_run}")
    print()

    # GPS
    with GPSD(host=args.gps_host, port=args.gps_port) as gps:
        print("Waiting for GPS fix …", end="", flush=True)
        try:
            gps.wait_for_fix(timeout=60)
            print(" OK")
        except GPSDNoFixError as exc:
            print(f"\nNo GPS fix: {exc}", file=sys.stderr)
            sys.exit(1)

        # Radio
        radio = None
        if not args.dry_run:
            print(f"Connecting to {args.radio} via rigctld …", end="", flush=True)
            try:
                if args.radio == "ft891":
                    radio = FT891(host=args.rigctld_host, port=args.rigctld_port)
                elif args.radio == "ic9700":
                    radio = IC9700(host=args.rigctld_host, port=args.rigctld_port)
                else:
                    radio = IC7300(host=args.rigctld_host, port=args.rigctld_port)
                radio.set_frequency(args.freq)
                radio.set_mode(args.mode)
                print(" OK")
            except Exception as exc:
                print(f"\nFailed: {exc}", file=sys.stderr)
                sys.exit(1)

        print(f"\n  {'Time':>8s}  {'Dist':>8s}  {'Brg':>6s}  "
              f"{'Speed':>8s}  {'Radial':>9s}  {'Δf':>9s}  {'VFO':>16s}")
        print(f"  {'─'*8}  {'─'*8}  {'─'*6}  "
              f"{'─'*8}  {'─'*9}  {'─'*9}  {'─'*16}")

        last_update = 0.0
        current_offset_hz = 0.0

        try:
            while _running:
                now = time.monotonic()
                if now - last_update >= args.interval:
                    fix = gps.get_fix()

                    if not fix.has_fix or fix.speed_ms is None or fix.heading is None:
                        print(f"\r  (awaiting fix or speed …)        ", end="", flush=True)
                        last_update = now
                        time.sleep(0.1)
                        continue

                    dist_km = haversine_km(
                        fix.latitude, fix.longitude,
                        args.target_lat, args.target_lon,
                    )
                    brg = bearing_deg(
                        fix.latitude, fix.longitude,
                        args.target_lat, args.target_lon,
                    )

                    if fix.speed_ms >= args.min_speed:
                        v_radial = radial_velocity_ms(
                            fix.speed_ms, fix.heading, brg
                        )
                        delta_hz = doppler_hz(f_nominal_hz, v_radial)
                    else:
                        v_radial = 0.0
                        delta_hz = 0.0

                    corrected_khz = args.freq + delta_hz / 1000.0

                    if radio and abs(delta_hz - current_offset_hz) >= 1.0:
                        try:
                            radio.set_frequency(corrected_khz)
                            current_offset_hz = delta_hz
                        except Exception:
                            pass

                    ts = datetime.now(tz=timezone.utc).strftime("%H:%M:%S")
                    print(
                        f"\r  {ts}  "
                        f"{dist_km:6.1f} km  "
                        f"{brg:5.1f}°  "
                        f"{fix.speed_kmh:6.1f}km/h  "
                        f"{v_radial:+7.1f}m/s  "
                        f"{delta_hz:+7.2f}Hz  "
                        f"{corrected_khz:13.4f} kHz",
                        end="", flush=True,
                    )
                    last_update = now
                time.sleep(0.05)

        finally:
            # Restore nominal frequency on exit
            if radio:
                try:
                    radio.set_frequency(args.freq)
                    radio.close()
                except Exception:
                    pass

    print(f"\n\nRestored {args.freq:.3f} kHz  (Doppler correction removed)")


if __name__ == "__main__":
    main()
