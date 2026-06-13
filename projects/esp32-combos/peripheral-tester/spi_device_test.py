#!/usr/bin/env python3
"""
SPI Device Characterization Tool

Compares ESP32 scpi-spi implementation against Bus Pirate golden reference.
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


class SCPISPI:
    """SCPI-SPI instrument interface"""

    def __init__(self, host: str, port: int = 5025):
        self.host = host
        self.port = port
        self.sock = None

    def connect(self):
        """Connect to SCPI-SPI instrument"""
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

    def transfer(self, data: List[int]) -> Optional[List[int]]:
        """SPI transfer (simultaneous MOSI/MISO)"""
        try:
            hex_data = ",".join([f"{b:#x}" for b in data])
            response = self.query(f"SPI:TRANSFER? {hex_data}")
            if response and response != "ERROR":
                # Parse comma-separated hex values
                return [int(x, 16) for x in response.split(",")]
            return None
        except Exception as e:
            print(f"ESP32 SPI error: {e}")
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
    """Generate test patterns for SPI verification"""
    patterns = [
        0x00, 0xFF,           # All zeros, all ones
        0xAA, 0x55,           # Alternating bits
        0x01, 0x02, 0x04, 0x08, 0x10, 0x20, 0x40, 0x80,  # Walking 1s
        0xFE, 0xFD, 0xFB, 0xF7, 0xEF, 0xDF, 0xBF, 0x7F,  # Walking 0s
    ]
    # Add some random patterns
    patterns.extend([random.randint(0, 255) for _ in range(8)])
    return patterns


def spi_read_register(interface, reg: int, num_bytes: int = 1) -> Optional[List[int]]:
    """Read from SPI device register (common pattern: write reg addr, read data)"""

    # Most SPI devices: send register address with read bit, then clock out data
    # Read bit is typically MSB=1 for many devices
    read_cmd = [reg | 0x80] + [0x00] * num_bytes  # 0x80 = read bit

    if isinstance(interface, SCPISPI):
        return interface.transfer(read_cmd)
    else:  # BusPirate
        try:
            result = interface.spi_bulk_transfer(read_cmd)
            return result
        except Exception as e:
            print(f"Bus Pirate SPI read error: {e}")
            return None


def spi_write_register(interface, reg: int, data: List[int]) -> bool:
    """Write to SPI device register (common pattern: write reg addr, write data)"""

    # Most SPI devices: send register address with write bit=0, then data
    write_cmd = [reg & 0x7F] + data  # 0x7F mask clears read bit

    try:
        if isinstance(interface, SCPISPI):
            interface.transfer(write_cmd)
        else:  # BusPirate
            interface.spi_bulk_transfer(write_cmd)
        return True
    except Exception as e:
        print(f"SPI write error: {e}")
        return False


def compare_spi_read(esp_spi: SCPISPI, buspirate: BusPirate,
                     reg: int, num_bytes: int = 1) -> Tuple[Optional[List[int]], Optional[List[int]], bool]:
    """Read from both ESP32 and Bus Pirate, compare MISO results"""

    # ESP32 read
    esp_result = spi_read_register(esp_spi, reg, num_bytes)
    esp_data = esp_result[1:] if esp_result else None  # Skip command echo byte

    # Bus Pirate read
    bp_result = spi_read_register(buspirate, reg, num_bytes)
    bp_data = bp_result[1:] if bp_result else None  # Skip command echo byte

    # Compare
    match = (esp_data == bp_data) if (esp_data is not None and bp_data is not None) else False

    return esp_data, bp_data, match


def compare_spi_write(esp_spi: SCPISPI, buspirate: BusPirate,
                      reg: int, data: List[int], use_esp: bool = True) -> bool:
    """Write via ESP32 or Bus Pirate, verify both can read it back"""

    if use_esp:
        if not spi_write_register(esp_spi, reg, data):
            return False
    else:
        if not spi_write_register(buspirate, reg, data):
            return False

    time.sleep(0.02)  # Let write settle

    # Read back with both
    esp_data, bp_data, match = compare_spi_read(esp_spi, buspirate, reg, len(data))

    return match and (esp_data == data)


def sweep_registers(esp_spi: SCPISPI, buspirate: BusPirate, relay: Optional[SCPIRelay],
                    reg_start: int, reg_end: int, power_cycle: bool):
    """Sweep SPI register addresses with test patterns"""

    test_patterns = generate_test_patterns()
    total_tests = 0
    mismatches = 0
    write_failures = 0

    print(f"\nStarting SPI sweep: registers 0x{reg_start:02X}-0x{reg_end:02X}")
    print(f"Test patterns: {len(test_patterns)}")
    print("-" * 80)

    for reg in range(reg_start, reg_end + 1):
        # Power cycle if requested
        if power_cycle and relay:
            relay.power_cycle()

        # Test each pattern (single-byte writes for simplicity)
        for pattern in test_patterns:
            total_tests += 1

            # Write with ESP32
            success = compare_spi_write(esp_spi, buspirate, reg, [pattern], use_esp=True)

            if not success:
                write_failures += 1
                print(f"WRITE FAIL: reg 0x{reg:02X}, pattern 0x{pattern:02X}")
                continue

            # Read comparison
            esp_data, bp_data, match = compare_spi_read(esp_spi, buspirate, reg, 1)

            if not match:
                mismatches += 1
                esp_str = f"0x{esp_data[0]:02X}" if esp_data else "None"
                bp_str = f"0x{bp_data[0]:02X}" if bp_data else "None"
                print(f"MISMATCH: reg 0x{reg:02X}, ESP32={esp_str} BP={bp_str}")

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
        description="SPI Device Characterization: ESP32 vs Bus Pirate",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Scan SPI device registers 0x00-0xFF
  %(prog)s --esp-spi 10.1.0.100 --buspirate /dev/ttyUSB0

  # With power cycling between tests
  %(prog)s --esp-spi 10.1.0.100 --esp-relay 10.1.0.101 --buspirate /dev/ttyUSB0 \\
           --power-cycle

  # Narrow register range
  %(prog)s --esp-spi 10.1.0.100 --buspirate /dev/ttyUSB0 \\
           --reg-start 0x00 --reg-end 0x0F

Note: This assumes a typical SPI register interface (reg addr + read/write bit).
      Device-specific protocols may require modifications to spi_read_register()
      and spi_write_register() functions.
        """
    )

    parser.add_argument("--esp-spi", required=True, help="ESP32 scpi-spi IP address")
    parser.add_argument("--esp-relay", help="ESP32 scpi-relay IP address (for power cycling)")
    parser.add_argument("--buspirate-port", required=True, help="Bus Pirate serial port")
    parser.add_argument("--reg-start", type=lambda x: int(x, 0), default=0x00,
                        help="Start register address (default: 0x00)")
    parser.add_argument("--reg-end", type=lambda x: int(x, 0), default=0xFF,
                        help="End register address (default: 0xFF)")
    parser.add_argument("--spi-mode", type=int, default=0, choices=[0, 1, 2, 3],
                        help="SPI mode (CPOL/CPHA, default: 0)")
    parser.add_argument("--spi-speed", type=int, default=1000000,
                        help="SPI clock speed in Hz (default: 1000000)")
    parser.add_argument("--power-cycle", action="store_true",
                        help="Power cycle DUT between tests via scpi-relay")

    args = parser.parse_args()

    if args.power_cycle and not args.esp_relay:
        print("ERROR: --power-cycle requires --esp-relay")
        sys.exit(1)

    # Initialize instruments
    print("Connecting to instruments...")

    esp_spi = SCPISPI(args.esp_spi)
    esp_spi.connect()
    # Configure SPI mode/speed (assumes scpi-spi supports these commands)
    esp_spi.write(f"SPI:MODE {args.spi_mode}")
    esp_spi.write(f"SPI:SPEED {args.spi_speed}")
    print(f"  ESP32 SPI: {args.esp_spi} (mode {args.spi_mode}, {args.spi_speed} Hz)")

    relay = None
    if args.esp_relay:
        relay = SCPIRelay(args.esp_relay)
        relay.connect()
        print(f"  ESP32 Relay: {args.esp_relay}")

    buspirate = BusPirate(args.buspirate_port)
    buspirate.connect()
    buspirate.enter_bitbang()
    buspirate.enter_spi()

    # Configure Bus Pirate SPI
    # Config byte: output=3.3V, mode=args.spi_mode, speed=1MHz
    speed_map = {30000: 0, 125000: 1, 250000: 2, 1000000: 3, 2000000: 4, 4000000: 5, 8000000: 6}
    speed_bits = speed_map.get(args.spi_speed, 3)  # Default 1MHz
    config = 0b10000000 | (args.spi_mode << 2) | speed_bits
    buspirate.spi_configure(config)
    print(f"  Bus Pirate: {args.buspirate_port} (mode {args.spi_mode}, ~{args.spi_speed} Hz)")

    try:
        sweep_registers(esp_spi, buspirate, relay,
                       args.reg_start, args.reg_end,
                       args.power_cycle)
    finally:
        # Cleanup
        print("\nCleaning up...")
        esp_spi.disconnect()
        if relay:
            relay.disconnect()
        buspirate.reset()
        buspirate.disconnect()


if __name__ == "__main__":
    main()
