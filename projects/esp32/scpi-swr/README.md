# ESP32 SCPI SWR/Power Meter

Network-accessible RF power meter and SWR analyzer. Measures forward and reflected RF power via AD8307 logarithmic detectors (or diode detectors), calculates standing wave ratio (SWR), and exposes SCPI commands over TCP/IP port 5025.

## Features

- **Dual-channel RF power measurement** (forward + reflected)
- **SWR calculation** with automatic Γ (reflection coefficient) computation
- **Calibration table** with linear interpolation (up to 16 points per channel)
- **EEPROM persistence** — calibration survives ESP32 reboots
- **Selectable units** — dBm or watts
- **Standard SCPI interface** — compatible with LabVIEW, MATLAB, Python pyvisa
- **Raw ADC access** — query uncalibrated readings for manual analysis

## Hardware

### Bill of Materials

| Component | Quantity | Notes |
|-----------|----------|-------|
| ESP32 dev board | 1 | Any variant with WiFi (classic ESP32, S2, S3, C3) |
| AD8307 logarithmic detector | 2 | Analog Devices AD8307AN or module (Adafruit #4305) |
| Directional coupler | 1 | 50Ω, -20 to -30 dB coupling (e.g., Mini-Circuits ZFDC-20-5+) |
| Voltage divider resistors | 2 sets | For 5V → 3.3V level shifting (10kΩ + 20kΩ per channel) |
| 50Ω termination | 1-2 | For reflected port if using T-network instead of coupler |

**Alternative (simple, nonlinear):** Replace AD8307 with Schottky diode detectors (1N5711, BAT46) + 10nF capacitor + 100kΩ resistor. Requires more calibration points due to square-law region.

### Wiring

#### AD8307 Logarithmic Detectors

**Forward channel:**
```
RF FWD (from coupler) → AD8307 IN
AD8307 OUT → 10kΩ → GPIO 36 (ADC1_CH0)
                  └→ 20kΩ → GND  (voltage divider: 5V → 1.67V for ESP32 ADC)
AD8307 VCC → 5V (from ESP32 VIN or external PSU)
AD8307 GND → ESP32 GND
```

**Reflected channel:**
```
RF REF (from coupler) → AD8307 IN
AD8307 OUT → 10kΩ → GPIO 39 (ADC1_CH3)
                  └→ 20kΩ → GND
AD8307 VCC → 5V
AD8307 GND → GND
```

**Why voltage divider?** AD8307 output is 0-2.5V typical (can reach 3V at +17dBm input), but ESP32 ADC max is 3.3V. The 10kΩ/20kΩ divider (1:3 ratio) scales 5V down to 1.67V, protecting the ADC. Adjust calibration to compensate.

**Bypassing the divider:** If your AD8307 module already includes level shifting to 3.3V, connect OUT directly to GPIO 36/39.

#### Directional Coupler

The directional coupler sits inline between the transmitter and load (antenna):

```
TX OUT → Coupler INPUT → Coupler OUTPUT → Antenna/Load
         Coupler FWD → AD8307 #1 (forward power)
         Coupler REF → AD8307 #2 (reflected power)
```

**Coupling factor:** -20 dB is typical. At 100W (50 dBm) transmit power, FWD and REF ports see 1W (30 dBm). AD8307 handles up to +17 dBm safely; use an external attenuator (e.g., -10 dB pad) if measuring >5W.

**50Ω termination:** Some couplers require 50Ω termination on unused ports. Check datasheet.

#### Simple Diode Detector (Alternative)

If using Schottky diodes instead of AD8307:

```
RF FWD → 1N5711 anode
1N5711 cathode → 10nF → GPIO 36
                       └→ 100kΩ → GND  (DC return path)
```

**Limitation:** Diode detectors are nonlinear below ~0 dBm (square-law region). Calibration required at multiple power levels (e.g., -30, -20, -10, 0, +10 dBm).

### Power Supply

ESP32 runs from USB 5V (via VIN pin) or 3.3V LDO. AD8307 requires 4.5-5.5V (use ESP32 VIN or external 5V PSU).

**Current draw:** ESP32 WiFi active ~200 mA, AD8307 ~8 mA each. Total ~220 mA. Any USB port or 5V wall adapter suffices.

## SCPI Commands

### Common Commands

| Command | Response | Description |
|---------|----------|-------------|
| `*IDN?` | `N0GQ,ESP32-SCPI-SWR,1.0,2026` | Identification string |
| `*RST` | `OK` | Reset (clears calibration tables, does not erase EEPROM) |
| `SYST:ERR?` | `0,"No error"` | System error query |

### Power Measurement

| Command | Response | Description |
|---------|----------|-------------|
| `POW:FWD?` | `10.25` | Forward power (dBm or watts, depends on unit) |
| `POW:REF?` | `-5.30` | Reflected power |
| `SWR?` | `1.45` | Standing wave ratio (unitless, 1.0 = perfect match) |
| `POW:UNIT,DBM` | `OK` | Set power unit to dBm |
| `POW:UNIT,WATT` | `OK` | Set power unit to watts |
| `POW:UNIT?` | `DBM` | Query current power unit |

**Example (dBm):**
```
POW:UNIT,DBM
POW:FWD?  → 10.25 (dBm)
POW:REF?  → -10.50 (dBm)
SWR?      → 1.12
```

**Example (watts):**
```
POW:UNIT,WATT
POW:FWD?  → 10.5915 (watts = 10.25 dBm)
POW:REF?  → 0.0089 (watts = -10.50 dBm)
SWR?      → 1.12
```

### Calibration

| Command | Response | Description |
|---------|----------|-------------|
| `CAL:FWD,<raw>,<dbm>` | `OK (FWD cal now has 3 points)` | Add forward cal point (raw = ADC 0-4095, dbm = actual power) |
| `CAL:REF,<raw>,<dbm>` | `OK (REF cal now has 3 points)` | Add reflected cal point |
| `CAL:SAV` | `OK` | Save calibration to EEPROM (non-volatile storage) |
| `CAL:LOAD` | `OK (FWD 3 points, REF 3 points)` | Load calibration from EEPROM |
| `CAL:FWD:CLEAR` | `OK` | Clear forward calibration table |
| `CAL:REF:CLEAR` | `OK` | Clear reflected calibration table |
| `CAL:FWD:COUNT?` | `3` | Query number of forward cal points |
| `CAL:REF:COUNT?` | `3` | Query number of reflected cal points |

**Calibration procedure:**

1. Connect known power source (signal generator + calibrated attenuator, or power meter)
2. Set power to first level (e.g., -30 dBm)
3. Query raw ADC: `ADC:FWD?` → returns `512`
4. Add calibration point: `CAL:FWD,512,-30.0`
5. Repeat for multiple power levels (e.g., -30, -20, -10, 0, +10 dBm)
6. Save to EEPROM: `CAL:SAV`
7. Repeat for reflected channel using `CAL:REF,<raw>,<dbm>`

**How many points?** Minimum 2 (defines a line). Recommended 4-6 across expected power range. Maximum 16 per channel.

**Interpolation:** Firmware uses linear interpolation between calibration points. For nonlinear detectors (diodes), add more points in the nonlinear region.

### Raw ADC Access

| Command | Response | Description |
|---------|----------|-------------|
| `ADC:FWD?` | `2048` | Raw forward ADC value (0-4095, 12-bit) |
| `ADC:REF?` | `512` | Raw reflected ADC value |

Use for debugging, manual calibration, or verifying ADC sanity.

## Python Examples

### Basic Power Measurement

```python
import socket

def scpi_query(ip, port, cmd):
    s = socket.socket()
    s.connect((ip, port))
    s.sendall((cmd + '\n').encode())
    if '?' in cmd:
        resp = s.recv(1024).decode().strip()
        s.close()
        return resp
    s.close()

# Read forward power and SWR
fwd_dbm = float(scpi_query('192.168.1.42', 5025, 'POW:FWD?'))
ref_dbm = float(scpi_query('192.168.1.42', 5025, 'POW:REF?'))
swr = float(scpi_query('192.168.1.42', 5025, 'SWR?'))

print(f"Forward: {fwd_dbm:.2f} dBm")
print(f"Reflected: {ref_dbm:.2f} dBm")
print(f"SWR: {swr:.2f}:1")
```

### Calibration Script

```python
import socket

def scpi_send(ip, port, cmd):
    s = socket.socket()
    s.connect((ip, port))
    s.sendall((cmd + '\n').encode())
    resp = s.recv(1024).decode().strip()
    s.close()
    return resp

ip = '192.168.1.42'
port = 5025

# Clear existing calibration
scpi_send(ip, port, 'CAL:FWD:CLEAR')

# Add calibration points (example: AD8307 with -20 dB coupler)
# At 0 dBm transmit: coupler FWD port = -20 dBm
# AD8307 output = 25 mV/dB * (-20 + 84) = 1.6V → ADC ~2048 (after divider)
cal_points = [
    (512, -30),   # -30 dBm input → ADC 512
    (1024, -20),  # -20 dBm → ADC 1024
    (2048, -10),  # -10 dBm → ADC 2048
    (3072, 0),    # 0 dBm → ADC 3072
    (4000, 10)    # +10 dBm → ADC 4000 (near max)
]

for raw, dbm in cal_points:
    resp = scpi_send(ip, port, f'CAL:FWD,{raw},{dbm}')
    print(resp)

# Save to EEPROM
scpi_send(ip, port, 'CAL:SAV')
print("Calibration saved!")

# Verify
count = scpi_send(ip, port, 'CAL:FWD:COUNT?')
print(f"Calibration table has {count} points")
```

### Antenna Sweep (with SDG function generator)

```python
import socket
import time

def scpi_query(ip, port, cmd):
    s = socket.socket()
    s.connect((ip, port))
    s.sendall((cmd + '\n').encode())
    resp = s.recv(1024).decode().strip() if '?' in cmd else None
    s.close()
    return resp

swr_meter = ('192.168.1.42', 5025)
sig_gen = ('10.1.1.55', 5025)  # Siglent SDG1062X

# Set generator to 10 dBm
scpi_query(sig_gen[0], sig_gen[1], 'C1:OUTP LOAD,50')
scpi_query(sig_gen[0], sig_gen[1], 'C1:BSWV AMPL,1.0')  # 1V pk = +10 dBm into 50Ω
scpi_query(sig_gen[0], sig_gen[1], 'C1:OUTP ON')

# Sweep 14.0 - 14.35 MHz (20m band)
results = []
for freq_mhz in range(14000, 14350, 10):  # 10 kHz steps
    freq_hz = freq_mhz * 1000
    scpi_query(sig_gen[0], sig_gen[1], f'C1:BSWV FRQ,{freq_hz}')
    time.sleep(0.1)  # Settle time
    
    swr = float(scpi_query(swr_meter[0], swr_meter[1], 'SWR?'))
    results.append((freq_mhz / 1000.0, swr))
    print(f"{freq_mhz / 1000.0:.3f} MHz: SWR {swr:.2f}:1")

# Turn off generator
scpi_query(sig_gen[0], sig_gen[1], 'C1:OUTP OFF')

# Find minimum SWR
min_freq, min_swr = min(results, key=lambda x: x[1])
print(f"\nMinimum SWR: {min_swr:.2f}:1 at {min_freq:.3f} MHz")
```

## Calibration Theory

### AD8307 Transfer Function

The AD8307 is a logarithmic detector with a linear-in-dB output:

```
V_out = V_intercept + V_slope × P_in_dBm
```

Typical values:
- `V_slope` = 25 mV/dB (20 mV/dB to 30 mV/dB variation between chips)
- `V_intercept` = ~0.4V at -75 dBm (varies with frequency and chip)

**Example:** At -20 dBm input:
```
V_out = 0.4V + 25 mV/dB × (-20 dBm - (-75 dBm))
      = 0.4V + 25 mV/dB × 55 dB
      = 0.4V + 1.375V
      = 1.775V
```

After the 10kΩ/20kΩ voltage divider (3:1 reduction):
```
ADC input = 1.775V / 3 = 0.592V
ADC count = (0.592V / 3.3V) × 4095 = 734
```

**Why calibration is required:**
- Slope varies ±20% between chips
- Intercept varies with frequency (especially >100 MHz)
- Directional coupler coupling factor has ±0.5 dB tolerance
- Voltage divider resistor tolerance (±1% or ±5%)

**Calibration corrects all of these errors.**

### Interpolation Algorithm

Given N calibration points `(raw_i, dbm_i)` sorted by `raw_i`, firmware finds power at raw ADC value `x`:

1. **Below lowest point:** Extrapolate using first two points (linear slope)
2. **Between points:** Find `raw_i ≤ x < raw_{i+1}`, interpolate:
   ```
   dbm = dbm_i + (x - raw_i) × (dbm_{i+1} - dbm_i) / (raw_{i+1} - raw_i)
   ```
3. **Above highest point:** Extrapolate using last two points

**Why linear interpolation works:** AD8307 output is already linear-in-dB. Between calibration points, deviations are <0.2 dB (well within typical RF power measurement tolerance).

**For nonlinear detectors (diodes):** Use more calibration points (8-12) in the square-law region (<-10 dBm).

### SWR Calculation

SWR is derived from the reflection coefficient Γ:

```
Γ = sqrt(P_reflected / P_forward)
SWR = (1 + Γ) / (1 - Γ)
```

**Example:** 10W forward, 1W reflected:
```
Γ = sqrt(1 / 10) = 0.316
SWR = (1 + 0.316) / (1 - 0.316) = 1.316 / 0.684 = 1.92
```

**Edge cases handled by firmware:**
- `P_forward ≤ 0` → SWR = 99.9 (no power, invalid)
- `P_reflected < 0` → treat as 0 (noise floor)
- `P_reflected ≥ P_forward` → SWR = 99.9 (impossible, likely cal error)
- `Γ ≥ 1` → SWR = 99.9 (avoid divide by zero)
- `SWR < 1.0` → clamp to 1.0 (mathematical minimum)
- `SWR > 99.9` → clamp to 99.9 (practical upper limit)

## Use Cases

### Antenna Tuner Adjustment

1. Connect SWR meter inline between transmitter and antenna tuner
2. Key transmitter (CW or carrier, 5-10W)
3. Monitor `SWR?` in real-time (poll every 100ms)
4. Adjust tuner capacitors/inductors until SWR minimized (ideally <1.5:1)

**Automation:** Use Python script with antenna tuner SCPI commands (if tuner supports it) to sweep capacitance/inductance and find minimum SWR setting.

### Transmission Line Fault Detection

High SWR (>3:1) indicates:
- Open or short circuit (SWR → ∞)
- Damaged coax (water ingress, crushed cable)
- Antenna disconnected
- Wrong impedance load (e.g., 75Ω antenna on 50Ω line)

**Time-domain reflectometry (TDR):** Inject pulse, measure time delay to reflection, calculate fault distance:
```
Distance (meters) = (t_delay × c) / (2 × √ε_r)
```
where `c` = 3×10^8 m/s, `ε_r` = coax velocity factor (0.66 for RG-58, 0.84 for LMR-400).

This SWR meter measures CW power only. For TDR, use oscilloscope + pulse generator.

### Amplifier Output Monitoring

Monitor amplifier reflected power to detect load mismatch that could damage output transistors:

1. Set SWR alarm threshold (e.g., 2.0:1)
2. Poll `SWR?` at 10 Hz
3. If SWR > threshold, trigger relay to disconnect amplifier output or reduce drive

**Protection circuit:** Use ESP32 GPIO to control PTT relay. If `SWR? > 2.5`, set GPIO LOW → open PTT relay → kill transmit.

### Integration with Antenna Analyzers

Combine with a vector network analyzer (VNA) or scalar analyzer:

1. VNA measures complex impedance (Z = R + jX)
2. SWR meter measures SWR and power
3. Cross-verify: `SWR_theory = (Z_max / Z_min)` where Z is magnitude |Z|

**Practical advantage:** SWR meter works at full transmit power (100W+), VNA typically limited to low power (<0 dBm / 1 mW).

## Performance

### Accuracy

| Parameter | Typical | Notes |
|-----------|---------|-------|
| Power accuracy | ±0.5 dB | With 4-point calibration, over -20 to +10 dBm range |
| SWR accuracy | ±0.1 | At SWR 1.5:1 - 3.0:1 (most common range) |
| Frequency range | DC - 500 MHz | Limited by AD8307; use higher-freq log amp for VHF/UHF |
| Dynamic range | 60 dB | Depends on number of cal points; AD8307 capable of 92 dB |
| ADC noise | ~10 counts RMS | Equivalent to 0.1 dB at typical slope |

**Improving accuracy:**
- Use precision voltage divider resistors (0.1% tolerance)
- Add shielding to minimize RF pickup on ADC traces
- Calibrate at temperature extremes if using outdoors

### Speed

| Operation | Time |
|-----------|------|
| Single ADC read | ~1 ms (10 samples × 100µs each) |
| Power query | ~2 ms (both channels) |
| SWR query | ~3 ms (read both channels + calculate) |
| Maximum poll rate | ~300 Hz (limited by network latency, not firmware) |

**Streaming mode (future):** Could implement UDP broadcast of SWR at 100 Hz for real-time graphing.

## Troubleshooting

### "No calibration data" error

**Cause:** Calibration table is empty (0 points).

**Solution:**
1. Query raw ADC: `ADC:FWD?` (should return 0-4095)
2. If ADC reads 0 or 4095 constantly, check wiring (disconnected or shorted)
3. Add at least 2 calibration points: `CAL:FWD,<raw1>,<dbm1>` and `CAL:FWD,<raw2>,<dbm2>`
4. Save: `CAL:SAV`

### SWR always reads 99.9

**Cause:** Reflected power ≥ forward power, or forward power = 0.

**Possible issues:**
- Directional coupler installed backwards (swap FWD and REF)
- Load is open or short circuit (SWR → ∞)
- Calibration is incorrect (e.g., swapped FWD and REF cal tables)

**Debug:**
```
ADC:FWD?  → 2000
ADC:REF?  → 3500
```
If REF > FWD, coupler is backwards or wiring swapped.

### Power reading drifts with temperature

**Cause:** AD8307 has ~0.5 mV/°C tempco (equivalent to ~0.02 dB/°C).

**Solution:**
- Add temperature sensor (DS18B20 or BME280)
- Apply software temperature compensation: `dbm_corrected = dbm_raw + k × (T - T_cal)`
- Typical `k` = 0.02 dB/°C
- Re-calibrate at operating temperature

### ADC reads 0 or 4095 constantly

**Cause:** ADC input out of range.

**0 (0V):**
- AD8307 VCC not connected (chip not powered)
- AD8307 output disconnected
- Voltage divider resistor values wrong (too much attenuation)

**4095 (3.3V rail):**
- Voltage divider resistor missing (AD8307 OUT directly to ESP32 ADC, >3.3V)
- AD8307 output stuck high (chip damaged)

**Check:**
- Measure AD8307 OUT pin with multimeter (should be 0.5-2.5V at typical RF power)
- Measure ESP32 ADC pin (should be 0.2-1.5V after divider)

## Theory of Operation

### AD8307 Logarithmic Detector

The AD8307 contains:
1. **Limiting amplifier chain** — 8 cascaded gain stages, each contributing ±6 dB
2. **Successive detection** — each stage output is rectified and summed
3. **Output averaging** — R-C filter produces DC voltage proportional to log(input power)

**Why logarithmic?** RF power spans 6+ orders of magnitude (1 µW to 100W = 50 dB to 50 dBm). Linear ADCs can't capture this range. Log detectors compress the range: 100 dB input → 2.5V output (25 mV/dB slope).

**Phase insensitive:** AD8307 measures envelope power, not I/Q. Suitable for AM, FM, CW, SSB, all modulations.

### Directional Coupler

A directional coupler is a 4-port device:
- **Input port** — connects to transmitter
- **Output port** — connects to load (antenna)
- **Coupled port** — samples forward wave (FWD)
- **Isolated port** — samples reflected wave (REF)

**Coupling factor:** Ratio of input power to coupled power. -20 dB means 1% of power is sampled (100W → 1W at coupled port).

**Directivity:** Isolation between FWD and REF ports. Good couplers have >30 dB directivity (reflected power doesn't leak into FWD port).

**Why inline?** Measures actual power delivered to load, not just transmitter output. Accounts for transmission line loss.

### SWR and Reflection Coefficient

**Reflection coefficient Γ:**
```
Γ = (Z_load - Z_0) / (Z_load + Z_0)
```
where `Z_0` = characteristic impedance (50Ω for most systems).

**Example:** 75Ω load on 50Ω line:
```
Γ = (75 - 50) / (75 + 50) = 25 / 125 = 0.2
SWR = (1 + 0.2) / (1 - 0.2) = 1.2 / 0.8 = 1.5
```

**Power relationship:**
```
P_reflected = Γ² × P_forward
```

So `Γ = sqrt(P_reflected / P_forward)`, which is what the firmware calculates.

**Return loss (RL):**
```
RL = -20 × log10(Γ) dB
```

Example: SWR 1.5:1 → Γ = 0.2 → RL = 14 dB.

## Advanced: Temperature Compensation

For outdoor or high-power applications where temperature varies >20°C, add a temperature sensor and apply correction:

**Hardware:** Add DS18B20 1-Wire temperature sensor to GPIO 4.

**Firmware modification:**
```cpp
#include <OneWire.h>
#include <DallasTemperature.h>

OneWire oneWire(4);  // GPIO 4
DallasTemperature sensors(&oneWire);

void setup() {
  // ... existing setup ...
  sensors.begin();
}

float read_fwd_dbm() {
  sensors.requestTemperatures();
  float temp_c = sensors.getTempCByIndex(0);
  float dbm_raw = raw_to_dbm(fwd_cal, read_adc(fwd_adc_pin));
  
  // AD8307 tempco: ~0.02 dB/°C (typical)
  // Assume calibration at 25°C
  const float cal_temp = 25.0;
  const float tempco = 0.02;  // dB/°C
  float dbm_corrected = dbm_raw + tempco * (temp_c - cal_temp);
  
  return dbm_corrected;
}
```

**Typical improvement:** ±0.3 dB over 0-50°C (vs ±1 dB uncorrected).

## Future Enhancements

- **Alarm thresholds** — `SWR:ALARM:HIGH,<swr>` with GPIO output to kill PTT
- **Data logging** — Write SWR/power vs time to SD card or SPIFFS
- **Web UI** — HTTP server with real-time SWR bargraph (WebSocket push)
- **Multi-frequency cal** — Store separate calibration tables per frequency band
- **Harmonic measurement** — Add third detector for 2×f0 harmonic power
- **UDP streaming** — Broadcast SWR at 100 Hz for external graphing tools

## Related Projects

- **`~/rf-bench/projects/rf/antenna-analyzer/`** — Antenna impedance analyzer (VNA-based)
- **`~/rf-bench/projects/rf/amplifier-test/`** — Amplifier gain/linearity/efficiency measurement
- **`~/rf-bench/drivers/siglent/`** — Siglent SSA3032X Plus spectrum analyzer (power measurement via marker)
- **`~/rf-bench/projects/esp32/scpi-relay/`** — Relay controller (for automatic antenna switching)
- **`~/rf-bench/projects/esp32/scpi-gps/`** — GPS receiver (for position-tagged SWR logs)

## References

- [AD8307 Datasheet](https://www.analog.com/media/en/technical-documentation/data-sheets/AD8307.pdf) — Analog Devices
- [Directional Couplers: Basic Concepts](https://www.minicircuits.com/pages/s-parameters/directional_couplers_primer.pdf) — Mini-Circuits
- [SWR and Transmission Lines](https://www.arrl.org/transmission-lines) — ARRL Handbook
- [Linear Interpolation](https://en.wikipedia.org/wiki/Linear_interpolation) — Wikipedia

## License

Public domain. Use freely.

## Author

Jeff Francis / N0GQ — 2026-06-12
