#!/usr/bin/env python3
"""MQTT bridge for Arduino+W5100 4-channel network relay board."""

import sys
sys.path.insert(0, "/home/jfrancis/Dropbox/build/rf-bench/drivers/mqtt")
sys.path.insert(0, "/home/jfrancis/Dropbox/build/rf-bench/drivers/arduino-relay-board")

from rf_bench.mqtt import Bridge
from rf_bench.arduino_relay_board import ArduinoRelayBoard


class RelayBridge(Bridge):
    prefix = "/bench/relay"
    poll_interval = 0.5

    def setup(self):
        self.relay = ArduinoRelayBoard("10.1.1.36")
        self.meta(model="Arduino+W5100 4-ch relay", ip="10.1.1.36",
                  driver="rf_bench.arduino_relay_board.ArduinoRelayBoard")

    def poll(self):
        states = self.relay.status_all()
        for i, state in enumerate(states, 1):
            self.publish(f"ch{i}", state)

    def on_command(self, subtopic, payload):
        value = payload.get("value")
        if value is None:
            return

        if subtopic == "ch1/set":
            (self.relay.on if value else self.relay.off)(1)
        elif subtopic == "ch2/set":
            (self.relay.on if value else self.relay.off)(2)
        elif subtopic == "ch3/set":
            (self.relay.on if value else self.relay.off)(3)
        elif subtopic == "ch4/set":
            (self.relay.on if value else self.relay.off)(4)
        elif subtopic == "all_off/set":
            self.relay.all_off()

    def cleanup(self):
        self.relay.close()


if __name__ == "__main__":
    RelayBridge.main()
