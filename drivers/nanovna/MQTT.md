# MQTT Map — NanoVNA-F Vector Network Analyzer

**Prefix:** `bench/nanovna`

## Published topics

| Topic | Type | Unit | Description |
|-------|------|------|-------------|
| `bench/nanovna/start_hz` | float | Hz | Sweep start frequency |
| `bench/nanovna/stop_hz` | float | Hz | Sweep stop frequency |
| `bench/nanovna/points` | int | — | Number of sweep points |
| `bench/nanovna/s11/min_db` | float | dB | Best return loss in sweep |
| `bench/nanovna/s11/min_freq_hz` | float | Hz | Frequency of best match |
| `bench/nanovna/vswr_min` | float | :1 | VSWR at best match point |
| `bench/nanovna/s21/center_db` | float | dB | S21 at center frequency |
| `bench/nanovna/s21/center_freq_hz` | float | Hz | Center frequency |

## Command topics

| Topic | Type | Description |
|-------|------|-------------|
| `bench/nanovna/sweep/set` | object | Set sweep: `{"start": Hz, "stop": Hz, "points": N}` |

**Note:** Full S-parameter arrays are NOT published via MQTT. Use the driver directly for complete sweep data.

**Poll interval:** 5 s (on-demand sweep, not continuous)
**Connection:** USB serial (/dev/ttyACM1)
**Bridge script:** `drivers/mqtt/bridges/bridge_nanovna.py`
