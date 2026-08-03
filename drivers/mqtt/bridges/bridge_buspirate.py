#!/usr/bin/env python3
"""MQTT bridge for Bus Pirate (v3/v4/v5).

Publishes Bus Pirate connection status and version info.
Commands allow raw I2C/SPI/UART operations via MQTT.
"""

import sys
sys.path.insert(0, "/home/jfrancis/Dropbox/build/rf-bench/drivers/mqtt")
sys.path.insert(0, "/home/jfrancis/Dropbox/build/rf-bench/drivers/buspirate")

from rf_bench.mqtt import Bridge
from rf_bench.buspirate import BusPirate


class BusPirateBridge(Bridge):
    prefix = "/bench/buspirate"
    poll_interval = 5.0

    def setup(self):
        self.bp = BusPirate()
        self.meta(model="Bus Pirate", connection="serial",
                  driver="rf_bench.buspirate.BusPirate")

    def poll(self):
        self.publish("connected", True)

    def on_command(self, subtopic, payload):
        value = payload.get("value")
        if value is None:
            return

        if subtopic == "i2c_scan/set":
            try:
                devices = self.bp.i2c_scan()
                self.publish("i2c_devices", devices)
            except Exception:
                pass

    def cleanup(self):
        self.bp.close()


if __name__ == "__main__":
    BusPirateBridge.main()
