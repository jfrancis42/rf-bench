# MQTT Map — Flipper Zero

**Prefix:** `bench/flipper`

## Published topics

| Topic | Type | Unit | Description |
|-------|------|------|-------------|
| `bench/flipper/connected` | bool | — | Flipper is responsive |
| `bench/flipper/firmware` | string | — | Firmware version |
| `bench/flipper/hardware` | string | — | Hardware revision |

## Command topics

| Topic | Type | Description |
|-------|------|-------------|
| `bench/flipper/subghz/tx/set` | object | Transmit Sub-GHz: `{"frequency": Hz, "protocol": str, "data": str}` |

## Notes

The Flipper Zero has many capabilities (Sub-GHz, IR, RFID, NFC, GPIO)
but most are interactive/one-shot operations better suited to direct
driver control. The MQTT bridge primarily provides presence detection
and basic Sub-GHz transmit capability for automation scenarios.

**Poll interval:** 2 s
**Connection:** USB serial (/dev/ttyACM0)
**Bridge script:** `drivers/mqtt/bridges/bridge_flipper.py`
