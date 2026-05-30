> ⚠️ **UNTESTED** — This implementation has not been verified against physical hardware.
> Code is complete but has not been bench-tested. Verify behavior before relying on output.

# rf-bench-scope-eye

**GitHub:** https://github.com/jfrancis42/rf-bench-scope-eye

Eye diagram builder using the SDS2000X scope. Captures N triggered waveforms of a
serial signal, time-aligns each to the first rising-edge threshold crossing, and overlays
all traces with low alpha to show signal density. Reports eye height (V) and eye width
(% of UI).

## Hardware

| Instrument | Role |
|-----------|------|
| Siglent SDS2354X Plus (10.1.1.58) | 500 MHz oscilloscope — waveform capture |

## Usage

```
python scope_eye.py --baud BAUD [options]
```

`--baud` is required — it sets the timebase (1.5 bit periods / 10 divisions).

### Options

| Flag | Default | Description |
|------|---------|-------------|
| `--scope HOST` | 10.1.1.58 | Scope IP address |
| `--channel N` | 1 | Scope channel (1–4) |
| `--captures N` | 200 | Number of waveforms |
| `--baud N` | required | Signal baud rate |
| `--threshold V` | 0.0 | Trigger and crossing level (V) |
| `--plot FILE` | timestamped | Output PNG path |

### Examples

```bash
# UART 115200 baud eye diagram
python scope_eye.py --baud 115200 --captures 200

# High-speed SPI on CH2, 1V threshold
python scope_eye.py --baud 1000000 --channel 2 --threshold 1.65 --captures 500

# RS-485 differential
python scope_eye.py --baud 921600 --threshold 0.2 --captures 300 --plot rs485_eye.png
```

## Output

A PNG eye diagram with black background, green trace overlay (alpha=0.05 per trace),
cyan threshold line, and eye metrics in the title.

## Eye metrics

- **Eye height (mV):** voltage opening at the UI midpoint (50% percentile separation).
- **Eye width (% UI):** fraction of the bit period where the eye is "open" (5th/95th
  percentile on opposite sides of threshold).

## Notes

- Timebase is set automatically from `--baud`.
- The alignment algorithm finds the first upward crossing via linear interpolation — it
  works best with a clean NRZ signal (UART, SPI, I2C, CAN).
- For differential signals, connect the differential pair to two channels, set up the
  scope's math channel (A−B), and probe that channel.
