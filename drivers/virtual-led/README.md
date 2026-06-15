# rf-bench-drivers-virtual-led

Python driver for **Virtual LED Indicator** SCPI instrument. Controls LED on/off state, colors, blink rate, size, and label via SCPI-over-TCP (port 5025).

## Installation

```bash
pip install rf-bench-drivers-virtual-led
```

## Quick Start

```python
from rf_bench.virtual import VirtualLED

# PTT indicator (red when active)
with VirtualLED("10.1.1.52") as led:
    led.configure(
        on_color="#ff0000",
        off_color="#440000",
        label="PTT"
    )
    led.on()   # Turn on

# GPS lock indicator (blue, blinking at 500ms)
with VirtualLED("10.1.1.52") as led:
    led.configure(
        on_color="#4488ff",
        off_color="#222244",
        label="GPS",
        blink_ms=500
    )
    led.on()
```

## Multi-Instance Usage

For multiple leds controlled by a single backend (e.g., via BenchView), use the multi-instance driver:

```python
from rf_bench.virtual import VirtualLEDMulti

# Connect to multi-instance backend
# Port is assigned by BenchView and read from *_ports.yaml
leds = VirtualLEDMulti("localhost", port=5100)

# Control individual instances (1-based indexing)
leds.set_value(1, 50.0)  # Instance 1
leds.set_value(2, 75.0)  # Instance 2
leds.set_label(1, "Channel 1")
leds.set_label(2, "Channel 2")

# Query instance count
count = leds.get_count()  # → 2

leds.close()
```

**Multi-instance backend:**

```bash
cd ~/Dropbox/build/rf-bench/virtual/led/backend
python3 server-multi.py --scpi-port 5100 --http-port 8100 --count 2 --layout row
```

**Port Assignment:**

When using BenchView, ports are assigned dynamically and exported to:
- `~/.rf-bench/<panel-name>_ports.yaml` (inventory overlay)
- `<config-dir>/<panel-name>_ports.yaml` (legacy)

Bridge scripts should read port assignments from the YAML file rather than hardcoding them.

## Backend Server

The driver connects to a virtual LED indicator backend server:

```bash
cd ~/Dropbox/build/rf-bench/virtual/led/backend
python3 server.py --scpi-port 5025 --http-port 8000
```

Open browser at `http://localhost:8000` to see the virtual LED.

## API Reference

### Connection

```python
VirtualLED(host, port=5025, timeout=2.0)
```

- **host**: IP address or hostname of backend server
- **port**: SCPI TCP port (default 5025)
- **timeout**: Socket timeout in seconds

### IEEE 488.2 Commands

```python
led.idn()           # → "N0GQ,Virtual-LED,1.0,2026"
led.reset()         # Reset to default state
led.get_error()     # → "0,No error"
```

### LED State Control

```python
led.set_state(True)       # Turn on (True, 1, "ON")
led.set_state(False)      # Turn off (False, 0, "OFF")
led.get_state()           # → True or False

# Convenience methods
led.on()                  # Turn on
led.off()                 # Turn off
led.toggle()              # Toggle state
```

### LED Configuration

```python
# Full configuration
led.configure(
    on_color="#00ff00",     # Green when ON
    off_color="#333333",    # Dark gray when OFF
    label="Status",
    blink_ms=0,             # 0 = no blink
    size=80                 # Diameter in pixels
)

# Individual settings
led.set_on_color("#ff0000")      # Red when ON
led.set_off_color("#440000")     # Dark red when OFF
led.set_label("PTT")
led.set_blink(500)               # Blink every 500ms
led.set_size(120)                # Larger LED

# Query settings
led.get_on_color()      # → "#ff0000"
led.get_off_color()     # → "#440000"
led.get_label()         # → "PTT"
led.get_blink()         # → 500
led.get_size()          # → 120
```

## Common Use Cases

### PTT (Push-to-Talk) Indicator

```python
from rf_bench.icom import IC7300
from rf_bench.virtual import VirtualLED
import time

radio = IC7300()
led = VirtualLED("10.1.1.52")

led.configure(
    on_color="#ff0000",
    off_color="#440000",
    label="PTT"
)

while True:
    ptt = radio.get_ptt()
    led.set_state(ptt)
    time.sleep(0.05)
```

### GPS Lock Indicator

```python
from rf_bench.gpsd import GPSD
from rf_bench.virtual import VirtualLED
import time

gps = GPSD()
led = VirtualLED("10.1.1.52")

led.configure(
    on_color="#4488ff",
    off_color="#222244",
    label="GPS"
)

while True:
    fix = gps.get_fix()
    has_lock = (fix.get('mode', 0) >= 2)
    led.set_state(has_lock)
    time.sleep(1.0)
```

### Alarm Indicator (fast blink)

```python
from rf_bench.virtual import VirtualLED
import time

led = VirtualLED("10.1.1.52")

led.configure(
    on_color="#ff0000",
    off_color="#220000",
    label="ALARM",
    blink_ms=200,      # Fast blink
    size=120           # Large
)

# Trigger alarm
led.on()

# Wait 10 seconds
time.sleep(10)

# Clear alarm
led.off()
```

### Multi-LED Status Panel

Run multiple backend servers on different ports:

```python
from rf_bench.virtual import VirtualLED

# Power LED (green)
power = VirtualLED("10.1.1.52", port=5025)
power.configure(on_color="#00ff00", label="Power")
power.on()

# TX LED (red)
tx = VirtualLED("10.1.1.52", port=5026)
tx.configure(on_color="#ff0000", label="TX")
tx.off()

# RX LED (yellow)
rx = VirtualLED("10.1.1.52", port=5027)
rx.configure(on_color="#ffff00", label="RX")
rx.off()
```

## SCPI Command Reference

### IEEE 488.2 Common Commands
- `*IDN?` — Identification query
- `*RST` — Reset to defaults
- `SYST:ERR?` — Query error queue

### LED State Commands
- `STAT:VAL <0|1|OFF|ON|FALSE|TRUE>` — Set LED state
- `STAT:VAL?` — Query LED state (returns 0 or 1)

### Configuration Commands
- `CONF:ONCOL <color>` — Set ON color (hex: #RGB or #RRGGBB)
- `CONF:ONCOL?` — Query ON color
- `CONF:OFFCOL <color>` — Set OFF color (hex: #RGB or #RRGGBB)
- `CONF:OFFCOL?` — Query OFF color
- `CONF:BLINK <ms>` — Set blink rate (0 = no blink)
- `CONF:BLINK?` — Query blink rate
- `CONF:SIZE <pixels>` — Set LED diameter (20-200)
- `CONF:SIZE?` — Query LED size
- `CONF:LABEL <string>` — Set label text
- `CONF:LABEL?` — Query label text

### Direct SCPI Example

```bash
# Using netcat
echo "*IDN?" | nc localhost 5025
echo "STAT:VAL 1" | nc localhost 5025
echo "CONF:ONCOL #ff0000" | nc localhost 5025
echo "CONF:LABEL PTT" | nc localhost 5025
```

## LED Display

The virtual LED displays:
- **ON**: Bright color with radial glow effect
- **OFF**: Dark color with recessed (inset) appearance
- **Blink**: Toggles between ON and OFF at configured rate
- **Size**: Configurable diameter (20-200 pixels, default 80)
- **Label**: Text below LED

## Error Handling

```python
from rf_bench.virtual import VirtualLED, VirtualLEDError

try:
    led = VirtualLED("10.1.1.99")  # Wrong IP
except VirtualLEDError as e:
    print(f"Connection failed: {e}")

try:
    led.set_size(300)  # Out of range
except ValueError as e:
    print(f"Invalid size: {e}")
```

## Requirements

- Python 3.7+
- No external dependencies (uses stdlib `socket`)

## License

GPL-3.0-or-later — see LICENSE file in package root.

## See Also

- Backend server: `~/Dropbox/build/rf-bench/virtual/led/`
- BenchView panel manager: `~/Dropbox/build/rf-bench/virtual/benchview/`
- Other virtual instruments: `~/Dropbox/build/rf-bench/virtual/`
- RF Bench drivers: `~/Dropbox/build/rf-bench/drivers/`
