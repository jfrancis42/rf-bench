#!/usr/bin/env python3
"""
Automated Sub-GHz TX/RX protocol testing combining scpi-relay + scpi-ptt + Flipper Zero.

Tests multiple DUT receivers against a suite of protocol test vectors, automatically
switching between DUTs via scpi-relay and transmitting test patterns via Flipper Zero.
"""

import argparse
import csv
import time
import sys
from pathlib import Path
from typing import List, Dict, Any, Protocol
from dataclasses import dataclass

from rf_bench.flipper import FlipperZero
from rf_bench.scpi_relay import ScpiRelay
from rf_bench.scpi_ptt import ScpiPTT


@dataclass
class TestVector:
    """Single protocol test vector."""
    protocol: str  # OOK, 2FSK, 4FSK
    frequency_mhz: float
    data_rate: int  # baud
    payload: str  # hex string
    expected_decode: str
    description: str = ""


class DUTDecoder(Protocol):
    """
    Interface for DUT decoder implementation.

    User must provide a class implementing this protocol for their specific
    DUT hardware. The decoder should read the DUT's output and return the
    decoded data.
    """

    def decode(self, timeout: float = 5.0) -> str:
        """
        Wait for and decode a transmission from the DUT.

        Args:
            timeout: Maximum time to wait for decode (seconds)

        Returns:
            Decoded data as hex string, or empty string on timeout/error
        """
        ...


def load_test_vectors(csv_path: Path) -> List[TestVector]:
    """
    Load test vectors from CSV file.

    CSV format:
        protocol,frequency_mhz,data_rate,payload,expected_decode,description
        OOK,433.92,4800,AABBCCDD,AABBCCDD,Simple OOK test
    """
    vectors = []
    with open(csv_path, 'r') as f:
        reader = csv.DictReader(f)
        for row in reader:
            vectors.append(TestVector(
                protocol=row['protocol'],
                frequency_mhz=float(row['frequency_mhz']),
                data_rate=int(row['data_rate']),
                payload=row['payload'],
                expected_decode=row['expected_decode'],
                description=row.get('description', '')
            ))
    return vectors


def configure_flipper_tx(flipper: FlipperZero, vector: TestVector) -> None:
    """Configure Flipper Zero for transmission of test vector."""
    # Set frequency
    flipper.subghz.set_frequency(int(vector.frequency_mhz * 1e6))

    # Configure modulation based on protocol
    if vector.protocol == "OOK":
        flipper.subghz.set_modulation("AM")
    elif vector.protocol in ["2FSK", "4FSK"]:
        flipper.subghz.set_modulation("FM")
    else:
        raise ValueError(f"Unsupported protocol: {vector.protocol}")

    # Set data rate
    flipper.subghz.set_data_rate(vector.data_rate)


def run_test_forward(
    relay: ScpiRelay,
    ptt: ScpiPTT,
    flipper: FlipperZero,
    decoders: List[DUTDecoder],
    vectors: List[TestVector],
    num_duts: int = 4
) -> Dict[str, Any]:
    """
    Run forward test: Flipper TX → DUT RX.

    Returns:
        Results dict with compliance matrix
    """
    results = {
        'vectors': [],
        'duts': list(range(1, num_duts + 1)),
        'matrix': []  # [vector_idx][dut_idx] = pass/fail/error
    }

    print(f"\n{'='*80}")
    print(f"FORWARD TEST: Flipper TX → DUT RX ({len(vectors)} vectors, {num_duts} DUTs)")
    print(f"{'='*80}\n")

    for vec_idx, vector in enumerate(vectors):
        print(f"Vector {vec_idx+1}/{len(vectors)}: {vector.description or vector.protocol}")
        print(f"  Protocol: {vector.protocol}, Freq: {vector.frequency_mhz} MHz, Rate: {vector.data_rate} baud")
        print(f"  Payload: {vector.payload}, Expected: {vector.expected_decode}")

        results['vectors'].append({
            'index': vec_idx,
            'protocol': vector.protocol,
            'frequency_mhz': vector.frequency_mhz,
            'data_rate': vector.data_rate,
            'payload': vector.payload,
            'expected': vector.expected_decode,
            'description': vector.description
        })

        # Configure Flipper for this test vector
        configure_flipper_tx(flipper, vector)

        dut_results = []

        for dut_idx in range(1, num_duts + 1):
            print(f"  Testing DUT {dut_idx}...", end=' ', flush=True)

            # Connect this DUT receiver via relay
            relay.connect_channel(dut_idx)
            time.sleep(0.1)  # settling time

            try:
                # Transmit test pattern via Flipper
                flipper.subghz.transmit_raw(vector.payload)

                # Wait for DUT to decode
                decoded = decoders[dut_idx - 1].decode(timeout=5.0)

                # Check result
                if decoded == vector.expected_decode:
                    print("PASS")
                    dut_results.append("PASS")
                elif decoded:
                    print(f"FAIL (got {decoded})")
                    dut_results.append(f"FAIL:{decoded}")
                else:
                    print("TIMEOUT")
                    dut_results.append("TIMEOUT")

            except Exception as e:
                print(f"ERROR ({e})")
                dut_results.append(f"ERROR:{e}")

            # Disconnect DUT
            relay.disconnect_all()
            time.sleep(0.1)

        results['matrix'].append(dut_results)
        print()

    return results


def run_test_reverse(
    relay: ScpiRelay,
    ptt: ScpiPTT,
    flipper: FlipperZero,
    vectors: List[TestVector],
    num_duts: int = 4
) -> Dict[str, Any]:
    """
    Run reverse test: DUT TX → Flipper RX.

    In this mode, scpi-ptt keys the DUT transmitter and Flipper receives/decodes.
    """
    results = {
        'vectors': [],
        'duts': list(range(1, num_duts + 1)),
        'matrix': []
    }

    print(f"\n{'='*80}")
    print(f"REVERSE TEST: DUT TX → Flipper RX ({len(vectors)} vectors, {num_duts} DUTs)")
    print(f"{'='*80}\n")

    for vec_idx, vector in enumerate(vectors):
        print(f"Vector {vec_idx+1}/{len(vectors)}: {vector.description or vector.protocol}")
        print(f"  Protocol: {vector.protocol}, Freq: {vector.frequency_mhz} MHz, Rate: {vector.data_rate} baud")

        results['vectors'].append({
            'index': vec_idx,
            'protocol': vector.protocol,
            'frequency_mhz': vector.frequency_mhz,
            'data_rate': vector.data_rate,
            'description': vector.description
        })

        # Configure Flipper for reception
        flipper.subghz.set_frequency(int(vector.frequency_mhz * 1e6))
        flipper.subghz.start_rx()

        dut_results = []

        for dut_idx in range(1, num_duts + 1):
            print(f"  Testing DUT {dut_idx}...", end=' ', flush=True)

            # Connect this DUT transmitter via relay
            relay.connect_channel(dut_idx)
            time.sleep(0.1)

            try:
                # Key DUT transmitter via PTT
                ptt.key()
                time.sleep(0.5)  # transmission time
                ptt.unkey()

                # Check if Flipper received anything
                rx_data = flipper.subghz.get_received()

                if rx_data:
                    print(f"RX: {rx_data}")
                    dut_results.append(f"RX:{rx_data}")
                else:
                    print("NO SIGNAL")
                    dut_results.append("NO_SIGNAL")

            except Exception as e:
                print(f"ERROR ({e})")
                dut_results.append(f"ERROR:{e}")

            # Disconnect DUT
            relay.disconnect_all()
            ptt.unkey()
            time.sleep(0.1)

        flipper.subghz.stop_rx()
        results['matrix'].append(dut_results)
        print()

    return results


def print_compliance_matrix(results: Dict[str, Any]) -> None:
    """Print test results as a compliance matrix."""
    print(f"\n{'='*80}")
    print("COMPLIANCE MATRIX")
    print(f"{'='*80}\n")

    # Header
    print(f"{'Vector':<8}", end='')
    for dut in results['duts']:
        print(f"DUT{dut:<4}", end='')
    print()
    print("-" * (8 + 7 * len(results['duts'])))

    # Results
    for vec_idx, dut_results in enumerate(results['matrix']):
        vec_info = results['vectors'][vec_idx]
        vec_label = f"{vec_idx+1}"
        print(f"{vec_label:<8}", end='')

        for result in dut_results:
            if result == "PASS":
                symbol = "✓"
            elif result.startswith("FAIL"):
                symbol = "✗"
            elif result == "TIMEOUT":
                symbol = "T"
            elif result == "NO_SIGNAL":
                symbol = "N"
            elif result.startswith("ERROR"):
                symbol = "E"
            elif result.startswith("RX:"):
                symbol = "R"
            else:
                symbol = "?"
            print(f"{symbol:<7}", end='')
        print()

    print()
    print("Legend: ✓=pass, ✗=fail, T=timeout, N=no signal, E=error, R=received")
    print()


def main():
    parser = argparse.ArgumentParser(
        description="Automated Sub-GHz protocol testing with Flipper Zero",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Forward test (Flipper TX → DUT RX)
  %(prog)s --esp-relay 10.1.0.40 --esp-ptt 10.1.0.41 \\
           --flipper-port /dev/ttyACM0 --test-vectors ook_tests.csv

  # Reverse test (DUT TX → Flipper RX)
  %(prog)s --esp-relay 10.1.0.40 --esp-ptt 10.1.0.41 \\
           --flipper-port /dev/ttyACM0 --test-vectors ook_tests.csv --reverse
        """
    )

    parser.add_argument('--esp-relay', required=True,
                       help='scpi-relay IP address')
    parser.add_argument('--esp-ptt', required=True,
                       help='scpi-ptt IP address')
    parser.add_argument('--flipper-port', required=True,
                       help='Flipper Zero serial port')
    parser.add_argument('--test-vectors', required=True, type=Path,
                       help='CSV file with test vectors')
    parser.add_argument('--num-duts', type=int, default=4,
                       help='Number of DUT receivers to test (1-4, default: 4)')
    parser.add_argument('--reverse', action='store_true',
                       help='Reverse mode: DUT TX → Flipper RX')
    parser.add_argument('--protocol', choices=['OOK', '2FSK', '4FSK'],
                       help='Filter test vectors by protocol')
    parser.add_argument('--freq-mhz', type=float,
                       help='Filter test vectors by frequency (MHz)')

    args = parser.parse_args()

    # Validate test vectors file
    if not args.test_vectors.exists():
        print(f"Error: Test vectors file not found: {args.test_vectors}")
        return 1

    # Load test vectors
    print(f"Loading test vectors from {args.test_vectors}...")
    vectors = load_test_vectors(args.test_vectors)

    # Apply filters
    if args.protocol:
        vectors = [v for v in vectors if v.protocol == args.protocol]
    if args.freq_mhz:
        vectors = [v for v in vectors if abs(v.frequency_mhz - args.freq_mhz) < 0.01]

    if not vectors:
        print("Error: No test vectors match the specified filters")
        return 1

    print(f"Loaded {len(vectors)} test vector(s)")

    # Connect to hardware
    print(f"\nConnecting to hardware...")
    print(f"  scpi-relay: {args.esp_relay}")
    print(f"  scpi-ptt: {args.esp_ptt}")
    print(f"  Flipper Zero: {args.flipper_port}")

    try:
        relay = ScpiRelay(args.esp_relay)
        ptt = ScpiPTT(args.esp_ptt)
        flipper = FlipperZero(args.flipper_port)
    except Exception as e:
        print(f"Error connecting to hardware: {e}")
        return 1

    print("Hardware connected\n")

    # Ensure all relays disconnected and PTT off at start
    relay.disconnect_all()
    ptt.unkey()

    try:
        if args.reverse:
            # Reverse test: DUT TX → Flipper RX
            results = run_test_reverse(relay, ptt, flipper, vectors, args.num_duts)
        else:
            # Forward test: Flipper TX → DUT RX
            # Note: User must provide DUT decoder implementations
            print("Error: Forward mode requires DUT decoder implementations")
            print("Please implement DUTDecoder interface for your specific DUT hardware")
            return 1
            # decoders = [...]  # User must provide
            # results = run_test_forward(relay, ptt, flipper, decoders, vectors, args.num_duts)

        # Print results
        print_compliance_matrix(results)

    finally:
        # Clean up
        relay.disconnect_all()
        ptt.unkey()
        flipper.close()

    return 0


if __name__ == '__main__':
    sys.exit(main())
