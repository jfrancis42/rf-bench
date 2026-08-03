#!/usr/bin/env python3
"""MQTT time-series logger — subscribes to /bench/# and logs all
measurements to a SQLite database for post-hoc correlation analysis.

Each row stores: timestamp, topic, value (JSON), and the original
message's ts field for instrument-side timing.

Usage:
    python timeseries_logger.py
    python timeseries_logger.py --db /path/to/bench.db
    python timeseries_logger.py --topics "/bench/psu/#" "/bench/kestrel/#"
"""

import argparse
import json
import logging
import os
import signal
import sqlite3
import sys
import time

sys.path.insert(0, "/home/jfrancis/Dropbox/build/rf-bench/drivers/mqtt")

from rf_bench.mqtt import MQTTClient, DEFAULT_BROKER, DEFAULT_PORT

log = logging.getLogger(__name__)

DEFAULT_DB = os.path.expanduser("~/rf-bench-timeseries.db")
DEFAULT_TOPICS = ["/bench/#"]


class TimeseriesLogger:
    def __init__(self, db_path: str, topics: list[str],
                 broker: str = DEFAULT_BROKER, port: int = DEFAULT_PORT):
        self.db_path = db_path
        self.topics = topics
        self.broker = broker
        self.port = port
        self._running = True
        self._conn = None
        self._batch = []
        self._batch_size = 50
        self._last_flush = time.time()
        self._flush_interval = 5.0

    def _init_db(self):
        self._conn = sqlite3.connect(self.db_path)
        self._conn.execute("""
            CREATE TABLE IF NOT EXISTS measurements (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                received_at REAL NOT NULL,
                instrument_ts REAL,
                topic TEXT NOT NULL,
                value TEXT NOT NULL
            )
        """)
        self._conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_measurements_topic
            ON measurements(topic)
        """)
        self._conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_measurements_time
            ON measurements(received_at)
        """)
        self._conn.commit()

    def _on_message(self, topic: str, data: dict):
        # Skip metadata topics
        if "/$" in topic:
            return

        row = (
            time.time(),
            data.get("ts"),
            topic,
            json.dumps(data.get("value")),
        )
        self._batch.append(row)

        if (len(self._batch) >= self._batch_size or
                time.time() - self._last_flush > self._flush_interval):
            self._flush()

    def _flush(self):
        if not self._batch:
            return
        self._conn.executemany(
            "INSERT INTO measurements (received_at, instrument_ts, topic, value) "
            "VALUES (?, ?, ?, ?)",
            self._batch
        )
        self._conn.commit()
        count = len(self._batch)
        self._batch.clear()
        self._last_flush = time.time()
        log.debug("Flushed %d rows", count)

    def run(self):
        logging.basicConfig(
            level=logging.INFO,
            format="%(asctime)s %(name)s %(levelname)s %(message)s",
            datefmt="%H:%M:%S"
        )

        self._init_db()
        log.info("Logging to %s", self.db_path)

        client = MQTTClient(
            client_id="timeseries-logger",
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

        for topic in self.topics:
            client.subscribe(topic, self._on_message)
            log.info("Subscribed to %s", topic)

        def _stop(sig, frame):
            self._running = False

        signal.signal(signal.SIGINT, _stop)
        signal.signal(signal.SIGTERM, _stop)

        log.info("Logger running, Ctrl+C to stop")

        while self._running:
            time.sleep(1.0)
            if time.time() - self._last_flush > self._flush_interval:
                self._flush()

        # Final flush
        self._flush()
        client.disconnect()
        self._conn.close()
        log.info("Logger stopped")


def main():
    parser = argparse.ArgumentParser(description="MQTT time-series logger")
    parser.add_argument("--db", default=DEFAULT_DB,
                        help=f"SQLite database path (default: {DEFAULT_DB})")
    parser.add_argument("--topics", nargs="+", default=DEFAULT_TOPICS,
                        help="MQTT topics to subscribe to (default: /bench/#)")
    parser.add_argument("--broker", default=DEFAULT_BROKER)
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    args = parser.parse_args()

    logger = TimeseriesLogger(
        db_path=args.db,
        topics=args.topics,
        broker=args.broker,
        port=args.port,
    )
    logger.run()


if __name__ == "__main__":
    main()
