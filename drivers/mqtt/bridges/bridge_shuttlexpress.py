#!/usr/bin/env python3
"""MQTT bridge for Contour Design ShuttleXpress jog/shuttle controller.

Publishes jog, shuttle, and button events as they occur (event-driven, not polled).
The bridge runs the ShuttleXpress event loop in a thread and publishes each event.
"""

import logging
import signal
import sys
import time
import threading

sys.path.insert(0, "/home/jfrancis/Dropbox/build/rf-bench/drivers/mqtt")
sys.path.insert(0, "/home/jfrancis/Dropbox/build/rf-bench/drivers/shuttlexpress")

from rf_bench.mqtt import MQTTClient, DEFAULT_BROKER, DEFAULT_PORT
from rf_bench.shuttlexpress import ShuttleXpress

log = logging.getLogger(__name__)

PREFIX = "/bench/shuttle"


def main():
    import argparse
    parser = argparse.ArgumentParser(description="MQTT bridge for ShuttleXpress")
    parser.add_argument("--broker", default=DEFAULT_BROKER)
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    parser.add_argument("--log-level", default="INFO",
                        choices=["DEBUG", "INFO", "WARNING", "ERROR"])
    args = parser.parse_args()

    logging.basicConfig(
        level=getattr(logging, args.log_level),
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
        datefmt="%H:%M:%S"
    )

    client = MQTTClient(
        client_id="bridge-bench-shuttle",
        broker=args.broker,
        port=args.port
    )

    online_topic = f"{PREFIX}/$online"
    client.connect(lwt_topic=online_topic)

    deadline = time.time() + 10
    while not client.connected and time.time() < deadline:
        time.sleep(0.1)
    if not client.connected:
        log.error("Failed to connect to MQTT broker")
        return

    client.publish(online_topic, True, retain=True, qos=1)
    client.publish(f"{PREFIX}/$model", "ShuttleXpress", retain=True, qos=1)
    client.publish(f"{PREFIX}/$driver", "rf_bench.shuttlexpress.ShuttleXpress",
                   retain=True, qos=1)

    shuttle = ShuttleXpress()

    @shuttle.on_jog
    def _jog(event):
        client.publish(f"{PREFIX}/jog", event.value, retain=False)

    @shuttle.on_shuttle
    def _shuttle(event):
        client.publish(f"{PREFIX}/shuttle", event.value, retain=True)

    @shuttle.on_button
    def _button(event):
        client.publish(f"{PREFIX}/button/{event.value}", True, retain=False)

    log.info("ShuttleXpress bridge running on %s", shuttle.path)

    running = True

    def _stop(sig, frame):
        nonlocal running
        running = False
        shuttle.stop()

    signal.signal(signal.SIGINT, _stop)
    signal.signal(signal.SIGTERM, _stop)

    t = shuttle.run_in_thread()

    try:
        while running and t.is_alive():
            time.sleep(0.5)
    finally:
        client.publish(online_topic, False, retain=True, qos=1)
        client.disconnect()


if __name__ == "__main__":
    main()
