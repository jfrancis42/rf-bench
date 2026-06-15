# Virtual Push Button

🔨 **Status: Built 2026-06-14** — Phase 2 interactive control (momentary push button)

SCPI-controlled push button with **bidirectional** communication. Users can click the button in the browser to trigger actions, or external SCPI/MQTT commands can trigger button presses. Momentary action with press count tracking.

## Features

- **SCPI TCP server** on port 5102 (IEEE 488.2 standard)
- **Bidirectional WebSocket** for instant updates
- **Momentary push button** with press/release animation
- **Press counter** tracks total presses since startup
- **Configurable labels** and colors
- **Adjustable size** (80-200 pixels)
- **MQTT bidirectional** (subscribe to receive, publish on user press)

## Ports

- **SCPI:** `tcp://0.0.0.0:5102`
- **HTTP:** `http://0.0.0.0:8102`
- **WebSocket:** `ws://0.0.0.0:8102/ws` (bidirectional)
- **MQTT:** Configurable via `MQTT:CONF` command

## SCPI Commands

### Button Control
- `STAT:PRESS` — Trigger a button press (momentary, ~200ms)
- `STAT:PRESS?` — Query if button is currently pressed (0 or 1)
- `STAT:COUNT?` — Query total press count since startup
- `STAT:COUNT:CLEAR` — Reset press counter to zero

### Configuration
- `CONF:LABEL <string>` — Set button label (default "Button")
- `CONF:LABEL?` — Query button label
- `CONF:COL <color>` — Set button color (hex, default "#4488ff")
- `CONF:COL?` — Query button color
- `CONF:PRESSCOL <color>` — Set pressed color (hex, brighter)
- `CONF:PRESSCOL?` — Query pressed color
- `CONF:SIZE <int>` — Set button size in pixels (80-200, default 120)
- `CONF:SIZE?` — Query button size

### IEEE 488.2 Standard
- `*IDN?` — Identification query
- `*RST` — Reset to defaults (clears counter)
- `SYST:ERR?` — Query error queue

### MQTT
- `MQTT:CONF <host>,<sub_topic>[,<pub_topic>]` — Configure MQTT
  - `sub_topic`: Topic to subscribe (receive trigger commands)
  - `pub_topic`: Topic to publish (send press events)
- `MQTT:CONF?` — Query MQTT configuration

## Bidirectional Flow

```
User clicks button → WebSocket → Backend → MQTT pub_topic
                                        ↓
                                     Press counter incremented
                                     SCPI clients can query count

External SCPI STAT:PRESS → Backend → WebSocket → Browser animates press
                               ↓
                            MQTT published

MQTT message arrives → Backend → WebSocket → Browser animates press
                           ↓
                        Press counter incremented
```

## Quick Start

```bash
# Start the server
cd ~/Dropbox/build/rf-bench/virtual/button/backend
python3 server.py

# Open in browser
xdg-open http://localhost:8102
```

## Configuration Examples

### Spectrum analyzer sweep trigger (orange)
```bash
echo "CONF:LABEL Sweep" | nc localhost 5102
echo "CONF:COL #ff8800" | nc localhost 5102
echo "CONF:PRESSCOL #ffaa44" | nc localhost 5102
```

### Screenshot capture (green)
```bash
echo "CONF:LABEL Capture" | nc localhost 5102
echo "CONF:COL #00ff00" | nc localhost 5102
echo "CONF:PRESSCOL #44ff44" | nc localhost 5102
```

### Peak search (blue, larger)
```bash
echo "CONF:LABEL Peak" | nc localhost 5102
echo "CONF:COL #4488ff" | nc localhost 5102
echo "CONF:SIZE 150" | nc localhost 5102
```

### Reset counter (red)
```bash
echo "CONF:LABEL Reset" | nc localhost 5102
echo "CONF:COL #ff0000" | nc localhost 5102
```

## Integration Examples

### SSA peak search trigger
```python
from rf_bench.siglent import SSA3000X
import socket, time

ssa = SSA3000X('10.1.1.60')
button_sock = socket.socket()
button_sock.connect(('localhost', 5102))

# Configure button
button_sock.sendall(b'CONF:LABEL Peak Search\n')
button_sock.sendall(b'CONF:COL #ff8800\n')

# Monitor button presses
last_count = 0
while True:
    button_sock.sendall(b'STAT:COUNT?\n')
    time.sleep(0.01)
    response = button_sock.recv(1024).decode().strip()
    if response:
        try:
            current_count = int(response)
            if current_count > last_count:
                print(f"Button pressed! Running peak search...")
                ssa.peak_search()
                marker_freq = ssa.get_marker_frequency(1)
                marker_level = ssa.get_marker_level(1)
                print(f"Peak: {marker_freq/1e6:.3f} MHz at {marker_level:.1f} dBm")
                last_count = current_count
        except ValueError:
            pass
    time.sleep(0.1)
```

### Screenshot capture with counter
```python
from rf_bench.siglent import SSA3000X
import socket, time
from datetime import datetime

ssa = SSA3000X('10.1.1.60')
button_sock = socket.socket()
button_sock.connect(('localhost', 5102))

# Configure button
button_sock.sendall(b'CONF:LABEL Capture\n')
button_sock.sendall(b'CONF:COL #00ff00\n')

# Monitor presses and capture screenshots
last_count = 0
while True:
    button_sock.sendall(b'STAT:COUNT?\n')
    time.sleep(0.01)
    response = button_sock.recv(1024).decode().strip()
    if response:
        try:
            current_count = int(response)
            if current_count > last_count:
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                filename = f"ssa_capture_{timestamp}.png"
                ssa.save_screenshot(filename)
                print(f"Captured: {filename}")
                last_count = current_count
        except ValueError:
            pass
    time.sleep(0.1)
```

### Multi-button panel (run 3 buttons on different ports)
```python
import socket, time
from rf_bench.siglent import SSA3000X

ssa = SSA3000X('10.1.1.60')

# Button 1: Peak Search (port 8102)
# Button 2: Marker to Center (port 8103)
# Button 3: Screenshot (port 8104)

button1 = socket.socket()
button1.connect(('localhost', 5102))
button1.sendall(b'CONF:LABEL Peak\n')

button2 = socket.socket()
button2.connect(('localhost', 5103))  # Next button (not built yet)
button2.sendall(b'CONF:LABEL Center\n')

# Monitor all buttons...
```

### Antenna tuner trigger
```python
import socket, time

# Connect to antenna tuner (could be an IC-7300 or external tuner)
tuner_sock = socket.socket()
tuner_sock.connect(('192.168.1.50', 5025))

# Connect to button
button_sock = socket.socket()
button_sock.connect(('localhost', 5102))
button_sock.sendall(b'CONF:LABEL Tune\n')
button_sock.sendall(b'CONF:COL #ff8800\n')

# Monitor button and trigger tuner
last_count = 0
while True:
    button_sock.sendall(b'STAT:COUNT?\n')
    time.sleep(0.01)
    response = button_sock.recv(1024).decode().strip()
    if response:
        try:
            current_count = int(response)
            if current_count > last_count:
                print("Starting antenna tuner...")
                tuner_sock.sendall(b'TUNE:START\n')
                last_count = current_count
        except ValueError:
            pass
    time.sleep(0.1)
```

### ESP32 relay pulse trigger
```python
import socket, time

# Connect to ESP32 relay controller
relay_sock = socket.socket()
relay_sock.connect(('192.168.1.42', 5025))

# Connect to button
button_sock = socket.socket()
button_sock.connect(('localhost', 5102))
button_sock.sendall(b'CONF:LABEL Pulse\n')
button_sock.sendall(b'CONF:COL #00ff00\n')

# Monitor button and pulse relay
last_count = 0
while True:
    button_sock.sendall(b'STAT:COUNT?\n')
    time.sleep(0.01)
    response = button_sock.recv(1024).decode().strip()
    if response:
        try:
            current_count = int(response)
            if current_count > last_count:
                print("Pulsing relay...")
                relay_sock.sendall(b'ROUT:CLOS (@1)\n')  # Close
                time.sleep(0.5)
                relay_sock.sendall(b'ROUT:OPEN (@1)\n')  # Open
                last_count = current_count
        except ValueError:
            pass
    time.sleep(0.1)
```

### MQTT Integration (bidirectional)
```bash
# Configure MQTT
echo "MQTT:CONF localhost,button/trigger,button/pressed" | nc localhost 5102

# Trigger button remotely
mosquitto_pub -h localhost -t button/trigger -m "1"

# Listen for button presses
mosquitto_sub -h localhost -t button/pressed
```

```python
import paho.mqtt.client as mqtt
import time

def on_message(client, userdata, msg):
    print(f"Button was pressed! (count in message)")

client = mqtt.Client()
client.on_message = on_message
client.connect("localhost", 1883, 60)
client.subscribe("button/pressed")
client.loop_start()

# Trigger button remotely
time.sleep(1)
client.publish("button/trigger", "PRESS")
time.sleep(1)
client.publish("button/trigger", "1")

time.sleep(5)
client.loop_stop()
```

## Use Cases

- **Sweep/scan triggers** (SSA, SDR, oscilloscope)
- **Screenshot/capture** (save instrument state)
- **Peak search** (spectrum analyzer)
- **Marker operations** (marker to center, next peak)
- **Calibration triggers** (start cal routine)
- **Antenna tuner** (start tuning cycle)
- **Pulse generation** (relay pulse, gate pulse)
- **Mode changes** (cycle through modes)
- **Data logging** (start/stop recording)
- **Test sequence triggers** (run automated test)

## Momentary vs Toggle

Unlike the **toggle switch** which maintains state (ON/OFF), the **button** is momentary:
- Press event happens immediately
- Button "releases" after ~200ms
- Useful for triggering one-shot actions
- Press counter tracks total activations

For maintained state (ON/OFF), use the **toggle switch** instead.

## Files

```
button/
├── backend/
│   └── server.py          # FastAPI + SCPI + WebSocket + MQTT (bidirectional)
├── frontend/
│   └── index.html         # Interactive push button with animation
└── README.md              # This file
```

## See Also

- [slider](../slider/) — Analog continuous control
- [toggle](../toggle/) — Maintained ON/OFF switch
- [knob](../knob/) — Rotary control (coming soon)
- [PORT-ASSIGNMENTS.md](../PORT-ASSIGNMENTS.md) — Port allocations
- [workbench.md](../../workbench.md) — Virtual instrument architecture
