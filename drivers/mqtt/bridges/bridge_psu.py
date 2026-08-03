#!/usr/bin/env python3
"""MQTT bridge for Siglent SPD3303X-E triple-output power supply."""

import sys
sys.path.insert(0, "/home/jfrancis/Dropbox/build/rf-bench/drivers/mqtt")
sys.path.insert(0, "/home/jfrancis/Dropbox/build/rf-bench/drivers/siglent")

from rf_bench.mqtt import Bridge
from rf_bench.siglent import SPD3303X


class PSUBridge(Bridge):
    prefix = "/bench/psu"
    poll_interval = 1.0

    def setup(self):
        self.psu = SPD3303X("10.1.1.56")
        self.meta(model="SPD3303X-E", ip="10.1.1.56",
                  driver="rf_bench.siglent.SPD3303X")

    def poll(self):
        for ch in (1, 2, 3):
            self.publish(f"ch{ch}/voltage_v", self.psu.measure_voltage(ch))
            self.publish(f"ch{ch}/current_a", self.psu.measure_current(ch))
            self.publish(f"ch{ch}/power_w", self.psu.measure_power(ch))
            self.publish(f"ch{ch}/output", self.psu.is_enabled(ch))

        status = self.psu.get_status()
        self.publish("ch1/mode", status["ch1_mode"])
        self.publish("ch2/mode", status["ch2_mode"])
        self.publish("tracking", status["track_mode"])

        for ch in (1, 2):
            self.publish(f"ch{ch}/voltage_setpoint_v",
                         self.psu.get_voltage_setpoint(ch))
            self.publish(f"ch{ch}/current_setpoint_a",
                         self.psu.get_current_setpoint(ch))

    def on_command(self, subtopic, payload):
        value = payload.get("value")
        if value is None:
            return

        if subtopic == "ch1/voltage_v/set":
            self.psu.set_voltage(1, float(value))
        elif subtopic == "ch2/voltage_v/set":
            self.psu.set_voltage(2, float(value))
        elif subtopic == "ch1/current_a/set":
            self.psu.set_current(1, float(value))
        elif subtopic == "ch2/current_a/set":
            self.psu.set_current(2, float(value))
        elif subtopic == "ch1/output/set":
            (self.psu.enable if value else self.psu.disable)(1)
        elif subtopic == "ch2/output/set":
            (self.psu.enable if value else self.psu.disable)(2)
        elif subtopic == "ch3/output/set":
            (self.psu.enable if value else self.psu.disable)(3)
        elif subtopic == "tracking/set":
            self.psu.set_tracking(str(value).upper())

    def cleanup(self):
        self.psu.close()


if __name__ == "__main__":
    PSUBridge.main()
