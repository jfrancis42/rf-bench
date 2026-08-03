#!/usr/bin/env python3
"""MQTT bridge for MightyOhm Geiger Counter."""

import sys
import logging
sys.path.insert(0, "/home/jfrancis/Dropbox/build/rf-bench/drivers/mqtt")
sys.path.insert(0, "/home/jfrancis/Dropbox/build/rf-bench/drivers/mightyohm")

from rf_bench.mqtt import Bridge
from rf_bench.mightyohm import MightyOhmGeiger, MightyOhmGeigerError

log = logging.getLogger(__name__)


class GeigerBridge(Bridge):
    prefix = "/bench/geiger"
    poll_interval = 1.0  # Match device output rate

    def setup(self):
        """Initialize Geiger counter connection."""
        try:
            self.geiger = MightyOhmGeiger()
            self.meta(
                model="MightyOhm Geiger Counter v1.0",
                connection=self.geiger.port,
                driver="rf_bench.mightyohm.MightyOhmGeiger",
                tube_type=self.geiger.tube_type,
                conversion_factor=self.geiger.conversion_factor
            )
            log.info(f"Connected to Geiger counter on {self.geiger.port}")
            log.info(f"Tube type: {self.geiger.tube_type}")
        except MightyOhmGeigerError as e:
            log.error(f"Failed to connect to Geiger counter: {e}")
            raise

    def poll(self):
        """Read and publish radiation measurements."""
        try:
            reading = self.geiger.read()

            # Publish individual measurements
            self.publish("cps", reading['cps'])
            self.publish("cpm", reading['cpm'])
            self.publish("dose_usv_hr", reading['dose_usv_hr'])
            self.publish("mode", reading['mode'])

            # Consolidated reading blob
            self.publish_dict("reading", {
                "cps": reading['cps'],
                "cpm": reading['cpm'],
                "dose_usv_hr": reading['dose_usv_hr'],
                "mode": reading['mode'],
            })

        except MightyOhmGeigerError as e:
            log.error(f"Error reading from Geiger counter: {e}")
            # Don't raise — let the bridge retry on next poll

    def cleanup(self):
        """Close Geiger counter connection."""
        if hasattr(self, 'geiger'):
            self.geiger.close()
            log.info("Geiger counter connection closed")


if __name__ == "__main__":
    GeigerBridge.main()
