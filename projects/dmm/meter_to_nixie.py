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
from rf_bench import connect


def main():
    """Read DMM and display on virtual Nixie display."""

    print("Connecting to instruments via inventory...")
    try:
        dmm = connect('sdm')
        # TODO: Add virtual display to inventory when multi-instance support is ready
        # For now, virtual instruments require explicit connection
        from rf_bench.virtual import VirtualNumericDisplay
        display = VirtualNumericDisplay("localhost", port=5000)
    except Exception as e:
        print(f"ERROR: Could not connect to instruments: {e}")
        print("Check that SDM3045X is powered on and inventory.yaml has correct IP.")
        sys.exit(1)

    print("Connected successfully.")

    # Configure display for Nixie tube style
    print("Configuring Nixie display...")
    display.set_style("NIXIE")  # Use NIXIE style (not 7SEG or LED)
    display.set_color("#ff6600")  # Orange glow like Nixie tubes
    display.set_precision(4)
    display.set_units("Bench Meter")  # Static label since DMM doesn't report function

    print("\nReading DMM and updating display at 1 Hz...")
    print("View at: http://localhost:8000")
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
