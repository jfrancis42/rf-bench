> ⚠️ **UNTESTED** — This implementation has not been verified against physical hardware.
> Code is complete but has not been bench-tested. Verify behavior before relying on output.

# rf-bench-stress-monitor

**GitHub:** https://github.com/jfrancis42/rf-bench-stress-monitor

Component stress monitor: applies a continuous DC bias via the SPD3303X and logs
a DMM measurement parameter over time. Primary use case is MLCC capacitance vs.
DC bias (DC bias effect), but also supports resistor drift under load, Zener voltage
stability, and diode Vf drift.

## Hardware

| Instrument | Role |
|-----------|------|
| Siglent SPD3303X-E (10.1.1.56) | PSU — constant bias voltage |
| Siglent SDM3045X (10.1.1.63) | 4.5-digit DMM — parameter logging |

## Usage

```
python stress_monitor.py --voltage V --mode MODE [options]
```

`--voltage` is required.

### Options

| Flag | Default | Description |
|------|---------|-------------|
| `--psu HOST` | 10.1.1.56 | SPD3303X IP |
| `--dmm HOST` | 10.1.1.63 | SDM3045X IP |
| `--mode capacitance\|resistance\|voltage\|diode` | capacitance | Measurement mode |
| `--voltage V` | required | Bias voltage |
| `--interval S` | 60 | Seconds between measurements |
| `--duration S` | 3600 | Total run time |
| `--threshold-pct PCT` | 20 | SMS alert drift threshold |
| `--log FILE` | — | CSV log path |
| `--plot` | off | Save drift plot PNG |

### Examples

```bash
# MLCC capacitance vs. 5V DC bias
python stress_monitor.py --mode capacitance --voltage 5.0 --interval 30 --plot

# Resistor drift under 3.3V
python stress_monitor.py --mode resistance --voltage 3.3 --duration 7200 --log drift.csv

# Zener voltage stability at 5.1V
python stress_monitor.py --mode voltage --voltage 5.1 --threshold-pct 2
```

## Output

Console shows each measurement with elapsed time and drift:

```
  [    1]      0s        102.45 nF  drift=+0.00%
  [    2]     60s        97.21 nF   drift=-5.10%
```

## Plot

Two subplots: measured value vs. time (top) and drift % from initial value (bottom).
File: `{prefix}_stress.png`.

## CSV columns

`timestamp`, `elapsed_s`, `voltage_v`, `measured`, `drift_pct`

## SMS alerts

Single alert per session when drift exceeds `--threshold-pct`.
Requires `~/Dropbox/build/creds/voipms-rest.txt`.
