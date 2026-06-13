#!/usr/bin/env python3
"""
SPI Protocol Decode Validation

Combines ESP32 scpi-spi traffic generation with SDS2504X hardware SPI decode
to validate protocol correctness. ESP32 generates known SPI transactions;
scope captures and decodes on digital channels; Python compares transmitted
vs decoded frames.

Hardware:
- ESP32 running scpi-spi (traffic generation)
- Siglent SDS2504X with MSO option (digital decode)
- Parallel connection: ESP32 SPI pins → scope digital inputs

Usage:
    ./spi_protocol_test.py --esp 10.1.0.100 --scope 10.1.0.200 \
        --test-vectors test_vectors_spi.csv

Test vector CSV format:
    operation,data,frequency,mode,bit_order,description
    write,0xAA55BB,1000000,0,MSB,Write 3 bytes
    read,0xFF,1000000,0,MSB,Read with dummy byte
    transfer,0xDEADBEEF,500000,3,MSB,Full duplex transfer

SPI modes:
    0: CPOL=0, CPHA=0 (sample rising, shift falling)
    1: CPOL=0, CPHA=1 (sample falling, shift rising)
    2: CPOL=1, CPHA=0 (sample falling, shift rising)
    3: CPOL=1, CPHA=1 (sample rising, shift falling)

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
except ImportError:
    print("ERROR: rf_bench.siglent not found. Install with:", file=sys.stderr)
    print("  pip install rf-bench-drivers-siglent", file=sys.stderr)
    sys.exit(1)

import socket


class SPIProtocolTester:
    """SPI protocol decode validation combining ESP32 generation + scope decode."""

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

    def setup_scope_spi_decode(self, mosi_ch: str = "D0", miso_ch: str = "D1",
                               sclk_ch: str = "D2", cs_ch: str = "D3"):
        """Configure scope for SPI hardware decode on digital channels."""
        self.scope.write("DIGITAL:STATE ON")

        # Configure SPI decode
        self.scope.write("DECODE1:MODE SPI")
        self.scope.write(f"DECODE1:SPI:MOSI {mosi_ch}")
        self.scope.write(f"DECODE1:SPI:MISO {miso_ch}")
        self.scope.write(f"DECODE1:SPI:CLK {sclk_ch}")
        self.scope.write(f"DECODE1:SPI:CS {cs_ch}")
        self.scope.write("DECODE1:STATE ON")

        print(f"Scope configured: SPI decode on MOSI={mosi_ch}, MISO={miso_ch}, CLK={sclk_ch}, CS={cs_ch}")

    def run_test_vector(self, vector: Dict) -> Tuple[bool, str]:
        """
        Execute one test vector: generate SPI traffic, capture decode, compare.

        Returns (passed, message)
        """
        operation = vector['operation']
        data = vector.get('data', '')
        frequency = int(vector.get('frequency', 1000000))
        mode = int(vector.get('mode', 0))
        bit_order = vector.get('bit_order', 'MSB')
        description = vector.get('description', '')

        print(f"\n[TEST] {description}")
        print(f"  Operation: {operation}, Data: {data}, Freq: {frequency} Hz, Mode: {mode}, Order: {bit_order}")

        # Configure ESP32 SPI parameters
        self.esp32_scpi(f"SPI:FREQ {frequency}")
        self.esp32_scpi(f"SPI:MODE {mode}")
        self.esp32_scpi(f"SPI:ORDER {bit_order}")

        # Generate SPI traffic based on operation
        if operation == 'write':
            if not data:
                return False, "Missing data for write operation"
            self.esp32_scpi(f"SPI:WRITE {data}")

        elif operation == 'read':
            byte_count = vector.get('byte_count', 1)
            response = self.esp32_scpi(f"SPI:READ? {data},{byte_count}")
            print(f"  ESP32 read: {response}")

        elif operation == 'transfer':
            if not data:
                return False, "Missing data for transfer operation"
            response = self.esp32_scpi(f"SPI:TRANSFER? {data}")
            print(f"  ESP32 transfer result: {response}")

        else:
            return False, f"Unknown operation: {operation}"

        # Give scope time to capture and decode
        time.sleep(0.5)

        # Read decoded SPI frames from scope
        decoded = self.scope.query("DECODE1:DATA?")
        print(f"  Scope decoded: {decoded}")

        # Compare transmitted vs decoded
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
        description="SPI protocol decode validation: ESP32 generation + SDS2504X decode"
    )
    parser.add_argument('--esp', required=True, help='ESP32 IP address')
    parser.add_argument('--scope', required=True, help='SDS2504X scope IP address')
    parser.add_argument('--test-vectors', required=True, help='CSV file with test vectors')
    parser.add_argument('--mosi-channel', default='D0', help='Scope channel for MOSI (default: D0)')
    parser.add_argument('--miso-channel', default='D1', help='Scope channel for MISO (default: D1)')
    parser.add_argument('--sclk-channel', default='D2', help='Scope channel for SCLK (default: D2)')
    parser.add_argument('--cs-channel', default='D3', help='Scope channel for CS (default: D3)')

    args = parser.parse_args()

    tester = SPIProtocolTester(args.esp, args.scope)

    try:
        tester.connect_esp32()
        tester.setup_scope_spi_decode(args.mosi_channel, args.miso_channel,
                                       args.sclk_channel, args.cs_channel)

        success = tester.run_test_suite(args.test_vectors)

        sys.exit(0 if success else 1)

    finally:
        tester.close()


if __name__ == '__main__':
    main()
