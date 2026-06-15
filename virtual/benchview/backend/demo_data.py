#!/usr/bin/env python3
"""
Demo data generator for BenchView testing.
Publishes simulated instrument data to MQTT topics.
"""

import time
import random
import math
import paho.mqtt.client as mqtt


def main():
    """Generate demo data"""
    client = mqtt.Client()
    client.connect('localhost', 1883, 60)
    client.loop_start()

    print("Publishing demo data to MQTT...")
    print("Topics:")
    print("  bench/demo/frequency - Frequency in MHz (14.0-14.5)")
    print("  bench/demo/power     - Power in watts (0-100)")
    print("  bench/demo/ptt       - PTT status (0/1)")
    print("  bench/demo/lock      - GPS lock status (0/1)")
    print("\nPress Ctrl+C to stop\n")

    freq_base = 14.200  # MHz
    power_base = 50.0   # W
    ptt_state = False
    lock_state = True
    counter = 0

    try:
        while True:
            # Simulate frequency drift ±50 kHz
            freq = freq_base + 0.050 * math.sin(counter * 0.1)
            client.publish("bench/demo/frequency", f"{freq:.3f}")

            # Simulate power fluctuation
            if ptt_state:
                power = power_base + random.uniform(-5, 5)
            else:
                power = 0.0
            client.publish("bench/demo/power", f"{power:.1f}")

            # Toggle PTT every 10 seconds
            if counter % 50 == 0:
                ptt_state = not ptt_state
                client.publish("bench/demo/ptt", "1" if ptt_state else "0")
                print(f"PTT: {'ON' if ptt_state else 'OFF'}")

            # Simulate GPS lock flickering occasionally
            if counter % 100 == 0:
                lock_state = not lock_state
                client.publish("bench/demo/lock", "1" if lock_state else "0")
                print(f"GPS Lock: {'YES' if lock_state else 'NO'}")

            print(f"Freq: {freq:.3f} MHz, Power: {power:.1f} W", end='\r')

            counter += 1
            time.sleep(0.2)  # 5 Hz update rate

    except KeyboardInterrupt:
        print("\n\nStopping demo data generator...")
        client.loop_stop()
        client.disconnect()


if __name__ == "__main__":
    main()
