# ESP32 SCPI GPS Controller

Network-controlled GPS receiver using Standard Commands for Programmable Instruments (SCPI) over TCP/IP. Reads NMEA data from a serial GPS module and provides parsed data via SCPI queries.

## Features

- **SCPI over TCP/IP** on port 5025 (industry standard)
- **NMEA 0183 parsing** from serial GPS module
- **WiFi connectivity** with configurable credentials
- **Standard SCPI commands** compatible with test equipment automation
- **Individual field queries** (lat, lon, altitude, speed, heading, time, date, etc.)
- **Bulk CSV query** for all GPS data at once
- **Fix quality monitoring** (satellite count, HDOP, fix type)
- **Low latency** continuous GPS data streaming

## Hardware Requirements

- ESP32 development board (any variant with WiFi and UART2)
- Serial GPS module (NEO-6M, NEO-7M, NEO-8M, or similar)
- Jumper wires

### Wiring

#### GPS Module Connection

| ESP32 GPIO | GPS Module Pin | Function |
|------------|----------------|----------|
| GPIO 16    | TX             | GPS transmit → ESP32 receive |
| GPIO 17    | RX             | ESP32 transmit → GPS receive (optional, not used) |
| 3.3V or 5V | VCC            | Power (check module spec: NEO-6M usually 3.3V-5V) |
| GND        | GND            | Ground   |

**Important:** Most GPS modules output 3.3V logic on TX, which is safe for ESP32. Some 5V modules may need a level shifter, but most modern GPS modules are 3.3V compatible.

**GPS antenna:** Modules with built-in chip antenna (like NEO-6M) work indoors near windows but perform better outdoors with clear sky view. External active antenna models work much better indoors.

### Typical GPS Modules

- **NEO-6M** — 9600 baud, 3.3V-5V, U-blox GPS, ceramic patch antenna
- **NEO-7M** — 9600 baud, 3.3V-5V, improved sensitivity
- **NEO-8M** — 9600 baud, 3.3V-5V, concurrent GPS/GLONASS
- **GT-U7** — 9600 baud, rebranded NEO-6M/7M
- **GY-GPS6MV2** — 9600 baud, NEO-6M with flash for EEPROM config

Default baud rate is **9600**. Some modules use 4800 or can be configured for 38400. If you see no GPS data on the serial monitor, try changing `gps_baud` in the code.

## Software Setup

1. **Install Arduino IDE** with ESP32 board support
   - File → Preferences → Additional Board Manager URLs: `https://dl.espressif.com/dl/package_esp32_index.json`
   - Tools → Board → Boards Manager → Search "ESP32" → Install

2. **Configure WiFi credentials**
   - Edit `scpi-gps.ino`
   - Change `ssid` and `password` near the top of the file

3. **Check GPS baud rate** (default 9600)
   - Most modules use 9600 baud
   - If no data: try 4800 or 38400 by changing `gps_baud` in the code

4. **Upload to ESP32**
   - Tools → Board → ESP32 Dev Module (or your specific board)
   - Tools → Port → (select your ESP32's serial port)
   - Click Upload

5. **Verify GPS reception**
   - Open Serial Monitor (115200 baud)
   - Reset the ESP32
   - Note the IP address printed
   - Wait for "GPS fix" message (may take 30-60 seconds outdoors, longer indoors)

## SCPI Command Reference

Connect to the ESP32 on port 5025 using any TCP client (`telnet`, `nc`, or Python `socket`).

### Identification

```
*IDN?
```
Returns device identification string: `N0GQ,ESP32-SCPI-GPS,1.0,2026`

### Reset

```
*RST
```
Clears GPS data buffer (does not affect GPS module, only ESP32 state).

### Fix Status

```
GPS:FIX?
```
Returns `1` if GPS has valid fix, `0` if no fix. Check this before querying position data.

### Position Queries

```
GPS:LAT?                 # Latitude in decimal degrees (+ = N, - = S)
GPS:LON?                 # Longitude in decimal degrees (+ = E, - = W)
GPS:ALT?                 # Altitude in meters above mean sea level
```

**Example responses:**
```
GPS:LAT?  → 39.73915730
GPS:LON?  → -104.98470270
GPS:ALT?  → 1655.20
```

### Motion Queries

```
GPS:SPEED?               # Speed over ground in km/h (default)
GPS:SPEED:KNOTS?         # Speed over ground in knots
GPS:TRACK?               # Course/heading in degrees true (0-360)
GPS:HEADING?             # Alias for GPS:TRACK?
```

**Example responses:**
```
GPS:SPEED?        → 45.50
GPS:SPEED:KNOTS?  → 24.57
GPS:TRACK?        → 135.20
```

### Time and Date Queries

```
GPS:TIME?                # UTC time as HH:MM:SS
GPS:DATE?                # UTC date as YYYY-MM-DD
```

**Example responses:**
```
GPS:TIME?  → 18:23:45
GPS:DATE?  → 2026-06-12
```

**Note:** Date comes from $GPRMC sentence. Some GPS modules don't output RMC, so date may not be available (returns error).

### Quality Queries

```
GPS:SATS?                # Number of satellites in use
GPS:HDOP?                # Horizontal Dilution of Precision (lower is better)
GPS:QUAL?                # Fix quality: 0=invalid, 1=GPS fix, 2=DGPS fix
GPS:AGE?                 # Age of last fix in milliseconds
```

**Example responses:**
```
GPS:SATS?  → 8
GPS:HDOP?  → 1.20
GPS:QUAL?  → 1
GPS:AGE?   → 253
```

### Bulk Query

```
GPS:ALL?
```

Returns all GPS data as a single CSV line:

```
lat,lon,alt,speed_kmh,track,hour,min,sec,year,month,day,sats,hdop,fix_qual
```

**Example response:**
```
39.73915730,-104.98470270,1655.20,45.50,135.20,18,23,45,2026,06,12,8,1.20,1
```

**CSV field order:**
1. Latitude (decimal degrees)
2. Longitude (decimal degrees)
3. Altitude (meters MSL)
4. Speed (km/h)
5. Track/heading (degrees true)
6. Hour (UTC, 0-23)
7. Minute (0-59)
8. Second (0-59)
9. Year (4-digit)
10. Month (1-12)
11. Day (1-31)
12. Satellites in use
13. HDOP
14. Fix quality (0/1/2)

### System Error Query

```
SYST:ERR?
```
Returns `0,"No error"` (always, for this simple device).

### Command Format Notes

- Commands can be uppercase or lowercase (case-insensitive)
- Short form allowed: `GPS:LAT` = `GPS:LATITUDE`
- Commands can be terminated with newline (`\n`), carriage return (`\r`), or semicolon (`;`)
- Multiple commands can be sent in one line separated by semicolons: `GPS:FIX?;GPS:LAT?;GPS:LON?`
- All position queries return `ERROR: No GPS fix` if `GPS:FIX?` returns 0

## Usage Examples

### Telnet (interactive)

```bash
telnet 192.168.1.42 5025
*IDN?
GPS:FIX?
GPS:LAT?
GPS:LON?
GPS:ALT?
GPS:ALL?
```

### Netcat (command-line)

```bash
echo "GPS:FIX?" | nc 192.168.1.42 5025
echo "GPS:ALL?" | nc 192.168.1.42 5025
```

### Python

```python
import socket

def scpi_command(ip, port, command):
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.connect((ip, port))
        s.sendall((command + '\n').encode())
        if '?' in command:
            response = s.recv(1024).decode().strip()
            return response

# Check for GPS fix
fix = scpi_command('192.168.1.42', 5025, 'GPS:FIX?')
print(f"GPS fix: {fix}")

if fix == '1':
    # Get individual fields
    lat = float(scpi_command('192.168.1.42', 5025, 'GPS:LAT?'))
    lon = float(scpi_command('192.168.1.42', 5025, 'GPS:LON?'))
    alt = float(scpi_command('192.168.1.42', 5025, 'GPS:ALT?'))
    print(f"Position: {lat:.6f}, {lon:.6f}, {alt:.1f}m")

    # Get all data as CSV
    all_data = scpi_command('192.168.1.42', 5025, 'GPS:ALL?')
    print(f"All GPS data: {all_data}")
else:
    print("No GPS fix yet")
```

### Python with pyvisa (instrument automation)

If you have `pyvisa` and `pyvisa-py` installed:

```python
import pyvisa

rm = pyvisa.ResourceManager('@py')
gps = rm.open_resource('TCPIP::192.168.1.42::5025::SOCKET',
                       read_termination='\n',
                       write_termination='\n')

print(gps.query('*IDN?'))

if gps.query('GPS:FIX?') == '1':
    lat = float(gps.query('GPS:LAT?'))
    lon = float(gps.query('GPS:LON?'))
    speed = float(gps.query('GPS:SPEED?'))
    sats = int(gps.query('GPS:SATS?'))

    print(f"Lat: {lat:.6f}°, Lon: {lon:.6f}°")
    print(f"Speed: {speed:.1f} km/h")
    print(f"Satellites: {sats}")

gps.close()
```

### Continuous Monitoring

```python
import socket
import time

s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
s.connect(('192.168.1.42', 5025))

def query(cmd):
    s.sendall((cmd + '\n').encode())
    return s.recv(1024).decode().strip()

try:
    while True:
        if query('GPS:FIX?') == '1':
            all_data = query('GPS:ALL?')
            fields = all_data.split(',')
            print(f"Lat: {fields[0]:>12}  Lon: {fields[1]:>13}  "
                  f"Alt: {fields[2]:>7}m  Speed: {fields[3]:>5} km/h  "
                  f"Sats: {fields[11]:>2}")
        else:
            print("Waiting for GPS fix...")
        time.sleep(1)
except KeyboardInterrupt:
    s.close()
```

### Complete Test Script

A complete test script `test_gps.py` is included that demonstrates all functionality:

```bash
# Edit the IP address in test_gps.py first, then run:
python3 test_gps.py
```

This script:
- Identifies the device
- Checks for GPS fix
- Queries all individual fields
- Queries bulk CSV data
- Continuously monitors position for 10 seconds

## Debugging

- **Serial Monitor (115200 baud)** shows WiFi connection status, IP address, and GPS fix status
- **Connection refused:** Check IP address, port number (5025), and firewall settings
- **"No GPS fix" errors:** GPS module needs clear sky view; can take 30-60 seconds (cold start) or 1-5 minutes indoors
- **No GPS data on serial:** Check baud rate (try 4800 or 38400 if 9600 doesn't work), verify wiring (GPS TX → ESP32 GPIO 16)
- **GPS fix lost indoors:** Normal behavior; GPS requires line-of-sight to satellites (4+ satellites minimum)
- **Weak signal indoors:** Use GPS module with external active antenna or place near window
- **Date returns error:** Some GPS modules don't output $GPRMC sentence with date; only $GPGGA (position/time)
- **HDOP very high (>5):** Poor satellite geometry or weak signals; try moving to location with better sky view

### GPS Fix Time

- **Cold start** (no almanac): 30-60 seconds outdoors with clear sky
- **Warm start** (recent almanac): 5-15 seconds
- **Hot start** (recent fix, <2 hours): 1-5 seconds
- **Indoors:** May take several minutes or may not achieve fix at all without external antenna

### Troubleshooting No GPS Data

1. Check wiring: GPS TX → ESP32 GPIO 16 (RX2)
2. Check power: GPS VCC to 3.3V or 5V (module-dependent)
3. Check baud rate in code (default 9600)
4. Open Serial Monitor at 115200 baud
5. Look for "Waiting for GPS fix..." message (proves GPS serial is working)
6. If no message, GPS is not sending data — check wiring and power
7. Move GPS module to window or outdoors for better satellite reception

## Integration with Test Systems

This SCPI GPS controller integrates with:

- **LabVIEW** via VISA driver (use TCPIP SOCKET resource)
- **MATLAB** via `tcpip` or Instrument Control Toolbox
- **Python** via `pyvisa`, `socket`, or `PySerial`
- **Keysight VEE, TestStand, etc.** via standard SCPI/VISA interface

The standard SCPI command set and GPS subsystem make this compatible with automated test equipment (ATE) frameworks for mobile RF testing, antenna testing, vehicle testing, and field data collection.

## Use Cases

- **RF field testing** — correlate signal strength measurements with GPS location
- **Antenna pattern measurement** — drive test with position logging
- **Time synchronization** — GPS provides accurate UTC time (better than NTP for remote sites)
- **Mobile data logging** — pair with sensors for geo-tagged measurements
- **Asset tracking** — networked GPS for lab equipment or test vehicles
- **Automated test rigs** — SCPI-controlled position for outdoor RF test automation

## License

Public domain. Use freely.

## Author

N0GQ — 2026-06-12
