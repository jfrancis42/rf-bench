#!/usr/bin/env python3
"""
Example test script for ESP32 SCPI Servo Controller
Demonstrates servo control and query
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
    print("ESP32 SCPI Servo Controller - Test Script")
    print("=" * 60)

    # Identify device
    idn = scpi_command(ESP32_IP, SCPI_PORT, '*IDN?')
    print(f"Device: {idn}\n")

    print("IMPORTANT: Servos must be powered from external 5V supply!")
    print("           Do NOT power from ESP32 5V pin.\n")

    input("Press Enter when servos are connected and powered...")
    print()

    # Reset to center
    print("Resetting all servos to center (90°):")
    print("-" * 60)
    scpi_command(ESP32_IP, SCPI_PORT, '*RST')
    time.sleep(1)
    print("  ✓ All servos centered\n")

    # Test each servo individually
    print("Testing Individual Servos:")
    print("-" * 60)

    for servo_num in range(1, 5):
        print(f"\n  Testing Servo {servo_num}:")

        # Move to minimum (0°)
        print(f"    Moving to 0°...", end=' ', flush=True)
        scpi_command(ESP32_IP, SCPI_PORT, f'SERV:MIN (@{servo_num})')
        time.sleep(0.5)
        pos = scpi_command(ESP32_IP, SCPI_PORT, f'SERV:POS? (@{servo_num})')
        print(f"Position: {pos}°")

        # Move to center (90°)
        print(f"    Moving to 90°...", end=' ', flush=True)
        scpi_command(ESP32_IP, SCPI_PORT, f'SERV:CENT (@{servo_num})')
        time.sleep(0.5)
        pos = scpi_command(ESP32_IP, SCPI_PORT, f'SERV:POS? (@{servo_num})')
        print(f"Position: {pos}°")

        # Move to maximum (180°)
        print(f"    Moving to 180°...", end=' ', flush=True)
        scpi_command(ESP32_IP, SCPI_PORT, f'SERV:MAX (@{servo_num})')
        time.sleep(0.5)
        pos = scpi_command(ESP32_IP, SCPI_PORT, f'SERV:POS? (@{servo_num})')
        print(f"Position: {pos}°")

        # Return to center
        scpi_command(ESP32_IP, SCPI_PORT, f'SERV:CENT (@{servo_num})')
        time.sleep(0.3)

    print()

    # Test sweep function
    print("Testing Sweep Function:")
    print("-" * 60)

    print("  Sweeping Servo 1: 0° → 180° (5° steps, 20ms delay)")
    scpi_command(ESP32_IP, SCPI_PORT, 'SERV:SWEEP (@1),0,180,5,20')
    print("  ✓ Sweep complete")

    time.sleep(0.5)

    print("  Sweeping Servo 1: 180° → 0° (10° steps, 30ms delay)")
    scpi_command(ESP32_IP, SCPI_PORT, 'SERV:SWEEP (@1),180,0,10,30')
    print("  ✓ Sweep complete")

    time.sleep(0.5)

    print()

    # Test all servos together
    print("Testing Coordinated Motion:")
    print("-" * 60)

    # All to center
    print("  All servos → 90°")
    scpi_command(ESP32_IP, SCPI_PORT, 'SERV:ALL:CENT')
    time.sleep(1)

    # All to one side
    print("  All servos → 0°")
    scpi_command(ESP32_IP, SCPI_PORT, 'SERV:ALL,0')
    time.sleep(1)

    # All to other side
    print("  All servos → 180°")
    scpi_command(ESP32_IP, SCPI_PORT, 'SERV:ALL,180')
    time.sleep(1)

    # Alternating pattern
    print("  Alternating pattern: 0°, 180°, 0°, 180°")
    scpi_command(ESP32_IP, SCPI_PORT, 'SERV:POS (@1),0')
    scpi_command(ESP32_IP, SCPI_PORT, 'SERV:POS (@2),180')
    scpi_command(ESP32_IP, SCPI_PORT, 'SERV:POS (@3),0')
    scpi_command(ESP32_IP, SCPI_PORT, 'SERV:POS (@4),180')
    time.sleep(1)

    # Reverse pattern
    print("  Reverse pattern: 180°, 0°, 180°, 0°")
    scpi_command(ESP32_IP, SCPI_PORT, 'SERV:POS (@1),180')
    scpi_command(ESP32_IP, SCPI_PORT, 'SERV:POS (@2),0')
    scpi_command(ESP32_IP, SCPI_PORT, 'SERV:POS (@3),180')
    scpi_command(ESP32_IP, SCPI_PORT, 'SERV:POS (@4),0')
    time.sleep(1)

    # Return to center
    print("  All servos → 90° (center)")
    scpi_command(ESP32_IP, SCPI_PORT, 'SERV:ALL:CENT')
    time.sleep(1)

    print()

    # Smooth wave motion
    print("Demonstrating Smooth Wave Motion (10 seconds):")
    print("-" * 60)

    start_time = time.time()
    while time.time() - start_time < 10.0:
        elapsed = time.time() - start_time

        # Calculate sine wave positions for each servo (phase-shifted)
        import math
        angle1 = int(90 + 60 * math.sin(elapsed * 2 * math.pi / 3))
        angle2 = int(90 + 60 * math.sin(elapsed * 2 * math.pi / 3 + math.pi/2))
        angle3 = int(90 + 60 * math.sin(elapsed * 2 * math.pi / 3 + math.pi))
        angle4 = int(90 + 60 * math.sin(elapsed * 2 * math.pi / 3 + 3*math.pi/2))

        # Send commands
        scpi_command(ESP32_IP, SCPI_PORT, f'SERV:POS (@1),{angle1}')
        scpi_command(ESP32_IP, SCPI_PORT, f'SERV:POS (@2),{angle2}')
        scpi_command(ESP32_IP, SCPI_PORT, f'SERV:POS (@3),{angle3}')
        scpi_command(ESP32_IP, SCPI_PORT, f'SERV:POS (@4),{angle4}')

        print(f"  {elapsed:5.2f}s | Servo 1: {angle1:3d}° | Servo 2: {angle2:3d}° | "
              f"Servo 3: {angle3:3d}° | Servo 4: {angle4:3d}°")

        time.sleep(0.1)

    print()

    # Return to center and finish
    print("Returning all servos to center:")
    print("-" * 60)
    scpi_command(ESP32_IP, SCPI_PORT, 'SERV:ALL:CENT')
    print("  ✓ All servos centered\n")

    print("Test complete!")
    print("\nNote: Servos will remain energized (holding position) until")
    print("      ESP32 is powered off or a new position command is sent.")


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
        print("Centering all servos before exit...")
        try:
            scpi_command(ESP32_IP, SCPI_PORT, 'SERV:ALL:CENT')
        except:
            pass
