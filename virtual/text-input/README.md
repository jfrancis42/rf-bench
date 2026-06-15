# Virtual Text Input

🔨 **Status: Built 2026-06-14** — Phase 2 interactive control (text input field)

SCPI-controlled text input with **bidirectional** communication. Users can type arbitrary commands/messages in the browser, or external SCPI/MQTT commands can send text to the display. Includes command history with recall.

## Features

- **SCPI TCP server** on port 5104 (IEEE 488.2 standard)
- **Bidirectional WebSocket** for instant updates
- **Text input field** with configurable rows (single-line or multi-line)
- **Command history** with configurable depth (0-100 entries)
- **Click-to-recall** history items
- **Enter to send** (Shift+Enter for newline in multi-row mode)
- **Configurable labels** and placeholder text
- **MQTT bidirectional** (subscribe to receive, publish on user submit)

## Ports

- **SCPI:** `tcp://0.0.0.0:5104`
- **HTTP:** `http://0.0.0.0:8104`
- **WebSocket:** `ws://0.0.0.0:8104/ws` (bidirectional)
- **MQTT:** Configurable via `MQTT:CONF` command

## SCPI Commands

### Text Input
- `TEXT:SEND <string>` — Send text (adds to history, triggers display update)
- `TEXT:SEND?` — Query last sent text
- `TEXT:HIST?` — Query command history (newline-separated, most recent last)
- `TEXT:HIST:CLEAR` — Clear command history

### Configuration
- `CONF:LABEL <string>` — Set input label (default "Command")
- `CONF:LABEL?` — Query input label
- `CONF:ROWS <int>` — Set number of rows (1-10, default 1)
- `CONF:ROWS?` — Query number of rows
- `CONF:HIST <int>` — Set history depth (0-100, default 20)
- `CONF:HIST?` — Query history depth
- `CONF:PLACEHOLDER <string>` — Set placeholder text
- `CONF:PLACEHOLDER?` — Query placeholder text

### IEEE 488.2 Standard
- `*IDN?` — Identification query
- `*RST` — Reset to defaults (clears history)
- `SYST:ERR?` — Query error queue

### MQTT
- `MQTT:CONF <host>,<sub_topic>[,<pub_topic>]` — Configure MQTT
  - `sub_topic`: Topic to subscribe (receive text input)
  - `pub_topic`: Topic to publish (send user-submitted text)
- `MQTT:CONF?` — Query MQTT configuration

## Bidirectional Flow

```
User types text + Enter → WebSocket → Backend → MQTT pub_topic
                                            ↓
                                         History updated
                                         SCPI clients can query

External SCPI TEXT:SEND → Backend → WebSocket → Browser displays
                             ↓
                          MQTT published

MQTT message arrives → Backend → WebSocket → Browser displays
                          ↓
                       History updated
```

## Quick Start

```bash
# Start the server
cd ~/Dropbox/build/rf-bench/virtual/text-input/backend
python3 server.py

# Open in browser
xdg-open http://localhost:8104
```

## Configuration Examples

### Single-line SCPI command input
```bash
echo "CONF:LABEL SCPI Command" | nc localhost 5104
echo "CONF:ROWS 1" | nc localhost 5104
echo "CONF:PLACEHOLDER Enter SCPI command..." | nc localhost 5104
echo "CONF:HIST 50" | nc localhost 5104
```

### Multi-line script editor (3 rows)
```bash
echo "CONF:LABEL Script" | nc localhost 5104
echo "CONF:ROWS 3" | nc localhost 5104
echo "CONF:PLACEHOLDER Enter script (Shift+Enter for newline)..." | nc localhost 5104
```

### Debug console (large history)
```bash
echo "CONF:LABEL Debug Console" | nc localhost 5104
echo "CONF:ROWS 1" | nc localhost 5104
echo "CONF:HIST 100" | nc localhost 5104
```

### MQTT topic input
```bash
echo "CONF:LABEL MQTT Message" | nc localhost 5104
echo "CONF:PLACEHOLDER Enter message to publish..." | nc localhost 5104
```

## Integration Examples

### SCPI command relay to instrument
```python
import socket, threading, time

# Connect to text input
text_sock = socket.socket()
text_sock.connect(('localhost', 5104))

# Connect to SSA
ssa_sock = socket.socket()
ssa_sock.connect(('10.1.1.60', 5025))

# Configure text input
text_sock.sendall(b'CONF:LABEL SSA3032X Command\n')
text_sock.sendall(b'CONF:PLACEHOLDER Enter SCPI command...\n')

# Poll for new commands and forward to SSA
last_text = ""
while True:
    text_sock.sendall(b'TEXT:SEND?\n')
    time.sleep(0.01)
    response = text_sock.recv(1024).decode().strip()
    if response and response != last_text:
        last_text = response
        print(f"Forwarding to SSA: {last_text}")
        ssa_sock.sendall(f"{last_text}\n".encode())
        time.sleep(0.01)
        
        # Read response if query
        if '?' in last_text:
            ssa_response = ssa_sock.recv(1024).decode().strip()
            print(f"SSA response: {ssa_response}")
    
    time.sleep(0.1)
```

### Interactive history recall
```python
import socket

text_sock = socket.socket()
text_sock.connect(('localhost', 5104))

# Send some test commands
for cmd in ["*IDN?", "FREQ:CENT 100MHz", "SPAN 10MHz", "BW 10kHz"]:
    text_sock.sendall(f'TEXT:SEND {cmd}\n'.encode())
    time.sleep(0.5)

# Query history
text_sock.sendall(b'TEXT:HIST?\n')
time.sleep(0.01)
history = text_sock.recv(4096).decode().strip()
print("Command history:")
print(history)
```

### Log all user input to file
```python
import socket, time
from datetime import datetime

text_sock = socket.socket()
text_sock.connect(('localhost', 5104))

text_sock.sendall(b'CONF:LABEL Command Logger\n')

last_text = ""
with open('command_log.txt', 'a') as log:
    while True:
        text_sock.sendall(b'TEXT:SEND?\n')
        time.sleep(0.01)
        response = text_sock.recv(1024).decode().strip()
        if response and response != last_text:
            last_text = response
            timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            log_line = f"[{timestamp}] {last_text}\n"
            log.write(log_line)
            log.flush()
            print(log_line.strip())
        
        time.sleep(0.1)
```

### Multi-instrument command dispatcher
```python
import socket, time, re

text_sock = socket.socket()
text_sock.connect(('localhost', 5104))

# Connect to multiple instruments
ssa = socket.socket()
ssa.connect(('10.1.1.60', 5025))

sdg = socket.socket()
sdg.connect(('10.1.1.55', 5025))

spd = socket.socket()
spd.connect(('10.1.1.56', 5025))

text_sock.sendall(b'CONF:LABEL Multi-Instrument Command\n')
text_sock.sendall(b'CONF:PLACEHOLDER Prefix: SSA:, SDG:, SPD:...\n')

# Parse prefix and route commands
last_text = ""
while True:
    text_sock.sendall(b'TEXT:SEND?\n')
    time.sleep(0.01)
    response = text_sock.recv(1024).decode().strip()
    
    if response and response != last_text:
        last_text = response
        
        # Route based on prefix
        if response.upper().startswith('SSA:'):
            cmd = response[4:].strip()
            print(f"→ SSA: {cmd}")
            ssa.sendall(f"{cmd}\n".encode())
            
        elif response.upper().startswith('SDG:'):
            cmd = response[4:].strip()
            print(f"→ SDG: {cmd}")
            sdg.sendall(f"{cmd}\n".encode())
            
        elif response.upper().startswith('SPD:'):
            cmd = response[4:].strip()
            print(f"→ SPD: {cmd}")
            spd.sendall(f"{cmd}\n".encode())
        
        else:
            print(f"Unknown prefix: {response}")
    
    time.sleep(0.1)
```

### MQTT remote control interface
```bash
# Configure MQTT
echo "MQTT:CONF localhost,control/input,control/commands" | nc localhost 5104

# Send commands remotely
mosquitto_pub -h localhost -t control/input -m "*IDN?"
mosquitto_pub -h localhost -t control/input -m "FREQ:CENT 1GHz"

# Listen for user submissions
mosquitto_sub -h localhost -t control/commands
```

```python
import paho.mqtt.client as mqtt
import time

def on_message(client, userdata, msg):
    print(f"User submitted: {msg.payload.decode()}")

client = mqtt.Client()
client.on_message = on_message
client.connect("localhost", 1883, 60)
client.subscribe("control/commands")
client.loop_start()

# Send commands to the text input
time.sleep(1)
client.publish("control/input", "FREQ:CENT 2.4GHz")
time.sleep(1)
client.publish("control/input", "SPAN 100MHz")

time.sleep(5)
client.loop_stop()
```

### Script sequencer with history
```python
import socket, time

text_sock = socket.socket()
text_sock.connect(('localhost', 5104))

text_sock.sendall(b'CONF:LABEL Script Sequencer\n')
text_sock.sendall(b'CONF:ROWS 5\n')
text_sock.sendall(b'CONF:PLACEHOLDER Enter multi-line script...\n')

# Monitor for script submissions
last_text = ""
while True:
    text_sock.sendall(b'TEXT:SEND?\n')
    time.sleep(0.01)
    response = text_sock.recv(1024).decode().strip()
    
    if response and response != last_text:
        last_text = response
        print("Executing script:")
        print(response)
        print("---")
        
        # Split multi-line script and execute each line
        for line in response.split('\n'):
            line = line.strip()
            if line and not line.startswith('#'):
                print(f"  → {line}")
                # Execute line on instrument here
                time.sleep(0.2)
        
        print("Script complete\n")
    
    time.sleep(0.1)
```

### LabVIEW/MATLAB command interface
```python
# Simple TCP server that forwards text input to LabVIEW/MATLAB
import socket, threading, time

text_sock = socket.socket()
text_sock.connect(('localhost', 5104))

text_sock.sendall(b'CONF:LABEL LabVIEW Command\n')

# Create TCP server for LabVIEW to poll
server = socket.socket()
server.bind(('localhost', 5555))
server.listen(1)

print("Waiting for LabVIEW connection on port 5555...")
labview_conn, addr = server.accept()
print(f"LabVIEW connected from {addr}")

# Forward text input to LabVIEW
last_text = ""
while True:
    text_sock.sendall(b'TEXT:SEND?\n')
    time.sleep(0.01)
    response = text_sock.recv(1024).decode().strip()
    
    if response and response != last_text:
        last_text = response
        print(f"Forwarding to LabVIEW: {last_text}")
        try:
            labview_conn.sendall(f"{last_text}\n".encode())
        except:
            print("LabVIEW disconnected")
            break
    
    time.sleep(0.1)
```

## Use Cases

- **SCPI command terminal** for manual instrument control
- **Multi-instrument dispatcher** (prefix-based routing)
- **Debug console** with command history
- **Script sequencer** (multi-line scripts)
- **MQTT remote control** interface
- **Command logger** (audit trail)
- **Test automation** (scripted command sequences)
- **LabVIEW/MATLAB integration** (external control)
- **Chatbot interface** (control via natural language → SCPI)
- **Educational tool** (learn SCPI interactively)

## Single-line vs Multi-line

- **Single-line (CONF:ROWS 1):** Enter key sends immediately
- **Multi-line (CONF:ROWS 2-10):** Shift+Enter for newline, Enter alone sends

Multi-line mode useful for:
- JSON payloads
- Multi-command scripts
- Long text messages
- Configuration files

## History Behavior

- History depth configurable via `CONF:HIST` (0-100, default 20)
- Most recent entries displayed first (reversed)
- Click any history item to recall into input field
- History survives WebSocket reconnect (stored on backend)
- History cleared by `*RST` or `TEXT:HIST:CLEAR`

## Files

```
text-input/
├── backend/
│   └── server.py          # FastAPI + SCPI + WebSocket + MQTT (bidirectional)
├── frontend/
│   └── index.html         # Text input with history and recall
└── README.md              # This file
```

## See Also

- [slider](../slider/) — Analog continuous control
- [toggle](../toggle/) — Maintained ON/OFF switch
- [button](../button/) — Momentary push button
- [knob](../knob/) — Rotary control
- [PORT-ASSIGNMENTS.md](../PORT-ASSIGNMENTS.md) — Port allocations
- [workbench.md](../../workbench.md) — Virtual instrument architecture
