# MQTT Map — Bus Pirate

**Prefix:** `bench/buspirate`

## Published topics

| Topic | Type | Unit | Description |
|-------|------|------|-------------|
| `bench/buspirate/connected` | bool | — | Bus Pirate is responsive |

## Command topics

| Topic | Type | Description |
|-------|------|-------------|
| `bench/buspirate/i2c_scan/set` | any | Trigger I2C bus scan; results published to `bench/buspirate/i2c_devices` |

## Notes

The Bus Pirate is primarily a protocol bridge tool. Its MQTT presence is
minimal — mainly online/offline status and on-demand I2C scans. Direct
instrument access (SPI/I2C/UART read/write) is better done through the
driver API directly rather than MQTT for latency-sensitive operations.

**Poll interval:** 5 s
**Connection:** USB serial (/dev/ttyUSB* or /dev/ttyACM1 for v5)
**Bridge script:** `drivers/mqtt/bridges/bridge_buspirate.py`
