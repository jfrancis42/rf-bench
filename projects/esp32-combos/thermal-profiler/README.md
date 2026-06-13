# Thermal Profiler (ESP32 + DMM)

Multi-point temperature profiling combining scpi-temp (8-16 sensors) + scpi-heater (PID control) + SDM3045X (reference).

## Status: 🔨

## Hardware Requirements

1. **scpi-temp ESP32** — 8-16× DS18B20 temperature sensors in spatial array
2. **scpi-heater ESP32** — PID-controlled chamber heater
3. **Siglent SDM3045X** — Benchtop DMM with 4-wire RTD input (reference thermometer)
4. **Thermal chamber** — DIY enclosure with heater and insulation
5. **Reference thermometer** — Calibrated RTD probe connected to DMM

## Installation

```bash
pip install rf-bench-drivers-siglent requests matplotlib numpy
```

## Usage

### Basic 60°C Profile

```bash
./thermal_profile.py \
  --esp-temp 10.1.0.50 \
  --esp-heater 10.1.0.51 \
  --dmm 10.1.0.11 \
  --setpoint-c 60 \
  --duration-min 30 \
  --log-interval-sec 10
```

### Example: 16-Sensor Grid, 30-Minute Soak

```bash
./thermal_profile.py \
  --esp-temp 10.1.0.50 \
  --esp-heater 10.1.0.51 \
  --dmm 10.1.0.11 \
  --setpoint-c 85 \
  --duration-min 30 \
  --log-interval-sec 5 \
  --output reflow_profile_85C.csv
```

This will:
1. Set chamber heater to 85°C via PID control
2. Read all 16 DS18B20 sensors every 5 seconds
3. Read calibrated reference thermometer via DMM
4. Log all data to CSV
5. Wait for thermal equilibrium (all sensors within 1°C of setpoint for 5 min)
6. Generate heatmap showing spatial temperature distribution
7. Compute statistics: mean, std dev, min, max, range
8. Disable heater when complete

## Sensor Placement

For best results, arrange DS18B20 sensors in a **grid pattern** inside the chamber:

- **8 sensors**: 2×4 grid (2 rows, 4 columns)
- **9 sensors**: 3×3 grid
- **12 sensors**: 3×4 grid
- **16 sensors**: 4×4 grid

Place the **reference thermometer (DMM RTD)** in the **center** of the chamber for best accuracy.

Example 4×4 layout:
```
┌─────────────────────┐
│  S1  S2  S3  S4    │
│  S5  S6  S7  S8    │
│  S9 S10 S11 S12    │
│ S13 S14 S15 S16    │
│        REF          │
└─────────────────────┘
```

The script will automatically detect the number of sensors and generate an appropriate heatmap.

## Output

### CSV Format

Columns:
- `timestamp` — ISO 8601 timestamp
- `elapsed_sec` — Seconds since start
- `reference_c` — DMM reference temperature (°C)
- `sensor_XXXXXXXX` — Temperature from each DS18B20 (°C)

### Heatmap

Automatically generated PNG file showing:
- Spatial temperature distribution in chamber
- Color scale: blue (cold) → white (setpoint) → red (hot)
- Cell annotations with exact temperatures
- Summary statistics in title

## Use Cases

1. **DIY Thermal Chamber Uniformity Testing**
   - Verify temperature distribution across chamber volume
   - Identify hot/cold spots
   - Validate PID control performance

2. **PCB Reflow Profiling**
   - Map temperature gradients across board during reflow
   - Verify solder paste manufacturer's recommended profile
   - Optimize heater placement

3. **Component Temperature Characterization**
   - Profile DUTs at multiple points simultaneously
   - Measure thermal time constants
   - Validate thermal models

4. **Thermal Chamber Commissioning**
   - Verify chamber meets uniformity specs
   - Document performance for calibration records
   - Optimize insulation and airflow

## DS18B20 vs DMM Reference

| Parameter | DS18B20 | SDM3045X + RTD |
|-----------|---------|----------------|
| Accuracy | ±0.5°C | ±0.02°C (typical) |
| Resolution | 0.0625°C (12-bit) | 0.001°C |
| Cost | ~$1 each | ~$500 (DMM) + $50 (RTD) |
| Spatial coverage | 8-16 points | 1 point |
| Purpose | Uniformity mapping | Absolute reference |

The DMM provides a **calibrated reference** to validate the DS18B20 array. Typical workflow:
1. Use DMM to verify setpoint accuracy
2. Use DS18B20 array to map spatial distribution
3. Compute mean DS18B20 error vs DMM reference
4. Apply correction factor if needed

## Thermal Equilibrium Detection

The script automatically detects when the chamber reaches equilibrium:

**Criteria**: All sensors within **1°C** of setpoint for **5 minutes**.

When equilibrium is reached, the script prints `✓ EQUILIBRIUM` in the log output. This indicates:
- Spatial temperature distribution is stable
- Safe to extract statistics
- Heatmap represents steady-state condition

## Example Output

```
Connecting to DMM at 10.1.0.11...
  DMM: Siglent Technologies,SDM3045X,SDM3X5X4R1234,1.01.01.33R1

Discovering sensors on scpi-temp at http://10.1.0.50...
  Found 16 DS18B20 sensors:
    1. 28FF1234567890AB
    2. 28FF2345678901BC
    ...

Connecting to scpi-heater at http://10.1.0.51...
  Heater: scpi-heater v1.0.0

Heater setpoint: 60°C
Heater output: ON

Starting thermal profile:
  Setpoint: 60.0°C
  Duration: 30.0 min
  Log interval: 10.0 sec
  Output: thermal_profile_60C_20260612_143022.csv
  Sensors: 16

[  0.50 min] Mean: 24.31°C  Std: 0.456°C  Range: 1.375°C  Ref: 24.12°C  
[  0.67 min] Mean: 28.56°C  Std: 0.512°C  Range: 1.625°C  Ref: 28.34°C  
...
[ 15.83 min] Mean: 59.87°C  Std: 0.234°C  Range: 0.750°C  Ref: 59.92°C  ✓ EQUILIBRIUM
...
[ 30.00 min] Mean: 60.02°C  Std: 0.198°C  Range: 0.625°C  Ref: 60.01°C  ✓ EQUILIBRIUM

Profile complete. Data saved to thermal_profile_60C_20260612_143022.csv

Generating heatmap (grid: 4×4)...
Heatmap saved: thermal_profile_60C_20260612_143022.png

Disabling heater...
Done.
```

## Arguments

```
--esp-temp IP          IP address of scpi-temp ESP32 (required)
--esp-heater IP        IP address of scpi-heater ESP32 (required)
--dmm IP               IP address of SDM3045X DMM (required)
--setpoint-c TEMP      Target temperature in °C (required)
--duration-min MIN     Total profile duration in minutes (default: 30)
--log-interval-sec SEC Data logging interval in seconds (default: 10)
--output PATH          Output CSV file path (default: auto-generated)
```

## Notes

- Script automatically disables heater when complete or interrupted (Ctrl-C)
- DMM must be configured for 4-wire RTD measurement
- DS18B20 sensors must be on OneWire bus of scpi-temp ESP32
- Heater PID parameters should be tuned conservatively (see README)
- For best results, allow chamber to pre-heat and stabilize before profiling
- Reference thermometer should be positioned in center of chamber
- All timestamps are in local system time
