#!/usr/bin/env python3
"""
Plot PSU Accuracy Data

Reads CSV files from rf-bench measurement framework and plots:
- Measured vs Set voltage
- Voltage error vs Set voltage
- Error percentage vs Set voltage

Usage:
  python3 plot_psu_accuracy.py <csv_file>

  # Or use most recent PSU test:
  python3 plot_psu_accuracy.py
"""

import sys
import pandas as pd
import matplotlib.pyplot as plt
from pathlib import Path


def plot_measurement(csv_path):
    """Plot PSU accuracy measurement."""

    # Read metadata from comments
    metadata = {}
    with open(csv_path) as f:
        for line in f:
            if not line.startswith('#'):
                break
            if ':' in line:
                key, value = line[1:].split(':', 1)
                metadata[key.strip()] = value.strip()

    # Read CSV data (skip comment lines)
    df = pd.read_csv(csv_path, comment='#')

    print(f"\nPlotting: {metadata.get('name', 'Unknown')}")
    print(f"Operator: {metadata.get('operator', 'Unknown')}")
    print(f"Date: {metadata.get('timestamp', 'Unknown')}")
    print(f"DUT: {metadata.get('dut', 'Unknown')}")
    print(f"Load: {metadata.get('load', 'Unknown')}")
    print()

    # Create figure with 3 subplots
    fig, (ax1, ax2, ax3) = plt.subplots(3, 1, figsize=(10, 10))
    fig.suptitle(f"{metadata.get('name', 'PSU Accuracy Test')}\n{metadata.get('operator', '')} - {metadata.get('timestamp', '')[:10]}",
                 fontsize=14, fontweight='bold')

    # Plot 1: Measured vs Set
    ax1.plot(df['voltage_set'], df['voltage_measured'], 'bo-', label='Measured')
    ax1.plot(df['voltage_set'], df['voltage_set'], 'r--', label='Ideal (1:1)', alpha=0.5)
    ax1.set_xlabel('Set Voltage (V)')
    ax1.set_ylabel('Measured Voltage (V)')
    ax1.set_title('Measured vs Set Voltage')
    ax1.grid(True, alpha=0.3)
    ax1.legend()

    # Plot 2: Voltage Error
    ax2.plot(df['voltage_set'], df['voltage_error'], 'ro-')
    ax2.axhline(y=0, color='k', linestyle='--', alpha=0.3)
    ax2.set_xlabel('Set Voltage (V)')
    ax2.set_ylabel('Voltage Error (V)')
    ax2.set_title('Voltage Error vs Set Voltage')
    ax2.grid(True, alpha=0.3)

    # Plot 3: Error Percentage
    ax3.plot(df['voltage_set'], df['voltage_error_pct'], 'go-')
    ax3.axhline(y=0, color='k', linestyle='--', alpha=0.3)
    ax3.set_xlabel('Set Voltage (V)')
    ax3.set_ylabel('Error (%)')
    ax3.set_title('Error Percentage vs Set Voltage')
    ax3.grid(True, alpha=0.3)

    plt.tight_layout()

    # Save plot
    output_path = csv_path.replace('.csv', '_plot.png')
    plt.savefig(output_path, dpi=150, bbox_inches='tight')
    print(f"✓ Plot saved: {output_path}")

    # Show plot
    plt.show()


def find_most_recent_psu_test():
    """Find most recent PSU accuracy test."""
    data_dir = Path.home() / '.rf-bench' / 'data'

    if not data_dir.exists():
        print("ERROR: No measurement data found at ~/.rf-bench/data/")
        return None

    # Find all CSV files with "PSU" or "power" in name
    csv_files = list(data_dir.glob('*PSU*.csv')) + list(data_dir.glob('*power*.csv'))

    if not csv_files:
        print("ERROR: No PSU test files found")
        return None

    # Get most recent by modification time
    most_recent = max(csv_files, key=lambda p: p.stat().st_mtime)

    print(f"Using most recent PSU test: {most_recent.name}")
    return str(most_recent)


def main():
    if len(sys.argv) > 1:
        csv_path = sys.argv[1]
    else:
        csv_path = find_most_recent_psu_test()
        if csv_path is None:
            return 1

    if not Path(csv_path).exists():
        print(f"ERROR: File not found: {csv_path}")
        return 1

    plot_measurement(csv_path)
    return 0


if __name__ == "__main__":
    exit(main())
