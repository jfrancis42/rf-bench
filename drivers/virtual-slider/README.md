# rf-bench-drivers-virtual-slider

Python driver for **Virtual Slider Control** SCPI instrument. Controls slider value, range, scale (linear/log), orientation (horizontal/vertical), labels, and color via SCPI-over-TCP (port 5025).

## Installation

```bash
pip install rf-bench-drivers-virtual-slider
```

Or install from source:

```bash
cd drivers/virtual-slider
pip install -e .
```

## Quick Start

```python
from rf_bench.virtual import VirtualSlider

# Horizontal power slider (0-100W)
with VirtualSlider("10.1.1.52") as slider:
    slider.configure(
        min_val=0,
        max_val=100,
        value=50,
        label="RF Power",
        unit="W",
        orientation="horizontal"
    )
    slider.set_value(75)

# Vertical frequency slider with log scale
with VirtualSlider("10.1.1.52") as slider:
    slider.configure(
        min_val=1e6,
        max_val=30e6,
        value=14.2e6,
        label="Frequency",
        unit="MHz",
        orientation="vertical",
        scale="log"
    )
    slider.set_value(7.05e6)
```

## Backend Server

The driver connects to a virtual slider backend server:

```bash
cd ~/Dropbox/build/rf-bench/virtual/slider/backend
python3 server.py --scpi-port 5025 --http-port 8000
```

Open browser at `http://localhost:8000` to see the virtual slider.

## API Reference

### Connection

```python
VirtualSlider(host, port=5025, timeout=2.0)
```

- **host**: IP address or hostname of backend server
- **port**: SCPI TCP port (default 5025)
- **timeout**: Socket timeout in seconds

### IEEE 488.2 Commands

```python
slider.idn()           # → "N0GQ,Virtual-Slider,1.0,2026"
slider.reset()         # Reset to default state
slider.get_error()     # → "0,No error"
```

### Slider Value Control

```python
slider.set_value(50.0)        # Set slider value
slider.get_value()            # → 50.0

# Step increment/decrement
slider.step_up()              # Increase by step size
slider.step_down()            # Decrease by step size
```

### Slider Configuration

```python
# Full configuration
slider.configure(
    min_val=0.0,               # Minimum value
    max_val=100.0,             # Maximum value
    value=50.0,                # Current value
    step=1.0,                  # Step size
    label="Power",             # Label text
    unit="W",                  # Unit text
    orientation="horizontal",  # "horizontal" or "vertical"
    scale="linear",            # "linear" or "log"
    color="#4488ff"            # Slider color (hex)
)

# Individual settings
slider.set_min(0.0)
slider.set_max(100.0)
slider.set_step(5.0)
slider.set_label("RF Power")
slider.set_unit("dBm")
slider.set_orientation("vertical")     # "horizontal" or "vertical"
slider.set_scale("log")                # "linear" or "log"
slider.set_color("#ff4400")            # Orange slider

# Query settings
slider.get_min()              # → 0.0
slider.get_max()              # → 100.0
slider.get_step()             # → 5.0
slider.get_label()            # → "RF Power"
slider.get_unit()             # → "dBm"
slider.get_orientation()      # → "vertical"
slider.get_scale()            # → "log"
slider.get_color()            # → "#ff4400"
```

## Common Use Cases

### RF Power Control

```python
from rf_bench.siglent import SDG1000X
from rf_bench.virtual import VirtualSlider
import time

gen = SDG1000X("10.1.1.55")
slider = VirtualSlider("10.1.1.52")

slider.configure(
    min_val=-60,
    max_val=10,
    value=-10,
    step=1,
    label="Output Power",
    unit="dBm",
    orientation="horizontal"
)

while True:
    power_dbm = slider.get_value()
    amp_v = 10 ** ((power_dbm - 13) / 20)  # Convert dBm to Vpp (50Ω)
    gen.set_amplitude(1, amp_v)
    time.sleep(0.1)
```

### Frequency Selection (Log Scale)

```python
from rf_bench.icom import IC7300
from rf_bench.virtual import VirtualSlider
import time

radio = IC7300()
slider = VirtualSlider("10.1.1.52")

slider.configure(
    min_val=1.8e6,
    max_val=30e6,
    value=14.2e6,
    step=1e3,
    label="Frequency",
    unit="MHz",
    orientation="vertical",
    scale="log"
)

while True:
    freq_hz = slider.get_value()
    radio.set_frequency(int(freq_hz))
    time.sleep(0.2)
```

### Attenuation Control

```python
from rf_bench.virtual import VirtualSlider
import socket

# Control RF attenuator via ESP32 SCPI
atten_sock = socket.socket()
atten_sock.connect(("10.1.1.42", 5025))

slider = VirtualSlider("10.1.1.52")

slider.configure(
    min_val=0,
    max_val=31.5,
    value=0,
    step=0.5,
    label="Attenuation",
    unit="dB",
    orientation="horizontal"
)

while True:
    atten_db = slider.get_value()
    cmd = f"ATTEN:VAL {atten_db}\n"
    atten_sock.sendall(cmd.encode())
    time.sleep(0.1)
```

### Voltage Sweep with PSU

```python
from rf_bench.siglent import SPD3303X
from rf_bench.virtual import VirtualSlider
import time

psu = SPD3303X("10.1.1.56")
slider = VirtualSlider("10.1.1.52")

slider.configure(
    min_val=0,
    max_val=32,
    value=12,
    step=0.1,
    label="Supply Voltage",
    unit="V",
    orientation="vertical"
)

psu.enable_output(1, True)

while True:
    voltage = slider.get_value()
    psu.set_voltage(1, voltage)
    time.sleep(0.05)
```

### Multi-Slider Control Panel

Run multiple backend servers on different ports:

```python
from rf_bench.virtual import VirtualSlider

# Power slider
power = VirtualSlider("10.1.1.52", port=5025)
power.configure(
    min_val=-60, max_val=10, value=-10,
    label="Power", unit="dBm",
    orientation="horizontal"
)

# Frequency slider
freq = VirtualSlider("10.1.1.52", port=5026)
freq.configure(
    min_val=1e6, max_val=30e6, value=14.2e6,
    label="Frequency", unit="MHz",
    orientation="vertical", scale="log"
)

# Attenuation slider
atten = VirtualSlider("10.1.1.52", port=5027)
atten.configure(
    min_val=0, max_val=31.5, value=0,
    label="Attenuation", unit="dB",
    orientation="horizontal"
)
```

## SCPI Command Reference

### IEEE 488.2 Common Commands
- `*IDN?` — Identification query
- `*RST` — Reset to defaults
- `SYST:ERR?` — Query error queue

### Slider Value Commands
- `SLID:VAL <value>` — Set slider value
- `SLID:VAL?` — Query slider value
- `SLID:UP` — Step up by step size
- `SLID:DOWN` — Step down by step size

### Configuration Commands
- `CONF:MIN <value>` — Set minimum value
- `CONF:MIN?` — Query minimum value
- `CONF:MAX <value>` — Set maximum value
- `CONF:MAX?` — Query maximum value
- `CONF:STEP <value>` — Set step size
- `CONF:STEP?` — Query step size
- `CONF:LABEL <string>` — Set label text
- `CONF:LABEL?` — Query label text
- `CONF:UNIT <string>` — Set unit text
- `CONF:UNIT?` — Query unit text
- `CONF:ORIEN <horizontal|vertical>` — Set orientation
- `CONF:ORIEN?` — Query orientation
- `CONF:SCALE <linear|log>` — Set scale type
- `CONF:SCALE?` — Query scale type
- `CONF:COLOR <color>` — Set slider color (hex: #RGB or #RRGGBB)
- `CONF:COLOR?` — Query slider color

### Direct SCPI Example

```bash
# Using netcat
echo "*IDN?" | nc localhost 5025
echo "SLID:VAL 50" | nc localhost 5025
echo "CONF:MIN 0" | nc localhost 5025
echo "CONF:MAX 100" | nc localhost 5025
echo "CONF:LABEL Power" | nc localhost 5025
echo "CONF:UNIT W" | nc localhost 5025
echo "CONF:ORIEN horizontal" | nc localhost 5025
echo "CONF:SCALE linear" | nc localhost 5025
echo "CONF:COLOR #4488ff" | nc localhost 5025
```

## Slider Display

The virtual slider displays:
- **Track**: Background bar showing full range
- **Thumb**: Draggable control (circular for horizontal, rectangular for vertical)
- **Value Display**: Current value with unit (above horizontal, beside vertical)
- **Label**: Text below slider
- **Scale**: Linear or logarithmic spacing
- **Orientation**: Horizontal (left-to-right) or vertical (bottom-to-top)

## Error Handling

```python
from rf_bench.virtual import VirtualSlider, VirtualSliderError

try:
    slider = VirtualSlider("10.1.1.99")  # Wrong IP
except VirtualSliderError as e:
    print(f"Connection failed: {e}")

try:
    slider.set_value(150)  # Out of range (max=100)
except ValueError as e:
    print(f"Invalid value: {e}")

try:
    slider.set_orientation("diagonal")  # Invalid orientation
except ValueError as e:
    print(f"Invalid orientation: {e}")

try:
    slider.set_scale("exponential")  # Invalid scale
except ValueError as e:
    print(f"Invalid scale: {e}")
```

## Requirements

- Python 3.7+
- No external dependencies (uses stdlib `socket`)

## License

GPL-3.0-or-later — see LICENSE file in package root.

## See Also

- Backend server: `~/Dropbox/build/rf-bench/virtual/slider/`
- BenchView panel manager: `~/Dropbox/build/rf-bench/virtual/benchview/`
- Other virtual instruments: `~/Dropbox/build/rf-bench/virtual/`
- RF Bench drivers: `~/Dropbox/build/rf-bench/drivers/`
