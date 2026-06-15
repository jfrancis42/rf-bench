# rf-bench-drivers-virtual-line-chart

Python driver for **Virtual Line Chart** SCPI instrument. Time-series scrolling line chart with configurable history, auto-scaling, and threshold zones.

## Installation

```bash
pip install rf-bench-drivers-virtual-line-chart
```

Or install from source:

```bash
cd drivers/virtual-line-chart
pip install -e .
```

## Quick Start

```python
from rf_bench.virtual import VirtualLineChart

# Basic usage
with VirtualLineChart("10.1.1.52") as chart:
    chart.set_title("Temperature Monitor")
    chart.set_units("°C")
    chart.add_value(25.3)
    chart.add_value(25.5)

# With manual scaling
with VirtualLineChart("10.1.1.52") as chart:
    chart.configure(
        title="RF Power",
        units="dBm",
        min_val=-50,
        max_val=10,
        color="#00ff00"
    )
    chart.add_value(-23.4)
```

## Backend Server

The driver connects to a virtual line chart backend server:

```bash
cd ~/Dropbox/build/rf-bench/virtual/line-chart/backend
python3 server.py
```

The server exposes:
- **SCPI TCP** on port 5004 (configurable)
- **HTTP** on port 8004 (serves web UI)
- **WebSocket** on port 8004/ws (real-time updates)
- **MQTT subscriber** (optional, configured via SCPI)

Open browser at `http://localhost:8004` to see the chart.

## API Reference

### Connection

```python
VirtualLineChart(host, port=5004, timeout=2.0)
```

- **host**: IP address or hostname of backend server
- **port**: SCPI TCP port (default 5004)
- **timeout**: Socket timeout in seconds

### IEEE 488.2 Commands

```python
chart.idn()           # → "N0GQ,Virtual-Line-Chart,1.0,2026"
chart.reset()         # Reset to default state
chart.get_error()     # → "0,No error"
```

### Measurement

```python
# Add data point
chart.add_value(25.3)

# Query most recent value
chart.get_value()     # → 25.3
```

### Configuration

```python
# Full configuration
chart.configure(
    title="Temperature Monitor",
    units="°C",
    min_val=0,          # Optional, None for auto
    max_val=100,        # Optional, None for auto
    color="#00ff00",    # Optional, default green
    history=200         # Optional, default 100
)

# Individual settings
chart.set_title("Temperature Monitor")
chart.set_units("°C")
chart.set_history_length(200)  # 10-1000 samples
chart.set_color("#00ff00")     # CSS color

# Y-axis range
chart.set_range(-50, 10)       # Set both min/max
chart.set_min(-50)             # Set minimum only
chart.set_max(10)              # Set maximum only

# Auto-scaling
chart.set_auto_scale(True)     # Enable auto-scaling
chart.set_auto_scale(False)    # Disable auto-scaling

# Query settings
chart.get_title()              # → "Temperature Monitor"
chart.get_units()              # → "°C"
chart.get_history_length()     # → 200
chart.get_color()              # → "#00ff00"
chart.get_min()                # → "-50" or "AUTO"
chart.get_max()                # → "10" or "AUTO"
chart.get_auto_scale()         # → True/False
```

### MQTT Integration

```python
# Configure MQTT broker and topic
chart.configure_mqtt("10.1.0.20", "sensors/temperature")

# Query MQTT config
chart.get_mqtt_config()        # → "10.1.0.20,sensors/temperature"
```

Once configured, the chart automatically updates when numeric messages arrive on the MQTT topic. MQTT payload must be a number (int or float as string).

### Streaming Data

```python
import numpy as np

# Stream values with delay
values = np.linspace(0, 100, 50)
chart.stream(values, interval=0.1)

# Sine wave
t = np.linspace(0, 4*np.pi, 100)
values = 50 + 30 * np.sin(t)
chart.stream(values, interval=0.05)
```

## Common Use Cases

### Spectrum Analyzer Power Monitor

```python
from rf_bench.siglent import SSA3000X
from rf_bench.virtual import VirtualLineChart
import time

ssa = SSA3000X("10.1.1.60")
chart = VirtualLineChart("10.1.1.52")

chart.configure("RF Power", "dBm", -60, 10, history=300)

ssa.set_center_span(14.2e6, 10e3)
ssa.tracking_on()

while True:
    ssa.peak_search()
    _, power = ssa.get_peak()
    chart.add_value(power)
    time.sleep(0.1)
```

### Radio S-Meter Logger

```python
from rf_bench.icom import IC7300
from rf_bench.virtual import VirtualLineChart
import time

radio = IC7300()
chart = VirtualLineChart("10.1.1.52")

chart.configure("Signal Strength", "S-units", 0, 9, "#00ff00", history=500)

radio.set_frequency(14_200_000)
radio.set_mode("USB")

while True:
    s_units = radio.get_strength_settled()
    chart.add_value(s_units)
    time.sleep(0.2)
```

### Temperature Monitor (DMM)

```python
from rf_bench.siglent import SDM3000X
from rf_bench.virtual import VirtualLineChart
import time

dmm = SDM3000X("10.1.1.63")
chart = VirtualLineChart("10.1.1.52")

chart.configure("Temperature", "°C", 20, 30, history=600)
dmm.configure_temperature("PT100", "4W")

while True:
    temp = dmm.measure_temperature()
    chart.add_value(temp)
    time.sleep(1.0)
```

### Voltage Monitor (PSU)

```python
from rf_bench.siglent import SPD3303X
from rf_bench.virtual import VirtualLineChart
import time

psu = SPD3303X("10.1.1.56")
chart = VirtualLineChart("10.1.1.52")

chart.configure("Supply Voltage", "V", 0, 15, history=300)

psu.set_voltage(1, 13.8)
psu.set_current(1, 2.0)
psu.enable(1)

while True:
    v = psu.measure_voltage(1)
    chart.add_value(v)
    time.sleep(0.2)
```

### Current Monitor (DC Load)

```python
from rf_bench.yertai import ET5406A
from rf_bench.virtual import VirtualLineChart
import time

load = ET5406A("/dev/ttyUSB0")
chart = VirtualLineChart("10.1.1.52")

chart.configure("Load Current", "A", 0, 5, "#ff8800", history=400)

load.set_mode("CC")
load.set_current(2.0)
load.enable()

while True:
    i = load.measure_current()
    chart.add_value(i)
    time.sleep(0.1)
```

### RTL-SDR Power Logger

```python
from rf_bench.rtlsdr import RTLSDR
from rf_bench.virtual import VirtualLineChart
import numpy as np
import time

sdr = RTLSDR()
chart = VirtualLineChart("10.1.1.52")

chart.configure("Band Power", "dBFS", -80, -20, history=500)

sdr.set_frequency(144.39e6)
sdr.set_sample_rate(2.4e6)
sdr.set_gain("auto")

while True:
    samples = sdr.read_samples(256 * 1024)
    power_db = 10 * np.log10(np.mean(np.abs(samples)**2))
    chart.add_value(power_db)
    time.sleep(0.1)
```

### GPS Altitude Logger

```python
from rf_bench.gpsd import GPSD
from rf_bench.virtual import VirtualLineChart
import time

gps = GPSD()
chart = VirtualLineChart("10.1.1.52")

chart.configure("Altitude", "m", 1000, 2000, history=600)

while True:
    fix = gps.get_current_fix()
    if fix and fix.altitude is not None:
        chart.add_value(fix.altitude)
    time.sleep(1.0)
```

### MQTT Temperature Stream

```python
from rf_bench.virtual import VirtualLineChart

chart = VirtualLineChart("10.1.1.52")

chart.configure(
    title="Workshop Temperature",
    units="°C",
    min_val=15,
    max_val=35,
    history=1000
)

# Subscribe to MQTT topic — chart updates automatically
chart.configure_mqtt("10.1.0.20", "workshop/temperature")

# Now the chart receives updates via MQTT and no Python loop is needed
# MQTT messages with numeric payloads automatically add data points
```

### Multi-Trace Monitoring (Multiple Charts)

```python
from rf_bench.siglent import SPD3303X
from rf_bench.virtual import VirtualLineChart
import time

psu = SPD3303X("10.1.1.56")

# Run two backend servers on different ports
# Terminal 1: python3 server.py --scpi-port 5004 --http-port 8004
# Terminal 2: python3 server.py --scpi-port 5030 --http-port 8005

voltage_chart = VirtualLineChart("10.1.1.52", port=5004)
current_chart = VirtualLineChart("10.1.1.52", port=5030)

voltage_chart.configure("Supply Voltage", "V", 0, 15)
current_chart.configure("Supply Current", "A", 0, 3)

psu.set_voltage(1, 13.8)
psu.set_current(1, 2.0)
psu.enable(1)

while True:
    v = psu.measure_voltage(1)
    i = psu.measure_current(1)
    voltage_chart.add_value(v)
    current_chart.add_value(i)
    time.sleep(0.2)
```

### Beacon Strength Logger (IC-9700)

```python
from rf_bench.icom import IC9700
from rf_bench.virtual import VirtualLineChart
import time

radio = IC9700()
chart = VirtualLineChart("10.1.1.52")

chart.configure("Beacon Strength", "dBm", -120, -60, "#00ff00", history=1000)

radio.set_frequency(144_300_000)  # 2m beacon
radio.set_mode("CW")
radio.set_agc("slow")

while True:
    strength = radio.get_strength_settled()
    chart.add_value(strength)
    time.sleep(1.0)
```

## SCPI Command Reference

### IEEE 488.2 Common Commands
- `*IDN?` — Identification query
- `*RST` — Reset to defaults
- `SYST:ERR?` — Query error queue

### Measurement Commands
- `MEAS:VAL <float>` — Add data point
- `MEAS:VAL?` — Query most recent value

### Configuration Commands
- `CONF:HIST <10-1000>` — Set history length
- `CONF:HIST?` — Query history length
- `CONF:MIN <float>` — Set Y-axis minimum
- `CONF:MIN?` — Query minimum (returns "AUTO" or value)
- `CONF:MAX <float>` — Set Y-axis maximum
- `CONF:MAX?` — Query maximum (returns "AUTO" or value)
- `CONF:AUTO <ON|OFF>` — Enable/disable auto-scaling
- `CONF:AUTO?` — Query auto-scaling state
- `CONF:UNIT <string>` — Set display units
- `CONF:UNIT?` — Query display units
- `CONF:COL <color>` — Set line color (CSS, e.g., "#00ff00")
- `CONF:COL?` — Query line color
- `CONF:TITLE <string>` — Set chart title
- `CONF:TITLE?` — Query chart title

### MQTT Commands
- `MQTT:CONF <host>,<topic>` — Configure MQTT broker and topic
- `MQTT:CONF?` — Query MQTT configuration

### Direct SCPI Example

```bash
# Using netcat
echo "CONF:TITLE Temperature Monitor" | nc localhost 5004
echo "CONF:UNIT °C" | nc localhost 5004
echo "CONF:HIST 200" | nc localhost 5004
echo "CONF:AUTO OFF" | nc localhost 5004
echo "CONF:MIN 0" | nc localhost 5004
echo "CONF:MAX 100" | nc localhost 5004
echo "MEAS:VAL 25.3" | nc localhost 5004
echo "MEAS:VAL 26.1" | nc localhost 5004
```

## Chart Display

The virtual chart shows:
- **Scrolling line**: Right-to-left with spring-damped interpolation
- **X-axis**: Relative time (most recent = 0 seconds)
- **Y-axis**: Auto-scales to data range (or fixed if configured)
- **Threshold zones**: Green/yellow/red background zones (configurable in frontend)
- **Title**: Above chart
- **Units**: On Y-axis label
- **Current value**: Numeric readout

## Error Handling

```python
from rf_bench.virtual import VirtualLineChart, VirtualLineChartError

try:
    chart = VirtualLineChart("10.1.1.99")  # Wrong IP
except VirtualLineChartError as e:
    print(f"Connection failed: {e}")

try:
    chart.set_history_length(5000)  # Out of range
except ValueError as e:
    print(f"Invalid parameter: {e}")
```

## Requirements

- Python 3.7+
- No external dependencies (uses stdlib `socket`)

## License

GPL-3.0-or-later — see LICENSE file in package root.

## See Also

- Backend server: `~/Dropbox/build/rf-bench/virtual/line-chart/`
- Other virtual instruments: `~/Dropbox/build/rf-bench/virtual/`
- RF Bench drivers: `~/Dropbox/build/rf-bench/drivers/`
