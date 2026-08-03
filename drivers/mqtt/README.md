# rf_bench.mqtt — MQTT Bridge Infrastructure

Publish/subscribe bus for the entire rf-bench instrument ecosystem. Every
instrument gets a thin bridge daemon that publishes measurements and
subscribes to commands, using JSON-encoded messages and a consistent
topic schema.

## Architecture

```
┌─────────────┐     ┌──────────────┐     ┌───────────────────────┐
│  Instrument │◄───►│ Bridge Daemon │────►│  Internal Broker      │
│  (SCPI/BLE) │     │ (poll/push)   │     │  10.1.0.20:1883       │
└─────────────┘     └──────────────┘     │  (no auth, LAN only)  │
                                          └──────────┬────────────┘
                                                     │ Mosquitto bridge
                                                     │ (WireGuard, topic # both 0)
                                          ┌──────────▼────────────┐
                                          │  Public Broker         │
                                          │  us.n0gq.org:1883      │
                                          │  (password auth)       │
                                          └──────────┬────────────┘
                                                     │
                    ┌────────────────────────────────┼──────────┐
                    │                                │          │
              ┌─────▼─────┐  ┌────────▼──────┐  ┌──▼────────┐
              │ Time-series│  │  Alert Daemon  │  │ Phone/    │
              │   Logger   │  │  (threshold→   │  │ Dashboard │
              │  (SQLite)  │  │   SMS/log)     │  │ (IoT MQTT │
              └────────────┘  └───────────────┘  │  Panel)   │
                                                  └──────────┘
```

Internal clients (bridges, subscribers, automation scripts) connect directly
to `10.1.0.20:1883` (no auth). External clients (phone, remote monitoring)
connect to `us.n0gq.org:1883` with username/password. The Mosquitto bridge
syncs all messages bidirectionally — publish on either side, see it on both.

**DNS:** `mqtt.n0gq.org` is a CNAME for `us.n0gq.org`. On internal networks
with split DNS it may resolve to `10.1.0.20` directly.

**Credentials:** Add users with `mosquitto_passwd /etc/mosquitto/passwd <user>`
on `us.n0gq.org`. See `~/skynet/mqtt-credentials.md`.

## Quick Start

```bash
# Install the mqtt package
cd drivers/mqtt
pip install -e . --break-system-packages

# Run a bridge (example: power supply)
python bridges/bridge_psu.py

# Run the time-series logger
python subscribers/timeseries_logger.py

# Run the alert daemon
python subscribers/alert_daemon.py --config subscribers/alerts_example.yaml
```

## Message Format

All messages are JSON with a standard envelope:

```json
{"value": 13.82, "ts": 1719792000.123}
```

- `value` — the measurement (float, int, bool, string, or object)
- `ts` — Unix timestamp from the publishing host

## Topic Schema

```
bench/<instrument>/<channel>/<measurement>     (read)
bench/<instrument>/<channel>/<measurement>/set (write)
bench/<instrument>/$online                      (LWT: true/false)
bench/<instrument>/$model                       (metadata)
bench/<instrument>/$driver                      (metadata)
```

## Bridges

| Bridge | Instrument | Poll | Status |
|--------|-----------|------|--------|
| bridge_psu.py | SPD3303X-E | 1s | Ready |
| bridge_dmm.py | SDM3045X | 1s | Ready |
| bridge_sdg.py | SDG1062X | 2s | Ready |
| bridge_ssa.py | SSA3032X Plus | 2s | Ready |
| bridge_scope.py | SDS2504X Plus | 2s | Ready |
| bridge_load.py | ET5406A+ | 2s | Ready |
| bridge_ic7300.py | IC-7300 | 500ms | Ready |
| bridge_ic9700.py | IC-9700 | 500ms | Ready |
| bridge_ft891.py | FT-891 | 500ms | Ready |
| bridge_kestrel.py | Kestrel 5500L | ~4s (BLE push) | Ready |
| bridge_mhs5225.py | MHS-5225A | 2s | Ready |
| bridge_gps.py | gpsd | 1s | Ready |
| bridge_rtlsdr.py | RTL-SDR | 1s | Ready |
| bridge_nanovna.py | NanoVNA-F | 5s | Ready |
| bridge_relay.py | Arduino relay | 500ms | Ready |
| bridge_shuttlexpress.py | ShuttleXpress | Event | Ready |
| bridge_hp8712b.py | HP 8712B | 5s | HW pending |
| bridge_solartron.py | Solartron 7151 | 1s | HW pending |
| bridge_xl9535.py | XL9535 relay | 500ms | HW pending |
| bridge_buspirate.py | Bus Pirate | 5s | Ready |
| bridge_flipper.py | Flipper Zero | 2s | Ready |
| bridge_kiwisdr.py | KiwiSDR | 2s | Ready |
| bridge_sunsdr.py | SunSDR2 Pro | 1s | Ready |

## Subscribers

| Script | Description |
|--------|-------------|
| timeseries_logger.py | Logs all `bench/#` messages to SQLite |
| alert_daemon.py | Threshold rules (YAML) → SMS/log alerts |

## MQTT Map Documents

Each driver directory contains an `MQTT.md` file describing available
topics, types, and commands. See:

- `drivers/siglent/MQTT.md` — SPD3303X, SDM3045X, SDG1062X, SSA3032X, SDS2504X
- `drivers/icom/MQTT.md` — IC-7300, IC-9700
- `drivers/yaesu/MQTT.md` — FT-891
- `drivers/yertai/MQTT.md` — ET5406A+
- `drivers/kestrel/MQTT.md` — Kestrel 5500L
- `drivers/koolertron/MQTT.md` — MHS-5225A
- `drivers/gpsd/MQTT.md` — GPS
- `drivers/rtlsdr/MQTT.md` — RTL-SDR
- `drivers/nanovna/MQTT.md` — NanoVNA-F
- `drivers/shuttlexpress/MQTT.md` — ShuttleXpress
- `drivers/arduino-relay-board/MQTT.md` — Arduino relay
- `drivers/hp/MQTT.md` — HP 8712B
- `drivers/solartron/MQTT.md` — Solartron 7151
- `drivers/relay/MQTT.md` — XL9535
- `drivers/buspirate/MQTT.md` — Bus Pirate
- `drivers/flipper/MQTT.md` — Flipper Zero
- `drivers/kiwisdr/MQTT.md` — KiwiSDR
- `drivers/sunsdr/MQTT.md` — SunSDR2 Pro

## Dependencies

- `paho-mqtt>=2.0` (installed: `pip install paho-mqtt`)
- `pyyaml` (for alert daemon config only)

## Design Decisions

1. **JSON everywhere** — all payloads are JSON objects, even for scalar values.
   This allows consistent parsing and the `ts` field enables time alignment
   across instruments without relying on broker timestamps.

2. **Retained messages by default** — new subscribers immediately see the last
   known state of every instrument without waiting for the next poll cycle.

3. **LWT (Last Will and Testament)** — each bridge sets `$online` to false via
   LWT so consumers know immediately when a bridge dies.

4. **No raw bulk data on MQTT** — traces (801 points), waveforms, and IQ streams
   stay on direct SCPI/driver connections. MQTT carries derived values (peaks,
   markers, scalars) that are useful for dashboards and automation.

5. **Bridges are independent daemons** — each bridge runs standalone. You can
   run just the instruments you have connected. No central coordinator needed.

6. **sys.path inserts for development** — bridges use sys.path.insert() to find
   the mqtt base package and their respective driver packages during development.
   In production (pip-installed), these are unnecessary.
