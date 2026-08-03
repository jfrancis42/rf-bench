#!/usr/bin/env python3
"""MQTT bridge for HP 8712B vector network analyzer (GPIB via KISS-488).

Hardware pending — KISS-488 adapter not yet installed. Bridge is built
to the driver API and will work once the hardware is connected.

Shares one KISS-488 link with bridge_solartron.py.  Both bridges call
``KISS488.shared()``, so if they run in the same process they use a single
socket; run as separate daemons they each take one of the adapter's **two**
available Telnet sessions and no third client can connect.  See
the local design notes under ``rf-bench/docs/``.
"""

import sys
sys.path.insert(0, "/home/jfrancis/Dropbox/build/rf-bench/drivers/mqtt")
sys.path.insert(0, "/home/jfrancis/Dropbox/build/rf-bench/drivers/gpib")
sys.path.insert(0, "/home/jfrancis/Dropbox/build/rf-bench/drivers/hp")

from rf_bench.gpib import KISS488
from rf_bench.mqtt import Bridge
from rf_bench.hp import HP8712B

KISS488_HOST = "10.1.1.70"
HP8712B_GPIB_ADDR = 16


class HP8712BBridge(Bridge):
    prefix = "/bench/hp8712b"
    poll_interval = 5.0

    def setup(self):
        self.gpib = KISS488.shared(KISS488_HOST)
        self.vna = HP8712B(self.gpib.device(HP8712B_GPIB_ADDR, name="hp8712b"))
        self.meta(model="HP 8712B", ip=KISS488_HOST,
                  gpib_addr=HP8712B_GPIB_ADDR,
                  driver="rf_bench.hp.HP8712B")

    def poll(self):
        freqs = self.vna.get_frequencies()
        if freqs is None or len(freqs) == 0:
            return

        self.publish("start_hz", float(freqs[0]))
        self.publish("stop_hz", float(freqs[-1]))
        self.publish("points", len(freqs))

        param = self.vna.get_parameter()
        self.publish("parameter", param)

        # Get trace data
        try:
            trace_db = self.vna.get_trace_db()
            if trace_db is not None and len(trace_db) > 0:
                min_idx = int(min(range(len(trace_db)), key=lambda i: trace_db[i]))
                self.publish("min_db", float(trace_db[min_idx]))
                self.publish("min_freq_hz", float(freqs[min_idx]))

                # If S11, compute VSWR at min point
                if param and "S11" in param.upper():
                    rl_db = abs(trace_db[min_idx])
                    gamma = 10 ** (-rl_db / 20)
                    if gamma < 1.0:
                        vswr = (1 + gamma) / (1 - gamma)
                    else:
                        vswr = 99.9
                    self.publish("vswr_min", round(vswr, 3))
        except Exception:
            pass

    def on_command(self, subtopic, payload):
        value = payload.get("value")
        if value is None:
            return

        if subtopic == "sweep/set":
            if isinstance(value, dict):
                start = value.get("start")
                stop = value.get("stop")
                points = value.get("points", 401)
                if start and stop:
                    self.vna.setup_sweep(int(start), int(stop), int(points))
        elif subtopic == "parameter/set":
            self.vna.set_parameter(str(value))

    def cleanup(self):
        self.vna.close()     # releases this bridge's handle on the adapter
        self.gpib.close()    # releases the shared-adapter reference


if __name__ == "__main__":
    HP8712BBridge.main()
