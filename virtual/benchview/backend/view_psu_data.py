#!/usr/bin/env python3
"""
View PSU Accuracy Data

Shows how to load and work with rf-bench measurement CSV files.

Usage:
  python3 view_psu_data.py [csv_file]
"""

import sys
import csv
from pathlib import Path


def load_measurement(csv_path):
    """Load measurement with metadata and data."""

    # Read metadata from comment lines
    metadata = {}
    with open(csv_path) as f:
        for line in f:
            if not line.startswith('#'):
                break
            if ':' in line:
                key, value = line[1:].split(':', 1)
                metadata[key.strip()] = value.strip()

    # Read data rows
    data = []
    with open(csv_path) as f:
        reader = csv.DictReader(f, delimiter=',')
        for row in reader:
            # Convert numeric columns
            for key in row:
                try:
                    row[key] = float(row[key])
                except (ValueError, TypeError):
                    pass
            data.append(row)

    return metadata, data


def print_measurement(csv_path):
    """Print measurement summary and data."""

    metadata, data = load_measurement(csv_path)

    print("\n" + "=" * 70)
    print("MEASUREMENT METADATA")
    print("=" * 70)

    for key, value in sorted(metadata.items()):
        print(f"  {key:20s}: {value}")

    print("\n" + "=" * 70)
    print(f"DATA ({len(data)} rows)")
    print("=" * 70)

    if data:
        # Print column headers
        headers = list(data[0].keys())
        print("\n" + "  ".join(f"{h:>15s}" for h in headers))
        print("-" * 70)

        # Print first 10 rows
        for i, row in enumerate(data[:10], 1):
            values = [row[h] for h in headers]
            print("  ".join(f"{v:>15.4f}" if isinstance(v, float) else f"{v:>15s}" for v in values))

        if len(data) > 10:
            print(f"  ... ({len(data) - 10} more rows)")

    print("\n" + "=" * 70)
    print("QUICK STATS")
    print("=" * 70)

    # Calculate some basic stats
    if 'voltage_error' in data[0]:
        errors = [row['voltage_error'] for row in data]
        mean_error = sum(errors) / len(errors)
        max_error = max(abs(e) for e in errors)

        print(f"  Mean error:     {mean_error:+.5f} V")
        print(f"  Max abs error:  {max_error:.5f} V")

    if 'voltage_error_pct' in data[0]:
        error_pcts = [row['voltage_error_pct'] for row in data]
        mean_pct = sum(error_pcts) / len(error_pcts)

        print(f"  Mean error %:   {mean_pct:+.3f}%")

    print()


def show_csv_location():
    """Show where CSV files are stored."""
    data_dir = Path.home() / '.rf-bench' / 'data'

    if not data_dir.exists():
        print("No measurements found yet.")
        return

    csv_files = list(data_dir.glob('*.csv'))

    print(f"\nMeasurement data directory: {data_dir}")
    print(f"Found {len(csv_files)} CSV file(s)\n")

    # Show most recent 5
    csv_files.sort(key=lambda p: p.stat().st_mtime, reverse=True)

    for csv_file in csv_files[:5]:
        size_kb = csv_file.stat().st_size / 1024
        print(f"  {csv_file.name}")
        print(f"    Size: {size_kb:.1f} KB")


def main():
    print("\n" + "=" * 70)
    print("RF-BENCH MEASUREMENT DATA VIEWER")
    print("=" * 70)

    if len(sys.argv) > 1:
        csv_path = sys.argv[1]
    else:
        # Find most recent PSU test
        data_dir = Path.home() / '.rf-bench' / 'data'

        if not data_dir.exists():
            print("\nNo measurement data found.")
            print("Run a measurement first, then use this script to view it.\n")
            return 1

        csv_files = list(data_dir.glob('*PSU*.csv'))

        if not csv_files:
            show_csv_location()
            print("\nNo PSU test files found.")
            print("Specify a CSV file: python3 view_psu_data.py <file.csv>\n")
            return 1

        # Get most recent
        csv_path = str(max(csv_files, key=lambda p: p.stat().st_mtime))
        print(f"\nViewing most recent PSU test: {Path(csv_path).name}\n")

    if not Path(csv_path).exists():
        print(f"ERROR: File not found: {csv_path}\n")
        show_csv_location()
        return 1

    print_measurement(csv_path)

    print("=" * 70)
    print("HOW TO USE THIS DATA")
    print("=" * 70)
    print("""
1. View in spreadsheet:
   libreoffice ~/.rf-bench/data/<filename>.csv

2. Load in Python:
   import pandas as pd
   df = pd.read_csv('~/.rf-bench/data/<filename>.csv', comment='#')
   print(df.head())

3. Plot with matplotlib:
   import matplotlib.pyplot as plt
   plt.plot(df['voltage_set'], df['voltage_measured'])
   plt.show()

4. Search all measurements:
   rf-bench-data search --tags power-supply
   rf-bench-data recent
""")

    return 0


if __name__ == "__main__":
    exit(main())
