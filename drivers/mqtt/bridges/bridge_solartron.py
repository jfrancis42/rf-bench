#!/usr/bin/env python3
"""MQTT bridge for Solartron 7151 6.5-digit DMM (GPIB via KISS-488).

Hardware pending — KISS-488 adapter not yet installed. Bridge is built
to the driver API and will work once the hardware is connected.

Shares one KISS-488 link with bridge_hp8712b.py — see that file's note on the
adapter's two-session limit, and the local design notes under ``rf-bench/docs/``.

GPIB address 22, not the factory default 16: the HP 8712B is at 16 and the two
instruments share this bus.  Set on the 7151's rear-panel DIP switches; the
change takes effect only after a power-on reset.
"""

import sys
sys.path.insert(0, "/home/jfrancis/Dropbox/build/rf-bench/drivers/mqtt")
sys.path.insert(0, "/home/jfrancis/Dropbox/build/rf-bench/drivers/gpib")
sys.path.insert(0, "/home/jfrancis/Dropbox/build/rf-bench/drivers/solartron")

from rf_bench.gpib import KISS488
from rf_bench.mqtt import Bridge
from rf_bench.solartron import Solartron7151

KISS488_HOST = "10.1.1.70"
SOLARTRON_GPIB_ADDR = 22


class SolartronBridge(Bridge):
    prefix = "/bench/solartron"
    poll_interval = 1.0

    def setup(self):
        self.gpib = KISS488.shared(KISS488_HOST)
        self.dmm = Solartron7151(
            self.gpib.device(SOLARTRON_GPIB_ADDR, name="solartron7151")
        )
        self.meta(model="Solartron 7151", ip=KISS488_HOST,
                  gpib_addr=SOLARTRON_GPIB_ADDR,
                  driver="rf_bench.solartron.Solartron7151")

    def poll(self):
        # TRACK ON (set by the driver's init sequence) means the most recent
        # reading is always available for a bare read.
        try:
            value = self.dmm.read_value()
        except OverflowError:
            self.publish("overload", True)
            return
        except (TimeoutError, ValueError):
            return
        self.publish("value", value)
        self.publish("overload", False)

        self.publish("mode", self.dmm.get_mode())
        self.publish("range", self.dmm.get_range())

    def on_command(self, subtopic, payload):
        value = payload.get("value")
        if value is None:
            return

        if subtopic == "mode/set":
            # Accepts "VDC"/"VAC"/"KOHM"/"IDC"/"IAC" or the integer code 0-4.
            self.dmm.set_mode(value)
        elif subtopic == "range/set":
            # Numeric range code 0-6; see the RANGE_* constants in the driver.
            self.dmm.set_range(int(value))
        elif subtopic == "integration/set":
            self.dmm.set_integration(int(value))

    def cleanup(self):
        self.dmm.close()     # releases this bridge's handle on the adapter
        self.gpib.close()    # releases the shared-adapter reference


if __name__ == "__main__":
    SolartronBridge.main()
