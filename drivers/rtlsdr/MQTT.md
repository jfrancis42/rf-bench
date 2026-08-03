# MQTT Map — RTL-SDR Blog v4

**Prefix:** `bench/rtlsdr`

## Published topics

| Topic | Type | Unit | Description |
|-------|------|------|-------------|
| `bench/rtlsdr/center_freq_hz` | int | Hz | Current center frequency |
| `bench/rtlsdr/sample_rate_hz` | int | Hz | Sample rate |
| `bench/rtlsdr/gain_db` | float | dB | RF gain setting |
| `bench/rtlsdr/peak/freq_hz` | float | Hz | Peak frequency in current spectrum |
| `bench/rtlsdr/peak/power_dbfs` | float | dBFS | Peak power level |

## Command topics

| Topic | Type | Description |
|-------|------|-------------|
| `bench/rtlsdr/center_freq_hz/set` | int | Set center frequency |
| `bench/rtlsdr/sample_rate_hz/set` | int | Set sample rate |
| `bench/rtlsdr/gain_db/set` | float | Set RF gain |
| `bench/rtlsdr/bias_tee/set` | bool | Enable/disable bias tee |

**Note:** Raw IQ data is NOT published via MQTT. Use the driver directly for IQ capture.

**Poll interval:** 1 s
**Bridge script:** `drivers/mqtt/bridges/bridge_rtlsdr.py`
