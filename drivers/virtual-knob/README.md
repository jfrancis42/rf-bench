# rf-bench-drivers-virtual-knob

Python driver for **Virtual Rotary Knob** SCPI instrument. Controls knob value, range, step size, wrap-around behavior, appearance (color, size, label, units) via SCPI-over-TCP (port 5025).

## Installation

```bash
pip install rf-bench-drivers-virtual-knob
```

## Quick Start

```python
from rf_bench.virtual import VirtualKnob

# RF gain control (-10 to +10 dB with 0.5 dB steps)
with VirtualKnob("10.1.1.52") as knob:
    knob.configure(
        min_val=-10,
        max_val=10,
        step=0.5,
        label="RF Gain",
        unit="dB",
        color="#4A90E2"
    )
    knob.set_value(0)   # Set to 0 dB

# Frequency tuning (7.000-7.300 MHz with wrap-around)
with VirtualKnob("10.1.1.52") as knob:
    knob.configure(
        min_val=7000000,
        max_val=7300000,
        step=1000,
        wrap=True,
        label="Frequency",
        unit="Hz",
        color="#FF5733"
    )
    knob.set_value(7100000)
```

## Multi-Instance Usage

For multiple knobs controlled by a single backend (e.g., via BenchView), use the multi-instance driver:

```python
from rf_bench.virtual import VirtualKnobMulti

# Connect to multi-instance backend
# Port is assigned by BenchView and read from *_ports.yaml
knobs = VirtualKnobMulti("localhost", port=5100)

# Control individual instances (1-based indexing)
knobs.set_value(1, 50.0)  # Instance 1
knobs.set_value(2, 75.0)  # Instance 2
knobs.set_label(1, "Channel 1")
knobs.set_label(2, "Channel 2")

# Query instance count
count = knobs.get_count()  # → 2

knobs.close()
```

**Multi-instance backend:**

```bash
cd ~/Dropbox/build/rf-bench/virtual/knob/backend
python3 server-multi.py --scpi-port 5100 --http-port 8100 --count 2 --layout row
```

**Port Assignment:**

When using BenchView, ports are assigned dynamically and exported to:
- `~/.rf-bench/<panel-name>_ports.yaml` (inventory overlay)
- `<config-dir>/<panel-name>_ports.yaml` (legacy)

Bridge scripts should read port assignments from the YAML file rather than hardcoding them.

## Backend Server

The driver connects to a virtual knob backend server:

```bash
cd ~/Dropbox/build/rf-bench/virtual/knob/backend
python3 server.py --scpi-port 5025 --http-port 8000
```

Open browser at `http://localhost:8000` to see the virtual knob.

## API Reference

### Connection

```python
VirtualKnob(host, port=5025, timeout=5.0)
```

- **host**: IP address or hostname of backend server
- **port**: SCPI TCP port (default 5025)
- **timeout**: Socket timeout in seconds

### IEEE 488.2 Commands

```python
knob.idn()           # → "N0GQ,Virtual-Knob,00001,1.0"
knob.reset()         # Reset to default state
knob.get_error()     # → "0,No error"
```

### Knob Value Control

```python
knob.set_value(50)        # Set value to 50
knob.get_value()          # → 50.0

# Value is clamped to [min, max] unless wrap is enabled
# If step > 0, value is quantized to nearest step
```

### Range Configuration

```python
knob.set_min(-10)         # Set minimum value
knob.get_min()            # → -10.0

knob.set_max(10)          # Set maximum value
knob.get_max()            # → 10.0

knob.set_step(0.5)        # Set step size (0 = continuous)
knob.get_step()           # → 0.5

knob.set_wrap(True)       # Enable wrap-around
knob.get_wrap()           # → True
```

### Appearance Configuration

```python
knob.set_label("Volume")       # Set label text
knob.get_label()               # → "Volume"

knob.set_unit("dB")           # Set unit string
knob.get_unit()               # → "dB"

knob.set_color("#4A90E2")     # Set knob color (hex)
knob.get_color()              # → "#4A90E2"

knob.set_size(150)            # Set diameter (100-250 pixels)
knob.get_size()               # → 150
```

### Bulk Configuration

```python
# Configure all parameters at once
knob.configure(
    min_val=0,
    max_val=100,
    step=1,
    wrap=False,
    label="Volume",
    unit="%",
    color="#4A90E2",
    size=150
)
```

## Common Use Cases

### RF Gain Control

```python
from rf_bench.icom import IC7300
from rf_bench.virtual import VirtualKnob
import time

radio = IC7300()
knob = VirtualKnob("10.1.1.52")

knob.configure(
    min_val=-10,
    max_val=10,
    step=0.5,
    label="RF Gain",
    unit="dB"
)

knob.set_value(0)  # Start at 0 dB

while True:
    gain = knob.get_value()
    # Apply gain to radio (method depends on radio model)
    # radio.set_rf_gain(gain)
    time.sleep(0.1)
```

### Frequency Tuning with Wrap-Around

```python
from rf_bench.icom import IC7300
from rf_bench.virtual import VirtualKnob
import time

radio = IC7300()
knob = VirtualKnob("10.1.1.52")

# 40m band (7.000-7.300 MHz)
knob.configure(
    min_val=7000000,
    max_val=7300000,
    step=1000,           # 1 kHz steps
    wrap=True,           # Wrap around at band edges
    label="Frequency",
    unit="Hz",
    color="#FF5733"
)

knob.set_value(7100000)

while True:
    freq = knob.get_value()
    radio.set_frequency(freq)
    time.sleep(0.05)
```

### Volume Control (0-100%)

```python
from rf_bench.virtual import VirtualKnob
import subprocess
import time

knob = VirtualKnob("10.1.1.52")

knob.configure(
    min_val=0,
    max_val=100,
    step=5,              # 5% steps
    label="Volume",
    unit="%",
    color="#00AA00"
)

knob.set_value(50)

while True:
    volume = int(knob.get_value())
    # Set system volume (Linux example)
    subprocess.run(['amixer', 'sset', 'Master', f'{volume}%'],
                   check=False, stdout=subprocess.DEVNULL)
    time.sleep(0.2)
```

### Attenuator Control (0-31.5 dB, 0.5 dB steps)

```python
from rf_bench.siglent import SDG1000X
from rf_bench.virtual import VirtualKnob
import time

gen = SDG1000X("10.1.1.55")
knob = VirtualKnob("10.1.1.52")

knob.configure(
    min_val=0,
    max_val=31.5,
    step=0.5,
    label="Attenuation",
    unit="dB",
    color="#FF8800"
)

knob.set_value(0)

while True:
    atten = knob.get_value()
    # Adjust generator amplitude to compensate
    output_dbm = 0 - atten  # Target 0 dBm at DUT
    gen.set_amplitude(1, output_dbm, unit='DBM')
    time.sleep(0.1)
```

### Sweep Rate Control (0.1-10 Hz)

```python
from rf_bench.virtual import VirtualKnob
import time

knob = VirtualKnob("10.1.1.52")

knob.configure(
    min_val=0.1,
    max_val=10,
    step=0.1,
    label="Sweep Rate",
    unit="Hz",
    color="#9C27B0"
)

knob.set_value(1.0)

while True:
    rate = knob.get_value()
    period = 1.0 / rate
    print(f"Sweep period: {period:.2f} s")
    time.sleep(0.5)
```

## SCPI Command Reference

### IEEE 488.2 Common Commands
- `*IDN?` — Identification query
- `*RST` — Reset to defaults (value=0, min=0, max=100, step=0, wrap=off, label="Knob")
- `SYST:ERR?` — Query error queue

### Value Commands
- `MEAS:VAL <number>` — Set knob value
- `MEAS:VAL?` — Query knob value

### Range Configuration Commands
- `CONF:MIN <number>` — Set minimum value
- `CONF:MIN?` — Query minimum value
- `CONF:MAX <number>` — Set maximum value
- `CONF:MAX?` — Query maximum value
- `CONF:STEP <number>` — Set step size (0 = continuous)
- `CONF:STEP?` — Query step size
- `CONF:WRAP <0|1>` — Set wrap-around (0=off, 1=on)
- `CONF:WRAP?` — Query wrap-around state

### Appearance Configuration Commands
- `CONF:LABEL <string>` — Set label text
- `CONF:LABEL?` — Query label text
- `CONF:UNIT <string>` — Set unit string
- `CONF:UNIT?` — Query unit string
- `CONF:COL <color>` — Set knob color (hex: #RGB or #RRGGBB)
- `CONF:COL?` — Query knob color
- `CONF:SIZE <pixels>` — Set knob diameter (100-250)
- `CONF:SIZE?` — Query knob size

### Direct SCPI Example

```bash
# Using netcat
echo "*IDN?" | nc localhost 5025
echo "MEAS:VAL 50" | nc localhost 5025
echo "CONF:MIN -10" | nc localhost 5025
echo "CONF:MAX 10" | nc localhost 5025
echo "CONF:STEP 0.5" | nc localhost 5025
echo "CONF:LABEL RF Gain" | nc localhost 5025
echo "CONF:UNIT dB" | nc localhost 5025
echo "MEAS:VAL?" | nc localhost 5025
```

## Knob Display

The virtual knob displays:
- **Rotary encoder**: 3D knob with position indicator and tick marks
- **Value**: Large numeric display with units (e.g., "50.0 dB")
- **Label**: Text below the knob
- **Range**: Visual indicator showing min/max/current position
- **Mouse control**: Click and drag to rotate, scroll wheel for fine adjustment
- **Keyboard control**: Arrow keys, Page Up/Down, Home/End
- **Size**: Configurable diameter (100-250 pixels, default 150)
- **Color**: Configurable knob color (default #4A90E2 blue)

## Behavior

### Step Quantization

When `step > 0`, all values are quantized:
```python
knob.configure(min_val=0, max_val=100, step=5)
knob.set_value(47)   # Quantized to 45
knob.get_value()     # → 45.0
```

### Wrap-Around

When `wrap=True`, rotating past max wraps to min:
```python
knob.configure(min_val=0, max_val=100, wrap=True)
knob.set_value(100)
# Rotate up → wraps to 0
```

When `wrap=False`, value is clamped:
```python
knob.configure(min_val=0, max_val=100, wrap=False)
knob.set_value(150)  # Clamped to 100
knob.get_value()     # → 100.0
```

### Continuous vs Stepped

- `step=0`: Continuous rotation (smooth values)
- `step>0`: Discrete steps (e.g., step=1 for integer values)

## Error Handling

```python
from rf_bench.virtual import VirtualKnob, VirtualKnobError

try:
    knob = VirtualKnob("10.1.1.99")  # Wrong IP
except VirtualKnobError as e:
    print(f"Connection failed: {e}")

try:
    knob = VirtualKnob("10.1.1.52")
    knob.set_size(300)  # Out of range (100-250)
except VirtualKnobError as e:
    print(f"Command failed: {e}")

# Check error queue
err = knob.get_error()
if not err.startswith("0,"):
    print(f"SCPI error: {err}")
```

## Requirements

- Python 3.7+
- No external dependencies (uses stdlib `socket`)

## License

GPL-3.0-or-later — see LICENSE file in package root.

## See Also

- Backend server: `~/Dropbox/build/rf-bench/virtual/knob/`
- BenchView panel manager: `~/Dropbox/build/rf-bench/virtual/benchview/`
- Other virtual instruments: `~/Dropbox/build/rf-bench/virtual/`
- RF Bench drivers: `~/Dropbox/build/rf-bench/drivers/`
