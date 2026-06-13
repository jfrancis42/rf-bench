# SCPI Power Monitor

ESP32-based power monitor using INA219 voltage/current sensor with SCPI control over TCP/IP.

## Hardware

**Required:**
- ESP32 dev board (any variant)
- INA219 I2C voltage/current sensor module
- WiFi network

**INA219 Module:**
- **I2C address:** 0x40 (default, configurable to 0x41-0x4F via solder jumpers)
- **Bus voltage range:** 0-26V (configurable 16V or 32V mode)
- **Current range:** ±3.2A with 0.1Ω shunt resistor (default)
- **Resolution:** 0.8mA current, 4mV voltage
- **Power supply:** 3.3V or 5V (module typically has onboard regulator)

## Wiring

### ESP32 ↔ INA219 (I2C)
```
INA219    ESP32
------    -----
VCC   →   3.3V (or 5V if module requires it)
GND   →   GND
SDA   →   GPIO 21 (I2C data)
SCL   →   GPIO 22 (I2C clock)
```

### INA219 Power Path
```
Power Supply (+) → INA219 VIN+ → INA219 VIN- → Load (+)
Load (−) / GND   → INA219 GND
```

**Current flows:** Power supply positive → VIN+ → (through 0.1Ω shunt) → VIN- → load positive. Load negative returns to power supply ground.

**Voltage sensing:** INA219 measures voltage at VIN+ (bus voltage) and voltage drop across internal shunt resistor (shunt voltage). Current calculated via Ohm's law (I = V_shunt / R_shunt).

## Shunt Resistor Impact

The INA219 module has a built-in 0.1Ω shunt resistor (typical). This determines current range and resolution:

| Shunt Resistor | Max Current | Resolution | Power Dissipation @ Max |
|---------------|-------------|------------|------------------------|
| 0.1Ω (default) | ±3.2A | 0.8mA | 1.024W |
| 0.01Ω (high current) | ±32A | 8mA | 10.24W |
| 1.0Ω (low current) | ±320mA | 80µA | 102mW |

**Trade-off:** Lower resistance → higher max current, lower resolution, higher power dissipation. Higher resistance → lower max current, higher resolution, lower dissipation.

Most INA219 modules ship with 0.1Ω shunt soldered in. For different ranges, replace the shunt resistor (typically an SMD 2512 or through-hole wirewound resistor) and update the calibration in firmware (`ina219.setCalibration_32V_2A()` → adjust parameters or use `setCalibration_16V_400mA()` for high-precision low-current measurements).

## Calibration Modes

The Adafruit INA219 library provides several pre-calibrated modes:

| Mode | Bus Voltage | Max Current | Shunt | Use Case |
|------|------------|-------------|-------|----------|
| `setCalibration_32V_2A()` | 0-32V | 0-2A | 0.1Ω | General purpose (default) |
| `setCalibration_32V_1A()` | 0-32V | 0-1A | 0.1Ω | Lower current, higher resolution |
| `setCalibration_16V_400mA()` | 0-16V | 0-400mA | 0.1Ω | Precision low-current (USB, battery) |

**Firmware default:** `setCalibration_32V_2A()` — suitable for most bench power supply monitoring (0-32V, 0-2A).

**To change:** Edit line in `setup()`:
```cpp
ina219.setCalibration_32V_2A();  // Change to _16V_400mA() for low-current precision
```

## SCPI Commands

### Common Commands
- `*IDN?` — identification (returns "N0GQ,ESP32-SCPI-Power,1.0,2026")
- `*RST` — reset energy accumulator to zero
- `SYST:ERR?` — system error query (returns sensor status)

### Measurement Commands
- `MEAS:VOLT?` — query bus voltage (V)
- `MEAS:CURR?` — query current (mA)
- `MEAS:POW?` — query power (mW)
- `MEAS:ALL?` — query all as CSV: "V,mA,mW"
- `MEAS:ENER?` — query accumulated energy (mWh)
- `MEAS:ENER:RES` — reset energy accumulator to zero
- `MEAS:SHUNT?` — query shunt voltage (mV) — diagnostic only

### Configuration Commands
- `MEAS:SAMP:RATE,<ms>` — set sampling interval (10-10000ms, default 100ms)
- `MEAS:SAMP:RATE?` — query sampling rate

**Short forms allowed:** `MEAS:VOLT?` = `MEASURE:VOLTAGE?`

**Command termination:** Commands terminated by `\n`, `\r`, or `;`

## Use Cases

### Battery Discharge Monitoring
Monitor battery voltage, current, and energy consumed over time. Characterize battery capacity (mAh) and discharge curves.

```python
import socket
import time

def scpi_query(ip, cmd):
    s = socket.socket()
    s.connect((ip, 5025))
    s.sendall((cmd + '\n').encode())
    resp = s.recv(1024).decode().strip()
    s.close()
    return resp

# Reset energy counter
scpi_query('192.168.1.42', 'MEAS:ENER:RES')

# Monitor discharge every 10 seconds
while True:
    csv = scpi_query('192.168.1.42', 'MEAS:ALL?')
    v, ma, mw = csv.split(',')
    energy_mwh = scpi_query('192.168.1.42', 'MEAS:ENER?')
    print(f"{v}V, {ma}mA, {mw}mW, {energy_mwh}mWh consumed")
    time.sleep(10)
```

### DUT Power Consumption
Measure power consumption of a device under test (DUT) during different operating modes (idle, active, sleep).

```python
# Set fast sampling for transient capture
scpi_query('192.168.1.42', 'MEAS:SAMP:RATE,10')  # 10ms = 100 Hz

# Reset energy before test
scpi_query('192.168.1.42', 'MEAS:ENER:RES')

# Trigger DUT activity (external control)
# ...

# Measure total energy consumed
energy_mwh = float(scpi_query('192.168.1.42', 'MEAS:ENER?'))
print(f"Energy consumed: {energy_mwh} mWh = {energy_mwh/1000:.3f} Wh")
```

### Efficiency Testing
Measure input and output power simultaneously with two INA219 modules (one on input, one on output). Calculate efficiency.

```python
# Two ESP32+INA219 units at different I2C addresses
input_ip = '192.168.1.42'   # Input side
output_ip = '192.168.1.43'  # Output side

input_mw = float(scpi_query(input_ip, 'MEAS:POW?'))
output_mw = float(scpi_query(output_ip, 'MEAS:POW?'))

efficiency = (output_mw / input_mw) * 100 if input_mw > 0 else 0
print(f"Efficiency: {efficiency:.2f}% ({input_mw}mW in, {output_mw}mW out)")
```

### USB Power Profiling
Insert INA219 inline with USB cable (cut VCC, connect via INA219 VIN+/VIN-). Monitor USB device power draw over time.

**Note:** USB 2.0 spec is 5V ±5% (4.75-5.25V), max 500mA. USB 3.0 is 900mA. INA219 0.1Ω shunt has 10mV drop at 100mA — negligible for most devices but may affect sensitive high-current devices (use 0.01Ω shunt for <1mV drop).

### Solar Panel / Charger Monitoring
Monitor solar panel output voltage, current, and energy generation over time. Track daily energy production.

## Installation

1. Install Arduino IDE
2. Install ESP32 board support: File → Preferences → Additional Board Manager URLs: `https://dl.espressif.com/dl/package_esp32_index.json`
3. Tools → Board → Boards Manager → Search "ESP32" → Install
4. Install Adafruit INA219 library: Tools → Manage Libraries → Search "Adafruit INA219" → Install
   - Also installs dependencies: Adafruit BusIO
5. Edit WiFi credentials in `scpi-power.ino` (lines 18-19)
6. Tools → Board → ESP32 Dev Module
7. Tools → Port → (select USB serial port)
8. Upload sketch

## Testing

Open Serial Monitor (115200 baud) to see boot messages:

```
SCPI Power Monitor
==================
I2C: SDA=21, SCL=22
INA219: Found at 0x40
INA219: Calibrated for 32V, 2A range (0.1Ω shunt)
Connecting to YourSSID.... connected!
IP address: 192.168.1.42
SCPI port: 5025

Ready for SCPI commands
Power monitoring active
```

If "ERROR: INA219 not found!" appears, check wiring and I2C address (default 0x40).

**Test via telnet:**
```bash
telnet 192.168.1.42 5025
*IDN?
# returns: N0GQ,ESP32-SCPI-Power,1.0,2026

MEAS:ALL?
# returns: 5.0234,123.45,620.67
#          (5.02V, 123.45mA, 620.67mW)

MEAS:ENER?
# returns: 12.345678
#          (12.35 mWh accumulated)
```

**Python test:**
```python
import socket

def scpi_query(ip, cmd):
    s = socket.socket()
    s.connect((ip, 5025))
    s.sendall((cmd + '\n').encode())
    resp = s.recv(1024).decode().strip()
    s.close()
    return resp

print(scpi_query('192.168.1.42', '*IDN?'))
print(scpi_query('192.168.1.42', 'MEAS:ALL?'))
```

## Troubleshooting

### "INA219 not found" error

1. **Check wiring:** SDA → GPIO 21, SCL → GPIO 22, VCC → 3.3V, GND → GND
2. **Check I2C address:** Default is 0x40. If module has jumpers/switches for address, ensure they match firmware (0x40).
3. **Check module power:** INA219 module should have power LED lit.
4. **I2C bus scan:** Use an I2C scanner sketch to verify module appears on bus.

### Zero current reading despite load

1. **Check power path wiring:** Current must flow VIN+ → VIN- (through shunt). If wired backwards, current reads negative.
2. **Load too small:** 0.1Ω shunt with 32V_2A calibration has ~0.8mA resolution. Currents <1mA may read as zero. Use `setCalibration_16V_400mA()` for sub-milliamp precision.
3. **Shunt resistor damaged:** Overload can vaporize shunt. Check with multimeter (should read ~0.1Ω between VIN+ and VIN-).

### Incorrect voltage reading

1. **Bus voltage vs load voltage:** INA219 measures voltage at VIN+ relative to GND. If load is not grounded to INA219 GND, reading will be wrong.
2. **Voltage drop across shunt:** Load voltage = bus voltage − shunt voltage. At 1A through 0.1Ω shunt, voltage drop is 100mV. For precision, use shunt voltage reading: `MEAS:SHUNT?` returns drop in mV.

### Energy accumulator drifts or resets

1. **millis() overflow:** ESP32 `millis()` overflows after 49.7 days. Energy integration resets at overflow. For long-term monitoring, query and log energy periodically (e.g., hourly).
2. **Sampling rate too low:** Default 100ms. If power varies rapidly, use faster sampling: `MEAS:SAMP:RATE,10` (10ms = 100 Hz).
3. **ESP32 reboot:** Energy accumulator is RAM-based, lost on reboot. For persistence, periodically log to external storage (SD card, SPIFFS, or via SCPI to logging host).

## Accuracy and Limitations

**INA219 Specifications:**
- Bus voltage accuracy: ±4mV (±0.012% at 32V)
- Current accuracy: ±0.5% typical (depends on shunt resistor tolerance)
- Power accuracy: Voltage × Current error (~0.5-1%)

**Energy integration accuracy:**
- Limited by sampling rate (default 100ms) and millis() resolution (1ms)
- For constant loads, accuracy is excellent (±1%)
- For rapidly varying loads, use faster sampling (10ms minimum)

**Maximum current:**
- With 0.1Ω shunt: 3.2A absolute max (limited by INA219 ADC range)
- Beyond 3.2A, readings saturate — replace with 0.01Ω shunt for up to 32A

**Shunt power dissipation:**
- 0.1Ω shunt at 2A: P = I²R = 4 × 0.1 = 0.4W
- At 3.2A: P = 10.24 × 0.1 = 1.024W (shunt gets hot!)
- Most INA219 modules use SMD 2512 shunt (1W rating) — stays within spec at 3.2A but runs warm

## Advanced Configuration

### Changing I2C Address

INA219 modules typically have solder jumpers labeled A0, A1. Bridging these changes I2C address:

| A1 | A0 | Address |
|----|----|---------|
| 0  | 0  | 0x40 (default) |
| 0  | 1  | 0x41 |
| 1  | 0  | 0x44 |
| 1  | 1  | 0x45 |

To use non-default address, edit firmware line:
```cpp
const uint8_t ina219_address = 0x41;  // Change from 0x40
```

### Replacing Shunt Resistor

For higher current (>3.2A) or higher resolution (<0.8mA), replace the shunt resistor:

1. Identify shunt on INA219 module (usually a large SMD resistor between VIN+ and VIN-, or through-hole wirewound)
2. Desolder and replace with desired value (0.01Ω for high current, 1.0Ω for precision low current)
3. Update calibration in firmware:
   - For 0.01Ω shunt (0-32A range): use custom calibration (see Adafruit INA219 library docs)
   - For 1.0Ω shunt (0-320mA, high resolution): use `setCalibration_16V_400mA()` and adjust scaling

**Warning:** Shunt resistor must be rated for power dissipation. A 0.01Ω / 2W shunt can handle √(2 / 0.01) = 14.1A before exceeding 2W. For 32A, use a 5W+ shunt.

## Related Projects

- `~/rf-bench/drivers/yertai/` — Yertai ET5406A+ DC electronic load driver
- `~/rf-bench/projects/power/` — PSU, battery, and power-related test projects
- `~/govt-data/` — REST API reference for structuring networked embedded services
- `~/rf-bench/projects/esp32/scpi-relay/` — Relay controller sibling project
- `~/rf-bench/projects/esp32/scpi-gps/` — GPS receiver sibling project
