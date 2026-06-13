# Battery Charger

**Status:** 🔨 In development

Multi-chemistry battery charger combining ESP32 SCPI instruments with bench PSU and DMM. Supports lead-acid, LiFePO4, Li-ion, and NiMH chemistries with temperature monitoring, relay safety gating, and comprehensive logging.

## Features

- **Multi-chemistry profiles:** Lead-acid (3-stage), LiFePO4 (CC/CV), Li-ion (CC/CV taper), NiMH (-ΔV detection)
- **Temperature monitoring:** DS18B20 via scpi-temp (0.5°C resolution)
- **Hardware safety:** Relay gates PSU output for emergency cutoff
- **Precision measurement:** scpi-adc or SDM3045X for terminal voltage, PSU for current
- **State machine:** Automatic transitions through charge phases
- **Logging:** SQLite + CSV with timestamp/voltage/current/temperature/Ah
- **Emergency cutoff:** Temperature and voltage anomaly detection

## Hardware Setup

### Required Equipment

1. **ESP32 #1 (scpi-temp):** DS18B20 temperature sensor on battery case
2. **ESP32 #2 (scpi-relay):** Relay module inline with PSU positive output
3. **ESP32 #3 (scpi-adc):** Terminal voltage monitoring (or use SDM3045X)
4. **SPD3303X PSU:** Charging power source (CH1)
5. **SDM3045X DMM:** Optional precision voltage/current monitoring

### Wiring Diagram

```
                     ┌─────────────┐
                     │  SPD3303X   │
                     │  PSU CH1    │
                     └──────┬──────┘
                            │ + output
                            │
                   ┌────────▼────────┐
                   │   ESP32 #2      │
                   │  scpi-relay     │
                   │  Relay NO→COM   │
                   └────────┬────────┘
                            │ gated +
                            │
                    ┌───────▼────────┐
                    │                │
                    │    BATTERY     │
                    │                │
                    └───────┬────────┘
                            │ -
                            │
                   ┌────────▼────────┐
                   │  PSU CH1 GND    │
                   └─────────────────┘

Temperature sensor (DS18B20):
   ESP32 #1 (scpi-temp) → sensor on battery case

Terminal voltage (option A):
   ESP32 #3 (scpi-adc) voltage divider across battery terminals

Terminal voltage (option B):
   SDM3045X DMM across battery terminals
```

**CRITICAL SAFETY:**
- Relay is normally open; closes only when charge is active
- PSU output is OFF until relay closes
- Temperature sensor must contact battery case (not just ambient air)
- Fuse PSU output at 2× maximum charge current
- **Multi-cell lithium REQUIRES a BMS** — this is a single-cell or BMS-protected pack charger

## Chemistry Profiles

| Chemistry   | Bulk V | Absorption V | Float V | Bulk C | End C  | Temp Range  | Notes                          |
|-------------|--------|--------------|---------|--------|--------|-------------|--------------------------------|
| Lead-acid   | 14.4V  | 14.4V        | 13.6V   | 0.2C   | 0.05C  | 0-50°C      | 3-stage: bulk→abs→float        |
| LiFePO4     | 3.65V  | 3.65V        | —       | 0.5C   | 0.05C  | 0-45°C      | CC/CV, no float                |
| Li-ion      | 4.2V   | 4.2V         | —       | 0.5C   | 0.05C  | 0-45°C      | CC/CV taper to 0.05C           |
| NiMH        | 1.5V   | —            | —       | 0.5C   | —      | 0-45°C      | CC with -ΔV termination (5 mV) |

**Voltages are per-cell.** Use `--cell-count` for series packs (e.g., 12V lead-acid = 6 cells).

## Usage Examples

### Lead-acid 12V 7Ah (6-cell) at 0.2C

```bash
./battery_charger.py \
  --esp-temp 10.1.0.100 \
  --esp-relay 10.1.0.101 \
  --esp-adc 10.1.0.102 \
  --psu 10.1.0.50 \
  --dmm 10.1.0.51 \
  --chemistry lead-acid \
  --capacity-ah 7.0 \
  --charge-rate-c 0.2 \
  --cell-count 6
```

**Phases:**
1. **Bulk:** 1.4A CC until 14.4V (typ. 5-8 hours to 80% SoC)
2. **Absorption:** 14.4V CV until current drops to 0.35A (0.05C)
3. **Float:** 13.6V maintenance indefinitely (until user stops)

### LiFePO4 3.2V 10Ah (1-cell) at 0.5C

```bash
./battery_charger.py \
  --esp-temp 10.1.0.100 \
  --esp-relay 10.1.0.101 \
  --esp-adc 10.1.0.102 \
  --psu 10.1.0.50 \
  --dmm 10.1.0.51 \
  --chemistry lifepo4 \
  --capacity-ah 10.0 \
  --charge-rate-c 0.5 \
  --cell-count 1
```

**Phases:**
1. **Bulk:** 5.0A CC until 3.65V (typ. 1.5-2 hours)
2. **Taper:** 3.65V CV until current drops to 0.5A (0.05C)
3. **Complete:** Relay opens, charge done

### Li-ion 3.7V 2600mAh (18650 cell) at 0.5C

```bash
./battery_charger.py \
  --esp-temp 10.1.0.100 \
  --esp-relay 10.1.0.101 \
  --esp-adc 10.1.0.102 \
  --psu 10.1.0.50 \
  --dmm 10.1.0.51 \
  --chemistry li-ion \
  --capacity-ah 2.6 \
  --charge-rate-c 0.5 \
  --cell-count 1
```

**Phases:**
1. **Bulk:** 1.3A CC until 4.2V (typ. 1.5-2 hours)
2. **Taper:** 4.2V CV until current drops to 0.13A (0.05C)
3. **Complete:** Relay opens, charge done

### NiMH 1.2V 2000mAh (AA cell) at 0.5C

```bash
./battery_charger.py \
  --esp-temp 10.1.0.100 \
  --esp-relay 10.1.0.101 \
  --esp-adc 10.1.0.102 \
  --psu 10.1.0.50 \
  --dmm 10.1.0.51 \
  --chemistry nimh \
  --capacity-ah 2.0 \
  --charge-rate-c 0.5 \
  --cell-count 1
```

**Phases:**
1. **Bulk:** 1.0A CC, monitoring for -ΔV (voltage drop ≥5 mV after peak)
2. **Complete:** When -ΔV detected (typ. 1.5-2 hours), relay opens

**NiMH caveat:** -ΔV detection requires thermal mass (AA/AAA cells work well; sub-C may need higher -ΔV threshold).

## Voltage Measurement Options

**Option A (default):** scpi-adc ESP32 with voltage divider
- Fast (no VISA overhead)
- Requires calibration of divider resistors
- Adequate for most chemistries (±10 mV accuracy)

**Option B:** SDM3045X DMM
- High precision (6.5 digits)
- Use `--use-dmm-voltage` flag
- Recommended for Li-ion (tight 4.2V tolerance)

Current is always measured from PSU (MEAS:CURR? on SPD3303X).

## Safety Features

### Temperature Monitoring
- DS18B20 sensor on battery case (not ambient air)
- 0.5°C resolution
- Cutoff if outside chemistry-specific range (e.g., 0-45°C for lithium)

### Voltage Limits
- Automatic cutoff if voltage exceeds 110% of absorption target
- Protects against sensor failure or PSU overshoot

### Relay Gating
- Relay is normally open (PSU disconnected)
- Closes only when charge is active
- Opens immediately on any error or completion
- Provides hardware-level cutoff independent of software

### Multi-cell Lithium Warning
**DO NOT use this charger for unprotected multi-cell lithium packs.** Cell balancing is required; use a BMS or balance charger. This charger is safe for:
- Single-cell lithium (1S)
- BMS-protected lithium packs (BMS handles balancing)
- Non-lithium chemistries (lead-acid, NiMH)

## Logging

Two output formats per charge session:

1. **SQLite:** `battery_charge_YYYYMMDD_HHMMSS.db`
   - Table: `charge_log (timestamp, state, voltage_v, current_a, temp_c, ah_charged)`
   - Query examples:
     ```sql
     -- Plot voltage vs time
     SELECT timestamp, voltage_v FROM charge_log;
     
     -- Find peak current
     SELECT MAX(current_a) FROM charge_log;
     
     -- Average temperature
     SELECT AVG(temp_c) FROM charge_log WHERE state = 'bulk';
     ```

2. **CSV:** `battery_charge_YYYYMMDD_HHMMSS.csv`
   - Same columns, easily imported to Excel/MATLAB/Python
   - Use for plotting or further analysis

## Troubleshooting

### "Voltage exceeds safe limit" immediately on start
- Check wiring polarity
- Verify voltage divider calibration (if using scpi-adc)
- Try `--use-dmm-voltage` to rule out ADC issue

### "Temperature exceeds maximum" in normal conditions
- Ensure DS18B20 is on battery case, not air
- Check ambient temperature (charging lithium >45°C is unsafe)
- Verify scpi-temp sensor ID (use `*IDN?` query)

### Current never drops in absorption/taper phase
- Battery may be sulfated (lead-acid) or degraded (lithium)
- Check PSU current limit is set correctly
- Verify PSU is in CV mode (not stuck in CC)

### NiMH charge never completes
- -ΔV detection requires cooling after peak; may take 5-10 minutes
- Try larger `delta_v_mv` (10 mV instead of 5 mV)
- Ensure battery is not pre-heated (warm batteries show weak -ΔV)

### Relay doesn't close
- Check scpi-relay wiring (NO vs NC terminals)
- Verify relay logic (ROUT:OPEN closes NO relay, ROUT:CLOS opens it)
- Test relay manually: `echo "ROUT:OPEN (@1)" | nc 10.1.0.101 5025`

## Dependencies

```bash
pip install pyvisa pyvisa-py
```

## See Also

- **scpi-temp:** `~/Dropbox/build/rf-bench/projects/esp32/scpi-temp/`
- **scpi-relay:** `~/Dropbox/build/rf-bench/projects/esp32/scpi-relay/`
- **scpi-adc:** `~/Dropbox/build/rf-bench/projects/esp32/scpi-adc/`
- **SPD3303X driver:** `~/Dropbox/build/rf-bench/drivers/siglent-spd3303x/`
- **SDM3045X driver:** `~/Dropbox/build/rf-bench/drivers/siglent-sdm3045x/`

## Future Enhancements

- **scpi-mux integration:** Parallel charging of multiple batteries with individual monitoring
- **Web dashboard:** Real-time graphs of V/I/T via WebSocket
- **Adaptive charge rate:** Reduce current if temperature rises >40°C
- **Battery health estimation:** Track internal resistance and capacity fade over multiple cycles
- **Multi-cell balancing:** Active balancing via scpi-relay array (bypass resistors)
