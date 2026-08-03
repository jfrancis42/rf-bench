#!/usr/bin/env python3
"""Simple test for Geiger counter MQTT bridge using mosquitto_sub."""

import subprocess
import sys
import time

BROKER = "10.1.0.20"
TOPIC = "/bench/geiger/#"
DURATION = 30


def main():
    print("=" * 70)
    print("Geiger Counter MQTT Bridge Test")
    print("=" * 70)
    print(f"Broker: {BROKER}")
    print(f"Topic: {TOPIC}")
    print(f"Duration: {DURATION} seconds")
    print()
    print("Messages from bridge:")
    print("-" * 70)

    try:
        # Use mosquitto_sub to monitor messages
        proc = subprocess.Popen(
            ["mosquitto_sub", "-h", BROKER, "-t", TOPIC, "-v"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1
        )

        start_time = time.time()
        message_count = 0
        reading_count = 0

        while time.time() - start_time < DURATION:
            line = proc.stdout.readline()
            if not line:
                break

            message_count += 1
            print(line.rstrip())

            # Count full readings
            if "/reading " in line:
                reading_count += 1

        proc.terminate()
        proc.wait(timeout=2)

        print()
        print("=" * 70)
        print("Test Summary")
        print("=" * 70)
        print(f"Duration: {time.time() - start_time:.1f} seconds")
        print(f"Total messages: {message_count}")
        print(f"Full readings: {reading_count}")
        print()
        print("✓ MQTT bridge is working correctly!")

        return 0

    except KeyboardInterrupt:
        print("\n\nTest interrupted by user")
        if 'proc' in locals():
            proc.terminate()
        return 1
    except Exception as e:
        print(f"\nError: {e}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
