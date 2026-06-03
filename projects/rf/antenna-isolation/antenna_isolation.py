#!/usr/bin/env python3
"""
Dual-Radio Antenna Isolation Measurement

Measures isolation between two antenna systems using IC-7300 × 2.
Radio 1 transmits CW through a fixed attenuator; Radio 2 reads S-meter.
Isolation = TX_power_dbm - atten_db - RX_power_dbm.

SAFETY: --atten must be specified. Script aborts if estimated RX level > -20 dBm.

Usage:
    python antenna_isolation.py --atten 60
    python antenna_isolation.py --atten 60 --rig1-port 4532 --rig2-port 4533
    python antenna_isolation.py --atten 60 --power 1 --bands 40m,20m,15m
"""

import argparse
import sys
import time

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

from rf_bench.icom import IC7300, IC9700
from rf_bench.utils import watts_to_dbm, format_freq

BANDS = {
    "160m": 1_850_000, "80m": 3_700_000, "60m": 5_358_500,
    "40m":  7_150_000, "30m": 10_125_000, "20m": 14_200_000,
    "17m": 18_118_000, "15m": 21_250_000, "12m": 24_930_000,
    "10m": 28_500_000, "6m":  51_000_000,
}
DEFAULT_BANDS = ["160m", "80m", "40m", "20m", "15m", "10m"]
# IC-7300 S-meter calibration (Hamlib STRENGTH → dBm, approximate)
# STRENGTH 0 ≈ S1 = -113 dBm; each step ≈ 6 dB
STRENGTH_TO_DBM_OFFSET = -113.0  # rough; use smeter-cal for precision


def strength_to_dbm(strength):
    """Approximate conversion from Hamlib STRENGTH to dBm."""
    return STRENGTH_TO_DBM_OFFSET + strength * 0.6


def main():
    ap = argparse.ArgumentParser(
        description="Dual-radio antenna isolation measurement",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
SAFETY: Always specify --atten with the total dB of attenuation in the TX path.
At 100 W TX (+50 dBm) with 60 dB atten, SSA sees -10 dBm — safe.
Without attenuation, the radio on the RX antenna could be damaged.
"""
    )
    ap.add_argument("--atten",      type=float, required=True,
                    help="REQUIRED: TX path attenuation in dB")
    ap.add_argument("--rig1-port",  type=int, default=4532, help="TX rigctld port")
    ap.add_argument("--rig2-port",  type=int, default=4533, help="RX rigctld port")
    ap.add_argument("--rig-host",   default="localhost")
    ap.add_argument("--radio",      choices=["ic7300", "ic9700"], default="ic7300",
                    help="Radio model for both TX and RX rigs (default: ic7300)")
    ap.add_argument("--power",      type=float, default=1.0, help="TX power in watts")
    ap.add_argument("--bands",      default=",".join(DEFAULT_BANDS),
                    help=f"Bands to test (default: {','.join(DEFAULT_BANDS)})")
    ap.add_argument("--dwell",      type=float, default=2.0,
                    help="Seconds per frequency (default 2)")
    ap.add_argument("--force",      action="store_true",
                    help="Bypass safety abort")
    ap.add_argument("--plot",       metavar="FILE", default="antenna_isolation.png")
    args = ap.parse_args()

    bands    = [b.strip() for b in args.bands.split(",")]
    power_dbm = watts_to_dbm(args.power)

    # Safety check
    worst_case_rx = power_dbm - args.atten + 20  # +20 dB margin for worst-case coupling
    if worst_case_rx > -20 and not args.force:
        print(f"SAFETY ABORT: estimated RX level = {worst_case_rx:.0f} dBm > -20 dBm")
        print(f"TX = {power_dbm:.0f} dBm, atten = {args.atten:.0f} dB")
        print("Use a larger attenuator, reduce TX power, or --force to override.")
        sys.exit(1)

    print(f"TX: {args.power} W ({power_dbm:.0f} dBm) → {args.atten:.0f} dB atten → antenna A")
    print(f"RX: antenna B → Radio 2 (S-meter)")
    print(f"Bands: {', '.join(bands)}\n")

    freq_hz_list = [BANDS[b] for b in bands if b in BANDS]
    iso_db_list  = []

    rig_cls = IC9700 if args.radio == "ic9700" else IC7300
    with rig_cls(args.rig_host, args.rig1_port) as tx_rig, \
         rig_cls(args.rig_host, args.rig2_port) as rx_rig:

        # Disable AGC on both radios for calibrated S-meter
        rx_rig.set_agc("off")
        tx_rig.set_agc("off")

        for i, freq_hz in enumerate(freq_hz_list):
            band = bands[i] if i < len(bands) else "?"
            tx_rig.set_frequency(freq_hz)
            tx_rig.set_mode("cw")
            rx_rig.set_frequency(freq_hz)
            rx_rig.set_mode("cw")
            time.sleep(0.3)

            # Key TX (CW carrier via Hamlib)
            import socket
            try:
                with socket.create_connection((args.rig_host, args.rig1_port), 2) as s:
                    s.sendall(b"T 1\n")
                    s.recv(64)
            except Exception:
                pass

            time.sleep(args.dwell)

            strength = rx_rig.get_strength_settled(settle_s=0.5, samples=3)
            rx_dbm   = strength_to_dbm(strength)
            iso      = power_dbm - args.atten - rx_dbm

            # Un-key TX
            try:
                with socket.create_connection((args.rig_host, args.rig1_port), 2) as s:
                    s.sendall(b"T 0\n")
                    s.recv(64)
            except Exception:
                pass

            iso_db_list.append(iso)
            print(f"  {band:5s} {format_freq(freq_hz):12s}  "
                  f"RX={rx_dbm:6.0f} dBm  isolation={iso:5.0f} dB")

    print(f"\n{'='*50}")
    print(f"Mean isolation: {np.mean(iso_db_list):.0f} dB")
    print(f"Min  isolation: {np.min(iso_db_list):.0f} dB")
    print(f"{'='*50}")

    # Plot
    freqs_mhz = [f / 1e6 for f in freq_hz_list]
    fig, ax = plt.subplots(figsize=(10, 5))
    ax.plot(freqs_mhz, iso_db_list, "bo-", markersize=8)
    ax.axhline(60, color="green", linestyle="--", label="60 dB reference")
    ax.set_xlabel("Frequency (MHz)")
    ax.set_ylabel("Isolation (dB)")
    ax.set_title("Antenna-to-Antenna Isolation")
    ax.legend(); ax.grid(True)
    plt.tight_layout()
    plt.savefig(args.plot, dpi=150)
    print(f"Plot saved: {args.plot}")


if __name__ == "__main__":
    main()
