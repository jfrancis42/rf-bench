#!/usr/bin/env python3
"""MQTT bridge for gpsd GPS receiver."""

import sys
sys.path.insert(0, "/home/jfrancis/Dropbox/build/rf-bench/drivers/mqtt")
sys.path.insert(0, "/home/jfrancis/Dropbox/build/rf-bench/drivers/gpsd")

from rf_bench.mqtt import Bridge
from rf_bench.gpsd import GPSD


class GPSBridge(Bridge):
    prefix = "/bench/gps"
    poll_interval = 1.0

    def setup(self):
        self.gps = GPSD()
        self.meta(model="gpsd", connection="localhost:2947",
                  driver="rf_bench.gpsd.GPSD")

    def poll(self):
        if not self.gps.has_fix:
            self.publish("fix", False)
            return

        self.publish("fix", True)
        self.publish("fix_3d", self.gps.has_3d_fix)
        self.publish("lat", self.gps.latitude)
        self.publish("lon", self.gps.longitude)

        alt = self.gps.altitude_ft
        if alt is not None:
            self.publish("alt_ft", alt)

        speed = self.gps.speed_mph
        if speed is not None:
            self.publish("speed_mph", speed)

        heading = self.gps.heading
        if heading is not None:
            self.publish("heading_deg", heading)

        hdop = self.gps.hdop
        if hdop is not None:
            self.publish("hdop", hdop)

        sats = self.gps.satellites_used
        if sats is not None:
            self.publish("satellites_used", sats)

        # Consolidated position blob
        position = {
            "fix": True,
            "fix_3d": self.gps.has_3d_fix,
            "lat": self.gps.latitude,
            "lon": self.gps.longitude,
            "alt_ft": alt,
            "speed_mph": speed,
            "heading_deg": heading,
            "hdop": hdop,
            "satellites_used": sats,
        }
        self.publish_dict("position", position)

    def cleanup(self):
        self.gps.close()


if __name__ == "__main__":
    GPSBridge.main()
