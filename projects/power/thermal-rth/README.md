> ⚠️ **UNTESTED** — This implementation has not been verified against physical hardware.
> Code is complete but has not been bench-tested. Verify behavior before relying on output.

# rf-bench-thermal-rth

**GitHub:** https://github.com/jfrancis42/rf-bench-thermal-rth

Thermal resistance (θ, °C/W) meter using the SPD3303X PSU for controlled dissipation
and the SDM3045X DMM for temperature measurement. Steps through a list of power levels,
waits for thermal equilibrium at each point (rate < 0.1 °C/min), and computes θ.

## Hardware

| Instrument | Role |
|-----------|------|
| Siglent SPD3303X-E (10.1.1.56) | Triple-output PSU — controlled DUT power |
| Siglent SDM3045X (10.1.1.63) | 4.5-digit DMM — temperature measurement |
| Thermocouple (Type K) | Case temperature sensor on DUT |

**Important:** The SDM3045X does **not** support thermocouple input. This script
attempts the SCPI temperature command and falls back to prompting for manual
temperature entry. For automatic operation use an SDM3055 or SDM3065X.

## Usage

```
python thermal_rth.py --power-steps "0.5,1,2,5" [options]
```

### Options

| Flag | Default | Description |
|------|---------|-------------|
| `--psu HOST` | 10.1.1.56 | SPD3303X IP |
| `--dmm HOST` | 10.1.1.63 | SDM3045X IP |
| `--power-steps LIST` | "0.5,1,2,5" | Comma-separated watts |
| `--log FILE` | — | CSV log path |
| `--plot` | off | Save θ-vs-power PNG |

### Examples

```bash
# Transistor package θ_ja measurement
python thermal_rth.py --power-steps "0.5,1,2,5" --plot

# Heatsink θ_sa measurement, full log
python thermal_rth.py --power-steps "1,2,5,10,20" --log heatsink.csv --plot
```

## How it works

1. Measures ambient temperature at P=0.
2. For each power step: sets PSU voltage/current, measures actual P = V × I.
3. Polls temperature every 15 s until rate < 0.1 °C/min (max 10 min per step).
4. Records ΔT = T_case − T_ambient; θ = ΔT / P.
5. At the end: plots ΔT vs P and θ vs P with a linear fit.

## CSV columns

`timestamp`, `power_w`, `voltage_v`, `current_a`, `temperature_c`, `delta_t_c`, `theta_cw`
