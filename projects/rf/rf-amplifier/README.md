# siglent-rf-amplifier

RF amplifier test bench tool for the Siglent SSA3032X Plus + SDG1062X.  Measures:

- **Gain and flatness** across a swept frequency range
- **Harmonic content** (2nd and 3rd harmonic) at each frequency (optional)
- **1 dB compression point (P1dB)** at a user-selected frequency (optional)

## Hardware

| Instrument | Role |
|-----------|------|
| Siglent SSA3032X Plus (10.1.1.60) | Spectrum analyzer — measurement receiver |
| Siglent SDG1062X (10.1.1.55) | Function generator — signal source (SDG mode, ≤60 MHz) |
| SSA tracking generator | Built-in TG — signal source (TG mode, 9 kHz – 3.2 GHz) |

## Setup

### SDG mode (default, ≤60 MHz)

```
SDG CH1 OUT ──── DUT RF In
DUT RF Out  ──── SSA RF In
```

### TG mode (--source tg, up to 3.2 GHz)

```
SSA TG Out  ──── DUT RF In
DUT RF Out  ──── SSA RF In
```

**CAUTION:** If the DUT output power exceeds +30 dBm, insert an attenuator between the
DUT output and the SSA RF In to protect the analyzer input.

## Usage

```
python rf_amplifier.py [options]
```

### Options

| Flag | Default | Description |
|------|---------|-------------|
| `--start KHZ` | 1000 | Start frequency in kHz |
| `--stop KHZ` | 30000 | Stop frequency in kHz |
| `--points N` | 200 | Number of frequency points |
| `--input-dbm DBM` | −20 | SDG output level (input to DUT) in dBm |
| `--source {sdg\|tg}` | sdg | Signal source |
| `--p1db` | off | Measure 1 dB compression point |
| `--p1db-freq KHZ` | midpoint | Frequency for P1dB sweep |
| `--harmonics` | off | Measure 2nd/3rd harmonic levels |
| `--sdg-host HOST` | 10.1.1.55 | SDG IP address |
| `--ssa-host HOST` | 10.1.1.60 | SSA IP address |
| `--output PREFIX` | timestamped | Output filename prefix |

### Examples

```bash
# Basic HF gain sweep (1–30 MHz)
python rf_amplifier.py

# Wide HF/VHF sweep with harmonics
python rf_amplifier.py --start 1000 --stop 200000 --harmonics

# Full-range sweep using tracking generator
python rf_amplifier.py --source tg --start 1000 --stop 3200000

# P1dB on 40m amateur band
python rf_amplifier.py --p1db --p1db-freq 14000

# Everything: gain + harmonics + P1dB, saved to custom prefix
python rf_amplifier.py --p1db --harmonics --input-dbm -30 --output my_lna
```

## Output files

| File | Description |
|------|-------------|
| `<prefix>_gain.png` | Gain vs frequency plot; optional harmonics panel |
| `<prefix>_gain.txt` | Text report with summary statistics |
| `<prefix>_gain.json` | Full numerical data (frequencies, gain, output power) |
| `<prefix>_p1db.png` | Gain compression and output power plot (with `--p1db`) |

## Notes

- **SDG mode** is recommended for HF measurements (better accuracy, narrow-band
  measurement at each frequency minimizes noise).
- **TG mode** is required for frequencies above 60 MHz (SDG1062X limit).
- The 1 dB compression measurement requires SDG mode; it is not available with TG.
- For high-gain amplifiers, reduce `--input-dbm` to avoid overloading the SSA
  (SSA3032X Plus input maximum is +30 dBm absolute, +10 dBm recommended max).
