#!/usr/bin/env python3
"""MQTT bridge for solsdr (ExpertSDR3-free SunSDR2 PRO).

Publishes frequency, mode, streaming state, and S-meter (dBFS) read from a
running solsdr appliance's control API, and accepts frequency/mode/gain/RIT/AGC
commands over /set topics.

This bridges the `rf_bench.solsdr` NETWORK driver — solsdr is a separate
appliance process that owns the radio; this daemon is just one of its clients.
solsdr must be running with --control-api (default port 5556). Point --host at
the machine running solsdr.

Distinct from bridge_sunsdr.py, which bridges the ExpertSDR3/TCI path. Run only
ONE of the two against a given radio.

    python3 bridge_solsdr.py --host 10.1.2.50           # solsdr on that host
    python3 bridge_solsdr.py --host 10.1.2.50 --broker 10.1.0.20

Topics (prefix /bench/solsdr):
    $online $model $connection $driver $host   (meta / LWT)
    online              bool   — control API reachable
    frequency_hz        int    — tuned freq (driver shadow / solsdr status)
    mode                str    — USB/LSB/AM/FM/CW
    streaming           int    — 1 while the RX IQ pipeline is running
    s_meter_dbfs        float  — RX signal level (dBFS, NOT dBm)
    ptt                 bool   — solsdr status ptt flag

Commands (publish JSON {"value": ...} to prefix/<sub>/set):
    frequency_hz/set    int Hz
    mode/set            USB|LSB|AM|FM|CW
    rf_gain/set         dB (mapped to nearest preamp/att step)
    preamp/set          -20|-10|0|+10|off|preamp
    rit/set             Hz (0 = off)
    agc/set             auto|on|off|fixed:<g>
    squelch/set         0-1
    nr/set              0-1
"""

import argparse
import sys

sys.path.insert(0, "/home/jfrancis/Dropbox/build/rf-bench/drivers/mqtt")
sys.path.insert(0, "/home/jfrancis/Dropbox/build/rf-bench/drivers/solsdr")

from rf_bench.mqtt import Bridge, BridgeConfig, DEFAULT_BROKER, DEFAULT_PORT
from rf_bench.solsdr import SolSDR, SolSDRError


class SolSDRBridge(Bridge):
    prefix = "/bench/solsdr"
    poll_interval = 1.0

    # Set by main() before run().
    host = "127.0.0.1"
    control_port = 5556

    def setup(self):
        self.sdr = SolSDR(self.host, control_port=self.control_port)
        self.meta(model="SunSDR2 PRO (solsdr)",
                  connection=f"solsdr control API {self.host}:{self.control_port}",
                  driver="rf_bench.solsdr.SolSDR",
                  host=self.host)

    def poll(self):
        try:
            st = self.sdr.status()
        except SolSDRError:
            # solsdr not reachable right now — report offline, try again next tick
            self.publish("online", False)
            return

        self.publish("online", True)
        self.publish("streaming", st["streaming"])
        self.publish("ptt", st["ptt"])
        if st["freq"] is not None:
            self.publish("frequency_hz", st["freq"])
        if st["mode"] is not None:
            self.publish("mode", st["mode"])
        # Prefer the dedicated smeter command (always fresh); fall back to status.
        try:
            self.publish("s_meter_dbfs", self.sdr.get_strength())
        except SolSDRError:
            if st["smeter"] is not None:
                self.publish("s_meter_dbfs", st["smeter"])

    def on_command(self, subtopic, payload):
        value = payload.get("value") if isinstance(payload, dict) else payload
        if value is None:
            return
        try:
            if subtopic == "frequency_hz/set":
                self.sdr.set_frequency(int(float(value)))
            elif subtopic == "mode/set":
                self.sdr.set_mode(str(value))
            elif subtopic == "rf_gain/set":
                self.sdr.set_rf_gain(float(value))
            elif subtopic == "preamp/set":
                self.sdr.set_preamp(str(value))
            elif subtopic == "rit/set":
                self.sdr.set_rit(float(value))
            elif subtopic == "agc/set":
                self.sdr.set_agc(str(value))
            elif subtopic == "squelch/set":
                self.sdr.set_squelch(float(value))
            elif subtopic == "nr/set":
                self.sdr.set_nr(float(value))
        except SolSDRError as e:
            # Don't let a bad command kill the bridge; log via base-class logger.
            import logging
            logging.getLogger(__name__).warning("command %s failed: %s",
                                                 subtopic, e)

    def cleanup(self):
        try:
            self.sdr.close()
        except Exception:
            pass


def main():
    parser = argparse.ArgumentParser(
        description="MQTT bridge for solsdr (ExpertSDR3-free SunSDR2 PRO)")
    parser.add_argument("--host", default="127.0.0.1",
                        help="host running solsdr (default 127.0.0.1)")
    parser.add_argument("--control-port", type=int, default=5556,
                        help="solsdr control API port (default 5556)")
    parser.add_argument("--broker", default=DEFAULT_BROKER,
                        help=f"MQTT broker (default {DEFAULT_BROKER})")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT,
                        help=f"MQTT broker port (default {DEFAULT_PORT})")
    parser.add_argument("--interval", type=float, default=SolSDRBridge.poll_interval,
                        help=f"poll interval s (default {SolSDRBridge.poll_interval})")
    parser.add_argument("--log-level", default="INFO",
                        choices=["DEBUG", "INFO", "WARNING", "ERROR"])
    args = parser.parse_args()

    SolSDRBridge.host = args.host
    SolSDRBridge.control_port = args.control_port
    bridge = SolSDRBridge(BridgeConfig(
        broker=args.broker, port=args.port,
        poll_interval=args.interval, log_level=args.log_level))
    bridge.run()


if __name__ == "__main__":
    main()
