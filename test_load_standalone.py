#!/usr/bin/env python3
"""
Standalone test of ET5406A+ electronic load - includes driver inline.
No installation required, just needs ET54, pyvisa, pyvisa-py, pyserial.

Copy this file to greybox and run:
  python3 test_load_standalone.py
"""

import sys
import time
import serial.tools.list_ports

# Check dependencies
try:
    from ET54 import ET54
except ImportError:
    print("Error: ET54 library not installed")
    print("Run: pip3 install ET54 pyvisa pyvisa-py pyserial --break-system-packages")
    sys.exit(1)


# ============================================================================
# ET5406A Driver (inline)
# ============================================================================

class ET5406AError(Exception):
    pass


class ET5406A:
    """Yertai ET5406A+ programmable DC load driver."""

    def __init__(self, port=None, baudrate=9600, timeout=2.0):
        """Initialize ET5406A+ electronic load.

        Args:
            port: Serial port path. If None, auto-detects CH340.
            baudrate: Serial baud rate (default 9600)
            timeout: Serial timeout in seconds (default 2.0)
        """
        if port is None:
            port = self._find_port()

        # Convert port to VISA resource string
        visa_resource = f"ASRL{port}::INSTR"

        # Initialize upstream ET54 library
        try:
            self._inst = ET54(
                visa_resource,
                baudrate=baudrate,
                timeout=int(timeout * 1000)
            )
        except Exception as e:
            raise ET5406AError(f"Failed to connect to ET5406A+ at {port}: {e}")

        # Single-channel device — expose ch1 directly
        self._ch = self._inst.ch1

        # Extract identification from upstream
        self.model = self._inst.idn.get("model", "ET5406A+")
        self.serial_n = self._inst.idn.get("SN", "")
        self.firmware = self._inst.idn.get("firmware", "")
        self.hardware = self._inst.idn.get("hardware", "")

    @staticmethod
    def _find_port():
        """Return the first CH340 serial port found."""
        for p in serial.tools.list_ports.comports():
            hwid = (p.hwid or "").lower()
            desc = (p.description or "").lower()
            if "1a86:7523" in hwid or "ch340" in desc or "ch341" in desc:
                return p.device
        raise ET5406AError(
            "No ET5406A+ found (no CH340 adapter detected). "
            "Pass port= explicitly, e.g. ET5406A('/dev/ttyUSB0')."
        )

    def close(self):
        """Unlock front panel and close connection."""
        try:
            self._inst.unlock()
            self._inst.close()
        except:
            pass

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()

    # Delegate all other methods to self._ch (channel 1)
    def __getattr__(self, name):
        return getattr(self._ch, name)

    # Override read_all() to fix field order (maintain backward compatibility)
    def read_all(self):
        """Read all measurements. Returns (voltage, current, power, resistance)."""
        # Upstream returns (current, voltage, power, resistance)
        # We return (voltage, current, power, resistance) for backward compatibility
        c, v, p, r = self._ch.read_all()
        return (v, c, p, r)


# ============================================================================
# Test Script
# ============================================================================

def main():
    print("=" * 70)
    print("ET5406A+ Electronic Load Test (Standalone)")
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
        print("\nTrying explicit port /dev/ttyUSB0...")
        try:
            load = ET5406A("/dev/ttyUSB0")
            print(f"  ✓ Connected via /dev/ttyUSB0")
            print(f"    Model:    {load.model}")
            print(f"    Serial:   {load.serial_n}")
        except ET5406AError as e:
            print(f"  ✗ Still failed: {e}")
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
