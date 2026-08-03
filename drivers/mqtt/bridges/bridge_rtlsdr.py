#!/usr/bin/env python3
"""MQTT bridge for RTL-SDR Blog v4 receiver.

Publishes center frequency, sample rate, and peak power from a snapshot
power spectrum measurement each poll cycle. Does NOT publish raw IQ.
"""

import sys
sys.path.insert(0, "/home/jfrancis/Dropbox/build/rf-bench/drivers/mqtt")
sys.path.insert(0, "/home/jfrancis/Dropbox/build/rf-bench/drivers/rtlsdr")

import numpy as np

from rf_bench.mqtt import Bridge
from rf_bench.rtlsdr import RTLSDR


class RTLSDRBridge(Bridge):
    prefix = "/bench/rtlsdr"
    poll_interval = 1.0

    def setup(self):
        self.sdr = RTLSDR()
        info = self.sdr.identify()
        self.meta(model=info.get("tuner", "RTL-SDR"),
                  driver="rf_bench.rtlsdr.RTLSDR")

    def poll(self):
        self.publish("center_freq_hz", self.sdr._sdr.center_freq)
        self.publish("sample_rate_hz", self.sdr._sdr.sample_rate)
        self.publish("gain_db", self.sdr._sdr.gain)

        # Power spectrum snapshot
        try:
            freqs, psd_db = self.sdr.power_spectrum()
            peak_idx = int(np.argmax(psd_db))
            self.publish("peak/freq_hz", float(freqs[peak_idx]))
            self.publish("peak/power_dbfs", float(psd_db[peak_idx]))
        except Exception:
            pass

    def on_command(self, subtopic, payload):
        value = payload.get("value")
        if value is None:
            return

        if subtopic == "center_freq_hz/set":
            self.sdr.set_center_freq(int(float(value)))
        elif subtopic == "sample_rate_hz/set":
            self.sdr.set_sample_rate(int(float(value)))
        elif subtopic == "gain_db/set":
            self.sdr.set_gain(float(value))
        elif subtopic == "bias_tee/set":
            self.sdr.set_bias_tee(bool(value))

    def cleanup(self):
        self.sdr.close()


if __name__ == "__main__":
    RTLSDRBridge.main()
