# MQTT Map — KiwiSDR HF Receiver

**Prefix:** `bench/kiwisdr`

## Published topics

| Topic | Type | Unit | Description |
|-------|------|------|-------------|
| `bench/kiwisdr/connected` | bool | — | WebSocket connection active |
| `bench/kiwisdr/frequency_hz` | float | Hz | Current tuned frequency |
| `bench/kiwisdr/mode` | string | — | Demodulation mode (AM, USB, LSB, CW, etc.) |
| `bench/kiwisdr/s_meter_dbm` | float | dBm | S-meter reading |

## Command topics

| Topic | Type | Description |
|-------|------|-------------|
| `bench/kiwisdr/frequency_hz/set` | float | Set tuned frequency |
| `bench/kiwisdr/mode/set` | string | Set demodulation mode |

**Note:** Audio/IQ streams are NOT published via MQTT. Use the driver directly for audio/IQ capture.

**Poll interval:** 2 s
**Connection:** WebSocket to KiwiSDR host:8073
**Bridge script:** `drivers/mqtt/bridges/bridge_kiwisdr.py`
