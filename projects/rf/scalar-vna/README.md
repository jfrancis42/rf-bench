# siglent-scalar-vna

Two-port scalar network analyzer using the Siglent SSA3032X Plus + RB3X25 reflection bridge.

Measures:

- **S11** — Return loss and VSWR (via reflection bridge)
- **S21** — Insertion loss / gain (via through path)

## Hardware

| Instrument | Role |
|-----------|------|
| Siglent SSA3032X Plus (10.1.1.60) | Spectrum analyzer + tracking generator |
| Siglent RB3X25 | Passive reflection bridge (S11 only) |

## Setup

### S11 (return loss / VSWR)

```
┌──────────────────────────────────────┐
│            SSA3032X Plus             │
│                                      │
│  TG Out ──── RB3X25 TG              │
│              RB3X25 SA ──── RF In   │
│                                      │
│              RB3X25 DUT ──── [DUT]  │
└──────────────────────────────────────┘
```

Open-circuit calibration: disconnect DUT, leave RB3X25 DUT port open.

### S21 (insertion loss / gain)

```
SSA TG Out ──── DUT input
DUT output ──── SSA RF In

Through calibration: connect TG Out directly to RF In (no DUT).
```

## Usage

```
python scalar_vna.py [options]
```

### Options

| Flag | Default | Description |
|------|---------|-------------|
| `--s11` | — | Measure S11 only |
| `--s21` | — | Measure S21 only |
| (neither) | — | Measure both S11 and S21 |
| `--start KHZ` | 100 | Start frequency in kHz |
| `--stop KHZ` | 200000 | Stop frequency in kHz |
| `--points N` | 301 | Sweep points |
| `--cal-file FILE` | ~/.scalar_vna_cal.npz | Calibration file |
| `--calibrate` | — | Run calibration only and save |
| `--ssa-host HOST` | 10.1.1.60 | SSA IP address |
| `--output PREFIX` | timestamped | Output filename prefix |
| `--yes` | — | Skip interactive prompts |

### Examples

```bash
# S11 + S21 measurement (with cable change prompts)
python scalar_vna.py

# S11 only (e.g. antenna measurement)
python scalar_vna.py --s11

# S21 only (e.g. filter insertion loss)
python scalar_vna.py --s21 --start 100 --stop 50000

# Re-calibrate S11 open-circuit
python scalar_vna.py --s11 --calibrate

# Re-calibrate S21 through reference
python scalar_vna.py --s21 --calibrate

# Unattended measurement (assumes calibration already saved)
python scalar_vna.py --s11 --yes --output filter_test
```

## Output files

| File | Description |
|------|-------------|
| `<prefix>.png` | S11 (return loss + VSWR) and/or S21 panel(s) |
| `<prefix>.txt` | Text report with frequency table |
| `<prefix>.json` | Full numerical data (freqs, RL, VSWR, S21) |
| `~/.scalar_vna_cal.npz` | Saved calibration (S11 open + S21 through) |

## Notes

- The SSA tracking generator must be licensed and working.  Verify TG Out has
  signal before use (connect to RF In, check for flat trace ~0 dBm).
- S11 calibration must be taken at the same frequency range as the measurement.
  If the frequency range changes, recalibrate.
- S21 measurement range is limited by the SSA noise floor (~−100 dBm).  For
  high-loss DUTs, reduce the frequency span or increase points.
- The S11 and S21 calibrations are stored in the same `.npz` file.  Calibrating
  one does not invalidate the other.
