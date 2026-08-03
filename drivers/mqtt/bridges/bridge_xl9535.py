#!/usr/bin/env python3
"""MQTT bridge for XL9535 I2C relay board (via Bus Pirate).

Hardware ordered — not yet tested. Bridge built to the driver API.
"""

import sys
sys.path.insert(0, "/home/jfrancis/Dropbox/build/rf-bench/drivers/mqtt")
sys.path.insert(0, "/home/jfrancis/Dropbox/build/rf-bench/drivers/relay")

from rf_bench.mqtt import Bridge
from rf_bench.relay import XL9535


class XL9535Bridge(Bridge):
    prefix = "/bench/xl9535"
    poll_interval = 0.5

    def setup(self):
        self.relay = XL9535()
        self.meta(model="XL9535 I2C Relay", connection="i2c:buspirate",
                  driver="rf_bench.relay.XL9535")

    def poll(self):
        states = self.relay.read_all()
        for i, state in enumerate(states, 1):
            self.publish(f"ch{i}", state)

    def on_command(self, subtopic, payload):
        value = payload.get("value")
        if value is None:
            return

        # Match ch1/set through ch16/set
        for i in range(1, 17):
            if subtopic == f"ch{i}/set":
                if value:
                    self.relay.on(i)
                else:
                    self.relay.off(i)
                return

        if subtopic == "all_off/set":
            self.relay.all_off()

    def cleanup(self):
        self.relay.close()


if __name__ == "__main__":
    XL9535Bridge.main()
