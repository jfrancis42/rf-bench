# MQTT Map — Icom Radios

## IC-7300

**Prefix:** `bench/ic7300`

### Published topics

| Topic | Type | Unit | Description |
|-------|------|------|-------------|
| `bench/ic7300/frequency_hz` | float | Hz | VFO frequency |
| `bench/ic7300/mode` | string | — | Operating mode (USB, LSB, CW, AM, FM, etc.) |
| `bench/ic7300/passband_hz` | int | Hz | Filter passband width |
| `bench/ic7300/s_meter_dbm` | float | dBm | S-meter reading |

### Command topics

| Topic | Type | Description |
|-------|------|-------------|
| `bench/ic7300/frequency_hz/set` | float | Set VFO frequency |
| `bench/ic7300/mode/set` | string | Set operating mode |
| `bench/ic7300/agc/set` | string | Set AGC mode (off, slow, mid, fast) |

**Poll interval:** 500 ms
**Bridge script:** `drivers/mqtt/bridges/bridge_ic7300.py`

---

## IC-9700

**Prefix:** `bench/ic9700`

### Published topics

| Topic | Type | Unit | Description |
|-------|------|------|-------------|
| `bench/ic9700/frequency_hz` | float | Hz | VFO frequency |
| `bench/ic9700/mode` | string | — | Operating mode |
| `bench/ic9700/passband_hz` | int | Hz | Filter passband width |
| `bench/ic9700/s_meter_dbm` | float | dBm | S-meter reading |
| `bench/ic9700/vfo` | string | — | Active VFO (VFOA, VFOB) |
| `bench/ic9700/split` | bool | — | Split operation active |
| `bench/ic9700/ptt` | bool | — | Transmitting |

### Command topics

| Topic | Type | Description |
|-------|------|-------------|
| `bench/ic9700/frequency_hz/set` | float | Set VFO frequency |
| `bench/ic9700/mode/set` | string | Set operating mode |
| `bench/ic9700/vfo/set` | string | Set active VFO |
| `bench/ic9700/ptt/set` | bool | Key/unkey transmitter |
| `bench/ic9700/agc/set` | string | Set AGC mode |

**Poll interval:** 500 ms
**Bridge script:** `drivers/mqtt/bridges/bridge_ic9700.py`
