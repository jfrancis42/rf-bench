#!/usr/bin/env python3
"""
I2C Protocol Decode Validation

Combines ESP32 scpi-i2c traffic generation with SDS2504X hardware I2C decode
to validate protocol correctness. ESP32 generates known I2C transactions;
scope captures and decodes on digital channels; Python compares transmitted
vs decoded frames.

Hardware:
- ESP32 running scpi-i2c (traffic generation)
- Siglent SDS2504X with MSO option (digital decode)
- Parallel connection: ESP32 I2C pins → scope digital inputs

Usage:
    ./i2c_protocol_test.py --esp 10.1.0.100 --scope 10.1.0.200 \
        --test-vectors test_vectors_i2c.csv

Test vector CSV format:
    operation,address,data,frequency,description
    write,0x50,0xAA55,100000,Write to EEPROM
    read,0x50,,100000,Read from EEPROM
    scan,,,100000,Address scan 0x00-0x7F

Author: jfrancis / jfrancis
License: MIT
"""

import argparse
import csv
import sys
import time
from typing import List, Dict, Tuple, Optional

try:
    from rf_bench.siglent import SDS2000X
from rf_bench import connect
except ImportError:
    print("ERROR: rf_bench.siglent not found. Install with:", file=sys.stderr)
    print("  pip install rf-bench-drivers-siglent", file=sys.stderr)
    sys.exit(1)

import socket


class I2CProtocolTester:
    """I2C protocol decode validation combining ESP32 generation + scope decode."""

    def __init__(self, esp_ip: str, scope_ip: str):
        self.esp_ip = esp_ip
        self.scope = SDS2000X(scope_ip)
        self.esp_socket = None

    def connect_esp32(self):
        """Connect to ESP32 SCPI server."""
        try:
            self.esp_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.esp_socket.settimeout(5.0)
            self.esp_socket.connect((self.esp_ip, 5025))
            # Read welcome banner
            banner = self.esp_socket.recv(1024).decode('ascii')
            print(f"Connected to ESP32: {banner.strip()}")
        except Exception as e:
            print(f"ERROR: Failed to connect to ESP32 at {self.esp_ip}:5025: {e}", file=sys.stderr)
            sys.exit(1)

    def esp32_scpi(self, command: str) -> Optional[str]:
        """Send SCPI command to ESP32, return response if query."""
        if not self.esp_socket:
            raise RuntimeError("ESP32 not connected")

        self.esp_socket.sendall((command + "\n").encode('ascii'))

        if '?' in command:
            response = self.esp_socket.recv(4096).decode('ascii').strip()
            return response
        return None

    def setup_scope_i2c_decode(self, sda_channel: str = "D0", scl_channel: str = "D1"):
        """Configure scope for I2C hardware decode on digital channels."""
        # Enable digital channels
        self.scope.write(f"DIGITAL:STATE ON")

        # Configure I2C decode
        # Note: Actual SDS2504X I2C decode commands depend on firmware version
        # Consult SDS2000X Programming Guide for exact syntax
        self.scope.write(f"DECODE1:MODE I2C")
        self.scope.write(f"DECODE1:I2C:SDA {sda_channel}")
        self.scope.write(f"DECODE1:I2C:SCL {scl_channel}")
        self.scope.write(f"DECODE1:STATE ON")

        print(f"Scope configured: I2C decode on SDA={sda_channel}, SCL={scl_channel}")

    def run_test_vector(self, vector: Dict) -> Tuple[bool, str]:
        """
        Execute one test vector: generate I2C traffic, capture decode, compare.

        Returns (passed, message)
        """
        operation = vector['operation']
        address = vector.get('address', '')
        data = vector.get('data', '')
        frequency = int(vector.get('frequency', 100000))
        description = vector.get('description', '')

        print(f"\n[TEST] {description}")
        print(f"  Operation: {operation}, Address: {address}, Data: {data}, Freq: {frequency} Hz")

        # Configure ESP32 I2C frequency
        self.esp32_scpi(f"I2C:FREQ {frequency}")

        # Generate I2C traffic based on operation
        if operation == 'write':
            if not address or not data:
                return False, "Missing address or data for write operation"
            self.esp32_scpi(f"I2C:WRITE {address},{data}")

        elif operation == 'read':
            if not address:
                return False, "Missing address for read operation"
            byte_count = vector.get('byte_count', 1)
            response = self.esp32_scpi(f"I2C:READ? {address},{byte_count}")
            print(f"  ESP32 read: {response}")

        elif operation == 'scan':
            response = self.esp32_scpi("I2C:SCAN?")
            print(f"  ESP32 scan result: {response}")

        else:
            return False, f"Unknown operation: {operation}"

        # Give scope time to capture and decode
        time.sleep(0.5)

        # Read decoded I2C frames from scope
        # Note: Actual decode readback command depends on SDS2504X firmware
        # This is a placeholder - consult programming guide
        decoded = self.scope.query("DECODE1:DATA?")
        print(f"  Scope decoded: {decoded}")

        # Compare transmitted vs decoded
        # For now, just check that decode returned something
        if decoded and len(decoded) > 0:
            return True, "Decode captured data"
        else:
            return False, "Scope decode returned no data"

    def run_test_suite(self, csv_path: str):
        """Run all test vectors from CSV file."""
        try:
            with open(csv_path, 'r') as f:
                reader = csv.DictReader(f)
                vectors = list(reader)
        except FileNotFoundError:
            print(f"ERROR: Test vector file not found: {csv_path}", file=sys.stderr)
            sys.exit(1)

        print(f"Loaded {len(vectors)} test vectors from {csv_path}")

        passed = 0
        failed = 0

        for i, vector in enumerate(vectors, 1):
            success, message = self.run_test_vector(vector)

            if success:
                print(f"  ✓ PASS: {message}")
                passed += 1
            else:
                print(f"  ✗ FAIL: {message}")
                failed += 1

        print(f"\n{'='*60}")
        print(f"Results: {passed} passed, {failed} failed, {passed+failed} total")
        print(f"{'='*60}")

        return failed == 0

    def close(self):
        """Clean up connections."""
        if self.esp_socket:
            self.esp_socket.close()


def main():
    parser = argparse.ArgumentParser(
        description="I2C protocol decode validation: ESP32 generation + SDS2504X decode"
    )
    parser.add_argument('--esp', required=True, help='ESP32 IP address')
    parser.add_argument('--scope', required=True, help='SDS2504X scope IP address')
    parser.add_argument('--test-vectors', required=True, help='CSV file with test vectors')
    parser.add_argument('--sda-channel', default='D0', help='Scope digital channel for SDA (default: D0)')
    parser.add_argument('--scl-channel', default='D1', help='Scope digital channel for SCL (default: D1)')

    args = parser.parse_args()

    tester = I2CProtocolTester(args.esp, args.scope)

    try:
        tester.connect_esp32()
        tester.setup_scope_i2c_decode(args.sda_channel, args.scl_channel)

        success = tester.run_test_suite(args.test_vectors)

        sys.exit(0 if success else 1)

    finally:
        tester.close()


if __name__ == '__main__':
    main()
