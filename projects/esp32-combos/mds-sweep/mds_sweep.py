#!/usr/bin/env python3
"""
Automated receiver MDS (Minimum Detectable Signal) sweep.

Combines:
- scpi-atten (PE4302/HMC472) for calibrated attenuation
- SSA3032X TG for signal source
- IC-7300/IC-9700 via Hamlib for tuning and S-meter readout

Measures MDS across a frequency range by stepping attenuation until
S-meter drops to noise floor threshold.
"""

import argparse
import sys
import time
from typing import List, Tuple
import matplotlib.pyplot as plt
import numpy as np

try:
    from rf_bench.siglent.ssa3000x import SSA3000X
except ImportError:
    print("ERROR: rf-bench-drivers-siglent not installed")
    print("Install: pip install rf-bench-drivers-siglent")
    sys.exit(1)

try:
    from rf_bench.icom.rigctl import RigCtl, RadioModel
from rf_bench import connect
except ImportError:
    print("ERROR: rf-bench-drivers-icom not installed")
    print("Install: pip install rf-bench-drivers-icom")
    sys.exit(1)

try:
    import requests
except ImportError:
    print("ERROR: requests library not installed")
    print("Install: pip install requests")
    sys.exit(1)


class ScpiAtten:
    """Interface to scpi-atten ESP32 device."""

    def __init__(self, ip: str):
        self.base_url = f"http://{ip}"
        # Verify device is reachable
        try:
            resp = requests.get(f"{self.base_url}/status", timeout=2)
            resp.raise_for_status()
        except Exception as e:
            raise RuntimeError(f"Cannot reach scpi-atten at {ip}: {e}")

    def set_attenuation(self, db: float):
        """Set attenuation in dB (0.0 to 80.0 for PE4302)."""
        resp = requests.post(f"{self.base_url}/atten", json={"db": db}, timeout=2)
        resp.raise_for_status()

    def get_attenuation(self) -> float:
        """Read current attenuation in dB."""
        resp = requests.get(f"{self.base_url}/atten", timeout=2)
        resp.raise_for_status()
        return resp.json()["db"]


def measure_mds_at_freq(
    freq_hz: int,
    atten: ScpiAtten,
    ssa: SSA3000X,
    rig: RigCtl,
    tg_power_dbm: float = 0.0,
    atten_start_db: float = 0.0,
    atten_stop_db: float = 80.0,
    atten_step_db: float = 0.5,
    s_meter_threshold: int = 1
) -> Tuple[float, List[Tuple[float, int]]]:
    """
    Measure MDS at a single frequency.

    Returns:
        (mds_dbm, sweep_data) where sweep_data is [(atten_db, s_meter), ...]
    """
    # Tune radio to frequency
    rig.set_frequency(freq_hz)
    time.sleep(0.5)  # Allow radio to settle

    # Configure SSA TG
    ssa.tg_enable(True)
    ssa.tg_set_frequency(freq_hz)
    ssa.tg_set_power(tg_power_dbm)
    time.sleep(0.5)  # Allow TG to settle

    sweep_data = []
    mds_atten = None

    # Sweep attenuation from low to high
    atten_values = np.arange(atten_start_db, atten_stop_db + atten_step_db, atten_step_db)

    for att_db in atten_values:
        atten.set_attenuation(att_db)
        time.sleep(0.2)  # Allow attenuation to settle

        # Read S-meter
        s_meter = rig.get_strength()
        sweep_data.append((att_db, s_meter))

        print(f"  {freq_hz/1e6:.3f} MHz, atten {att_db:.1f} dB -> S-meter {s_meter}")

        # Check if we've reached threshold
        if s_meter <= s_meter_threshold and mds_atten is None:
            mds_atten = att_db
            # Continue for a few more steps to verify threshold
            if len([x for x in sweep_data if x[0] >= att_db]) >= 5:
                break

    # Calculate MDS
    if mds_atten is None:
        # Never reached threshold - MDS is better than our maximum attenuation
        mds_dbm = tg_power_dbm - atten_stop_db
        print(f"  WARNING: S-meter never reached threshold at {freq_hz/1e6:.3f} MHz")
    else:
        mds_dbm = tg_power_dbm - mds_atten

    return mds_dbm, sweep_data


def plot_results(freq_mhz_list: List[float], mds_dbm_list: List[float], output_file: str = "mds_sweep.png"):
    """Plot MDS vs frequency."""
    plt.figure(figsize=(12, 6))
    plt.plot(freq_mhz_list, mds_dbm_list, 'b.-', linewidth=2, markersize=8)
    plt.grid(True, alpha=0.3)
    plt.xlabel('Frequency (MHz)', fontsize=12)
    plt.ylabel('MDS (dBm)', fontsize=12)
    plt.title('Receiver Minimum Detectable Signal vs Frequency', fontsize=14, fontweight='bold')

    # Add horizontal reference lines
    plt.axhline(y=-120, color='g', linestyle='--', alpha=0.5, label='Good (-120 dBm)')
    plt.axhline(y=-100, color='orange', linestyle='--', alpha=0.5, label='Fair (-100 dBm)')

    plt.legend()
    plt.tight_layout()
    plt.savefig(output_file, dpi=150)
    print(f"\nPlot saved to {output_file}")


def main():
    parser = argparse.ArgumentParser(
        description="Automated receiver MDS sweep using scpi-atten + SSA3032X TG + Hamlib",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # HF sweep 7-30 MHz, IC-7300
  %(prog)s --esp-atten 10.1.0.50 --ssa 10.1.0.40 --radio IC7300 \\
           --freq-start 7.0 --freq-stop 30.0 --step 1.0

  # VHF sweep 144-148 MHz, IC-9700
  %(prog)s --esp-atten 10.1.0.50 --ssa 10.1.0.40 --radio IC9700 \\
           --freq-start 144.0 --freq-stop 148.0 --step 0.5

Hardware setup:
  SSA3032X TG output -> scpi-atten input -> scpi-atten output -> radio antenna input

  Verify TG output power with calibrated power meter before first use.
        """
    )

    parser.add_argument('--esp-atten', required=True, help='scpi-atten IP address')
    parser.add_argument('--ssa', required=True, help='SSA3032X IP address')
    parser.add_argument('--rigctld-host', default='localhost', help='rigctld host (default: localhost)')
    parser.add_argument('--rigctld-port', type=int, default=4532, help='rigctld port (default: 4532)')
    parser.add_argument('--radio', required=True, choices=['IC7300', 'IC9700'], help='Radio model')

    parser.add_argument('--freq-start', type=float, required=True, help='Start frequency (MHz)')
    parser.add_argument('--freq-stop', type=float, required=True, help='Stop frequency (MHz)')
    parser.add_argument('--step', type=float, required=True, help='Frequency step (MHz)')

    parser.add_argument('--tg-power', type=float, default=0.0, help='TG output power (dBm, default: 0.0)')
    parser.add_argument('--atten-start', type=float, default=0.0, help='Starting attenuation (dB, default: 0.0)')
    parser.add_argument('--atten-stop', type=float, default=80.0, help='Maximum attenuation (dB, default: 80.0)')
    parser.add_argument('--atten-step', type=float, default=0.5, help='Attenuation step (dB, default: 0.5)')
    parser.add_argument('--s-threshold', type=int, default=1, help='S-meter threshold (default: 1 = S1)')

    parser.add_argument('--output', default='mds_sweep.png', help='Output plot filename (default: mds_sweep.png)')

    args = parser.parse_args()

    # Initialize hardware
    print("Initializing hardware...")
    atten = ScpiAtten(args.esp_atten)
    ssa = connect(args.ssa or 'ssa')

    radio_model = RadioModel.IC7300 if args.radio == 'IC7300' else RadioModel.IC9700
    rig = RigCtl(host=args.rigctld_host, port=args.rigctld_port, model=radio_model)

    # Verify initial state
    print(f"scpi-atten: {atten.get_attenuation():.1f} dB")
    print(f"Radio: {rig.get_frequency()/1e6:.3f} MHz")
    print(f"SSA TG: {'ON' if ssa.tg_is_enabled() else 'OFF'}")

    # Generate frequency list
    freq_mhz_list = np.arange(args.freq_start, args.freq_stop + args.step, args.step)
    freq_hz_list = [int(f * 1e6) for f in freq_mhz_list]

    print(f"\nStarting MDS sweep:")
    print(f"  Frequency range: {args.freq_start:.3f} - {args.freq_stop:.3f} MHz")
    print(f"  Step: {args.step:.3f} MHz ({len(freq_hz_list)} points)")
    print(f"  TG power: {args.tg_power:.1f} dBm")
    print(f"  Attenuation range: {args.atten_start:.1f} - {args.atten_stop:.1f} dB")
    print(f"  S-meter threshold: S{args.s_threshold}")
    print()

    mds_dbm_list = []
    all_sweep_data = []

    try:
        for freq_hz in freq_hz_list:
            print(f"Measuring {freq_hz/1e6:.3f} MHz...")
            mds_dbm, sweep_data = measure_mds_at_freq(
                freq_hz,
                atten,
                ssa,
                rig,
                tg_power_dbm=args.tg_power,
                atten_start_db=args.atten_start,
                atten_stop_db=args.atten_stop,
                atten_step_db=args.atten_step,
                s_meter_threshold=args.s_threshold
            )
            mds_dbm_list.append(mds_dbm)
            all_sweep_data.append((freq_hz, sweep_data))
            print(f"  MDS: {mds_dbm:.1f} dBm\n")

    finally:
        # Cleanup
        print("Cleaning up...")
        ssa.tg_enable(False)
        atten.set_attenuation(0.0)

    # Print summary
    print("\n" + "="*60)
    print("MDS SWEEP RESULTS")
    print("="*60)
    print(f"{'Frequency (MHz)':<20} {'MDS (dBm)':<15}")
    print("-"*60)
    for freq_mhz, mds_dbm in zip(freq_mhz_list, mds_dbm_list):
        print(f"{freq_mhz:<20.3f} {mds_dbm:<15.1f}")
    print("-"*60)
    print(f"{'Best MDS:':<20} {min(mds_dbm_list):.1f} dBm at {freq_mhz_list[mds_dbm_list.index(min(mds_dbm_list))]:.3f} MHz")
    print(f"{'Worst MDS:':<20} {max(mds_dbm_list):.1f} dBm at {freq_mhz_list[mds_dbm_list.index(max(mds_dbm_list))]:.3f} MHz")
    print(f"{'Average MDS:':<20} {np.mean(mds_dbm_list):.1f} dBm")
    print("="*60)

    # Plot results
    plot_results(list(freq_mhz_list), mds_dbm_list, args.output)


if __name__ == '__main__':
    main()
