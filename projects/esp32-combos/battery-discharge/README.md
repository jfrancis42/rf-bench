# ESP32 Battery Discharge Tester

Automated battery discharge test combining scpi-load (or ET5406A+ via rf_bench.yertai) with scpi-temp and scpi-adc for comprehensive cell characterization.

## Features

- Constant current discharge with programmable cutoff voltage
- Per-cell temperature monitoring (critical for lithium safety)
- Isolated voltage sensing via scpi-adc (when using ESP32 load)
- Real-time data logging to SQLite and CSV (1 Hz sampling)
- Capacity integration (mAh) and energy integration (Wh) using trapezoidal method
- Automatic termination on cutoff voltage or temperature limit
- Capacity curve plot generation (V vs mAh, T vs mAh)
- Multi-cell testing via scpi-mux (parallel discharge)

## Hardware

**Load Options:**
1. **scpi-load** (ESP32 MOSFET load): Low power (<50W), portable, cost-effective
2. **ET5406A+** (Yertai DC load): High power (200W), on greybox at 10.1.0.16, built-in voltage measurement

**Required Instruments:**
- **scpi-temp**: Per-cell temperature monitoring (one ESP32 per cell, essential for lithium safety)
- **scpi-adc**: Isolated voltage sensing (required for ESP32 load; not needed for ET5406A+ which has built-in voltage measurement)

**Optional:**
- **scpi-mux**: Multi-cell parallel testing (switch between cells for sequential monitoring)

## Installation

```bash
# For ET5406A+ load support (optional)
pip install rf-bench-drivers-yertai --break-system-packages

# For plotting support (optional but recommended)
pip install matplotlib --break-system-packages
```

No installation needed for ESP32 scpi-load option - uses direct SCPI commands over TCP.

## Usage

### ESP32 Load Example

Discharge 18650 lithium cell at 1A to 2.5V cutoff:

```bash
./battery_discharge.py --load-type esp32 \
  --esp-load 10.1.0.100 \
  --esp-temp 10.1.0.101 \
  --esp-adc 10.1.0.102 \
  --current-a 1.0 \
  --cutoff-v 2.5 \
  --temp-limit-c 50 \
  --output-dir ./18650_discharge_data
```

### ET5406A+ Load Example

Discharge NiMH cell at 0.5A to 1.0V using high-power load on greybox:

```bash
./battery_discharge.py --load-type et5406a \
  --et5406a-port /dev/ttyUSB0 \
  --esp-temp 10.1.0.101 \
  --current-a 0.5 \
  --cutoff-v 1.0 \
  --temp-limit-c 45
```

### Command-Line Options

```
--load-type {esp32|et5406a}  Load type (required)
--esp-load IP               ESP32 scpi-load IP address (required if load-type=esp32)
--et5406a-port PORT         ET5406A+ serial port (required if load-type=et5406a)
--esp-temp IP               ESP32 scpi-temp IP address (required)
--esp-adc IP                ESP32 scpi-adc IP address (required for esp32 load)
--current-a AMPS            Discharge current in amperes (required)
--cutoff-v VOLTS            Cutoff voltage in volts (required)
--temp-limit-c CELSIUS      Temperature limit in Celsius (optional)
--output-dir DIR            Output directory for data files (default: ./discharge_data)
```

## Use Cases

### Battery Capacity Verification
Test manufacturer-claimed capacity against measured discharge performance:
```bash
# Test "3000mAh" 18650 cell
./battery_discharge.py --load-type esp32 --esp-load 10.1.0.100 \
  --esp-temp 10.1.0.101 --esp-adc 10.1.0.102 \
  --current-a 0.5 --cutoff-v 2.5
# Compare measured capacity against 3000mAh claim
```

### Aging Studies
Track capacity degradation over charge/discharge cycles:
```bash
# Month 0
./battery_discharge.py ... --output-dir ./aging_study/month_0

# Month 3 (after 100 cycles)
./battery_discharge.py ... --output-dir ./aging_study/month_3

# Compare capacity_mah values from test_parameters table
```

### Matched-Pair Selection
Find cells with similar capacity for series/parallel packs:
```bash
# Test 10 cells sequentially
for i in {1..10}; do
  ./battery_discharge.py ... --output-dir ./cell_matching/cell_$i
done

# Sort by total_capacity_mah from each test's database
# Select cells within ±50mAh for matched pack
```

### Temperature Safety Validation
Verify thermal performance under load:
```bash
# High-rate discharge with temperature monitoring
./battery_discharge.py --load-type et5406a --et5406a-port /dev/ttyUSB0 \
  --esp-temp 10.1.0.101 \
  --current-a 5.0 --cutoff-v 2.5 --temp-limit-c 60

# Check temperature_c column in CSV - should stay well below limit
```

## Output Files

All files timestamped `YYYYMMDD_HHMMSS`:

- **`discharge_<timestamp>.db`**: SQLite database with two tables:
  - `discharge_log`: Per-sample data (timestamp, elapsed_s, voltage_v, current_a, temperature_c, capacity_mah, energy_wh)
  - `test_parameters`: Test configuration and final results (start_time, target_current_a, cutoff_voltage_v, temp_limit_c, end_time, end_reason, total_capacity_mah, total_energy_wh)

- **`discharge_<timestamp>.csv`**: Same data as `discharge_log` table, human-readable

- **`discharge_<timestamp>.png`**: Capacity curve plot (two subplots: voltage vs capacity, temperature vs capacity)

## Data Analysis

### Query Final Capacity

```bash
sqlite3 discharge_20260612_143022.db \
  "SELECT total_capacity_mah, total_energy_wh FROM test_parameters"
```

### Extract Voltage Curve

```bash
sqlite3 -csv discharge_20260612_143022.db \
  "SELECT capacity_mah, voltage_v FROM discharge_log ORDER BY elapsed_s" \
  > voltage_curve.csv
```

### Calculate Internal Resistance

```python
import sqlite3

conn = sqlite3.connect('discharge_20260612_143022.db')
c = conn.cursor()

# Get voltage at 10% and 90% capacity
c.execute('SELECT MAX(capacity_mah) FROM discharge_log')
total_capacity = c.fetchone()[0]

c.execute('SELECT voltage_v, current_a FROM discharge_log WHERE capacity_mah >= ? ORDER BY capacity_mah LIMIT 1',
          (total_capacity * 0.1,))
v_10, i_10 = c.fetchone()

c.execute('SELECT voltage_v, current_a FROM discharge_log WHERE capacity_mah >= ? ORDER BY capacity_mah LIMIT 1',
          (total_capacity * 0.9,))
v_90, i_90 = c.fetchone()

# Approximate internal resistance from voltage drop
r_int = (v_90 - v_10) / ((i_10 + i_90) / 2.0)
print(f"Approximate internal resistance: {r_int*1000:.1f} mΩ")
```

## Multi-Cell Testing

Use scpi-mux to switch between cells:

```python
# Pseudo-code for parallel testing
for cell_id in range(1, 5):
    mux.write(f"ROUTE:CLOSE (@{cell_id})")  # Select cell
    voltage = adc.query("MEAS:VOLT?")
    temperature = temp.query("MEAS:TEMP?")
    # Log data for this cell
    mux.write(f"ROUTE:OPEN (@{cell_id})")  # Deselect
```

Future enhancement: multi-cell mode in battery_discharge.py for automatic round-robin sampling.

## Safety Notes

**Critical for Lithium Cells:**
- Always set `--temp-limit-c` to prevent thermal runaway (recommend 50-60°C max)
- Use per-cell temperature monitoring - do not share one sensor across multiple cells
- Isolated voltage sensing (scpi-adc) prevents ground loops in multi-cell setups
- Never discharge below manufacturer's minimum voltage (typically 2.5V for lithium)
- Test in fireproof container with ventilation
- Monitor first discharge manually - do not leave unattended until validated

**For All Battery Types:**
- Verify cutoff voltage matches chemistry (1.0V NiMH, 2.5V lithium, 1.75V alkaline, etc.)
- Start with low current (0.2C) to validate setup before high-rate tests
- Check polarity before connecting load - reverse polarity can damage both battery and load
- Fuse or current-limit power supply when testing unknown cells

## Status

🔨 **Active Development**

## Future Enhancements

- Automated cycler (charge/discharge loop with configurable rest periods)
- Comparative aging tests (track internal resistance, capacity fade, voltage sag over cycle count)
- Multi-cell parallel mode (automatic round-robin sampling via scpi-mux)
- Real-time web dashboard (WebSocket streaming to browser plot)
- Charge curve characterization (CC-CV profiling)
- Pulse discharge testing (measure voltage sag under pulsed load)
- State-of-health (SOH) estimation (capacity fade + impedance trending)
