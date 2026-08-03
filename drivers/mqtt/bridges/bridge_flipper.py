#!/usr/bin/env python3
"""MQTT bridge for Flipper Zero multi-tool.

Publishes device status and Sub-GHz readings when active.
"""

import sys
sys.path.insert(0, "/home/jfrancis/Dropbox/build/rf-bench/drivers/mqtt")
sys.path.insert(0, "/home/jfrancis/Dropbox/build/rf-bench/drivers/flipper")

from rf_bench.mqtt import Bridge
from rf_bench.flipper import FlipperZero


class FlipperBridge(Bridge):
    prefix = "/bench/flipper"
    poll_interval = 2.0

    def setup(self):
        self.flipper = FlipperZero()
        self.meta(model="Flipper Zero", connection="serial",
                  driver="rf_bench.flipper.FlipperZero")

    def poll(self):
        self.publish("connected", True)

        # Publish device info
        try:
            info = self.flipper.device_info()
            if info:
                self.publish("firmware", info.get("firmware", ""))
                self.publish("hardware", info.get("hardware", ""))
        except Exception:
            pass

    def on_command(self, subtopic, payload):
        value = payload.get("value")
        if value is None:
            return

        if subtopic == "subghz/tx/set":
            # Expect {"frequency": Hz, "protocol": str, "data": str}
            if isinstance(value, dict):
                freq = value.get("frequency")
                protocol = value.get("protocol")
                data = value.get("data")
                if freq and data:
                    try:
                        self.flipper.subghz_tx(int(freq), data,
                                               protocol=protocol or "RAW")
                    except Exception:
                        pass

    def cleanup(self):
        self.flipper.close()


if __name__ == "__main__":
    FlipperBridge.main()
