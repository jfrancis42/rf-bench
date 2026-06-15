# rf-bench-drivers-virtual-bar-graph

Python driver for **Virtual Bar Graph** SCPI instrument. Controls bar graph value, scale range, orientation, units, color, and color thresholds via SCPI-over-TCP (port 5025).

## Installation

```bash
pip install rf-bench-drivers-virtual-bar-graph
```

## Quick Start

```python
from rf_bench.virtual import VirtualBarGraph

# S-meter bar (0-9 scale)
with VirtualBarGraph("10.1.1.52") as bar:
    bar.configure(
        min_val=0,
        max_val=9,
        units="S",
        orientation="VERT",
        color="#00ff00"
    )
    bar.set_value(7.5)

# Power meter (0-100W with thresholds)
with VirtualBarGraph("10.1.1.52") as bar:
    bar.configure(
        min_val=0,
        max_val=100,
        units="W",
        orientation="HOR",
        color="#00ff00",
        threshold_yellow=70,
        threshold_red=90
    )
    bar.set_value(85)  # Bar turns yellow at 70W, red at 90W
```

## Multi-Instance Usage

For multiple bar-graphs controlled by a single backend (e.g., via BenchView), use the multi-instance driver:

```python
from rf_bench.virtual import VirtualBarGraphMulti

# Connect to multi-instance backend
# Port is assigned by BenchView and read from *_ports.yaml
bar_graphs = VirtualBarGraphMulti("localhost", port=5100)

# Control individual instances (1-based indexing)
bar_graphs.set_value(1, 50.0)  # Instance 1
bar_graphs.set_value(2, 75.0)  # Instance 2
bar_graphs.set_label(1, "Channel 1")
bar_graphs.set_label(2, "Channel 2")

# Query instance count
count = bar_graphs.get_count()  # → 2

bar_graphs.close()
```

**Multi-instance backend:**

```bash
cd ~/Dropbox/build/rf-bench/virtual/bar-graph/backend
python3 server-multi.py --scpi-port 5100 --http-port 8100 --count 2 --layout row
```

**Port Assignment:**

When using BenchView, ports are assigned dynamically and exported to:
- `~/.rf-bench/<panel-name>_ports.yaml` (inventory overlay)
- `<config-dir>/<panel-name>_ports.yaml` (legacy)

Bridge scripts should read port assignments from the YAML file rather than hardcoding them.

## Backend Server

The driver connects to a virtual bar graph backend server:

```bash
cd ~/Dropbox/build/rf-bench/virtual/bar-graph/backend
python3 server.py --scpi-port 5025 --http-port 8000
```

Open browser at `http://localhost:8000` to see the virtual bar graph.

## API Reference

### Connection

```python
VirtualBarGraph(host, port=5025, timeout=2.0)
```

- **host**: IP address or hostname of backend server
- **port**: SCPI TCP port (default 5025)
- **timeout**: Socket timeout in seconds

### IEEE 488.2 Commands

```python
bar.idn()           # → "N0GQ,Virtual-BarGraph,1.0,2026"
bar.reset()         # Reset to default state
bar.get_error()     # → "0,No error"
```

### Bar Value Control

```python
bar.set_value(45.3)       # Set bar value
bar.get_value()           # → 45.3
bar.update(50.0)          # Same as set_value (shorter name)
```

### Bar Configuration

```python
# Set scale range
bar.set_range(0, 100)     # Set min and max
bar.set_min(0)            # Set minimum only
bar.set_max(100)          # Set maximum only
bar.get_min()             # → 0.0
bar.get_max()             # → 100.0

# Set display properties
bar.set_units("W")        # Set units string
bar.get_units()           # → "W"
bar.set_orientation("HOR")  # HOR (horizontal) or VERT (vertical)
bar.get_orientation()     # → "HOR"
bar.set_color("#00ff00")  # Set bar color
bar.get_color()           # → "#00ff00"

# Set color thresholds
bar.set_thresholds(70, 90)  # Yellow at 70, red at 90
bar.get_thresholds()        # → (70.0, 90.0)

# Full configuration
bar.configure(
    min_val=0,
    max_val=100,
    units="W",
    orientation="HOR",
    color="#00ff00",
    threshold_yellow=70,
    threshold_red=90
)
```

### Animation

```python
# Animate through a sequence of values
bar.animate([10, 20, 30, 40, 50], interval=0.1)
```

## Common Use Cases

### IC-7300 S-meter Bar (0-9 scale)

```python
from rf_bench.icom import IC7300
from rf_bench.virtual import VirtualBarGraph
import time

radio = IC7300()
bar = VirtualBarGraph("10.1.1.52")

bar.configure(
    min_val=0,
    max_val=9,
    units="S",
    orientation="VERT",
    color="#00ff00"
)

while True:
    s_meter = radio.get_strength()  # Returns S-units (0-9)
    bar.set_value(s_meter)
    time.sleep(0.1)
```

### Power Monitor with Color Thresholds

```python
from rf_bench.siglent import SSA3000X
from rf_bench.virtual import VirtualBarGraph
import time

ssa = SSA3000X("10.1.1.60")
bar = VirtualBarGraph("10.1.1.52")

bar.configure(
    min_val=0,
    max_val=100,
    units="W",
    orientation="HOR",
    color="#00ff00",
    threshold_yellow=70,  # Caution
    threshold_red=90      # Danger
)

while True:
    # Measure power on spectrum analyzer
    power_dbm = ssa.get_marker_power(1)
    power_w = 10 ** ((power_dbm - 30) / 10)  # dBm → W
    bar.set_value(power_w)
    time.sleep(0.2)
```

### SWR Meter (1.0 to 3.0 scale)

```python
from rf_bench.virtual import VirtualBarGraph
import socket
import time

# Connect to ESP32 SCPI SWR meter
swr_sensor = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
swr_sensor.connect(("192.168.1.42", 5025))

bar = VirtualBarGraph("10.1.1.52")
bar.configure(
    min_val=1.0,
    max_val=3.0,
    units="SWR",
    orientation="VERT",
    color="#00ff00",
    threshold_yellow=1.5,
    threshold_red=2.0
)

while True:
    swr_sensor.sendall(b"MEAS:SWR?\n")
    swr = float(swr_sensor.recv(64).decode().strip())
    bar.set_value(swr)
    time.sleep(0.1)
```

### Battery Level Monitor (0-100%)

```python
from rf_bench.virtual import VirtualBarGraph
import psutil
import time

bar = VirtualBarGraph("10.1.1.52")
bar.configure(
    min_val=0,
    max_val=100,
    units="%",
    orientation="HOR",
    color="#00ff00",
    threshold_yellow=30,  # Low battery
    threshold_red=10      # Critical
)

while True:
    battery = psutil.sensors_battery()
    if battery:
        bar.set_value(battery.percent)
    time.sleep(5.0)
```

### Multi-Bar Dashboard

Run multiple backend servers on different ports:

```python
from rf_bench.virtual import VirtualBarGraph

# S-meter
s_meter = VirtualBarGraph("10.1.1.52", port=5025)
s_meter.configure(min_val=0, max_val=9, units="S", orientation="VERT")

# Power meter
power = VirtualBarGraph("10.1.1.52", port=5026)
power.configure(min_val=0, max_val=100, units="W", orientation="HOR",
                threshold_yellow=70, threshold_red=90)

# SWR meter
swr = VirtualBarGraph("10.1.1.52", port=5027)
swr.configure(min_val=1.0, max_val=3.0, units="SWR", orientation="VERT",
              threshold_yellow=1.5, threshold_red=2.0)

# Update all bars
s_meter.set_value(7.5)
power.set_value(85)
swr.set_value(1.3)
```

## SCPI Command Reference

### IEEE 488.2 Common Commands
- `*IDN?` — Identification query
- `*RST` — Reset to defaults
- `SYST:ERR?` — Query error queue

### Bar Value Commands
- `MEAS:VAL <value>` — Set bar value
- `MEAS:VAL?` — Query bar value

### Configuration Commands
- `CONF:MIN <value>` — Set minimum scale value
- `CONF:MIN?` — Query minimum scale value
- `CONF:MAX <value>` — Set maximum scale value
- `CONF:MAX?` — Query maximum scale value
- `CONF:UNIT <string>` — Set units string (e.g. "W", "V", "dBm", "%")
- `CONF:UNIT?` — Query units string
- `CONF:ORIENT <HOR|VERT>` — Set orientation (horizontal or vertical)
- `CONF:ORIENT?` — Query orientation
- `CONF:COL <color>` — Set bar color (CSS color: #RGB or #RRGGBB or name)
- `CONF:COL?` — Query bar color
- `CONF:THRES <yellow>,<red>` — Set color thresholds (yellow, red)
- `CONF:THRES?` — Query color thresholds

### Direct SCPI Example

```bash
# Using netcat
echo "*IDN?" | nc localhost 5025
echo "CONF:MIN 0" | nc localhost 5025
echo "CONF:MAX 100" | nc localhost 5025
echo "CONF:UNIT W" | nc localhost 5025
echo "CONF:ORIENT HOR" | nc localhost 5025
echo "CONF:THRES 70,90" | nc localhost 5025
echo "MEAS:VAL 85" | nc localhost 5025
```

## Bar Display

The virtual bar graph displays:
- **Bar fill**: Proportional to current value within min/max range
- **Color**: Green by default, yellow above first threshold, red above second threshold
- **Value text**: Numeric value with units displayed above/beside bar
- **Scale**: Min and max values shown at bar endpoints
- **Orientation**: Vertical (default) or horizontal layout

## Error Handling

```python
from rf_bench.virtual import VirtualBarGraph, VirtualBarGraphError

try:
    bar = VirtualBarGraph("10.1.1.99")  # Wrong IP
except VirtualBarGraphError as e:
    print(f"Connection failed: {e}")

try:
    bar.set_orientation("DIAGONAL")  # Invalid orientation
except ValueError as e:
    print(f"Invalid orientation: {e}")

# Query error queue
error_code, error_msg = bar.get_error().split(',', 1)
if error_code != "0":
    print(f"Instrument error: {error_msg}")
```

## Requirements

- Python 3.7+
- No external dependencies (uses stdlib `socket`)

## License

GPL-3.0-or-later — see LICENSE file in package root.

## See Also

- Backend server: `~/Dropbox/build/rf-bench/virtual/bar-graph/`
- BenchView panel manager: `~/Dropbox/build/rf-bench/virtual/benchview/`
- Other virtual instruments: `~/Dropbox/build/rf-bench/virtual/`
- RF Bench drivers: `~/Dropbox/build/rf-bench/drivers/`
