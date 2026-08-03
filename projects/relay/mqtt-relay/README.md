# mqtt-relay — MQTT-controlled relay switching

Subscribes to MQTT topics and controls relays on the Arduino relay board
(10.1.1.36). Two control modes: simple on/off switches, and momentary
buttons with pulse and hold-with-timeout behavior.

## Topic Mapping

| Topic | Relay | Behavior |
|-------|-------|----------|
| `/test/switch/one` | 1 | On/off toggle — stays in last commanded state |
| `/test/switch/two` | 2 | On/off toggle — stays in last commanded state |
| `/test/button/one` | 3 | 1-second pulse on press; re-arms on release |
| `/test/button/two` | 4 | On while held; auto-off after 30 seconds if no release seen |

## Payloads

All topics accept `0`/`1`, `on`/`off`, `true`/`false` as bare values or
inside the JSON envelope (`{"value": 1, "ts": ...}`).

**Switches** (`/test/switch/*`): `1` turns relay on, `0` turns it off.

**Button one** (`/test/button/one`): `1` = pressed (fires a 1s pulse),
`0` = released (re-arms for next pulse). Pressing again before release
is ignored — one pulse per press/release cycle.

**Button two** (`/test/button/two`): `1` = pressed (relay on, starts 30s
timer), `0` = released (relay off immediately). If no `0` is received
within 30 seconds, relay turns off automatically (safety timeout).

## Usage

```bash
python mqtt_relay.py
python mqtt_relay.py --relay-host 10.1.1.36 --broker 10.1.0.20
```

## Testing

```bash
# Switch relay 1 on/off
mosquitto_pub -h 10.1.0.20 -t /test/switch/one -m 1
mosquitto_pub -h 10.1.0.20 -t /test/switch/one -m 0

# Pulse relay 3 (simulate press then release)
mosquitto_pub -h 10.1.0.20 -t /test/button/one -m 1
mosquitto_pub -h 10.1.0.20 -t /test/button/one -m 0

# Hold relay 4 (will auto-off after 30s if you don't release)
mosquitto_pub -h 10.1.0.20 -t /test/button/one -m 1
sleep 5
mosquitto_pub -h 10.1.0.20 -t /test/button/two -m 0
```

Or from IoT MQTT Panel on `us.n0gq.org` (with auth) — the bridge syncs
messages to the internal broker where mqtt-relay is listening.

## Hardware

- Arduino Uno + Vilros Ethernet R3 (W5100) + 4-channel relay module
- IP: 10.1.1.36, TCP port 5025
- MQTT broker: 10.1.0.20:1883 (internal, no auth)

## Dependencies

- `rf_bench.mqtt` (drivers/mqtt)
- `rf_bench.arduino_relay_board` (drivers/arduino-relay-board)
