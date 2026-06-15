#!/usr/bin/env python3
"""
Virtual Numeric Display Nixie Demo

Displays simulated DMM readings on the virtual numeric display in Nixie tube
style at 1 Hz intervals. Uses random walk to simulate realistic meter drift.

Author: Jeff Francis (N0GQ) <gjfrancis@protonmail.com>
License: GPL-3.0-or-later
"""

import time
import random
from rf_bench.virtual import VirtualNumericDisplay


def main():
    """Display simulated DMM readings on virtual Nixie display."""

    # TODO: Add virtual display to inventory when multi-instance support is ready
    # For now, virtual instruments require explicit connection
    print("Connecting to Virtual Numeric Display...")
    display = VirtualNumericDisplay("localhost", port=5000)

    # Configure display for Nixie tube style
    print("Configuring Nixie display...")
    display.set_style("NIXIE")  # Use NIXIE style (not 7SEG or LED)
    display.set_color("#ff6600")  # Orange glow like Nixie tubes
    display.set_precision(4)
    display.set_units("Bench Meter")

    print("\nSimulating DMM readings at 1 Hz...")
    print("View at: http://localhost:8000")
    print("Press Ctrl+C to stop\n")

    # Start with a realistic voltage
    value = 13.8000
    measurement_types = [
        ("VDC", 13.8000, 0.001),
        ("VAC", 120.000, 0.05),
        ("IDC", 2.5000, 0.0001),
        ("OHM", 1000.00, 0.5),
    ]

    try:
        count = 0
        current_mode = 0

        while True:
            # Random walk to simulate realistic drift
            value += random.gauss(0, measurement_types[current_mode][2])
            value = max(0, value)  # No negative values

            # Update display
            display.set_value(value)
            display.set_units(measurement_types[current_mode][0])

            # Print to console for monitoring
            print(f"  {value:>10.4f} {measurement_types[current_mode][0]:<4s}", flush=True)

            count += 1

            # Switch measurement type every 15 seconds
            if count % 15 == 0:
                current_mode = (current_mode + 1) % len(measurement_types)
                value = measurement_types[current_mode][1]
                print(f"\n  → Switching to {measurement_types[current_mode][0]}\n")

            # Wait 1 second
            time.sleep(1.0)

    except KeyboardInterrupt:
        print("\n\nStopping...")
    finally:
        display.close()
        print("Done.")


if __name__ == "__main__":
    main()
