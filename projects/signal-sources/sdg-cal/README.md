> ⚠️ **UNTESTED** — This implementation has not been verified against physical hardware.
> Code is complete but has not been bench-tested. Verify behavior before relying on output.

# rf-bench-sdg-cal

**GitHub:** https://github.com/jfrancis42/rf-bench-sdg-cal

SDG1062X self-characterization and calibration tool using the SSA3032X Plus as the
reference measurement receiver. Measures output level flatness, harmonic content, output
power linearity (1 dB compression), and two-channel amplitude tracking. Generates per-channel
correction tables for use in other measurement scripts.

## Hardware

| Instrument | Role |
|-----------|------|
| Siglent SDG1062X (10.1.1.55) | Signal source under test |
| Siglent SSA3032X Plus (10.1.1.60) | Reference measurement receiver |

## Setup

### Single-channel tests (level flatness, harmonics, linearity)

```
SDG CH1 ──→ SSA [RF In]
```

### Two-channel tracking test

```
SDG CH1 ──→ SSA [RF In]   (measured alternately)
SDG CH2 ──→ SSA [RF In]
```

Reconnect the cable between CH1 and CH2 as prompted, or use a relay switch.

## Usage

```
python sdg_cal.py [tests] [options]
```

### Tests

| Flag | Description |
|------|-------------|
| `--level-cal` | Output level flatness vs. frequency (CH1 and CH2) |
| `--harmonics` | Harmonic content (2nd/3rd) at multiple frequencies |
| `--linearity` | Output power linearity and 1 dB compression |
| `--tracking` | CH1/CH2 amplitude tracking vs. frequency |
| `--all` | All tests above |
| `--save-correction` | Write `~/.sdg_cal.json` correction table |

### Options

| Flag | Default | Description |
|------|---------|-------------|
| `--freq KHZ` | 14000 | Test frequency for single-freq tests (kHz) |
| `--start KHZ` | 1000 | Sweep start (kHz) |
| `--stop KHZ` | 30000 | Sweep stop (kHz) |
| `--points N` | 20 | Number of sweep frequency points |
| `--ref-level DBM` | −10 | SDG output level for sweep tests |
| `--sdg-host HOST` | 10.1.1.55 | SDG IP address |
| `--ssa-host HOST` | 10.1.1.60 | SSA IP address |
| `--prefix TEXT` | timestamped | Output filename prefix |

### Examples

```bash
# Full characterization
python sdg_cal.py --all --save-correction

# Level flatness only, 1 MHz – 60 MHz
python sdg_cal.py --level-cal --start 1000 --stop 60000 --points 30

# Harmonic check at reference level −10 dBm
python sdg_cal.py --harmonics --ref-level -10

# Linearity at 14 MHz
python sdg_cal.py --linearity --freq 14000
```

## Output files

| File | Description |
|------|-------------|
| `{prefix}_flatness.png/txt/json` | Level flatness vs. frequency |
| `{prefix}_harmonics.png/txt/json` | 2nd/3rd harmonic content |
| `{prefix}_linearity.png/txt/json` | Output power vs. set level, P1dB |
| `{prefix}_tracking.png/txt/json` | CH1 − CH2 amplitude difference vs. frequency |
| `~/.sdg_cal.json` | Per-channel correction table (--save-correction) |
