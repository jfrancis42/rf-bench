#!/usr/bin/env python3
"""
UART Protocol Decode Validation

Combines ESP32 scpi-uart traffic generation with SDS2504X hardware UART decode
to validate protocol correctness. ESP32 generates known UART transactions;
scope captures and decodes on digital channels; Python compares transmitted
vs decoded frames.

Hardware:
- ESP32 running scpi-uart (traffic generation)
- Siglent SDS2504X with MSO option (digital decode)
- Parallel connection: ESP32 UART pins → scope digital inputs

Usage:
    ./uart_protocol_test.py --esp 10.1.0.100 --scope 10.1.0.200 \
        --test-vectors test_vectors_uart.csv

Test vector CSV format:
    data,baudrate,data_bits,parity,stop_bits,description
    "Hello World",115200,8,NONE,1,Standard ASCII message
    0xDEADBEEF,9600,8,EVEN,2,Hex data with even parity
    "@ABCDEFG",57600,7,ODD,1,7-bit data with odd parity

Parity options: NONE, EVEN, ODD, MARK, SPACE

Author: jfrancis / jfrancis
License: GPL-3.0-or-later
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


class UARTProtocolTester:
    """UART protocol decode validation combining ESP32 generation + scope decode."""

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

    def setup_scope_uart_decode(self, tx_channel: str = "D0", rx_channel: str = "D1"):
        """Configure scope for UART hardware decode on digital channels."""
        self.scope.write("DIGITAL:STATE ON")

        # Configure UART decode
        self.scope.write("DECODE1:MODE UART")
        self.scope.write(f"DECODE1:UART:TX {tx_channel}")
        self.scope.write(f"DECODE1:UART:RX {rx_channel}")
        self.scope.write("DECODE1:STATE ON")

        print(f"Scope configured: UART decode on TX={tx_channel}, RX={rx_channel}")

    def run_test_vector(self, vector: Dict) -> Tuple[bool, str]:
        """
        Execute one test vector: generate UART traffic, capture decode, compare.

        Returns (passed, message)
        """
        data = vector.get('data', '')
        baudrate = int(vector.get('baudrate', 115200))
        data_bits = int(vector.get('data_bits', 8))
        parity = vector.get('parity', 'NONE').upper()
        stop_bits = int(vector.get('stop_bits', 1))
        description = vector.get('description', '')

        print(f"\n[TEST] {description}")
        print(f"  Data: {data}, Baud: {baudrate}, {data_bits}{parity[0]}{stop_bits}")

        # Configure ESP32 UART parameters
        self.esp32_scpi(f"UART:BAUD {baudrate}")
        self.esp32_scpi(f"UART:DATABITS {data_bits}")
        self.esp32_scpi(f"UART:PARITY {parity}")
        self.esp32_scpi(f"UART:STOPBITS {stop_bits}")

        # Configure scope decode parameters
        self.scope.write(f"DECODE1:UART:BAUD {baudrate}")
        self.scope.write(f"DECODE1:UART:DATA {data_bits}")
        parity_map = {'NONE': 'NONE', 'EVEN': 'EVEN', 'ODD': 'ODD', 'MARK': 'MARK', 'SPACE': 'SPACE'}
        self.scope.write(f"DECODE1:UART:PARITY {parity_map.get(parity, 'NONE')}")
        self.scope.write(f"DECODE1:UART:STOP {stop_bits}")

        # Transmit data
        if not data:
            return False, "Missing data for transmission"

        # Handle both string and hex formats
        if data.startswith('0x'):
            self.esp32_scpi(f"UART:WRITE:HEX {data}")
        else:
            # Escape quotes for SCPI
            escaped_data = data.replace('"', '\\"')
            self.esp32_scpi(f'UART:WRITE "{escaped_data}"')

        # Give scope time to capture and decode
        # UART is slower than SPI/I2C, so wait proportionally to data length
        wait_time = max(0.5, len(data) * 10 / baudrate + 0.2)
        time.sleep(wait_time)

        # Read decoded UART frames from scope
        decoded = self.scope.query("DECODE1:DATA?")
        print(f"  Scope decoded: {decoded}")

        # Compare transmitted vs decoded
        # For ASCII strings, check substring match
        if decoded and len(decoded) > 0:
            # Strip quotes and whitespace from decoded data
            decoded_clean = decoded.strip().strip('"').strip("'")
            data_clean = data.strip().strip('"').strip("'")

            if data_clean in decoded_clean or decoded_clean in data_clean:
                return True, f"Decode matches: '{decoded_clean}'"
            else:
                return False, f"Decode mismatch: expected '{data_clean}', got '{decoded_clean}'"
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
        description="UART protocol decode validation: ESP32 generation + SDS2504X decode"
    )
    parser.add_argument('--esp', required=True, help='ESP32 IP address')
    parser.add_argument('--scope', required=True, help='SDS2504X scope IP address')
    parser.add_argument('--test-vectors', required=True, help='CSV file with test vectors')
    parser.add_argument('--tx-channel', default='D0', help='Scope digital channel for TX (default: D0)')
    parser.add_argument('--rx-channel', default='D1', help='Scope digital channel for RX (default: D1)')

    args = parser.parse_args()

    tester = UARTProtocolTester(args.esp, args.scope)

    try:
        tester.connect_esp32()
        tester.setup_scope_uart_decode(args.tx_channel, args.rx_channel)

        success = tester.run_test_suite(args.test_vectors)

        sys.exit(0 if success else 1)

    finally:
        tester.close()


if __name__ == '__main__':
    main()
