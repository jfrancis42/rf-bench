#!/usr/bin/env python3
"""MQTT bridge for Yaesu FT-891 HF transceiver (via Hamlib rigctld)."""

import sys
sys.path.insert(0, "/home/jfrancis/Dropbox/build/rf-bench/drivers/mqtt")
sys.path.insert(0, "/home/jfrancis/Dropbox/build/rf-bench/drivers/yaesu")

from rf_bench.mqtt import Bridge
from rf_bench.yaesu import FT891


class FT891Bridge(Bridge):
    prefix = "/bench/ft891"
    poll_interval = 0.5

    def setup(self):
        self.radio = FT891()
        self.meta(model="FT-891", connection="rigctld:4532",
                  driver="rf_bench.yaesu.FT891")

    def poll(self):
        self.publish("frequency_hz", self.radio.get_frequency())

        mode, passband = self.radio.get_mode()
        self.publish("mode", mode)
        self.publish("passband_hz", passband)

        self.publish("s_meter_dbm", self.radio.get_strength())

    def on_command(self, subtopic, payload):
        value = payload.get("value")
        if value is None:
            return

        if subtopic == "frequency_hz/set":
            self.radio.set_frequency(float(value))
        elif subtopic == "mode/set":
            self.radio.set_mode(str(value))
        elif subtopic == "agc/set":
            self.radio.set_agc(str(value))

    def cleanup(self):
        self.radio.close()


if __name__ == "__main__":
    FT891Bridge.main()
