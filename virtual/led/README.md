# Virtual LED Indicator

✅ **Status: Tested 2026-06-14** — SCPI commands, WebSocket updates, ON/OFF states, color changes, blink patterns (fast/slow), size adjustment, labels verified

SCPI-controlled LED indicator with configurable colors, blink rate, size, and label. Web-based display with realistic LED rendering including glow effects and specular highlights.

## Features

- **SCPI TCP server** on port 5025 (IEEE 488.2 standard)
- **WebSocket real-time updates** for instant state changes
- **Realistic LED rendering** with glow, shadow, and specular highlight
- **Configurable ON/OFF colors**
- **Optional blink** (configurable period)
- **Configurable size** (20-200 pixels diameter)
- **Text label** below LED
- **Auto-reconnect** on WebSocket disconnect

## Quick Start

```bash
cd ~/Dropbox/build/rf-bench/virtual/led/backend
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

### Status

```scpi
STAT:VAL <bool>          # Set LED state: 0/1, OFF/ON, FALSE/TRUE
STAT:VAL?                # Query LED state (returns 0 or 1)
```

### Configuration

```scpi
CONF:ONCOL <color>       # Set ON color (hex: #RGB or #RRGGBB, default #00ff00)
CONF:ONCOL?              # Query ON color

CONF:OFFCOL <color>      # Set OFF color (hex: #RGB or #RRGGBB, default #333333)
CONF:OFFCOL?             # Query OFF color

CONF:BLINK <ms>          # Set blink period in ms (0 = no blink, default 0)
CONF:BLINK?              # Query blink period

CONF:SIZE <int>          # Set LED diameter (20-200 pixels, default 80)
CONF:SIZE?               # Query LED diameter

CONF:LABEL <string>      # Set text label below LED
CONF:LABEL?              # Query text label
```

## Example Usage

### From command line (netcat)

```bash
# Query ID
echo "*IDN?" | nc localhost 5025

# Turn LED ON (green)
echo "STAT:VAL 1" | nc localhost 5025

# Turn LED OFF
echo "STAT:VAL 0" | nc localhost 5025

# PTT indicator (red when ON)
echo "CONF:ONCOL #ff0000" | nc localhost 5025
echo "CONF:OFFCOL #440000" | nc localhost 5025
echo "CONF:LABEL PTT" | nc localhost 5025
echo "STAT:VAL 1" | nc localhost 5025

# GPS lock indicator (blue, blinking)
echo "CONF:ONCOL #4488ff" | nc localhost 5025
echo "CONF:OFFCOL #222244" | nc localhost 5025
echo "CONF:BLINK 500" | nc localhost 5025
echo "CONF:LABEL GPS LOCK" | nc localhost 5025
echo "STAT:VAL 1" | nc localhost 5025

# Alarm indicator (red, fast blink)
echo "CONF:ONCOL #ff0000" | nc localhost 5025
echo "CONF:BLINK 200" | nc localhost 5025
echo "CONF:SIZE 120" | nc localhost 5025
echo "CONF:LABEL ALARM" | nc localhost 5025
echo "STAT:VAL 1" | nc localhost 5025
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

# Configure PTT indicator
send_scpi('localhost', 5025, 'CONF:ONCOL #ff0000')
send_scpi('localhost', 5025, 'CONF:OFFCOL #440000')
send_scpi('localhost', 5025, 'CONF:LABEL PTT')

# Blink 5 times
for _ in range(5):
    send_scpi('localhost', 5025, 'STAT:VAL 1')
    time.sleep(0.3)
    send_scpi('localhost', 5025, 'STAT:VAL 0')
    time.sleep(0.3)
```

### From rf_bench driver (ESP32 PTT monitor)

```python
import socket
import time

# Connect to ESP32 scpi-ptt
esp_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
esp_sock.connect(('192.168.1.42', 5025))

# Connect to virtual LED
led_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
led_sock.connect(('localhost', 5025))

# Configure LED
led_sock.sendall(b'CONF:ONCOL #ff0000\n')
led_sock.sendall(b'CONF:OFFCOL #440000\n')
led_sock.sendall(b'CONF:LABEL PTT\n')

# Poll ESP32 PTT state and update LED
try:
    while True:
        esp_sock.sendall(b'PTT:STAT?\n')
        response = esp_sock.recv(1024).decode().strip()
        ptt_active = (response == '1')
        
        led_sock.sendall(f'STAT:VAL {1 if ptt_active else 0}\n'.encode())
        time.sleep(0.05)  # 20 Hz poll rate
except KeyboardInterrupt:
    esp_sock.close()
    led_sock.close()
```

### From rf_bench driver (GPS lock monitor)

```python
from rf_bench.gpsd import GPSD
import socket
import time

# Connect to gpsd
gps = GPSD()

# Connect to virtual LED
led_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
led_sock.connect(('localhost', 5025))

# Configure LED
led_sock.sendall(b'CONF:ONCOL #4488ff\n')
led_sock.sendall(b'CONF:OFFCOL #222244\n')
led_sock.sendall(b'CONF:LABEL GPS\n')

# Monitor GPS fix status
try:
    while True:
        fix = gps.get_fix()
        has_lock = (fix.get('mode', 0) >= 2)  # 2D or 3D fix
        
        led_sock.sendall(f'STAT:VAL {1 if has_lock else 0}\n'.encode())
        time.sleep(1.0)  # 1 Hz update
except KeyboardInterrupt:
    led_sock.close()
    gps.close()
```

### From rf_bench driver (Relay state monitor)

```python
import socket
import time

# Connect to ESP32 scpi-relay
relay_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
relay_sock.connect(('192.168.1.42', 5025))

# Create 4 LED indicators for 4 relays
leds = []
for i in range(4):
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    # Each LED runs on different port (8000, 8010, 8020, 8030)
    # Or use different hosts
    sock.connect(('localhost', 5025))
    sock.sendall(b'CONF:ONCOL #00ff00\n')
    sock.sendall(b'CONF:OFFCOL #003300\n')
    sock.sendall(f'CONF:LABEL RELAY{i+1}\n'.encode())
    leds.append(sock)

# Poll relay states and update LEDs
try:
    while True:
        for i, led_sock in enumerate(leds):
            relay_sock.sendall(f'ROUT:CLOS? (@{i+1})\n'.encode())
            response = relay_sock.recv(1024).decode().strip()
            state = int(response)
            
            led_sock.sendall(f'STAT:VAL {state}\n'.encode())
        
        time.sleep(0.1)  # 10 Hz update
except KeyboardInterrupt:
    for sock in leds:
        sock.close()
    relay_sock.close()
```

## Color Presets

Common indicator colors:

| Purpose | Color | Hex |
|---------|-------|-----|
| Power/Ready (green) | Green | `#00ff00` |
| Transmit/PTT (red) | Red | `#ff0000` |
| Warning (yellow) | Yellow | `#ffff00` |
| Error (red) | Bright Red | `#ff0000` |
| GPS lock (blue) | Blue | `#4488ff` |
| Data activity (cyan) | Cyan | `#00ffff` |
| Standby (orange) | Orange | `#ff8800` |
| Off (dark gray) | Dark | `#333333` |

## Blink Patterns

Common blink rates for different purposes:

| Purpose | Period (ms) | Frequency |
|---------|-------------|-----------|
| Steady (no blink) | 0 | — |
| Slow heartbeat | 1000 | 1 Hz |
| Normal blink | 500 | 2 Hz |
| Fast alert | 200 | 5 Hz |
| Rapid alarm | 100 | 10 Hz |

## Use Cases

- **PTT indicator** (ESP32 scpi-ptt → red LED)
- **GPS lock status** (rf_bench.gpsd fix mode → blue LED)
- **Relay state monitor** (ESP32 scpi-relay → green LED per relay)
- **Instrument ready** (SSA/SDG/SDM online status → green LED)
- **TX power alarm** (SSA power > threshold → blinking red LED)
- **SWR warning** (ESP32 scpi-swr > 2.0 → yellow LED)
- **Battery charge complete** (ESP32 scpi-temp cutoff → green LED)
- **Antenna rotator limit** (ESP32 scpi-rotator limit switch → red LED)
- **Autopilot engaged** (radio/satellite/satellite.py mode → blue LED)

## Visual Features

### Realistic LED Appearance

- **ON state:**
  - Bright glow with radial blur
  - Multiple shadow layers (20px, 40px, 60px)
  - Specular highlight (30% white gradient on upper-left)
  - Inset highlight (20% white glow)

- **OFF state:**
  - Inset shadow (dark, recessed appearance)
  - Subtle top highlight (5% white)
  - No glow

- **Blink:**
  - Toggles between ON and OFF appearance at configured rate
  - Smooth transition (0.15s ease-out)

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
│   - CSS LED rendering               │
│   - JavaScript blink timer          │
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
- Build compound panels with multiple LEDs (Phase 4)
- Android app with native rendering (Phase 5)

## See Also

- `~/Dropbox/build/rf-bench/workbench.md` — Universal panel builder architecture
- `~/Dropbox/build/rf-bench/ideas.md` — Virtual instruments section
- `~/Dropbox/build/rf-bench/virtual/analog-meter/` — Analog meter with needle physics
- `~/Dropbox/build/rf-bench/virtual/numeric-display/` — Numeric display widget
