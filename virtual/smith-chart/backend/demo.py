#!/usr/bin/env python3
"""
Virtual Smith Chart — Comprehensive Demo

Demonstrates all features of the Virtual Smith Chart instrument:
- 4 independent traces with different colors
- Frequency markers
- SWR circles
- Animated impedance sweep around Smith chart
- Multiple measurement scenarios

Usage:
1. Start the backend server:
   cd ~/Dropbox/build/rf-bench/virtual/smith-chart/backend
   python3 server.py

2. Open browser at http://localhost:8011

3. Run this demo:
   python3 demo.py

The demo runs for ~30 seconds and demonstrates:
- Trace 1: Antenna sweep across 20m band (14.0-14.35 MHz)
- Trace 2: Matching network transformation path
- Trace 3: Crystal resonance impedance locus
- Trace 4: Transmission line transformation

Each trace uses a different color and is labeled. SWR circles are shown
to visualize match quality. Frequency markers identify key points.

Author: Jeff Francis (N0GQ) <gjfrancis@protonmail.com>
License: GPL-3.0-or-later
"""

import socket
import time
import math
import cmath
import argparse

# Parse command line arguments
parser = argparse.ArgumentParser(description="Virtual Smith Chart Demo")
parser.add_argument('--host', default='localhost', help='SCPI server hostname')
parser.add_argument('--port', type=int, default=5025, help='SCPI server port')
args = parser.parse_args()

# SCPI connection parameters
HOST = args.host
PORT = args.port


def scpi_command(sock, cmd):
    """Send SCPI command (no response expected)"""
    sock.sendall(f"{cmd}\n".encode('utf-8'))


def scpi_query(sock, cmd):
    """Send SCPI query and return response"""
    sock.sendall(f"{cmd}\n".encode('utf-8'))
    time.sleep(0.05)  # Brief delay for response
    try:
        response = sock.recv(4096).decode('utf-8').strip()
        return response
    except:
        return ""


def demo_antenna_sweep(sock):
    """Demo 1: Antenna impedance sweep across 20m band"""
    print("\n=== Demo 1: Antenna Impedance Sweep (20m Band) ===")
    print("Simulating S11 measurement from 14.0 to 14.35 MHz")
    print("Trace 1 (GREEN): Shows typical dipole impedance vs frequency")

    scpi_command(sock, "SMIT:TRAC 1")
    scpi_command(sock, "SMIT:TRAC:COL #00ff00")
    scpi_command(sock, "SMIT:TRAC:LAB 20m Dipole")
    scpi_command(sock, "SMIT:TRAC:CLE")
    scpi_command(sock, "SMIT:SWR 2.0")

    # Simulate dipole impedance: resonant at 14.2 MHz, reactive off-resonance
    f_resonant = 14.2e6

    for freq in range(14_000_000, 14_350_001, 25_000):
        # Simple dipole model: R ≈ 73Ω at resonance, X varies with frequency
        delta_f = freq - f_resonant
        r = 73 + abs(delta_f) * 0.0001  # Resistance increases off-resonance
        x = delta_f * 0.002             # Reactance proportional to detuning

        # Normalize to 50Ω
        z = complex(r, x)
        z_norm = z / 50.0

        # Mark every 100 kHz
        if freq % 100_000 == 0:
            scpi_command(sock, f"SMIT:MARK:FREQ {freq}")

        scpi_command(sock, f"SMIT:POIN {z_norm.real},{z_norm.imag}")
        time.sleep(0.05)

    print(f"Plotted {(14_350_000 - 14_000_000) // 25_000 + 1} points")
    time.sleep(1)


def demo_matching_network(sock):
    """Demo 2: Matching network transformation path"""
    print("\n=== Demo 2: Matching Network Transformation ===")
    print("Simulating L-network matching: 20+j30Ω → 50Ω")
    print("Trace 2 (MAGENTA): Shows impedance transformation steps")

    scpi_command(sock, "SMIT:TRAC 2")
    scpi_command(sock, "SMIT:TRAC:COL #ff00ff")
    scpi_command(sock, "SMIT:TRAC:LAB L-Network Match")
    scpi_command(sock, "SMIT:TRAC:CLE")

    # Start: Load impedance
    z_load = complex(20, 30)
    z_norm = z_load / 50.0
    print(f"  Load:        Z = {z_load.real:.1f} + j{z_load.imag:.1f} Ω")
    scpi_command(sock, f"SMIT:POIN {z_norm.real},{z_norm.imag}")
    time.sleep(0.5)

    # Step 1: Series capacitor cancels some reactance (smooth transition)
    print("  Adding series capacitor (smooth animation)...")
    for x_cancel in range(0, 26, 2):
        z_step = complex(20, 30 - x_cancel)
        z_norm = z_step / 50.0
        scpi_command(sock, f"SMIT:POIN {z_norm.real},{z_norm.imag}")
        time.sleep(0.1)

    # Step 2: Shunt inductor transforms to 50Ω (smooth transition)
    print("  Adding shunt inductor (smooth animation)...")
    for step in range(11):
        # Linear interpolation from (20, 5) to (50, 0)
        r = 20 + step * 3.0
        x = 5 - step * 0.5
        z_step = complex(r, x)
        z_norm = z_step / 50.0
        scpi_command(sock, f"SMIT:POIN {z_norm.real},{z_norm.imag}")
        time.sleep(0.1)

    print(f"  Final match: Z = 50 + j0 Ω (SWR = 1.0)")
    time.sleep(1)


def demo_crystal_resonance(sock):
    """Demo 3: Crystal impedance near resonance"""
    print("\n=== Demo 3: Crystal Resonance (10 MHz) ===")
    print("Simulating crystal impedance: series resonance locus")
    print("Trace 3 (CYAN): Shows impedance circle near resonance")

    scpi_command(sock, "SMIT:TRAC 3")
    scpi_command(sock, "SMIT:TRAC:COL #00ffff")
    scpi_command(sock, "SMIT:TRAC:LAB 10 MHz Crystal")
    scpi_command(sock, "SMIT:TRAC:CLE")
    scpi_command(sock, "SMIT:SWR 3.0")

    # Crystal equivalent circuit: Rs + jXs
    # Near resonance: impedance traces a circle
    f_series = 10e6

    for freq in range(9_990_000, 10_010_001, 200):
        delta_f = freq - f_series

        # Series resistance: ~15Ω
        r_s = 15

        # Series reactance: proportional to detuning
        x_s = delta_f * 0.003

        z = complex(r_s, x_s)
        z_norm = z / 50.0

        # Mark resonance point
        if abs(delta_f) < 500:
            scpi_command(sock, f"SMIT:MARK:FREQ {freq}")

        scpi_command(sock, f"SMIT:POIN {z_norm.real},{z_norm.imag}")
        time.sleep(0.03)

    print(f"Plotted impedance locus across ±10 kHz")
    time.sleep(1)


def demo_transmission_line(sock):
    """Demo 4: Transmission line impedance transformation"""
    print("\n=== Demo 4: Transmission Line Transformation ===")
    print("Simulating 50Ω coax with 25Ω load: rotation around Smith chart")
    print("Trace 4 (YELLOW): Shows impedance vs electrical length")

    scpi_command(sock, "SMIT:TRAC 4")
    scpi_command(sock, "SMIT:TRAC:COL #ffff00")
    scpi_command(sock, "SMIT:TRAC:LAB 50Ω Coax + 25Ω Load")
    scpi_command(sock, "SMIT:TRAC:CLE")

    # Load impedance
    z_load = complex(25, 0)  # 25Ω resistive
    z_load_norm = z_load / 50.0

    print(f"  Load:     Z = {z_load.real:.1f} Ω")
    scpi_command(sock, f"SMIT:POIN {z_load_norm.real},{z_load_norm.imag}")
    time.sleep(0.3)

    # Convert to reflection coefficient
    gamma_load = (z_load_norm - 1) / (z_load_norm + 1)

    # Rotate around Smith chart (transmission line electrical length)
    print("  Varying line length (0 to λ/2)...")
    for degrees in range(0, 361, 5):
        # Rotate reflection coefficient
        theta = math.radians(degrees)
        gamma_rotated = gamma_load * cmath.exp(1j * 2 * theta)

        # Convert back to impedance
        z_norm = (1 + gamma_rotated) / (1 - gamma_rotated)

        # Mark quarter-wave points
        if degrees in [90, 180, 270]:
            length = degrees / 360.0
            scpi_command(sock, f"SMIT:MARK:FREQ {int(length * 1e6)}")  # Use kHz as marker

        scpi_command(sock, f"SMIT:POIN {z_norm.real},{z_norm.imag}")
        time.sleep(0.05)

    print("  Completed full rotation (360° electrical length)")
    time.sleep(1)


def main():
    """Run comprehensive Smith chart demo"""
    print("=" * 60)
    print("Virtual Smith Chart — Comprehensive Demo")
    print("=" * 60)
    print(f"Connecting to SCPI server at {HOST}:{PORT}...")

    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.connect((HOST, PORT))
        sock.settimeout(2.0)
    except Exception as e:
        print(f"\nERROR: Could not connect to backend server.")
        print(f"Make sure the server is running:")
        print(f"  cd ~/Dropbox/build/rf-bench/virtual/smith-chart/backend")
        print(f"  python3 server.py")
        print(f"\nError details: {e}")
        return 1

    # Query identification
    idn = scpi_query(sock, "*IDN?")
    print(f"Connected to: {idn}")

    # Reset and configure
    print("\nInitializing Smith chart...")
    scpi_command(sock, "*RST")
    scpi_command(sock, "CONF:TITLE Virtual Smith Chart Demo")
    scpi_command(sock, "SMIT:Z0 50")
    scpi_command(sock, "SMIT:GRID ON")
    scpi_command(sock, "SMIT:MODE IMPED")

    print("Configuration complete.")
    print("\nView the chart in your browser:")
    print("  http://localhost:8011")
    print("\nStarting demo sequence...")

    # Run demos
    demo_antenna_sweep(sock)
    demo_matching_network(sock)
    demo_crystal_resonance(sock)
    demo_transmission_line(sock)

    # Final status
    print("\n" + "=" * 60)
    print("Demo Complete!")
    print("=" * 60)
    print("\nThe Smith chart now shows:")
    print("  Trace 1 (GREEN):   20m dipole impedance sweep")
    print("  Trace 2 (MAGENTA): L-network matching transformation")
    print("  Trace 3 (CYAN):    10 MHz crystal resonance locus")
    print("  Trace 4 (YELLOW):  Transmission line transformation")
    print("\nAll traces are visible in the browser.")
    print("The chart will remain active until you close the server.")

    # Check for errors
    error = scpi_query(sock, "SYST:ERR?")
    if not error.startswith("0,"):
        print(f"\nInstrument reported error: {error}")
    else:
        print("\nNo errors reported.")

    sock.close()
    print("\nDemo finished. Press Ctrl+C in the server terminal to exit.")
    return 0


if __name__ == "__main__":
    try:
        exit(main())
    except KeyboardInterrupt:
        print("\n\nDemo interrupted by user.")
        exit(1)
    except Exception as e:
        print(f"\n\nUnexpected error: {e}")
        import traceback
        traceback.print_exc()
        exit(1)
