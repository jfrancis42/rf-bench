#!/usr/bin/env python3
"""MQTT bridge for Siglent SDG1062X dual-channel function generator."""

import sys
sys.path.insert(0, "/home/jfrancis/Dropbox/build/rf-bench/drivers/mqtt")
sys.path.insert(0, "/home/jfrancis/Dropbox/build/rf-bench/drivers/siglent")

from rf_bench.mqtt import Bridge
from rf_bench.siglent import SDG1000X


class SDGBridge(Bridge):
    prefix = "/bench/sdg"
    poll_interval = 2.0

    def setup(self):
        self.sdg = SDG1000X("10.1.1.55")
        self.meta(model="SDG1062X", ip="10.1.1.55",
                  driver="rf_bench.siglent.SDG1000X")

    def poll(self):
        for ch in (1, 2):
            info = self.sdg.query_channel(ch)
            self.publish(f"ch{ch}/frequency_hz", info.get("freq_hz"))
            self.publish(f"ch{ch}/amplitude_dbm", info.get("level_dbm"))
            self.publish(f"ch{ch}/amplitude_vpp", info.get("amp_vpp"))
            self.publish(f"ch{ch}/phase_deg", info.get("phase_deg"))
            self.publish(f"ch{ch}/waveform", info.get("waveform"))
            self.publish(f"ch{ch}/output", self.sdg.query_output_state(ch))

    def on_command(self, subtopic, payload):
        value = payload.get("value")
        if value is None:
            return

        if subtopic == "ch1/frequency_hz/set":
            self.sdg.set_frequency(1, float(value))
        elif subtopic == "ch2/frequency_hz/set":
            self.sdg.set_frequency(2, float(value))
        elif subtopic == "ch1/amplitude_dbm/set":
            self.sdg.set_level(1, float(value))
        elif subtopic == "ch2/amplitude_dbm/set":
            self.sdg.set_level(2, float(value))
        elif subtopic == "ch1/output/set":
            (self.sdg.output_on if value else self.sdg.output_off)(1)
        elif subtopic == "ch2/output/set":
            (self.sdg.output_on if value else self.sdg.output_off)(2)

    def cleanup(self):
        self.sdg.close()


if __name__ == "__main__":
    SDGBridge.main()
