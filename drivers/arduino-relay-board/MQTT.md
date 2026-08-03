# MQTT Map — Arduino+W5100 4-Channel Network Relay Board

**Prefix:** `bench/relay`

## Published topics

| Topic | Type | Unit | Description |
|-------|------|------|-------------|
| `bench/relay/ch1` | bool | — | Relay 1 state (true=energized) |
| `bench/relay/ch2` | bool | — | Relay 2 state |
| `bench/relay/ch3` | bool | — | Relay 3 state |
| `bench/relay/ch4` | bool | — | Relay 4 state |

## Command topics

| Topic | Type | Description |
|-------|------|-------------|
| `bench/relay/ch1/set` | bool | Energize/release relay 1 |
| `bench/relay/ch2/set` | bool | Energize/release relay 2 |
| `bench/relay/ch3/set` | bool | Energize/release relay 3 |
| `bench/relay/ch4/set` | bool | Energize/release relay 4 |
| `bench/relay/all_off/set` | any | Release all relays |

**Poll interval:** 500 ms
**Connection:** Ethernet TCP port 5025 at 10.1.1.36
**Bridge script:** `drivers/mqtt/bridges/bridge_relay.py`
