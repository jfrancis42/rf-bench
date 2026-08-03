# MQTT Map — SunSDR2 Pro (TCI)

**Prefix:** `bench/sunsdr`

## Published topics

| Topic | Type | Unit | Description |
|-------|------|------|-------------|
| `bench/sunsdr/connected` | bool | — | TCI WebSocket connection active |
| `bench/sunsdr/frequency_hz` | float | Hz | Current VFO frequency |
| `bench/sunsdr/mode` | string | — | Operating mode |
| `bench/sunsdr/sample_rate_hz` | int | Hz | IQ sample rate |
| `bench/sunsdr/s_meter_dbm` | float | dBm | S-meter reading |

## Command topics

| Topic | Type | Description |
|-------|------|-------------|
| `bench/sunsdr/frequency_hz/set` | float | Set VFO frequency |
| `bench/sunsdr/mode/set` | string | Set operating mode |

**Note:** IQ audio streams are NOT published via MQTT. Use the driver directly for IQ/audio capture.

**Poll interval:** 1 s
**Connection:** TCI WebSocket to ExpertSDR3:50001
**Bridge script:** `drivers/mqtt/bridges/bridge_sunsdr.py`
