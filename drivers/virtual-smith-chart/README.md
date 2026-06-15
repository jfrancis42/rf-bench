# rf-bench-drivers-virtual-smith-chart

Python driver for **Virtual Smith Chart** SCPI instrument. Displays complex impedance data on a normalized Smith chart for antenna tuning, VNA measurements, and matching network design.

## Installation

```bash
pip install rf-bench-drivers-virtual-smith-chart
```

Or install from source:

```bash
cd drivers/virtual-smith-chart
pip install -e .
```

## Quick Start

```python
from rf_bench.virtual import VirtualSmithChart

# Simple impedance plot
with VirtualSmithChart("10.1.1.52") as chart:
    chart.set_title("Antenna Impedance")
    chart.set_z0(50)  # 50Ω reference
    
    # Plot normalized impedance (Z/Z0 = 0.8 + 0.4j)
    chart.add_point(0.8, 0.4)
    
    # Draw SWR=2.0 circle
    chart.set_swr_circle(2.0)

# VNA sweep with frequency markers
with VirtualSmithChart("10.1.1.52") as chart:
    chart.configure(
        title="20m Dipole S11",
        z0=50,
        trace=1,
        color="#00ff00",
        label="14.0-14.35 MHz"
    )
    
    for freq in range(14_000_000, 14_350_000, 50_000):
        z_complex = measure_impedance(freq)  # Your VNA code
        z_normalized = z_complex / 50.0
        chart.mark_frequency(freq)
        chart.add_point(z_normalized.real, z_normalized.imag)
```

## Backend Server

The driver connects to a virtual Smith chart backend server:

```bash
cd ~/Dropbox/build/rf-bench/virtual/smith-chart/backend
python3 server.py
```

Default ports:
- **SCPI TCP**: 5025 (configure with `--scpi-port`)
- **HTTP/WebSocket**: 8011 (configure with `--http-port`)

Open browser at `http://localhost:8011` to see the live Smith chart.

## API Reference

### Connection

```python
VirtualSmithChart(host, port=5025, timeout=2.0)
```

- **host**: IP address or hostname of backend server
- **port**: SCPI TCP port (default 5025)
- **timeout**: Socket timeout in seconds

### IEEE 488.2 Commands

```python
chart.idn()           # → "N0GQ,Virtual-Smith-Chart,1.0,2026"
chart.reset()         # Reset to defaults, clear all traces
chart.get_error()     # → "0,No error"
```

### Impedance Point Management

```python
# Add impedance point (rectangular, normalized to Z0)
chart.add_point(0.8, 0.4)  # Z/Z0 = 0.8 + 0.4j

# Add impedance point (polar form: magnitude, angle in degrees)
chart.add_point_polar(0.894, 26.57)  # Same as above

# Query most recent point
real, imag = chart.get_point()  # → (0.8, 0.4)

# Add frequency marker (labels next point with frequency)
chart.mark_frequency(14.2e6)  # Next point labeled "14.2 MHz"
chart.add_point(0.8, 0.4)      # This point shows freq label

# Query last frequency marker
freq = chart.get_frequency_marker()  # → 14200000.0
```

### Reference Impedance Configuration

```python
# Set reference impedance (default 50Ω)
chart.set_z0(75)   # 75Ω for some cable systems
chart.set_z0(50)   # Standard 50Ω

# Query reference impedance
z0 = chart.get_z0()  # → 50.0
```

### Trace Management

```python
# Select active trace (1-4)
chart.set_trace(1)  # Switch to trace 1
chart.set_trace(2)  # Switch to trace 2

# Query active trace
trace = chart.get_trace()  # → 1

# Clear active trace
chart.clear_trace()

# Clear all traces
chart.clear_all_traces()

# Configure trace color (hex format)
chart.set_trace_color("#00ff00")  # Green
chart.set_trace_color("#ff0000")  # Red

# Query trace color
color = chart.get_trace_color()  # → "#00ff00"

# Set trace label
chart.set_trace_label("Before Tuning")
chart.set_trace_label("After Tuning")

# Query trace label
label = chart.get_trace_label()  # → "Before Tuning"
```

### SWR Circle

```python
# Draw SWR circle (1.0-10.0)
chart.set_swr_circle(2.0)   # SWR = 2.0 circle
chart.set_swr_circle(1.5)   # SWR = 1.5 circle
chart.set_swr_circle(None)  # Hide SWR circle

# Query SWR circle value
swr = chart.get_swr_circle()  # → 2.0 or None
```

### Display Mode

```python
# Switch between impedance and admittance
chart.set_mode("IMPED")  # Impedance (default)
chart.set_mode("ADMIT")  # Admittance (Y = 1/Z)

# Query mode
mode = chart.get_mode()  # → "IMPED" or "ADMIT"

# Toggle grid
chart.set_grid(True)   # Show grid
chart.set_grid(False)  # Hide grid

# Query grid state
grid = chart.get_grid()  # → True or False

# Set title
chart.set_title("Antenna Tuner Performance")

# Query title
title = chart.get_title()  # → "Antenna Tuner Performance"
```

### Complete Configuration

```python
chart.configure(
    title="20m Dipole S11",
    z0=50,
    trace=1,
    color="#00ff00",
    label="14.0-14.35 MHz",
    mode="IMPED",
    grid=True,
    swr_circle=2.0
)
```

### MQTT Integration

```python
# Configure MQTT broker for live streaming
chart.configure_mqtt("mqtt.n0gq.org", "vna/smith")

# Backend subscribes to topic and expects JSON messages:
# {"z": [0.8, 0.4]}                    # Rectangular
# {"z": [0.894, 26.57], "polar": true} # Polar
# {"z": [0.8, 0.4], "freq": 14200000}  # With frequency

# Query MQTT configuration
config = chart.get_mqtt_config()  # → "mqtt.n0gq.org,vna/smith"
```

## Common Use Cases

### VNA S11 Frequency Sweep (HP 8712B)

```python
from rf_bench.virtual import VirtualSmithChart
from rf_bench.hp import HP8712B

vna = HP8712B("10.1.1.70")
chart = VirtualSmithChart("10.1.1.52")

# Configure VNA for 20m band sweep
vna.set_sweep(start=14e6, stop=14.35e6, points=71)
vna.set_parameter("S11")
vna.calibrate_solt()  # Short-Open-Load-Thru calibration

# Configure Smith chart
chart.configure(
    title="20m Dipole S11 - 50Ω System",
    z0=50,
    trace=1,
    color="#00ff00",
    label="Measured",
    swr_circle=2.0
)

# Fetch and plot sweep data
freqs, s11_mag, s11_phase = vna.get_trace_data()

for freq, mag, phase in zip(freqs, s11_mag, s11_phase):
    # Convert S11 (reflection coefficient) to impedance
    gamma = mag * cmath.exp(1j * math.radians(phase))
    z_norm = (1 + gamma) / (1 - gamma)
    
    chart.mark_frequency(freq)
    chart.add_point(z_norm.real, z_norm.imag)

vna.close()
chart.close()
```

### Antenna Tuner Before/After (Manual Tuning)

```python
from rf_bench.virtual import VirtualSmithChart
from rf_bench.siglent import SSA3000X

ssa = SSA3000X("10.1.1.60")
chart = VirtualSmithChart("10.1.1.52")

# Configure spectrum analyzer with tracking generator
freq = 14.2e6
ssa.set_center_span(freq, 100e3)
ssa.tracking_on()

# Configure Smith chart
chart.set_title("40m Inverted-V Tuning @ 7.2 MHz")
chart.set_z0(50)
chart.set_swr_circle(2.0)

# Measure before tuning (trace 1)
print("Measuring BEFORE tuning...")
chart.set_trace(1)
chart.set_trace_color("#ff0000")
chart.set_trace_label("Before Tuning")

z_before = measure_impedance_ssa(ssa, freq)  # Your measurement code
z_norm_before = z_before / 50.0
chart.add_point(z_norm_before.real, z_norm_before.imag)

input("Adjust tuner, then press Enter...")

# Measure after tuning (trace 2)
print("Measuring AFTER tuning...")
chart.set_trace(2)
chart.set_trace_color("#00ff00")
chart.set_trace_label("After Tuning")

z_after = measure_impedance_ssa(ssa, freq)
z_norm_after = z_after / 50.0
chart.add_point(z_norm_after.real, z_norm_after.imag)

print(f"Before: Z = {z_before:.1f} Ω, SWR = {calculate_swr(z_before, 50):.2f}")
print(f"After:  Z = {z_after:.1f} Ω, SWR = {calculate_swr(z_after, 50):.2f}")

ssa.close()
chart.close()
```

### Matching Network Design Verification

```python
from rf_bench.virtual import VirtualSmithChart
import cmath
import math

chart = VirtualSmithChart("10.1.1.52")

chart.configure(
    title="L-Network Matching (50Ω → 10+j20Ω)",
    z0=50,
    trace=1,
    color="#00ff00",
    label="Transformation Path",
    swr_circle=2.0
)

# Load impedance
z_load = complex(10, 20)  # 10 + j20 Ω
z_load_norm = z_load / 50.0
chart.add_point(z_load_norm.real, z_load_norm.imag)

# Step 1: Series capacitor cancels some reactance
# Xc = -15 Ω (resonates part of +20j)
z_after_c = complex(10, 20 - 15)  # 10 + j5 Ω
z_after_c_norm = z_after_c / 50.0
chart.add_point(z_after_c_norm.real, z_after_c_norm.imag)

# Step 2: Shunt inductor transforms to 50Ω
# XL = 25 Ω brings impedance to ~50Ω
# (Calculate using Smith chart math or network analysis)
z_final = complex(50, 0)  # Target: 50 + j0 Ω
z_final_norm = z_final / 50.0
chart.add_point(z_final_norm.real, z_final_norm.imag)

print("L-Network components:")
print(f"  Series C = {1 / (2 * math.pi * 14.2e6 * 15) * 1e12:.1f} pF")
print(f"  Shunt L  = {25 / (2 * math.pi * 14.2e6) * 1e6:.2f} µH")

chart.close()
```

### ESP32 SCPI Antenna Tuner (Live Tuning)

```python
from rf_bench.virtual import VirtualSmithChart
import socket
import time

# Connect to ESP32 SCPI antenna tuner (scpi-tuner project)
tuner = socket.socket()
tuner.connect(("10.1.0.50", 5025))

chart = VirtualSmithChart("10.1.1.52")

chart.configure(
    title="ESP32 Auto-Tuner - Live Tuning",
    z0=50,
    trace=1,
    color="#ffff00",
    label="Tuning Progress",
    swr_circle=1.5
)

# Start auto-tune
tuner.sendall(b"TUNE:AUTO 14.2e6\n")  # Auto-tune for 14.2 MHz

# Poll tuner status and plot impedance
while True:
    tuner.sendall(b"TUNE:STAT?\n")
    status = tuner.recv(1024).decode().strip()
    
    tuner.sendall(b"TUNE:Z?\n")
    z_str = tuner.recv(1024).decode().strip()
    real, imag = map(float, z_str.split(','))
    
    z_norm = complex(real, imag) / 50.0
    chart.add_point(z_norm.real, z_norm.imag)
    
    if status == "CONVERGED":
        print("Tuning complete!")
        break
    
    time.sleep(0.2)

tuner.sendall(b"TUNE:L?\n")
l_nh = float(tuner.recv(1024).decode())
tuner.sendall(b"TUNE:C?\n")
c_pf = float(tuner.recv(1024).decode())

print(f"Final L = {l_nh:.0f} nH, C = {c_pf:.1f} pF")

tuner.close()
chart.close()
```

### MQTT-Driven Impedance Streaming

```python
from rf_bench.virtual import VirtualSmithChart
import paho.mqtt.publish as publish
import time
import cmath

chart = VirtualSmithChart("10.1.1.52")

chart.configure(
    title="Live VNA Monitor via MQTT",
    z0=50,
    trace=1,
    color="#00ffff",
    label="Real-time S11"
)

# Configure MQTT streaming
chart.configure_mqtt("mqtt.n0gq.org", "vna/smith")

# Remote VNA publishes JSON to MQTT topic:
# Example from remote VNA script:
#
# import paho.mqtt.client as mqtt
# import json
# 
# client = mqtt.Client()
# client.connect("mqtt.n0gq.org", 1883)
# 
# for freq in range(14_000_000, 14_350_000, 50_000):
#     gamma = measure_s11(freq)  # Complex reflection coefficient
#     z_norm = (1 + gamma) / (1 - gamma)
#     
#     msg = json.dumps({
#         "z": [z_norm.real, z_norm.imag],
#         "freq": freq
#     })
#     client.publish("vna/smith", msg)
#     time.sleep(0.1)

print("Chart configured. Remote VNA can publish to MQTT topic: vna/smith")
print("Expected format: {\"z\": [real, imag], \"freq\": 14200000}")
```

### Multi-Band Antenna Comparison

```python
from rf_bench.virtual import VirtualSmithChart
from rf_bench.hp import HP8712B

vna = HP8712B("10.1.1.70")
chart = VirtualSmithChart("10.1.1.52")

chart.set_title("Multi-Band Dipole: 20m, 40m, 80m")
chart.set_z0(50)
chart.set_swr_circle(2.0)

bands = [
    (14.0e6, 14.35e6, 1, "#00ff00", "20m"),
    (7.0e6, 7.3e6, 2, "#ff00ff", "40m"),
    (3.5e6, 4.0e6, 3, "#00ffff", "80m"),
]

for start, stop, trace_id, color, label in bands:
    print(f"Sweeping {label}...")
    
    chart.set_trace(trace_id)
    chart.set_trace_color(color)
    chart.set_trace_label(label)
    
    vna.set_sweep(start=start, stop=stop, points=51)
    freqs, s11_mag, s11_phase = vna.get_trace_data()
    
    for freq, mag, phase in zip(freqs, s11_mag, s11_phase):
        gamma = mag * cmath.exp(1j * math.radians(phase))
        z_norm = (1 + gamma) / (1 - gamma)
        chart.add_point(z_norm.real, z_norm.imag)

vna.close()
chart.close()
```

### Transmission Line Impedance Transformation

```python
from rf_bench.virtual import VirtualSmithChart
import cmath
import math

chart = VirtualSmithChart("10.1.1.52")

chart.configure(
    title="50Ω Coax: Load → λ/4 Transform → λ/2 Transform",
    z0=50,
    trace=1,
    color="#ffff00",
    label="Transformation Path",
    grid=True
)

# Load impedance
z_load = complex(25, 0)  # 25 Ω resistive load
z_load_norm = z_load / 50.0
chart.add_point(z_load_norm.real, z_load_norm.imag)

# λ/4 transmission line transforms impedance by Z0²/ZL
z_after_quarter = 50**2 / z_load  # 100 Ω
z_after_quarter_norm = z_after_quarter / 50.0
chart.add_point(z_after_quarter_norm.real, z_after_quarter_norm.imag)

# λ/2 transmission line repeats impedance (no transformation)
z_after_half = z_after_quarter  # Still 100 Ω
z_after_half_norm = z_after_half / 50.0
chart.add_point(z_after_half_norm.real, z_after_half_norm.imag)

# Another λ/4 back to original
z_final = 50**2 / z_after_half  # 25 Ω
z_final_norm = z_final / 50.0
chart.add_point(z_final_norm.real, z_final_norm.imag)

print("Impedance transformation:")
print(f"  Load:          {z_load:.0f} Ω")
print(f"  After λ/4:     {z_after_quarter:.0f} Ω")
print(f"  After λ/2:     {z_after_half:.0f} Ω (unchanged)")
print(f"  After 2nd λ/4: {z_final:.0f} Ω (back to load)")

chart.close()
```

### HF Propagation: Antenna Impedance vs Time

```python
from rf_bench.virtual import VirtualSmithChart
from rf_bench.icom import IC7300
import time

radio = IC7300()
chart = VirtualSmithChart("10.1.1.52")

# Monitor how antenna impedance changes over time
# (Due to ionospheric conditions, weather, nearby objects)
chart.configure(
    title="20m Dipole Impedance: Sunrise Monitor",
    z0=50,
    trace=1,
    color="#ff8800",
    label="Time-lapse",
    swr_circle=2.0
)

radio.set_frequency(14_200_000)
radio.set_mode("USB")

# Measure impedance every 10 minutes for 2 hours
for minute in range(0, 121, 10):
    # Use external measurement device (antenna analyzer, VNA, etc.)
    z = measure_antenna_impedance(14.2e6)  # Your code
    z_norm = z / 50.0
    
    # Add timestamp as frequency marker (store minute count as kHz)
    chart.mark_frequency(minute * 1000)  # e.g. 60000 Hz = "60 min"
    chart.add_point(z_norm.real, z_norm.imag)
    
    swr = calculate_swr(z, 50)
    print(f"{minute:3d} min: Z = {abs(z):.1f} Ω ∠{math.degrees(cmath.phase(z)):.1f}°, SWR = {swr:.2f}")
    
    if minute < 120:
        time.sleep(600)  # 10 minutes

radio.close()
chart.close()
```

### Balun Performance Verification

```python
from rf_bench.virtual import VirtualSmithChart
from rf_bench.hp import HP8712B

vna = HP8712B("10.1.1.70")
chart = VirtualSmithChart("10.1.1.52")

chart.set_title("1:1 Balun: Balanced Port Impedance")
chart.set_z0(50)
chart.set_swr_circle(1.5)

# Sweep frequency and measure balanced port
vna.set_sweep(start=1e6, stop=30e6, points=291)  # 1-30 MHz, 100 kHz steps
vna.set_parameter("S11")

freqs, s11_mag, s11_phase = vna.get_trace_data()

chart.set_trace(1)
chart.set_trace_color("#00ff00")
chart.set_trace_label("1-30 MHz Sweep")

for freq, mag, phase in zip(freqs, s11_mag, s11_phase):
    gamma = mag * cmath.exp(1j * math.radians(phase))
    z_norm = (1 + gamma) / (1 - gamma)
    
    # Mark every 5 MHz
    if freq % 5e6 < 100e3:
        chart.mark_frequency(freq)
    
    chart.add_point(z_norm.real, z_norm.imag)

vna.close()
chart.close()
```

### Crystal/Resonator Impedance

```python
from rf_bench.virtual import VirtualSmithChart
from rf_bench.siglent import SSA3000X

ssa = SSA3000X("10.1.1.60")
chart = VirtualSmithChart("10.1.1.52")

# Measure crystal impedance near resonance
center = 10e6  # 10 MHz crystal
span = 20e3    # ±10 kHz

chart.configure(
    title="10 MHz Crystal Resonance",
    z0=50,
    trace=1,
    color="#ff00ff",
    label="9.99-10.01 MHz",
    swr_circle=3.0
)

ssa.set_center_span(center, span)
ssa.tracking_on()

# Sweep around resonance
for freq in range(int(center - span/2), int(center + span/2), 100):
    z = measure_impedance_ssa(ssa, freq)  # Your code
    z_norm = z / 50.0
    
    if freq % 1000 == 0:
        chart.mark_frequency(freq)
    
    chart.add_point(z_norm.real, z_norm.imag)

ssa.close()
chart.close()
```

## SCPI Command Reference

### IEEE 488.2 Common Commands
- `*IDN?` — Identification query
- `*RST` — Reset to defaults, clear all traces
- `SYST:ERR?` — Query error queue

### Impedance Point Commands
- `SMIT:POIN <real>,<imag>` — Add point (rectangular, normalized)
- `SMIT:POIN?` — Query most recent point
- `SMIT:POIN:POL <mag>,<angle_deg>` — Add point (polar form)

### Reference Impedance Commands
- `SMIT:Z0 <ohms>` — Set reference impedance
- `SMIT:Z0?` — Query reference impedance

### Trace Commands
- `SMIT:TRAC <1-4>` — Select active trace
- `SMIT:TRAC?` — Query active trace
- `SMIT:TRAC:CLE` — Clear active trace
- `SMIT:TRAC:ALL:CLE` — Clear all traces
- `SMIT:TRAC:COL <color>` — Set trace color (hex "#RRGGBB")
- `SMIT:TRAC:COL?` — Query trace color
- `SMIT:TRAC:LAB <string>` — Set trace label
- `SMIT:TRAC:LAB?` — Query trace label

### Marker Commands
- `SMIT:MARK:FREQ <Hz>` — Add frequency marker to next point
- `SMIT:MARK:FREQ?` — Query last frequency marker

### SWR Circle Commands
- `SMIT:SWR <ratio>` — Draw SWR circle (1.0-10.0)
- `SMIT:SWR?` — Query SWR circle value

### Display Mode Commands
- `SMIT:MODE <IMPED|ADMIT>` — Switch impedance/admittance
- `SMIT:MODE?` — Query mode
- `SMIT:GRID <ON|OFF>` — Show/hide grid
- `SMIT:GRID?` — Query grid state
- `CONF:TITLE <string>` — Set chart title
- `CONF:TITLE?` — Query title

### MQTT Commands
- `MQTT:CONF <host>,<topic>` — Configure MQTT broker and topic
- `MQTT:CONF?` — Query MQTT configuration

### Direct SCPI Example

```bash
# Using netcat
echo "*IDN?" | nc localhost 5025
echo "SMIT:Z0 50" | nc localhost 5025
echo "CONF:TITLE Antenna Tuning" | nc localhost 5025
echo "SMIT:TRAC 1" | nc localhost 5025
echo "SMIT:TRAC:COL #00ff00" | nc localhost 5025
echo "SMIT:TRAC:LAB Before Tuning" | nc localhost 5025
echo "SMIT:SWR 2.0" | nc localhost 5025
echo "SMIT:POIN 0.8,0.4" | nc localhost 5025
echo "SMIT:MARK:FREQ 14.2e6" | nc localhost 5025
```

## Smith Chart Display

The virtual Smith chart shows:
- **Constant resistance circles**: Horizontal lines at chart center = real axis
- **Constant reactance arcs**: Upper half = inductive (+jX), lower = capacitive (-jX)
- **Center point**: Normalized Z = 1 + j0 (perfect 50Ω match)
- **Outer circle**: |Γ| = 1 (total reflection)
- **SWR circles**: Circles centered at origin, radius determined by SWR
- **Trace colors**: Up to 4 independent traces with configurable colors
- **Frequency markers**: Points labeled with frequency in MHz
- **Grid**: Constant R/X grid lines (toggleable)

## Error Handling

```python
from rf_bench.virtual import VirtualSmithChart, VirtualSmithChartError

try:
    chart = VirtualSmithChart("10.1.1.99")  # Wrong IP
except VirtualSmithChartError as e:
    print(f"Connection failed: {e}")

try:
    chart.set_z0(-10)  # Invalid Z0
except ValueError as e:
    print(f"Invalid parameter: {e}")

# Check instrument error queue
error = chart.get_error()
if not error.startswith("0,"):
    print(f"Instrument error: {error}")
```

## Requirements

- Python 3.7+
- No external dependencies (uses stdlib `socket`)

## Backend Server Requirements

The backend server requires:
- Python 3.7+
- FastAPI (`pip install fastapi`)
- uvicorn (`pip install uvicorn`)
- websockets (`pip install websockets`)
- paho-mqtt (`pip install paho-mqtt`)

## License

GPL-3.0-or-later

Copyright (C) 2026 Jeff Francis (N0GQ) <gjfrancis@protonmail.com>

This program is free software: you can redistribute it and/or modify
it under the terms of the GNU General Public License as published by
the Free Software Foundation, either version 3 of the License, or
(at your option) any later version.

This program is distributed in the hope that it will be useful,
but WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
GNU General Public License for more details.

You should have received a copy of the GNU General Public License
along with this program. If not, see <https://www.gnu.org/licenses/>.

## See Also

- Backend server: `~/Dropbox/build/rf-bench/virtual/smith-chart/`
- BenchView panel manager: `~/Dropbox/build/rf-bench/virtual/benchview/`
- Other virtual instruments: `~/Dropbox/build/rf-bench/virtual/`
- RF Bench drivers: `~/Dropbox/build/rf-bench/drivers/`
- HP 8712B VNA driver: `rf-bench-drivers-hp`
- Siglent SSA driver: `rf-bench-drivers-siglent`
