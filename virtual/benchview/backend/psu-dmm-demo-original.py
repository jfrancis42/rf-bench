#!/usr/bin/env python3
"""
PSU-DMM Feedback Demo

Interactive BenchView application:
- Slider controls SPD3303X CH1 output voltage (0-32V)
- Numeric display shows SDM3045X actual measurement in Nixie style
- Real-time feedback loop shows PSU accuracy

Hardware setup:
  SPD3303X CH1+ → SDM3045X VΩ input (red)
  SPD3303X CH1- → SDM3045X COM (black)

Usage:
  1. Start BenchView with this panel (it will launch virtual instruments)
  2. Run this glue script
  3. Open browser to http://localhost:8350
  4. Move the slider to set voltage, watch the display update
"""

import sys
import time
import yaml
from pathlib import Path

from rf_bench import connect


def main():
    print("=== PSU-DMM Feedback Demo ===\n")

    # Load BenchView port assignments
    ports_file = Path(__file__).parent / "psu-dmm-demo_ports.yaml"
    if not ports_file.exists():
        print(f"ERROR: BenchView port assignments not found: {ports_file}")
        print("Please start BenchView first:")
        print("  python benchview.py psu-dmm-demo.yaml")
        sys.exit(1)

    with open(ports_file) as f:
        ports_data = yaml.safe_load(f)

    slider_port = ports_data['instruments']['voltage-slider']['scpi_port']
    display_port = ports_data['instruments']['voltage-display']['scpi_port']

    print(f"BenchView ports loaded:")
    print(f"  Slider:  port {slider_port}")
    print(f"  Display: port {display_port}\n")

    # Connect to physical instruments via inventory
    print("Connecting to instruments via inventory...")
    try:
        psu = connect('spd')
        dmm = connect('sdm')
        print(f"  PSU: {psu.identify()}")
        print(f"  DMM: {dmm.identify()}\n")
    except Exception as e:
        print(f"ERROR: Failed to connect to instruments: {e}")
        print("Check that SPD3303X and SDM3045X are powered on.")
        sys.exit(1)

    # Connect to virtual instruments (direct connection, not via inventory yet)
    import socket

    def scpi_command(port: int, cmd: str) -> str:
        """Send SCPI command and get response."""
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.connect(('localhost', port))
            s.sendall(f"{cmd}\n".encode())
            if '?' in cmd:
                return s.recv(4096).decode().strip()
            return ""

    # Configure PSU CH1
    print("Configuring PSU channel 1...")
    psu.set_voltage(1, 0.0)  # Start at 0V
    psu.set_current(1, 0.5)  # 500mA current limit
    psu.enable(1)  # Enable output
    print("  CH1 enabled, 0.0V, 500mA limit\n")

    # Configure DMM for DC voltage measurement
    print("Configuring DMM for DC voltage...")
    dmm.configure_vdc()
    print("  DC voltage mode selected\n")

    # Configure virtual slider (instance 1)
    print("Configuring virtual slider...")
    scpi_command(slider_port, "CONF1:MIN 0.0")
    scpi_command(slider_port, "CONF1:MAX 32.0")
    scpi_command(slider_port, "CONF1:STEP 0.1")
    scpi_command(slider_port, "CONF1:UNIT V")
    scpi_command(slider_port, "CONF1:LAB PSU CH1 Voltage")
    print("  Slider configured: 0-32V, 0.1V step\n")

    # Configure virtual display (instance 1)
    print("Configuring virtual display...")
    scpi_command(display_port, "CONF1:STYLE NIXIE")
    scpi_command(display_port, "CONF1:COL #ff6600")
    scpi_command(display_port, "CONF1:PREC 3")
    scpi_command(display_port, "CONF1:UNIT V")
    print("  Display configured: NIXIE style, orange, 3 decimals\n")

    print("Running feedback loop...")
    print("Open browser: http://localhost:8200")
    print("Move the slider to set voltage\n")
    print("Press Ctrl+C to stop\n")
    print(f"{'Time':>8}  {'Slider':>8}  {'PSU Set':>8}  {'DMM Read':>8}  {'Error':>8}")
    print("-" * 60)

    last_slider_value = None

    try:
        while True:
            # Read slider position (slider index 1)
            slider_str = scpi_command(slider_port, "SOUR1:VAL?")
            try:
                slider_value = float(slider_str)
            except:
                slider_value = 0.0

            # Only update PSU if slider changed (reduces SCPI traffic)
            if slider_value != last_slider_value:
                psu.set_voltage(1, slider_value)
                last_slider_value = slider_value
                time.sleep(0.1)  # Let PSU settle

            # Read DMM
            dmm_value = dmm.read()

            # Update display (display index 1)
            scpi_command(display_port, f"MEAS1:VAL {dmm_value}")

            # Calculate error
            error = dmm_value - slider_value

            # Print status
            timestamp = time.strftime("%H:%M:%S")
            print(f"{timestamp}  {slider_value:>7.3f}V  {slider_value:>7.3f}V  "
                  f"{dmm_value:>7.3f}V  {error:>+7.3f}V", flush=True)

            time.sleep(0.2)  # 5 Hz update rate

    except KeyboardInterrupt:
        print("\n\nStopping...")
    finally:
        # Clean shutdown
        print("Disabling PSU output...")
        psu.set_voltage(1, 0.0)
        psu.disable(1)
        psu.close()
        dmm.close()
        print("Done.")


if __name__ == "__main__":
    main()
