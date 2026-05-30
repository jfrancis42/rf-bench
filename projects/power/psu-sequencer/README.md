> ⚠️ **UNTESTED** — This implementation has not been verified against physical hardware.
> Code is complete but has not been bench-tested. Verify behavior before relying on output.

# rf-bench-psu-sequencer

**GitHub:** https://github.com/jfrancis42/rf-bench-psu-sequencer

Power-on/power-off sequencer for the SPD3303X. Executes multi-channel sequences with
precise millisecond-level timing read from a JSON file. Supports repeat cycling,
inter-cycle dwell, and overcurrent abort.

## Hardware

| Instrument | Role |
|-----------|------|
| Siglent SPD3303X-E (10.1.1.56) | Triple-output PSU — 2×32V/3.2A + 5V fixed |

## Usage

```
python psu_sequencer.py --sequence FILE.json [options]
```

### Sequence JSON format

```json
{"name": "FPGA board", "steps": [
  {"t_ms": 0,   "ch": 1, "action": "on",  "volts": 1.0, "ilim_a": 0.5},
  {"t_ms": 10,  "ch": 2, "action": "on",  "volts": 3.3, "ilim_a": 1.0},
  {"t_ms": 500, "ch": 2, "action": "off"},
  {"t_ms": 510, "ch": 1, "action": "off"}
]}
```

- `t_ms` — time offset from sequence start in milliseconds
- `ch` — channel number (1, 2, or 3)
- `action` — `"on"` or `"off"`
- `volts`, `ilim_a` — required for `"on"` actions only

Steps are automatically sorted by `t_ms`.

### Options

| Flag | Default | Description |
|------|---------|-------------|
| `--psu HOST` | 10.1.1.56 | SPD3303X IP address |
| `--sequence FILE` | required | JSON sequence file |
| `--cycles N` | 1 | Repeat cycles |
| `--dwell S` | 1.0 | Delay between cycles |
| `--abort-ma MA` | off | Abort if any channel exceeds this mA |

### Examples

```bash
# Run once
python psu_sequencer.py --sequence fpga_boot.json

# 100 power cycles with 2s dwell
python psu_sequencer.py --sequence board.json --cycles 100 --dwell 2.0

# Soak test with overcurrent abort
python psu_sequencer.py --sequence soak.json --cycles 1000 --abort-ma 500
```

## Safety

- All channels are powered off before the first cycle and unconditionally on exit
  (including Ctrl+C and exceptions).
- `--abort-ma` checks current on CH1 and CH2 every millisecond during execution.
  On overcurrent, all channels are immediately powered off and the run stops.
- CH3 is the fixed 5V/3.3V output — `on`/`off` actions are supported but voltage
  cannot be programmed.

## Notes

- Timing accuracy depends on OS scheduler latency — expect ±1–5 ms for most systems.
  For sub-millisecond sequences, consider an FPGA or microcontroller.
- Steps within the same `t_ms` are executed in the order they appear in the JSON array.
