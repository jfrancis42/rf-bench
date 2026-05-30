> ⚠️ **UNTESTED** — This implementation has not been verified against physical hardware.
> Code is complete but has not been bench-tested. Verify behavior before relying on output.

# rf-bench-osc-stability

**GitHub:** https://github.com/jfrancis42/rf-bench-osc-stability

Oscillator frequency stability analyzer. Measures carrier frequency versus time using
SSA3032X Plus narrow-span centroid tracking, then computes Allan deviation (ADEV) σ_y(τ)
at multiple tau values. Identifies oscillator noise types from the ADEV slope
(white FM, flicker FM, random walk FM).

## Hardware

| Instrument | Role |
|-----------|------|
| Siglent SSA3032X Plus (10.1.1.60) | Frequency tracking via narrow-span centroid |
| Siglent SDG1062X (10.1.1.55) | Optional — carrier source for testing |

## Setup

### SDG source mode (default)

```
SDG CH1 OUT ──→ SSA [RF In]
```

### External source mode (`--source ext`)

```
Oscillator output ──→ [attenuator if needed] ──→ SSA [RF In]
```

Keep the signal level between −20 and 0 dBm at the SSA input for best CNR.

## Usage

```
python osc_stability.py --freq FREQ_KHZ [options]
```

### Options

| Flag | Default | Description |
|------|---------|-------------|
| `--freq KHZ` | 10000 | Carrier frequency in kHz |
| `--source {sdg\|ext}` | sdg | Signal source |
| `--duration S` | 300 | Measurement duration (seconds) |
| `--interval S` | 1.0 | Target sample interval (seconds) |
| `--carrier-level DBM` | −10 | SDG output level (sdg mode) |
| `--ssa-host HOST` | 10.1.1.60 | SSA IP address |
| `--sdg-host HOST` | 10.1.1.55 | SDG IP address |
| `--prefix TEXT` | timestamped | Output filename prefix |
| `--plot FILE.npz` | — | Offline: regenerate plots from saved data |

### Examples

```bash
# 5-minute stability run on 10 MHz TXCO
python osc_stability.py --freq 10000 --source ext --duration 300

# 1-hour run with 2-second intervals
python osc_stability.py --freq 14000 --source ext --duration 3600 --interval 2.0

# Regenerate plots from saved data
python osc_stability.py --plot stability_20260101_120000.npz
```

## Output files

| File | Description |
|------|-------------|
| `{prefix}_stability.npz` | Frequency samples, timestamps, metadata |
| `{prefix}_stability.png` | Frequency deviation + ADEV log-log plot |
| `{prefix}_stability.txt` | ADEV table: tau, σ_y(τ) |

## Allan deviation

Non-overlapping two-sample ADEV:
- Fractional frequency deviation: y_k = (f_k − f₀) / f₀
- ADEV: σ_y(τ) = √(½ · mean((ȳ_{k+1} − ȳ_k)²))

Slope interpretation: −1 = white FM, −½ = flicker FM, 0 = random walk FM.
The ADEV floor indicates the best stability achievable at that averaging time.
