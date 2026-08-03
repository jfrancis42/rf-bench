#!/usr/bin/env python3
"""
Op-amp offset voltage measurement using ESP32 scpi-mux + scpi-relay + SPD3303X + SDM3045X.

Measures Vos (input offset voltage) by configuring op-amp in unity-gain
(Vout = Vin + Vos). With Vin = 0V, Vout = Vos directly.

Hardware:
- scpi-mux: CD4067 16-channel analog multiplexer (selects DUT)
- scpi-relay: Power gating (prevents thermal crosstalk between DUTs)
- SPD3303X: Dual power supply (±15V rails)
- SDM3045X: 6.5-digit DMM (~10 µV resolution on 200 mV range)

Test circuit: Unity-gain buffer
    V+ ──┐
         │
    Vin ─┤─\
         │  >─── Vout (to DMM via scpi-mux)
    ┌────┤+/
    │    │
    │    └── V-
    │
    └────────┘ (feedback)

With Vin = 0V: Vout = Vos (input offset voltage)

Usage:
    ./opamp_offset.py --esp-mux 10.1.0.50 --esp-relay 10.1.0.51 \
                       --psu 10.1.0.44 --dmm 10.1.0.42 \
                       --duts 16 --supply-v 15.0
"""

import argparse
import time
import csv
import sys
from datetime import datetime
from pathlib import Path
from rf_bench import connect

try:
    from rf_bench.siglent.spd3303x import SPD3303X
    from rf_bench.siglent.sdm3045x import SDM3045X
except ImportError:
    print("ERROR: rf-bench Siglent drivers not found.", file=sys.stderr)
    print("Install: pip install rf-bench-drivers-siglent", file=sys.stderr)
    sys.exit(1)

try:
    import requests
except ImportError:
    print("ERROR: requests library required", file=sys.stderr)
    print("Install: pip install requests", file=sys.stderr)
    sys.exit(1)


class ScpiMux:
    """ESP32 scpi-mux CD4067 16-channel multiplexer control."""

    def __init__(self, ip):
        self.base_url = f"http://{ip}"

    def select_channel(self, channel):
        """Select channel 1-16."""
        if not 1 <= channel <= 16:
            raise ValueError(f"Channel must be 1-16, got {channel}")
        resp = requests.get(f"{self.base_url}/channel/{channel}")
        resp.raise_for_status()

    def get_channel(self):
        """Get currently selected channel."""
        resp = requests.get(f"{self.base_url}/channel")
        resp.raise_for_status()
        return int(resp.text.strip())


class ScpiRelay:
    """ESP32 scpi-relay power control."""

    def __init__(self, ip):
        self.base_url = f"http://{ip}"

    def on(self):
        """Turn relay ON (power DUT)."""
        resp = requests.get(f"{self.base_url}/on")
        resp.raise_for_status()

    def off(self):
        """Turn relay OFF (remove DUT power)."""
        resp = requests.get(f"{self.base_url}/off")
        resp.raise_for_status()

    def get_state(self):
        """Get relay state (on/off)."""
        resp = requests.get(f"{self.base_url}/state")
        resp.raise_for_status()
        return resp.text.strip().lower()


def setup_psu(psu, supply_v):
    """Configure SPD3303X for ±supply_v operation."""
    print(f"Configuring PSU for ±{supply_v}V...")

    # CH1 = +V, CH2 = -V (negative voltage)
    psu.set_voltage(1, supply_v)
    psu.set_current(1, 0.1)  # 100 mA current limit

    psu.set_voltage(2, supply_v)
    psu.set_current(2, 0.1)

    # Enable outputs
    psu.set_output(1, True)
    psu.set_output(2, True)

    time.sleep(0.5)

    # Verify voltages
    v_pos = psu.get_voltage(1)
    v_neg = psu.get_voltage(2)
    print(f"PSU: CH1 = +{v_pos:.3f}V, CH2 = -{v_neg:.3f}V")


def setup_dmm(dmm):
    """Configure SDM3045X for precision DC voltage measurement."""
    print("Configuring DMM...")

    # DC voltage mode, 200 mV range for best resolution (~10 µV)
    # Op-amp Vos typically < 10 mV, so 200 mV range is ideal
    dmm.write("CONF:VOLT:DC 0.2")  # 200 mV range
    dmm.write("VOLT:DC:NPLC 10")   # 10 PLC = ~167 ms @ 60 Hz (max averaging)
    dmm.write("VOLT:DC:AVER:COUN 10")  # 10 averages
    dmm.write("VOLT:DC:AVER:STAT ON")

    time.sleep(0.2)


def measure_offset(mux, relay, dmm, channel, settling_time=1.0):
    """Measure offset voltage for a single DUT.

    Args:
        mux: ScpiMux instance
        relay: ScpiRelay instance
        dmm: SDM3045X instance
        channel: DUT channel (1-16)
        settling_time: Seconds to wait after power-on

    Returns:
        Offset voltage in volts (float)
    """
    # Select DUT channel
    mux.select_channel(channel)
    time.sleep(0.1)

    # Power on DUT
    relay.on()
    time.sleep(settling_time)

    # Measure Vos (DMM measures op-amp output in unity-gain config)
    vos = dmm.get_voltage()

    # Power off to prevent heating adjacent DUTs
    relay.off()

    return vos


def main():
    parser = argparse.ArgumentParser(
        description="Precision op-amp offset voltage measurement",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Test 16 op-amps with ±15V supply
  ./opamp_offset.py --esp-mux 10.1.0.50 --esp-relay 10.1.0.51 \\
                     --psu 10.1.0.44 --dmm 10.1.0.42 \\
                     --duts 16 --supply-v 15.0

  # Test 8 op-amps with ±12V, 2 sec settling
  ./opamp_offset.py --esp-mux 10.1.0.50 --esp-relay 10.1.0.51 \\
                     --psu 10.1.0.44 --dmm 10.1.0.42 \\
                     --duts 8 --supply-v 12.0 --settling 2.0

Hardware setup:
  - SPD3303X CH1 → +V rail (all op-amps)
  - SPD3303X CH2 → -V rail (all op-amps)
  - scpi-relay → DUT power enable (prevents thermal crosstalk)
  - Op-amp outputs → scpi-mux channels 1-16 → SDM3045X
  - Op-amps wired in unity-gain (Vout = Vin + Vos, Vin = 0V)
        """
    )

    parser.add_argument("--esp-mux", required=True,
                        help="ESP32 scpi-mux IP address")
    parser.add_argument("--esp-relay", required=True,
                        help="ESP32 scpi-relay IP address")
    parser.add_argument("--psu", required=True,
                        help="SPD3303X PSU IP address")
    parser.add_argument("--dmm", required=True,
                        help="SDM3045X DMM IP address")
    parser.add_argument("--duts", type=int, default=16,
                        help="Number of DUTs to test (1-16, default 16)")
    parser.add_argument("--supply-v", type=float, default=15.0,
                        help="Supply voltage magnitude (±V, default 15.0)")
    parser.add_argument("--settling", type=float, default=1.0,
                        help="Settling time after power-on (sec, default 1.0)")
    parser.add_argument("--output", type=str, default=None,
                        help="Output CSV file (default: opamp_offset_YYYYMMDD_HHMMSS.csv)")

    args = parser.parse_args()

    if not 1 <= args.duts <= 16:
        parser.error("--duts must be 1-16")

    if args.supply_v <= 0:
        parser.error("--supply-v must be positive")

    # Generate output filename if not specified
    if args.output is None:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        args.output = f"opamp_offset_{timestamp}.csv"

    print("=" * 70)
    print("Op-Amp Offset Voltage Measurement")
    print("=" * 70)
    print(f"ESP32 scpi-mux:   {args.esp_mux}")
    print(f"ESP32 scpi-relay: {args.esp_relay}")
    print(f"SPD3303X PSU:     {args.psu}")
    print(f"SDM3045X DMM:     {args.dmm}")
    print(f"DUTs to test:     {args.duts}")
    print(f"Supply voltage:   ±{args.supply_v}V")
    print(f"Settling time:    {args.settling}s")
    print(f"Output file:      {args.output}")
    print("=" * 70)
    print()

    # Initialize instruments
    print("Connecting to instruments...")
    try:
        mux = ScpiMux(args.esp_mux)
        relay = ScpiRelay(args.esp_relay)
        psu = connect(args.psu or 'spd')
        dmm = SDM3045X(args.dmm)
    except Exception as e:
        print(f"ERROR: Failed to connect to instruments: {e}", file=sys.stderr)
        sys.exit(1)

    print("Connected.\n")

    # Setup instruments
    try:
        setup_psu(psu, args.supply_v)
        setup_dmm(dmm)
    except Exception as e:
        print(f"ERROR: Instrument setup failed: {e}", file=sys.stderr)
        sys.exit(1)

    # Ensure relay is off initially
    relay.off()
    time.sleep(0.2)

    print("\nStarting measurements...\n")

    results = []

    try:
        for ch in range(1, args.duts + 1):
            print(f"DUT {ch:2d}: ", end="", flush=True)

            try:
                vos = measure_offset(mux, relay, dmm, ch, args.settling)
                vos_uv = vos * 1e6  # Convert to µV

                results.append({
                    "dut": ch,
                    "vos_v": vos,
                    "vos_uv": vos_uv
                })

                print(f"Vos = {vos*1e3:+7.4f} mV ({vos_uv:+8.2f} µV)")

            except Exception as e:
                print(f"ERROR: {e}")
                results.append({
                    "dut": ch,
                    "vos_v": None,
                    "vos_uv": None
                })

            time.sleep(0.1)

    except KeyboardInterrupt:
        print("\n\nMeasurement interrupted by user.")

    finally:
        # Cleanup: turn off PSU
        print("\nShutting down PSU...")
        try:
            psu.set_output(1, False)
            psu.set_output(2, False)
            relay.off()
        except Exception as e:
            print(f"WARNING: Cleanup error: {e}", file=sys.stderr)

    # Save results to CSV
    if results:
        print(f"\nSaving results to {args.output}...")

        with open(args.output, "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=["dut", "vos_v", "vos_uv"])
            writer.writeheader()
            writer.writerows(results)

        print(f"Saved {len(results)} measurements.\n")

        # Sort by |Vos| for matched-pair selection
        valid_results = [r for r in results if r["vos_v"] is not None]
        if valid_results:
            sorted_results = sorted(valid_results, key=lambda r: abs(r["vos_v"]))

            print("=" * 70)
            print("DUTs sorted by |Vos| (best to worst):")
            print("=" * 70)
            for i, r in enumerate(sorted_results, 1):
                vos_mv = r["vos_v"] * 1e3
                vos_uv = r["vos_uv"]
                print(f"{i:2d}. DUT {r['dut']:2d}: {vos_mv:+7.4f} mV ({vos_uv:+8.2f} µV)")

            print("\nMatched pairs (adjacent in sorted list):")
            print("-" * 70)
            for i in range(0, len(sorted_results) - 1, 2):
                if i + 1 < len(sorted_results):
                    dut1 = sorted_results[i]
                    dut2 = sorted_results[i + 1]
                    delta_uv = abs(dut1["vos_uv"] - dut2["vos_uv"])
                    print(f"Pair {i//2 + 1}: DUT {dut1['dut']:2d} + DUT {dut2['dut']:2d}  "
                          f"(ΔVos = {delta_uv:.2f} µV)")

    print("\nDone.")


if __name__ == "__main__":
    main()
