"""Base Bridge class for rf-bench MQTT instrument bridges.

A bridge is a thin daemon that connects to one instrument (via its driver)
and publishes its state to MQTT topics. It also subscribes to /set command
topics and translates them into driver calls.

Subclass, define prefix/poll_interval, implement setup()/poll()/on_command().
"""

import argparse
import json
import logging
import signal
import time
from dataclasses import dataclass, field
from typing import Optional

from .client import MQTTClient, DEFAULT_BROKER, DEFAULT_PORT

log = logging.getLogger(__name__)


@dataclass
class BridgeConfig:
    """Configuration for a bridge instance."""
    broker: str = DEFAULT_BROKER
    port: int = DEFAULT_PORT
    poll_interval: float = 2.0
    log_level: str = "INFO"


class Bridge:
    """Base class for instrument MQTT bridges.

    Subclasses must define:
        prefix: str           — MQTT topic prefix (e.g. "bench/ssa")
        poll_interval: float  — seconds between poll() calls

    Subclasses must implement:
        setup()               — connect to the instrument, call self.meta(...)
        poll()                — read instrument state, call self.publish(...)

    Subclasses may implement:
        on_command(subtopic, payload)  — handle /set commands
        cleanup()                      — disconnect from instrument on shutdown
    """

    prefix: str = "/bench/unknown"
    poll_interval: float = 2.0

    def __init__(self, config: Optional[BridgeConfig] = None):
        self.config = config or BridgeConfig()
        self._client: Optional[MQTTClient] = None
        self._running = False

    @property
    def client_id(self) -> str:
        return f"bridge-{self.prefix.replace('/', '-')}"

    def meta(self, **kwargs):
        """Publish metadata topics ($model, $ip, $driver, etc.)."""
        for key, value in kwargs.items():
            topic = f"{self.prefix}/${key}"
            self._client.publish(topic, value, retain=True, qos=1)

    def publish(self, subtopic: str, value, retain: bool = True,
                qos: int = 0, extra: Optional[dict] = None):
        """Publish a measurement to prefix/subtopic."""
        topic = f"{self.prefix}/{subtopic}"
        self._client.publish(topic, value, retain=retain, qos=qos, extra=extra)

    def publish_dict(self, subtopic: str, data: dict, retain: bool = True,
                     qos: int = 0):
        """Publish a multi-field measurement as a single JSON message."""
        topic = f"{self.prefix}/{subtopic}"
        data["ts"] = time.time()
        self._client.publish_raw(topic, data, retain=retain, qos=qos)

    def setup(self):
        """Connect to instrument and publish metadata. Override this."""
        raise NotImplementedError

    def poll(self):
        """Read instrument state and publish. Override this."""
        raise NotImplementedError

    def on_command(self, subtopic: str, payload: dict):
        """Handle a /set command. Override if instrument accepts commands.

        subtopic: the part after prefix/ (e.g. "ch1/voltage/set")
        payload: the decoded JSON dict from the MQTT message
        """
        pass

    def cleanup(self):
        """Disconnect from instrument. Override for cleanup logic."""
        pass

    def _handle_command(self, topic: str, data: dict):
        """Internal: route /set messages to on_command."""
        # Strip prefix and leading slash
        subtopic = topic[len(self.prefix) + 1:]
        try:
            self.on_command(subtopic, data)
        except Exception as e:
            log.error("Command handler error for %s: %s", topic, e)

    def run(self):
        """Main loop: connect, setup, poll forever."""
        logging.basicConfig(
            level=getattr(logging, self.config.log_level.upper(), logging.INFO),
            format="%(asctime)s %(name)s %(levelname)s %(message)s",
            datefmt="%H:%M:%S"
        )

        self._client = MQTTClient(
            client_id=self.client_id,
            broker=self.config.broker,
            port=self.config.port
        )

        online_topic = f"{self.prefix}/$online"
        self._client.connect(lwt_topic=online_topic)

        # Wait for connection
        deadline = time.time() + 10
        while not self._client.connected and time.time() < deadline:
            time.sleep(0.1)
        if not self._client.connected:
            log.error("Failed to connect to MQTT broker at %s:%d",
                      self.config.broker, self.config.port)
            return

        # Publish online status
        self._client.publish(online_topic, True, retain=True, qos=1)

        # Subscribe to command topics
        cmd_topic = f"{self.prefix}/+/set"
        self._client.subscribe(cmd_topic, self._handle_command, qos=1)
        # Also subscribe to nested command topics (e.g. ch1/voltage/set)
        cmd_topic_nested = f"{self.prefix}/+/+/set"
        self._client.subscribe(cmd_topic_nested, self._handle_command, qos=1)

        log.info("Bridge %s connected to %s:%d",
                 self.prefix, self.config.broker, self.config.port)

        # Setup instrument
        try:
            self.setup()
        except Exception as e:
            log.error("Setup failed: %s", e)
            self._client.publish(online_topic, False, retain=True, qos=1)
            self._client.disconnect()
            return

        log.info("Bridge %s setup complete, polling every %.1fs",
                 self.prefix, self.config.poll_interval)

        # Signal handling
        self._running = True

        def _stop(sig, frame):
            self._running = False

        signal.signal(signal.SIGINT, _stop)
        signal.signal(signal.SIGTERM, _stop)

        # Poll loop
        while self._running:
            try:
                self.poll()
            except Exception as e:
                log.error("Poll error: %s", e)
            time.sleep(self.config.poll_interval)

        # Shutdown
        log.info("Bridge %s shutting down", self.prefix)
        self._client.publish(online_topic, False, retain=True, qos=1)
        try:
            self.cleanup()
        except Exception as e:
            log.warning("Cleanup error: %s", e)
        self._client.disconnect()

    @classmethod
    def main(cls):
        """CLI entry point with standard arguments."""
        parser = argparse.ArgumentParser(
            description=f"MQTT bridge for {cls.prefix}")
        parser.add_argument("--broker", default=DEFAULT_BROKER,
                            help=f"MQTT broker address (default: {DEFAULT_BROKER})")
        parser.add_argument("--port", type=int, default=DEFAULT_PORT,
                            help=f"MQTT broker port (default: {DEFAULT_PORT})")
        parser.add_argument("--interval", type=float,
                            default=cls.poll_interval,
                            help=f"Poll interval in seconds (default: {cls.poll_interval})")
        parser.add_argument("--log-level", default="INFO",
                            choices=["DEBUG", "INFO", "WARNING", "ERROR"])
        args = parser.parse_args()

        config = BridgeConfig(
            broker=args.broker,
            port=args.port,
            poll_interval=args.interval,
            log_level=args.log_level,
        )
        bridge = cls(config)
        bridge.run()
