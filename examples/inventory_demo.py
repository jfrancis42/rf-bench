#!/usr/bin/env python3
"""Demonstrate the rf-bench inventory system.

Shows how to use the centralized instrument connection system.
"""

from rf_bench import connect
from rf_bench.inventory import Inventory


def main():
    print("=== rf-bench Inventory Demo ===\n")

    # Method 1: Simple connect (recommended)
    print("1. Simple connection (one-liner):")
    print("   from rf_bench import connect")
    print("   sdg = connect('sdg')")
    print()

    # Method 2: Inventory object
    print("2. Using Inventory object:")
    inv = Inventory()
    print(f"   Loaded from: {inv.path}")
    print()

    # List instruments
    print("3. Available instruments:")
    for name in inv.list():
        info = inv.get(name)
        host = info['connection']['host']
        port = info['connection']['port']
        inst_type = info['type']
        print(f"   {name:15} {inst_type:15} {host}:{port}")
    print()

    # Show aliases
    print("4. Aliases:")
    for alias, canonical in inv.aliases.items():
        print(f"   {alias:10} -> {canonical}")
    print()

    # Filter by tags
    print("5. Filter by tags:")
    siglent = inv.list(tags=['siglent'])
    print(f"   Siglent instruments: {', '.join(siglent)}")
    print()

    # Connection info
    print("6. Detailed info:")
    info = inv.get('sdg')
    print(f"   Name: sdg-main")
    print(f"   Type: {info['type']}")
    print(f"   Driver: {info['driver']}")
    print(f"   Protocol: {info['connection']['protocol']}")
    print(f"   Host: {info['connection']['host']}")
    print(f"   Port: {info['connection']['port']}")
    print(f"   Location: {info.get('location', 'Not specified')}")
    print(f"   Tags: {', '.join(info.get('tags', []))}")
    print()

    # Show calibration tracking
    print("7. Calibration tracking:")
    for name in inv.list():
        info = inv.get(name)
        cal = info.get('calibration', {})
        if cal.get('due'):
            print(f"   {name}: due {cal['due']}")
    print()

    # Actual connection example (commented out to avoid hardware access)
    print("8. Actual connection (example - commented out):")
    print("   # sdg = connect('sdg')")
    print("   # sdg.set_waveform(1, 'sine', 1e6, 1.0)")
    print("   # print(sdg.get_identity())")
    print()

    print("=== Demo complete ===")


if __name__ == '__main__':
    main()
