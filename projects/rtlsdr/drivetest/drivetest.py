#!/usr/bin/env python3
"""
RF Coverage Drive Test

Continuously monitors a target frequency with the RTL-SDR, logging signal
power vs time.  With GPS, also logs lat/lon and writes a GPX track file
so the coverage map can be overlaid on any mapping tool.

GPS is optional — without it, data is still logged with timestamps.

Usage:
    python drivetest.py --freq 462.5625e6 --gps           # GMRS repeater
    python drivetest.py --freq 144.39e6 --gps --out aprs  # APRS coverage
    python drivetest.py --freq 162.55e6                    # NOAA weather, no GPS
    python drivetest.py --freq 1090e6 --bw 2e6 --gps     # ADS-B presence

Output files (--out sets the stem, default: drivetest):
    <stem>.csv    — timestamp, lat, lon, power_db per sample
    <stem>.gpx    — GPX track with signal strength extension (GPS only)
"""

import argparse
import csv
import math
import signal
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

from rf_bench.rtlsdr import RTLSDR, RTLSDRError

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


# ── signal power measurement ──────────────────────────────────────────────────

def measure_power_db(sdr: RTLSDR, bw_fraction: float = 0.5) -> float:
    """
    Capture one IQ block and return mean power in the central bw_fraction
    of the band.  The outer edges are discarded to reduce aliasing artifacts.
    """
    block = sdr.capture_iq(65_536)
    # bandpass: keep central fraction of the spectrum
    n = len(block)
    margin = int(n * (1 - bw_fraction) / 2)
    spec = np.fft.fftshift(np.fft.fft(block))
    power = np.mean(np.abs(spec[margin: n - margin]) ** 2)
    return 10 * math.log10(float(power) + 1e-30)


# ── GPX writer ────────────────────────────────────────────────────────────────

GPX_HEADER = """\
<?xml version="1.0" encoding="UTF-8"?>
<gpx version="1.1" creator="rf-bench-drivetest"
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
          <rf:power_db>{power:.2f}</rf:power_db>
        </extensions>
      </trkpt>
"""

GPX_FOOTER = """\
    </trkseg>
  </trk>
</gpx>
"""


class GPXWriter:
    def __init__(self, path: Path, name: str) -> None:
        self._fh = open(path, "w")
        self._fh.write(GPX_HEADER.format(name=name))

    def write_point(self, lat: float, lon: float, alt: float,
                    iso_time: str, power_db: float) -> None:
        self._fh.write(GPX_TRKPT.format(
            lat=lat, lon=lon, alt=alt or 0.0,
            time=iso_time, power=power_db,
        ))
        self._fh.flush()

    def close(self) -> None:
        self._fh.write(GPX_FOOTER)
        self._fh.close()


# ── main ──────────────────────────────────────────────────────────────────────

def main() -> None:
    ap = argparse.ArgumentParser(
        description="RTL-SDR RF coverage drive test with optional GPS logging"
    )
    ap.add_argument("--freq", type=float, required=True,
                    help="Target center frequency in Hz (e.g. 144.39e6)")
    ap.add_argument("--bw", type=float, default=200_000,
                    help="Sample rate in S/s (default: 200000 = 200 kHz)")
    ap.add_argument("--gain", default="auto",
                    help="RTL-SDR gain in dB or 'auto' (default: auto)")
    ap.add_argument("--interval", type=float, default=1.0,
                    help="Measurement interval in seconds (default: 1)")
    ap.add_argument("--duration", type=float, default=0.0,
                    help="Run duration in seconds (0 = until Ctrl-C)")
    ap.add_argument("--out", default="drivetest",
                    help="Output file stem (default: drivetest)")
    ap.add_argument("--serial", help="RTL-SDR serial number")
    ap.add_argument("--bias-tee", action="store_true",
                    help="Enable RTL-SDR Blog bias tee")
    ap.add_argument("--gps", action="store_true",
                    help="Enable GPS logging via gpsd")
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

    gain = args.gain if args.gain == "auto" else float(args.gain)
    ts_start = datetime.now(tz=timezone.utc).strftime("%Y%m%d_%H%M%S")
    csv_path = Path(f"{args.out}_{ts_start}.csv")
    gpx_path = Path(f"{args.out}_{ts_start}.gpx") if gps else None

    print(f"\nDrive test: {args.freq/1e6:.4f} MHz  "
          f"BW={args.bw/1e3:.0f} kHz  "
          f"GPS={'on' if gps else 'off'}")
    print(f"CSV: {csv_path}")
    if gpx_path:
        print(f"GPX: {gpx_path}")
    print()

    gpx = GPXWriter(gpx_path, f"drivetest {args.freq/1e6:.4f} MHz") if gpx_path else None
    deadline = time.monotonic() + args.duration if args.duration > 0 else float("inf")
    n = 0

    try:
        with open(csv_path, "w", newline="") as csv_file:
            writer = csv.writer(csv_file)
            writer.writerow([
                "timestamp_utc", "epoch_s",
                "lat_deg", "lon_deg", "alt_m",
                "gps_fix_mode", "gps_speed_kmh", "gps_heading_deg",
                "freq_hz", "power_db",
            ])

            with RTLSDR(serial=args.serial, gain=gain) as sdr:
                sdr.set_center_freq(int(args.freq))
                sdr.set_sample_rate(int(args.bw))
                if args.bias_tee:
                    sdr.set_bias_tee(True)

                info = sdr.identify()
                print(f"RTL-SDR: {info['tuner_type']}  "
                      f"rate={info['sample_rate']/1e3:.0f} kS/s  "
                      f"gain={info['gain']} dB\n")

                last_meas = 0.0
                while _running and time.monotonic() < deadline:
                    now = time.monotonic()
                    if now - last_meas >= args.interval:
                        power_db = measure_power_db(sdr)
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
                            f"{args.freq:.0f}",
                            f"{power_db:.2f}",
                        ])
                        csv_file.flush()

                        if gpx and lat:
                            gpx.write_point(lat, lon, alt or 0.0, ts, power_db)

                        n += 1
                        loc_str = (f"{lat:.5f},{lon:.5f}" if lat
                                   else "no GPS    ")
                        print(
                            f"\r  {ts[11:19]}  "
                            f"power={power_db:+7.1f} dB  "
                            f"loc={loc_str}  n={n}",
                            end="", flush=True,
                        )
                        last_meas = now
                    time.sleep(0.05)

                if args.bias_tee:
                    sdr.set_bias_tee(False)

    except RTLSDRError as exc:
        print(f"\nRTL-SDR error: {exc}", file=sys.stderr)
        sys.exit(1)
    finally:
        if gpx:
            gpx.close()
        if gps:
            gps.close()

    print(f"\n\nDone — {n} samples.  CSV: {csv_path}")
    if gpx_path:
        print(f"GPX: {gpx_path}")


if __name__ == "__main__":
    main()
