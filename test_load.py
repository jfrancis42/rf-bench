#!/usr/bin/env python3
"""
Quick test of ET5406A+ electronic load after switching to ET54.py wrapper.

Hardware setup:
- ET5406A+ connected via USB (CH340 → /dev/ttyUSB0 on greybox)
- SPD3303X-E CH1 providing 13.8V input to the load

Tests:
1. Connection and identification
2. CC mode at 0.5A, 1.0A, 1.5A
3. Measurements (V, I, P, R)
4. Input on/off control
5. Safe shutdown
"""

import sys
import time

try:
    from rf_bench.yertai import ET5406A, ET5406AError
except ImportError:
    print("Error: rf-bench-drivers-yertai not installed")
    print("Run: pip install -e ~/Dropbox/build/rf-bench/drivers/yertai/ --break-system-packages")
    sys.exit(1)


def main():
    print("=" * 70)
    print("ET5406A+ Electronic Load Test")
    print("=" * 70)

    # Connect
    print("\n[1] Connecting to load...")
    try:
        load = ET5406A()
        print(f"  ✓ Connected")
        print(f"    Model:    {load.model}")
        print(f"    Serial:   {load.serial_n}")
        print(f"    Firmware: {load.firmware}")
        print(f"    Hardware: {load.hardware}")
    except ET5406AError as e:
        print(f"  ✗ Connection failed: {e}")
        sys.exit(1)

    try:
        # Initial state
        print("\n[2] Initial state")
        print(f"    Mode:       {load.mode}")
        print(f"    Input:      {load.input}")
        print(f"    Protection: {load.protection}")

        # Turn off initially to start clean
        print("\n[3] Turning off input...")
        load.off()
        time.sleep(0.5)
        print(f"    Input: {load.input}")

        # Test CC mode at different currents
        test_currents = [0.5, 1.0, 1.5]

        for current in test_currents:
            print(f"\n[4] Testing CC mode at {current} A")

            # Set CC mode
            print(f"    Setting CC {current} A...")
            load.CC_mode(current)
            time.sleep(0.3)
            print(f"    Mode: {load.mode}")
            print(f"    CC setpoint: {load.CC_current} A")

            # Turn on
            print(f"    Turning on input...")
            load.on()
            time.sleep(1.0)  # Allow settling

            # Read measurements
            v, i, p, r = load.read_all()
            print(f"    Measurements:")
            print(f"      Voltage:    {v:.3f} V")
            print(f"      Current:    {i:.3f} A")
            print(f"      Power:      {p:.3f} W")
            print(f"      Resistance: {r:.3f} Ω")

            # Verify current is approximately correct (±10%)
            if abs(i - current) < current * 0.1:
                print(f"    ✓ Current within 10% of setpoint")
            else:
                print(f"    ⚠ Current deviation: expected {current} A, got {i:.3f} A")

            # Turn off
            load.off()
            time.sleep(0.5)

        # Test input on/off
        print(f"\n[5] Testing input on/off")
        print(f"    Setting CC 0.5 A...")
        load.CC_mode(0.5)
        time.sleep(0.3)

        print(f"    Input OFF...")
        load.off()
        time.sleep(0.3)
        print(f"      Input: {load.input}")

        print(f"    Input ON...")
        load.on()
        time.sleep(0.3)
        print(f"      Input: {load.input}")
        i = load.read_current()
        print(f"      Current: {i:.3f} A")

        print(f"    Input OFF...")
        load.off()
        time.sleep(0.3)
        print(f"      Input: {load.input}")

        # Check protection state
        print(f"\n[6] Checking protection")
        prot = load.protection
        print(f"    Protection: {prot}")
        if prot == "NONE":
            print(f"    ✓ No protection faults")
        else:
            print(f"    ⚠ Protection fault active: {prot}")

        # Final state
        print(f"\n[7] Final state")
        print(f"    Turning off input...")
        load.off()
        time.sleep(0.3)
        print(f"    Input: {load.input}")
        print(f"    Mode:  {load.mode}")

        print("\n[8] Cleanup")
        print("    Closing connection...")
        load.close()

        print("\n" + "=" * 70)
        print("✓ Test completed successfully")
        print("=" * 70)

    except Exception as e:
        print(f"\n✗ Test failed: {e}")
        import traceback
        traceback.print_exc()

        # Emergency shutdown
        try:
            print("\nEmergency shutdown...")
            load.off()
            load.close()
        except:
            pass

        sys.exit(1)


if __name__ == "__main__":
    main()
