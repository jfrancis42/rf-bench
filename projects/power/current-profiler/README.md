# AC Current Profiler

Fluke 80i-400 clamp + bench DMM. Logs AC **current** over time and derives a
load profile: min/avg/RMS/peak current, on/off duty cycle, session stats.
Optionally publishes to the rf-bench MQTT bus.

**Measures current, not power.** The clamp can't see voltage, so this tool
reports amps and never fabricates watts. `--nominal-volts` adds an *indicative*
apparent-VA estimate (A×V, PF=1 assumed) that is clearly labeled an estimate —
use `../ac-power/` for real measured power.

## Connections

```
conductor ──► 80i-400 clamp ──► DMM current (mA) jacks, AC current mode
```

## Usage

```bash
python current_profiler.py                    # log via inventory DMM "sdm", 1 Hz
python current_profiler.py --interval 0.5      # 2 Hz
python current_profiler.py --duration 3600     # stop after 1 h
python current_profiler.py --csv load.csv
python current_profiler.py --on-threshold 1.5  # "on" when >1.5 A
python current_profiler.py --mqtt              # publish to MQTT bus
python current_profiler.py --nominal-volts 120 # add indicative apparent-VA
```

## MQTT

`--mqtt` publishes `/bench/clamp/amps`, `/bench/clamp/on`, and (if
`--nominal-volts`) `/bench/clamp/apparent_va_est`. For an always-on daemon use
the bridge instead: `drivers/mqtt/bridges/bridge_clamp.py`.

See `ideas/fluke-80i400-projects.md`.
