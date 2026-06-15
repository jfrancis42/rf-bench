# rf-bench-drivers-virtual-numeric-display

Python driver for **Virtual Numeric Display** SCPI instrument. Displays numerical values with configurable precision, units, font size, color, and style via SCPI-over-TCP (port 5025).

## Installation

```bash
pip install rf-bench-drivers-virtual-numeric-display
```

## Quick Start

```python
from rf_bench.virtual import VirtualNumericDisplay

# Frequency display (IC-7300 readout)
with VirtualNumericDisplay("10.1.1.52") as display:
    display.configure(
        precision=6,
        digits=10,
        units="MHz",
        font_size=80,
        color="#00ff00",
        style="7SEG"
    )
    display.set_value(14.257000)

# Voltage display (power supply readout)
with VirtualNumericDisplay("10.1.1.52") as display:
    display.configure(
        precision=1,
        digits=6,
        units="V",
        font_size=100,
        color="#00ffff"
    )
    display.set_value(13.8)
```

## Multi-Instance Usage

For multiple numeric-displays controlled by a single backend (e.g., via BenchView), use the multi-instance driver:

```python
from rf_bench.virtual import VirtualNumericDisplayMulti

# Connect to multi-instance backend
# Port is assigned by BenchView and read from *_ports.yaml
displays = VirtualNumericDisplayMulti("localhost", port=5100)

# Control individual instances (1-based indexing)
displays.set_value(1, 50.0)  # Instance 1
displays.set_value(2, 75.0)  # Instance 2
displays.set_label(1, "Channel 1")
displays.set_label(2, "Channel 2")

# Query instance count
count = displays.get_count()  # → 2

displays.close()
```

**Multi-instance backend:**

```bash
cd ~/Dropbox/build/rf-bench/virtual/numeric-display/backend
python3 server-multi.py --scpi-port 5100 --http-port 8100 --count 2 --layout row
```

**Port Assignment:**

When using BenchView, ports are assigned dynamically and exported to:
- `~/.rf-bench/<panel-name>_ports.yaml` (inventory overlay)
- `<config-dir>/<panel-name>_ports.yaml` (legacy)

Bridge scripts should read port assignments from the YAML file rather than hardcoding them.

## Backend Server

The driver connects to a virtual numeric display backend server:

```bash
cd ~/Dropbox/build/rf-bench/virtual/numeric-display/backend
python3 server.py --scpi-port 5025 --http-port 8000
```

Open browser at `http://localhost:8000` to see the virtual numeric display.

## API Reference

### Connection

```python
VirtualNumericDisplay(host, port=5025, timeout=2.0)
```

- **host**: IP address or hostname of backend server
- **port**: SCPI TCP port (default 5025)
- **timeout**: Socket timeout in seconds

### IEEE 488.2 Commands

```python
display.idn()           # → "N0GQ,Virtual-Numeric-Display,1.0,2026"
display.reset()         # Reset to default state
display.get_error()     # → "0,No error"
```

### Value Control

```python
display.set_value(14.257000)    # Set displayed value
display.get_value()             # → 14.257
display.update(14.257)          # Alias for set_value()
```

### Display Configuration

```python
# Full configuration
display.configure(
    precision=6,        # Decimal places (0-6)
    digits=10,          # Total digit count (4-12)
    units="MHz",        # Units string
    font_size=80,       # Font size in pixels (20-120)
    color="#00ff00",    # Text color (hex)
    style="7SEG"        # Display style (7SEG/PLAIN/LED/NIXIE)
)

# Individual settings
display.set_precision(6)        # 0-6 decimal places
display.set_digits(10)          # 4-12 total digits
display.set_units("MHz")        # Units string (any text)
display.set_font_size(80)       # 20-120 pixels
display.set_color("#00ff00")    # CSS hex color
display.set_style("7SEG")       # 7SEG, PLAIN, LED, or NIXIE

# Query settings
display.get_precision()    # → 6
display.get_digits()       # → 10
display.get_units()        # → "MHz"
display.get_font_size()    # → 80
display.get_color()        # → "#00ff00"
display.get_style()        # → "7SEG"
```

## Common Use Cases

### IC-7300 Frequency Readout

```python
from rf_bench.icom import IC7300
from rf_bench.virtual import VirtualNumericDisplay
import time

radio = IC7300()
display = VirtualNumericDisplay("10.1.1.52")

display.configure(
    precision=6,
    digits=10,
    units="MHz",
    color="#00ff00",
    style="7SEG"
)

while True:
    freq_hz = radio.get_frequency()
    freq_mhz = freq_hz / 1e6
    display.set_value(freq_mhz)
    time.sleep(0.1)
```

### GPS Altitude Display

```python
from rf_bench.gpsd import GPSD
from rf_bench.virtual import VirtualNumericDisplay
import time

gps = GPSD()
display = VirtualNumericDisplay("10.1.1.52")

display.configure(
    precision=1,
    digits=8,
    units="m",
    color="#4488ff",
    style="LED"
)

while True:
    fix = gps.get_fix()
    altitude = fix.get('alt', 0.0)
    display.set_value(altitude)
    time.sleep(1.0)
```

### Temperature Display

```python
from rf_bench.virtual import VirtualNumericDisplay
import random
import time

display = VirtualNumericDisplay("10.1.1.52")

display.configure(
    precision=1,
    digits=6,
    units="°C",
    color="#ff8800",
    style="NIXIE"
)

while True:
    # Simulated temperature sensor
    temp = 20.0 + random.uniform(-2.0, 5.0)
    display.set_value(temp)
    time.sleep(2.0)
```

### Power Meter Display

```python
from rf_bench.siglent import SSA3000X
from rf_bench.virtual import VirtualNumericDisplay
import time

ssa = SSA3000X("10.1.1.60")
display = VirtualNumericDisplay("10.1.1.52")

ssa.set_center_frequency(14.257e6)
ssa.set_span(10e3)

display.configure(
    precision=2,
    digits=8,
    units="dBm",
    color="#ffff00",
    style="7SEG"
)

while True:
    power_dbm = ssa.measure_channel_power()
    display.set_value(power_dbm)
    time.sleep(0.5)
```

### S-Meter Display

```python
from rf_bench.icom import IC7300
from rf_bench.virtual import VirtualNumericDisplay
import time

radio = IC7300()
display = VirtualNumericDisplay("10.1.1.52")

display.configure(
    precision=0,
    digits=4,
    units="S",
    font_size=100,
    color="#00ff00",
    style="LED"
)

while True:
    s_units = radio.get_strength()
    display.set_value(s_units)
    time.sleep(0.05)
```

### Multi-Display Panel

Run multiple backend servers on different ports:

```python
from rf_bench.virtual import VirtualNumericDisplay
from rf_bench.icom import IC7300
import time

radio = IC7300()

# Frequency display
freq_disp = VirtualNumericDisplay("10.1.1.52", port=5025)
freq_disp.configure(precision=6, units="MHz", color="#00ff00")

# S-meter display
smeter_disp = VirtualNumericDisplay("10.1.1.52", port=5026)
smeter_disp.configure(precision=0, units="S", color="#ffff00")

# Power display
power_disp = VirtualNumericDisplay("10.1.1.52", port=5027)
power_disp.configure(precision=1, units="W", color="#ff0000")

while True:
    freq_disp.set_value(radio.get_frequency() / 1e6)
    smeter_disp.set_value(radio.get_strength())
    power_disp.set_value(radio.get_power())
    time.sleep(0.1)
```

## SCPI Command Reference

### IEEE 488.2 Common Commands
- `*IDN?` — Identification query
- `*RST` — Reset to defaults
- `SYST:ERR?` — Query error queue

### Value Commands
- `MEAS:VAL <number>` — Set displayed value
- `MEAS:VAL?` — Query displayed value

### Configuration Commands
- `CONF:PREC <0-6>` — Set decimal precision
- `CONF:PREC?` — Query decimal precision
- `CONF:DIG <4-12>` — Set total digit count
- `CONF:DIG?` — Query total digit count
- `CONF:UNIT <string>` — Set units string
- `CONF:UNIT?` — Query units string
- `CONF:SIZE <20-120>` — Set font size in pixels
- `CONF:SIZE?` — Query font size
- `CONF:COL <color>` — Set text color (hex: #RGB or #RRGGBB)
- `CONF:COL?` — Query text color
- `CONF:STYLE <7SEG|PLAIN|LED|NIXIE>` — Set display style
- `CONF:STYLE?` — Query display style

### Direct SCPI Example

```bash
# Using netcat
echo "*IDN?" | nc localhost 5025
echo "MEAS:VAL 14.257" | nc localhost 5025
echo "CONF:PREC 6" | nc localhost 5025
echo "CONF:UNIT MHz" | nc localhost 5025
echo "CONF:COL #00ff00" | nc localhost 5025
echo "CONF:STYLE 7SEG" | nc localhost 5025
```

## Display Styles

The virtual numeric display supports four visual styles:

- **7SEG**: Classic 7-segment LCD look (default)
- **PLAIN**: Clean sans-serif font (modern)
- **LED**: LED dot matrix appearance (retro)
- **NIXIE**: Nixie tube aesthetic (vintage)

## Error Handling

```python
from rf_bench.virtual import VirtualNumericDisplay, VirtualNumericDisplayError

try:
    display = VirtualNumericDisplay("10.1.1.99")  # Wrong IP
except VirtualNumericDisplayError as e:
    print(f"Connection failed: {e}")

try:
    display.set_precision(10)  # Out of range
except ValueError as e:
    print(f"Invalid precision: {e}")

try:
    display.set_color("blue")  # Invalid format
except ValueError as e:
    print(f"Invalid color: {e}")
```

## Requirements

- Python 3.7+
- No external dependencies (uses stdlib `socket`)

## License

GPL-3.0-or-later — see LICENSE file in package root.

## See Also

- Backend server: `~/Dropbox/build/rf-bench/virtual/numeric-display/`
- BenchView panel manager: `~/Dropbox/build/rf-bench/virtual/benchview/`
- Other virtual instruments: `~/Dropbox/build/rf-bench/virtual/`
- RF Bench drivers: `~/Dropbox/build/rf-bench/drivers/`
