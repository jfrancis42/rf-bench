> ⚠️ **UNTESTED** — This implementation has not been verified against physical hardware.
> Code is complete but has not been bench-tested. Verify behavior before relying on output.

# rf-bench-flipper-cc1101

**GitHub:** https://github.com/jfrancis42/rf-bench-flipper-cc1101

Characterizes the Flipper Zero's CC1101 Sub-GHz radio. Measures frequency accuracy (ppm),
output power vs. PATABLE index, and harmonic content using the SSA3032X Plus. Generates
`~/.flipper_cc1101_cal.json` for use by other rf-bench-flipper projects.

## Hardware

| Instrument | Role |
|-----------|------|
| Flipper Zero (/dev/ttyACM0) | CC1101 TX — carrier source |
| Siglent SSA3032X Plus (10.1.1.60) | Spectrum analyzer — measures output |

Connect Flipper Sub-GHz SMA output to SSA input via short coax. Use a 20–30 dB attenuator
to protect the SSA input when measuring at high power.

## Usage

```
python cc1101.py [options]
```

### Options

| Flag | Default | Description |
|------|---------|-------------|
| `--ssa HOST` | 10.1.1.60 | SSA IP address |
| `--serial PORT` | /dev/ttyACM0 | Flipper serial port |
| `--freqs LIST` | 315,433.92,868,915 | Comma-separated MHz |
| `--gain DBM` | 0 | SSA reference level offset |
| `--patable` | off | Sweep PATABLE indices 0–7 |
| `--harmonics` | off | Measure harmonic content |
| `--output PREFIX` | timestamped | Output filename prefix |

### Examples

```bash
# Full characterization of all ISM bands
python cc1101.py --freqs 315,433.92,868,915 --harmonics

# PATABLE sweep at 433.92 MHz only
python cc1101.py --freqs 433.92 --patable

# Custom frequency with harmonics
python cc1101.py --freqs 433.92 --harmonics
```

## Output files

| File | Description |
|------|-------------|
| `{prefix}_cc1101.png` | Frequency error + PATABLE power plot |
| `~/.flipper_cc1101_cal.json` | Calibration table (ppm, dBm per band) |

## Notes

- Harmonic check uses FCC Part 15 −43 dBc limit as the pass/fail threshold.
- PATABLE sweep currently steps through the 8 indices but the Flipper driver
  exposes power via the gain argument to subghz_tx_carrier.
- Frequency accuracy is typically ±2–5 ppm with the stock Flipper TCXO.
