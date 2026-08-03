# MQTT Map — XL9535 I2C Relay Board

**Prefix:** `bench/xl9535`

**Status:** Hardware ordered — not yet tested.

## Published topics

| Topic | Type | Unit | Description |
|-------|------|------|-------------|
| `bench/xl9535/ch1` | bool | — | Relay 1 state |
| `bench/xl9535/ch2` | bool | — | Relay 2 state |
| ... | | | Up to 16 channels depending on board |
| `bench/xl9535/ch16` | bool | — | Relay 16 state |

## Command topics

| Topic | Type | Description |
|-------|------|-------------|
| `bench/xl9535/ch1/set` | bool | Energize/release relay 1 |
| ... | | Up to ch16 |
| `bench/xl9535/all_off/set` | any | Release all relays |

**Poll interval:** 500 ms
**Connection:** I2C via Bus Pirate (address 0x20-0x27)
**Bridge script:** `drivers/mqtt/bridges/bridge_xl9535.py`
