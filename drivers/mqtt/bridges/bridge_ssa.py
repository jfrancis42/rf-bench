#!/usr/bin/env python3
"""MQTT bridge for Siglent SSA3032X Plus spectrum analyzer.

Publishes marker values and peak data. Does NOT publish full traces
(801 points per sweep) — that stays in direct SCPI.
"""

import sys
sys.path.insert(0, "/home/jfrancis/Dropbox/build/rf-bench/drivers/mqtt")
sys.path.insert(0, "/home/jfrancis/Dropbox/build/rf-bench/drivers/siglent")

from rf_bench.mqtt import Bridge
from rf_bench.siglent import SSA3000X


class SSABridge(Bridge):
    prefix = "/bench/ssa"
    poll_interval = 2.0

    def setup(self):
        self.ssa = SSA3000X("10.1.1.60")
        self.meta(model="SSA3032X Plus", ip="10.1.1.60",
                  driver="rf_bench.siglent.SSA3000X")

    def poll(self):
        # Frequency range
        start = self.ssa.query(":FREQ:STAR?").strip()
        stop = self.ssa.query(":FREQ:STOP?").strip()
        center = self.ssa.query(":FREQ:CENT?").strip()
        span = self.ssa.query(":FREQ:SPAN?").strip()

        self.publish("start_hz", float(start))
        self.publish("stop_hz", float(stop))
        self.publish("center_hz", float(center))
        self.publish("span_hz", float(span))

        # Reference level
        ref = self.ssa.query(":DISP:WIND:TRAC:Y:SCAL:RLEV?").strip()
        self.publish("ref_level_dbm", float(ref))

        # RBW
        rbw = self.ssa.query(":BAND?").strip()
        self.publish("rbw_hz", float(rbw))

        # Peak search on current trace
        trace = self.ssa.get_trace()
        if trace is not None and len(trace) > 0:
            peak_freq, peak_level = self.ssa.get_peak(trace)
            self.publish("peak/freq_hz", peak_freq)
            self.publish("peak/level_dbm", peak_level)

    def on_command(self, subtopic, payload):
        value = payload.get("value")
        if value is None:
            return

        if subtopic == "center_hz/set":
            self.ssa.write(f":FREQ:CENT {float(value)}")
        elif subtopic == "span_hz/set":
            self.ssa.write(f":FREQ:SPAN {float(value)}")
        elif subtopic == "ref_level_dbm/set":
            self.ssa.set_ref_level(float(value))
        elif subtopic == "rbw_hz/set":
            self.ssa.write(f":BAND {float(value)}")

    def cleanup(self):
        self.ssa.close()


if __name__ == "__main__":
    SSABridge.main()
