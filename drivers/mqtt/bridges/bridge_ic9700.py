#!/usr/bin/env python3
"""MQTT bridge for Icom IC-9700 VHF/UHF/SHF transceiver (via Hamlib rigctld)."""

import sys
sys.path.insert(0, "/home/jfrancis/Dropbox/build/rf-bench/drivers/mqtt")
sys.path.insert(0, "/home/jfrancis/Dropbox/build/rf-bench/drivers/icom")

from rf_bench.mqtt import Bridge
from rf_bench.icom import IC9700


class IC9700Bridge(Bridge):
    prefix = "/bench/ic9700"
    poll_interval = 0.5

    def setup(self):
        self.radio = IC9700()
        self.meta(model="IC-9700", connection="rigctld:4532",
                  driver="rf_bench.icom.IC9700")

    def poll(self):
        self.publish("frequency_hz", self.radio.get_frequency())

        mode, passband = self.radio.get_mode()
        self.publish("mode", mode)
        self.publish("passband_hz", passband)

        self.publish("s_meter_dbm", self.radio.get_strength())

        vfo = self.radio.get_vfo()
        self.publish("vfo", vfo)

        split = self.radio.get_split()
        self.publish("split", split)

        ptt = self.radio.get_ptt()
        self.publish("ptt", ptt)

    def on_command(self, subtopic, payload):
        value = payload.get("value")
        if value is None:
            return

        if subtopic == "frequency_hz/set":
            self.radio.set_frequency(float(value))
        elif subtopic == "mode/set":
            self.radio.set_mode(str(value))
        elif subtopic == "vfo/set":
            self.radio.set_vfo(str(value))
        elif subtopic == "ptt/set":
            self.radio.set_ptt(bool(value))
        elif subtopic == "agc/set":
            self.radio.set_agc(str(value))

    def cleanup(self):
        self.radio.close()


if __name__ == "__main__":
    IC9700Bridge.main()
