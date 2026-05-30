> ⚠️ **UNTESTED** — This implementation has not been verified against physical hardware.
> Code is complete but has not been bench-tested. Verify behavior before relying on output.

# rf-bench-noise-figure

**GitHub:** https://github.com/jfrancis42/rf-bench-noise-figure

Y-factor noise figure meter using the SSA3032X Plus as the measurement receiver. Supports
single-frequency NF measurement and swept NF vs. frequency. Stores a baseline SSA noise
floor calibration to de-embed the SSA's own noise figure from the result.

## Hardware

| Instrument | Role |
|-----------|------|
| Siglent SSA3032X Plus (10.1.1.60) | Measurement receiver (zero-span noise floor) |
| Noise source | Switched noise reference (ENR typically 15–25 dB) |

The script prompts you to toggle the noise source manually (hot/cold states). A
programmable noise source can be automated by subclassing `_prompt_noise_state()`.

## Setup

### Direct NF measurement (DUT between noise source and SSA)

```
Noise source ──→ [DUT] ──→ SSA [RF In]
```

### Baseline calibration (`--baseline` flag)

```
Noise source ──→ SSA [RF In]   (no DUT; measures SSA noise figure alone)
```

Run baseline calibration once; results are stored in `~/.noise_figure_ssa_cal.json`
and auto-loaded on subsequent measurements.

## Usage

```
python noise_figure.py --enr ENR_DB [options]
```

### Options

| Flag | Default | Description |
|------|---------|-------------|
| `--enr DB` | required | Noise source Excess Noise Ratio (dB) at the measurement frequency |
| `--freq KHZ` | 14000 | Measurement frequency in kHz (single-freq mode) |
| `--sweep` | off | Sweep NF vs. frequency (uses --start / --stop) |
| `--start KHZ` | 1000 | Sweep start frequency (kHz) |
| `--stop KHZ` | 30000 | Sweep stop frequency (kHz) |
| `--points N` | 20 | Number of sweep frequency points |
| `--gain DB` | 0 | DUT gain estimate for de-embedding (0 = skip de-embedding) |
| `--baseline` | off | Run baseline SSA calibration (no DUT) |
| `--rbw HZ` | 30000 | Measurement RBW |
| `--averages N` | 10 | Trace averages for noise floor measurement |
| `--ssa-host HOST` | 10.1.1.60 | SSA IP address |
| `--prefix TEXT` | timestamped | Output filename prefix |

### Examples

```bash
# Run baseline calibration first (once)
python noise_figure.py --baseline --enr 15

# Measure NF of LNA at 14 MHz, ENR=15 dB
python noise_figure.py --enr 15 --freq 14000

# Swept NF 1–30 MHz, LNA with ~20 dB gain
python noise_figure.py --enr 15 --sweep --start 1000 --stop 30000 --gain 20
```

## Output files

| File | Description |
|------|-------------|
| `{prefix}_nf.png` | NF bar chart (single) or NF vs. frequency (sweep) |
| `{prefix}_nf.txt` | Tabular results |
| `{prefix}_nf.json` | Full numerical data |
| `~/.noise_figure_ssa_cal.json` | Stored SSA baseline calibration |

## Method

Y-factor technique:
- Y = P_hot / P_cold (linear power ratio from SSA noise floor measurements)
- NF_system = ENR_dB − 10·log10(Y − 1)
- De-embedding (Friis): NF_DUT = NF_system − (NF_SSA − 1) / G_DUT

All noise power averaging is performed in the linear domain (mW), not in dB.
