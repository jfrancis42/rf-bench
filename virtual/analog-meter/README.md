# Virtual Analog Meter

SCPI-controlled analog meter with realistic needle physics. Web-based display with spring-damper animation matching real d'Arsonval meter movements.

## Features

- **SCPI TCP server** on port 5025 (IEEE 488.2 standard)
- **WebSocket real-time updates** for smooth animation
- **Spring-damper needle physics** (ζ ≈ 0.65, ω₀ ≈ 2π × 3 Hz) — needles overshoot and settle like real meters
- **Configurable scale** (min/max/units)
- **Colored zones** for visual thresholds (up to 5 zones)
- **Auto-reconnect** on WebSocket disconnect

## Quick Start

```bash
cd ~/Dropbox/build/rf-bench/virtual/analog-meter/backend
python3 server.py
```

Open browser: `http://localhost:8000`

## SCPI Commands

### IEEE 488.2 Common Commands

```scpi
*IDN?                    # Query instrument ID
*RST                     # Reset to defaults
SYST:ERR?                # Query error queue
```

### Measurement

```scpi
MEAS:VAL <float>         # Set displayed value
MEAS:VAL?                # Query current value
```

### Configuration

```scpi
CONF:MIN <float>         # Set scale minimum (default 0)
CONF:MIN?                # Query scale minimum

CONF:MAX <float>         # Set scale maximum (default 100)
CONF:MAX?                # Query scale maximum

CONF:UNIT <string>       # Set display units (e.g., "dBm", "V", "A")
CONF:UNIT?               # Query display units

CONF:ZONE <id>,<v0>,<v1>,<color>   # Define colored zone (id 1-5)
CONF:ZONE? <id>                    # Query zone definition
```

### Zone Format

Zones are colored arcs on the meter face:
- `id`: 1-5 (zone identifier)
- `v0`: start value (in scale units)
- `v1`: end value (in scale units)
- `color`: hex color string (e.g., `#226644`)

Default zones:
1. `0-33`: Green (`#226644`) — safe
2. `33-66`: Yellow (`#886600`) — caution
3. `66-100`: Red (`#882222`) — danger

## Example Usage

### From command line (netcat)

```bash
# Query ID
echo "*IDN?" | nc localhost 5025

# Set scale 0-150 dBm
echo "CONF:MIN -150" | nc localhost 5025
echo "CONF:MAX 0" | nc localhost 5025
echo "CONF:UNIT dBm" | nc localhost 5025

# Set value to -73.5 dBm
echo "MEAS:VAL -73.5" | nc localhost 5025

# Define custom zones
echo "CONF:ZONE 1,-150,-100,#226644" | nc localhost 5025  # Green: strong
echo "CONF:ZONE 2,-100,-80,#886600" | nc localhost 5025   # Yellow: weak
echo "CONF:ZONE 3,-80,0,#882222" | nc localhost 5025      # Red: very weak
```

### From Python

```python
import socket
import time

def send_scpi(host, port, command):
    """Send SCPI command, return response if query"""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.connect((host, port))
        s.sendall(f"{command}\n".encode())
        if '?' in command:
            return s.recv(1024).decode().strip()

# Configure meter
send_scpi('localhost', 5025, 'CONF:MIN 0')
send_scpi('localhost', 5025, 'CONF:MAX 100')
send_scpi('localhost', 5025, 'CONF:UNIT V')

# Animate voltage reading
for v in range(0, 101, 5):
    send_scpi('localhost', 5025, f'MEAS:VAL {v}')
    time.sleep(0.2)
```

### From rf_bench driver

```python
from rf_bench.siglent import SSA3000X
import socket
import time

# Connect to SSA spectrum analyzer
ssa = SSA3000X('10.1.1.60')

# Connect to virtual meter
meter_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
meter_sock.connect(('localhost', 5025))

# Configure meter for dBm display
meter_sock.sendall(b'CONF:MIN -120\n')
meter_sock.sendall(b'CONF:MAX -30\n')
meter_sock.sendall(b'CONF:UNIT dBm\n')

# Poll SSA marker 1 level and update meter
try:
    while True:
        level = ssa.get_marker_level(1)
        meter_sock.sendall(f'MEAS:VAL {level}\n'.encode())
        time.sleep(0.1)  # 10 Hz update rate
except KeyboardInterrupt:
    meter_sock.close()
    ssa.close()
```

## Use Cases

- **S-meter display** for IC-7300/IC-9700 via Hamlib rigctld
- **Spectrum analyzer marker readout** (SSA marker level)
- **DMM voltage/current display** (SDM3045X measurements)
- **SWR meter** (ESP32 scpi-swr forward/reflected power)
- **Temperature gauge** (ESP32 scpi-temp DS18B20 readings)
- **Antenna rotator azimuth/elevation** (ESP32 scpi-rotator)

## Needle Physics

Realistic meter movement via spring-damper second-order system:

```javascript
const SPRING = 355;      // Spring constant
const DAMPING = 23;      // Damping coefficient

// Each frame:
const error = targetValue - displayValue;
const accel = error * SPRING - velocity * DAMPING;
velocity += accel * dt;
displayValue += velocity * dt;
```

This creates underdamped response (ζ ≈ 0.65) with:
- Natural frequency: ~3 Hz
- Slight overshoot on large value changes
- Smooth settling (no hunting)
- Visually matches real analog panel meters

## Architecture

```
┌─────────────────────────────────────┐
│   External SCPI Client              │
│   (LabVIEW, MATLAB, Python, nc)     │
└─────────────┬───────────────────────┘
              │ TCP 5025
              ▼
┌─────────────────────────────────────┐
│   Python Backend (server.py)        │
│   - SCPI parser                     │
│   - State management                │
│   - WebSocket broadcaster           │
└─────────────┬───────────────────────┘
              │ WebSocket
              ▼
┌─────────────────────────────────────┐
│   Web Frontend (index.html)         │
│   - Canvas 2D rendering             │
│   - Spring-damper animation         │
│   - Auto-reconnect                  │
└─────────────────────────────────────┘
```

## Dependencies

```bash
pip install fastapi uvicorn websockets --break-system-packages
```

No npm/Node.js required — frontend is pure HTML/CSS/JS.

## Status

✅ **Built, untested** — Phase 1 display-only widget.

## Next Steps

- Add MQTT subscription support (Phase 2)
- Add SCPI polling config (Phase 3 — poll external instruments)
- Build compound panels with multiple meters (Phase 4)
- Android app with native Canvas rendering (Phase 5)

## See Also

- `~/Dropbox/build/rf-bench/workbench.md` — Universal panel builder architecture
- `~/Dropbox/build/rf-bench/ideas.md` — Virtual instruments section
- `~/Dropbox/build/starship-lander/js/instruments.js` — Original needle physics implementation
