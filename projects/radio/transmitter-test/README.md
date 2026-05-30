> ⚠️ **UNTESTED** — This implementation has not been verified against physical hardware.
> Code is complete but has not been bench-tested. Verify behavior before relying on output.

# rf-bench-transmitter-test

**GitHub:** https://github.com/jfrancis42/rf-bench-transmitter-test

Automated HF transmitter test suite for the Icom IC-7300 and Yaesu FT-891. Measures output
power across all HF bands, harmonic content (with FCC Part 97 pass/fail), ALC compression
curve, and SSB carrier suppression. The SSA3032X Plus is used as the measurement receiver.

## Hardware

| Instrument | Role |
|-----------|------|
| Siglent SSA3032X Plus (10.1.1.60) | Spectrum analyzer — power and harmonic measurement |
| Icom IC-7300 or Yaesu FT-891 | Transmitter under test |
| Hamlib rigctld (localhost:4532) | CAT control (PTT, frequency, mode) |
| Fixed attenuator chain (60 dB default) | Protects SSA from full transmit power |

## Setup

```
Radio [TX Antenna port] ──→ 20 dB pad ──→ 20 dB pad ──→ 20 dB pad ──→ SSA [RF In]
                                                      (total: 60 dB attenuation)
```

**CAUTION:** Never connect the radio TX port directly to the SSA without attenuation.
100 W (50 dBm) minus 60 dB attenuation = −10 dBm at the SSA — safe margin with headroom.
Use higher attenuation (e.g., 80 dB) for 100 W transceivers.

```bash
# Start rigctld before running tests
rigctld -m 3073 -r /dev/ttyUSB0 -s 115200 &   # IC-7300
# or
rigctld -m 1036 -r /dev/ttyUSB0 -s 38400 &    # FT-891
```

## Usage

```
python transmitter_test.py --radio {ic7300|ft891} [tests] [options]
```

### Tests

| Flag | Description |
|------|-------------|
| `--power` | CW carrier power at each band center (dBm and W) |
| `--harmonics` | 2nd/3rd/4th harmonic levels (dBc); FCC Part 97 pass/fail |
| `--alc` | ALC compression curve: output power vs. power control setting |
| `--carrier-suppression` | SSB carrier suppression (residual carrier in dBc) |
| `--all` | All tests above |

### Options

| Flag | Default | Description |
|------|---------|-------------|
| `--radio {ic7300\|ft891}` | required | Radio model |
| `--freq KHZ` | 14200 | Test frequency in kHz (single-freq tests) |
| `--atten DB` | 60 | Total path attenuation (dB) |
| `--ssa-host HOST` | 10.1.1.60 | SSA IP address |
| `--rig-host HOST` | localhost | rigctld hostname |
| `--rig-port PORT` | 4532 | rigctld port |
| `--prefix TEXT` | timestamped | Output filename prefix |

### Examples

```bash
# Power at all HF bands
python transmitter_test.py --radio ic7300 --power

# Full test suite with 80 dB attenuation
python transmitter_test.py --radio ft891 --all --atten 80

# Harmonic check only, 20m band
python transmitter_test.py --radio ic7300 --harmonics --freq 14200

# ALC curve at 40m
python transmitter_test.py --radio ic7300 --alc --freq 7150
```

## Output files

| File | Description |
|------|-------------|
| `{prefix}_power.png/txt/json` | Power vs. band plot and table |
| `{prefix}_harmonics.png/txt/json` | Harmonic levels and FCC compliance |
| `{prefix}_alc.png/txt/json` | ALC compression curve |
| `{prefix}_carrier.txt/json` | Carrier suppression result |
