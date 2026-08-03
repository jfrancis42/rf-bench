# MQTT Map — Koolertron MHS-5225A DDS Generator + Counter

**Prefix:** `bench/mhs5225`

## Published topics

| Topic | Type | Unit | Description |
|-------|------|------|-------------|
| `bench/mhs5225/ch1/frequency_hz` | float | Hz | Channel 1 output frequency |
| `bench/mhs5225/ch1/amplitude_vpp` | float | Vpp | Channel 1 amplitude |
| `bench/mhs5225/ch1/waveform` | int | — | Waveform code (0=sine, 1=square, etc.) |
| `bench/mhs5225/ch1/duty_cycle` | float | % | Duty cycle |
| `bench/mhs5225/ch1/phase_deg` | int | ° | Phase offset |
| `bench/mhs5225/ch2/...` | | | Same as CH1 |
| `bench/mhs5225/counter/freq_hz` | float | Hz | Frequency counter reading |

## Command topics

| Topic | Type | Description |
|-------|------|-------------|
| `bench/mhs5225/ch1/frequency_hz/set` | float | Set CH1 frequency |
| `bench/mhs5225/ch2/frequency_hz/set` | float | Set CH2 frequency |
| `bench/mhs5225/ch1/amplitude_vpp/set` | float | Set CH1 amplitude |
| `bench/mhs5225/ch2/amplitude_vpp/set` | float | Set CH2 amplitude |
| `bench/mhs5225/output/set` | bool | Enable/disable all outputs |

**Poll interval:** 2 s
**Connection:** USB serial (57600 baud)
**Bridge script:** `drivers/mqtt/bridges/bridge_mhs5225.py`
