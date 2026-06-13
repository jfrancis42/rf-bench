# ESP32 SCPI Temperature Monitor

Network-accessible DS18B20 1-Wire digital temperature sensor array using Standard Commands for Programmable Instruments (SCPI) over TCP/IP.

## Features

- **SCPI over TCP/IP** on port 5025 (industry standard)
- **Up to 16 DS18B20 sensors** on a single 1-Wire bus
- **High precision:** 12-bit resolution (0.0625°C)
- **Wide range:** -55°C to +125°C
- **Accurate:** ±0.5°C from -10°C to +85°C
- **Unique addressing:** Each sensor identified by 64-bit ROM address
- **Temperature alarms:** Configurable high/low thresholds per sensor
- **WiFi connectivity** with configurable credentials
- **Standard SCPI commands** compatible with test equipment automation
- **Celsius and Fahrenheit** readout
- **CSV bulk read** of all sensors at once

## Hardware Requirements

- ESP32 development board (any variant with WiFi)
- DS18B20 digital temperature sensors (1 to 16 units)
- 4.7kΩ resistor (pull-up for 1-Wire bus)
- Jumper wires
- Optional: 0.1µF ceramic capacitors (one per sensor, for noise filtering)

### DS18B20 Temperature Sensor

The DS18B20 is a 1-Wire digital temperature sensor with three pins:

```
  DS18B20
  -------
  1. GND (black)   — Ground
  2. DATA (yellow) — 1-Wire data bus
  3. VCC (red)     — 3.3V or 5V power
```

**TO-92 package pinout (flat side facing you, leads down):**
```
   ___
  |   |
  |___|
  | | |
  1 2 3
  G D V
  N A C
  D T C
    A
```

**Waterproof probe version:** Color-coded wires (red = VCC, black = GND, yellow/white = DATA).

### Wiring Diagram

#### Single Sensor Setup

```
ESP32                DS18B20 Sensor
-----                --------------
3.3V or 5V ----+---- VCC (red, pin 3)
               |
          4.7kΩ pull-up
               |
GPIO 4 --------+----- DATA (yellow, pin 2)

GND ---------------— GND (black, pin 1)
```

**Critical:** The 4.7kΩ pull-up resistor between DATA and VCC is **required** for 1-Wire communication. Without it, the bus will not work.

#### Multiple Sensor Setup (Parallel Bus)

```
ESP32              DS18B20 #1      DS18B20 #2      DS18B20 #3
-----              ----------      ----------      ----------
3.3V or 5V ----+---- VCC ----------- VCC ----------- VCC
               |
          4.7kΩ pull-up
               |
GPIO 4 --------+----- DATA --------- DATA --------- DATA

GND ---------------— GND ----------- GND ----------- GND
```

All sensors share the same three wires (parallel connection). Each sensor is identified by its unique 64-bit ROM address. A single 4.7kΩ pull-up on the DATA line suffices for the entire bus (do not add a resistor per sensor).

**For 8+ sensors or long cable runs (>3m):**
- Use external 5V power (not 3.3V) for better noise margin
- Add 0.1µF ceramic capacitor across VCC/GND at each sensor
- Use twisted-pair or shielded cable for DATA and GND
- Keep 4.7kΩ pull-up near the ESP32, not at the far end

### Parasitic Power Mode (Not Recommended)

DS18B20 can operate in "parasitic power" mode (DATA line provides power via internal capacitor). This mode:
- Works for 1-2 sensors only
- Unreliable with multiple sensors or long cables
- Requires stronger pull-up (2.2kΩ instead of 4.7kΩ)

**Wiring for parasitic mode:**
```
ESP32                DS18B20 Sensor
-----                --------------
GPIO 4 --------+----- DATA (yellow, pin 2)
               |
          2.2kΩ pull-up
               |
3.3V ----------+

GND ---------------— GND (black, pin 1)
                 \__ VCC (red, pin 3) — shorted to GND
```

**Recommendation:** Use external power (3-wire mode) for reliability, especially with multiple sensors.

## Software Setup

1. **Install Arduino IDE** with ESP32 board support
   - File → Preferences → Additional Board Manager URLs: `https://dl.espressif.com/dl/package_esp32_index.json`
   - Tools → Board → Boards Manager → Search "ESP32" → Install

2. **Install required libraries**
   - Tools → Manage Libraries
   - Search "OneWire" by Paul Stoffregen → Install
   - Search "DallasTemperature" by Miles Burton → Install

3. **Configure WiFi credentials**
   - Edit `scpi-temp.ino`
   - Change `ssid` and `password` near the top of the file

4. **Upload to ESP32**
   - Tools → Board → ESP32 Dev Module (or your specific board)
   - Tools → Port → (select your ESP32's serial port)
   - Click Upload

5. **Find the IP address**
   - Open Serial Monitor (115200 baud)
   - Reset the ESP32
   - Note the IP address printed (e.g., `192.168.1.42`)
   - Serial monitor also shows detected sensor count and ROM addresses

## SCPI Command Reference

Connect to the ESP32 on port 5025 using any TCP client (`telnet`, `nc`, or Python `socket`).

### Identification

```
*IDN?
```
Returns device identification string: `N0GQ,ESP32-SCPI-Temperature,1.0,2026`

### Reset

```
*RST
```
Clears all alarm settings (does not affect sensor readings).

### System Error Query

```
SYST:ERR?
```
Returns `0,"No error"` (always, for this simple device).

### Sensor Discovery

```
TEMP:COUN?
```
Returns the number of sensors detected on the 1-Wire bus (e.g., `4`).

### Read Temperature (Celsius)

```
TEMP:MEAS? (@1)        # Read sensor 1 in °C
TEMP:MEAS? (@2)        # Read sensor 2 in °C
TEMP:MEAS? (@3)        # Read sensor 3 in °C
```

Returns temperature in Celsius with 4 decimal places (e.g., `23.5625`).

**Note:** SCPI sensor numbers are 1-indexed (1 to N), not 0-indexed.

### Read Temperature (Fahrenheit)

```
TEMP:MEAS:F? (@1)      # Read sensor 1 in °F
TEMP:MEAS:F? (@2)      # Read sensor 2 in °F
```

Returns temperature in Fahrenheit with 4 decimal places (e.g., `74.4125`).

### Read All Sensors (CSV)

```
TEMP:ALL?
```

Returns all sensor temperatures as comma-separated values in Celsius (e.g., `23.5625,24.1250,22.8750,25.0000`).

**Performance:** Requesting all sensors at once is faster than individual queries because temperature conversion is done once for the entire bus.

### Query Sensor Address

```
TEMP:ADDR? (@1)        # Get 64-bit ROM address of sensor 1
TEMP:ADDR? (@2)        # Get address of sensor 2
```

Returns 16-character hex string (e.g., `28FF123456780190`). This is the unique factory-programmed address for the sensor. Useful for:
- Sensor identification and labeling
- Troubleshooting (verify sensor is detected)
- Cross-referencing with other 1-Wire tools

**ROM address format:** `<family code><serial number><CRC>`
- First byte (28) = DS18B20 family code
- Next 6 bytes = unique serial number
- Last byte = CRC-8 checksum

### Temperature Alarms

Set high and low temperature thresholds. Query alarm state to check if temperature is out of range.

```
TEMP:ALAR:HIGH (@1),50.0    # Set high alarm threshold for sensor 1 to 50°C
TEMP:ALAR:LOW (@1),10.0     # Set low alarm threshold for sensor 1 to 10°C

TEMP:ALAR? (@1)             # Query alarm state (returns 0 = OK, 1 = ALARM)
```

**Alarm logic:**
- Returns `1` if temperature > high threshold OR temperature < low threshold
- Returns `0` if temperature is within bounds or thresholds not set
- Thresholds are disabled by default (set threshold to enable)
- `*RST` command clears all alarm settings

**Use case:** Automated monitoring — periodically query `TEMP:ALAR?` for each sensor and send alert if any return `1`.

### Command Format Notes

- Commands can be uppercase or lowercase (case-insensitive)
- Short form allowed: `TEMP:MEAS` instead of `TEMP:MEASURE`
- Commands can be terminated with newline (`\n`), carriage return (`\r`), or semicolon (`;`)
- Multiple commands can be sent in one line separated by semicolons: `TEMP:MEAS? (@1);TEMP:MEAS? (@2)`

## Usage Examples

### Telnet (interactive)

```bash
telnet 192.168.1.42 5025
*IDN?
TEMP:COUN?
TEMP:MEAS? (@1)
TEMP:MEAS:F? (@1)
TEMP:ALL?
TEMP:ADDR? (@1)
TEMP:ALAR:HIGH (@1),30.0
TEMP:ALAR? (@1)
```

### Netcat (command-line)

```bash
echo "TEMP:COUN?" | nc 192.168.1.42 5025
echo "TEMP:MEAS? (@1)" | nc 192.168.1.42 5025
echo "TEMP:ALL?" | nc 192.168.1.42 5025
```

### Python (socket)

```python
import socket

def scpi_command(ip, port, command):
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.connect((ip, port))
        s.sendall((command + '\n').encode())
        if '?' in command:
            response = s.recv(1024).decode().strip()
            return response

# Discover sensors
sensor_count = int(scpi_command('192.168.1.42', 5025, 'TEMP:COUN?'))
print(f"Found {sensor_count} sensors")

# Read all sensors
for i in range(1, sensor_count + 1):
    temp = scpi_command('192.168.1.42', 5025, f'TEMP:MEAS? (@{i})')
    addr = scpi_command('192.168.1.42', 5025, f'TEMP:ADDR? (@{i})')
    print(f"Sensor {i} ({addr}): {temp}°C")

# Read all at once (faster)
temps = scpi_command('192.168.1.42', 5025, 'TEMP:ALL?')
print(f"All temperatures: {temps}")

# Set alarm and monitor
scpi_command('192.168.1.42', 5025, 'TEMP:ALAR:HIGH (@1),30.0')
scpi_command('192.168.1.42', 5025, 'TEMP:ALAR:LOW (@1),15.0')

alarm = scpi_command('192.168.1.42', 5025, 'TEMP:ALAR? (@1)')
if alarm == '1':
    print("ALARM: Temperature out of range!")
```

### Python with pyvisa (instrument automation)

If you have `pyvisa` and `pyvisa-py` installed:

```python
import pyvisa

rm = pyvisa.ResourceManager('@py')
temp = rm.open_resource('TCPIP::192.168.1.42::5025::SOCKET', 
                        read_termination='\n',
                        write_termination='\n')

print(temp.query('*IDN?'))

sensor_count = int(temp.query('TEMP:COUN?'))
print(f"Sensors: {sensor_count}")

# Read temperatures
for i in range(1, sensor_count + 1):
    temp_c = float(temp.query(f'TEMP:MEAS? (@{i})'))
    print(f"Sensor {i}: {temp_c:.2f}°C")

temp.close()
```

### Data Logging Example

```python
import socket
import time
import csv
from datetime import datetime

def scpi_query(ip, port, cmd):
    with socket.socket() as s:
        s.connect((ip, port))
        s.sendall((cmd + '\n').encode())
        return s.recv(1024).decode().strip()

IP = '192.168.1.42'
PORT = 5025
INTERVAL = 60  # seconds

# Discover sensors
sensor_count = int(scpi_query(IP, PORT, 'TEMP:COUN?'))
print(f"Logging {sensor_count} sensors every {INTERVAL}s")

with open('temperature_log.csv', 'w', newline='') as f:
    writer = csv.writer(f)
    
    # Header
    headers = ['timestamp'] + [f'sensor_{i+1}' for i in range(sensor_count)]
    writer.writerow(headers)
    
    while True:
        timestamp = datetime.now().isoformat()
        temps = scpi_query(IP, PORT, 'TEMP:ALL?').split(',')
        
        row = [timestamp] + [float(t) for t in temps]
        writer.writerow(row)
        f.flush()
        
        print(f"{timestamp}: {', '.join(f'{float(t):.2f}°C' for t in temps)}")
        time.sleep(INTERVAL)
```

## Typical Applications

### Environmental Monitoring

- **Server room:** Monitor multiple rack temperatures with a single ESP32
- **HVAC testing:** Profile temperature distribution in ducts and rooms
- **Cold chain:** Monitor refrigerator/freezer at multiple points
- **Greenhouse:** Track soil, air, and water temperatures

### Thermal Testing

- **Component characterization:** Measure transistor junction, heatsink, and ambient temperatures during power cycling
- **Thermal time constants:** Step power and log temperature vs time
- **Thermal resistance:** Measure ΔT across interfaces (junction-case, case-sink, sink-ambient)
- **PCB hot-spot mapping:** Array of sensors across board surface

### Laboratory Automation

- **Chemical reaction monitoring:** Track solution temperature in real-time
- **Calibration bath:** Verify uniform temperature in liquid baths
- **Environmental chamber:** Profile temperature gradient inside chambers
- **Sample storage:** Monitor multiple freezers/incubators from one endpoint

### RF Bench Integration

- **Amplifier thermal drift:** Correlate gain vs temperature
- **Oscillator stability:** Measure frequency vs temperature (with `~/govt-data/` GPS time)
- **VCO tempco:** Characterize voltage-controlled oscillator temperature coefficient
- **Power supply thermal regulation:** Monitor PSU temperature under load

## Debugging

### Serial Monitor (115200 baud)

The Serial Monitor shows:
- WiFi connection status and IP address
- Number of sensors detected
- ROM address of each sensor
- Real-time SCPI commands received
- Error messages (sensor not responding, invalid commands)

**Expected boot output:**
```
SCPI Temperature Monitor
========================
Found 3 DS18B20 sensor(s) on GPIO 4
  Sensor 1: 28FF123456780190
  Sensor 2: 28FF234567890ABC
  Sensor 3: 28FF345678901DEF

Connecting to YourSSID.... connected!
IP address: 192.168.1.42
SCPI port: 5025

Ready for SCPI commands
```

### No Sensors Detected (`TEMP:COUN?` returns 0)

1. **Check wiring:**
   - DATA wire to GPIO 4
   - VCC (red) to 3.3V or 5V
   - GND (black) to ESP32 GND
2. **Verify 4.7kΩ pull-up resistor** between DATA and VCC (common mistake: pull-up missing or wrong value)
3. **Check sensor power:** Measure VCC pin — should be 3.3V or 5V
4. **Test sensor:** Try with just one sensor first (eliminate faulty unit)
5. **Confirm DS18B20 variant:** Some sensors are labeled "DS18B20" but are counterfeit chips that don't follow the standard protocol

### Sensor Not Responding (`ERROR: Sensor not responding`)

- **Intermittent connection:** Loose wire, corroded probe connector
- **Bus contention:** Multiple devices sharing GPIO 4 (check for conflicts)
- **Parasitic power failure:** Switch to external power mode if using parasitic
- **Bad sensor:** Test with a known-good DS18B20

### Temperature Reads 85.0°C or -127.0°C

- **85.0°C:** Power-on reset value; sensor not fully initialized or conversion not complete. Firmware retries once automatically; persistent 85.0 indicates power/timing issue.
- **-127.0°C:** Sensor disconnected mid-read, bad CRC, or communication failure. Check wiring and pull-up.

### Temperature Fluctuates Wildly or Shows Noise

- **Add 0.1µF ceramic capacitors** across VCC/GND at each sensor
- **Shorten cable length** or use shielded/twisted-pair wire
- **Reduce WiFi TX power** (can cause EMI on 1-Wire bus)
- **Separate power supply** — don't share noisy 5V rail with sensors

### Temperature Reads Incorrectly (Consistent Offset)

- **Sensor calibration:** DS18B20 is factory calibrated but can drift ±0.5°C. Compare to a known-accurate thermometer and apply software offset if needed.
- **Self-heating:** In still air, sensor can self-heat by ~0.1-0.3°C due to measurement current. Use lower resolution (9-bit instead of 12-bit) to reduce power, or use waterproof probe version (better thermal coupling).
- **Thermal lag:** DS18B20 takes ~5-10 seconds to settle in air, ~1-2 seconds in liquid. Wait longer between readings for accurate data.

### Multiple Sensors Return Same Temperature

- **Address collision (extremely rare):** Two sensors with identical ROM addresses. Test sensors one at a time to identify duplicates. Return defective sensor.
- **Bus short:** All DATA lines shorted together incorrectly. Verify parallel wiring.

### ESP32 Reboots or Crashes

- **Insufficient power:** If powering 8+ sensors at 5V from ESP32's 5V pin (via USB), total current can exceed USB limit. Use external 5V supply.
- **Watchdog timeout:** Temperature conversion takes ~750ms and blocks during `sensors.requestTemperatures()`. This is normal and acceptable.

## Performance Notes

### Conversion Time

DS18B20 resolution vs conversion time:
- 9-bit (0.5°C): 93.75 ms
- 10-bit (0.25°C): 187.5 ms
- 11-bit (0.125°C): 375 ms
- 12-bit (0.0625°C): 750 ms (default)

Firmware uses 12-bit mode for best precision. Commands that read temperature (`TEMP:MEAS?`, `TEMP:MEAS:F?`, `TEMP:ALAR?`) take ~750ms to return. This is a hardware limitation of the DS18B20, not a software issue.

**Optimization:** Use `TEMP:ALL?` to read all sensors at once — temperature conversion happens simultaneously for the entire bus (still ~750ms, but only once for all sensors instead of N times).

### Maximum Sensor Count

Theoretical limit: 1-Wire protocol supports up to 256 devices on a bus (8-bit addressing). DS18B20 ROM address allows ~281 trillion unique IDs.

**Practical limits:**
- **Firmware limit:** 16 sensors (set by `max_sensors` constant; increase if needed, but memory grows proportionally)
- **Electrical limit:** ~10-20 sensors on a single bus with standard 4.7kΩ pull-up before signal integrity degrades
- **Cable length limit:** >10m cable with 8+ sensors may need stronger pull-up (2.2kΩ) or active driver

**For 20+ sensors:** Use multiple ESP32 devices (one per 10-15 sensors) or an active 1-Wire master IC.

### Polling Rate

Maximum practical polling rate with N sensors:
- 1 sensor: ~1.3 Hz (750ms conversion + overhead)
- 4 sensors (using `TEMP:ALL?`): ~1.2 Hz
- 16 sensors (using `TEMP:ALL?`): ~1.1 Hz

**For faster updates:** Reduce resolution to 9-bit (93ms conversion) via `sensors.setResolution(9)` in firmware. Sacrifices precision (0.5°C steps instead of 0.0625°C).

## Integration with Test Systems

This SCPI temperature monitor integrates with:

- **LabVIEW** via VISA driver (use TCPIP SOCKET resource)
- **MATLAB** via `tcpip` or Instrument Control Toolbox
- **Python** via `pyvisa`, `socket`, or higher-level automation frameworks
- **Keysight VEE, TestStand, etc.** via standard SCPI/VISA interface

The standard SCPI command set makes this compatible with automated test equipment (ATE) frameworks.

## License

Public domain. Use freely.

## Author

N0GQ — 2026-06-12
