> ⚠️ **UNTESTED** — This implementation has not been verified against physical hardware.
> Code is complete but has not been bench-tested. Verify behavior before relying on output.

# rf-bench-dmm-sorter

**GitHub:** https://github.com/jfrancis42/rf-bench-dmm-sorter

Component bin sorter using the SDM3045X bench DMM. Reads resistance, capacitance, or diode
Vf in a continuous loop. After each stable reading, announces the nearest E12/E24 bin,
gives a pass/fail against a tolerance, sounds a system bell, and optionally logs to CSV.

Stability detection: a reading change >5% signals a new component (resets the buffer);
once 3 consecutive readings are within 0.1% of each other the component is declared stable.

## Hardware

| Instrument | Role |
|-----------|------|
| Siglent SDM3045X (10.1.1.63) | 4.5-digit bench DMM — resistance/capacitance/diode |

## Usage

```
python dmm_sorter.py [options]
```

### Options

| Flag | Default | Description |
|------|---------|-------------|
| `--dmm HOST` | 10.1.1.63 | SDM3045X IP address |
| `--mode resistance\|kelvin\|capacitance\|diode` | resistance | Measurement mode |
| `--series E12\|E24` | E12 | E-series for binning |
| `--tolerance PCT` | 5 | Pass/fail tolerance % |
| `--log FILE` | — | CSV log file |

### Examples

```bash
# Sort resistors by E12 value, 5% tolerance
python dmm_sorter.py --mode resistance

# Sort 1% resistors by E24 value, log to CSV
python dmm_sorter.py --mode resistance --series E24 --tolerance 1 --log resistors.csv

# Sort capacitors
python dmm_sorter.py --mode capacitance --series E12

# Kelvin (4-wire) for sub-ohm / contact resistance
python dmm_sorter.py --mode kelvin --tolerance 1

# Diode Vf sorting
python dmm_sorter.py --mode diode
```

## Output

Each stable reading prints a line:

```
  [   1]       4.712 kΩ  →  E12: 4.700 kΩ  error: +0.3%  PASS
  [   2]       9.87 kΩ   →  E12: 10.00 kΩ  error: -1.3%  PASS
```

## CSV log columns

`timestamp`, `component`, `mode`, `measured`, `nominal`, `error_pct`, `result`

## Notes

- SDM3045X does **not** support 4-wire (Kelvin) capacitance — kelvin mode only applies to resistance.
- Audio bell (`\a`) fires after each stable reading; disable in terminal preferences if unwanted.
- The sorter ignores OL (overload) readings and waits for a finite positive value.
