# MQTT Map — Solartron 7151 6.5-Digit DMM

**Prefix:** `bench/solartron`

**Status:** Hardware pending — KISS-488 GPIB adapter not yet installed.

## Published topics

| Topic | Type | Unit | Description |
|-------|------|------|-------------|
| `bench/solartron/value` | float | varies | Current measurement value |
| `bench/solartron/function` | string | — | Measurement function |
| `bench/solartron/range` | string | — | Current range setting |

## Command topics

| Topic | Type | Description |
|-------|------|-------------|
| `bench/solartron/function/set` | string | Set measurement function |
| `bench/solartron/range/set` | string | Set range |

**Poll interval:** 1 s
**Connection:** GPIB via KISS-488 at 10.1.1.70
**Bridge script:** `drivers/mqtt/bridges/bridge_solartron.py`
