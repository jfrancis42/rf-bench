# Virtual Bar Graph

✅ **Status: Tested 2026-06-14** — SCPI commands, WebSocket updates, orientation switching, threshold zones, color changes verified

SCPI-controlled bar graph display with configurable range, orientation, color, and threshold zones.

## Features

- **Orientations:** Vertical (default) or horizontal
- **Range:** Configurable min/max scale
- **Color Thresholds:** Green → Yellow → Red zones based on value
- **Real-time Updates:** WebSocket push + MQTT subscriber
- **SCPI Control:** IEEE 488.2 compliant TCP server

## Quick Start

```bash
cd backend
python3 server.py
```

Open browser: `http://localhost:8000`

## SCPI Commands

### Measurement
- `MEAS:VAL <float>` — Set displayed value
- `MEAS:VAL?` — Query current value

### Configuration
- `CONF:MIN <float>` — Set minimum scale (default 0)
- `CONF:MAX <float>` — Set maximum scale (default 100)
- `CONF:ORIENT <HOR|VERT>` — Set orientation (default VERT)
- `CONF:UNIT <string>` — Set display units
- `CONF:COL <color>` — Set bar color (hex: #RGB or #RRGGBB)
- `CONF:THRES <yellow>,<red>` — Set threshold values (e.g., "70,90")

### MQTT
- `MQTT:CONF <host>,<topic>` — Configure MQTT broker and subscribe topic

### IEEE 488.2
- `*IDN?` — Identification query
- `*RST` — Reset to defaults
- `SYST:ERR?` — Query error queue

## Examples

### Signal Strength (dBm)
```bash
echo "CONF:MIN -120" | nc localhost 5025
echo "CONF:MAX -30" | nc localhost 5025
echo "CONF:UNIT dBm" | nc localhost 5025
echo "CONF:THRES -70,-50" | nc localhost 5025
echo "MEAS:VAL -65.5" | nc localhost 5025
```

### Battery Charge (%)
```bash
echo "CONF:MIN 0" | nc localhost 5025
echo "CONF:MAX 100" | nc localhost 5025
echo "CONF:UNIT %" | nc localhost 5025
echo "CONF:THRES 30,15" | nc localhost 5025  # Yellow at 30%, red at 15%
echo "CONF:ORIENT HOR" | nc localhost 5025
echo "MEAS:VAL 78.5" | nc localhost 5025
```

### RF Power (W)
```bash
echo "CONF:MIN 0" | nc localhost 5025
echo "CONF:MAX 100" | nc localhost 5025
echo "CONF:UNIT W" | nc localhost 5025
echo "CONF:COL #ff8800" | nc localhost 5025
echo "CONF:THRES 80,95" | nc localhost 5025
echo "MEAS:VAL 55.0" | nc localhost 5025
```

## MQTT Control

```bash
# Configure MQTT
echo "MQTT:CONF 10.1.0.20,bench/bargraph/value" | nc localhost 5025

# Publish values
mosquitto_pub -h 10.1.0.20 -t bench/bargraph/value -m "42.5"
```

## Python Integration

```python
import socket
import time

s = socket.socket()
s.connect(('localhost', 5025))

# Configure for SWR display
s.sendall(b'CONF:MIN 1.0\n')
s.sendall(b'CONF:MAX 3.0\n')
s.sendall(b'CONF:UNIT SWR\n')
s.sendall(b'CONF:THRES 1.5,2.0\n')

# Update values
while True:
    swr = measure_swr()  # Your measurement function
    s.sendall(f'MEAS:VAL {swr}\n'.encode())
    time.sleep(0.1)
```

## Architecture

**Backend:** Python FastAPI async server
- SCPI TCP server on port 5025 (asyncio.start_server)
- WebSocket server on port 8000/ws (FastAPI @app.websocket)
- HTTP server on port 8000 (serves frontend/index.html)
- MQTT subscriber (paho-mqtt, optional)

**Frontend:** Pure HTML/CSS/JS (no build step)
- CSS gradient bar with smooth transitions
- Threshold-based color zones (green/yellow/red)
- WebSocket client with auto-reconnect
- Horizontal and vertical orientations

## Use Cases

- Signal strength (dBm, S-meter)
- Battery charge/voltage
- RF power output
- SWR meter
- Temperature gauges
- CPU/memory usage
- Modulation depth
- Audio levels
