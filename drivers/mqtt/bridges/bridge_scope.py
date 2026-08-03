#!/usr/bin/env python3
"""MQTT bridge for Siglent SDS2504X Plus oscilloscope.

Publishes per-channel Vpp, RMS, frequency, and trigger status.
Does NOT publish waveform data — that stays in direct SCPI.
"""

import sys
sys.path.insert(0, "/home/jfrancis/Dropbox/build/rf-bench/drivers/mqtt")
sys.path.insert(0, "/home/jfrancis/Dropbox/build/rf-bench/drivers/siglent")

import logging

from rf_bench.mqtt import Bridge
from rf_bench.siglent import SDS2000X

log = logging.getLogger(__name__)


class ScopeBridge(Bridge):
    prefix = "/bench/scope"
    poll_interval = 2.0

    def setup(self):
        self.scope = SDS2000X("10.1.1.58")
        self.meta(model="SDS2504X Plus", ip="10.1.1.58",
                  driver="rf_bench.siglent.SDS2000X")

    def poll(self):
        for ch in (1, 2, 3, 4):
            try:
                vpp = self.scope.measure_vpp(ch)
                self.publish(f"ch{ch}/vpp_v", vpp)
            except Exception:
                pass

            try:
                rms = self.scope.measure_rms(ch)
                self.publish(f"ch{ch}/rms_v", rms)
            except Exception:
                pass

            try:
                freq = self.scope.measure_freq(ch)
                self.publish(f"ch{ch}/frequency_hz", freq)
            except Exception:
                pass

        # Timebase
        try:
            tdiv = self.scope._query(":TDIV?").strip()
            self.publish("timebase_s_div", float(tdiv))
        except Exception:
            pass

        # Trigger status
        try:
            trig = self.scope._query("TRIG_MODE?").strip()
            self.publish("trigger_mode", trig)
        except Exception:
            pass

    def on_command(self, subtopic, payload):
        value = payload.get("value")
        if value is None:
            return

        if subtopic == "run/set":
            if value:
                self.scope.run()
            else:
                self.scope.stop()

    def cleanup(self):
        self.scope.close()


if __name__ == "__main__":
    ScopeBridge.main()
