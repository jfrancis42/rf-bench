# rf-bench-drivers-virtual-compass

Python driver for **Virtual Compass** SCPI instrument. Displays directional heading with compass rose and cardinal labels via SCPI-over-TCP (port 5033).

## Installation

```bash
pip install rf-bench-drivers-virtual-compass
```

Or install from source:

```bash
cd drivers/virtual-compass
pip install -e .
```

## Quick Start

```python
from rf_bench.virtual import VirtualCompass

# Basic compass
with VirtualCompass("10.1.1.52") as compass:
    compass.set_heading(45.5)      # Northeast
    compass.set_title("Aircraft Heading")
    compass.enable_labels()
    compass.enable_rose()

# GPS integration
from rf_bench.gpsd import GPSD
import time

gps = GPSD()
compass = VirtualCompass("10.1.1.52")

compass.configure(
    title="GPS Track",
    needle_color="#00ff00",
    show_labels=True,
    show_rose=True
)

while True:
    fix = gps.get_fix()
    if fix.heading is not None:
        compass.set_heading(fix.heading)
    time.sleep(0.5)
```

## Backend Server

The driver connects to a virtual compass backend server:

```bash
cd ~/Dropbox/build/rf-bench/virtual/compass/backend
python3 server.py
```

Server listens on:
- SCPI TCP: port 5033 (default, or use `--scpi-port`)
- HTTP: port 8008 (default, or use `--http-port`)
- WebSocket: ws://localhost:8008/ws

Open browser at `http://localhost:8008` to see the virtual compass.

## API Reference

### Connection

```python
VirtualCompass(host, port=5033, timeout=2.0)
```

- **host**: IP address or hostname of backend server
- **port**: SCPI TCP port (default 5033)
- **timeout**: Socket timeout in seconds

### IEEE 488.2 Commands

```python
compass.idn()           # → "N0GQ,Virtual-Compass,1.0,2026"
compass.reset()         # Reset to default state
compass.get_error()     # → "0,No error"
```

### Heading Control

```python
# Set heading (0-360°, 0=North, clockwise)
compass.set_heading(0)       # North
compass.set_heading(45)      # Northeast
compass.set_heading(90)      # East
compass.set_heading(180)     # South
compass.set_heading(270)     # West
compass.set_heading(365)     # Normalized to 5°

# Query heading
compass.get_heading()        # → 45.0

# Convenience methods
compass.update(135)          # Shorter alias for set_heading
compass.point_north()        # Set to 0°
compass.point_east()         # Set to 90°
compass.point_south()        # Set to 180°
compass.point_west()         # Set to 270°
```

### Display Configuration

```python
# Compass size (200-600 pixels)
compass.set_size(400)
compass.get_size()           # → 400

# Needle color (CSS color string)
compass.set_needle_color("#ff0000")  # Red
compass.set_needle_color("#0f0")     # Green (short form)
compass.set_needle_color("blue")     # Named color
compass.get_needle_color()           # → "#ff0000"

# Cardinal labels (N, E, S, W)
compass.enable_labels()
compass.disable_labels()
compass.get_labels_enabled()         # → True

# Compass rose (degree markings)
compass.enable_rose()
compass.disable_rose()
compass.get_rose_enabled()           # → True

# Display title
compass.set_title("Aircraft Heading")
compass.get_title()                  # → "Aircraft Heading"

# Full configuration
compass.configure(
    title="GPS Track",
    size=350,
    needle_color="#00ff88",
    show_labels=True,
    show_rose=True
)
```

### MQTT Integration

The backend server can subscribe to MQTT topics for automatic heading updates:

```python
# Configure MQTT broker and topic
compass.configure_mqtt("mqtt.example.com", "heading/gps1")

# Query configuration
compass.get_mqtt_config()    # → "mqtt.example.com,heading/gps1"
```

Once configured, the backend subscribes to the topic and automatically updates the compass when messages arrive. Topic messages should contain a single floating-point heading value (0-360).

## Common Use Cases

### GPS Navigation Display

```python
from rf_bench.gpsd import GPSD
from rf_bench.virtual import VirtualCompass
import time

gps = GPSD()
compass = VirtualCompass("10.1.1.52")

compass.configure(
    title="GPS Track",
    size=400,
    needle_color="#00ff00",
    show_labels=True,
    show_rose=True
)

print("Tracking GPS heading...")
while True:
    fix = gps.get_fix()
    if fix.heading is not None:
        compass.set_heading(fix.heading)
        print(f"Heading: {fix.heading:.1f}° at {fix.speed:.1f} m/s")
    else:
        print("Waiting for GPS fix...")
    time.sleep(0.5)
```

### Antenna Rotator Display

```python
from rf_bench.virtual import VirtualCompass
import socket
import time

# Assuming rotator speaks SCPI on port 5025
def get_rotator_azimuth(host):
    s = socket.socket()
    s.connect((host, 5025))
    s.sendall(b"AZ?\n")
    az = float(s.recv(64).decode().strip())
    s.close()
    return az

compass = VirtualCompass("10.1.1.52")
compass.configure(
    title="Antenna Azimuth",
    size=450,
    needle_color="#ff8800",
    show_labels=True,
    show_rose=True
)

rotator_host = "10.1.1.60"

while True:
    az = get_rotator_azimuth(rotator_host)
    compass.set_heading(az)
    print(f"Antenna: {az:.1f}°")
    time.sleep(1)
```

### APRS Heading Display (Live APRS-IS)

```python
from rf_bench.virtual import VirtualCompass
import socket
import time

# Connect to APRS-IS (aprs.n0gq.org WebSocket in production)
# This is a simplified example

compass = VirtualCompass("10.1.1.52")
compass.configure(
    title="APRS Mobile Heading",
    size=400,
    needle_color="#00aaff",
    show_labels=True,
    show_rose=True
)

# Assume APRS parsing returns heading from position reports
def get_aprs_heading(callsign):
    # Stub: query aprs-server API for latest heading
    import requests
    r = requests.get(f"http://10.1.0.20:8090/station/{callsign}")
    data = r.json()
    return data.get("heading", 0)

callsign = "N0GQ-9"

while True:
    heading = get_aprs_heading(callsign)
    compass.set_heading(heading)
    print(f"{callsign} heading: {heading}°")
    time.sleep(5)
```

### Drone Telemetry (MAVLink)

```python
from rf_bench.virtual import VirtualCompass
from pymavlink import mavutil
import time

# Connect to drone via MAVLink
master = mavutil.mavlink_connection('udp:127.0.0.1:14550')
master.wait_heartbeat()

compass = VirtualCompass("10.1.1.52")
compass.configure(
    title="Drone Heading",
    size=450,
    needle_color="#ff00ff",
    show_labels=True,
    show_rose=True
)

print("Tracking drone heading...")
while True:
    msg = master.recv_match(type='VFR_HUD', blocking=True, timeout=1)
    if msg:
        heading = msg.heading  # 0-360°
        compass.set_heading(heading)
        print(f"Drone: {heading}° at {msg.groundspeed} m/s")
    time.sleep(0.2)
```

### MQTT Remote Display

Publish heading from GPS to MQTT, display on compass:

**Publisher (GPS device):**
```python
from rf_bench.gpsd import GPSD
import paho.mqtt.client as mqtt
import time

gps = GPSD()
client = mqtt.Client()
client.connect("mqtt.example.com", 1883, 60)
client.loop_start()

while True:
    fix = gps.get_fix()
    if fix.heading is not None:
        client.publish("heading/gps1", str(fix.heading))
    time.sleep(1)
```

**Subscriber (compass backend):**
```python
from rf_bench.virtual import VirtualCompass

compass = VirtualCompass("10.1.1.52")
compass.configure_mqtt("mqtt.example.com", "heading/gps1")

# Backend now subscribes and updates automatically
# No polling loop needed
```

### Wind Direction Display

```python
from rf_bench.virtual import VirtualCompass
import serial
import time

# Read from Davis Vantage Pro2 weather station
ser = serial.Serial('/dev/ttyUSB0', 19200, timeout=1)

compass = VirtualCompass("10.1.1.52")
compass.configure(
    title="Wind Direction",
    size=400,
    needle_color="#00ccff",
    show_labels=True,
    show_rose=True
)

def read_wind_direction():
    # Parse NMEA-like output from weather station
    line = ser.readline().decode('ascii').strip()
    if line.startswith('$WIMDA'):
        parts = line.split(',')
        wind_dir = float(parts[13])  # True wind direction
        return wind_dir
    return None

while True:
    wind_dir = read_wind_direction()
    if wind_dir is not None:
        compass.set_heading(wind_dir)
        print(f"Wind from: {wind_dir:.0f}°")
    time.sleep(2)
```

### Radio Beam Heading (VHF Contest)

```python
from rf_bench.virtual import VirtualCompass
import time

# Manual beam pointing during VHF contest
compass = VirtualCompass("10.1.1.52")
compass.configure(
    title="Beam Heading",
    size=500,
    needle_color="#ff0000",
    show_labels=True,
    show_rose=True
)

# Control via keyboard or rotator feedback
headings = {
    'n': 0, 'ne': 45, 'e': 90, 'se': 135,
    's': 180, 'sw': 225, 'w': 270, 'nw': 315
}

while True:
    cmd = input("Direction (n/ne/e/se/s/sw/w/nw) or angle: ").lower()
    if cmd in headings:
        compass.set_heading(headings[cmd])
    elif cmd.isdigit():
        compass.set_heading(int(cmd))
    else:
        print("Invalid direction")
```

### Boat Course Indicator

```python
from rf_bench.gpsd import GPSD
from rf_bench.virtual import VirtualCompass
import time

gps = GPSD()
compass = VirtualCompass("10.1.1.52")

compass.configure(
    title="Course Over Ground",
    size=450,
    needle_color="#0088ff",
    show_labels=True,
    show_rose=True
)

print("Boat navigation display...")
while True:
    fix = gps.get_fix()
    if fix.heading is not None and fix.speed > 0.5:  # Only show when moving
        compass.set_heading(fix.heading)
        print(f"COG: {fix.heading:.0f}° SOG: {fix.speed * 1.94384:.1f} kt")
    else:
        print("Not moving or no GPS fix")
    time.sleep(1)
```

## SCPI Command Reference

### IEEE 488.2 Common Commands
- `*IDN?` — Identification query → "N0GQ,Virtual-Compass,1.0,2026"
- `*RST` — Reset to defaults
- `SYST:ERR?` — Query error queue → "0,No error"

### Measurement Commands
- `MEAS:HEAD <float>` — Set heading in degrees (0-360, 0=North)
- `MEAS:HEAD?` — Query current heading

### Configuration Commands
- `CONF:SIZE <int>` — Set compass size (200-600 pixels, default 350)
- `CONF:SIZE?` — Query compass size
- `CONF:COL <color>` — Set needle color (hex: "#ff0000" or named: "red")
- `CONF:COL?` — Query needle color
- `CONF:LABEL <ON|OFF>` — Enable/disable cardinal labels (default ON)
- `CONF:LABEL?` — Query label state
- `CONF:ROSE <ON|OFF>` — Enable/disable compass rose (default ON)
- `CONF:ROSE?` — Query rose state
- `CONF:TITLE <string>` — Set display title
- `CONF:TITLE?` — Query title

### MQTT Commands
- `MQTT:CONF <host>,<topic>` — Configure MQTT broker and topic
- `MQTT:CONF?` — Query MQTT configuration

### Direct SCPI Example

```bash
# Using netcat
echo "MEAS:HEAD 45.5" | nc localhost 5033
echo "CONF:TITLE GPS Track" | nc localhost 5033
echo "CONF:COL #00ff00" | nc localhost 5033
echo "CONF:LABEL ON" | nc localhost 5033
echo "CONF:ROSE ON" | nc localhost 5033
echo "MQTT:CONF mqtt.example.com,heading/gps1" | nc localhost 5033
```

## Compass Display

The virtual compass displays:
- **Needle**: Red (default) or custom color, points toward heading
- **Rose**: Degree markings every 10° around the perimeter (0-360)
- **Cardinals**: N, E, S, W labels at 0°, 90°, 180°, 270°
- **Heading**: Numeric readout at bottom center (e.g. "045°")
- **Title**: Configurable text at top center

The needle rotates clockwise from North (0°):
- 0° / 360° = North
- 90° = East
- 180° = South
- 270° = West

## Error Handling

```python
from rf_bench.virtual import VirtualCompass, VirtualCompassError

try:
    compass = VirtualCompass("10.1.1.99")  # Wrong IP
except VirtualCompassError as e:
    print(f"Connection failed: {e}")

try:
    compass.set_size(1000)  # Out of range
except ValueError as e:
    print(f"Invalid parameter: {e}")
```

## Requirements

- Python 3.7+
- No external dependencies (uses stdlib `socket`)

## Optional Integration Packages

- `rf-bench-drivers-gpsd` — GPS position and heading
- `paho-mqtt` — MQTT publish/subscribe
- `pymavlink` — Drone telemetry (MAVLink)
- `pyserial` — Weather station serial interface

## License

GPL-3.0-or-later — see LICENSE file in package root.

## See Also

- Backend server: `~/Dropbox/build/rf-bench/virtual/compass/`
- BenchView panel manager: `~/Dropbox/build/rf-bench/virtual/benchview/`
- Other virtual instruments: `~/Dropbox/build/rf-bench/virtual/`
- RF Bench drivers: `~/Dropbox/build/rf-bench/drivers/`
