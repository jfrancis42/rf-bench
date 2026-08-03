#!/usr/bin/env python3
"""MQTT-to-relay bridge:
  /test/switch/one   → relay 1 (on/off toggle)
  /test/switch/two   → relay 2 (on/off toggle)
  /test/button/one   → relay 3 (1s pulse on press, re-arms on release)
  /test/button/two   → relay 4 (on while held, auto-off after 30s)
"""

import sys
import signal
import time
import threading
import argparse

sys.path.insert(0, "/home/jfrancis/Dropbox/build/rf-bench/drivers/mqtt")
sys.path.insert(0, "/home/jfrancis/Dropbox/build/rf-bench/drivers/arduino-relay-board")

from rf_bench.mqtt import MQTTClient
from rf_bench.arduino_relay_board import ArduinoRelayBoard

DEFAULT_RELAY_HOST = "10.1.1.36"


def parse_value(data):
    val = data.get("value") if isinstance(data, dict) else data
    if val in (1, "1", True, "true", "on"):
        return True
    elif val in (0, "0", False, "false", "off"):
        return False
    return None


def main():
    parser = argparse.ArgumentParser(description="MQTT-to-relay bridge")
    parser.add_argument("--relay-host", default=DEFAULT_RELAY_HOST,
                        help=f"Arduino relay board IP (default: {DEFAULT_RELAY_HOST})")
    parser.add_argument("--broker", default=None,
                        help="MQTT broker (default: 10.1.0.20)")
    args = parser.parse_args()

    relay = ArduinoRelayBoard(args.relay_host)
    kwargs = {"client_id": "mqtt-relay"}
    if args.broker:
        kwargs["broker"] = args.broker
    mqtt = MQTTClient(**kwargs)
    mqtt.connect()

    deadline = time.time() + 10
    while not mqtt.connected and time.time() < deadline:
        time.sleep(0.1)
    if not mqtt.connected:
        print("Failed to connect to MQTT broker")
        relay.close()
        return

    # --- Switches: simple on/off ---

    def make_switch_handler(relay_num):
        def handler(topic, data):
            val = parse_value(data)
            if val is True:
                relay.on(relay_num)
                print(f"Relay {relay_num} ON")
            elif val is False:
                relay.off(relay_num)
                print(f"Relay {relay_num} OFF")
        return handler

    mqtt.subscribe("/test/switch/one", make_switch_handler(1))
    mqtt.subscribe("/test/switch/two", make_switch_handler(2))

    # --- Button one: pulse relay 3 for 1s on press, re-arm on release ---

    button_one_armed = True
    button_one_lock = threading.Lock()

    def pulse_relay_3():
        nonlocal button_one_armed
        relay.on(3)
        print("Relay 3 PULSE start")
        time.sleep(1)
        relay.off(3)
        print("Relay 3 PULSE end")

    def on_button_one(topic, data):
        nonlocal button_one_armed
        val = parse_value(data)
        if val is True:
            with button_one_lock:
                if button_one_armed:
                    button_one_armed = False
                    threading.Thread(target=pulse_relay_3, daemon=True).start()
        elif val is False:
            with button_one_lock:
                button_one_armed = True
                print("Relay 3 re-armed")

    mqtt.subscribe("/test/button/one", on_button_one)

    # --- Button two: relay 4 on while held, auto-off after 30s ---

    button_two_timer = None
    button_two_lock = threading.Lock()

    def auto_off_relay_4():
        with button_two_lock:
            relay.off(4)
            print("Relay 4 OFF (30s timeout)")

    def on_button_two(topic, data):
        nonlocal button_two_timer
        val = parse_value(data)
        if val is True:
            with button_two_lock:
                if button_two_timer:
                    button_two_timer.cancel()
                relay.on(4)
                print("Relay 4 ON (held)")
                button_two_timer = threading.Timer(30, auto_off_relay_4)
                button_two_timer.daemon = True
                button_two_timer.start()
        elif val is False:
            with button_two_lock:
                if button_two_timer:
                    button_two_timer.cancel()
                    button_two_timer = None
                relay.off(4)
                print("Relay 4 OFF (released)")

    mqtt.subscribe("/test/button/two", on_button_two)

    print(f"Watching topics on {args.relay_host}:")
    print("  /test/switch/one   → relay 1 (toggle)")
    print("  /test/switch/two   → relay 2 (toggle)")
    print("  /test/button/one   → relay 3 (1s pulse)")
    print("  /test/button/two   → relay 4 (hold, 30s max)")

    running = True

    def stop(sig, frame):
        nonlocal running
        running = False

    signal.signal(signal.SIGINT, stop)
    signal.signal(signal.SIGTERM, stop)

    while running:
        time.sleep(1)

    with button_two_lock:
        if button_two_timer:
            button_two_timer.cancel()

    mqtt.disconnect()
    relay.close()


if __name__ == "__main__":
    main()
