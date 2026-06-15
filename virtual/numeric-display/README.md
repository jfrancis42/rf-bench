# Virtual Numeric Display

✅ **Status: Tested 2026-06-15** — SCPI commands, WebSocket updates, all five styles (7SEG/LED/PLAIN/NIXIE/VFD), precision/units/color/size verified

SCPI-controlled numeric display with configurable precision, units, font size, color, and style. Web-based display with multiple rendering styles including Nixie tubes and VFD displays.

## Features

- **SCPI TCP server** on port 5025 (IEEE 488.2 standard)
- **WebSocket real-time updates** for instant value changes
- **Five display styles**: 7-segment LCD, LED, Plain text, Nixie tube, VFD
- **Fixed-width vintage fonts** for Nixie and VFD styles
- **Configurable precision** (0-6 decimal places)
- **Configurable font size** (20-120 pixels)
- **Configurable color** with glow effect
- **Units display** below main value
- **Auto-reconnect** on WebSocket disconnect

## Font Installation (Required for Nixie & VFD)

**IMPORTANT:** Nixie and VFD styles require the Analog Digits font packs, which cannot be redistributed due to licensing. Run the installer to download and install them:

```bash
python3 install_fonts.py
```

See [FONTS.md](FONTS.md) for detailed installation instructions.

## Quick Start

```bash
cd ~/Dropbox/build/rf-bench/virtual/numeric-display/backend
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
CONF:PREC <int>          # Set decimal precision (0-6, default 2)
CONF:PREC?               # Query decimal precision

CONF:UNIT <string>       # Set display units (e.g., "MHz", "V", "A", "°C")
CONF:UNIT?               # Query display units

CONF:SIZE <int>          # Set font size (20-120 pixels, default 80)
CONF:SIZE?               # Query font size

CONF:COL <color>         # Set text color (hex: #RGB or #RRGGBB, default #00ff00)
CONF:COL?                # Query text color

CONF:STYLE <string>      # Set display style: "7SEG" or "PLAIN" (default 7SEG)
CONF:STYLE?              # Query display style
```

## Example Usage

### From command line (netcat)

```bash
# Query ID
echo "*IDN?" | nc localhost 5025

# Frequency display: 14.257000 MHz (6 decimals)
echo "CONF:PREC 6" | nc localhost 5025
echo "CONF:UNIT MHz" | nc localhost 5025
echo "MEAS:VAL 14.257000" | nc localhost 5025

# Voltage display: 13.8 V (1 decimal, larger font, cyan)
echo "CONF:PREC 1" | nc localhost 5025
echo "CONF:UNIT V" | nc localhost 5025
echo "CONF:SIZE 100" | nc localhost 5025
echo "CONF:COL #00ffff" | nc localhost 5025
echo "MEAS:VAL 13.8" | nc localhost 5025

# Temperature: 25°C (0 decimals, red, plain style)
echo "CONF:PREC 0" | nc localhost 5025
echo "CONF:UNIT °C" | nc localhost 5025
echo "CONF:COL #ff0000" | nc localhost 5025
echo "CONF:STYLE PLAIN" | nc localhost 5025
echo "MEAS:VAL 25" | nc localhost 5025
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

# Configure frequency display
send_scpi('localhost', 5025, 'CONF:PREC 3')
send_scpi('localhost', 5025, 'CONF:UNIT MHz')
send_scpi('localhost', 5025, 'CONF:COL #00ff00')

# Animate frequency sweep 14.000 → 14.350 MHz
for freq in range(14000, 14351):
    f_mhz = freq / 1000.0
    send_scpi('localhost', 5025, f'MEAS:VAL {f_mhz}')
    time.sleep(0.01)  # 100 Hz update
```

### From rf_bench driver (IC-7300 frequency readout)

```python
from rf_bench.icom import IC7300
import socket
import time

# Connect to IC-7300 via Hamlib rigctld
radio = IC7300()

# Connect to virtual display
display_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
display_sock.connect(('localhost', 5025))

# Configure display
display_sock.sendall(b'CONF:PREC 3\n')
display_sock.sendall(b'CONF:UNIT MHz\n')
display_sock.sendall(b'CONF:SIZE 90\n')
display_sock.sendall(b'CONF:COL #00ff88\n')

# Poll radio frequency and update display
try:
    while True:
        freq_hz = radio.get_frequency()
        freq_mhz = freq_hz / 1e6
        display_sock.sendall(f'MEAS:VAL {freq_mhz}\n'.encode())
        time.sleep(0.1)  # 10 Hz update
except KeyboardInterrupt:
    display_sock.close()
    radio.close()
```

### From rf_bench driver (DMM voltage readout)

```python
from rf_bench.siglent import SDM3000X
import socket
import time

# Connect to SDM3045X DMM
dmm = SDM3000X('10.1.1.63')

# Connect to virtual display
display_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
display_sock.connect(('localhost', 5025))

# Configure display
display_sock.sendall(b'CONF:PREC 4\n')
display_sock.sendall(b'CONF:UNIT V\n')
display_sock.sendall(b'CONF:COL #ffff00\n')

# Poll DMM and update display
try:
    while True:
        voltage = dmm.measure_voltage_dc()
        display_sock.sendall(f'MEAS:VAL {voltage}\n'.encode())
        time.sleep(0.2)  # 5 Hz update (DMM is slower)
except KeyboardInterrupt:
    display_sock.close()
    dmm.close()
```

## Display Styles

### 7SEG (default)
Classic 7-segment LCD style. Uses monospace font with bold weight, mimics traditional bench meter displays. Best for numeric-only readouts where units are shown separately below.

### PLAIN
Modern sans-serif font. Cleaner, more readable for alphanumeric content. Better for mixed text/number displays.

## Color Presets

Common colors for different measurement types:

| Measurement | Color | Hex |
|-------------|-------|-----|
| Frequency | Green | `#00ff00` |
| Voltage (DC) | Yellow | `#ffff00` |
| Current | Orange | `#ff8800` |
| Temperature | Red | `#ff0000` |
| Power | Cyan | `#00ffff` |
| S-meter | Green | `#00ff88` |
| GPS coordinates | Blue | `#4488ff` |

Colors include automatic glow/shadow effect matching the text color.

## Use Cases

- **Frequency readout** for IC-7300/IC-9700/FT-891 via Hamlib rigctld
- **DMM voltage/current display** (SDM3045X, Solartron 7151)
- **GPS coordinates** (latitude, longitude, altitude via rf_bench.gpsd)
- **Power meter** (ESP32 scpi-power INA219 readings)
- **Counter display** (ESP32 scpi-counter frequency measurements)
- **Temperature readout** (ESP32 scpi-temp DS18B20)
- **Distance/range display** (ESP32 scpi-distance HC-SR04)
- **Altitude display** for aircraft tracking (Vestigare ADS-B altitude)

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
│   - CSS gradient display panel      │
│   - Dynamic styling                 │
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
- Build compound panels with multiple displays (Phase 4)
- Android app with native text rendering (Phase 5)

## See Also

- `~/Dropbox/build/rf-bench/workbench.md` — Universal panel builder architecture
- `~/Dropbox/build/rf-bench/ideas.md` — Virtual instruments section
- `~/Dropbox/build/rf-bench/virtual/analog-meter/` — Analog meter with needle physics
