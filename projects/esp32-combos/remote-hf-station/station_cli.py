#!/usr/bin/env python3
"""
Remote HF Station CLI — Command-line interface for scripting

Provides CLI access to all remote station functions for use in
automated contest scripts, beaconing, satellite tracking, etc.

Usage examples:
    # Set frequency and mode
    ./station_cli.py set-freq 14074
    ./station_cli.py set-mode USB

    # Aim antenna
    ./station_cli.py aim-antenna --azimuth 90 --elevation 15

    # Read SWR
    ./station_cli.py read-swr

    # Key PTT
    ./station_cli.py key-ptt --duration 5

    # Get current status
    ./station_cli.py status
"""

import argparse
import sys
import time
from pathlib import Path

import pyvisa
from rf_bench.icom import IC7300
from rf_bench import connect


class RemoteStation:
    """CLI interface to remote HF station."""

    def __init__(self, rigctld_host, rigctld_port, rotator_ip, ptt_ip, swr_ip):
        """Connect to all instruments."""
        print("Connecting to instruments...", file=sys.stderr)

        # Radio via Hamlib
        self.radio = IC7300(host=rigctld_host, port=rigctld_port)

        # ESP32 SCPI devices
        rm = pyvisa.ResourceManager('@py')
        self.rotator = rm.open_resource(f'TCPIP0::{rotator_ip}::5025::SOCKET')
        self.ptt = rm.open_resource(f'TCPIP0::{ptt_ip}::5025::SOCKET')
        self.swr_meter = rm.open_resource(f'TCPIP0::{swr_ip}::5025::SOCKET')

        for inst in [self.rotator, self.ptt, self.swr_meter]:
            inst.read_termination = '\n'
            inst.write_termination = '\n'

        print("✓ Connected", file=sys.stderr)

    def set_frequency(self, freq_khz):
        """Set radio frequency in kHz."""
        self.radio.set_frequency(freq_khz)
        print(f"Frequency set to {freq_khz} kHz")

    def get_frequency(self):
        """Get current frequency in kHz."""
        freq_khz = self.radio.get_frequency()
        print(f"{freq_khz}")
        return freq_khz

    def set_mode(self, mode):
        """Set radio mode."""
        self.radio.set_mode(mode)
        print(f"Mode set to {mode}")

    def get_mode(self):
        """Get current mode."""
        mode = self.radio.get_mode()
        print(f"{mode}")
        return mode

    def aim_antenna(self, azimuth, elevation):
        """Set antenna azimuth and elevation."""
        self.rotator.write(f'SOUR:AZ {azimuth}')
        self.rotator.write(f'SOUR:EL {elevation}')
        print(f"Antenna aimed to Az:{azimuth}° El:{elevation}°")

    def get_position(self):
        """Get current antenna position."""
        az = float(self.rotator.query('SOUR:AZ?'))
        el = float(self.rotator.query('SOUR:EL?'))
        print(f"Azimuth: {az}° | Elevation: {el}°")
        return az, el

    def read_swr(self):
        """Read current SWR."""
        swr = float(self.swr_meter.query('MEAS:SWR?'))
        print(f"{swr:.2f}")
        return swr

    def set_ptt(self, state):
        """Control PTT state."""
        self.ptt.write(f'OUTP:STAT {1 if state else 0}')
        print(f"PTT: {'ON' if state else 'OFF'}")

    def key_ptt(self, duration):
        """Key PTT for specified duration in seconds."""
        print(f"Keying PTT for {duration} seconds...", file=sys.stderr)
        self.set_ptt(True)
        time.sleep(duration)
        self.set_ptt(False)
        print("PTT released", file=sys.stderr)

    def get_status(self):
        """Get complete station status."""
        freq = self.radio.get_frequency()
        mode = self.radio.get_mode()
        az = float(self.rotator.query('SOUR:AZ?'))
        el = float(self.rotator.query('SOUR:EL?'))
        swr = float(self.swr_meter.query('MEAS:SWR?'))

        print("=== Remote HF Station Status ===")
        print(f"Frequency: {freq} kHz")
        print(f"Mode: {mode}")
        print(f"Antenna: Az={az}° El={el}°")
        print(f"SWR: {swr:.2f}")

        return {
            'frequency_khz': freq,
            'mode': mode,
            'azimuth': az,
            'elevation': el,
            'swr': swr
        }


def main():
    # Common connection arguments
    parent_parser = argparse.ArgumentParser(add_help=False)
    parent_parser.add_argument('--rigctld-host', default='localhost',
                               help='rigctld hostname (default: localhost)')
    parent_parser.add_argument('--rigctld-port', type=int, default=4532,
                               help='rigctld port (default: 4532)')
    parent_parser.add_argument('--rotator-ip', default='192.168.1.100',
                               help='ESP32 rotator IP (default: 192.168.1.100)')
    parent_parser.add_argument('--ptt-ip', default='192.168.1.101',
                               help='ESP32 PTT IP (default: 192.168.1.101)')
    parent_parser.add_argument('--swr-ip', default='192.168.1.102',
                               help='ESP32 SWR meter IP (default: 192.168.1.102)')

    # Main parser with subcommands
    parser = argparse.ArgumentParser(
        description='Remote HF Station CLI',
        parents=[parent_parser]
    )
    subparsers = parser.add_subparsers(dest='command', help='Command to execute')

    # set-freq
    p_setfreq = subparsers.add_parser('set-freq', help='Set frequency in kHz')
    p_setfreq.add_argument('frequency', type=int, help='Frequency in kHz')

    # get-freq
    subparsers.add_parser('get-freq', help='Get current frequency')

    # set-mode
    p_setmode = subparsers.add_parser('set-mode', help='Set operating mode')
    p_setmode.add_argument('mode', choices=['USB', 'LSB', 'CW', 'RTTY', 'AM', 'FM'],
                           help='Operating mode')

    # get-mode
    subparsers.add_parser('get-mode', help='Get current mode')

    # aim-antenna
    p_aim = subparsers.add_parser('aim-antenna', help='Aim antenna')
    p_aim.add_argument('--azimuth', type=float, required=True, help='Azimuth in degrees')
    p_aim.add_argument('--elevation', type=float, required=True, help='Elevation in degrees')

    # get-position
    subparsers.add_parser('get-position', help='Get antenna position')

    # read-swr
    subparsers.add_parser('read-swr', help='Read SWR')

    # ptt-on
    subparsers.add_parser('ptt-on', help='Turn PTT on')

    # ptt-off
    subparsers.add_parser('ptt-off', help='Turn PTT off')

    # key-ptt
    p_key = subparsers.add_parser('key-ptt', help='Key PTT for duration')
    p_key.add_argument('--duration', type=float, required=True,
                       help='Duration in seconds')

    # status
    subparsers.add_parser('status', help='Get complete station status')

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        sys.exit(1)

    # Connect to station
    try:
        station = RemoteStation(
            args.rigctld_host,
            args.rigctld_port,
            args.rotator_ip,
            args.ptt_ip,
            args.swr_ip
        )
    except Exception as e:
        print(f"Error connecting to station: {e}", file=sys.stderr)
        sys.exit(1)

    # Execute command
    try:
        if args.command == 'set-freq':
            station.set_frequency(args.frequency)
        elif args.command == 'get-freq':
            station.get_frequency()
        elif args.command == 'set-mode':
            station.set_mode(args.mode)
        elif args.command == 'get-mode':
            station.get_mode()
        elif args.command == 'aim-antenna':
            station.aim_antenna(args.azimuth, args.elevation)
        elif args.command == 'get-position':
            station.get_position()
        elif args.command == 'read-swr':
            station.read_swr()
        elif args.command == 'ptt-on':
            station.set_ptt(True)
        elif args.command == 'ptt-off':
            station.set_ptt(False)
        elif args.command == 'key-ptt':
            station.key_ptt(args.duration)
        elif args.command == 'status':
            station.get_status()
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == '__main__':
    main()
