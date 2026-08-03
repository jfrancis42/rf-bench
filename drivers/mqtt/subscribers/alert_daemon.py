#!/usr/bin/env python3
"""MQTT alert daemon — monitors bench topics and triggers alerts
when thresholds are crossed.

Configuration is a YAML file defining rules. Each rule specifies:
- topic: MQTT topic to watch
- condition: Python expression evaluated with `value` as the measurement
- message: Alert text (can include {value} and {topic} placeholders)
- action: "sms" or "log" (default: log)
- cooldown_s: Minimum seconds between repeated alerts (default: 300)

Example config (alerts.yaml):
    rules:
      - topic: /bench/psu/ch1/voltage_v
        condition: "value < 11.5"
        message: "PSU CH1 voltage low: {value:.2f} V"
        action: sms
        cooldown_s: 600

      - topic: /bench/kestrel/temperature_c
        condition: "value > 45"
        message: "Ambient temperature high: {value:.1f} °C"
        action: sms

      - topic: /bench/load/protection/ovp
        condition: "value == True"
        message: "DC load OVP triggered!"
        action: sms
        cooldown_s: 60

Usage:
    python alert_daemon.py --config alerts.yaml
"""

import argparse
import json
import logging
import os
import signal
import subprocess
import sys
import time

sys.path.insert(0, "/home/jfrancis/Dropbox/build/rf-bench/drivers/mqtt")

from rf_bench.mqtt import MQTTClient, DEFAULT_BROKER, DEFAULT_PORT

log = logging.getLogger(__name__)

try:
    import yaml
except ImportError:
    yaml = None


def load_config(path: str) -> dict:
    if yaml is None:
        raise ImportError("PyYAML required: pip install pyyaml")
    with open(path) as f:
        return yaml.safe_load(f)


class AlertRule:
    def __init__(self, topic: str, condition: str, message: str,
                 action: str = "log", cooldown_s: float = 300):
        self.topic = topic
        self.condition = condition
        self.message = message
        self.action = action
        self.cooldown_s = cooldown_s
        self._last_fired = 0.0

    def evaluate(self, value) -> bool:
        try:
            return bool(eval(self.condition, {"__builtins__": {}},
                             {"value": value}))
        except Exception:
            return False

    def should_fire(self) -> bool:
        return (time.time() - self._last_fired) >= self.cooldown_s

    def fire(self, value, topic: str):
        self._last_fired = time.time()
        msg = self.message.format(value=value, topic=topic)

        if self.action == "sms":
            self._send_sms(msg)
        log.warning("ALERT: %s", msg)

    @staticmethod
    def _send_sms(message: str):
        """Send SMS via the voipms proxy at https://voip.n0gq.org."""
        sms_script = os.path.expanduser("~/Dropbox/build/money/sms.py")
        if os.path.exists(sms_script):
            try:
                subprocess.run(
                    [sys.executable, sms_script, message],
                    timeout=30, check=False
                )
            except Exception as e:
                log.error("SMS send failed: %s", e)
        else:
            log.warning("SMS script not found at %s, logging only", sms_script)


class AlertDaemon:
    def __init__(self, rules: list[AlertRule], broker: str = DEFAULT_BROKER,
                 port: int = DEFAULT_PORT):
        self.rules = rules
        self.broker = broker
        self.port = port
        self._running = True
        # Group rules by topic for efficient dispatch
        self._topic_rules: dict[str, list[AlertRule]] = {}
        for rule in rules:
            self._topic_rules.setdefault(rule.topic, []).append(rule)

    def _on_message(self, topic: str, data: dict):
        value = data.get("value")
        if value is None:
            return

        # Check exact matches
        rules = self._topic_rules.get(topic, [])
        for rule in rules:
            if rule.evaluate(value) and rule.should_fire():
                rule.fire(value, topic)

    def run(self):
        logging.basicConfig(
            level=logging.INFO,
            format="%(asctime)s %(name)s %(levelname)s %(message)s",
            datefmt="%H:%M:%S"
        )

        client = MQTTClient(
            client_id="alert-daemon",
            broker=self.broker,
            port=self.port
        )
        client.connect()

        deadline = time.time() + 10
        while not client.connected and time.time() < deadline:
            time.sleep(0.1)
        if not client.connected:
            log.error("Failed to connect to MQTT broker")
            return

        # Subscribe to all unique topics from rules
        topics = set(rule.topic for rule in self.rules)
        for topic in topics:
            client.subscribe(topic, self._on_message)
            log.info("Watching: %s", topic)

        def _stop(sig, frame):
            self._running = False

        signal.signal(signal.SIGINT, _stop)
        signal.signal(signal.SIGTERM, _stop)

        log.info("Alert daemon running with %d rules, Ctrl+C to stop",
                 len(self.rules))

        while self._running:
            time.sleep(1.0)

        client.disconnect()
        log.info("Alert daemon stopped")


def main():
    parser = argparse.ArgumentParser(description="MQTT alert daemon")
    parser.add_argument("--config", required=True,
                        help="YAML config file with alert rules")
    parser.add_argument("--broker", default=DEFAULT_BROKER)
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    args = parser.parse_args()

    config = load_config(args.config)
    rules = []
    for r in config.get("rules", []):
        rules.append(AlertRule(
            topic=r["topic"],
            condition=r["condition"],
            message=r["message"],
            action=r.get("action", "log"),
            cooldown_s=r.get("cooldown_s", 300),
        ))

    daemon = AlertDaemon(rules, broker=args.broker, port=args.port)
    daemon.run()


if __name__ == "__main__":
    main()
