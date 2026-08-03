#!/usr/bin/env python3
"""MQTT bridge for Yertai ET5406A+ programmable DC electronic load.

Note: The ET5406A+ connects via USB serial at /dev/ttyUSB0 on greybox (10.1.0.16).
This bridge must run on the machine with the physical USB connection.
"""

import sys
sys.path.insert(0, "/home/jfrancis/Dropbox/build/rf-bench/drivers/mqtt")
sys.path.insert(0, "/home/jfrancis/Dropbox/build/rf-bench/drivers/yertai")

from rf_bench.mqtt import Bridge
from rf_bench.yertai import ET5406A


class LoadBridge(Bridge):
    prefix = "/bench/load"
    poll_interval = 2.0

    def setup(self):
        self.load = ET5406A()
        self.meta(model="ET5406A+", connection="serial",
                  driver="rf_bench.yertai.ET5406A")

    def poll(self):
        self.publish("voltage_v", self.load.read_voltage())
        self.publish("current_a", self.load.read_current())
        self.publish("power_w", self.load.read_power())
        self.publish("resistance_ohm", self.load.read_resistance())
        self.publish("mode", self.load.mode)
        self.publish("input", self.load.input)

        # Protection status
        prot = self.load.protection
        self.publish("protection/ovp", prot.get("OVP", False))
        self.publish("protection/ocp", prot.get("OCP", False))
        self.publish("protection/opp", prot.get("OPP", False))

    def on_command(self, subtopic, payload):
        value = payload.get("value")
        if value is None:
            return

        if subtopic == "input/set":
            self.load.input = bool(value)
        elif subtopic == "mode/set":
            mode = str(value).upper()
            if mode == "CC":
                self.load.CC_mode(self.load.CC_current)
            elif mode == "CV":
                self.load.CV_mode(self.load.CV_voltage)
            elif mode == "CP":
                self.load.CP_mode(self.load.CP_power)
            elif mode == "CR":
                self.load.CR_mode(self.load.CR_resistance)
        elif subtopic == "current_a/set":
            self.load.CC_current = float(value)
        elif subtopic == "voltage_v/set":
            self.load.CV_voltage = float(value)
        elif subtopic == "power_w/set":
            self.load.CP_power = float(value)
        elif subtopic == "resistance_ohm/set":
            self.load.CR_resistance = float(value)

    def cleanup(self):
        self.load.close()


if __name__ == "__main__":
    LoadBridge.main()
