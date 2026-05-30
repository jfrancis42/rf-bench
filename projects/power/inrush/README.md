> ⚠️ **UNTESTED** — This implementation has not been verified against physical hardware.
> Code is complete but has not been bench-tested. Verify behavior before relying on output.

# rf-bench-inrush

**GitHub:** https://github.com/jfrancis42/rf-bench-inrush

Inrush current capture using SPD3303X + SDS2000X. Enables the PSU output, captures the
current transient via a sense resistor, and computes peak inrush current, duration above
10% of peak, and I²t. Repeat mode overlays N captures for statistical analysis.

## Hardware

| Instrument | Role |
|-----------|------|
| Siglent SPD3303X-E (10.1.1.56) | PSU — DUT supply |
| Siglent SDS2354X Plus (10.1.1.58) | Scope — sense resistor voltage capture |
| Sense resistor (e.g. 0.1 Ω, 1%) | Current sensing element |

**Wiring:** Insert the sense resistor in series with the DUT supply return path.
Connect scope CH1 across the resistor (+ toward supply, − toward GND/DUT).

## Usage

```
python inrush.py --voltage V [options]
```

`--voltage` is required.

### Options

| Flag | Default | Description |
|------|---------|-------------|
| `--psu HOST` | 10.1.1.56 | SPD3303X IP |
| `--scope HOST` | 10.1.1.58 | SDS2000X IP |
| `--channel N` | 1 | Scope channel |
| `--sense-ohm R` | 0.1 | Sense resistor (Ω) |
| `--voltage V` | required | DUT supply voltage |
| `--captures N` | 1 | Number of captures (overlaid) |
| `--plot FILE` | timestamped | Output PNG |

### Examples

```bash
# Single inrush capture at 5V
python inrush.py --voltage 5.0

# 10 captures overlaid, 10 mΩ shunt, 12V supply
python inrush.py --voltage 12.0 --sense-ohm 0.01 --captures 10 --plot inrush12v.png
```

## Metrics

| Metric | Description |
|--------|-------------|
| Peak current (A) | Maximum instantaneous inrush |
| Duration (ms) | Time current stays above 10% of peak |
| I²t (A²·ms) | Thermal stress integral for fuse/protection coordination |

## Notes

- PSU current limit is set to 5 A to allow full inrush capture; normal steady-state
  limit is NOT enforced during measurement.
- 2-second delay between captures allows DUT capacitors to discharge fully.
- Trigger threshold = `sense_ohm × 0.01` A (≈ 10 mA) — adjust `--sense-ohm` if the
  scope triggers prematurely on noise.
