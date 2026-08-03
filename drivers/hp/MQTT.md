# MQTT Map — HP 8712B Vector Network Analyzer

**Prefix:** `bench/hp8712b`

**Status:** Hardware pending — KISS-488 GPIB adapter not yet installed.

## Published topics

| Topic | Type | Unit | Description |
|-------|------|------|-------------|
| `bench/hp8712b/start_hz` | float | Hz | Sweep start frequency |
| `bench/hp8712b/stop_hz` | float | Hz | Sweep stop frequency |
| `bench/hp8712b/points` | int | — | Sweep point count |
| `bench/hp8712b/parameter` | string | — | Active S-parameter (S11, S21, etc.) |
| `bench/hp8712b/min_db` | float | dB | Minimum trace value |
| `bench/hp8712b/min_freq_hz` | float | Hz | Frequency of minimum |
| `bench/hp8712b/vswr_min` | float | :1 | VSWR at minimum (S11 only) |

## Command topics

| Topic | Type | Description |
|-------|------|-------------|
| `bench/hp8712b/sweep/set` | object | Set sweep: `{"start": Hz, "stop": Hz, "points": N}` |
| `bench/hp8712b/parameter/set` | string | Set S-parameter (S11, S21, S12, S22) |

**Poll interval:** 5 s
**Connection:** GPIB via KISS-488 at 10.1.1.70
**Bridge script:** `drivers/mqtt/bridges/bridge_hp8712b.py`
