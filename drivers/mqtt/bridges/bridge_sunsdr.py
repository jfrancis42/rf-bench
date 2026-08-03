#!/usr/bin/env python3
"""MQTT bridge for SunSDR2 Pro (TCI WebSocket interface).

Publishes frequency, mode, and signal level from the TCI connection.
"""

import sys
sys.path.insert(0, "/home/jfrancis/Dropbox/build/rf-bench/drivers/mqtt")
sys.path.insert(0, "/home/jfrancis/Dropbox/build/rf-bench/drivers/sunsdr")

from rf_bench.mqtt import Bridge
from rf_bench.sunsdr import SunSDR


class SunSDRBridge(Bridge):
    prefix = "/bench/sunsdr"
    poll_interval = 1.0

    def setup(self):
        self.sdr = SunSDR()
        self.meta(model="SunSDR2 Pro", connection="tci",
                  driver="rf_bench.sunsdr.SunSDR")

    def poll(self):
        self.publish("connected", self.sdr.is_connected)

        if self.sdr.is_connected:
            self.publish("frequency_hz", self.sdr.frequency)
            self.publish("mode", self.sdr.mode)
            self.publish("sample_rate_hz", self.sdr.sample_rate)

            level = self.sdr.get_smeter()
            if level is not None:
                self.publish("s_meter_dbm", level)

    def on_command(self, subtopic, payload):
        value = payload.get("value")
        if value is None:
            return

        if subtopic == "frequency_hz/set":
            self.sdr.set_frequency(float(value))
        elif subtopic == "mode/set":
            self.sdr.set_mode(str(value))

    def cleanup(self):
        self.sdr.close()


if __name__ == "__main__":
    SunSDRBridge.main()
