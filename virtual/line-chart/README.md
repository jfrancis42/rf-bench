# Virtual Line Chart

SCPI-controlled time-series line chart with scrolling history, auto-scaling, and real-time statistics.

## Features

- **Scrolling History:** Configurable buffer (10-1000 samples)
- **Auto-Scaling:** Dynamic Y-axis or fixed range
- **Real-Time Stats:** Current, min, max, average values
- **Canvas Rendering:** Smooth line with glow effects and data points
- **Grid & Axes:** Clear Y-axis labels and grid lines
- **SCPI & MQTT:** Add data points via either interface

## Quick Start

```bash
cd backend
python3 server.py
```

Open browser: `http://localhost:8005`

## SCPI Commands

### Measurement
- `MEAS:VAL <float>` — Add data point to chart
- `MEAS:VAL?` — Query most recent value

### Configuration
- `CONF:HIST <int>` — Set history length in samples (10-1000, default 100)
- `CONF:MIN <float>` — Set Y-axis minimum (default: auto)
- `CONF:MAX <float>` — Set Y-axis maximum (default: auto)
- `CONF:AUTO <ON|OFF>` — Enable/disable auto-scaling (default ON)
- `CONF:UNIT <string>` — Set display units
- `CONF:COL <color>` — Set line color (hex: #RGB or #RRGGBB)
- `CONF:TITLE <string>` — Set chart title

### MQTT
- `MQTT:CONF <host>,<topic>` — Configure MQTT broker and subscribe topic

### IEEE 488.2
- `*IDN?` — Identification query
- `*RST` — Reset to defaults
- `SYST:ERR?` — Query error queue

## Examples

### Temperature Monitoring
```bash
echo "CONF:HIST 200" | nc localhost 5029
echo "CONF:TITLE Temperature Monitor" | nc localhost 5029
echo "CONF:UNIT °C" | nc localhost 5029
echo "CONF:COL #ff8800" | nc localhost 5029

# Add data points
for temp in 25.3 25.5 25.7 26.0 26.2; do
  echo "MEAS:VAL $temp" | nc localhost 5029
  sleep 1
done
```

### S-Meter Logger
```bash
echo "CONF:HIST 300" | nc localhost 5029
echo "CONF:TITLE S-Meter" | nc localhost 5029
echo "CONF:UNIT dBm" | nc localhost 5029
echo "CONF:MIN -120" | nc localhost 5029
echo "CONF:MAX -30" | nc localhost 5029
echo "CONF:AUTO OFF" | nc localhost 5029
echo "CONF:COL #00ff00" | nc localhost 5029
```

### Battery Voltage Trend
```bash
echo "CONF:HIST 500" | nc localhost 5029
echo "CONF:TITLE Battery Voltage" | nc localhost 5029
echo "CONF:UNIT V" | nc localhost 5029
echo "CONF:MIN 11.0" | nc localhost 5029
echo "CONF:MAX 14.0" | nc localhost 5029
echo "CONF:AUTO OFF" | nc localhost 5029
```

## MQTT Control

```bash
# Configure MQTT
echo "MQTT:CONF 10.1.0.20,bench/chart/temperature" | nc localhost 5029

# Publish values
while true; do
  temp=$(sensors | grep 'Core 0' | awk '{print $3}' | tr -d '+°C')
  mosquitto_pub -h 10.1.0.20 -t bench/chart/temperature -m "$temp"
  sleep 2
done
```

## Python Integration

```python
import socket
import time
import random

s = socket.socket()
s.connect(('localhost', 5029))

# Configure chart
s.sendall(b'CONF:HIST 150\n')
s.sendall(b'CONF:TITLE RF Power Output\n')
s.sendall(b'CONF:UNIT W\n')
s.sendall(b'CONF:COL #ff3333\n')

# Stream data
while True:
    power = 50.0 + random.uniform(-5, 5)  # Simulated RF power
    s.sendall(f'MEAS:VAL {power}\n'.encode())
    time.sleep(0.5)
```

## Architecture

**Backend:** Python FastAPI async server
- SCPI TCP server on port 5029
- WebSocket server on port 8005/ws
- HTTP server on port 8005
- MQTT subscriber (optional)
- Data stored in `collections.deque` with configurable maxlen
- Timestamps automatically added for each data point

**Frontend:** Pure HTML/CSS/JS with Canvas
- 700×400px chart canvas
- Grid lines and Y-axis labels
- Smooth line rendering with glow effect
- Data points marked as circles
- Real-time statistics (current, min, max, avg)
- WebSocket client with auto-reconnect

## Use Cases

- Signal strength monitoring over time
- Temperature trending
- Battery voltage discharge curves
- Power output stability
- CPU/memory usage
- Network latency tracking
- RF noise floor logging
- Modulation depth variation
- Audio level recording
- Any time-series metric

## Data Management

- **History Buffer:** Circular buffer (deque) automatically discards oldest values
- **Timestamps:** Relative to most recent sample (0 = now, negative = past)
- **Auto-Scale:** Adds 10% padding above/below data range for better visibility
- **Fixed Range:** Set CONF:AUTO OFF and specify CONF:MIN/MAX for stable axes
- **Statistics:** Computed from all samples in current buffer

## Performance

- Handles 1000-sample history without performance degradation
- Typical update rate: 10-100 samples/second
- Canvas redraws on every data point addition
- WebSocket broadcast to all connected clients on update
