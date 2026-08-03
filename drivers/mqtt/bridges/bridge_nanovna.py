#!/usr/bin/env python3
"""MQTT bridge for NanoVNA-F vector network analyzer.

Publishes latest S11/S21 data and VSWR at center frequency after each sweep.
Does NOT auto-sweep continuously — publishes on demand or after user-triggered sweep.
"""

import sys
sys.path.insert(0, "/home/jfrancis/Dropbox/build/rf-bench/drivers/mqtt")
sys.path.insert(0, "/home/jfrancis/Dropbox/build/rf-bench/drivers/nanovna")

import math

from rf_bench.mqtt import Bridge
from rf_bench.nanovna import NanoVNA


class NanoVNABridge(Bridge):
    prefix = "/bench/nanovna"
    poll_interval = 5.0

    def setup(self):
        self.vna = NanoVNA()
        self.meta(model="NanoVNA-F", connection="serial",
                  driver="rf_bench.nanovna.NanoVNA")

    def poll(self):
        # Get S-parameter data from the current sweep
        try:
            freqs, s11, s21 = self.vna.get_s_data_full()
        except Exception:
            return

        if freqs is None or len(freqs) == 0:
            return

        # Publish frequency range
        self.publish("start_hz", float(freqs[0]))
        self.publish("stop_hz", float(freqs[-1]))
        self.publish("points", len(freqs))

        # Find minimum S11 (best match point)
        s11_db = [20 * math.log10(abs(s)) if abs(s) > 0 else -100 for s in s11]
        min_idx = s11_db.index(min(s11_db))
        min_rl = s11_db[min_idx]

        self.publish("s11/min_db", min_rl)
        self.publish("s11/min_freq_hz", float(freqs[min_idx]))

        # VSWR at best-match point
        gamma = abs(s11[min_idx])
        if gamma < 1.0:
            vswr = (1 + gamma) / (1 - gamma)
        else:
            vswr = 99.9
        self.publish("vswr_min", round(vswr, 3))

        # Center-point S21 (insertion loss)
        mid = len(freqs) // 2
        if s21 and len(s21) > mid:
            s21_mid_db = 20 * math.log10(abs(s21[mid])) if abs(s21[mid]) > 0 else -100
            self.publish("s21/center_db", round(s21_mid_db, 2))
            self.publish("s21/center_freq_hz", float(freqs[mid]))

    def on_command(self, subtopic, payload):
        value = payload.get("value")
        if value is None:
            return

        if subtopic == "sweep/set":
            # Expect {"start": Hz, "stop": Hz, "points": N}
            if isinstance(value, dict):
                start = value.get("start")
                stop = value.get("stop")
                points = value.get("points", 401)
                if start and stop:
                    self.vna.setup_sweep(int(start), int(stop), int(points))

    def cleanup(self):
        self.vna.close()


if __name__ == "__main__":
    NanoVNABridge.main()
