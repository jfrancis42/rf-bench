#!/usr/bin/env python3
"""
Wideband RF antenna array scanner using scpi-relay, scpi-gps, and RTL-SDR.

Automates antenna pattern characterization by:
1. Switching between antennas via scpi-relay (4-channel XL9535 relay board)
2. Capturing power spectrum with RTL-SDR
3. GPS timestamping via scpi-gps for mobile surveys
4. Logging frequency/power/antenna/GPS to SQLite
5. Generating antenna pattern plots (power vs freq, polar if using rotator)
"""

import argparse
import sqlite3
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import requests

try:
    from rf_bench.rtlsdr import RTLSDR
except ImportError:
    print("ERROR: rf_bench.rtlsdr not found. Install: pip install rf-bench-drivers-rtlsdr", file=sys.stderr)
    sys.exit(1)


def scpi_command(host, port, command):
    """Send SCPI command via HTTP GET to ESP32 instrument."""
    try:
        url = f"http://{host}:{port}/scpi?cmd={requests.utils.quote(command)}"
        resp = requests.get(url, timeout=5)
        resp.raise_for_status()
        return resp.text.strip()
    except requests.RequestException as e:
        print(f"ERROR: SCPI command failed ({host}:{port}): {e}", file=sys.stderr)
        return None


def get_gps_data(gps_host, gps_port=80):
    """Query scpi-gps for current position and timestamp."""
    lat = scpi_command(gps_host, gps_port, "GPS:LAT?")
    lon = scpi_command(gps_host, gps_port, "GPS:LON?")
    alt = scpi_command(gps_host, gps_port, "GPS:ALT?")
    sat = scpi_command(gps_host, gps_port, "GPS:SAT?")

    if not all([lat, lon, alt, sat]):
        return None

    return {
        'lat': float(lat),
        'lon': float(lon),
        'alt': float(alt),
        'sat': int(sat),
        'timestamp': datetime.now(timezone.utc).isoformat()
    }


def select_antenna(relay_host, relay_port, channel):
    """Select antenna via scpi-relay (channels 1-4)."""
    # Turn off all relays first
    for ch in range(1, 5):
        scpi_command(relay_host, relay_port, f"ROUT:OPEN (@{ch})")

    # Activate selected antenna relay
    result = scpi_command(relay_host, relay_port, f"ROUT:CLOS (@{channel})")
    return result is not None


def capture_spectrum(rtlsdr, freq_start_hz, freq_stop_hz, step_hz):
    """Capture power spectrum across frequency range using RTL-SDR.

    Returns list of (freq_hz, power_dbfs) tuples.
    """
    spectrum = []
    current_freq = freq_start_hz

    while current_freq <= freq_stop_hz:
        rtlsdr.center_freq = current_freq
        time.sleep(0.1)  # Settle time

        # Read samples and compute power
        samples = rtlsdr.read_samples(256 * 1024)
        power_dbfs = 10 * np.log10(np.mean(np.abs(samples)**2) + 1e-12)

        spectrum.append((current_freq, power_dbfs))
        current_freq += step_hz

    return spectrum


def init_database(db_path):
    """Create SQLite database for scan results."""
    conn = sqlite3.connect(db_path)
    c = conn.cursor()

    c.execute('''
        CREATE TABLE IF NOT EXISTS scans (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT NOT NULL,
            freq_hz INTEGER NOT NULL,
            power_dbfs REAL NOT NULL,
            antenna INTEGER NOT NULL,
            gps_lat REAL,
            gps_lon REAL,
            gps_alt REAL,
            gps_sat INTEGER
        )
    ''')

    conn.commit()
    return conn


def log_scan_point(conn, timestamp, freq_hz, power_dbfs, antenna, gps_data):
    """Insert scan data point into database."""
    c = conn.cursor()
    c.execute('''
        INSERT INTO scans (timestamp, freq_hz, power_dbfs, antenna, gps_lat, gps_lon, gps_alt, gps_sat)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    ''', (
        timestamp,
        freq_hz,
        power_dbfs,
        antenna,
        gps_data['lat'] if gps_data else None,
        gps_data['lon'] if gps_data else None,
        gps_data['alt'] if gps_data else None,
        gps_data['sat'] if gps_data else None
    ))
    conn.commit()


def plot_antenna_patterns(db_path, output_dir):
    """Generate antenna pattern plots from scan database."""
    conn = sqlite3.connect(db_path)
    c = conn.cursor()

    # Get all unique antennas
    antennas = [row[0] for row in c.execute('SELECT DISTINCT antenna FROM scans ORDER BY antenna')]

    if not antennas:
        print("No scan data found in database")
        return

    # Plot power vs frequency for each antenna
    plt.figure(figsize=(12, 8))

    for antenna in antennas:
        rows = c.execute('''
            SELECT freq_hz, AVG(power_dbfs) as avg_power
            FROM scans
            WHERE antenna = ?
            GROUP BY freq_hz
            ORDER BY freq_hz
        ''', (antenna,)).fetchall()

        freqs = [r[0] / 1e6 for r in rows]  # Convert to MHz
        powers = [r[1] for r in rows]

        plt.plot(freqs, powers, label=f'Antenna {antenna}', marker='.')

    plt.xlabel('Frequency (MHz)')
    plt.ylabel('Power (dBFS)')
    plt.title('Antenna Array Pattern Comparison')
    plt.legend()
    plt.grid(True, alpha=0.3)

    output_path = Path(output_dir) / 'antenna_patterns.png'
    plt.savefig(output_path, dpi=150, bbox_inches='tight')
    print(f"Saved antenna pattern plot: {output_path}")
    plt.close()

    # Generate normalized comparison (dB relative to best antenna)
    plt.figure(figsize=(12, 8))

    # Get all frequency points
    freq_points = [row[0] for row in c.execute('SELECT DISTINCT freq_hz FROM scans ORDER BY freq_hz')]

    # Build matrix of power values [antenna][freq]
    power_matrix = {}
    for antenna in antennas:
        power_matrix[antenna] = {}
        rows = c.execute('''
            SELECT freq_hz, AVG(power_dbfs)
            FROM scans
            WHERE antenna = ?
            GROUP BY freq_hz
        ''', (antenna,)).fetchall()
        for freq_hz, power in rows:
            power_matrix[antenna][freq_hz] = power

    # Normalize to best antenna at each frequency
    for antenna in antennas:
        freqs_mhz = []
        relative_db = []

        for freq_hz in freq_points:
            if freq_hz not in power_matrix[antenna]:
                continue

            # Find max power across all antennas at this frequency
            max_power = max(power_matrix[ant].get(freq_hz, -999) for ant in antennas)

            freqs_mhz.append(freq_hz / 1e6)
            relative_db.append(power_matrix[antenna][freq_hz] - max_power)

        plt.plot(freqs_mhz, relative_db, label=f'Antenna {antenna}', marker='.')

    plt.xlabel('Frequency (MHz)')
    plt.ylabel('Relative Gain (dB)')
    plt.title('Antenna Array Pattern (Normalized to Best)')
    plt.legend()
    plt.grid(True, alpha=0.3)
    plt.axhline(y=0, color='k', linestyle='--', alpha=0.5)

    output_path = Path(output_dir) / 'antenna_patterns_normalized.png'
    plt.savefig(output_path, dpi=150, bbox_inches='tight')
    print(f"Saved normalized antenna pattern plot: {output_path}")
    plt.close()

    conn.close()


def main():
    parser = argparse.ArgumentParser(
        description='ESP32+RTL-SDR antenna array scanner',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Scan 144-148 MHz with 4 antennas, 25 kHz steps
  %(prog)s --esp-relay 10.1.0.100 --esp-gps 10.1.0.101 \\
           --freq-start 144 --freq-stop 148 --step-khz 25 --antennas 1 2 3 4

  # VHF survey without GPS
  %(prog)s --esp-relay 10.1.0.100 --freq-start 144 --freq-stop 148 --antennas 1 2

  # HF scan with 10 kHz steps
  %(prog)s --esp-relay 10.1.0.100 --freq-start 7 --freq-stop 7.3 \\
           --step-khz 10 --antennas 1 2 3
        """
    )

    parser.add_argument('--esp-relay', required=True, help='scpi-relay ESP32 IP address')
    parser.add_argument('--relay-port', type=int, default=80, help='scpi-relay port (default: 80)')
    parser.add_argument('--esp-gps', help='scpi-gps ESP32 IP address (optional)')
    parser.add_argument('--gps-port', type=int, default=80, help='scpi-gps port (default: 80)')

    parser.add_argument('--freq-start', type=float, required=True, help='Start frequency (MHz)')
    parser.add_argument('--freq-stop', type=float, required=True, help='Stop frequency (MHz)')
    parser.add_argument('--step-khz', type=float, default=25, help='Step size (kHz, default: 25)')

    parser.add_argument('--antennas', type=int, nargs='+', required=True,
                       help='Antenna relay channels to scan (1-4)')

    parser.add_argument('--ppm', type=float, default=0, help='RTL-SDR frequency correction (ppm)')
    parser.add_argument('--gain', type=float, default=30, help='RTL-SDR gain (dB, default: 30)')

    parser.add_argument('--db', default='antenna_scan.db', help='SQLite database path')
    parser.add_argument('--output-dir', default='.', help='Output directory for plots')

    args = parser.parse_args()

    # Validate antenna channels
    for ant in args.antennas:
        if ant < 1 or ant > 4:
            print(f"ERROR: Antenna channel {ant} out of range (1-4)", file=sys.stderr)
            return 1

    # Convert frequencies to Hz
    freq_start_hz = int(args.freq_start * 1e6)
    freq_stop_hz = int(args.freq_stop * 1e6)
    step_hz = int(args.step_khz * 1e3)

    # Initialize RTL-SDR
    print(f"Initializing RTL-SDR (ppm={args.ppm}, gain={args.gain} dB)...")
    rtlsdr = RTLSDR()
    rtlsdr.sample_rate = 2.048e6
    rtlsdr.gain = args.gain
    rtlsdr.freq_correction = args.ppm

    # Initialize database
    print(f"Initializing database: {args.db}")
    conn = init_database(args.db)

    # Main scan loop
    total_points = len(args.antennas) * ((freq_stop_hz - freq_start_hz) // step_hz + 1)
    print(f"\nStarting scan: {len(args.antennas)} antennas, {args.freq_start}-{args.freq_stop} MHz, {args.step_khz} kHz steps")
    print(f"Total points: {total_points}")
    print()

    point_count = 0

    for antenna in args.antennas:
        print(f"=== Antenna {antenna} ===")

        # Select antenna via relay
        if not select_antenna(args.esp_relay, args.relay_port, antenna):
            print(f"ERROR: Failed to select antenna {antenna}", file=sys.stderr)
            continue

        time.sleep(0.5)  # Relay settle time

        # Get GPS data if available
        gps_data = None
        if args.esp_gps:
            gps_data = get_gps_data(args.esp_gps, args.gps_port)
            if gps_data:
                print(f"GPS: {gps_data['lat']:.6f}, {gps_data['lon']:.6f}, {gps_data['alt']:.1f}m, {gps_data['sat']} sats")
            else:
                print("WARNING: GPS data unavailable")

        # Capture spectrum
        print(f"Scanning {args.freq_start}-{args.freq_stop} MHz...")
        spectrum = capture_spectrum(rtlsdr, freq_start_hz, freq_stop_hz, step_hz)

        # Log to database
        timestamp = datetime.now(timezone.utc).isoformat()
        for freq_hz, power_dbfs in spectrum:
            log_scan_point(conn, timestamp, freq_hz, power_dbfs, antenna, gps_data)
            point_count += 1

            if point_count % 100 == 0:
                print(f"Progress: {point_count}/{total_points} ({100*point_count/total_points:.1f}%)")

        print(f"Antenna {antenna} complete: {len(spectrum)} points\n")

    # Cleanup
    rtlsdr.close()
    conn.close()

    # Generate plots
    print("Generating antenna pattern plots...")
    plot_antenna_patterns(args.db, args.output_dir)

    print("\n=== Scan Complete ===")
    print(f"Database: {args.db}")
    print(f"Total points: {point_count}")
    print(f"Plots saved to: {args.output_dir}")

    return 0


if __name__ == '__main__':
    sys.exit(main())
