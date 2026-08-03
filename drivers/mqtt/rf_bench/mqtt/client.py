"""Thin MQTT client wrapper for rf-bench.

Handles connection, reconnection, JSON encoding/decoding, and retained
message semantics. All values published as JSON objects with at minimum
a 'value' key and a 'ts' (Unix timestamp) key.
"""

import json
import time
from typing import Any, Callable, Optional

import paho.mqtt.client as paho


DEFAULT_BROKER = "10.1.0.20"
DEFAULT_PORT = 1883
KEEPALIVE = 60


class MQTTClient:
    """rf-bench MQTT client with JSON message convention.

    All published messages are JSON: {"value": <val>, "ts": <unix_float>}
    Additional keys can be included via the `extra` parameter.
    """

    def __init__(self, client_id: str, broker: str = DEFAULT_BROKER,
                 port: int = DEFAULT_PORT):
        self._broker = broker
        self._port = port
        self._client = paho.Client(paho.CallbackAPIVersion.VERSION2,
                                   client_id=client_id)
        self._client.on_connect = self._on_connect
        self._client.on_disconnect = self._on_disconnect
        self._client.on_message = self._on_message
        self._connected = False
        self._subscriptions: dict[str, Callable[[str, Any], None]] = {}

    @property
    def connected(self) -> bool:
        return self._connected

    def connect(self, lwt_topic: Optional[str] = None):
        """Connect to broker. Optionally set Last Will and Testament."""
        if lwt_topic:
            payload = json.dumps({"value": False, "ts": time.time()})
            self._client.will_set(lwt_topic, payload, qos=1, retain=True)
        self._client.connect(self._broker, self._port, KEEPALIVE)
        self._client.loop_start()

    def disconnect(self):
        self._client.loop_stop()
        self._client.disconnect()

    def publish(self, topic: str, value: Any, retain: bool = True,
                qos: int = 0, extra: Optional[dict] = None):
        """Publish a JSON message. Value is wrapped in standard envelope."""
        msg = {"value": value, "ts": time.time()}
        if extra:
            msg.update(extra)
        payload = json.dumps(msg)
        self._client.publish(topic, payload, qos=qos, retain=retain)

    def publish_raw(self, topic: str, payload: dict, retain: bool = True,
                    qos: int = 0):
        """Publish an arbitrary JSON dict (caller controls the envelope)."""
        self._client.publish(topic, json.dumps(payload), qos=qos, retain=retain)

    def subscribe(self, topic: str, callback: Callable[[str, Any], None],
                  qos: int = 0):
        """Subscribe to a topic. Callback receives (topic, decoded_json_dict)."""
        self._subscriptions[topic] = callback
        if self._connected:
            self._client.subscribe(topic, qos)

    def unsubscribe(self, topic: str):
        self._subscriptions.pop(topic, None)
        self._client.unsubscribe(topic)

    def _on_connect(self, client, userdata, flags, reason_code, properties=None):
        self._connected = True
        for topic in self._subscriptions:
            self._client.subscribe(topic)

    def _on_disconnect(self, client, userdata, flags, reason_code,
                       properties=None):
        self._connected = False

    def _on_message(self, client, userdata, msg):
        topic = msg.topic
        try:
            data = json.loads(msg.payload.decode())
        except (json.JSONDecodeError, UnicodeDecodeError):
            data = {"value": msg.payload.decode(), "ts": time.time()}

        # Route to matching subscription (supports wildcards via paho)
        for pattern, callback in self._subscriptions.items():
            if paho.topic_matches_sub(pattern, topic):
                callback(topic, data)

    def __enter__(self):
        self.connect()
        return self

    def __exit__(self, *_):
        self.disconnect()
