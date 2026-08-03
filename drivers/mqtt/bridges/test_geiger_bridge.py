#!/usr/bin/env python3
"""Test script for Geiger counter MQTT bridge."""

import sys
import time
import json
sys.path.insert(0, "/home/jfrancis/Dropbox/build/rf-bench/drivers/mqtt")

from rf_bench.mqtt import MQTTClient

BROKER = "10.1.0.20"
PORT = 1883
PREFIX = "/bench/geiger"


def test_bridge():
    """Monitor MQTT messages from Geiger bridge."""
    print("=" * 70)
    print("Geiger Counter MQTT Bridge Test")
    print("=" * 70)
    print(f"Broker: {BROKER}:{PORT}")
    print(f"Topic prefix: {PREFIX}")
    print()
    print("Waiting for messages (Ctrl+C to stop)...")
    print("-" * 70)

    message_count = {}
    first_message_time = None

    def on_message(topic, data):
        nonlocal first_message_time
        if first_message_time is None:
            first_message_time = time.time()

        # Count messages per topic
        message_count[topic] = message_count.get(topic, 0) + 1

        # Handle JSON envelope - data might already be unwrapped
        if isinstance(data, dict):
            if 'value' in data:
                # Standard envelope
                value = data['value']
                ts = data.get('ts', time.time())
            else:
                # Direct dict (like reading blob)
                value = data
                ts = data.get('ts', time.time())
        else:
            # Bare value
            value = data
            ts = time.time()

        # Format output based on topic
        topic_short = topic.replace(PREFIX + '/', '')

        if topic_short == '$online':
            status = "ONLINE ✓" if value else "OFFLINE ✗"
            print(f"\n[{time.strftime('%H:%M:%S')}] Bridge status: {status}\n")

        elif topic_short == 'reading':
            # Full reading blob
            if isinstance(value, dict):
                print(f"[{time.strftime('%H:%M:%S')}] "
                      f"CPS={value.get('cps', '?'):3d}  "
                      f"CPM={value.get('cpm', '?'):4d}  "
                      f"Dose={value.get('dose_usv_hr', 0):.2f} µSv/hr  "
                      f"Mode={value.get('mode', '?')}")
            else:
                print(f"[{time.strftime('%H:%M:%S')}] Reading: {value}")

        elif topic_short == '$meta':
            # Bridge metadata
            print(f"\n[{time.strftime('%H:%M:%S')}] Bridge metadata:")
            if isinstance(value, dict):
                for k, v in value.items():
                    print(f"  {k}: {v}")
            print()

        else:
            # Individual measurement topics
            if topic_short in ['cps', 'cpm']:
                print(f"  {topic_short.upper()}: {value}")
            elif topic_short == 'dose_usv_hr':
                print(f"  Dose: {value:.2f} µSv/hr")
            elif topic_short == 'mode':
                print(f"  Mode: {value}")

    try:
        # Subscribe to all topics under the prefix
        with MQTTClient(BROKER, PORT) as client:
            client.subscribe(f"{PREFIX}/#", on_message)

            # Monitor for 60 seconds
            start = time.time()
            while time.time() - start < 60:
                time.sleep(0.1)

            print("\n" + "=" * 70)
            print("Test Summary")
            print("=" * 70)
            print(f"Duration: {time.time() - (first_message_time or start):.1f} seconds")
            print(f"Total topics: {len(message_count)}")
            print("\nMessage counts by topic:")
            for topic, count in sorted(message_count.items()):
                topic_short = topic.replace(PREFIX + '/', '')
                print(f"  {topic_short}: {count}")

    except KeyboardInterrupt:
        print("\n\nTest interrupted by user")
    except Exception as e:
        print(f"\nError: {e}")
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(test_bridge())
