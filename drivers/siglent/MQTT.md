# MQTT Map — Siglent Instruments

## SPD3303X-E Power Supply

**Prefix:** `bench/psu`

### Published topics (read)

| Topic | Type | Unit | Description |
|-------|------|------|-------------|
| `bench/psu/ch1/voltage_v` | float | V | Measured output voltage |
| `bench/psu/ch1/current_a` | float | A | Measured output current |
| `bench/psu/ch1/power_w` | float | W | Measured output power |
| `bench/psu/ch1/output` | bool | — | Output enabled |
| `bench/psu/ch1/mode` | string | — | "CV" or "CC" |
| `bench/psu/ch1/voltage_setpoint_v` | float | V | Programmed voltage |
| `bench/psu/ch1/current_setpoint_a` | float | A | Programmed current limit |
| `bench/psu/ch2/...` | | | Same as CH1 |
| `bench/psu/ch3/voltage_v` | float | V | Fixed channel measured voltage |
| `bench/psu/ch3/current_a` | float | A | Fixed channel measured current |
| `bench/psu/ch3/power_w` | float | W | Fixed channel measured power |
| `bench/psu/ch3/output` | bool | — | Fixed channel output enabled |
| `bench/psu/tracking` | string | — | "INDEP", "SER", or "PARA" |

### Command topics (write)

| Topic | Type | Description |
|-------|------|-------------|
| `bench/psu/ch1/voltage_v/set` | float | Set CH1 voltage |
| `bench/psu/ch2/voltage_v/set` | float | Set CH2 voltage |
| `bench/psu/ch1/current_a/set` | float | Set CH1 current limit |
| `bench/psu/ch2/current_a/set` | float | Set CH2 current limit |
| `bench/psu/ch1/output/set` | bool | Enable/disable CH1 |
| `bench/psu/ch2/output/set` | bool | Enable/disable CH2 |
| `bench/psu/ch3/output/set` | bool | Enable/disable CH3 |
| `bench/psu/tracking/set` | string | Set tracking mode |

**Poll interval:** 1 s
**Bridge script:** `drivers/mqtt/bridges/bridge_psu.py`

---

## SDM3045X Multimeter

**Prefix:** `bench/dmm`

### Published topics

| Topic | Type | Unit | Description |
|-------|------|------|-------------|
| `bench/dmm/function` | string | — | Current measurement function (VOLT:DC, CURR:AC, RES, etc.) |
| `bench/dmm/value` | float | varies | Current measurement value |
| `bench/dmm/unit` | string | — | SI unit for current function |

### Command topics

| Topic | Type | Description |
|-------|------|-------------|
| `bench/dmm/function/set` | string | Switch function (VDC, VAC, IDC, IAC, RES, FRES, FREQ, PER, CONT, DIODE) |

**Poll interval:** 1 s
**Bridge script:** `drivers/mqtt/bridges/bridge_dmm.py`

---

## SDG1062X Function Generator

**Prefix:** `bench/sdg`

### Published topics

| Topic | Type | Unit | Description |
|-------|------|------|-------------|
| `bench/sdg/ch1/frequency_hz` | float | Hz | Channel 1 frequency |
| `bench/sdg/ch1/amplitude_dbm` | float | dBm | Channel 1 amplitude |
| `bench/sdg/ch1/amplitude_vpp` | float | Vpp | Channel 1 amplitude |
| `bench/sdg/ch1/phase_deg` | float | ° | Channel 1 phase |
| `bench/sdg/ch1/waveform` | string | — | Waveform type (SINE, SQUARE, RAMP) |
| `bench/sdg/ch1/output` | bool | — | Output state |
| `bench/sdg/ch2/...` | | | Same as CH1 |

### Command topics

| Topic | Type | Description |
|-------|------|-------------|
| `bench/sdg/ch1/frequency_hz/set` | float | Set CH1 frequency |
| `bench/sdg/ch2/frequency_hz/set` | float | Set CH2 frequency |
| `bench/sdg/ch1/amplitude_dbm/set` | float | Set CH1 level |
| `bench/sdg/ch2/amplitude_dbm/set` | float | Set CH2 level |
| `bench/sdg/ch1/output/set` | bool | Enable/disable CH1 |
| `bench/sdg/ch2/output/set` | bool | Enable/disable CH2 |

**Poll interval:** 2 s
**Bridge script:** `drivers/mqtt/bridges/bridge_sdg.py`

---

## SSA3032X Plus Spectrum Analyzer

**Prefix:** `bench/ssa`

### Published topics

| Topic | Type | Unit | Description |
|-------|------|------|-------------|
| `bench/ssa/start_hz` | float | Hz | Sweep start frequency |
| `bench/ssa/stop_hz` | float | Hz | Sweep stop frequency |
| `bench/ssa/center_hz` | float | Hz | Center frequency |
| `bench/ssa/span_hz` | float | Hz | Frequency span |
| `bench/ssa/ref_level_dbm` | float | dBm | Reference level |
| `bench/ssa/rbw_hz` | float | Hz | Resolution bandwidth |
| `bench/ssa/peak/freq_hz` | float | Hz | Peak signal frequency |
| `bench/ssa/peak/level_dbm` | float | dBm | Peak signal level |

### Command topics

| Topic | Type | Description |
|-------|------|-------------|
| `bench/ssa/center_hz/set` | float | Set center frequency |
| `bench/ssa/span_hz/set` | float | Set span |
| `bench/ssa/ref_level_dbm/set` | float | Set reference level |
| `bench/ssa/rbw_hz/set` | float | Set RBW |

**Note:** Full 801-point traces are NOT published via MQTT (too large). Use direct SCPI for raw trace data.

**Poll interval:** 2 s
**Bridge script:** `drivers/mqtt/bridges/bridge_ssa.py`

---

## SDS2504X Plus Oscilloscope

**Prefix:** `bench/scope`

### Published topics

| Topic | Type | Unit | Description |
|-------|------|------|-------------|
| `bench/scope/ch1/vpp_v` | float | V | Channel 1 peak-to-peak voltage |
| `bench/scope/ch1/rms_v` | float | V | Channel 1 RMS voltage |
| `bench/scope/ch1/frequency_hz` | float | Hz | Channel 1 frequency |
| `bench/scope/ch2/...` | | | Same for CH2–CH4 |
| `bench/scope/timebase_s_div` | float | s | Timebase setting |
| `bench/scope/trigger_mode` | string | — | Trigger mode |

### Command topics

| Topic | Type | Description |
|-------|------|-------------|
| `bench/scope/run/set` | bool | Start/stop acquisition |

**Note:** Waveform data is NOT published via MQTT. Use direct SCPI for waveform capture.

**Poll interval:** 2 s
**Bridge script:** `drivers/mqtt/bridges/bridge_scope.py`
