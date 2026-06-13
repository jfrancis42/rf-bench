# ESP32 SCPI Electronic Load

Network-controlled programmable DC electronic load with four operating modes: constant current (CC), constant power (CP), constant resistance (CR), and constant voltage (CV). Uses MOSFET-based design with INA219 voltage/current sensing and ESP32 DAC for gate control.

## Features

- **Four load modes**: CC, CP, CR, CV
- **SCPI interface** over WiFi (port 5025)
- **Voltage range**: 0-26V (INA219 bus voltage limit)
- **Current range**: 0-3.2A (with standard 0.1Ω INA219 shunt)
- **Power dissipation**: Limited by MOSFET heatsinking (typically 10-50W)
- **PID control**: Fast-responding feedback loop (100 Hz update rate)
- **Real-time measurements**: Voltage, current, power
- **Network control**: Standard SCPI commands compatible with test automation

## Hardware Requirements

### Components

1. **ESP32 dev board** — any variant with DAC (classic ESP32, ESP32-S2, ESP32-S3)
2. **INA219 current sensor module** — 0.1Ω shunt, I2C interface
3. **N-channel power MOSFET** — IRF540N (100V, 33A) or similar logic-level type
4. **Op-amp** (optional but recommended) — LM358, TL072, or similar rail-to-rail op-amp for gate drive scaling
5. **Heatsink** — TO-220 heatsink rated for expected power dissipation
6. **External PSU** — 5-12V to power op-amp (if used); ESP32 runs on USB power

### Wiring

#### INA219 to ESP32
```
INA219 VCC  → ESP32 3.3V
INA219 GND  → ESP32 GND
INA219 SDA  → ESP32 GPIO 21
INA219 SCL  → ESP32 GPIO 22
```

#### INA219 Power Path (load sensing)
```
DUT positive (+) → INA219 VIN+
INA219 VIN-      → MOSFET drain (D)
MOSFET source (S) → 0.1Ω sense resistor → GND
DUT negative (−)  → GND
```

The INA219 measures voltage at VIN+ (relative to GND) and current through the shunt between VIN+ and VIN-.

#### MOSFET Gate Drive

**Simple direct drive (no op-amp):**
```
ESP32 GPIO 25 (DAC1, 0-3.3V) → MOSFET gate (G)
MOSFET source (S) → GND (via 10kΩ pull-down resistor)
```

This works with logic-level MOSFETs (Vgs(th) < 3V), but limited current capability.

**Op-amp voltage follower (recommended for higher gate voltage):**
```
ESP32 GPIO 25 (DAC1) → Op-amp non-inverting input (+)
Op-amp inverting input (−) → Op-amp output (feedback)
Op-amp output → MOSFET gate
Op-amp V+ → 12V external PSU
Op-amp V− → GND
MOSFET gate → 10kΩ pull-down resistor → GND
```

This buffers the DAC output and provides higher gate drive voltage (0-12V) for standard MOSFETs.

**Op-amp gain stage (for very high gate voltage or current):**
```
ESP32 GPIO 25 → R1 (10kΩ) → Op-amp non-inverting input
Op-amp non-inverting input → R2 (10kΩ) → GND
Op-amp inverting input → R3 (10kΩ) → Op-amp output
Op-amp inverting input → R4 (10kΩ) → GND
Gain = 1 + (R3/R4) = 2 (for 0-6.6V output from 0-3.3V input)
```

Adjust R3/R4 ratio for desired gain (higher gain = higher max gate voltage = higher max current).

### MOSFET Selection

**Key parameters:**
- **Vds (drain-source voltage)**: Must exceed maximum DUT voltage (e.g., 100V for 12V supplies)
- **Id (continuous drain current)**: Must exceed maximum load current (e.g., 10A for 3A loads with safety margin)
- **Rdson (on-resistance)**: Lower is better, but less critical in linear mode
- **Power dissipation**: Must handle worst-case power: P = V × I (e.g., 12V × 3A = 36W)
- **Vgs(th) (gate threshold voltage)**: Logic-level (<3V) for direct DAC drive; standard (2-4V) for op-amp drive

**Recommended MOSFETs:**

| Part Number | Vds | Id | Rdson | Vgs(th) | Power (TO-220) | Notes |
|-------------|-----|----|----|-------|----------------|-------|
| IRF540N | 100V | 33A | 44mΩ | 2-4V | 130W | Standard, requires op-amp |
| IRLZ44N | 55V | 47A | 22mΩ | 1-2V | 110W | Logic-level, direct DAC OK |
| IRL540N | 100V | 36A | 44mΩ | 1-2V | 130W | Logic-level, direct DAC OK |
| STP55NF06L | 60V | 55A | 14mΩ | 1-2.5V | 150W | Logic-level, low Rdson |

**Heatsink selection:**
- **Thermal resistance**: θJA (junction-to-ambient) = (Tj(max) - Ta) / P
- Example: IRF540N at 36W dissipation, 25°C ambient, 150°C max junction temp
- Required θJA = (150 - 25) / 36 = 3.5 °C/W
- IRF540N package thermal resistance θJC = 0.7 °C/W
- Heatsink thermal resistance: θHA = θJA - θJC = 2.8 °C/W (add thermal compound)

For >20W dissipation, use forced-air cooling (fan).

## Software Setup

### Arduino IDE

1. Install ESP32 board support (Tools → Board → Boards Manager → "ESP32")
2. Install Adafruit INA219 library (Tools → Manage Libraries → "Adafruit INA219")
3. Open `scpi-load.ino`
4. Edit WiFi credentials (`ssid`, `password`) at top of file
5. Select board: Tools → Board → ESP32 Dev Module
6. Select port: Tools → Port → (your USB serial port)
7. Click Upload
8. Open Serial Monitor (115200 baud) to see IP address

### PlatformIO (alternative)

```bash
cd ~/Dropbox/build/rf-bench/projects/esp32/scpi-load
pio init --board esp32dev
pio run -t upload
pio device monitor
```

## SCPI Command Reference

Connect via telnet or raw TCP socket on port 5025.

### Common Commands

| Command | Function | Response |
|---------|----------|----------|
| `*IDN?` | Identification | `N0GQ,ESP32-SCPI-Load,1.0,2026` |
| `*RST` | Reset to safe state (load off, CC mode, 0A) | `OK` |
| `SYST:ERR?` | System error query | `0,"No error"` or error code |

### Load Configuration

| Command | Function | Response |
|---------|----------|----------|
| `LOAD:MODE,<mode>` | Set load mode (CC, CP, CR, CV) | `OK` or `ERROR` |
| `LOAD:MODE?` | Query load mode | `CC`, `CP`, `CR`, or `CV` |
| `LOAD:EN,<0\|1>` | Enable (1) or disable (0) load | `OK` |
| `LOAD:EN?` | Query enable state | `0` or `1` |

### Setpoints

| Command | Function | Range | Response |
|---------|----------|-------|----------|
| `LOAD:CURR,<amps>` | Set current setpoint (CC mode) | 0-3.2A | `OK` or `ERROR` |
| `LOAD:CURR?` | Query current setpoint | — | `<amps>` |
| `LOAD:POW,<watts>` | Set power setpoint (CP mode) | 0-80W | `OK` or `ERROR` |
| `LOAD:POW?` | Query power setpoint | — | `<watts>` |
| `LOAD:RES,<ohms>` | Set resistance setpoint (CR mode) | >0Ω | `OK` or `ERROR` |
| `LOAD:RES?` | Query resistance setpoint | — | `<ohms>` |
| `LOAD:VOLT,<volts>` | Set voltage setpoint (CV mode) | 0-26V | `OK` or `ERROR` |
| `LOAD:VOLT?` | Query voltage setpoint | — | `<volts>` |

### Measurements

| Command | Function | Response |
|---------|----------|----------|
| `MEAS:VOLT?` | Measure bus voltage | `<volts>` (4 decimals) |
| `MEAS:CURR?` | Measure current | `<amps>` (4 decimals) |
| `MEAS:POW?` | Measure power | `<watts>` (4 decimals) |
| `MEAS:ALL?` | Query all as CSV | `<V>,<A>,<W>` |

### Load Modes Explained

#### CC (Constant Current)
Regulates current to the setpoint regardless of voltage. PID controller adjusts MOSFET gate to maintain constant current.

**Use case**: Battery discharge testing, LED driver testing, current source verification.

**Example**:
```
LOAD:MODE,CC
LOAD:CURR,1.5
LOAD:EN,1
```
Load draws 1.5A regardless of DUT voltage (5V = 7.5W, 12V = 18W, etc.).

#### CP (Constant Power)
Regulates power (V × I) to the setpoint. As voltage changes, current adjusts to maintain constant power.

**Use case**: Power supply output impedance measurement, battery capacity testing at constant power.

**Example**:
```
LOAD:MODE,CP
LOAD:POW,10
LOAD:EN,1
```
Load maintains 10W power dissipation. At 12V: 0.83A, at 5V: 2A.

#### CR (Constant Resistance)
Simulates a resistor: I = V / R. Current is proportional to voltage.

**Use case**: Resistive load simulation, testing voltage regulation under load.

**Example**:
```
LOAD:MODE,CR
LOAD:RES,10
LOAD:EN,1
```
Load behaves as a 10Ω resistor. At 12V: 1.2A, at 5V: 0.5A.

#### CV (Constant Voltage)
Regulates voltage to the setpoint. PID controller adjusts current to maintain constant bus voltage.

**Use case**: Battery charger testing, voltage regulator droop measurement, simulating a back-EMF source.

**Example**:
```
LOAD:MODE,CV
LOAD:VOLT,10
LOAD:EN,1
```
Load draws current to maintain 10V bus voltage (acts like a voltage sink / active clamp).

**Warning**: CV mode can draw excessive current if DUT voltage > setpoint. Use with caution.

## Usage Examples

### Python (socket)

```python
import socket
import time

def scpi_query(ip, port, cmd):
    s = socket.socket()
    s.connect((ip, port))
    s.sendall((cmd + '\n').encode())
    if '?' in cmd:
        resp = s.recv(1024).decode().strip()
        s.close()
        return resp
    s.close()

# Connect to load
ip = '192.168.1.42'
port = 5025

# Identify
print(scpi_query(ip, port, '*IDN?'))  # N0GQ,ESP32-SCPI-Load,1.0,2026

# Set CC mode, 1A
scpi_query(ip, port, 'LOAD:MODE,CC')
scpi_query(ip, port, 'LOAD:CURR,1.0')
scpi_query(ip, port, 'LOAD:EN,1')

# Wait for settling
time.sleep(1)

# Read measurements
csv = scpi_query(ip, port, 'MEAS:ALL?')
v, i, p = map(float, csv.split(','))
print(f"Voltage: {v:.3f}V, Current: {i:.3f}A, Power: {p:.2f}W")

# Disable load
scpi_query(ip, port, 'LOAD:EN,0')
```

### Python (pyvisa)

```python
import pyvisa

rm = pyvisa.ResourceManager('@py')
load = rm.open_resource('TCPIP::192.168.1.42::5025::SOCKET')
load.read_termination = '\n'
load.write_termination = '\n'

print(load.query('*IDN?'))

# Set CP mode, 10W
load.write('LOAD:MODE,CP')
load.write('LOAD:POW,10')
load.write('LOAD:EN,1')

time.sleep(1)

voltage = float(load.query('MEAS:VOLT?'))
current = float(load.query('MEAS:CURR?'))
power = float(load.query('MEAS:POW?'))

print(f"V={voltage:.3f}V, I={current:.3f}A, P={power:.2f}W")

load.write('LOAD:EN,0')
load.close()
```

### Battery Discharge Test (CC Mode)

```python
import socket
import time
import csv

def scpi_cmd(ip, port, cmd):
    s = socket.socket()
    s.connect((ip, port))
    s.sendall((cmd + '\n').encode())
    if '?' in cmd:
        resp = s.recv(1024).decode().strip()
    else:
        resp = None
    s.close()
    return resp

ip = '192.168.1.42'
port = 5025

# Configure CC mode, 500mA discharge
scpi_cmd(ip, port, '*RST')
scpi_cmd(ip, port, 'LOAD:MODE,CC')
scpi_cmd(ip, port, 'LOAD:CURR,0.5')
scpi_cmd(ip, port, 'LOAD:EN,1')

# Log discharge curve
with open('battery_discharge.csv', 'w', newline='') as f:
    writer = csv.writer(f)
    writer.writerow(['Time (s)', 'Voltage (V)', 'Current (A)', 'Power (W)'])
    
    start = time.time()
    while True:
        elapsed = time.time() - start
        csv_data = scpi_cmd(ip, port, 'MEAS:ALL?')
        v, i, p = map(float, csv_data.split(','))
        
        writer.writerow([elapsed, v, i, p])
        print(f"{elapsed:.1f}s: {v:.3f}V, {i:.3f}A, {p:.2f}W")
        
        # Stop at cutoff voltage (e.g., 3.0V for LiPo)
        if v < 3.0:
            break
        
        time.sleep(10)  # Sample every 10 seconds

# Disable load
scpi_cmd(ip, port, 'LOAD:EN,0')
print("Discharge complete")
```

### Power Supply Load Regulation Test (CR Mode)

```python
import socket

def scpi_cmd(ip, port, cmd):
    s = socket.socket()
    s.connect((ip, port))
    s.sendall((cmd + '\n').encode())
    resp = s.recv(1024).decode().strip() if '?' in cmd else None
    s.close()
    return resp

ip = '192.168.1.42'
port = 5025

# Test PSU at different load resistances
resistances = [100, 50, 20, 10, 5]  # Ohms

for r in resistances:
    scpi_cmd(ip, port, 'LOAD:MODE,CR')
    scpi_cmd(ip, port, f'LOAD:RES,{r}')
    scpi_cmd(ip, port, 'LOAD:EN,1')
    
    time.sleep(1)  # Wait for settling
    
    v = float(scpi_cmd(ip, port, 'MEAS:VOLT?'))
    i = float(scpi_cmd(ip, port, 'MEAS:CURR?'))
    
    print(f"R={r}Ω: V={v:.3f}V, I={i:.3f}A, Load regulation: {(v/12)*100:.2f}% of nominal")

scpi_cmd(ip, port, 'LOAD:EN,0')
```

## PID Tuning

The firmware includes default PID gains optimized for fast response:

```cpp
load_state.pid_kp = 50.0;   // Proportional gain
load_state.pid_ki = 10.0;   // Integral gain
load_state.pid_kd = 1.0;    // Derivative gain
```

If the load oscillates or is sluggish, adjust these values:

- **Oscillation (overshoot/ringing)**: Reduce Kp and/or Kd
- **Slow response**: Increase Kp
- **Steady-state error**: Increase Ki
- **Noise sensitivity**: Reduce Kd

**Tuning procedure (Ziegler-Nichols method):**
1. Set Ki = 0, Kd = 0
2. Increase Kp until load oscillates
3. Note critical Kp (Ku) and oscillation period (Tu)
4. Set: Kp = 0.6 × Ku, Ki = 2 × Kp / Tu, Kd = Kp × Tu / 8

**Alternative: manual tuning:**
1. Start with Kp = 10, Ki = 0, Kd = 0
2. Apply step change in setpoint (e.g., 0A → 1A)
3. If slow, increase Kp by 2× and repeat
4. If oscillating, reduce Kp by 50%
5. Once stable with some steady-state error, add Ki = Kp / 10
6. If noisy, add Kd = Kp / 10

## Troubleshooting

### Load doesn't draw current (LOAD:EN,1 but MEAS:CURR? = 0)

**Possible causes:**
1. **INA219 not connected** — check Serial Monitor output for "INA219 not found" error
2. **MOSFET gate voltage too low** — verify DAC output (measure GPIO 25 with multimeter), verify op-amp power supply
3. **MOSFET damaged** — test MOSFET with multimeter (Rdson between drain/source should be <1Ω when gate is driven)
4. **No DUT voltage** — INA219 must see voltage at VIN+ to calculate power/resistance targets
5. **Setpoint too low** — in CC mode, verify `LOAD:CURR?` returns non-zero value

### Load oscillates (current/voltage hunting)

**Possible causes:**
1. **PID gains too high** — reduce Kp and Kd in firmware
2. **Poor gate drive** — add capacitor (100nF-1µF) from MOSFET gate to ground to filter high-frequency noise
3. **Ground loop** — ensure INA219 GND, ESP32 GND, DUT GND, MOSFET source are all connected to single point
4. **Inadequate heatsinking** — MOSFET overheating causes thermal runaway; add larger heatsink or fan

### INA219 sensor not found

**Possible causes:**
1. **Wiring error** — check SDA (GPIO 21), SCL (GPIO 22), VCC (3.3V), GND
2. **I2C address mismatch** — some modules use 0x41 instead of 0x40; change `ina219_address` in firmware
3. **Faulty module** — try different INA219 module
4. **I2C bus conflict** — disconnect other I2C devices

### DAC output stuck at 0V or 3.3V

**Possible causes:**
1. **PID saturated** — normal during large setpoint changes; should recover within 1 second
2. **Firmware bug** — add Serial.print() in `update_control_loop()` to debug DAC values
3. **GPIO conflict** — GPIO 25 is DAC1 on classic ESP32; verify board variant supports DAC

## Safety Considerations

**This is a LINEAR MODE electronic load — the MOSFET dissipates all power as heat.**

1. **Thermal management**: MOSFET can overheat and fail if heatsink is inadequate. For >10W dissipation, use forced-air cooling.
2. **Current limits**: INA219 with 0.1Ω shunt maxes out at 3.2A. Beyond this, the ADC saturates and readings are incorrect.
3. **Voltage limits**: INA219 bus voltage range is 0-26V. Exceeding this may damage the sensor.
4. **Startup surge**: When LOAD:EN,1 is sent, PID may transiently overshoot. Start with low setpoints and increase gradually.
5. **Inductive loads**: If DUT has large inductance (e.g., DC-DC converter output), add TVS diode across MOSFET drain-source to suppress voltage spikes during load transients.
6. **No reverse polarity protection**: Connecting DUT backwards will damage INA219 and possibly MOSFET. Add reverse polarity protection diode if needed.
7. **No over-temperature protection**: Firmware does not monitor MOSFET or INA219 temperature. For unattended operation, add thermistor + shutdown logic.

**Recommended additions for production use:**
- Over-temperature shutdown (thermistor on MOSFET heatsink)
- Over-current hardware limit (comparator + MOSFET gate clamp)
- Over-voltage hardware limit (crowbar SCR or TVS diode)
- Reverse polarity protection (series Schottky diode or MOSFET)
- Current sense resistor in MOSFET source path (redundant current measurement)

## License

Public domain / CC0. Use at your own risk.

## Author

Jeff Francis / N0GQ  
Part of rf-bench: https://github.com/jfrancis42/rf-bench
