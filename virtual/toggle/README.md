# Virtual Toggle Switch

🔨 **Status: Built 2026-06-14** — Phase 2 interactive control (bidirectional ON/OFF switch)

SCPI-controlled toggle switch with **bidirectional** communication. Users can click the switch in the browser to control instruments, or external SCPI/MQTT commands can change the state. Perfect for enabling/disabling outputs, modes, or features.

## Features

- **SCPI TCP server** on port 5101 (IEEE 488.2 standard)
- **Bidirectional WebSocket** for instant updates (user → instrument → user)
- **Interactive toggle switch** with smooth animation
- **Configurable labels** (main label, ON label, OFF label)
- **Customizable colors** (ON color, OFF color)
- **Adjustable size** (50-200 pixels)
- **MQTT bidirectional** (subscribe to receive, publish on user change)

## Ports

- **SCPI:** `tcp://0.0.0.0:5101`
- **HTTP:** `http://0.0.0.0:8101`
- **WebSocket:** `ws://0.0.0.0:8101/ws` (bidirectional)
- **MQTT:** Configurable via `MQTT:CONF` command

## SCPI Commands

### State Control
- `STAT:VAL <bool>` — Set switch state (0/1, OFF/ON, FALSE/TRUE)
- `STAT:VAL?` — Query current state (returns 0 or 1)

### Configuration
- `CONF:LABEL <string>` — Set switch label (default "Switch")
- `CONF:LABEL?` — Query switch label
- `CONF:ONCOL <color>` — Set ON color (hex, default "#00ff00")
- `CONF:ONCOL?` — Query ON color
- `CONF:OFFCOL <color>` — Set OFF color (hex, default "#444444")
- `CONF:OFFCOL?` — Query OFF color
- `CONF:ONLABEL <string>` — Set ON state label (default "ON")
- `CONF:ONLABEL?` — Query ON label
- `CONF:OFFLABEL <string>` — Set OFF state label (default "OFF")
- `CONF:OFFLABEL?` — Query OFF label
- `CONF:SIZE <int>` — Set switch size in pixels (50-200, default 100)
- `CONF:SIZE?` — Query switch size

### IEEE 488.2 Standard
- `*IDN?` — Identification query
- `*RST` — Reset to defaults
- `SYST:ERR?` — Query error queue

### MQTT
- `MQTT:CONF <host>,<sub_topic>[,<pub_topic>]` — Configure MQTT
  - `sub_topic`: Topic to subscribe (receive state changes)
  - `pub_topic`: Topic to publish (send user clicks)
- `MQTT:CONF?` — Query MQTT configuration

## Bidirectional Flow

```
User clicks switch → WebSocket → Backend → MQTT pub_topic
                                        ↓
                                     SCPI clients notified

External SCPI command → Backend → WebSocket → Browser updates switch
                            ↓
                         MQTT published

MQTT message arrives → Backend → WebSocket → Browser updates switch
                           ↓
                        SCPI clients notified
```

## Quick Start

```bash
# Start the server
cd ~/Dropbox/build/rf-bench/virtual/toggle/backend
python3 server.py

# Open in browser
xdg-open http://localhost:8101
```

## Configuration Examples

### PSU output enable (green ON, gray OFF)
```bash
echo "CONF:LABEL PSU Output" | nc localhost 5101
echo "CONF:ONCOL #00ff00" | nc localhost 5101
echo "CONF:OFFCOL #444444" | nc localhost 5101
echo "CONF:ONLABEL ENABLED" | nc localhost 5101
echo "CONF:OFFLABEL DISABLED" | nc localhost 5101
echo "STAT:VAL 1" | nc localhost 5101  # Turn ON
```

### PTT (Push-to-Talk) indicator (red ON, dark OFF)
```bash
echo "CONF:LABEL PTT" | nc localhost 5101
echo "CONF:ONCOL #ff0000" | nc localhost 5101
echo "CONF:OFFCOL #440000" | nc localhost 5101
echo "CONF:ONLABEL TX" | nc localhost 5101
echo "CONF:OFFLABEL RX" | nc localhost 5101
echo "STAT:VAL 0" | nc localhost 5101  # Set to RX
```

### Tracking generator enable (orange ON)
```bash
echo "CONF:LABEL Tracking Gen" | nc localhost 5101
echo "CONF:ONCOL #ff8800" | nc localhost 5101
echo "CONF:OFFCOL #663300" | nc localhost 5101
echo "STAT:VAL 1" | nc localhost 5101
```

### AGC mode (blue theme)
```bash
echo "CONF:LABEL AGC" | nc localhost 5101
echo "CONF:ONCOL #4488ff" | nc localhost 5101
echo "CONF:OFFCOL #222244" | nc localhost 5101
echo "CONF:ONLABEL AUTO" | nc localhost 5101
echo "CONF:OFFLABEL MANUAL" | nc localhost 5101
```

## Integration Examples

### SPD3303X PSU output control
```python
from rf_bench.siglent import SPD3303X
import socket, time

psu = SPD3303X('10.1.1.56')
toggle_sock = socket.socket()
toggle_sock.connect(('localhost', 5101))

# Configure toggle
toggle_sock.sendall(b'CONF:LABEL CH1 Output\n')
toggle_sock.sendall(b'CONF:ONCOL #00ff00\n')
toggle_sock.sendall(b'CONF:OFFCOL #444444\n')

# Sync initial state
current_state = psu.get_output(1)
toggle_sock.sendall(f'STAT:VAL {1 if current_state else 0}\n'.encode())

# Poll toggle for changes
while True:
    toggle_sock.sendall(b'STAT:VAL?\n')
    time.sleep(0.01)
    response = toggle_sock.recv(1024).decode().strip()
    if response:
        try:
            new_state = (response == '1')
            if new_state != current_state:
                psu.set_output(1, new_state)
                current_state = new_state
                print(f'PSU CH1: {"ON" if new_state else "OFF"}')
        except ValueError:
            pass
    time.sleep(0.1)
```

### SSA tracking generator control
```python
from rf_bench.siglent import SSA3000X
import socket, time

ssa = SSA3000X('10.1.1.60')
toggle_sock = socket.socket()
toggle_sock.connect(('localhost', 5101))

# Configure toggle
toggle_sock.sendall(b'CONF:LABEL Tracking Gen\n')
toggle_sock.sendall(b'CONF:ONCOL #ff8800\n')

# Get initial state
tg_enabled = ssa.get_tracking_generator()
toggle_sock.sendall(f'STAT:VAL {1 if tg_enabled else 0}\n'.encode())

# Bidirectional control
while True:
    # Check toggle for user changes
    toggle_sock.sendall(b'STAT:VAL?\n')
    time.sleep(0.01)
    response = toggle_sock.recv(1024).decode().strip()
    if response:
        try:
            new_state = (response == '1')
            if new_state != tg_enabled:
                ssa.set_tracking_generator(new_state)
                tg_enabled = new_state
                print(f'Tracking Gen: {"ON" if new_state else "OFF"}')
        except ValueError:
            pass
    time.sleep(0.2)
```

### Radio AGC control (IC-7300)
```python
from rf_bench.icom import IC7300
import socket, time

radio = IC7300()
toggle_sock = socket.socket()
toggle_sock.connect(('localhost', 5101))

# Configure toggle
toggle_sock.sendall(b'CONF:LABEL AGC\n')
toggle_sock.sendall(b'CONF:ONCOL #4488ff\n')
toggle_sock.sendall(b'CONF:ONLABEL AUTO\n')
toggle_sock.sendall(b'CONF:OFFLABEL MANUAL\n')

# Get initial AGC mode
current_agc = radio.get_agc()
agc_auto = (current_agc != 'off')
toggle_sock.sendall(f'STAT:VAL {1 if agc_auto else 0}\n'.encode())

# Control AGC
while True:
    toggle_sock.sendall(b'STAT:VAL?\n')
    time.sleep(0.01)
    response = toggle_sock.recv(1024).decode().strip()
    if response:
        try:
            new_state = (response == '1')
            if new_state != agc_auto:
                if new_state:
                    radio.set_agc('fast')  # or 'slow'/'mid'
                else:
                    radio.set_agc('off')
                agc_auto = new_state
                print(f'AGC: {"AUTO" if new_state else "MANUAL"}')
        except ValueError:
            pass
    time.sleep(0.2)
```

### ESP32 relay control
```python
import socket, time

# Connect to ESP32 SCPI relay controller
relay_sock = socket.socket()
relay_sock.connect(('192.168.1.42', 5025))

# Connect to toggle
toggle_sock = socket.socket()
toggle_sock.connect(('localhost', 5101))

# Configure toggle
toggle_sock.sendall(b'CONF:LABEL Relay 1\n')
toggle_sock.sendall(b'CONF:ONCOL #00ff00\n')

# Get initial relay state
relay_sock.sendall(b'ROUT:CLOS? (@1)\n')
time.sleep(0.1)
current_state = (relay_sock.recv(1024).decode().strip() == '1')
toggle_sock.sendall(f'STAT:VAL {1 if current_state else 0}\n'.encode())

# Control relay
while True:
    toggle_sock.sendall(b'STAT:VAL?\n')
    time.sleep(0.01)
    response = toggle_sock.recv(1024).decode().strip()
    if response:
        try:
            new_state = (response == '1')
            if new_state != current_state:
                if new_state:
                    relay_sock.sendall(b'ROUT:CLOS (@1)\n')
                else:
                    relay_sock.sendall(b'ROUT:OPEN (@1)\n')
                current_state = new_state
                print(f'Relay 1: {"CLOSED" if new_state else "OPEN"}')
        except ValueError:
            pass
    time.sleep(0.1)
```

### MQTT Integration (bidirectional)
```bash
# Configure MQTT with both subscribe and publish topics
echo "MQTT:CONF localhost,toggle/in,toggle/out" | nc localhost 5101

# Now:
# - Messages (0 or 1) published to toggle/in will update the switch
# - User clicking the switch will publish to toggle/out
```

```python
import paho.mqtt.client as mqtt
import time

def on_message(client, userdata, msg):
    state = msg.payload.decode()
    print(f"Switch changed to: {'ON' if state == '1' else 'OFF'}")

client = mqtt.Client()
client.on_message = on_message
client.connect("localhost", 1883, 60)
client.subscribe("toggle/out")  # Listen for user clicks
client.loop_start()

# Control switch remotely
client.publish("toggle/in", "1")  # Turn ON
time.sleep(2)
client.publish("toggle/in", "0")  # Turn OFF

time.sleep(5)
client.loop_stop()
```

## Use Cases

- **PSU output enable/disable**
- **Tracking generator ON/OFF**
- **Radio features** (AGC, preamp, attenuator, noise blanker)
- **Relay control** (antenna switching, routing)
- **Mode selection** (binary choices: auto/manual, local/remote)
- **Feature flags** (enable/disable specific functionality)
- **Safety interlocks** (enable/disable with visual confirmation)
- **Data logging** (start/stop recording)

## Boolean Value Parsing

The toggle accepts multiple formats for boolean values:

**TRUE values:** `1`, `TRUE`, `ON`, `YES` (case-insensitive)  
**FALSE values:** `0`, `FALSE`, `OFF`, `NO` (case-insensitive)

Examples:
```bash
echo "STAT:VAL 1" | nc localhost 5101
echo "STAT:VAL ON" | nc localhost 5101
echo "STAT:VAL true" | nc localhost 5101
```

All set the switch to ON.

## Files

```
toggle/
├── backend/
│   └── server.py          # FastAPI + SCPI + WebSocket + MQTT (bidirectional)
├── frontend/
│   └── index.html         # Interactive toggle switch
└── README.md              # This file
```

## See Also

- [slider](../slider/) — Analog continuous control
- [button](../button/) — Momentary push button (coming soon)
- [PORT-ASSIGNMENTS.md](../PORT-ASSIGNMENTS.md) — Port allocations
- [workbench.md](../../workbench.md) — Virtual instrument architecture
