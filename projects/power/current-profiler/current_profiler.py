#!/usr/bin/env python3
"""
AC Current Profiler — Fluke 80i-400 clamp + bench DMM (+ optional MQTT)

Logs AC current through a Fluke 80i-400 clamp over time and derives a load
profile: min/avg/peak/RMS current, on/off duty cycle (via a threshold), and
per-session statistics. Optionally publishes each reading to the rf-bench MQTT
bus so the existing timeseries_logger and alert_daemon pick it up.

Honesty note — this measures CURRENT, not power:
  The 80i-400 gives amps only. Real power (W) needs simultaneous mains-voltage
  sensing, which is a shock hazard and a separate project
  (projects/power/ac-power/). This tool deliberately reports amps and never
  fabricates watts from an assumed 120 V / PF=1 — that would be wrong for
  reactive and nonlinear loads. If you want an *indicative* VA figure for a
  known nominal voltage, pass --nominal-volts and it's labeled apparent-VA
  (assumes PF=1), clearly flagged as an estimate.

Signal path: conductor → 80i-400 clamp → DMM current (mA) jacks, AC current.

Usage:
  python current_profiler.py                         # log via inventory DMM "sdm"
  python current_profiler.py --interval 0.5          # 2 Hz
  python current_profiler.py --duration 3600         # stop after 1 hour
  python current_profiler.py --csv load.csv          # log to CSV
  python current_profiler.py --on-threshold 1.5      # "on" when >1.5 A
  python current_profiler.py --mqtt                  # publish to MQTT bus
  python current_profiler.py --nominal-volts 120     # add indicative apparent-VA

Author: Jeff Francis (N0GQ) <gjfrancis@protonmail.com>
License: GPL-3.0-or-later
"""

import argparse
import csv as csv_module
import sys
import time
from datetime import datetime

from rf_bench.fluke import Fluke80i400
from rf_bench import connect


def main() -> int:
    p = argparse.ArgumentParser(description="AC current profiler (Fluke 80i-400 + DMM)")
    p.add_argument("--dmm", default="sdm", help="Inventory DMM name (default sdm)")
    p.add_argument("--interval", type=float, default=1.0, help="Sample interval s")
    p.add_argument("--duration", type=float, default=None,
                   help="Stop after N seconds (default: run until Ctrl-C)")
    p.add_argument("--csv", default=None, help="Log readings to CSV")
    p.add_argument("--on-threshold", type=float, default=1.0,
                   help="Current (A) above which the load counts as 'on' (default 1.0)")
    p.add_argument("--nominal-volts", type=float, default=None,
                   help="If set, also report INDICATIVE apparent VA = A×V (PF=1 "
                        "assumed; estimate only, not measured power)")
    p.add_argument("--mqtt", action="store_true", help="Publish readings to MQTT bus")
    p.add_argument("--mqtt-prefix", default="/bench/clamp",
                   help="MQTT topic prefix (default /bench/clamp)")
    args = p.parse_args()

    try:
        dmm = connect(args.dmm)
    except Exception as e:  # noqa: BLE001
        print(f"ERROR: could not connect to DMM '{args.dmm}': {e}")
        return 1
    clamp = Fluke80i400(dmm=dmm)

    mqtt = None
    if args.mqtt:
        try:
            from rf_bench.mqtt import MQTTClient
            mqtt = MQTTClient(client_id="clamp-profiler")
            mqtt.connect()
            print(f"MQTT: publishing to {args.mqtt_prefix}/*")
        except Exception as e:  # noqa: BLE001
            print(f"WARNING: MQTT disabled ({e})")
            mqtt = None

    writer = csv_file = None
    if args.csv:
        csv_file = open(args.csv, "w", newline="")
        writer = csv_module.writer(csv_file)
        header = ["timestamp", "amps", "uncertainty_a", "in_range", "on"]
        if args.nominal_volts:
            header.append("apparent_va_est")
        writer.writerow(header)

    print("Meter must be on AC current (mA). Clamp ONE conductor only.")
    print(f"'on' threshold: {args.on_threshold} A. Ctrl-C to stop.\n")
    print(f"{'time':<20} {'amps':>9} {'± A':>7}  state")

    n = 0
    sum_a = sum_sq = 0.0
    peak = 0.0
    min_a = float("inf")
    on_count = 0
    t_start = time.monotonic()
    try:
        while True:
            r = clamp.read()
            on = r.amps >= args.on_threshold
            n += 1
            sum_a += r.amps
            sum_sq += r.amps ** 2
            peak = max(peak, r.amps)
            min_a = min(min_a, r.amps)
            on_count += 1 if on else 0

            ts = datetime.now().isoformat(timespec="seconds")
            unc = f"{r.uncertainty:.1f}" if r.uncertainty is not None else "  --"
            print(f"{ts:<20} {r.amps:>9.2f} {unc:>7}  {'ON ' if on else 'off'}")

            row = [ts, f"{r.amps:.3f}",
                   "" if r.uncertainty is None else f"{r.uncertainty:.3f}",
                   r.in_range, on]
            va_est = None
            if args.nominal_volts:
                va_est = r.amps * args.nominal_volts
                row.append(f"{va_est:.1f}")

            if writer:
                writer.writerow(row)
                csv_file.flush()

            if mqtt:
                mqtt.publish(f"{args.mqtt_prefix}/amps", r.amps)
                mqtt.publish(f"{args.mqtt_prefix}/on", int(on))
                if va_est is not None:
                    mqtt.publish(f"{args.mqtt_prefix}/apparent_va_est", va_est)

            if args.duration and (time.monotonic() - t_start) >= args.duration:
                break
            time.sleep(args.interval)
    except KeyboardInterrupt:
        print("\nStopped.")
    finally:
        if csv_file:
            csv_file.close()
        if mqtt:
            mqtt.disconnect()

    if n:
        elapsed = time.monotonic() - t_start
        print("\n--- session ---")
        print(f"samples:   {n} over {elapsed:.0f} s")
        print(f"current:   min {min_a:.2f} / avg {sum_a/n:.2f} / "
              f"rms {(sum_sq/n) ** 0.5:.2f} / peak {peak:.2f} A")
        print(f"duty (on): {100.0*on_count/n:.1f} %  (threshold {args.on_threshold} A)")
        if args.nominal_volts:
            print(f"apparent:  ~{(sum_a/n)*args.nominal_volts:.0f} VA avg "
                  f"(ESTIMATE, PF=1 assumed — not measured power)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
