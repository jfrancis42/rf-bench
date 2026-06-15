#!/usr/bin/env python3
"""
Siglent SDM3045X → Virtual Numeric Display (Nixie format)

Reads the current measurement from the Siglent bench DMM and displays it
on the virtual numeric display in Nixie tube style at 1 Hz intervals.

Author: Jeff Francis (N0GQ) <gjfrancis@protonmail.com>
License: GPL-3.0-or-later
"""

import time
import sys
from pathlib import Path

# Add drivers to path
sys.path.insert(0, str(Path(__file__).parent / "../../drivers/siglent"))
sys.path.insert(0, str(Path(__file__).parent / "../../drivers/virtual-numeric-display"))

from rf_bench.siglent import SDM3000X
from rf_bench.virtual import VirtualNumericDisplay


def main():
    """Read DMM and display on virtual Nixie display."""

    # Connect to instruments
    dmm_host = "10.1.1.63"  # May need to scan network if IP changed
    display_host = "localhost"
    display_port = 5000  # SCPI port for single-instance backend

    print(f"Connecting to SDM3045X at {dmm_host}...")
    try:
        dmm = SDM3000X(dmm_host, timeout=2.0)
    except Exception as e:
        print(f"ERROR: Could not connect to DMM: {e}")
        print("The meter may be off or at a different IP address.")
        print("Try running 'nmap -sn 10.1.0.0/23' to find it.")
        sys.exit(1)

    print(f"Connecting to Virtual Numeric Display at {display_host}:{display_port}...")
    display = VirtualNumericDisplay(display_host, port=display_port)

    # Configure display for Nixie tube style
    print("Configuring Nixie display...")
    display.set_style("NIXIE")  # Use NIXIE style (not 7SEG or LED)
    display.set_color("#ff6600")  # Orange glow like Nixie tubes
    display.set_precision(4)
    display.set_units("Bench Meter")  # Static label since DMM doesn't report function

    print("\nReading DMM and updating display at 1 Hz...")
    print("View at: http://10.1.0.11:8000")
    print("Press Ctrl+C to stop\n")
    print("NOTE: Units are not auto-detected. The display shows the raw value")
    print("      from whatever function is currently selected on the meter.\n")

    try:
        while True:
            # Read current measurement from DMM (just returns float)
            value = dmm.read()

            # Update display
            display.set_value(value)

            # Print to console for monitoring
            print(f"  {value:>12.4f}", flush=True)

            # Wait 1 second
            time.sleep(1.0)

    except KeyboardInterrupt:
        print("\n\nStopping...")
    finally:
        dmm.close()
        display.close()
        print("Done.")


if __name__ == "__main__":
    main()
