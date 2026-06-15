#!/usr/bin/env python3
"""
RF Matrix Router - Multi-instrument RF routing matrix
Combines scpi-matrix + XL9535 relay board + external RF relays

Routes RF signals between sources (SSA TG, SDG output, IC-7300 TX, RTL-SDR)
and destinations (4-8 DUTs or test fixtures).
"""

import argparse
import sys
from typing import Dict, Tuple, Optional

# Will be available when rf_bench.relay is tested:
# from rf_bench.relay import XL9535
# For now, placeholder imports
try:
    from rf_bench.relay import XL9535
from rf_bench import connect
    RELAY_AVAILABLE = True
except ImportError:
    RELAY_AVAILABLE = False
    print("Warning: rf_bench.relay.XL9535 not available (hardware pending)", file=sys.stderr)


class RFMatrix:
    """RF routing matrix controller"""

    # Source/destination definitions
    SOURCES = {
        'SSA_TG': 0,      # SSA3032X tracking generator output
        'SDG': 1,         # SDG1062X function generator output
        'IC7300': 2,      # IC-7300 HF transceiver TX output
        'RTLSDR': 3,      # RTL-SDR input (for monitoring)
    }

    def __init__(self, esp_matrix_ip: Optional[str] = None,
                 xl9535_port: Optional[str] = None,
                 topology: str = '4x4'):
        """
        Initialize RF matrix controller

        Args:
            esp_matrix_ip: IP address of scpi-matrix ESP32 controller
            xl9535_port: Bus Pirate serial port for XL9535 I2C control
            topology: Matrix topology - '4x4' (4 sources, 4 dests) or '8x2' (8 sources, 2 dests)
        """
        self.esp_matrix_ip = esp_matrix_ip
        self.xl9535_port = xl9535_port
        self.topology = topology

        if topology == '4x4':
            self.num_sources = 4
            self.num_dests = 4
        elif topology == '8x2':
            self.num_sources = 8
            self.num_dests = 2
        else:
            raise ValueError(f"Unknown topology: {topology}. Use '4x4' or '8x2'")

        # Initialize hardware controller
        if esp_matrix_ip:
            self.controller_type = 'scpi-matrix'
            # TODO: Initialize SCPI connection to ESP32
            print(f"Using scpi-matrix at {esp_matrix_ip}")
        elif xl9535_port and RELAY_AVAILABLE:
            self.controller_type = 'xl9535'
            # TODO: Initialize XL9535 via Bus Pirate
            print(f"Using XL9535 via Bus Pirate on {xl9535_port}")
        else:
            self.controller_type = 'simulation'
            print("Running in simulation mode (no hardware)")

        # Current routing state
        self.current_routes: Dict[int, Optional[int]] = {i: None for i in range(self.num_sources)}

    def compute_relay_pattern(self, source: int, dest: int) -> int:
        """
        Compute relay bit pattern for crosspoint routing

        Args:
            source: Source index (0-based)
            dest: Destination index (0-based)

        Returns:
            16-bit relay pattern for XL9535 or scpi-matrix
        """
        if source >= self.num_sources or dest >= self.num_dests:
            raise ValueError(f"Invalid route: source {source}, dest {dest}")

        # Crosspoint topology: relay index = source * num_dests + dest
        relay_index = source * self.num_dests + dest

        # For XL9535: 16 relays across two 8-bit ports
        # Bit pattern: set bit at relay_index position
        pattern = 1 << relay_index

        return pattern

    def route(self, source_name: str, dest_number: int) -> bool:
        """
        Route RF signal from source to destination

        Args:
            source_name: Source name (e.g., 'SSA_TG', 'SDG', 'IC7300', 'RTLSDR')
            dest_number: Destination DUT number (1-based, e.g., 1-4 for 4x4)

        Returns:
            True if routing successful, False otherwise
        """
        if source_name not in self.SOURCES:
            print(f"Error: Unknown source '{source_name}'. Valid: {list(self.SOURCES.keys())}")
            return False

        source_idx = self.SOURCES[source_name]
        dest_idx = dest_number - 1  # Convert to 0-based

        if dest_idx < 0 or dest_idx >= self.num_dests:
            print(f"Error: Invalid destination {dest_number}. Valid range: 1-{self.num_dests}")
            return False

        # Compute relay pattern
        pattern = self.compute_relay_pattern(source_idx, dest_idx)

        print(f"Routing {source_name} -> DUT{dest_number}")
        print(f"  Source index: {source_idx}, Dest index: {dest_idx}")
        print(f"  Relay pattern: 0x{pattern:04X} (binary: {pattern:016b})")

        # Command hardware
        if self.controller_type == 'scpi-matrix':
            return self._command_scpi_matrix(pattern)
        elif self.controller_type == 'xl9535':
            return self._command_xl9535(pattern)
        else:
            print("  (Simulation mode - no hardware commanded)")
            return True

    def _command_scpi_matrix(self, pattern: int) -> bool:
        """Send relay pattern to scpi-matrix ESP32"""
        # TODO: Implement SCPI socket connection and GPIO commands
        print(f"  TODO: Send pattern 0x{pattern:04X} to scpi-matrix at {self.esp_matrix_ip}")
        return True

    def _command_xl9535(self, pattern: int) -> bool:
        """Send relay pattern to XL9535 I2C GPIO expander"""
        # TODO: Implement XL9535 I2C commands via Bus Pirate
        print(f"  TODO: Send pattern 0x{pattern:04X} to XL9535 on {self.xl9535_port}")
        return True

    def disconnect_all(self) -> bool:
        """Disconnect all routes (set all relays to off)"""
        print("Disconnecting all routes")

        if self.controller_type == 'scpi-matrix':
            return self._command_scpi_matrix(0x0000)
        elif self.controller_type == 'xl9535':
            return self._command_xl9535(0x0000)
        else:
            print("  (Simulation mode - no hardware commanded)")
            return True

    def verify_connection(self, source_name: str, dest_number: int) -> bool:
        """
        Verify RF connection (optional - requires continuity measurement)

        Args:
            source_name: Source name
            dest_number: Destination DUT number (1-based)

        Returns:
            True if connection verified, False otherwise
        """
        print(f"TODO: Verify {source_name} -> DUT{dest_number} connection")
        print("  (Requires scpi-relay continuity measurement or RF power detection)")
        return True


def main():
    parser = argparse.ArgumentParser(
        description='RF Matrix Router - Route RF signals between sources and DUTs',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Route SSA tracking generator to DUT 2 (4x4 matrix)
  %(prog)s --topology 4x4 --route SSA_TG!DUT2

  # Route SDG function generator to DUT 1 using scpi-matrix
  %(prog)s --esp-matrix 192.168.1.100 --route SDG!DUT1

  # Route IC-7300 to DUT 3 using XL9535
  %(prog)s --xl9535-buspirate /dev/ttyUSB0 --route IC7300!DUT3

  # Disconnect all routes
  %(prog)s --disconnect-all

Sources: SSA_TG, SDG, IC7300, RTLSDR
Destinations: DUT1, DUT2, DUT3, DUT4 (for 4x4) or DUT1, DUT2 (for 8x2)
        """
    )

    # Hardware configuration
    parser.add_argument('--esp-matrix', '--esp-matrix-ip',
                       help='IP address of scpi-matrix ESP32 controller')
    parser.add_argument('--xl9535-buspirate-port', '--xl9535-port',
                       help='Bus Pirate serial port for XL9535 I2C control (e.g., /dev/ttyUSB0)')
    parser.add_argument('--topology', choices=['4x4', '8x2'], default='4x4',
                       help='Matrix topology (default: 4x4)')

    # Routing commands
    parser.add_argument('--route', metavar='SOURCE!DEST',
                       help='Route source to destination (e.g., SSA_TG!DUT2)')
    parser.add_argument('--disconnect-all', action='store_true',
                       help='Disconnect all routes (set all relays off)')
    parser.add_argument('--verify', action='store_true',
                       help='Verify connection after routing')

    # List options
    parser.add_argument('--list-sources', action='store_true',
                       help='List available sources')

    args = parser.parse_args()

    # List sources and exit
    if args.list_sources:
        print("Available sources:")
        for name, idx in sorted(RFMatrix.SOURCES.items(), key=lambda x: x[1]):
            print(f"  {name} (index {idx})")
        return 0

    # Initialize matrix controller
    try:
        matrix = RFMatrix(
            esp_matrix_ip=args.esp_matrix,
            xl9535_port=args.xl9535_buspirate_port,
            topology=args.topology
        )
    except ValueError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1

    # Execute commands
    if args.disconnect_all:
        if not matrix.disconnect_all():
            return 1

    if args.route:
        # Parse SOURCE!DEST format
        if '!' not in args.route:
            print("Error: Route format is SOURCE!DEST (e.g., SSA_TG!DUT2)", file=sys.stderr)
            return 1

        source_name, dest_str = args.route.split('!', 1)

        # Parse destination (DUT1 -> 1, or just 1)
        if dest_str.upper().startswith('DUT'):
            dest_str = dest_str[3:]

        try:
            dest_number = int(dest_str)
        except ValueError:
            print(f"Error: Invalid destination '{dest_str}'. Use DUT1, DUT2, etc., or just 1, 2, etc.",
                  file=sys.stderr)
            return 1

        # Route
        if not matrix.route(source_name, dest_number):
            return 1

        # Verify if requested
        if args.verify:
            if not matrix.verify_connection(source_name, dest_number):
                print("Warning: Connection verification failed")

    return 0


if __name__ == '__main__':
    sys.exit(main())
