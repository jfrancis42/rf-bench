> ⚠️ **UNTESTED** — This implementation has not been verified against physical hardware.
> Code is complete but has not been bench-tested. Verify behavior before relying on output.

# rf-bench-dmm-tcr

**GitHub:** https://github.com/jfrancis42/rf-bench-dmm-tcr

Temperature Coefficient of Resistance (TCR) meter using the SDM3045X. Alternates
between resistance measurements and temperature readings, logs to CSV, fits a linear
TC (ppm/°C), and optionally plots R deviation vs. temperature.

## Hardware

| Instrument | Role |
|-----------|------|
| Siglent SDM3045X (10.1.1.63) | 4.5-digit DMM — resistance (2-wire or 4-wire) |
| Type K thermocouple | Temperature sensor (manual entry or SDM3055/3065X) |

**Important:** The SDM3045X does not support thermocouple/temperature measurement.
This script attempts the SCPI temperature command; if it fails, it falls back to
prompting you to enter the temperature manually. For fully automatic TCR logging,
use an SDM3055 or SDM3065X.

## Usage

```
python dmm_tcr.py [options]
```

### Options

| Flag | Default | Description |
|------|---------|-------------|
| `--dmm HOST` | 10.1.1.63 | DMM IP address |
| `--mode 2wire\|4wire` | 2wire | Resistance mode |
| `--interval S` | 2 | Seconds between sample pairs |
| `--duration S` | 3600 | Total run time (seconds) |
| `--log FILE` | — | CSV log path |
| `--plot` | off | Save R-vs-T PNG when run ends |

### Examples

```bash
# Quick 10-minute TCR run with 4-wire measurement
python dmm_tcr.py --mode 4wire --duration 600 --plot

# Long soak with CSV log
python dmm_tcr.py --duration 3600 --interval 5 --log tcr_run.csv --plot
```

## Output

Console shows each sample as measured:

```
  [   1]  T=+23.50 °C  R=9999.82 Ω  elapsed=0s
  [   2]  T=+25.12 °C  R=9999.95 Ω  elapsed=2s
```

Final TCR fit summary:

```
  TCR fit:
    R0   = 9999.82 Ω  @ T0 = 23.5 °C
    α    = +15.2 ppm/°C  (linear)
    RMS residual = 2.1 ppm
```

## CSV columns

`timestamp`, `elapsed_s`, `temperature_c`, `resistance_ohm`
