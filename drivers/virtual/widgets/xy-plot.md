# Xy Plot — part of `rf-bench-drivers-virtual`
Python driver for **Virtual XY Plot** SCPI instrument. Displays scatter or line plots with configurable axes, point styling, and grid.

## Installation

```bash
pip install rf-bench-drivers-virtual
```

Or install from source:

```bash
cd drivers/virtual-xy-plot
pip install -e .
```

## Quick Start

```python
from rf_bench.virtual import VirtualXYPlot

# Simple scatter plot
with VirtualXYPlot("10.1.1.52") as plot:
    plot.set_title("Measurement Results")
    plot.set_labels("Frequency (MHz)", "Gain (dB)")
    plot.add_point(14.2, 6.5)
    plot.add_point(21.0, 8.2)
    plot.add_point(28.5, 7.1)

# Line plot with configured ranges
with VirtualXYPlot("10.1.1.52") as plot:
    plot.configure(
        title="Antenna Pattern",
        x_label="Azimuth (deg)",
        y_label="Gain (dBi)",
        style="LINE",
        color="#00ff00",
        x_min=0,
        x_max=360,
        y_min=-20,
        y_max=10
    )

    for angle in range(0, 361, 10):
        gain = compute_gain(angle)
        plot.add_point(angle, gain)
```

## Backend Server

The driver connects to a virtual XY plot backend server:

```bash
cd ~/Dropbox/build/rf-bench/virtual/xy-plot/backend
python3 server.py
```

Default ports:
- **SCPI TCP**: 5005 (configure with `--scpi-port`)
- **HTTP/WebSocket**: 8005 (configure with `--http-port`)

Open browser at `http://localhost:8005` to see the live plot.

## API Reference

### Connection

```python
VirtualXYPlot(host, port=5025, timeout=2.0)
```

- **host**: IP address or hostname of backend server
- **port**: SCPI TCP port (default 5025)
- **timeout**: Socket timeout in seconds

### IEEE 488.2 Commands

```python
plot.idn()           # → "N0GQ,Virtual-XY-Plot,1.0,2026"
plot.reset()         # Reset to defaults, clear all data
plot.get_error()     # → "0,No error"
```

### Data Point Management

```python
# Add single point
plot.add_point(50, 25.3)

# Add multiple points
points = [(10, 5.2), (20, 7.8), (30, 9.1)]
plot.add_points(points)

# Query point count
count = plot.get_point_count()  # → 3

# Clear all data
plot.clear()
```

### Axis Range Configuration

```python
# Individual axis settings
plot.set_x_min(0)
plot.set_x_max(100)
plot.set_y_min(-50)
plot.set_y_max(50)

# Query axis ranges
x_min = plot.get_x_min()  # → 0.0 or "AUTO"
x_max = plot.get_x_max()  # → 100.0 or "AUTO"

# Set all ranges at once
plot.set_ranges(x_min=0, x_max=360, y_min=-20, y_max=10)

# Auto-ranging (default)
plot.set_ranges()  # All axes auto-scale to data
```

### Label Configuration

```python
# Individual labels
plot.set_x_label("Frequency (MHz)")
plot.set_y_label("Gain (dB)")
plot.set_title("Amplifier Response")

# Query labels
x_label = plot.get_x_label()  # → "Frequency (MHz)"
title = plot.get_title()      # → "Amplifier Response"

# Set both axis labels
plot.set_labels("Resistance", "Reactance")
```

### Style Configuration

```python
# Plot style (SCATTER or LINE)
plot.set_style("SCATTER")  # Default
plot.set_style("LINE")     # Connect points with lines

# Query style
style = plot.get_style()  # → "SCATTER" or "LINE"

# Point/line color (hex format)
plot.set_color("#00ff00")  # Green
plot.set_color("#ff0000")  # Red
plot.set_color("#0f0")     # Short form also works

# Query color
color = plot.get_color()  # → "#00ff00"
```

### Complete Configuration

```python
plot.configure(
    title="Filter Response",
    x_label="Frequency (MHz)",
    y_label="Attenuation (dB)",
    style="LINE",
    color="#00ff00",
    x_min=1,
    x_max=30,
    y_min=-60,
    y_max=0
)
```

### MQTT Integration

```python
# Configure MQTT broker for live streaming
plot.configure_mqtt("mqtt.n0gq.org", "sensors/lab/temperature")

# Backend subscribes to topic and expects CSV messages: "x,y"
# Example MQTT messages:
#   "1.5,25.3"
#   "2.0,26.1"
#   "2.5,25.8"

# Query MQTT configuration
config = plot.get_mqtt_config()  # → "mqtt.n0gq.org,sensors/lab/temperature"
```

## Common Use Cases

### Smith Chart (S11 impedance plot)

```python
from rf_bench.virtual import VirtualXYPlot
from rf_bench.siglent import SSA3000X

ssa = SSA3000X("10.1.1.60")
plot = VirtualXYPlot("10.1.1.52")

# Configure as Smith chart
plot.configure_smith_chart("50Ω Impedance Match")

# Sweep frequency and measure S11
ssa.set_center_span(14.2e6, 2e6)
ssa.tracking_on()

for freq in range(13_200_000, 15_200_000, 50_000):
    ssa.set_tracking_freq(freq)
    s11_real, s11_imag = measure_s11_complex(ssa, freq)
    plot.add_point(s11_real, s11_imag)

ssa.close()
plot.close()
```

### Antenna Radiation Pattern

```python
from rf_bench.virtual import VirtualXYPlot
from rf_bench.icom import IC7300
import time

radio = IC7300()
plot = VirtualXYPlot("10.1.1.52")

plot.configure(
    title="2m Yagi Pattern @ 146.52 MHz",
    x_label="Azimuth (degrees)",
    y_label="Signal Strength (S-units)",
    style="LINE",
    color="#00ff00",
    x_min=0,
    x_max=360,
    y_min=0,
    y_max=9
)

radio.set_frequency(146_520_000)
radio.set_mode("FM")

# Rotate antenna, measure signal at each angle
for angle in range(0, 361, 5):
    set_rotator_position(angle)  # External rotator control
    time.sleep(1)  # Settle time
    signal = radio.get_strength_settled()
    plot.add_point(angle, signal)

radio.close()
plot.close()
```

### Filter Frequency Response

```python
from rf_bench.virtual import VirtualXYPlot
from rf_bench.siglent import SDG1000X, SSA3000X
import numpy as np

gen = SDG1000X("10.1.1.55")
ssa = SSA3000X("10.1.1.60")
plot = VirtualXYPlot("10.1.1.52")

plot.configure(
    title="Low-Pass Filter Response",
    x_label="Frequency (MHz)",
    y_label="Attenuation (dB)",
    style="LINE",
    color="#00ff00",
    x_min=1,
    x_max=30,
    y_min=-60,
    y_max=0
)

gen.set_amplitude(1, 1.0)  # 1V RMS input
gen.enable(1)

freqs = np.logspace(6, 7.5, 50)  # 1 MHz to 31.6 MHz, 50 points

for freq in freqs:
    gen.set_frequency(1, freq)
    ssa.set_center_span(freq, 100e3)
    ssa.peak_search()
    _, power_dbm = ssa.get_peak()
    
    # Reference: 1V RMS = +13 dBm into 50Ω
    attenuation = 13 - power_dbm
    plot.add_point(freq / 1e6, -attenuation)

gen.close()
ssa.close()
plot.close()
```

### Polar Plot (Antenna Beamwidth)

```python
from rf_bench.virtual import VirtualXYPlot
import math

plot = VirtualXYPlot("10.1.1.52")
plot.configure_polar("2m Yagi Polar Pattern", r_max=10)

# Sample antenna gain at various angles
for angle in range(0, 360, 10):
    gain_dbi = measure_antenna_gain(angle)  # External measurement
    
    # Normalize to 0-10 scale for polar plot
    normalized_gain = (gain_dbi + 20) / 3  # -20 to 10 dBi → 0 to 10
    
    plot.add_polar_point(angle, normalized_gain)

plot.close()
```

### S-Parameter Sweep (S21 gain/loss)

```python
from rf_bench.virtual import VirtualXYPlot
from rf_bench.hp import HP8712B  # VNA (future, hardware pending)

vna = HP8712B("10.1.1.70")
plot = VirtualXYPlot("10.1.1.52")

plot.configure(
    title="Amplifier S21 Gain",
    x_label="Frequency (MHz)",
    y_label="Gain (dB)",
    style="LINE",
    color="#00ff00",
    x_min=1,
    x_max=1000,
    y_min=-10,
    y_max=30
)

vna.set_sweep(start=1e6, stop=1000e6, points=201)
vna.set_parameter("S21")

freqs, s21_mag, _ = vna.get_trace_data()

for freq, gain_db in zip(freqs, s21_mag):
    plot.add_point(freq / 1e6, gain_db)

vna.close()
plot.close()
```

### I-V Curve (Diode characterization)

```python
from rf_bench.virtual import VirtualXYPlot
from rf_bench.siglent import SPD3303X, SDM3000X
import time

psu = SPD3303X("10.1.1.56")
dmm = SDM3000X("10.1.1.63")
plot = VirtualXYPlot("10.1.1.52")

plot.configure(
    title="1N4148 Diode I-V Curve",
    x_label="Voltage (V)",
    y_label="Current (mA)",
    style="LINE",
    color="#ff0000",
    x_min=0,
    x_max=1.0,
    y_min=0,
    y_max=50
)

psu.set_current(1, 0.1)  # 100 mA current limit
psu.enable(1)

for voltage in [v/100 for v in range(0, 101, 5)]:  # 0 to 1V, 0.05V steps
    psu.set_voltage(1, voltage)
    time.sleep(0.1)  # Settle
    
    current = dmm.measure_current_dc() * 1000  # Convert A to mA
    plot.add_point(voltage, current)

psu.disable(1)
psu.close()
dmm.close()
plot.close()
```

### Lissajous Pattern (Oscilloscope XY mode)

```python
from rf_bench.virtual import VirtualXYPlot
from rf_bench.siglent import SDG1000X, SDS2000X
import time

gen = SDG1000X("10.1.1.55")
scope = SDS2000X("10.1.1.58")
plot = VirtualXYPlot("10.1.1.52")

# Generate two sine waves with 2:3 frequency ratio
gen.set_waveform(1, "SINE")
gen.set_frequency(1, 1000)
gen.set_amplitude(1, 1.0)
gen.enable(1)

gen.set_waveform(2, "SINE")
gen.set_frequency(2, 1500)  # 3:2 ratio
gen.set_amplitude(2, 1.0)
gen.enable(2)

plot.configure(
    title="Lissajous Pattern (1kHz : 1.5kHz)",
    x_label="Channel 1 (V)",
    y_label="Channel 2 (V)",
    style="LINE",
    color="#00ff00",
    x_min=-1.5,
    x_max=1.5,
    y_min=-1.5,
    y_max=1.5
)

# Capture waveform data
scope.set_timebase(0.001)  # 1ms/div
scope.auto_setup()
ch1_data = scope.get_waveform_data(1)
ch2_data = scope.get_waveform_data(2)

# Plot X vs Y
for x, y in zip(ch1_data, ch2_data):
    plot.add_point(x, y)

gen.close()
scope.close()
plot.close()
```

### Live MQTT Streaming (Temperature vs Time)

```python
from rf_bench.virtual import VirtualXYPlot
import paho.mqtt.publish as publish
import time

plot = VirtualXYPlot("10.1.1.52")

plot.configure(
    title="Lab Temperature Monitor",
    x_label="Time (minutes)",
    y_label="Temperature (°C)",
    style="LINE",
    color="#ff8800",
    x_min=0,
    x_max=60,
    y_min=20,
    y_max=30
)

# Configure MQTT streaming
plot.configure_mqtt("mqtt.n0gq.org", "lab/temperature")

# External sensor publishes CSV to MQTT topic:
#   mosquitto_pub -h mqtt.n0gq.org -t lab/temperature -m "0.5,25.3"
#   mosquitto_pub -h mqtt.n0gq.org -t lab/temperature -m "1.0,25.5"
#   mosquitto_pub -h mqtt.n0gq.org -t lab/temperature -m "1.5,25.2"

# The backend server subscribes and plots automatically
# No polling needed from this script

print("Plot configured. Publish CSV to MQTT topic: lab/temperature")
print("Format: \"time_minutes,temperature_celsius\"")
```

## Mathematical Function Plotting

```python
from rf_bench.virtual import VirtualXYPlot
import numpy as np

plot = VirtualXYPlot("10.1.1.52")

# Sine wave
plot.configure(
    title="Sine Wave",
    x_label="X",
    y_label="Y",
    style="LINE",
    color="#00ff00"
)

plot.plot_function(lambda x: np.sin(x), 0, 2*np.pi, num_points=100)

# Or manually
plot.clear()
for x in np.linspace(0, 2*np.pi, 100):
    plot.add_point(x, np.sin(x))

plot.close()
```

## SCPI Command Reference

### IEEE 488.2 Common Commands
- `*IDN?` — Identification query
- `*RST` — Reset to defaults, clear data
- `SYST:ERR?` — Query error queue

### Data Point Commands
- `MEAS:XY <x>,<y>` — Add XY data point
- `MEAS:XY?` — Query number of points
- `MEAS:CLEAR` — Clear all data points

### Axis Range Commands
- `CONF:XMIN <float>` — Set X-axis minimum
- `CONF:XMIN?` — Query X-axis minimum
- `CONF:XMAX <float>` — Set X-axis maximum
- `CONF:XMAX?` — Query X-axis maximum
- `CONF:YMIN <float>` — Set Y-axis minimum
- `CONF:YMIN?` — Query Y-axis minimum
- `CONF:YMAX <float>` — Set Y-axis maximum
- `CONF:YMAX?` — Query Y-axis maximum

### Label Commands
- `CONF:XLABEL <string>` — Set X-axis label
- `CONF:XLABEL?` — Query X-axis label
- `CONF:YLABEL <string>` — Set Y-axis label
- `CONF:YLABEL?` — Query Y-axis label
- `CONF:TITLE <string>` — Set plot title
- `CONF:TITLE?` — Query plot title

### Style Commands
- `CONF:STYLE <SCATTER|LINE>` — Set plot style
- `CONF:STYLE?` — Query plot style
- `CONF:COL <color>` — Set point/line color (hex: "#RRGGBB" or "#RGB")
- `CONF:COL?` — Query color

### MQTT Commands
- `MQTT:CONF <host>,<topic>` — Configure MQTT broker and topic (expects "x,y" messages)
- `MQTT:CONF?` — Query MQTT configuration

### Direct SCPI Example

```bash
# Using netcat
echo "*IDN?" | nc localhost 5005
echo "CONF:TITLE Smith Chart" | nc localhost 5005
echo "CONF:XLABEL Resistance" | nc localhost 5005
echo "CONF:YLABEL Reactance" | nc localhost 5005
echo "CONF:STYLE SCATTER" | nc localhost 5005
echo "CONF:COL #00ff00" | nc localhost 5005
echo "MEAS:XY 50,0" | nc localhost 5005
echo "MEAS:XY 75,25" | nc localhost 5005
echo "MEAS:XY 100,50" | nc localhost 5005
```

## Plot Display

The virtual XY plot displays:
- **Canvas**: HTML5 Canvas with grid lines
- **Axes**: Auto-scaling or fixed range with tick marks
- **Points**: Scatter (circles) or line (connected path)
- **Labels**: Axis labels on borders, title at top
- **Grid**: Optional major/minor grid lines
- **Legend**: Color-coded with style indicator

## Error Handling

```python
from rf_bench.virtual import VirtualXYPlot, VirtualXYPlotError

try:
    plot = VirtualXYPlot("10.1.1.99")  # Wrong IP
except VirtualXYPlotError as e:
    print(f"Connection failed: {e}")

try:
    plot.set_style("INVALID")  # Invalid style
except ValueError as e:
    print(f"Invalid parameter: {e}")

# Check instrument error queue
error = plot.get_error()
if not error.startswith("0,"):
    print(f"Instrument error: {error}")
```

## Requirements

- Python 3.7+
- NumPy (optional, for `plot_function()` and mathematical examples)
- paho-mqtt (optional, for MQTT integration on backend)

## License

GPL-3.0-or-later — see LICENSE file in package root.

## See Also

- Backend server: `~/Dropbox/build/rf-bench/virtual/xy-plot/`
- BenchView panel manager: `~/Dropbox/build/rf-bench/virtual/benchview/`
- Other virtual instruments: `~/Dropbox/build/rf-bench/virtual/`
- RF Bench drivers: `~/Dropbox/build/rf-bench/drivers/`
