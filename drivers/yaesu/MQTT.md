# MQTT Map — Yaesu FT-891

**Prefix:** `bench/ft891`

## Published topics

| Topic | Type | Unit | Description |
|-------|------|------|-------------|
| `bench/ft891/frequency_hz` | float | Hz | VFO frequency |
| `bench/ft891/mode` | string | — | Operating mode (USB, LSB, CW, AM, FM, etc.) |
| `bench/ft891/passband_hz` | int | Hz | Filter passband width |
| `bench/ft891/s_meter_dbm` | float | dBm | S-meter reading |

## Command topics

| Topic | Type | Description |
|-------|------|-------------|
| `bench/ft891/frequency_hz/set` | float | Set VFO frequency |
| `bench/ft891/mode/set` | string | Set operating mode |
| `bench/ft891/agc/set` | string | Set AGC mode |

**Poll interval:** 500 ms
**Bridge script:** `drivers/mqtt/bridges/bridge_ft891.py`
