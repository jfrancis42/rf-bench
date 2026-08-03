#!/usr/bin/env python3
"""MQTT bridge for KiwiSDR HF receiver (0-30 MHz, WebSocket).

Publishes current frequency, mode, and S-meter level.
"""

import sys
sys.path.insert(0, "/home/jfrancis/Dropbox/build/rf-bench/drivers/mqtt")
sys.path.insert(0, "/home/jfrancis/Dropbox/build/rf-bench/drivers/kiwisdr")

from rf_bench.mqtt import Bridge
from rf_bench.kiwisdr import KiwiSDR


class KiwiSDRBridge(Bridge):
    prefix = "/bench/kiwisdr"
    poll_interval = 2.0

    def setup(self):
        self.kiwi = KiwiSDR()
        self.meta(model="KiwiSDR", driver="rf_bench.kiwisdr.KiwiSDR")

    def poll(self):
        self.publish("connected", self.kiwi.is_connected)

        if self.kiwi.is_connected:
            self.publish("frequency_hz", self.kiwi.frequency)
            self.publish("mode", self.kiwi.mode)

            level = self.kiwi.get_smeter()
            if level is not None:
                self.publish("s_meter_dbm", level)

    def on_command(self, subtopic, payload):
        value = payload.get("value")
        if value is None:
            return

        if subtopic == "frequency_hz/set":
            self.kiwi.set_frequency(float(value))
        elif subtopic == "mode/set":
            self.kiwi.set_mode(str(value))

    def cleanup(self):
        self.kiwi.close()


if __name__ == "__main__":
    KiwiSDRBridge.main()
