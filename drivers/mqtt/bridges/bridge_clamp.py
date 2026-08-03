#!/usr/bin/env python3
"""MQTT bridge for the Fluke 80i-400 AC current clamp read via a bench DMM.

Publishes conductor current (amps) and its datasheet uncertainty to the
rf-bench MQTT bus. The clamp is a passive 1 mA/A current transformer read on
the DMM's AC-current (mA) range — see rf_bench.fluke.

Publishes CURRENT only, never power: the clamp cannot see voltage, so watts
would require the separate (voltage-sensing) ac-power project. See
ideas/fluke-80i400-projects.md.

Env/args: the DMM must be manually set to AC current (mA) before starting.
"""

import sys
sys.path.insert(0, "/home/jfrancis/Dropbox/build/rf-bench/drivers/mqtt")
sys.path.insert(0, "/home/jfrancis/Dropbox/build/rf-bench/drivers/siglent")
sys.path.insert(0, "/home/jfrancis/Dropbox/build/rf-bench/drivers/fluke")

from rf_bench.mqtt import Bridge
from rf_bench.siglent import SDM3000X
from rf_bench.fluke import Fluke80i400


class ClampBridge(Bridge):
    prefix = "/bench/clamp"
    poll_interval = 1.0

    # DMM used as the clamp readout. Same meter as bridge_dmm; ensure only one
    # bridge drives it at a time, and set the meter to AC current (mA) first.
    DMM_IP = "10.1.1.63"

    def setup(self):
        self.dmm = SDM3000X(self.DMM_IP)
        self.dmm.configure_iac()               # AC current mode
        self.clamp = Fluke80i400(dmm=self.dmm)
        self.meta(model="Fluke 80i-400", ip=self.DMM_IP,
                  driver="rf_bench.fluke.Fluke80i400",
                  ratio="1 mA/A", readout="SDM3045X AC mA")

    def poll(self):
        r = self.clamp.read()
        self.publish("amps", round(r.amps, 3))
        self.publish("in_range", int(r.in_range))
        if r.uncertainty is not None:
            self.publish("uncertainty_a", round(r.uncertainty, 3))

    def cleanup(self):
        self.dmm.close()


if __name__ == "__main__":
    ClampBridge.main()
