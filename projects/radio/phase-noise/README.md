> ⚠️ **UNTESTED** — This implementation has not been verified against physical hardware.
> Code is complete but has not been bench-tested. Verify behavior before relying on output.

# rf-bench-phase-noise

**GitHub:** https://github.com/jfrancis42/rf-bench-phase-noise

Phase noise measurement tool using the SSA3032X Plus zero-span technique. Measures
single-sideband (SSB) phase noise L(f) in dBc/Hz at multiple offset frequencies and
plots the phase noise profile from 10 Hz to 1 MHz offset.

## Hardware

| Instrument | Role |
|-----------|------|
| Siglent SSA3032X Plus (10.1.1.60) | Spectrum analyzer (zero-span noise measurement) |
| Siglent SDG1062X (10.1.1.55) | Optional — carrier source for testing oscillators |

## Setup

### SDG source mode (default)

```
SDG CH1 OUT ──→ SSA [RF In]
```

Keep carrier level at −10 to −20 dBm at the SSA input. Use an attenuator if
the source is stronger than −10 dBm.

### External source mode (`--source ext`)

```
External oscillator / TX ──→ [attenuator if needed] ──→ SSA [RF In]
```

## Usage

```
python phase_noise.py --freq FREQ_KHZ [options]
```

### Options

| Flag | Default | Description |
|------|---------|-------------|
| `--freq KHZ` | 10000 | Carrier frequency in kHz |
| `--source {sdg\|ext}` | sdg | Signal source |
| `--carrier-level DBM` | −10 | SDG output level (sdg mode only) |
| `--offsets HZ,...` | 10,30,100,...,1M | Comma-separated offset frequencies (Hz) |
| `--averages N` | 5 | SSA trace averages at each offset |
| `--ssa-host HOST` | 10.1.1.60 | SSA IP address |
| `--sdg-host HOST` | 10.1.1.55 | SDG IP address |
| `--prefix TEXT` | timestamped | Output filename prefix |

### Examples

```bash
# Phase noise of a 10 MHz reference oscillator
python phase_noise.py --freq 10000 --source ext

# Phase noise of SDG at 14 MHz, 10 averages
python phase_noise.py --freq 14000 --averages 10

# Custom offsets: 100 Hz to 100 kHz in decades
python phase_noise.py --freq 28000 --offsets 100,1000,10000,100000
```

## Output files

| File | Description |
|------|-------------|
| `{prefix}_phase_noise.png` | L(f) vs. offset (log scale) with reference lines |
| `{prefix}_phase_noise.txt` | Tabular results: offset, L(f) |
| `{prefix}_phase_noise.json` | Machine-readable results |

## Method

The zero-span technique:
1. Measure carrier power with a 100 kHz span / 30 kHz RBW
2. For each offset: configure SSA to zero-span centered at carrier + offset
3. Measure noise floor (linear-domain averaging for correct noise statistics)
4. L(f) = P_noise_dBm − P_carrier_dBm − 10·log10(RBW_Hz) [dBc/Hz]
