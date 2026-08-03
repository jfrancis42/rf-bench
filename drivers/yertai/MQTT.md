# MQTT Map — Yertai ET5406A+ DC Electronic Load

**Prefix:** `bench/load`

## Published topics

| Topic | Type | Unit | Description |
|-------|------|------|-------------|
| `bench/load/voltage_v` | float | V | Measured input voltage |
| `bench/load/current_a` | float | A | Measured sink current |
| `bench/load/power_w` | float | W | Measured power dissipation |
| `bench/load/resistance_ohm` | float | Ω | Measured/calculated resistance |
| `bench/load/mode` | string | — | Operating mode (CC, CV, CP, CR, CCCV, etc.) |
| `bench/load/input` | bool | — | Input (load) enabled |
| `bench/load/protection/ovp` | bool | — | Over-voltage protection active |
| `bench/load/protection/ocp` | bool | — | Over-current protection active |
| `bench/load/protection/opp` | bool | — | Over-power protection active |

## Command topics

| Topic | Type | Description |
|-------|------|-------------|
| `bench/load/input/set` | bool | Enable/disable load input |
| `bench/load/mode/set` | string | Set operating mode (CC, CV, CP, CR) |
| `bench/load/current_a/set` | float | Set CC mode current |
| `bench/load/voltage_v/set` | float | Set CV mode voltage |
| `bench/load/power_w/set` | float | Set CP mode power |
| `bench/load/resistance_ohm/set` | float | Set CR mode resistance |

**Poll interval:** 2 s
**Connection:** USB serial (/dev/ttyUSB0 on greybox 10.1.0.16)
**Bridge script:** `drivers/mqtt/bridges/bridge_load.py`
