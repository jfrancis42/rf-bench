#!/usr/bin/env python3
"""MQTT bridge for Kestrel 5500L weather meter (BLE, async/push-based).

Unlike polled bridges, this runs an asyncio event loop that streams
readings from the Kestrel and publishes each to MQTT as they arrive (~4s).
"""

import asyncio
import logging
import signal
import sys
import time

sys.path.insert(0, "/home/jfrancis/Dropbox/build/rf-bench/drivers/mqtt")
sys.path.insert(0, "/home/jfrancis/Dropbox/build/rf-bench/drivers/kestrel")

from rf_bench.mqtt import MQTTClient, DEFAULT_BROKER, DEFAULT_PORT
from rf_bench.kestrel import Kestrel5500, KestrelReading

log = logging.getLogger(__name__)

KESTREL_MAC = "88:6B:0F:5F:D0:EB"
PREFIX = "/bench/kestrel"


class KestrelBridge:
    """Async MQTT bridge for Kestrel 5500L.

    Does not inherit from Bridge base class because it's event-driven,
    not poll-driven. Uses the same MQTT topic conventions.
    """

    def __init__(self, mac: str = KESTREL_MAC, broker: str = DEFAULT_BROKER,
                 port: int = DEFAULT_PORT):
        self.mac = mac
        self.broker = broker
        self.port = port
        self._client = None
        self._running = True

    def _publish_reading(self, reading: KestrelReading):
        """Publish all Kestrel fields to MQTT."""
        fields = {
            "temperature_c": reading.temperature_c,
            "relative_humidity": reading.relative_humidity,
            "pressure_mbar": reading.pressure_mbar,
            "wind_speed_ms": reading.wind_speed_ms,
            "altitude_m": reading.altitude_m,
            "dew_point_c": reading.dew_point_c,
            "wet_bulb_c": reading.wet_bulb_c,
            "heat_index_c": reading.heat_index_c,
            "wind_chill_c": reading.wind_chill_c,
            "density_altitude_ft": reading.density_altitude_ft,
            "rf_refractivity": reading.rf_refractivity,
            "air_density": reading.air_density,
            "cloud_base_agl_ft": reading.cloud_base_agl_ft,
            "speed_of_sound_ms": reading.speed_of_sound_ms,
            "vapor_pressure_mbar": reading.vapor_pressure_mbar,
            "station_pressure_inhg": reading.station_pressure_inhg,
            "altitude_ft": reading.altitude_ft,
            "wind_speed_mph": reading.wind_speed_mph,
            "wind_speed_kt": reading.wind_speed_kt,
            "temperature_f": reading.temperature_f,
        }

        for key, value in fields.items():
            if value is not None:
                self._client.publish(f"{PREFIX}/{key}", value)

    async def run(self):
        logging.basicConfig(
            level=logging.INFO,
            format="%(asctime)s %(name)s %(levelname)s %(message)s",
            datefmt="%H:%M:%S"
        )

        self._client = MQTTClient(
            client_id="bridge-bench-kestrel",
            broker=self.broker,
            port=self.port
        )

        online_topic = f"{PREFIX}/$online"
        self._client.connect(lwt_topic=online_topic)

        # Wait for MQTT connection
        deadline = time.time() + 10
        while not self._client.connected and time.time() < deadline:
            await asyncio.sleep(0.1)
        if not self._client.connected:
            log.error("Failed to connect to MQTT broker")
            return

        self._client.publish(online_topic, True, retain=True, qos=1)
        self._client.publish(f"{PREFIX}/$model", "Kestrel 5500L", retain=True, qos=1)
        self._client.publish(f"{PREFIX}/$mac", self.mac, retain=True, qos=1)
        self._client.publish(f"{PREFIX}/$driver", "rf_bench.kestrel.Kestrel5500",
                             retain=True, qos=1)

        log.info("MQTT connected, connecting to Kestrel at %s", self.mac)

        kestrel = Kestrel5500(self.mac)

        while self._running:
            try:
                async with kestrel:
                    log.info("Kestrel connected, streaming")
                    async for reading in kestrel.stream():
                        if not self._running:
                            break
                        self._publish_reading(reading)
            except Exception as e:
                log.error("Kestrel connection error: %s", e)
                if self._running:
                    log.info("Reconnecting in 10s...")
                    await asyncio.sleep(10)

        self._client.publish(online_topic, False, retain=True, qos=1)
        self._client.disconnect()


def main():
    import argparse
    parser = argparse.ArgumentParser(description="MQTT bridge for Kestrel 5500L")
    parser.add_argument("--mac", default=KESTREL_MAC,
                        help=f"Kestrel BLE MAC address (default: {KESTREL_MAC})")
    parser.add_argument("--broker", default=DEFAULT_BROKER,
                        help=f"MQTT broker address (default: {DEFAULT_BROKER})")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT,
                        help=f"MQTT broker port (default: {DEFAULT_PORT})")
    args = parser.parse_args()

    bridge = KestrelBridge(mac=args.mac, broker=args.broker, port=args.port)

    loop = asyncio.new_event_loop()

    def _stop():
        bridge._running = False

    loop.add_signal_handler(signal.SIGINT, _stop)
    loop.add_signal_handler(signal.SIGTERM, _stop)

    try:
        loop.run_until_complete(bridge.run())
    finally:
        loop.close()


if __name__ == "__main__":
    main()
