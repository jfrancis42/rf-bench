#!/usr/bin/env python3
"""MQTT bridge for Koolertron/MHinstek MHS-5225A DDS generator + counter.

Note: Connects via USB serial. This bridge must run on the machine with
the physical USB connection (10.1.1.52 or wherever it's plugged in).
"""

import sys
sys.path.insert(0, "/home/jfrancis/Dropbox/build/rf-bench/drivers/mqtt")
sys.path.insert(0, "/home/jfrancis/Dropbox/build/rf-bench/drivers/koolertron")

from rf_bench.mqtt import Bridge
from rf_bench.koolertron import MHS5200A


class MHS5225Bridge(Bridge):
    prefix = "/bench/mhs5225"
    poll_interval = 2.0

    def setup(self):
        self.gen = MHS5200A()
        self.meta(model="MHS-5225A", connection="serial",
                  driver="rf_bench.koolertron.MHS5200A")

    def poll(self):
        for ch in (1, 2):
            self.publish(f"ch{ch}/frequency_hz", self.gen.get_frequency(ch))
            self.publish(f"ch{ch}/amplitude_vpp", self.gen.get_amplitude(ch))
            self.publish(f"ch{ch}/waveform", self.gen.get_waveform(ch))
            self.publish(f"ch{ch}/duty_cycle", self.gen.get_duty_cycle(ch))
            self.publish(f"ch{ch}/phase_deg", self.gen.get_phase(ch))

        # Counter reading (may return 0 if counter not active)
        try:
            freq = self.gen.read_counter_hz()
            self.publish("counter/freq_hz", freq)
        except Exception:
            pass

    def on_command(self, subtopic, payload):
        value = payload.get("value")
        if value is None:
            return

        if subtopic == "ch1/frequency_hz/set":
            self.gen.set_frequency(1, float(value))
        elif subtopic == "ch2/frequency_hz/set":
            self.gen.set_frequency(2, float(value))
        elif subtopic == "ch1/amplitude_vpp/set":
            self.gen.set_amplitude(1, float(value))
        elif subtopic == "ch2/amplitude_vpp/set":
            self.gen.set_amplitude(2, float(value))
        elif subtopic == "output/set":
            if value:
                self.gen.output_on()
            else:
                self.gen.output_off()

    def cleanup(self):
        self.gen.close()


if __name__ == "__main__":
    MHS5225Bridge.main()
