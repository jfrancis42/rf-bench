# Virtual Text LCD

✅ **Status: Tested 2026-06-14** — SCPI commands, WebSocket updates, terminal display, scrolling, DotMatrix font verified

SCPI-controlled text LCD terminal display with retro monospace font styling. Supports scrolling text output and terminal-style line management.

## Features

- **SCPI TCP server** on port 5006 (IEEE 488.2 standard)
- **WebSocket real-time updates** for instant text changes
- **DotMatrix TTF font** for authentic LCD appearance
- **Scrolling terminal** with configurable line count
- **LCD-style colors** (green-on-black default, customizable)
- **Line-based output** with automatic scrolling

## Ports

- **SCPI:** `tcp://0.0.0.0:5006`
- **HTTP:** `http://0.0.0.0:8006`
- **WebSocket:** `ws://0.0.0.0:8006/ws`
- **MQTT:** Configurable via `MQTT:CONF` command

## SCPI Commands

### Text Output
- `DISP:TEXT <string>` — Append a line of text to the display
- `DISP:CLEAR` — Clear all text from the display
- `DISP:TEXT?` — Query all lines (newline-separated)

### Configuration
- `CONF:LINES <int>` — Set number of visible lines (default 10)
- `CONF:LINES?` — Query line count
- `CONF:COL <color>` — Set text color (hex, e.g., "#00ff00")
- `CONF:COL?` — Query text color
- `CONF:BGCOL <color>` — Set background color (hex, e.g., "#000000")
- `CONF:BGCOL?` — Query background color

### IEEE 488.2 Standard
- `*IDN?` — Identification query
- `*RST` — Reset to defaults (clears text)
- `SYST:ERR?` — Query error queue

### MQTT
- `MQTT:CONF <host>,<topic>` — Configure MQTT broker and topic
- `MQTT:CONF?` — Query MQTT configuration

## Quick Start

```bash
# Start the server
cd ~/Dropbox/build/rf-bench/virtual/text-lcd/backend
python3 server.py

# Open in browser
xdg-open http://localhost:8006

# Send text
echo "DISP:TEXT Hello, World!" | nc localhost 5006
echo "DISP:TEXT System Ready" | nc localhost 5006
echo "DISP:TEXT Awaiting Input..." | nc localhost 5006

# Clear display
echo "DISP:CLEAR" | nc localhost 5006
```

## Display Behavior

- Text is appended as lines (automatic newline per `DISP:TEXT` command)
- Display scrolls automatically when line count exceeds `CONF:LINES`
- Older lines scroll off the top
- Empty lines can be inserted with `DISP:TEXT ""`

## Integration Examples

### System log monitor
```python
import socket, time

sock = socket.socket()
sock.connect(('localhost', 5006))
sock.sendall(b'CONF:LINES 20\n')
sock.sendall(b'CONF:COL #00ff00\n')
sock.sendall(b'DISP:CLEAR\n')
sock.sendall(b'DISP:TEXT === System Monitor ===\n')

with open('/var/log/syslog', 'r') as f:
    f.seek(0, 2)  # Seek to end
    while True:
        line = f.readline()
        if line:
            sock.sendall(f'DISP:TEXT {line.strip()}\n'.encode())
        else:
            time.sleep(0.1)
```

### APRS packet display
```python
import socket, time

# Connect to APRS server WebSocket
# (example - actual implementation varies)

lcd_sock = socket.socket()
lcd_sock.connect(('localhost', 5006))
lcd_sock.sendall(b'CONF:COL #ffaa00\n')
lcd_sock.sendall(b'DISP:CLEAR\n')
lcd_sock.sendall(b'DISP:TEXT === APRS Monitor ===\n')

while True:
    # Get APRS packet (example)
    packet = get_aprs_packet()  # Your implementation
    
    callsign = packet.get('callsign', 'UNKNOWN')
    comment = packet.get('comment', '')
    
    lcd_sock.sendall(f'DISP:TEXT {callsign}: {comment}\n'.encode())
    time.sleep(0.5)
```

### Test equipment status
```python
from rf_bench.siglent import SSA3000X
import socket, time

ssa = SSA3000X('10.1.1.60')
lcd_sock = socket.socket()
lcd_sock.connect(('localhost', 5006))
lcd_sock.sendall(b'CONF:LINES 6\n')
lcd_sock.sendall(b'DISP:CLEAR\n')

while True:
    # Clear and redraw
    lcd_sock.sendall(b'DISP:CLEAR\n')
    lcd_sock.sendall(b'DISP:TEXT === SSA3032X Status ===\n')
    
    center_freq = ssa.get_center_frequency() / 1e6
    span = ssa.get_span() / 1e3
    rbw = ssa.get_resolution_bandwidth() / 1e3
    
    lcd_sock.sendall(f'DISP:TEXT Center: {center_freq:.3f} MHz\n'.encode())
    lcd_sock.sendall(f'DISP:TEXT Span: {span:.1f} kHz\n'.encode())
    lcd_sock.sendall(f'DISP:TEXT RBW: {rbw:.1f} kHz\n'.encode())
    
    time.sleep(1.0)
```

### MQTT Integration
```bash
# Configure MQTT
echo "MQTT:CONF localhost,lcd/messages" | nc localhost 5006

# Publish messages from elsewhere
mosquitto_pub -h localhost -t lcd/messages -m "System Started"
mosquitto_pub -h localhost -t lcd/messages -m "Temperature: 25°C"
```

## Use Cases

- System log displays
- APRS/packet radio message viewers
- Test equipment status panels
- Debug output terminals
- Event stream viewers
- Sensor data loggers
- Process monitoring displays
- Serial console outputs

## Files

```
text-lcd/
├── backend/
│   └── server.py          # FastAPI SCPI + WebSocket server
├── frontend/
│   ├── index.html         # Terminal LCD display
│   └── DotMatrix.TTF      # DotMatrix monospace font
└── README.md              # This file
```

## See Also

- [PORT-ASSIGNMENTS.md](../PORT-ASSIGNMENTS.md) — Port allocations for all instruments
- [BUILDING-STATUS.md](../BUILDING-STATUS.md) — Phase 1 completion status
- [numeric-display](../numeric-display/) — Single numeric value display
- [waterfall](../waterfall/) — Spectrum/time waterfall display
