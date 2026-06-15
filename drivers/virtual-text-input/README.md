# rf-bench-drivers-virtual-text-input

Python driver for **Virtual Text Input** SCPI instrument. Provides an interactive text entry field with command history, multi-line input, and bidirectional MQTT integration via SCPI-over-TCP (port 5104).

## Installation

```bash
pip install rf-bench-drivers-virtual-text-input
```

## Quick Start

### Basic Text Input

```python
from rf_bench.virtual import VirtualTextInput

# Simple text entry
with VirtualTextInput("10.1.1.52") as text_input:
    text_input.send("FREQ:CENT 100MHz")
    last = text_input.get_last()
    print(f"Last command: {last}")
```

### Interactive Command History

```python
from rf_bench.virtual import VirtualTextInput

with VirtualTextInput("10.1.1.52") as text_input:
    # Configure display
    text_input.configure(
        label="SCPI Command",
        rows=3,
        placeholder="Enter instrument command...",
        history_depth=50
    )
    
    # Send commands
    text_input.send("*IDN?")
    text_input.send("FREQ:CENT 100MHz")
    text_input.send("POW -10dBm")
    
    # Review history
    history = text_input.get_history()
    for i, cmd in enumerate(history, 1):
        print(f"{i}. {cmd}")
```

### MQTT Bidirectional Integration

```python
from rf_bench.virtual import VirtualTextInput

with VirtualTextInput("10.1.1.52") as text_input:
    # Configure MQTT
    text_input.configure_mqtt(
        host="mqtt.n0gq.org",
        sub_topic="scpi/commands/in",    # Receive commands from MQTT
        pub_topic="scpi/commands/out"    # Publish commands to MQTT
    )
    
    # Send command (also publishes to MQTT)
    text_input.send("FREQ:CENT 14.2MHz")
    
    # Any messages on sub_topic appear in the UI automatically
```

## Multi-Instance Usage

For multiple text-inputs controlled by a single backend (e.g., via BenchView), use the multi-instance driver:

```python
from rf_bench.virtual import VirtualTextInputMulti

# Connect to multi-instance backend
# Port is assigned by BenchView and read from *_ports.yaml
text_inputs = VirtualTextInputMulti("localhost", port=5100)

# Control individual instances (1-based indexing)
text_inputs.set_value(1, 50.0)  # Instance 1
text_inputs.set_value(2, 75.0)  # Instance 2
text_inputs.set_label(1, "Channel 1")
text_inputs.set_label(2, "Channel 2")

# Query instance count
count = text_inputs.get_count()  # → 2

text_inputs.close()
```

**Multi-instance backend:**

```bash
cd ~/Dropbox/build/rf-bench/virtual/text-input/backend
python3 server-multi.py --scpi-port 5100 --http-port 8100 --count 2 --layout row
```

**Port Assignment:**

When using BenchView, ports are assigned dynamically and exported to:
- `~/.rf-bench/<panel-name>_ports.yaml` (inventory overlay)
- `<config-dir>/<panel-name>_ports.yaml` (legacy)

Bridge scripts should read port assignments from the YAML file rather than hardcoding them.

## Backend Server

The driver connects to a virtual text input backend server:

```bash
cd ~/Dropbox/build/rf-bench/virtual/text-input/backend
python3 server.py
```

Open browser at `http://localhost:8104` to see the text input interface.

Server ports:
- **SCPI TCP**: 5104
- **HTTP/WebSocket**: 8104

## API Reference

### Connection

```python
VirtualTextInput(host, port=5104, timeout=2.0)
```

- **host**: IP address or hostname of backend server
- **port**: SCPI TCP port (default 5104)
- **timeout**: Socket timeout in seconds

### IEEE 488.2 Commands

```python
text_input.idn()           # → "N0GQ,Virtual-TextInput,1.0,2026"
text_input.reset()         # Reset to defaults
text_input.get_error()     # → "0,No error"
```

### Text Commands

```python
# Send text
text_input.send("FREQ:CENT 100MHz")
text_input.send("Multi-line\ntext\nsupported")

# Query last sent text
last = text_input.get_last()  # → "Multi-line\ntext\nsupported"

# Get command history (list, most recent last)
history = text_input.get_history()  # → ["FREQ:CENT 100MHz", ...]

# Clear history
text_input.clear_history()
```

### Configuration

```python
# Input field label
text_input.set_label("SCPI Command")
text_input.get_label()  # → "SCPI Command"

# Number of rows (1=input, >1=textarea)
text_input.set_rows(3)  # 1-10
text_input.get_rows()   # → 3

# Placeholder text
text_input.set_placeholder("Enter command...")
text_input.get_placeholder()  # → "Enter command..."

# History depth
text_input.set_history_depth(50)  # 0-100
text_input.get_history_depth()    # → 50

# Convenience: configure all at once
text_input.configure(
    label="SCPI Input",
    rows=5,
    placeholder="Type here...",
    history_depth=100
)
```

### MQTT Integration

```python
# Configure MQTT (bidirectional)
text_input.configure_mqtt(
    host="mqtt.n0gq.org",
    sub_topic="scpi/in",   # Receive from MQTT → display
    pub_topic="scpi/out"   # Send to MQTT when user submits
)

# Query MQTT config
config = text_input.get_mqtt_config()
# → {"host": "mqtt.n0gq.org", "sub_topic": "scpi/in", "pub_topic": "scpi/out"}
# → None if not configured
```

## Common Use Cases

### Manual Instrument Control

```python
from rf_bench.virtual import VirtualTextInput
from rf_bench.siglent import SSA3000X

# Control spectrum analyzer via text input
ssa = SSA3000X("10.1.1.60")
text_input = VirtualTextInput("10.1.1.52")

text_input.configure(
    label="SSA3000X Command",
    rows=2,
    placeholder="Enter SCPI command for spectrum analyzer..."
)

# User types commands in browser → SCPI client reads them
while True:
    last_cmd = text_input.get_last()
    if last_cmd:
        try:
            # Send to real instrument
            response = ssa._query(last_cmd)
            print(f"SSA: {response}")
        except Exception as e:
            print(f"Error: {e}")
```

### Command Logging and Replay

```python
from rf_bench.virtual import VirtualTextInput
import json
import time

text_input = VirtualTextInput("10.1.1.52")

# Log all commands to file
log_file = "scpi_commands.json"

try:
    while True:
        history = text_input.get_history()
        with open(log_file, 'w') as f:
            json.dump({
                "timestamp": time.time(),
                "commands": history
            }, f, indent=2)
        time.sleep(5)
except KeyboardInterrupt:
    print(f"Commands logged to {log_file}")

# Replay logged commands
with open(log_file) as f:
    data = json.load(f)
    for cmd in data["commands"]:
        text_input.send(cmd)
        time.sleep(0.5)
```

### MQTT Command Bridge

```python
from rf_bench.virtual import VirtualTextInput
from rf_bench.siglent import SDG1000X

# Bridge MQTT commands to real instrument
text_input = VirtualTextInput("10.1.1.52")
sdg = SDG1000X("10.1.1.55")

text_input.configure_mqtt(
    host="mqtt.n0gq.org",
    sub_topic="lab/sdg/commands",
    pub_topic="lab/sdg/responses"
)

# Poll text input for MQTT-received commands
last_cmd = ""
while True:
    current_cmd = text_input.get_last()
    if current_cmd != last_cmd:
        try:
            # Execute on real instrument
            if '?' in current_cmd:
                response = sdg._query(current_cmd)
                print(f"SDG response: {response}")
            else:
                sdg._write(current_cmd)
            last_cmd = current_cmd
        except Exception as e:
            print(f"Error: {e}")
    time.sleep(0.1)
```

### Test Automation with Command History

```python
from rf_bench.virtual import VirtualTextInput
import time

text_input = VirtualTextInput("10.1.1.52")
text_input.configure(label="Test Sequence", rows=5, history_depth=100)

# Test sequence
commands = [
    "*RST",
    "FREQ:CENT 14.2MHz",
    "FREQ:SPAN 1MHz",
    "POW:ATT 10dB",
    "BAND:RES 10kHz",
    "TRAC:MODE MAXH"
]

for cmd in commands:
    text_input.send(cmd)
    print(f"Sent: {cmd}")
    time.sleep(1)

# Verify all commands executed
history = text_input.get_history()
assert commands == history[-len(commands):]
print("Test sequence complete")
```

### Multi-Line Script Input

```python
from rf_bench.virtual import VirtualTextInput

text_input = VirtualTextInput("10.1.1.52")
text_input.configure(
    label="Python Script",
    rows=10,
    placeholder="Enter multi-line Python code..."
)

# Send multi-line script
script = """
for freq in range(14_000_000, 14_350_000, 10_000):
    set_frequency(freq)
    measure_power()
    time.sleep(0.1)
"""

text_input.send(script)

# Retrieve for execution
retrieved = text_input.get_last()
exec(retrieved)  # Execute the script
```

### Remote Lab Control Dashboard

```python
from rf_bench.virtual import VirtualTextInput
import paho.mqtt.client as mqtt
import json

text_input = VirtualTextInput("10.1.1.52")
text_input.configure(
    label="Remote Lab Command",
    rows=4,
    placeholder="Enter command for remote lab...",
    history_depth=200
)

# Configure MQTT for remote access
text_input.configure_mqtt(
    host="mqtt.n0gq.org",
    sub_topic="lab/remote/cmd",
    pub_topic="lab/remote/status"
)

# Local MQTT client listens and responds
def on_message(client, userdata, msg):
    cmd = msg.payload.decode()
    print(f"Executing remote command: {cmd}")
    
    # Execute command and publish result
    result = execute_lab_command(cmd)
    client.publish("lab/remote/status", json.dumps(result))

mqtt_client = mqtt.Client()
mqtt_client.on_message = on_message
mqtt_client.connect("mqtt.n0gq.org", 1883, 60)
mqtt_client.subscribe("lab/remote/cmd")
mqtt_client.loop_start()

print("Remote lab control active. Commands via MQTT or web UI.")
try:
    while True:
        time.sleep(1)
except KeyboardInterrupt:
    mqtt_client.loop_stop()
```

### Interactive Debugging Session

```python
from rf_bench.virtual import VirtualTextInput
from rf_bench.siglent import SSA3000X, SDG1000X

# Debug multiple instruments interactively
text_input = VirtualTextInput("10.1.1.52")
text_input.configure(
    label="Debug Console",
    rows=3,
    placeholder="instrument.command (e.g., ssa.get_center())",
    history_depth=100
)

ssa = SSA3000X("10.1.1.60")
sdg = SDG1000X("10.1.1.55")

# Allow arbitrary Python execution
import code
locals_dict = {"ssa": ssa, "sdg": sdg, "text_input": text_input}

while True:
    last_cmd = text_input.get_last()
    if last_cmd:
        try:
            result = eval(last_cmd, globals(), locals_dict)
            print(f"→ {result}")
        except Exception as e:
            print(f"Error: {e}")
    time.sleep(0.2)
```

## SCPI Command Reference

### IEEE 488.2 Common Commands
- `*IDN?` — Identification query → "N0GQ,Virtual-TextInput,1.0,2026"
- `*RST` — Reset to defaults
- `SYST:ERR?` — Query error queue

### Text Commands
- `TEXT:SEND <string>` — Send text (triggers display update and MQTT publish)
- `TEXT:SEND?` — Query last sent text
- `TEXT:HIST?` — Query command history (newline-separated)
- `TEXT:HIST:CLEAR` — Clear command history

### Configuration Commands
- `CONF:LABEL <string>` — Set input label
- `CONF:LABEL?` — Query input label
- `CONF:ROWS <1-10>` — Set number of rows
- `CONF:ROWS?` — Query number of rows
- `CONF:HIST <0-100>` — Set history depth
- `CONF:HIST?` — Query history depth
- `CONF:PLACEHOLDER <string>` — Set placeholder text
- `CONF:PLACEHOLDER?` — Query placeholder text

### MQTT Commands
- `MQTT:CONF <host>,<sub_topic>[,<pub_topic>]` — Configure MQTT
- `MQTT:CONF?` — Query MQTT configuration

### Direct SCPI Examples

```bash
# Using netcat
echo "*IDN?" | nc localhost 5104

# Send text
echo "TEXT:SEND FREQ:CENT 100MHz" | nc localhost 5104

# Query history
echo "TEXT:HIST?" | nc localhost 5104

# Configure
echo "CONF:LABEL SCPI Command" | nc localhost 5104
echo "CONF:ROWS 5" | nc localhost 5104
echo "CONF:PLACEHOLDER Enter command..." | nc localhost 5104

# Configure MQTT
echo "MQTT:CONF mqtt.n0gq.org,scpi/in,scpi/out" | nc localhost 5104
```

## Bidirectional Flow

The virtual text input supports three input sources:

1. **User types in browser** → WebSocket → backend → SCPI clients notified
2. **SCPI client sends TEXT:SEND** → backend → WebSocket → browser displays
3. **MQTT message arrives** → backend → WebSocket → browser displays

All submitted text (from any source) is published to MQTT pub_topic if configured.

## Display Features

The web interface provides:

- **Input field**: Single-line or multi-line textarea (configurable rows)
- **Label**: Descriptive text above input
- **Placeholder**: Hint text when input is empty
- **History panel**: Scrollable list of previous commands (most recent at top)
- **Real-time updates**: WebSocket sync keeps all views current
- **Enter to submit**: Single-line input submits on Enter key
- **Ctrl+Enter**: Multi-line input submits on Ctrl+Enter

## Error Handling

```python
from rf_bench.virtual import VirtualTextInput, VirtualTextInputError

try:
    text_input = VirtualTextInput("10.1.1.99")  # Wrong IP
except VirtualTextInputError as e:
    print(f"Connection failed: {e}")

try:
    text_input.set_rows(20)  # Out of range
except ValueError as e:
    print(f"Invalid parameter: {e}")
```

## Requirements

- Python 3.7+
- No external dependencies (uses stdlib `socket`)

Backend server requires:
- fastapi
- uvicorn
- websockets
- paho-mqtt (optional, for MQTT support)

## License

GPL-3.0-or-later — see LICENSE file in package root.

## See Also

- Backend server: `~/Dropbox/build/rf-bench/virtual/text-input/`
- BenchView panel manager: `~/Dropbox/build/rf-bench/virtual/benchview/`
- Other virtual instruments: `~/Dropbox/build/rf-bench/virtual/`
- RF Bench drivers: `~/Dropbox/build/rf-bench/drivers/`
