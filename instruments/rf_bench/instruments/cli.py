#!/usr/bin/env python3
"""
CLI tool for instrument registry management.

Commands:
  list          - List all registered instruments
  scan-usb      - Scan for USB serial devices
  scan-network  - Scan IP range for SCPI instruments
  test          - Test connection to specific instrument
"""

import sys
import argparse
from .registry import Registry
from .scanner import NetworkScanner


def cmd_list(args):
    """List all registered instruments."""
    registry = Registry()
    instruments = registry.list_available(role=args.role)

    if not instruments:
        print("No instruments found in registry.")
        print(f"Check {registry.config_path}")
        return 1

    print(f"\n{'='*80}")
    print(f"Instruments Registry ({len(instruments)} total)")
    print(f"{'='*80}\n")

    for inst in instruments:
        status = "✓ AVAILABLE" if inst['connected'] else "✗ Not detected"
        tags_str = ', '.join(inst['tags']) if inst['tags'] else 'none'

        print(f"Role:     {inst['role']}")
        print(f"Name:     {inst['name']}")
        print(f"Type:     {inst['connection_type'].upper()}")
        print(f"Status:   {status}")
        print(f"Location: {inst['location']}")
        print(f"Tags:     {tags_str}")
        print()

    return 0


def cmd_scan_usb(args):
    """Scan for USB serial devices."""
    registry = Registry()
    devices = registry.list_usb_devices()

    if not devices:
        print("No USB serial devices detected.")
        return 1

    print(f"\n{'='*80}")
    print(f"USB Serial Devices ({len(devices)} detected)")
    print(f"{'='*80}\n")

    for dev in devices:
        print(f"Device:  {dev['path']}")
        print(f"VID:PID: {dev['vid']}:{dev['pid']}")
        print()

    return 0


def cmd_scan_network(args):
    """Scan network for SCPI instruments."""
    scanner = NetworkScanner()

    print(f"\n{'='*80}")
    print(f"Scanning {args.network} for SCPI instruments on port {args.port}")
    print(f"{'='*80}\n")

    instruments = scanner.scan(
        network=args.network,
        port=args.port,
        timeout=args.timeout,
        show_progress=not args.quiet
    )

    if not instruments:
        print("No SCPI instruments found.")
        return 1

    print(f"\nFound {len(instruments)} instrument(s):\n")

    for inst in instruments:
        print(f"IP:       {inst['ip']}")
        print(f"Port:     {inst['port']}")
        print(f"*IDN?:    {inst['idn']}")
        print()

    # Update registry if requested
    if args.update or args.auto_add:
        print("Updating registry...")
        results = scanner.update_registry(
            instruments,
            auto_add=args.auto_add
        )

        if results['updated']:
            print(f"\n✓ Updated {len(results['updated'])} instrument(s):")
            for item in results['updated']:
                print(f"  {item['name']}: {item['old_ip']} → {item['new_ip']}")

        if results['added']:
            print(f"\n✓ Added {len(results['added'])} new instrument(s):")
            for item in results['added']:
                print(f"  {item['name']} at {item['ip']}")
                print(f"    (Edit ~/.rf-bench/instruments.yaml to set role and driver)")

        if results['unchanged']:
            print(f"\n  {len(results['unchanged'])} instrument(s) unchanged")

        print()

    return 0


def cmd_test(args):
    """Test connection to specific instrument."""
    registry = Registry()

    try:
        print(f"Attempting to connect to role='{args.role}'...")

        if args.serial:
            print(f"  (using serial port {args.serial})")
        if args.tag:
            print(f"  (filtering by tag '{args.tag}')")

        instrument = registry.get(
            role=args.role,
            serial=args.serial,
            tag=args.tag
        )

        print("✓ Connected successfully!")

        # Try to get *IDN? if it's a SCPI instrument
        if hasattr(instrument, 'query'):
            try:
                idn = instrument.query('*IDN?')
                print(f"*IDN?: {idn}")
            except:
                pass

        # Close connection
        if hasattr(instrument, 'close'):
            instrument.close()

        return 0

    except Exception as e:
        print(f"✗ Connection failed: {e}")
        return 1


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description='rf-bench instrument registry management',
        formatter_class=argparse.RawDescriptionHelpFormatter
    )

    subparsers = parser.add_subparsers(dest='command', help='Command to execute')

    # list command
    parser_list = subparsers.add_parser('list', help='List registered instruments')
    parser_list.add_argument('--role', help='Filter by role')

    # scan-usb command
    parser_scan_usb = subparsers.add_parser('scan-usb', help='Scan for USB devices')

    # scan-network command
    parser_scan_net = subparsers.add_parser('scan-network', help='Scan network for SCPI instruments')
    parser_scan_net.add_argument('network', help='Network to scan (e.g., 10.1.1.0/24)')
    parser_scan_net.add_argument('--port', type=int, default=5025, help='SCPI port (default: 5025)')
    parser_scan_net.add_argument('--timeout', type=float, default=0.5, help='Connection timeout (default: 0.5s)')
    parser_scan_net.add_argument('--quiet', action='store_true', help='Disable progress bar')
    parser_scan_net.add_argument('--update', action='store_true', help='Update existing instruments in registry')
    parser_scan_net.add_argument('--auto-add', action='store_true', help='Automatically add new instruments')

    # test command
    parser_test = subparsers.add_parser('test', help='Test connection to instrument')
    parser_test.add_argument('role', help='Instrument role')
    parser_test.add_argument('--serial', help='Serial port (for USB devices)')
    parser_test.add_argument('--tag', help='Filter by tag')

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        return 1

    # Dispatch to command handler
    if args.command == 'list':
        return cmd_list(args)
    elif args.command == 'scan-usb':
        return cmd_scan_usb(args)
    elif args.command == 'scan-network':
        return cmd_scan_network(args)
    elif args.command == 'test':
        return cmd_test(args)
    else:
        parser.print_help()
        return 1


if __name__ == '__main__':
    sys.exit(main())
