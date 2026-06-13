#!/usr/bin/env python3
"""
I2C Device Characterization Tool

Compares ESP32 scpi-i2c implementation against Bus Pirate golden reference.
Power-cycles DUT via scpi-relay between tests. Logs discrepancies.
"""

import argparse
import sys
import time
import random
from typing import List, Tuple, Optional

try:
    from rf_bench.buspirate import BusPirate
except ImportError:
    print("ERROR: rf-bench-drivers-buspirate not installed")
    print("Install: pip install rf-bench-drivers-buspirate")
    sys.exit(1)

import socket


class SCPII2C:
    """SCPI-I2C instrument interface"""

    def __init__(self, host: str, port: int = 5025):
        self.host = host
        self.port = port
        self.sock = None

    def connect(self):
        """Connect to SCPI-I2C instrument"""
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.sock.settimeout(5.0)
        self.sock.connect((self.host, self.port))

    def disconnect(self):
        """Disconnect from instrument"""
        if self.sock:
            self.sock.close()
            self.sock = None

    def query(self, cmd: str) -> str:
        """Send SCPI query and return response"""
        self.sock.sendall((cmd + "\n").encode())
        response = b""
        while True:
            chunk = self.sock.recv(4096)
            if not chunk:
                break
            response += chunk
            if b"\n" in chunk:
                break
        return response.decode().strip()

    def write(self, cmd: str):
        """Send SCPI command"""
        self.sock.sendall((cmd + "\n").encode())

    def write_byte(self, addr: int, reg: int, value: int) -> bool:
        """Write single byte to I2C device register"""
        try:
            self.write(f"I2C:WRITE {addr:#x},{reg:#x},{value:#x}")
            time.sleep(0.01)
            return True
        except Exception as e:
            print(f"ESP32 write error: {e}")
            return False

    def read_byte(self, addr: int, reg: int) -> Optional[int]:
        """Read single byte from I2C device register"""
        try:
            response = self.query(f"I2C:READ? {addr:#x},{reg:#x},1")
            if response and response != "ERROR":
                return int(response, 16)
            return None
        except Exception as e:
            print(f"ESP32 read error: {e}")
            return None


class SCPIRelay:
    """SCPI-Relay instrument interface"""

    def __init__(self, host: str, port: int = 5025):
        self.host = host
        self.port = port
        self.sock = None

    def connect(self):
        """Connect to SCPI-Relay instrument"""
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.sock.settimeout(5.0)
        self.sock.connect((self.host, self.port))

    def disconnect(self):
        """Disconnect from instrument"""
        if self.sock:
            self.sock.close()
            self.sock = None

    def write(self, cmd: str):
        """Send SCPI command"""
        self.sock.sendall((cmd + "\n").encode())

    def power_cycle(self, relay: int = 1, off_time: float = 1.0):
        """Power cycle DUT via relay"""
        print(f"Power cycling DUT (relay {relay}, {off_time}s off)...")
        self.write(f"RELAY{relay}:OFF")
        time.sleep(off_time)
        self.write(f"RELAY{relay}:ON")
        time.sleep(0.5)  # Settle time


def generate_test_patterns() -> List[int]:
    """Generate test patterns for write/read verification"""
    patterns = [
        0x00, 0xFF,           # All zeros, all ones
        0xAA, 0x55,           # Alternating bits
        0x01, 0x02, 0x04, 0x08, 0x10, 0x20, 0x40, 0x80,  # Walking 1s
        0xFE, 0xFD, 0xFB, 0xF7, 0xEF, 0xDF, 0xBF, 0x7F,  # Walking 0s
    ]
    # Add some random patterns
    patterns.extend([random.randint(0, 255) for _ in range(8)])
    return patterns


def compare_read(esp_i2c: SCPII2C, buspirate: BusPirate,
                 addr: int, reg: int) -> Tuple[Optional[int], Optional[int], bool]:
    """Read from both ESP32 and Bus Pirate, compare results"""

    # ESP32 read
    esp_value = esp_i2c.read_byte(addr, reg)

    # Bus Pirate read (write register address, then read 1 byte)
    try:
        buspirate.i2c_start()
        buspirate.i2c_write_byte((addr << 1) | 0)  # Write mode
        buspirate.i2c_write_byte(reg)
        buspirate.i2c_start()  # Repeated start
        buspirate.i2c_write_byte((addr << 1) | 1)  # Read mode
        bp_value = buspirate.i2c_read_byte(ack=False)  # NAK last byte
        buspirate.i2c_stop()
    except Exception as e:
        print(f"Bus Pirate read error: {e}")
        bp_value = None

    # Compare
    match = (esp_value == bp_value) if (esp_value is not None and bp_value is not None) else False

    return esp_value, bp_value, match


def compare_write(esp_i2c: SCPII2C, buspirate: BusPirate,
                  addr: int, reg: int, value: int, use_esp: bool = True) -> bool:
    """Write via ESP32 or Bus Pirate, verify both can read it back"""

    if use_esp:
        # Write with ESP32
        if not esp_i2c.write_byte(addr, reg, value):
            return False
    else:
        # Write with Bus Pirate
        try:
            buspirate.i2c_start()
            buspirate.i2c_write_byte((addr << 1) | 0)  # Write mode
            buspirate.i2c_write_byte(reg)
            buspirate.i2c_write_byte(value)
            buspirate.i2c_stop()
        except Exception as e:
            print(f"Bus Pirate write error: {e}")
            return False

    time.sleep(0.02)  # Let write settle

    # Read back with both
    esp_value, bp_value, match = compare_read(esp_i2c, buspirate, addr, reg)

    return match and (esp_value == value)


def sweep_registers(esp_i2c: SCPII2C, buspirate: BusPirate, relay: Optional[SCPIRelay],
                    addr: int, reg_start: int, reg_end: int, power_cycle: bool):
    """Sweep I2C register addresses with test patterns"""

    test_patterns = generate_test_patterns()
    total_tests = 0
    mismatches = 0
    write_failures = 0

    print(f"\nStarting I2C sweep: device 0x{addr:02X}, registers 0x{reg_start:02X}-0x{reg_end:02X}")
    print(f"Test patterns: {len(test_patterns)}")
    print("-" * 80)

    for reg in range(reg_start, reg_end + 1):
        # Power cycle if requested
        if power_cycle and relay:
            relay.power_cycle()

        # Test each pattern
        for pattern in test_patterns:
            total_tests += 1

            # Write with ESP32
            success = compare_write(esp_i2c, buspirate, addr, reg, pattern, use_esp=True)

            if not success:
                write_failures += 1
                print(f"WRITE FAIL: reg 0x{reg:02X}, pattern 0x{pattern:02X}")
                continue

            # Read comparison
            esp_val, bp_val, match = compare_read(esp_i2c, buspirate, addr, reg)

            if not match:
                mismatches += 1
                print(f"MISMATCH: reg 0x{reg:02X}, ESP32=0x{esp_val:02X} BP=0x{bp_val:02X}")

            # Progress indicator
            if total_tests % 100 == 0:
                print(f"Progress: {total_tests} tests, {mismatches} mismatches, {write_failures} write failures")

    print("-" * 80)
    print(f"SUMMARY: {total_tests} total tests")
    print(f"  Mismatches: {mismatches} ({100*mismatches/total_tests:.2f}%)")
    print(f"  Write failures: {write_failures} ({100*write_failures/total_tests:.2f}%)")
    print(f"  Success rate: {100*(total_tests-mismatches-write_failures)/total_tests:.2f}%")


def main():
    parser = argparse.ArgumentParser(
        description="I2C Device Characterization: ESP32 vs Bus Pirate",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Scan I2C EEPROM at 0x50, registers 0x00-0xFF
  %(prog)s --esp-i2c 10.1.0.100 --buspirate /dev/ttyUSB0 --device-addr 0x50

  # With power cycling between tests
  %(prog)s --esp-i2c 10.1.0.100 --esp-relay 10.1.0.101 --buspirate /dev/ttyUSB0 \\
           --device-addr 0x50 --power-cycle

  # Narrow register range
  %(prog)s --esp-i2c 10.1.0.100 --buspirate /dev/ttyUSB0 --device-addr 0x68 \\
           --reg-start 0x00 --reg-end 0x0F
        """
    )

    parser.add_argument("--esp-i2c", required=True, help="ESP32 scpi-i2c IP address")
    parser.add_argument("--esp-relay", help="ESP32 scpi-relay IP address (for power cycling)")
    parser.add_argument("--buspirate-port", required=True, help="Bus Pirate serial port")
    parser.add_argument("--device-addr", required=True, type=lambda x: int(x, 0),
                        help="I2C device address (e.g., 0x50)")
    parser.add_argument("--reg-start", type=lambda x: int(x, 0), default=0x00,
                        help="Start register address (default: 0x00)")
    parser.add_argument("--reg-end", type=lambda x: int(x, 0), default=0xFF,
                        help="End register address (default: 0xFF)")
    parser.add_argument("--power-cycle", action="store_true",
                        help="Power cycle DUT between tests via scpi-relay")

    args = parser.parse_args()

    if args.power_cycle and not args.esp_relay:
        print("ERROR: --power-cycle requires --esp-relay")
        sys.exit(1)

    # Initialize instruments
    print("Connecting to instruments...")

    esp_i2c = SCPII2C(args.esp_i2c)
    esp_i2c.connect()
    print(f"  ESP32 I2C: {args.esp_i2c}")

    relay = None
    if args.esp_relay:
        relay = SCPIRelay(args.esp_relay)
        relay.connect()
        print(f"  ESP32 Relay: {args.esp_relay}")

    buspirate = BusPirate(args.buspirate_port)
    buspirate.connect()
    buspirate.enter_bitbang()
    buspirate.enter_i2c()
    buspirate.configure_i2c(power=True, pullups=True, speed=400000)
    print(f"  Bus Pirate: {args.buspirate_port}")

    try:
        sweep_registers(esp_i2c, buspirate, relay,
                       args.device_addr, args.reg_start, args.reg_end,
                       args.power_cycle)
    finally:
        # Cleanup
        print("\nCleaning up...")
        esp_i2c.disconnect()
        if relay:
            relay.disconnect()
        buspirate.reset()
        buspirate.disconnect()


if __name__ == "__main__":
    main()
