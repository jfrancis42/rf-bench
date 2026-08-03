# Power Projects

Power supply and thermal measurement projects.

## AC mains projects (Fluke 80i-400 clamp)

| Project | Front-end | Safe? | What it does |
|---|---|---|---|
| `ac-harmonics/` | clamp → burden → scope | ✅ current-only | THD-i + per-harmonic breakdown of mains current |
| `ac-inrush/` | clamp → burden → scope | ✅ current-only | Turn-on inrush: peak A, duration, I²t |
| `current-profiler/` | clamp → DMM | ✅ current-only | Log current over time, duty cycle, MQTT publish |
| `ac-power/` | clamp + **voltage sense** → scope | ⚠ needs isolation | True power (W), VA, var, power factor. Safety-gated. |

See `ideas/fluke-80i400-projects.md` for the full ranked list, the two
front-ends, and the "wrong tool" cases. The clamp driver is `rf_bench.fluke`;
the DC-side inrush counterpart is `inrush/`.
