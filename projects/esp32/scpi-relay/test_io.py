#!/usr/bin/env python3
"""
Example test script for ESP32 SCPI Relay Controller
Demonstrates relay control and input reading
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
    print("ESP32 SCPI Relay Controller - I/O Test")
    print("=" * 50)

    # Identify device
    idn = scpi_command(ESP32_IP, SCPI_PORT, '*IDN?')
    print(f"Device: {idn}\n")

    # Test relay outputs
    print("Testing Relay Outputs:")
    print("-" * 50)

    for relay in range(1, 5):
        print(f"  Turning ON relay {relay}...", end=' ')
        scpi_command(ESP32_IP, SCPI_PORT, f'ROUTE:CLOSE (@{relay})')
        time.sleep(0.5)

        state = scpi_command(ESP32_IP, SCPI_PORT, f'ROUTE:CLOSE:STATE? (@{relay})')
        print(f"State: {state} ({'ON' if state == '1' else 'OFF'})")

        print(f"  Turning OFF relay {relay}...", end=' ')
        scpi_command(ESP32_IP, SCPI_PORT, f'ROUTE:OPEN (@{relay})')
        time.sleep(0.5)

        state = scpi_command(ESP32_IP, SCPI_PORT, f'ROUTE:CLOSE:STATE? (@{relay})')
        print(f"State: {state} ({'ON' if state == '1' else 'OFF'})")

    print()

    # Test digital inputs
    print("Reading Digital Inputs:")
    print("-" * 50)

    for inp in range(1, 5):
        state = scpi_command(ESP32_IP, SCPI_PORT, f'MEAS:DIG? (@{inp})')
        level = 'HIGH (3.3V)' if state == '1' else 'LOW (0V/floating)'
        print(f"  Digital Input {inp}: {level}")

    # Read all digital inputs at once
    all_dig = scpi_command(ESP32_IP, SCPI_PORT, 'MEAS:DIG:ALL?')
    print(f"  All inputs: {all_dig}")

    print()

    # Test analog input
    print("Reading Analog Input:")
    print("-" * 50)

    voltage = scpi_command(ESP32_IP, SCPI_PORT, 'MEAS:VOLT?')
    raw = scpi_command(ESP32_IP, SCPI_PORT, 'MEAS:VOLT:RAW?')

    print(f"  Voltage: {voltage}V")
    print(f"  Raw ADC: {raw} counts (0-4095)")

    print()

    # Continuous monitoring example
    print("Continuous Monitoring (5 seconds):")
    print("-" * 50)
    print("  Time    | Analog (V) | Digital Inputs")
    print("-" * 50)

    start_time = time.time()
    while time.time() - start_time < 5.0:
        voltage = scpi_command(ESP32_IP, SCPI_PORT, 'MEAS:VOLT?')
        dig_inputs = scpi_command(ESP32_IP, SCPI_PORT, 'MEAS:DIG:ALL?')

        elapsed = time.time() - start_time
        print(f"  {elapsed:5.2f}s | {float(voltage):9.4f}V | {dig_inputs}")
        time.sleep(0.5)

    print()
    print("Test complete!")

    # Reset all relays to off
    print("Resetting all relays to OFF...")
    scpi_command(ESP32_IP, SCPI_PORT, '*RST')


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
