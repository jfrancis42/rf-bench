# Virtual Compass

✅ **Status: Tested 2026-06-14** — SCPI commands, WebSocket updates, needle physics, cardinal directions verified

SCPI-controlled compass display with realistic needle physics for directional indication. Features smooth spring-damper motion and cardinal direction labels.

## Features

- **SCPI TCP server** on port 5008 (IEEE 488.2 standard)
- **WebSocket real-time updates** for instant heading changes
- **Realistic needle physics** with spring-damper model (overshoot and settling)
- **Cardinal directions** (N, E, S, W) with degree markings
- **Configurable colors** for needle and face

## Ports

- **SCPI:** `tcp://0.0.0.0:5008`
- **HTTP:** `http://0.0.0.0:8008`
- **WebSocket:** `ws://0.0.0.0:8008/ws`
- **MQTT:** Configurable via `MQTT:CONF` command

## SCPI Commands

### Measurement
- `MEAS:HEADING <float>` — Set heading in degrees (0-360, 0=North)
- `MEAS:HEADING?` — Query current heading

### Configuration
- `CONF:COL <color>` — Set needle color (hex, e.g., "#ff0000")
- `CONF:COL?` — Query needle color

### IEEE 488.2 Standard
- `*IDN?` — Identification query
- `*RST` — Reset to defaults
- `SYST:ERR?` — Query error queue

### MQTT
- `MQTT:CONF <host>,<topic>` — Configure MQTT broker and topic
- `MQTT:CONF?` — Query MQTT configuration

## Quick Start

```bash
# Start the server
cd ~/Dropbox/build/rf-bench/virtual/compass/backend
python3 server.py

# Open in browser
xdg-open http://localhost:8008

# Send commands
echo "MEAS:HEADING 45" | nc localhost 5008   # Northeast
echo "MEAS:HEADING 180" | nc localhost 5008  # South
echo "MEAS:HEADING 270" | nc localhost 5008  # West
```

## Needle Physics

The compass uses a spring-damper second-order system for realistic needle motion:
- Spring constant: 355
- Damping coefficient: 23
- Creates natural overshoot and settling behavior like real compass movements

## Integration Examples

### GPS heading display
```python
from rf_bench.gpsd import GPSD
import socket, time

gps = GPSD()
sock = socket.socket()
sock.connect(('localhost', 5008))
sock.sendall(b'CONF:COL #4488ff\n')

while True:
    fix = gps.get_fix()
    heading = fix.get('track', 0)  # GPS heading/track
    sock.sendall(f'MEAS:HEADING {heading}\n'.encode())
    time.sleep(0.5)
```

### Antenna rotator position
```python
import socket, time

# Connect to rotator controller
rotator_sock = socket.socket()
rotator_sock.connect(('192.168.1.42', 5025))

# Connect to compass display
compass_sock = socket.socket()
compass_sock.connect(('localhost', 5008))

while True:
    # Query rotator azimuth
    rotator_sock.sendall(b'AZ?\n')
    azimuth = float(rotator_sock.recv(1024).decode().strip())
    
    # Update compass
    compass_sock.sendall(f'MEAS:HEADING {azimuth}\n'.encode())
    time.sleep(0.2)
```

### MQTT Integration
```bash
# Configure MQTT
echo "MQTT:CONF localhost,antenna/azimuth" | nc localhost 5008

# Publish heading from elsewhere
mosquitto_pub -h localhost -t antenna/azimuth -m 135
```

## Use Cases

- GPS navigation displays
- Antenna rotator position indicators
- Wind direction monitoring
- Vehicle heading displays
- Satellite tracking ground station UI
- Marine navigation instruments
- Aircraft attitude indicators

## Files

```
compass/
├── backend/
│   └── server.py          # FastAPI SCPI + WebSocket server
├── frontend/
│   └── index.html         # Canvas compass with physics
└── README.md              # This file
```

## See Also

- [PORT-ASSIGNMENTS.md](../PORT-ASSIGNMENTS.md) — Port allocations for all instruments
- [BUILDING-STATUS.md](../BUILDING-STATUS.md) — Phase 1 completion status
- [analog-meter](../analog-meter/) — Similar physics-based needle gauge
- [gauge-cluster](../gauge-cluster/) — Multi-meter composite display
