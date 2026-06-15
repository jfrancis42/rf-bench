# rf-bench-drivers-virtual-toggle

Python driver for **Virtual Toggle Switch** SCPI instrument. Controls toggle switch on/off state, colors, labels, size, and mode selection via SCPI-over-TCP (port 5025).

## Installation

```bash
pip install rf-bench-drivers-virtual-toggle
```

Or install from source:

```bash
cd drivers/virtual-toggle
pip install -e .
```

## Quick Start

```python
from rf_bench.virtual import VirtualToggle

# TX/RX switch (red when transmitting)
with VirtualToggle("10.1.1.52") as toggle:
    toggle.configure(
        label="TX/RX",
        on_color="#ff0000",
        off_color="#444444",
        on_label="TRANSMIT",
        off_label="RECEIVE"
    )
    toggle.on()   # Switch to TX

# Power on/off toggle
with VirtualToggle("10.1.1.52") as toggle:
    toggle.configure(
        label="Power",
        on_color="#00ff00",
        off_color="#333333",
        on_label="ON",
        off_label="OFF"
    )
    toggle.toggle()  # Flip state
```

## Backend Server

The driver connects to a virtual toggle switch backend server:

```bash
cd ~/Dropbox/build/rf-bench/virtual/toggle/backend
python3 server.py --scpi-port 5025 --http-port 8000
```

Open browser at `http://localhost:8000` to see the virtual toggle switch.

## API Reference

### Connection

```python
VirtualToggle(host, port=5025, timeout=2.0)
```

- **host**: IP address or hostname of backend server
- **port**: SCPI TCP port (default 5025)
- **timeout**: Socket timeout in seconds

### IEEE 488.2 Commands

```python
toggle.idn()           # → "N0GQ,Virtual-Toggle,1.0,2026"
toggle.reset()         # Reset to default state
toggle.get_error()     # → "0,No error"
```

### Toggle Switch State Control

```python
toggle.set_state(True)       # Turn on (True, 1, "ON")
toggle.set_state(False)      # Turn off (False, 0, "OFF")
toggle.get_state()           # → True or False

# Convenience methods
toggle.on()                  # Turn on
toggle.off()                 # Turn off
toggle.toggle()              # Flip to opposite state
```

### Toggle Switch Configuration

```python
# Full configuration
toggle.configure(
    label="TX/RX",              # Main label
    on_color="#ff0000",         # Red when ON
    off_color="#444444",        # Gray when OFF
    on_label="TRANSMIT",        # ON state label
    off_label="RECEIVE",        # OFF state label
    size=150                    # Size in pixels
)

# Individual settings
toggle.set_label("Power")               # Main label
toggle.set_on_color("#00ff00")          # Green when ON
toggle.set_off_color("#333333")         # Dark gray when OFF
toggle.set_on_label("ENABLED")          # ON label
toggle.set_off_label("DISABLED")        # OFF label
toggle.set_size(120)                    # Larger toggle

# Query settings
toggle.get_label()          # → "Power"
toggle.get_on_color()       # → "#00ff00"
toggle.get_off_color()      # → "#333333"
toggle.get_on_label()       # → "ENABLED"
toggle.get_off_label()      # → "DISABLED"
toggle.get_size()           # → 120
```

## Common Use Cases

### TX/RX Control for Radio

```python
from rf_bench.icom import IC7300
from rf_bench.virtual import VirtualToggle
import time

radio = IC7300()
toggle = VirtualToggle("10.1.1.52")

toggle.configure(
    label="TX/RX",
    on_color="#ff0000",
    off_color="#00ff00",
    on_label="TRANSMIT",
    off_label="RECEIVE"
)

while True:
    ptt = radio.get_ptt()
    toggle.set_state(ptt)
    time.sleep(0.05)
```

### Power On/Off Switching

```python
from rf_bench.siglent import SPD3303X
from rf_bench.virtual import VirtualToggle

psu = SPD3303X("10.1.1.56")
toggle = VirtualToggle("10.1.1.52")

toggle.configure(
    label="PSU Power",
    on_color="#00ff00",
    off_color="#333333",
    on_label="ON",
    off_label="OFF"
)

# Enable output when toggle is on
if toggle.get_state():
    psu.set_output(1, True)
else:
    psu.set_output(1, False)
```

### Mode Selection (USB/LSB/CW)

```python
from rf_bench.icom import IC7300
from rf_bench.virtual import VirtualToggle

radio = IC7300()
toggle = VirtualToggle("10.1.1.52")

# USB = ON, LSB = OFF
toggle.configure(
    label="Mode",
    on_color="#4488ff",
    off_color="#ff8844",
    on_label="USB",
    off_label="LSB"
)

# Set radio mode based on toggle
mode = "USB" if toggle.get_state() else "LSB"
radio.set_mode(mode)
```

### AGC Control (Fast/Slow)

```python
from rf_bench.icom import IC7300
from rf_bench.virtual import VirtualToggle

radio = IC7300()
toggle = VirtualToggle("10.1.1.52")

toggle.configure(
    label="AGC",
    on_color="#ffaa00",
    off_color="#4488ff",
    on_label="FAST",
    off_label="SLOW"
)

# Set AGC based on toggle
agc = "fast" if toggle.get_state() else "slow"
radio.set_agc(agc)
```

### Multi-Toggle Control Panel

Run multiple backend servers on different ports:

```python
from rf_bench.virtual import VirtualToggle

# Power toggle (green)
power = VirtualToggle("10.1.1.52", port=5025)
power.configure(
    label="Power",
    on_color="#00ff00",
    on_label="ON",
    off_label="OFF"
)
power.on()

# TX/RX toggle (red/green)
txrx = VirtualToggle("10.1.1.52", port=5026)
txrx.configure(
    label="TX/RX",
    on_color="#ff0000",
    off_color="#00ff00",
    on_label="TX",
    off_label="RX"
)
txrx.off()

# Mode toggle (blue/orange)
mode = VirtualToggle("10.1.1.52", port=5027)
mode.configure(
    label="Mode",
    on_color="#4488ff",
    off_color="#ff8844",
    on_label="USB",
    off_label="LSB"
)
mode.on()
```

### Antenna Switch Control

```python
from rf_bench.virtual import VirtualToggle
import socket

# Simple SPDT antenna relay controller
relay = socket.socket()
relay.connect(("10.1.0.16", 5025))

toggle = VirtualToggle("10.1.1.52")
toggle.configure(
    label="Antenna",
    on_color="#00ff00",
    off_color="#ffaa00",
    on_label="ANT 1",
    off_label="ANT 2"
)

# Set relay based on toggle state
state = toggle.get_state()
relay.sendall(f"RELAY:STATE {1 if state else 2}\n".encode())
```

## SCPI Command Reference

### IEEE 488.2 Common Commands
- `*IDN?` — Identification query
- `*RST` — Reset to defaults
- `SYST:ERR?` — Query error queue

### Toggle Switch State Commands
- `STAT:VAL <0|1|OFF|ON|FALSE|TRUE>` — Set toggle state
- `STAT:VAL?` — Query toggle state (returns 0 or 1)

### Configuration Commands
- `CONF:LABEL <string>` — Set main label text
- `CONF:LABEL?` — Query main label
- `CONF:ONCOL <color>` — Set ON state color (hex: #RGB or #RRGGBB)
- `CONF:ONCOL?` — Query ON color
- `CONF:OFFCOL <color>` — Set OFF state color (hex: #RGB or #RRGGBB)
- `CONF:OFFCOL?` — Query OFF color
- `CONF:ONLABEL <string>` — Set ON state label text
- `CONF:ONLABEL?` — Query ON state label
- `CONF:OFFLABEL <string>` — Set OFF state label text
- `CONF:OFFLABEL?` — Query OFF state label
- `CONF:SIZE <pixels>` — Set toggle size (50-200)
- `CONF:SIZE?` — Query toggle size

### Direct SCPI Example

```bash
# Using netcat
echo "*IDN?" | nc localhost 5025
echo "STAT:VAL 1" | nc localhost 5025
echo "CONF:ONCOL #ff0000" | nc localhost 5025
echo "CONF:ONLABEL TRANSMIT" | nc localhost 5025
echo "CONF:LABEL TX/RX" | nc localhost 5025
```

## Toggle Switch Display

The virtual toggle switch displays:
- **ON**: Bright color with ON label visible
- **OFF**: Dark color with OFF label visible
- **Size**: Configurable width (50-200 pixels, default 100)
- **Labels**: Main label above switch, state-specific labels on switch
- **Interactive**: Clickable in browser to change state

## Error Handling

```python
from rf_bench.virtual import VirtualToggle, VirtualToggleError

try:
    toggle = VirtualToggle("10.1.1.99")  # Wrong IP
except VirtualToggleError as e:
    print(f"Connection failed: {e}")

try:
    toggle.set_size(300)  # Out of range
except ValueError as e:
    print(f"Invalid size: {e}")
```

## Requirements

- Python 3.7+
- No external dependencies (uses stdlib `socket`)

## License

GPL-3.0-or-later — see LICENSE file in package root.

## See Also

- Backend server: `~/Dropbox/build/rf-bench/virtual/toggle/`
- BenchView panel manager: `~/Dropbox/build/rf-bench/virtual/benchview/`
- Other virtual instruments: `~/Dropbox/build/rf-bench/virtual/`
- RF Bench drivers: `~/Dropbox/build/rf-bench/drivers/`
