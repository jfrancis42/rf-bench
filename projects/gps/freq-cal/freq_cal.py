#!/usr/bin/env python3
"""
GPS-Disciplined Frequency Drift Monitor

Measures a signal source (SDG1062X, TCXO, or any CW carrier) with the
SSA3032X repeatedly, using GPS-derived UTC timestamps as an accurate
time reference.  Logs frequency vs time to CSV and reports drift in
Hz/s and ppm.

GPS provides absolute time accuracy independent of the SSA's internal
TCXO, breaking the circular dependency in the standard SSA-only workflow.
Useful for characterising temperature-dependent frequency drift or
verifying that a reference oscillator meets its ageing spec.

Hardware:
    SSA3032X Plus  →  10.1.1.60
    SDG1062X       →  10.1.1.55  (optional; can measure any CW carrier)
    gpsd           →  localhost:2947

Usage:
    python freq_cal.py --freq 10e6 --duration 3600
    python freq_cal.py --freq 10e6 --duration 3600 --no-sdg   # external source
    python freq_cal.py --freq 14.2e6 --duration 600 --out drift.csv
    python freq_cal.py --report drift.csv                       # analyse saved data
"""

import argparse
import csv
import math
import signal
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from rf_bench.siglent import SSA3000X, SDG1000X
from rf_bench.gpsd import GPSD, GPSDNoFixError
from rf_bench import connect

_running = True


def _sigint(*_):
    global _running
    _running = False


signal.signal(signal.SIGINT, _sigint)

SSA_HOST = "10.1.1.60"
SDG_HOST = "10.1.1.55"


# ── SSA peak search ───────────────────────────────────────────────────────────

def measure_peak_freq(ssa: SSA3000X, center_hz: float,
                      span_hz: float = 1000.0) -> float:
    """
    Set a narrow span around center_hz and return the SSA peak frequency.
    Uses marker peak search for sub-Hz precision relative to the span.
    """
    ssa.set_center_freq(center_hz)
    ssa.set_span(span_hz)
    ssa.set_rbw(max(1.0, span_hz / 1000))
    ssa.set_vbw(max(1.0, span_hz / 1000))
    time.sleep(0.3)
    ssa.write("CALC:MARK1:MAX:PEAK")
    time.sleep(0.1)
    return float(ssa.query("CALC:MARK1:X?"))


# ── linear regression for drift ───────────────────────────────────────────────

def linear_regression(x: list, y: list):
    """Return (slope, intercept) via OLS."""
    n = len(x)
    if n < 2:
        return 0.0, y[0] if y else 0.0
    sx = sum(x)
    sy = sum(y)
    sxx = sum(xi ** 2 for xi in x)
    sxy = sum(xi * yi for xi, yi in zip(x, y))
    denom = n * sxx - sx ** 2
    if abs(denom) < 1e-12:
        return 0.0, sy / n
    slope = (n * sxy - sx * sy) / denom
    intercept = (sy - slope * sx) / n
    return slope, intercept


# ── report from saved CSV ──────────────────────────────────────────────────────

def report_from_csv(path: str, nominal_hz: float) -> None:
    rows = []
    with open(path, newline="") as fh:
        reader = csv.DictReader(fh)
        for row in reader:
            try:
                rows.append({
                    "t": float(row["epoch_s"]),
                    "f": float(row["freq_hz"]),
                    "gps_time": row.get("gps_time_utc", ""),
                })
            except (KeyError, ValueError):
                pass

    if not rows:
        print("No data in file.", file=sys.stderr)
        sys.exit(1)

    freqs = [r["f"] for r in rows]
    t0 = rows[0]["t"]
    times = [r["t"] - t0 for r in rows]

    mean_f = sum(freqs) / len(freqs)
    offset_hz = mean_f - nominal_hz
    offset_ppm = offset_hz / nominal_hz * 1e6

    slope_hz_s, _ = linear_regression(times, freqs)
    slope_ppm_day = slope_hz_s / nominal_hz * 1e6 * 86400

    print(f"\nFrequency Drift Analysis — {path}")
    print(f"  Nominal frequency : {nominal_hz/1e6:.6f} MHz")
    print(f"  Mean measured     : {mean_f/1e6:.9f} MHz")
    print(f"  Offset            : {offset_hz:+.3f} Hz  ({offset_ppm:+.4f} ppm)")
    print(f"  Drift rate        : {slope_hz_s*1000:+.4f} mHz/s  "
          f"({slope_ppm_day:+.4f} ppm/day)")
    print(f"  Samples           : {len(rows)}")
    print(f"  Duration          : {times[-1]:.0f} s  ({times[-1]/3600:.2f} h)")


# ── main ──────────────────────────────────────────────────────────────────────

def main() -> None:
    ap = argparse.ArgumentParser(
        description="GPS-disciplined frequency drift monitor using SSA3032X"
    )
    ap.add_argument("--freq", type=float, required=True,
                    help="Nominal signal frequency in Hz (e.g. 10e6)")
    ap.add_argument("--span", type=float, default=500.0,
                    help="SSA span in Hz around the signal (default: 500)")
    ap.add_argument("--duration", type=float, default=600.0,
                    help="Measurement duration in seconds (default: 600)")
    ap.add_argument("--interval", type=float, default=5.0,
                    help="Measurement interval in seconds (default: 5)")
    ap.add_argument("--out", metavar="FILE", default="freq_cal.csv",
                    help="Output CSV file (default: freq_cal.csv)")
    ap.add_argument("--no-sdg", action="store_true",
                    help="Skip SDG setup — measure an external source")
    ap.add_argument("--sdg-level", type=float, default=-10.0,
                    help="SDG output level in dBm (default: -10)")
    ap.add_argument("--ssa-host", default=SSA_HOST,
                    help=f"SSA3032X IP (default: {SSA_HOST})")
    ap.add_argument("--sdg-host", default=SDG_HOST,
                    help=f"SDG1062X IP (default: {SDG_HOST})")
    ap.add_argument("--gps-host", default="localhost",
                    help="gpsd hostname (default: localhost)")
    ap.add_argument("--gps-port", type=int, default=2947,
                    help="gpsd port (default: 2947)")
    ap.add_argument("--report", metavar="FILE",
                    help="Analyse a previously saved CSV and exit")
    args = ap.parse_args()

    if args.report:
        report_from_csv(args.report, args.freq)
        return

    print(f"GPS-Disciplined Frequency Drift Monitor")
    print(f"  Nominal  : {args.freq/1e6:.6f} MHz")
    print(f"  Duration : {args.duration:.0f} s")
    print(f"  Interval : {args.interval:.1f} s")
    print(f"  SSA      : {args.ssa_host}")
    print(f"  GPS      : {args.gps_host}:{args.gps_port}")
    print()

    with GPSD(host=args.gps_host, port=args.gps_port) as gps:
        print("Waiting for GPS fix …", end="", flush=True)
        try:
            gps.wait_for_fix(timeout=60)
            print(" OK")
        except GPSDNoFixError as exc:
            print(f"\nNo GPS fix: {exc}", file=sys.stderr)
            sys.exit(1)

        ssa = connect(args.ssa_host or 'ssa')
        sdg = None if args.no_sdg else SDG1000X(args.sdg_host)

        if sdg:
            print(f"SDG: enabling CH1 at {args.freq/1e6:.6f} MHz, "
                  f"{args.sdg_level:.1f} dBm …")
            sdg.set_waveform(1, "SINE")
            sdg.set_frequency(1, args.freq)
            sdg.set_amplitude_dbm(1, args.sdg_level)
            sdg.set_output(1, True)

        samples = []
        t_start = time.monotonic()
        deadline = t_start + args.duration
        last_meas = 0.0

        with open(args.out, "w", newline="") as csv_file:
            writer = csv.writer(csv_file)
            writer.writerow(["epoch_s", "gps_time_utc", "freq_hz",
                             "offset_hz", "offset_ppm",
                             "gps_hdop", "gps_sats_used"])

            print(f"\nMeasuring …  (Ctrl-C to stop early)\n")
            print(f"  {'Elapsed':>8s}  {'GPS Time':>22s}  {'Freq (Hz)':>16s}  "
                  f"{'Offset':>12s}  {'ppm':>8s}")
            print(f"  {'─'*8}  {'─'*22}  {'─'*16}  {'─'*12}  {'─'*8}")

            while _running and time.monotonic() < deadline:
                now = time.monotonic()
                if now - last_meas >= args.interval:
                    fix = gps.get_fix()
                    measured_hz = measure_peak_freq(ssa, args.freq, args.span)
                    epoch_s = time.time()

                    offset_hz = measured_hz - args.freq
                    offset_ppm = offset_hz / args.freq * 1e6

                    writer.writerow([
                        f"{epoch_s:.3f}",
                        fix.time_utc or "",
                        f"{measured_hz:.6f}",
                        f"{offset_hz:.6f}",
                        f"{offset_ppm:.6f}",
                        fix.hdop or "",
                        fix.satellites_used or "",
                    ])
                    csv_file.flush()
                    samples.append((now - t_start, measured_hz))

                    elapsed_s = now - t_start
                    print(f"  {elapsed_s:7.0f}s  {str(fix.time_utc or 'no GPS time'):>22s}  "
                          f"{measured_hz:16.4f}  {offset_hz:+10.4f} Hz  "
                          f"{offset_ppm:+8.4f}")
                    last_meas = now
                time.sleep(0.2)

        if sdg:
            sdg.set_output(1, False)
        ssa.close()

    if len(samples) >= 2:
        times = [s[0] for s in samples]
        freqs = [s[1] for s in samples]
        slope, _ = linear_regression(times, freqs)
        slope_ppm_day = slope / args.freq * 1e6 * 86400
        mean_f = sum(freqs) / len(freqs)
        offset_ppm = (mean_f - args.freq) / args.freq * 1e6

        print(f"\n{'='*54}")
        print(f"  Mean offset : {mean_f - args.freq:+.4f} Hz  ({offset_ppm:+.4f} ppm)")
        print(f"  Drift rate  : {slope*1000:+.4f} mHz/s  ({slope_ppm_day:+.4f} ppm/day)")
        print(f"  Samples     : {len(samples)}")
        print(f"  Saved to    : {args.out}")
        print(f"{'='*54}")


if __name__ == "__main__":
    main()
