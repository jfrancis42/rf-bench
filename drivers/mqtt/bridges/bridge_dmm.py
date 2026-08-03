#!/usr/bin/env python3
"""MQTT bridge for Siglent SDM3045X bench multimeter."""

import sys
sys.path.insert(0, "/home/jfrancis/Dropbox/build/rf-bench/drivers/mqtt")
sys.path.insert(0, "/home/jfrancis/Dropbox/build/rf-bench/drivers/siglent")

from rf_bench.mqtt import Bridge
from rf_bench.siglent import SDM3000X


class DMMBridge(Bridge):
    prefix = "/bench/dmm"
    poll_interval = 1.0

    def setup(self):
        self.dmm = SDM3000X("10.1.1.63")
        self.meta(model="SDM3045X", ip="10.1.1.63",
                  driver="rf_bench.siglent.SDM3000X")

    def poll(self):
        func = self.dmm.query("FUNC?").strip().strip('"')
        self.publish("function", func)

        value = self.dmm.read()
        self.publish("value", value)

        unit = self._func_to_unit(func)
        if unit:
            self.publish("unit", unit)

    def on_command(self, subtopic, payload):
        value = payload.get("value")
        if value is None:
            return

        if subtopic == "function/set":
            func = str(value).upper()
            func_map = {
                "VDC": "configure_vdc",
                "VAC": "configure_vac",
                "IDC": "configure_idc",
                "IAC": "configure_iac",
                "RES": "configure_resistance",
                "FRES": "configure_resistance",
                "FREQ": "configure_frequency",
                "PER": "configure_period",
                "CONT": "configure_continuity",
                "DIODE": "configure_diode",
            }
            method_name = func_map.get(func)
            if method_name:
                getattr(self.dmm, method_name)()

    def cleanup(self):
        self.dmm.close()

    @staticmethod
    def _func_to_unit(func: str) -> str:
        func = func.upper().replace('"', '')
        mapping = {
            "VOLT": "V", "VOLT:DC": "V", "VOLT:AC": "V",
            "CURR": "A", "CURR:DC": "A", "CURR:AC": "A",
            "RES": "Ω", "FRES": "Ω",
            "FREQ": "Hz", "PER": "s",
            "CONT": "Ω", "DIOD": "V",
            "CAP": "F", "TEMP": "°C",
        }
        return mapping.get(func, "")


if __name__ == "__main__":
    DMMBridge.main()
