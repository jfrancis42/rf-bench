> ⚠️ **UNTESTED** — This implementation has not been verified against physical hardware.
> Code is complete but has not been bench-tested. Verify behavior before relying on output.

# rf-bench-flipper-ir-rx-response

**GitHub:** https://github.com/jfrancis42/rf-bench-flipper-ir-rx-response

Maps the Flipper Zero IR receiver's demodulator bandpass. The scope AWG generates an
IR carrier at frequencies from 30-60 kHz in 500 Hz steps at 33% duty cycle, drives
an IR LED at the Flipper, and checks whether the Flipper decodes a NEC burst.
Output: decode_success vs. carrier frequency plot.

## Hardware

| Instrument | Role |
|-----------|------|
| Siglent SDS2354X Plus (10.1.1.58) | AWG drives IR LED |
| Flipper Zero (/dev/ttyACM0) | IR receiver under test |
| IR LED + 100 Ohm resistor | Driven by scope AWG CH1 |

Wire: AWG CH1 -> 100 Ohm -> IR LED anode -> GND. Position LED 10-20 mm from Flipper IR RX.

## Usage

```
python ir_rx_response.py [options]
```

### Options

| Flag | Default | Description |
|------|---------|-------------|
| `--scope HOST` | 10.1.1.58 | Scope IP |
| `--serial PORT` | /dev/ttyACM0 | Flipper serial port |
| `--start KHZ` | 30 | Start frequency (kHz) |
| `--stop KHZ` | 60 | Stop frequency (kHz) |
| `--step KHZ` | 0.5 | Step size (kHz) |
| `--output PREFIX` | timestamped | Output prefix |

## Output files

| File | Description |
|------|-------------|
| `{prefix}_rx_response.png` | Bandpass plot |
| `{prefix}_rx_response.csv` | Raw data: freq_hz, decode_success |
