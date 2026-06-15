# Virtual Slider

🔨 **Status: Built 2026-06-14** — Phase 2 proof-of-concept (first interactive control widget)

SCPI-controlled slider widget with **bidirectional** communication. Users can drag the slider in the browser to control instruments, or external SCPI/MQTT commands can preset the value. First Phase 2 interactive control widget.

## Features

- **SCPI TCP server** on port 5100 (IEEE 488.2 standard)
- **Bidirectional WebSocket** for instant updates (user → instrument → user)
- **Interactive slider** with drag-to-control
- **Configurable range** (min/max) with optional step size
- **Horizontal or vertical** orientation
- **Linear or logarithmic** scale
- **Customizable labels** (title, units) and colors
- **MQTT bidirectional** (subscribe to receive, publish on user change)

## Ports

- **SCPI:** `tcp://0.0.0.0:5100`
- **HTTP:** `http://0.0.0.0:8100`
- **WebSocket:** `ws://0.0.0.0:8100/ws` (bidirectional)
- **MQTT:** Configurable via `MQTT:CONF` command

## SCPI Commands

### Measurement
- `MEAS:VAL <float>` — Set slider value
- `MEAS:VAL?` — Query current value

### Configuration
- `CONF:MIN <float>` — Set minimum value (default 0)
- `CONF:MIN?` — Query minimum value
- `CONF:MAX <float>` — Set maximum value (default 100)
- `CONF:MAX?` — Query maximum value
- `CONF:STEP <float>` — Set step size (0 = continuous, default 1)
- `CONF:STEP?` — Query step size
- `CONF:ORIENT <HOR|VERT>` — Set orientation (default HOR)
- `CONF:ORIENT?` — Query orientation
- `CONF:SCALE <LIN|LOG>` — Set scale type (default LIN)
- `CONF:SCALE?` — Query scale type
- `CONF:LABEL <string>` — Set title label
- `CONF:LABEL?` — Query title label
- `CONF:UNIT <string>` — Set display units (e.g., "Hz", "V", "%")
- `CONF:UNIT?` — Query display units
- `CONF:COL <color>` — Set slider color (hex, e.g., "#00ff00")
- `CONF:COL?` — Query slider color

### IEEE 488.2 Standard
- `*IDN?` — Identification query
- `*RST` — Reset to defaults
- `SYST:ERR?` — Query error queue

### MQTT
- `MQTT:CONF <host>,<sub_topic>[,<pub_topic>]` — Configure MQTT
  - `sub_topic`: Topic to subscribe (receive values)
  - `pub_topic`: Topic to publish (send user changes)
- `MQTT:CONF?` — Query MQTT configuration

## Bidirectional Flow

This is the key Phase 2 feature — data flows both ways:

```
User drags slider → WebSocket → Backend → MQTT pub_topic
                                       ↓
                                    SCPI clients notified

External SCPI command → Backend → WebSocket → Browser updates slider
                            ↓
                         MQTT published

MQTT message arrives → Backend → WebSocket → Browser updates slider
                           ↓
                        SCPI clients notified
```

All sources (user, SCPI, MQTT) are synchronized in real-time.

## Quick Start

```bash
# Start the server
cd ~/Dropbox/build/rf-bench/virtual/slider/backend
python3 server.py

# Open in browser
xdg-open http://localhost:8100
```

## Configuration Examples

### Frequency control (1 kHz - 60 MHz, logarithmic)
```bash
echo "CONF:MIN 1000" | nc localhost 5100
echo "CONF:MAX 60000000" | nc localhost 5100
echo "CONF:STEP 1000" | nc localhost 5100
echo "CONF:SCALE LOG" | nc localhost 5100
echo "CONF:LABEL Frequency" | nc localhost 5100
echo "CONF:UNIT Hz" | nc localhost 5100
echo "CONF:COL #ff8800" | nc localhost 5100
echo "MEAS:VAL 14070000" | nc localhost 5100  # Set to 14.07 MHz
```

### PSU voltage control (0-32V, 0.1V steps)
```bash
echo "CONF:MIN 0" | nc localhost 5100
echo "CONF:MAX 32" | nc localhost 5100
echo "CONF:STEP 0.1" | nc localhost 5100
echo "CONF:SCALE LIN" | nc localhost 5100
echo "CONF:LABEL Voltage" | nc localhost 5100
echo "CONF:UNIT V" | nc localhost 5100
echo "CONF:COL #00ff00" | nc localhost 5100
echo "MEAS:VAL 13.8" | nc localhost 5100
```

### Attenuator (0-31.5 dB, 0.5 dB steps)
```bash
echo "CONF:MIN 0" | nc localhost 5100
echo "CONF:MAX 31.5" | nc localhost 5100
echo "CONF:STEP 0.5" | nc localhost 5100
echo "CONF:LABEL Attenuation" | nc localhost 5100
echo "CONF:UNIT dB" | nc localhost 5100
echo "CONF:COL #4488ff" | nc localhost 5100
echo "MEAS:VAL 10" | nc localhost 5100
```

### Vertical slider (volume control)
```bash
echo "CONF:MIN 0" | nc localhost 5100
echo "CONF:MAX 100" | nc localhost 5100
echo "CONF:STEP 1" | nc localhost 5100
echo "CONF:ORIENT VERT" | nc localhost 5100
echo "CONF:LABEL Volume" | nc localhost 5100
echo "CONF:UNIT %" | nc localhost 5100
echo "MEAS:VAL 75" | nc localhost 5100
```

## Integration Examples

### SDG function generator frequency control
```python
from rf_bench.siglent import SDG1000X
import socket, time

sdg = SDG1000X('10.1.1.55')
slider_sock = socket.socket()
slider_sock.connect(('localhost', 5100))

# Configure slider for 1 kHz - 10 MHz
slider_sock.sendall(b'CONF:MIN 1000\n')
slider_sock.sendall(b'CONF:MAX 10000000\n')
slider_sock.sendall(b'CONF:STEP 1000\n')
slider_sock.sendall(b'CONF:SCALE LOG\n')
slider_sock.sendall(b'CONF:LABEL Frequency\n')
slider_sock.sendall(b'CONF:UNIT Hz\n')

# Set initial value
current_freq = sdg.get_frequency(1)
slider_sock.sendall(f'MEAS:VAL {current_freq}\n'.encode())

# Poll slider for changes
while True:
    slider_sock.sendall(b'MEAS:VAL?\n')
    time.sleep(0.01)
    response = slider_sock.recv(1024).decode().strip()
    if response:
        try:
            new_freq = float(response)
            if abs(new_freq - current_freq) > 100:  # Debounce
                sdg.set_frequency(1, new_freq)
                current_freq = new_freq
                print(f'Frequency updated: {new_freq/1e6:.3f} MHz')
        except ValueError:
            pass
    time.sleep(0.1)
```

### PSU voltage control with readback
```python
from rf_bench.siglent import SPD3303X
import socket, time

psu = SPD3303X('10.1.1.56')
slider_sock = socket.socket()
slider_sock.connect(('localhost', 5100))

# Configure slider for 0-32V
slider_sock.sendall(b'CONF:MIN 0\n')
slider_sock.sendall(b'CONF:MAX 32\n')
slider_sock.sendall(b'CONF:STEP 0.1\n')
slider_sock.sendall(b'CONF:LABEL Voltage\n')
slider_sock.sendall(b'CONF:UNIT V\n')

# Set initial from PSU
current_voltage = psu.get_voltage(1)
slider_sock.sendall(f'MEAS:VAL {current_voltage}\n'.encode())

# Bidirectional: slider → PSU and PSU → slider
while True:
    # Check slider for changes
    slider_sock.sendall(b'MEAS:VAL?\n')
    time.sleep(0.01)
    response = slider_sock.recv(1024).decode().strip()
    if response:
        try:
            new_voltage = float(response)
            if abs(new_voltage - current_voltage) > 0.05:
                psu.set_voltage(1, new_voltage)
                current_voltage = new_voltage
                print(f'Voltage set: {new_voltage:.1f}V')
        except ValueError:
            pass

    # Update slider from actual PSU readback (for verification)
    actual_voltage = psu.measure_voltage(1)
    slider_sock.sendall(f'MEAS:VAL {actual_voltage}\n'.encode())

    time.sleep(0.2)
```

### RF attenuator control (via ESP32 SCPI)
```python
import socket, time

# Connect to ESP32 RF attenuator (PE4302/HMC472)
atten_sock = socket.socket()
atten_sock.connect(('192.168.1.42', 5025))

# Connect to slider
slider_sock = socket.socket()
slider_sock.connect(('localhost', 5100))

# Configure slider for 0-31.5 dB in 0.5 dB steps
slider_sock.sendall(b'CONF:MIN 0\n')
slider_sock.sendall(b'CONF:MAX 31.5\n')
slider_sock.sendall(b'CONF:STEP 0.5\n')
slider_sock.sendall(b'CONF:LABEL Attenuation\n')
slider_sock.sendall(b'CONF:UNIT dB\n')

# Get initial attenuator setting
atten_sock.sendall(b'ATTEN?\n')
time.sleep(0.1)
current_atten = float(atten_sock.recv(1024).decode().strip())
slider_sock.sendall(f'MEAS:VAL {current_atten}\n'.encode())

# Poll slider and update attenuator
while True:
    slider_sock.sendall(b'MEAS:VAL?\n')
    time.sleep(0.01)
    response = slider_sock.recv(1024).decode().strip()
    if response:
        try:
            new_atten = float(response)
            if abs(new_atten - current_atten) > 0.1:
                atten_sock.sendall(f'ATTEN {new_atten}\n'.encode())
                current_atten = new_atten
                print(f'Attenuation: {new_atten:.1f} dB')
        except ValueError:
            pass
    time.sleep(0.1)
```

### MQTT Integration (bidirectional)
```bash
# Configure MQTT with both subscribe and publish topics
echo "MQTT:CONF localhost,slider/in,slider/out" | nc localhost 5100

# Now:
# - Messages published to slider/in will update the slider
# - User dragging the slider will publish to slider/out
```

```python
import paho.mqtt.client as mqtt
import time

def on_message(client, userdata, msg):
    print(f"Slider value changed to: {msg.payload.decode()}")

client = mqtt.Client()
client.on_message = on_message
client.connect("localhost", 1883, 60)
client.subscribe("slider/out")  # Listen for user changes
client.loop_start()

# Send value to slider
client.publish("slider/in", "42.5")
time.sleep(1)
client.publish("slider/in", "75.0")

time.sleep(10)
client.loop_stop()
```

## Use Cases

- **Function generator frequency control** (sweep tuning)
- **Power supply voltage/current setting**
- **RF attenuator adjustment**
- **Volume/gain controls**
- **Spectrum analyzer RBW/span control**
- **Radio frequency tuning** (VFO)
- **Motor speed control**
- **Temperature setpoints**
- **Any continuous or stepped parameter**

## Phase 2 Significance

This is the **first Phase 2 interactive control widget**. It establishes the pattern for all future bidirectional controls:

- **Bidirectional WebSocket** (user can control, external can preset)
- **Conflict resolution** (user interaction pauses external updates)
- **SCPI command interface** (same as Phase 1 read-only widgets)
- **MQTT pub/sub** (both directions)
- **Real-time synchronization** across all clients

Once this slider is proven, the same architecture will be used for:
- Toggle switches
- Push buttons
- Rotary knobs
- Text input fields

## Files

```
slider/
├── backend/
│   └── server.py          # FastAPI + SCPI + WebSocket + MQTT (bidirectional)
├── frontend/
│   └── index.html         # Interactive HTML5 slider
└── README.md              # This file
```

## See Also

- [PORT-ASSIGNMENTS.md](../PORT-ASSIGNMENTS.md) — Port allocations for all instruments
- [BUILDING-STATUS.md](../BUILDING-STATUS.md) — Phase tracking
- [workbench.md](../../workbench.md) — Virtual instrument panel architecture
- Phase 1 indicators: [numeric-display](../numeric-display/), [bar-graph](../bar-graph/), [analog-meter](../analog-meter/)
