> ⚠️ **UNTESTED** — This implementation has not been verified against physical hardware.
> Code is complete but has not been bench-tested. Verify behavior before relying on output.

# rf-bench-flipper-rfid-field

**GitHub:** https://github.com/jfrancis42/rf-bench-flipper-rfid-field

The Flipper Zero emits its 125 kHz LF RFID reader field while the SSA3032X Plus
measures via a coupling loop. Three tests: frequency accuracy (ppm), harmonic content
(100 kHz–2 MHz sweep), and field strength vs. distance (manual step).

## Hardware

| Instrument | Role |
|-----------|------|
| Flipper Zero (/dev/ttyACM0) | LF RFID field emitter |
| Siglent SSA3032X Plus (10.1.1.60) | Measurement receiver |
| Coupling loop (DIY) | Antenna — pick up LF field |

Build a simple coupling loop: 5–10 turns of wire, ~50 mm diameter, with a 50Ω
termination resistor and SMA connector.

## Usage

```
python rfid_field.py --test {freq|harmonics|distance|all} [options]
```

### Options

| Flag | Default | Description |
|------|---------|-------------|
| `--ssa HOST` | 10.1.1.60 | SSA IP address |
| `--serial PORT` | /dev/ttyACM0 | Flipper serial port |
| `--test` | all | Test to run: freq, harmonics, distance, or all |
| `--output PREFIX` | timestamped | Output filename prefix |

### Examples

```bash
# Run all tests
python rfid_field.py --test all

# Frequency accuracy only
python rfid_field.py --test freq

# Field strength vs. distance (interactive prompts)
python rfid_field.py --test distance
```

## Output files

| File | Description |
|------|-------------|
| `{prefix}_rfid_field.png` | Summary plots |
| `{prefix}_rfid_field.json` | Raw measurement data |

## Notes

- The Flipper activates its RFID field via `lfrfid_emulate(EM4100, ...)`.
- Distance test is interactive: script prompts at each distance step.
- Harmonic alarm threshold is −30 dBc (informational; no regulatory limit for test equipment).
