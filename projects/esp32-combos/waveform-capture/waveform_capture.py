#!/usr/bin/env python3
"""
Arbitrary waveform recorder/playback combining scpi-adc (ADS1115) + scpi-relay (trigger) + SDG1062X.

Captures voltage waveforms via ADS1115 and replays them on a Siglent SDG1062X arbitrary waveform generator.
"""

import argparse
import csv
import time
import sys
from pathlib import Path

try:
    from rf_bench.siglent import SDG1000X
from rf_bench import connect
except ImportError:
    print("ERROR: rf_bench.siglent not found. Install with: pip install rf-bench-drivers-siglent")
    sys.exit(1)

try:
    import pyvisa
except ImportError:
    print("ERROR: pyvisa not found. Install with: pip install pyvisa pyvisa-py")
    sys.exit(1)


class SCPIDevice:
    """Generic SCPI device wrapper."""

    def __init__(self, ip_address, timeout=5000):
        self.rm = pyvisa.ResourceManager('@py')
        self.inst = self.rm.open_resource(f'TCPIP::{ip_address}::5025::SOCKET')
        self.inst.read_termination = '\n'
        self.inst.write_termination = '\n'
        self.inst.timeout = timeout

    def write(self, cmd):
        self.inst.write(cmd)

    def query(self, cmd):
        return self.inst.query(cmd).strip()

    def close(self):
        self.inst.close()
        self.rm.close()


def capture_waveform(adc_ip, channel, sample_rate, duration_sec, trigger_mode, relay_ip=None):
    """
    Capture waveform from scpi-adc device.

    Args:
        adc_ip: IP address of scpi-adc (ADS1115) device
        channel: ADC channel (0-3)
        sample_rate: Samples per second (max 860)
        duration_sec: Capture duration in seconds
        trigger_mode: 'auto' or 'relay'
        relay_ip: IP address of scpi-relay device (required if trigger_mode='relay')

    Returns:
        List of (timestamp, voltage) tuples
    """
    if sample_rate > 860:
        print(f"WARNING: ADS1115 max sample rate is 860 SPS, clamping from {sample_rate}")
        sample_rate = 860

    num_samples = int(sample_rate * duration_sec)
    sample_interval = 1.0 / sample_rate

    print(f"Configuring ADC at {adc_ip} for {num_samples} samples at {sample_rate} SPS...")
    adc = SCPIDevice(adc_ip)

    # Configure ADC channel and gain
    adc.write(f"CONF:VOLT:DC (@{channel})")
    adc.write(f"SENS:VOLT:DC:RANG 4.096")  # +/- 4.096V range for best resolution

    # Wait for trigger
    if trigger_mode == 'relay':
        if not relay_ip:
            raise ValueError("relay_ip required when trigger_mode='relay'")
        print(f"Waiting for trigger from relay at {relay_ip}...")
        relay = SCPIDevice(relay_ip)
        # Poll digital input until high
        while True:
            state = relay.query("SOUR:DIG:DATA:BYTE?")
            if int(state) & 0x01:  # Check bit 0
                break
            time.sleep(0.01)
        relay.close()
        print("Trigger detected!")
    else:
        print("Auto-trigger mode: starting capture immediately")

    # Capture samples
    print(f"Capturing {num_samples} samples...")
    samples = []
    start_time = time.time()

    for i in range(num_samples):
        timestamp = time.time() - start_time
        voltage = float(adc.query("READ?"))
        samples.append((timestamp, voltage))

        # Progress indicator
        if (i + 1) % max(1, num_samples // 10) == 0:
            percent = 100 * (i + 1) / num_samples
            print(f"  {percent:.0f}% complete ({i+1}/{num_samples})")

        # Sleep until next sample (account for measurement time)
        elapsed = time.time() - start_time
        target_time = (i + 1) * sample_interval
        sleep_time = target_time - elapsed
        if sleep_time > 0:
            time.sleep(sleep_time)

    adc.close()
    print(f"Capture complete: {len(samples)} samples in {samples[-1][0]:.3f} seconds")
    return samples


def save_csv(samples, filename):
    """Save samples to CSV file."""
    print(f"Saving to {filename}...")
    with open(filename, 'w', newline='') as f:
        writer = csv.writer(f)
        writer.writerow(['timestamp', 'voltage'])
        writer.writerows(samples)
    print(f"Saved {len(samples)} samples to {filename}")


def upload_to_sdg(samples, sdg_ip, sdg_channel):
    """
    Upload waveform to SDG1062X arbitrary waveform memory.

    Args:
        samples: List of (timestamp, voltage) tuples
        sdg_ip: IP address of SDG1062X
        sdg_channel: SDG channel (1 or 2)
    """
    print(f"Uploading waveform to SDG1062X at {sdg_ip} channel {sdg_channel}...")

    # Extract voltage values only
    voltages = [v for _, v in samples]

    # SDG1062X has 14-bit resolution; normalize to +/- 1.0 for arbitrary waveform
    v_min = min(voltages)
    v_max = max(voltages)
    v_range = v_max - v_min

    if v_range == 0:
        print("WARNING: Flat waveform detected (all samples identical)")
        normalized = [0.0] * len(voltages)
    else:
        # Normalize to -1.0 to +1.0 range
        normalized = [(2.0 * (v - v_min) / v_range) - 1.0 for v in voltages]

    print(f"  Voltage range: {v_min:.4f}V to {v_max:.4f}V")
    print(f"  Normalized to -1.0 to +1.0 for SDG arbitrary waveform")

    # Connect to SDG
    sdg = SDG1000X(sdg_ip)

    # Upload waveform (SDG1000X driver handles the protocol)
    arb_name = f"CAPTURE_{int(time.time())}"
    print(f"  Creating arbitrary waveform '{arb_name}'...")

    # Convert to SDG format (14-bit integer: -8191 to +8191)
    sdg_data = [int(v * 8191) for v in normalized]

    # Build SCPI command for arbitrary waveform upload
    # Format: DATA VOLATILE,<val1>,<val2>,...
    data_str = ','.join(map(str, sdg_data))
    sdg.inst.write(f"C{sdg_channel}:WVDT WVNM,{arb_name}")
    sdg.inst.write(f"C{sdg_channel}:WVDT LENGTH,{len(sdg_data)}")
    sdg.inst.write(f"C{sdg_channel}:WVDT DATA,{data_str}")

    # Configure channel to use the arbitrary waveform
    sdg.inst.write(f"C{sdg_channel}:BSWV WVTP,ARB")
    sdg.inst.write(f"C{sdg_channel}:BSWV ARB,{arb_name}")
    sdg.inst.write(f"C{sdg_channel}:BSWV AMP,{v_range}V")
    sdg.inst.write(f"C{sdg_channel}:BSWV OFST,{(v_min + v_max) / 2}V")

    # Set output trigger mode to external (burst mode)
    sdg.inst.write(f"C{sdg_channel}:BTWV STATE,ON")
    sdg.inst.write(f"C{sdg_channel}:BTWV TRSR,EXT")
    sdg.inst.write(f"C{sdg_channel}:BTWV TIME,{samples[-1][0]}S")

    # Enable output
    sdg.inst.write(f"C{sdg_channel}:OUTP ON")

    print(f"  Waveform uploaded and configured for external trigger")
    print(f"  Amplitude: {v_range:.4f}V, Offset: {(v_min + v_max) / 2:.4f}V")
    print(f"  Duration: {samples[-1][0]:.3f}s")

    sdg.close()


def main():
    parser = argparse.ArgumentParser(
        description='Capture waveforms from scpi-adc and replay on SDG1062X',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Capture 1 second at 860 SPS, auto-trigger
  %(prog)s --esp-adc 10.1.0.100 --sdg 10.1.0.50 --channel 0 --sample-rate 860 --duration-sec 1

  # Capture with hardware trigger from relay
  %(prog)s --esp-adc 10.1.0.100 --esp-relay 10.1.0.101 --sdg 10.1.0.50 \\
           --channel 0 --sample-rate 500 --duration-sec 2 --trigger-mode relay
        """
    )

    parser.add_argument('--esp-adc', required=True, help='IP address of scpi-adc (ADS1115) device')
    parser.add_argument('--esp-relay', help='IP address of scpi-relay device (for trigger)')
    parser.add_argument('--sdg', required=True, help='IP address of SDG1062X')
    parser.add_argument('--channel', type=int, default=0, choices=[0, 1, 2, 3],
                        help='ADC channel (0-3, default: 0)')
    parser.add_argument('--sdg-channel', type=int, default=1, choices=[1, 2],
                        help='SDG output channel (1 or 2, default: 1)')
    parser.add_argument('--sample-rate', type=int, default=860,
                        help='Samples per second (max 860 for ADS1115, default: 860)')
    parser.add_argument('--duration-sec', type=float, default=1.0,
                        help='Capture duration in seconds (default: 1.0)')
    parser.add_argument('--trigger-mode', choices=['auto', 'relay'], default='auto',
                        help='Trigger mode: auto (immediate) or relay (wait for digital input)')
    parser.add_argument('--output', type=Path, default=Path('waveform_capture.csv'),
                        help='Output CSV filename (default: waveform_capture.csv)')
    parser.add_argument('--no-upload', action='store_true',
                        help='Skip uploading to SDG (capture only)')

    args = parser.parse_args()

    if args.trigger_mode == 'relay' and not args.esp_relay:
        parser.error("--esp-relay required when --trigger-mode=relay")

    try:
        # Capture waveform
        samples = capture_waveform(
            args.esp_adc,
            args.channel,
            args.sample_rate,
            args.duration_sec,
            args.trigger_mode,
            args.esp_relay
        )

        # Save to CSV
        save_csv(samples, args.output)

        # Upload to SDG unless --no-upload
        if not args.no_upload:
            upload_to_sdg(samples, args.sdg, args.sdg_channel)
            print("\nWaveform ready for playback!")
            print(f"Trigger the SDG externally to replay the captured waveform on channel {args.sdg_channel}")
        else:
            print("\nCapture complete (upload skipped)")

    except KeyboardInterrupt:
        print("\n\nAborted by user")
        sys.exit(1)
    except Exception as e:
        print(f"\nERROR: {e}")
        sys.exit(1)


if __name__ == '__main__':
    main()
