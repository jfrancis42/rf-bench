#!/usr/bin/env python3
"""
Mobile Spectrum Survey

Captures power spectra from the RTL-SDR at regular intervals, optionally
geo-tagged with GPS coordinates.  Saves results to a CSV file that can be
post-processed into signal-strength heatmaps or coverage maps.

GPS is optional: without it, captures are timestamped only.

Usage:
    # Single frequency, GPS-tagged
    python survey.py --freq 144.39e6 --gps

    # Sweep three frequencies, 10-second dwell, no GPS
    python survey.py --sweep 433.92e6,868e6,915e6 --dwell 10

    # Continuous run, save to file
    python survey.py --freq 144.39e6 --gps --out survey.csv --duration 3600

    # FM band survey with GPS
    python survey.py --freq 97.9e6 --span 20e6 --gps --out fm_survey.csv
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


# ── spectrum capture ──────────────────────────────────────────────────────────

def capture_spectrum(sdr: RTLSDR, freq_hz: float,
                     sample_rate: int, gain,
                     blocks: int = 4) -> tuple:
    """
    Tune to freq_hz, capture `blocks` IQ blocks, return (freq_axis, power_db).
    Returns averaged PSD over the blocks.
    """
    sdr.set_center_freq(int(freq_hz))
    sdr.set_sample_rate(sample_rate)
    sdr.set_gain(gain)
    time.sleep(0.05)  # settle

    block_size = 65_536
    iq_blocks = []
    for block in sdr.stream_iq(block_size=block_size):
        iq_blocks.append(block)
        if len(iq_blocks) >= blocks:
            break
    sdr.stop_stream()

    iq = np.concatenate(iq_blocks)
    freq_hz_axis, power_db = sdr.power_spectrum(iq, rbw_hz=sample_rate / 512)
    return freq_hz_axis, power_db


def peak_power(freq_axis: np.ndarray, power_db: np.ndarray,
               center_hz: float, bw_hz: float) -> float:
    """Return peak power within ±bw_hz/2 of center_hz."""
    mask = np.abs(freq_axis - center_hz) <= bw_hz / 2
    if not np.any(mask):
        return float(np.max(power_db))
    return float(np.max(power_db[mask]))


# ── main ──────────────────────────────────────────────────────────────────────

def main() -> None:
    ap = argparse.ArgumentParser(
        description="Mobile spectrum survey — RTL-SDR with optional GPS geo-tagging"
    )
    ap.add_argument("--freq", type=float,
                    help="Single center frequency in Hz (e.g. 144.39e6)")
    ap.add_argument("--sweep", metavar="F1,F2,...",
                    help="Comma-separated list of center frequencies in Hz")
    ap.add_argument("--bw", type=float, default=2_400_000,
                    help="Sample rate / bandwidth in S/s (default: 2.4e6)")
    ap.add_argument("--gain", default="auto",
                    help="RTL-SDR gain in dB or 'auto' (default: auto)")
    ap.add_argument("--dwell", type=float, default=5.0,
                    help="Time at each frequency in seconds (default: 5)")
    ap.add_argument("--duration", type=float, default=0.0,
                    help="Total run duration in seconds (0 = run until Ctrl-C)")
    ap.add_argument("--out", metavar="FILE", default="survey.csv",
                    help="Output CSV file (default: survey.csv)")
    ap.add_argument("--serial", help="RTL-SDR serial number")
    ap.add_argument("--bias-tee", action="store_true",
                    help="Enable RTL-SDR Blog bias tee")
    ap.add_argument("--gps", action="store_true",
                    help="Enable GPS geo-tagging via gpsd")
    ap.add_argument("--gps-host", default="localhost",
                    help="gpsd hostname (default: localhost)")
    ap.add_argument("--gps-port", type=int, default=2947,
                    help="gpsd port (default: 2947)")
    ap.add_argument("--gps-wait", type=float, default=30.0,
                    help="Seconds to wait for GPS fix at startup (default: 30)")
    args = ap.parse_args()

    # Build frequency list
    if args.sweep:
        freqs = [float(f.strip()) for f in args.sweep.split(",")]
    elif args.freq:
        freqs = [args.freq]
    else:
        ap.error("specify --freq or --sweep")

    # GPS setup
    gps = None
    if args.gps:
        if not _HAS_GPSD:
            print("Warning: rf-bench-drivers-gpsd not installed; GPS disabled.",
                  file=sys.stderr)
        else:
            gps = GPSD(host=args.gps_host, port=args.gps_port)
            print(f"Waiting for GPS fix (up to {args.gps_wait:.0f}s) …",
                  end="", flush=True)
            try:
                gps.wait_for_fix(timeout=args.gps_wait)
                print(" OK")
            except GPSDNoFixError:
                print(" (no fix — continuing without GPS)")

    gain = args.gain if args.gain == "auto" else float(args.gain)
    sample_rate = int(args.bw)

    print(f"\nSpectrum survey: {len(freqs)} freq(s), "
          f"{args.dwell:.1f}s dwell, GPS={'on' if gps else 'off'}")
    print(f"Output: {args.out}\n")

    deadline = time.monotonic() + args.duration if args.duration > 0 else float("inf")
    n_captures = 0

    try:
        with open(args.out, "w", newline="") as csv_file:
            writer = csv.writer(csv_file)
            writer.writerow([
                "timestamp_utc", "epoch_s",
                "lat_deg", "lon_deg", "alt_m",
                "gps_fix_mode", "gps_hdop",
                "center_freq_hz", "peak_power_db",
                "bandwidth_hz",
            ])

            with RTLSDR(serial=args.serial, gain=gain) as sdr:
                if args.bias_tee:
                    sdr.set_bias_tee(True)

                info = sdr.identify()
                print(f"RTL-SDR: {info['tuner_type']}  "
                      f"gain={info['gain']} dB  ppm={info['ppm_correction']}\n")

                while _running and time.monotonic() < deadline:
                    for freq_hz in freqs:
                        if not _running or time.monotonic() >= deadline:
                            break

                        t0 = time.monotonic()
                        freq_axis, power_db = capture_spectrum(
                            sdr, freq_hz, sample_rate, gain
                        )
                        peak_db = peak_power(freq_axis, power_db, freq_hz, sample_rate)

                        ts = datetime.now(tz=timezone.utc).isoformat()
                        epoch_s = time.time()

                        lat = lon = alt = fix_mode = hdop = None
                        if gps:
                            fix = gps.get_fix()
                            if fix.has_fix:
                                lat = fix.latitude
                                lon = fix.longitude
                                alt = fix.altitude_m
                                fix_mode = fix.fix_mode
                                hdop = fix.hdop

                        writer.writerow([
                            ts, f"{epoch_s:.3f}",
                            f"{lat:.6f}" if lat else "",
                            f"{lon:.6f}" if lon else "",
                            f"{alt:.1f}" if alt is not None else "",
                            fix_mode or "",
                            f"{hdop:.2f}" if hdop else "",
                            f"{freq_hz:.0f}",
                            f"{peak_db:.2f}",
                            f"{sample_rate:.0f}",
                        ])
                        csv_file.flush()
                        n_captures += 1

                        loc_str = (f"{lat:.5f},{lon:.5f}" if lat else "no GPS")
                        print(
                            f"  {ts[11:19]}  "
                            f"{freq_hz/1e6:9.4f} MHz  "
                            f"peak={peak_db:+7.1f} dB  "
                            f"loc={loc_str}"
                        )

                        # Dwell remainder
                        elapsed = time.monotonic() - t0
                        if elapsed < args.dwell and _running:
                            time.sleep(args.dwell - elapsed)

                if args.bias_tee:
                    sdr.set_bias_tee(False)

    except RTLSDRError as exc:
        print(f"RTL-SDR error: {exc}", file=sys.stderr)
        sys.exit(1)
    finally:
        if gps:
            gps.close()

    print(f"\nDone — {n_captures} captures saved to {args.out}")


if __name__ == "__main__":
    main()
