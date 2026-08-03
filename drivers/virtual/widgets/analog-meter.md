# Analog Meter — part of `rf-bench-drivers-virtual`
Python driver for **Virtual Analog Meter** SCPI instrument. Controls 1-4 analog panel meters via SCPI-over-TCP (port 5025).

## Installation

```bash
pip install rf-bench-drivers-virtual
```

## Quick Start

```python
from rf_bench.virtual import VirtualAnalogMeter

# Single meter
with VirtualAnalogMeter("10.1.1.52") as meter:
    meter.configure(1, label="TX Power", units="W", min_val=0, max_val=100)
    meter.set_value(1, 45.3)

# Multiple meters
with VirtualAnalogMeter("10.1.1.52") as meters:
    meters.set_count(2)
    
    meters.configure(1, "TX Power", "W", 0, 100)
    meters.configure(2, "Voltage", "V", 0, 15)
    
    meters.set_value(1, 50.2)
    meters.set_value(2, 13.8)
```

## Multi-Instance Usage

For multiple analog-meters controlled by a single backend (e.g., via BenchView), use the multi-instance driver:

```python
from rf_bench.virtual import VirtualAnalogMeterMulti

# Connect to multi-instance backend
# Port is assigned by BenchView and read from *_ports.yaml
meters = VirtualAnalogMeterMulti("localhost", port=5100)

# Control individual instances (1-based indexing)
meters.set_value(1, 50.0)  # Instance 1
meters.set_value(2, 75.0)  # Instance 2
meters.set_label(1, "Channel 1")
meters.set_label(2, "Channel 2")

# Query instance count
count = meters.get_count()  # → 2

meters.close()
```

**Multi-instance backend:**

```bash
cd ~/Dropbox/build/rf-bench/virtual/analog-meter/backend
python3 server-multi.py --scpi-port 5100 --http-port 8100 --count 2 --layout row
```

**Port Assignment:**

When using BenchView, ports are assigned dynamically and exported to:
- `~/.rf-bench/<panel-name>_ports.yaml` (inventory overlay)
- `<config-dir>/<panel-name>_ports.yaml` (legacy)

Bridge scripts should read port assignments from the YAML file rather than hardcoding them.

## Backend Server

The driver connects to a virtual analog meter backend server:

```bash
cd ~/Dropbox/build/rf-bench/virtual/analog-meter/backend
python3 server-multi.py --scpi-port 5025 --http-port 8000 --count 2 --layout ROW
```

Open browser at `http://localhost:8000` to see the virtual meters.

## API Reference

### Connection

```python
VirtualAnalogMeter(host, port=5025, timeout=2.0)
```

- **host**: IP address or hostname of backend server
- **port**: SCPI TCP port (default 5025)
- **timeout**: Socket timeout in seconds

### IEEE 488.2 Commands

```python
meter.idn()           # → "N0GQ,Virtual-Analog-Meter-Multi,1.0,2026"
meter.reset()         # Reset to default state
meter.get_error()     # → "0,No error"
```

### Multi-Instance Management

```python
meter.set_count(2)              # Display 2 meters (1-4)
meter.get_count()               # → 2

meter.set_layout("ROW")         # ROW, COL, or 2X2
meter.get_layout()              # → "ROW"
```

### Meter Configuration (1-based indexing)

```python
# Full configuration
meter.configure(1,
    label="TX Power",
    units="W",
    min_val=0,
    max_val=100,
    color="#00ff88"  # Optional, default green
)

# Individual settings
meter.set_label(1, "TX Power")
meter.set_units(1, "W")
meter.set_range(1, min_val=0, max_val=100)
meter.set_min(1, 0)
meter.set_max(1, 100)
meter.set_color(1, "#ff0000")  # Red needle

# Query settings
meter.get_label(1)      # → "TX Power"
meter.get_units(1)      # → "W"
meter.get_min(1)        # → 0.0
meter.get_max(1)        # → 100.0
meter.get_color(1)      # → "#00ff88"
```

### Meter Value Control

```python
meter.set_value(1, 45.3)    # Set meter 1 to 45.3 W
meter.update(1, 50.2)       # Shorter alias
meter.get_value(1)          # → 50.2

# Values are clamped to min/max range
meter.set_range(1, 0, 100)
meter.set_value(1, 150)     # Clamped to 100
```

### Animation

```python
import numpy as np

# Smooth sweep
values = np.linspace(0, 100, 50)
meter.animate(1, values, interval=0.05)

# Sine wave
t = np.linspace(0, 4*np.pi, 100)
values = 50 + 30 * np.sin(t)
meter.animate(1, values, interval=0.02)
```

## Common Use Cases

### Power Meter (SSA3032X tracking generator)

```python
from rf_bench.siglent import SSA3000X
from rf_bench.virtual import VirtualAnalogMeter
import time

ssa = SSA3000X("10.1.1.60")
meter = VirtualAnalogMeter("10.1.1.52")

meter.configure(1, "RF Power", "dBm", -50, 10)

ssa.set_center_span(14.2e6, 10e3)
ssa.tracking_on()

while True:
    ssa.peak_search()
    _, power = ssa.get_peak()
    meter.set_value(1, power)
    time.sleep(0.1)
```

### S-Meter (IC-7300 radio)

```python
from rf_bench.icom import IC7300
from rf_bench.virtual import VirtualAnalogMeter
import time

radio = IC7300()
meter = VirtualAnalogMeter("10.1.1.52")

meter.configure(1, "Signal Strength", "S", 0, 9, color="#00ff00")

radio.set_frequency(14_200_000)
radio.set_mode("USB")

while True:
    s_units = radio.get_strength_settled()
    meter.set_value(1, s_units)
    time.sleep(0.2)
```

### Dual Power Monitor (TX/Reflected)

```python
from rf_bench.virtual import VirtualAnalogMeter
import time
import random

meter = VirtualAnalogMeter("10.1.1.52")
meter.set_count(2)
meter.set_layout("ROW")

meter.configure(1, "Forward", "W", 0, 100, color="#00ff00")
meter.configure(2, "Reflected", "W", 0, 20, color="#ff0000")

while True:
    fwd = random.uniform(45, 55)
    ref = random.uniform(0, 5)
    meter.set_value(1, fwd)
    meter.set_value(2, ref)
    time.sleep(0.5)
```

### Battery Monitor (Voltage + Current)

```python
from rf_bench.siglent import SPD3303X
from rf_bench.virtual import VirtualAnalogMeter
import time

psu = SPD3303X("10.1.1.56")
meter = VirtualAnalogMeter("10.1.1.52")

meter.set_count(2)
meter.configure(1, "Voltage", "V", 0, 15)
meter.configure(2, "Current", "A", 0, 3)

psu.set_voltage(1, 13.8)
psu.set_current(1, 2.0)
psu.enable(1)

while True:
    v = psu.measure_voltage(1)
    i = psu.measure_current(1)
    meter.set_value(1, v)
    meter.set_value(2, i)
    time.sleep(0.5)
```

### Multi-Meter Dashboard (2×2 grid)

```python
from rf_bench.virtual import VirtualAnalogMeter
import time
import math

meter = VirtualAnalogMeter("10.1.1.52")
meter.set_count(4)
meter.set_layout("2X2")

meter.configure(1, "Power", "W", 0, 100, "#00ff00")
meter.configure(2, "Voltage", "V", 0, 15, "#0088ff")
meter.configure(3, "Current", "A", 0, 10, "#ff8800")
meter.configure(4, "SWR", "", 1, 3, "#ff0000")

t = 0
while True:
    meter.set_value(1, 50 + 10 * math.sin(t))
    meter.set_value(2, 13.8 + 0.2 * math.sin(t * 1.3))
    meter.set_value(3, 3.6 + 0.5 * math.sin(t * 0.7))
    meter.set_value(4, 1.2 + 0.1 * abs(math.sin(t * 2)))
    t += 0.1
    time.sleep(0.05)
```

## SCPI Command Reference

All commands use 1-based indexing (N=1,2,3,4):

### IEEE 488.2 Common Commands
- `*IDN?` — Identification query
- `*RST` — Reset to defaults
- `SYST:ERR?` — Query error queue

### Multi-Instance Commands
- `INST:COUNT <1-4>` — Set meter count
- `INST:COUNT?` — Query meter count
- `INST:LAY <ROW|COL|2X2>` — Set layout
- `INST:LAY?` — Query layout

### Meter Commands (N = 1-4)
- `MEAS<N>:VAL <float>` — Set value
- `MEAS<N>:VAL?` — Query value
- `CONF<N>:MIN <float>` — Set minimum
- `CONF<N>:MIN?` — Query minimum
- `CONF<N>:MAX <float>` — Set maximum
- `CONF<N>:MAX?` — Query maximum
- `CONF<N>:UNIT <string>` — Set units
- `CONF<N>:UNIT?` — Query units
- `CONF<N>:LAB <string>` — Set label
- `CONF<N>:LAB?` — Query label
- `CONF<N>:COL <color>` — Set needle color
- `CONF<N>:COL?` — Query color

### Direct SCPI Example

```bash
# Using netcat
echo "INST:COUNT 2" | nc localhost 5025
echo "CONF1:LAB TX Power" | nc localhost 5025
echo "CONF1:UNIT W" | nc localhost 5025
echo "CONF1:MIN 0" | nc localhost 5025
echo "CONF1:MAX 100" | nc localhost 5025
echo "MEAS1:VAL 45.3" | nc localhost 5025
```

## Meter Display

The virtual meter displays:
- **Needle**: Moves smoothly with spring-damper physics
- **Arc**: 270° sweep from 7-8 o'clock (SW) to 1-2 o'clock (NE)
- **Zones**: Green (0-70%), yellow (70-85%), red (85-100%) by default
- **Scale**: 11 tick marks with numeric labels (0, 10, 20, ..., 100)
- **Value**: Numeric readout below center
- **Units**: Below numeric value
- **Label**: Above meter arc

## Error Handling

```python
from rf_bench.virtual import VirtualAnalogMeter, VirtualAnalogMeterError

try:
    meter = VirtualAnalogMeter("10.1.1.99")  # Wrong IP
except VirtualAnalogMeterError as e:
    print(f"Connection failed: {e}")

try:
    meter.set_value(5, 100)  # Index out of range
except ValueError as e:
    print(f"Invalid index: {e}")
```

## Requirements

- Python 3.7+
- No external dependencies (uses stdlib `socket`)

## License

GPL-3.0-or-later — see LICENSE file in package root.

## See Also

- Backend server: `~/Dropbox/build/rf-bench/virtual/analog-meter/`
- BenchView panel manager: `~/Dropbox/build/rf-bench/virtual/benchview/`
- Other virtual instruments: `~/Dropbox/build/rf-bench/virtual/`
- RF Bench drivers: `~/Dropbox/build/rf-bench/drivers/`
