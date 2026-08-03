#!/usr/bin/env python3
"""
Clamp Current Logger — Fluke 80i-400 AC current clamp + bench DMM

Reads AC current through a Fluke 80i-400 clamp using any rf-bench DMM as the
readout, applies the clamp's 1 mA/A (1000:1) conversion and ±(3 % + 0.4 A)
accuracy model, prints live, and optionally logs to CSV.

Physical connections:
  Conductor under test → clamped inside the 80i-400 jaws (one wire only —
      not both conductors of a mains pair, or the fields cancel)
  80i-400 banana plugs → DMM **current (mA) input**  (NOT the volts input)
  DMM set to AC current (true-RMS), mA range that reaches 400 mA

The 80i-400 outputs 1 mA per amp, so 400 A of conductor current = 400 mA into
the meter. The DMM driver returns amperes (e.g. 0.240 A); the clamp layer
multiplies by 1000 to give conductor amps (240 A).

Usage:
  python clamp_current.py                        # live read via inventory DMM
  python clamp_current.py --interval 0.5         # 2 Hz
  python clamp_current.py --csv run.csv          # log to CSV
  python clamp_current.py --dmm sdm              # inventory name of the DMM
  python clamp_current.py --ma 240               # one-shot manual conversion,
                                                 #   no instrument needed

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


def one_shot_manual(meter_ma: float) -> int:
    """Convert a single meter reading (mA) with no instrument attached."""
    clamp = Fluke80i400()
    r = clamp.reading_from_milliamps(meter_ma)
    unc = f"{r.uncertainty:.1f}" if r.uncertainty is not None else "n/a (out of range)"
    print(f"Meter:     {r.meter_ma:.3f} mA")
    print(f"Current:   {r.amps:.2f} A")
    print(f"Accuracy:  +/- {unc} A")
    print(f"In range:  {r.in_range}  (spec 1-400 A)")
    return 0


def live_log(dmm_name: str, interval: float, csv_path: str | None) -> int:
    """Continuously read the clamp via an inventory DMM until Ctrl-C."""

    print(f"Connecting to DMM '{dmm_name}' via inventory...")
    try:
        dmm = connect(dmm_name)
    except Exception as e:  # noqa: BLE001 — surface any connection failure plainly
        print(f"ERROR: could not connect to DMM '{dmm_name}': {e}")
        print("Check inventory.yaml and that the meter is powered and reachable.")
        return 1

    clamp = Fluke80i400(dmm=dmm)
    print(repr(clamp))
    print("Meter must be on AC current (mA). Clamp one conductor only.")
    print("Press Ctrl-C to stop.\n")

    writer = None
    csv_file = None
    if csv_path:
        csv_file = open(csv_path, "w", newline="")
        writer = csv_module.writer(csv_file)
        writer.writerow(["timestamp", "amps", "uncertainty_a", "in_range", "meter_ma"])

    print(f"{'time':<20} {'amps':>10} {'± A':>8}  range")
    try:
        while True:
            r = clamp.read()
            ts = datetime.now().isoformat(timespec="seconds")
            unc = f"{r.uncertainty:.1f}" if r.uncertainty is not None else "  --"
            flag = "" if r.in_range else "  <OUT OF SPEC>"
            print(f"{ts:<20} {r.amps:>10.2f} {unc:>8}{flag}")
            if writer:
                writer.writerow([ts, f"{r.amps:.3f}",
                                 "" if r.uncertainty is None else f"{r.uncertainty:.3f}",
                                 r.in_range, f"{r.meter_ma:.3f}"])
                csv_file.flush()
            time.sleep(interval)
    except KeyboardInterrupt:
        print("\nStopped.")
    finally:
        if csv_file:
            csv_file.close()
            print(f"Wrote {csv_path}")
    return 0


def main() -> int:
    p = argparse.ArgumentParser(description="Fluke 80i-400 clamp current logger")
    p.add_argument("--ma", type=float, default=None,
                   help="One-shot: convert this meter reading (mA) and exit; "
                        "no instrument needed.")
    p.add_argument("--dmm", default="sdm",
                   help="Inventory name of the readout DMM (default: sdm).")
    p.add_argument("--interval", type=float, default=1.0,
                   help="Sample interval in seconds (default: 1.0).")
    p.add_argument("--csv", default=None, help="Log readings to this CSV file.")
    args = p.parse_args()

    if args.ma is not None:
        return one_shot_manual(args.ma)
    return live_log(args.dmm, args.interval, args.csv)


if __name__ == "__main__":
    sys.exit(main())
