#!/usr/bin/env python3
"""
Flipper Zero Sub-GHz Link Test

Range and packet delivery rate (PDR) test between two Flipper Zeros (TX + RX),
or in single-Flipper mode using subghz_transmit_raw + subghz_get_rssi in quick
alternation to estimate link budget.

Results are logged per distance step. Prints summary table at the end.

Usage:
  python link_test.py --freq 433.92 --packets 50
  python link_test.py --freq 433.92 --distance 5 10 20 50 100
  python link_test.py --freq 315 --power 7 --packets 100
"""

import argparse
import os
import signal
import sys
import time
from datetime import datetime

import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                '..', 'rf-bench'))
from rf_bench.flipper import FlipperZero

# ---------------------------------------------------------------------------
# Defaults
# ---------------------------------------------------------------------------
DEFAULT_SERIAL   = "/dev/ttyACM0"
DEFAULT_FREQ_MHZ = 433.92
DEFAULT_PACKETS  = 50
DEFAULT_POWER    = 4     # 0-7 PATABLE index
DEFAULT_DISTS    = [1, 2, 5, 10, 20, 50, 100]  # meters

# Reference packet for single-Flipper mode: standard OOK preamble + data
REFERENCE_TIMINGS_US = (
    [500, 500] * 8 +   # preamble: 8 on/off at 500 us
    [500, 1500] * 4 +  # data: alternating bits
    [500, 5000]        # end gap
)

_running = True


def _sigint_handler(sig, frame):
    global _running
    _running = False
    print("\n  [Ctrl+C -- stopping test]")


signal.signal(signal.SIGINT, _sigint_handler)


# ---------------------------------------------------------------------------
# Single-Flipper link test
# ---------------------------------------------------------------------------

def single_flipper_test(fz: FlipperZero, freq_hz: float, n_packets: int,
                        power_idx: int) -> dict:
    """
    Alternate between TX and RSSI measurement.
    TX a reference packet, then immediately read RSSI.
    Returns {rssi_readings: [...], n_tx: int}.
    """
    rssi_readings = []
    for i in range(n_packets):
        if not _running:
            break
        fz.subghz_transmit_raw(int(freq_hz), REFERENCE_TIMINGS_US, preset='ook650')
        time.sleep(0.02)
        readings = fz.subghz_get_rssi(int(freq_hz), duration_s=0.2)
        if readings:
            rssi_readings.extend(readings)
        sys.stdout.write(f"\r  Packet {i+1}/{n_packets} ...")
        sys.stdout.flush()
    print()
    return {"rssi_readings": rssi_readings, "n_tx": n_packets}


# ---------------------------------------------------------------------------
# Two-Flipper link test (RX mode)
# ---------------------------------------------------------------------------

def rx_mode(fz: FlipperZero, freq_hz: float, n_packets: int) -> dict:
    """
    RX-only mode: listen and count received packets, record RSSI.
    Run this on the RX Flipper while a second unit (or transmitter) sends packets.
    """
    received = 0
    rssi_readings = []
    t_start = time.time()
    timeout = n_packets * 0.2 + 5.0  # generous timeout

    print(f"  [RX] Listening for {n_packets} packets @ {freq_hz/1e6:.4f} MHz ...")
    print(f"  Start the TX side now. Timeout: {timeout:.0f} s")

    while _running and received < n_packets:
        if time.time() - t_start > timeout:
            break
        readings = fz.subghz_get_rssi(int(freq_hz), duration_s=0.2)
        if readings:
            # Treat any non-floor RSSI as packet received
            useful = [r for r in readings if r > -110]
            if useful:
                received += 1
                rssi_readings.extend(useful)
                sys.stdout.write(f"\r  Received: {received}/{n_packets} ...")
                sys.stdout.flush()

    print()
    return {"received": received, "n_tx": n_packets,
            "rssi_readings": rssi_readings,
            "pdr": received / n_packets if n_packets > 0 else 0}


# ---------------------------------------------------------------------------
# Distance step loop
# ---------------------------------------------------------------------------

def distance_loop(fz: FlipperZero, freq_hz: float, n_packets: int,
                  power_idx: int, distances: list) -> list:
    """
    For each distance, prompt user to position, then run single-Flipper test.
    Returns list of result dicts.
    """
    results = []
    print(f"\n[LINK TEST]  freq={freq_hz/1e6:.4f} MHz  packets={n_packets}  "
          f"power_idx={power_idx}")
    print("  Using single-Flipper mode (TX then immediate RSSI)")

    for dist in distances:
        if not _running:
            break
        try:
            input(f"\n  Move to {dist} m, then press Enter ...")
        except EOFError:
            break

        r = single_flipper_test(fz, freq_hz, n_packets, power_idx)
        rssi = r["rssi_readings"]
        if rssi:
            mean_rssi = float(np.mean(rssi))
            min_rssi  = float(np.min(rssi))
        else:
            mean_rssi = float('nan')
            min_rssi  = float('nan')

        entry = {
            "distance_m": dist,
            "n_tx":       n_packets,
            "mean_rssi":  mean_rssi,
            "min_rssi":   min_rssi,
        }
        results.append(entry)
        print(f"  dist={dist}m  mean_RSSI={mean_rssi:+.1f} dBm  min={min_rssi:+.1f} dBm")

    return results


# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------

def print_summary(results: list, freq_hz: float, n_packets: int) -> None:
    print("\n" + "=" * 60)
    print(f"LINK TEST SUMMARY  freq={freq_hz/1e6:.4f} MHz  packets={n_packets}")
    print(f"  {'Distance (m)':>14}  {'Mean RSSI':>12}  {'Min RSSI':>10}")
    print("  " + "-" * 42)
    for r in results:
        print(f"  {r['distance_m']:>14}  {r['mean_rssi']:>+12.1f}  {r['min_rssi']:>+10.1f}")
    print("=" * 60)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Sub-GHz link budget / PDR test",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python link_test.py --freq 433.92 --packets 50
  python link_test.py --freq 315 --distance 1 5 10 20 50
  python link_test.py --freq 433.92 --rx-mode --packets 100
""",
    )
    parser.add_argument("--freq",     type=float, default=DEFAULT_FREQ_MHZ, metavar="MHZ",
                        help=f"Frequency MHz (default {DEFAULT_FREQ_MHZ})")
    parser.add_argument("--packets",  type=int, default=DEFAULT_PACKETS, metavar="N",
                        help=f"Packets per distance step (default {DEFAULT_PACKETS})")
    parser.add_argument("--power",    type=int, default=DEFAULT_POWER, metavar="IDX",
                        help=f"PATABLE power index 0-7 (default {DEFAULT_POWER})")
    parser.add_argument("--distance", type=float, nargs="+", default=DEFAULT_DISTS,
                        metavar="M", help="Distance steps in meters")
    parser.add_argument("--rx-mode",  action="store_true",
                        help="Run as RX only (use second Flipper or external TX)")
    parser.add_argument("--serial",   default=DEFAULT_SERIAL, metavar="PORT",
                        help=f"Flipper serial port (default {DEFAULT_SERIAL})")

    args = parser.parse_args()
    freq_hz = args.freq * 1e6

    try:
        print(f"Connecting to Flipper @ {args.serial} ...")
        fz = FlipperZero(args.serial)
        print(f"  {fz.identify()}")

        if args.rx_mode:
            r = rx_mode(fz, freq_hz, args.packets)
            print(f"\n  Received: {r['received']}/{r['n_tx']}  "
                  f"PDR: {r['pdr']*100:.1f}%")
            if r["rssi_readings"]:
                print(f"  Mean RSSI: {np.mean(r['rssi_readings']):+.1f} dBm")
        else:
            results = distance_loop(fz, freq_hz, args.packets, args.power,
                                    args.distance)
            if results:
                print_summary(results, freq_hz, args.packets)

    except KeyboardInterrupt:
        pass
    except Exception as exc:
        import traceback
        print(f"\nError: {exc}")
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
