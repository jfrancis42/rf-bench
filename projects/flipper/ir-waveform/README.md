> ⚠️ **UNTESTED** — This implementation has not been verified against physical hardware.
> Code is complete but has not been bench-tested. Verify behavior before relying on output.

# rf-bench-flipper-ir-waveform

**GitHub:** https://github.com/jfrancis42/rf-bench-flipper-ir-waveform

Captures Flipper IR LED output via a silicon photodiode connected to the oscilloscope.
Measures carrier frequency (via FFT), duty cycle, and NEC/SIRC protocol timing accuracy.
Optional --map-rx mode sweeps the scope AWG to map the Flipper IR receiver bandpass.

## Hardware

| Instrument | Role |
|-----------|------|
| Flipper Zero (/dev/ttyACM0) | IR transmitter |
| Siglent SDS2354X Plus (10.1.1.58) | Oscilloscope CH1 |
| Si photodiode + transimpedance amp | Converts IR to voltage |

For --map-rx: scope AWG CH1 drives an IR LED pointing at the Flipper.

## Usage

```
python ir_waveform.py --test {carrier|timing|all} [--map-rx]
```

### Options

| Flag | Default | Description |
|------|---------|-------------|
| `--scope HOST` | 10.1.1.58 | Scope IP |
| `--serial PORT` | /dev/ttyACM0 | Flipper serial port |
| `--test` | all | Test: carrier, timing, or all |
| `--protocol` | NEC | NEC or SIRC |
| `--map-rx` | off | Map receiver bandpass 30-60 kHz |
| `--output PREFIX` | timestamped | Output prefix |

### Examples

```bash
python ir_waveform.py --test all --protocol NEC
python ir_waveform.py --map-rx
```
