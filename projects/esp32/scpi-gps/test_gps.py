#!/usr/bin/env python3
"""
Example test script for ESP32 SCPI GPS Controller
Demonstrates GPS data queries
"""

import socket
import time

# Change this to your ESP32's IP address
ESP32_IP = '192.168.1.42'
SCPI_PORT = 5025


def scpi_command(ip, port, command):
    """Send SCPI command and return response if it's a query"""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.connect((ip, port))
        s.sendall((command + '\n').encode())

        # If it's a query (contains '?'), wait for response
        if '?' in command:
            response = s.recv(1024).decode().strip()
            return response

        return None


def main():
    print("ESP32 SCPI GPS Controller - Test Script")
    print("=" * 60)

    # Identify device
    idn = scpi_command(ESP32_IP, SCPI_PORT, '*IDN?')
    print(f"Device: {idn}\n")

    # Check for GPS fix
    print("Checking GPS Fix Status:")
    print("-" * 60)

    fix = scpi_command(ESP32_IP, SCPI_PORT, 'GPS:FIX?')
    if fix == '1':
        print("  ✓ GPS fix acquired")
    else:
        print("  ✗ No GPS fix (waiting for satellites...)")
        print("\nNote: GPS needs clear sky view and may take 30-60 seconds")
        print("      to acquire fix (longer indoors).\n")
        print("Move GPS antenna to window or outdoors, then run this script again.")
        return

    print()

    # Query individual GPS fields
    print("GPS Data (Individual Queries):")
    print("-" * 60)

    try:
        lat = scpi_command(ESP32_IP, SCPI_PORT, 'GPS:LAT?')
        lon = scpi_command(ESP32_IP, SCPI_PORT, 'GPS:LON?')
        alt = scpi_command(ESP32_IP, SCPI_PORT, 'GPS:ALT?')

        print(f"  Latitude:     {lat}°")
        print(f"  Longitude:    {lon}°")
        print(f"  Altitude:     {alt} m MSL")
        print()

        speed_kmh = scpi_command(ESP32_IP, SCPI_PORT, 'GPS:SPEED?')
        speed_knots = scpi_command(ESP32_IP, SCPI_PORT, 'GPS:SPEED:KNOTS?')
        track = scpi_command(ESP32_IP, SCPI_PORT, 'GPS:TRACK?')

        print(f"  Speed:        {speed_kmh} km/h ({speed_knots} knots)")
        print(f"  Heading:      {track}° true")
        print()

        time_utc = scpi_command(ESP32_IP, SCPI_PORT, 'GPS:TIME?')
        date_utc = scpi_command(ESP32_IP, SCPI_PORT, 'GPS:DATE?')

        if not date_utc.startswith('ERROR'):
            print(f"  Date/Time:    {date_utc} {time_utc} UTC")
        else:
            print(f"  Time:         {time_utc} UTC")
            print(f"  Date:         Not available (GPS module doesn't output RMC)")
        print()

        sats = scpi_command(ESP32_IP, SCPI_PORT, 'GPS:SATS?')
        hdop = scpi_command(ESP32_IP, SCPI_PORT, 'GPS:HDOP?')
        qual = scpi_command(ESP32_IP, SCPI_PORT, 'GPS:QUAL?')
        age = scpi_command(ESP32_IP, SCPI_PORT, 'GPS:AGE?')

        qual_str = {0: 'Invalid', 1: 'GPS fix', 2: 'DGPS fix'}.get(int(qual), 'Unknown')
        print(f"  Satellites:   {sats}")
        print(f"  HDOP:         {hdop}")
        print(f"  Fix Quality:  {qual} ({qual_str})")
        print(f"  Data Age:     {age} ms")

    except Exception as e:
        print(f"  Error querying GPS data: {e}")

    print()

    # Query all data as CSV
    print("GPS Data (Bulk CSV Query):")
    print("-" * 60)

    csv = scpi_command(ESP32_IP, SCPI_PORT, 'GPS:ALL?')
    fields = csv.split(',')

    if len(fields) == 14:
        print(f"  Raw CSV: {csv}\n")
        print(f"  Field Breakdown:")
        print(f"    [0]  Latitude:     {fields[0]}°")
        print(f"    [1]  Longitude:    {fields[1]}°")
        print(f"    [2]  Altitude:     {fields[2]} m")
        print(f"    [3]  Speed:        {fields[3]} km/h")
        print(f"    [4]  Track:        {fields[4]}°")
        print(f"    [5-7] Time:        {fields[5]}:{fields[6]}:{fields[7]} UTC")
        print(f"    [8-10] Date:       {fields[8]}-{fields[9]}-{fields[10]}")
        print(f"    [11] Satellites:   {fields[11]}")
        print(f"    [12] HDOP:         {fields[12]}")
        print(f"    [13] Fix Quality:  {fields[13]}")
    else:
        print(f"  Unexpected CSV format: {csv}")

    print()

    # Continuous monitoring
    print("Continuous Monitoring (10 seconds):")
    print("-" * 60)
    print("  Time   | Lat         | Lon          | Alt     | Speed   | Sats")
    print("-" * 60)

    start_time = time.time()
    while time.time() - start_time < 10.0:
        try:
            fix = scpi_command(ESP32_IP, SCPI_PORT, 'GPS:FIX?')
            if fix == '1':
                csv = scpi_command(ESP32_IP, SCPI_PORT, 'GPS:ALL?')
                fields = csv.split(',')

                if len(fields) >= 14:
                    elapsed = time.time() - start_time
                    print(f"  {elapsed:5.1f}s | {fields[0]:>11} | {fields[1]:>12} | "
                          f"{fields[2]:>6}m | {fields[3]:>6} km/h | {fields[11]:>2}")
                else:
                    print(f"  {elapsed:5.1f}s | GPS data unavailable")
            else:
                elapsed = time.time() - start_time
                print(f"  {elapsed:5.1f}s | No GPS fix")

            time.sleep(1.0)

        except Exception as e:
            print(f"  Error during monitoring: {e}")
            break

    print()
    print("Test complete!")


if __name__ == '__main__':
    try:
        main()
    except ConnectionRefusedError:
        print(f"ERROR: Could not connect to {ESP32_IP}:{SCPI_PORT}")
        print("Check that:")
        print("  1. The ESP32 is powered on")
        print("  2. It's connected to WiFi")
        print("  3. The IP address in this script matches the device")
    except KeyboardInterrupt:
        print("\n\nInterrupted by user")
