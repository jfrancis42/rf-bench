# siglent-balun-analyzer

Choking impedance analyzer for RF baluns and common-mode chokes.  Uses the Siglent
SSA3032X Plus tracking generator + RB3X25 reflection bridge to derive |Z| vs frequency.

## Key concept

Unlike antenna measurement where **low** VSWR is good, a balun/choke measurement
interprets **high** impedance as good.  A choke with 5 kΩ of impedance on 40m will
block common-mode current far more effectively than one with 200 Ω.

The instrument measures return loss (how much the choke looks like an open circuit).
From that, we derive the impedance magnitude:

```
Γ = 10^(−RL_dB / 20)
|Z| = 50 × (1 + Γ) / (1 − Γ)
```

## Hardware

| Instrument | Role |
|-----------|------|
| Siglent SSA3032X Plus (10.1.1.60) | Spectrum analyzer + tracking generator |
| Siglent RB3X25 | Passive reflection bridge |

## Setup

```
SSA TG Out ──── RB3X25 TG port
RB3X25 SA port ──── SSA RF In
RB3X25 DUT port ──── one end of choke
Far end of choke: OPEN (common-mode) or GND (differential-mode)
```

**Calibration (open circuit):**
```
RB3X25 DUT port ──── OPEN (nothing connected)
```

## Usage

```
python balun_analyzer.py [options]
```

### Options

| Flag | Default | Description |
|------|---------|-------------|
| `--start KHZ` | 1000 | Start frequency in kHz |
| `--stop KHZ` | 30000 | Stop frequency in kHz |
| `--points N` | 301 | Sweep points |
| `--hf` | default | HF preset: 1–30 MHz |
| `--vhf` | — | VHF preset: 30–300 MHz |
| `--uhf` | — | UHF preset: 300 MHz–1 GHz |
| `--cal-file FILE` | ~/.balun_cal.npz | Calibration file |
| `--calibrate` | — | Open-circuit calibration only |
| `--compare FILE` | — | Overlay previous measurement JSON |
| `--ssa-host HOST` | 10.1.1.60 | SSA IP address |
| `--output PREFIX` | timestamped | Output filename prefix |
| `--yes` | — | Skip interactive prompts |

### Examples

```bash
# Default HF sweep (1–30 MHz)
python balun_analyzer.py

# Open-circuit calibration
python balun_analyzer.py --calibrate

# Custom range (covers top HF and 6m)
python balun_analyzer.py --start 1000 --stop 55000

# VHF choke (VHF balun at antenna feedpoint)
python balun_analyzer.py --vhf

# Compare two chokes
python balun_analyzer.py --compare choke_a_choke.json --output choke_b
```

## Output files

| File | Description |
|------|-------------|
| `<prefix>_choke.png` | |Z| vs frequency (log scale, reference lines) |
| `<prefix>_choke.txt` | Text report with band-by-band effectiveness table |
| `<prefix>_choke.json` | Full numerical data (for future `--compare`) |
| `~/.balun_cal.npz` | Saved open-circuit calibration |

## Impedance thresholds

| |Z| | Assessment |
|----|------------|
| ≥ 5 kΩ | Excellent — minimal common-mode current |
| ≥ 1 kΩ | Good — adequate for most installations |
| ≥ 500 Ω | Fair — partial suppression only |
| < 500 Ω | Poor — choke is largely ineffective |

*Thresholds based on ARRL Antenna Handbook common-mode choke design guidelines.*

## Notes

- This tool measures **common-mode** choking impedance when the far end is open.
  Short the far end to ground for differential-mode (rare, mainly for power-line chokes).
- Impedance measurement gives magnitude |Z| only.  Complex Z (R + jX) requires a
  vector VNA.  For HF chokes, resistive impedance (R >> X) is preferable because it
  dissipates common-mode energy rather than just reflecting it back — but you can't
  determine this with a scalar measurement.
- The calibration file (`~/.balun_cal.npz`) is separate from the antenna-analyzer
  calibration.  Both use the same hardware setup, but keep them separate.
