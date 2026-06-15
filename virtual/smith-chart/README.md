># Virtual Smith Chart

Complex impedance visualization for RF/microwave antenna tuning, VNA measurements, and matching network design. Plots normalized impedance on Smith chart polar grid with constant resistance circles and reactance arcs.

## Features

- **Smith Chart Grid** — Constant resistance circles (0.2, 0.5, 1, 2, 5 Ω) and reactance arcs (±0.2j, ±0.5j, ±1j, ±2j, ±5j)
- **Multiple Traces** — 4 independent traces with customizable colors and labels
- **Reference Impedance** — Configurable Z₀ (default 50 Ω) for normalization
- **SWR Circles** — Overlay constant SWR contours (1.0-10.0)
- **Frequency Markers** — Label impedance points with frequency
- **Impedance/Admittance** — Toggle between impedance and admittance views
- **MQTT Integration** — Subscribe to real-time impedance data streams
- **BenchView Compatible** — Works with multi-instrument panel manager

## Quick Start

### Standalone Mode

```bash
cd backend
python3 server.py --scpi-port 5025 --http-port 8011

# Open browser
http://localhost:8011
```

### SCPI Control

```bash
# Set reference impedance
echo "SMIT:Z0 75" | nc localhost 5025

# Select trace 1 (green)
echo "SMIT:TRAC 1" | nc localhost 5025

# Add impedance point (normalized: 0.8+0.5j)
echo "SMIT:POIN 0.8,0.5" | nc localhost 5025

# Label with frequency
echo "SMIT:MARK:FREQ 14.2e6" | nc localhost 5025
echo "SMIT:POIN 0.8,0.5" | nc localhost 5025

# Draw SWR=2.0 circle
echo "SMIT:SWR 2.0" | nc localhost 5025

# Clear trace
echo "SMIT:TRAC:CLE" | nc localhost 5025
```

## SCPI Command Reference

### IEEE 488.2 Common Commands

- `*IDN?` — Identification query → "N0GQ,Virtual-Smith-Chart,1.0,2026"
- `*RST` — Reset to defaults
- `SYST:ERR?` — Query error queue

### Impedance Point Commands

- `SMIT:POIN <real>,<imag>` — Add impedance point (rectangular, normalized)
- `SMIT:POIN?` — Query most recent point
- `SMIT:POIN:POL <mag>,<angle>` — Add point (polar: magnitude, angle degrees)

Examples:
```bash
# Rectangular: Z = 0.5 + 0.3j (25 + 15j Ω @ Z₀=50)
echo "SMIT:POIN 0.5,0.3" | nc localhost 5025

# Polar: Z = 1.0∠45° (50∠45° Ω @ Z₀=50)
echo "SMIT:POIN:POL 1.0,45" | nc localhost 5025
```

### Configuration Commands

- `SMIT:Z0 <ohms>` — Set reference impedance (default 50 Ω)
- `SMIT:Z0?` — Query reference impedance
- `SMIT:TRAC <1-4>` — Select active trace
- `SMIT:TRAC?` — Query active trace
- `SMIT:TRAC:CLE` — Clear active trace
- `SMIT:TRAC:ALL:CLE` — Clear all traces
- `SMIT:TRAC:COL <color>` — Set active trace color (hex: #rrggbb)
- `SMIT:TRAC:COL?` — Query active trace color
- `SMIT:TRAC:LAB <string>` — Set active trace label
- `SMIT:TRAC:LAB?` — Query active trace label

### Marker and Display Commands

- `SMIT:MARK:FREQ <Hz>` — Stage frequency marker for next point
- `SMIT:MARK:FREQ?` — Query last frequency marker
- `SMIT:SWR <ratio>` — Draw SWR circle (1.0-10.0)
- `SMIT:SWR?` — Query SWR circle value
- `SMIT:MODE <IMPED|ADMIT>` — Switch impedance/admittance view
- `SMIT:MODE?` — Query current mode
- `SMIT:GRID <ON|OFF>` — Show/hide grid
- `SMIT:GRID?` — Query grid state
- `CONF:TITLE <string>` — Set chart title
- `CONF:TITLE?` — Query chart title

### MQTT Commands

- `MQTT:CONF <host>,<topic>` — Configure MQTT broker and topic to subscribe
- `MQTT:CONF?` — Query MQTT configuration

## Python Driver

Install:
```bash
cd ~/Dropbox/build/rf-bench/drivers/virtual-smith-chart
pip install -e .
```

Basic usage:
```python
from rf_bench.virtual import VirtualSmithChart

with VirtualSmithChart("localhost") as chart:
    # Configure
    chart.set_z0(50)
    chart.set_trace(1)
    chart.set_trace_label(1, "Antenna")
    chart.set_trace_color(1, "#00ff00")
    
    # Add impedance points
    chart.add_point(0.8, 0.5)      # Z = 40+25j Ω
    chart.add_point_polar(1.2, 30) # Z = 60∠30° Ω
    
    # Frequency sweep
    for freq_mhz in range(14, 15):
        z_real, z_imag = measure_antenna(freq_mhz)
        chart.add_point_with_freq(z_real/50, z_imag/50, freq_mhz * 1e6)
    
    # Draw SWR circle
    chart.set_swr(2.0)
```

Full API in driver README: `drivers/virtual-smith-chart/README.md`

## Integration Examples

### 1. HP 8712B VNA S11 Sweep

Plot reflection coefficient across frequency sweep:

```python
from rf_bench.hp import HP8712B
from rf_bench.virtual import VirtualSmithChart
import time

vna = HP8712B("10.1.1.70", gpib_address=16)
chart = VirtualSmithChart("localhost")

# Configure VNA for S11 sweep
vna.set_parameter("S11")
vna.set_frequency_range(10e6, 30e6)
vna.set_points(201)

# Configure chart
chart.set_z0(50)
chart.set_trace(1)
chart.set_trace_label(1, "Antenna S11")
chart.set_title("10-30 MHz Antenna Return Loss")

# Perform sweep
vna.trigger_sweep()
time.sleep(2)

freq, s11 = vna.get_trace_data()  # Returns complex S11 values

# Plot on Smith chart (S11 is already Γ, convert to Z)
chart.clear_trace(1)
for i, (f, gamma) in enumerate(zip(freq, s11)):
    # Convert reflection coefficient to normalized impedance
    z_norm = (1 + gamma) / (1 - gamma)
    
    # Plot every 10th point with frequency label
    if i % 10 == 0:
        chart.add_point_with_freq(z_norm.real, z_norm.imag, f)
    else:
        chart.add_point(z_norm.real, z_norm.imag)
```

### 2. Antenna Tuner Panel

Real-time impedance display during tuning:

```python
from rf_bench.siglent import SSA3000X, SDG1000X
from rf_bench.virtual import VirtualSmithChart, VirtualAnalogMeter
import numpy as np
import time

ssa = SSA3000X("10.1.1.60")
sdg = SDG1000X("10.1.1.55")
chart = VirtualSmithChart("localhost", port=5025)
swr_meter = VirtualAnalogMeter("localhost", port=5026)

# Configure tracking generator
ssa.tracking_generator(True, level=-10)
ssa.set_center_span(14.2e6, 100e3)

# Configure SWR meter
swr_meter.configure(1, "SWR", "", 1, 3)

# Configure chart
chart.set_z0(50)
chart.set_trace(1)
chart.set_swr(2.0)

while True:
    # Measure return loss
    ssa.peak_search()
    freq, power_dbm = ssa.get_peak()
    
    # Convert dBm return loss to reflection coefficient
    return_loss_db = abs(power_dbm)
    gamma_mag = 10 ** (-return_loss_db / 20)
    
    # Assume phase = 0 for simplicity (need VNA for true phase)
    gamma = complex(gamma_mag, 0)
    z_norm = (1 + gamma) / (1 - gamma)
    
    # Calculate SWR
    swr = (1 + gamma_mag) / (1 - gamma_mag)
    
    # Update displays
    chart.add_point(z_norm.real, z_norm.imag)
    swr_meter.set_value(1, swr)
    
    time.sleep(0.5)
```

### 3. Matching Network Design

Interactive L-network design tool:

```python
from rf_bench.virtual import VirtualSmithChart
import numpy as np

chart = VirtualSmithChart("localhost")

# Source and load impedances
z_source = 50 + 0j
z_load = 25 + 15j  # Antenna impedance

# Normalize to 50 Ω
z_load_norm = z_load / 50

# Configure chart
chart.set_z0(50)
chart.set_title("L-Network Matching: 50Ω → 25+15jΩ")

# Trace 1: Load impedance
chart.set_trace(1)
chart.set_trace_label(1, "Load (unmapped)")
chart.set_trace_color(1, "#ff0000")
chart.add_point(z_load_norm.real, z_load_norm.imag)

# Trace 2: Series reactance transformation
chart.set_trace(2)
chart.set_trace_label(2, "After series X")
chart.set_trace_color(2, "#ffff00")

# Try series inductor to move to constant R circle
for l_nh in np.linspace(0, 500, 20):
    xl = 2 * np.pi * 14.2e6 * l_nh * 1e-9  # Inductive reactance @ 14.2 MHz
    z_transformed = z_load + 1j * xl
    z_norm = z_transformed / 50
    chart.add_point(z_norm.real, z_norm.imag)

# Trace 3: Parallel reactance to match
chart.set_trace(3)
chart.set_trace_label(3, "After shunt C")
chart.set_trace_color(3, "#00ff00")

# (Continue transformation to 50+0j...)
```

### 4. ESP32 SCPI Antenna Tuner

Automatic tuner with live Smith chart:

```python
from rf_bench.virtual import VirtualSmithChart
import socket

# Connect to ESP32 SCPI tuner
tuner = socket.socket()
tuner.connect(('192.168.1.42', 5025))

chart = VirtualSmithChart("localhost")
chart.set_z0(50)
chart.set_trace(1)
chart.set_title("Auto-Tuner Search")

# Query tuner position
tuner.sendall(b'TUNE:L?\n')
l_pos = int(tuner.recv(1024).decode().strip())

tuner.sendall(b'TUNE:C?\n')
c_pos = int(tuner.recv(1024).decode().strip())

# Sweep L and C, plot impedance locus
for l in range(0, 100, 5):
    tuner.sendall(f'TUNE:L {l}\n'.encode())
    time.sleep(0.1)
    
    # Read SWR sensor
    tuner.sendall(b'MEAS:SWR?\n')
    swr = float(tuner.recv(1024).decode().strip())
    
    # Convert SWR to gamma magnitude (phase unknown)
    gamma_mag = (swr - 1) / (swr + 1)
    
    # Plot (assuming phase=0 for magnitude-only sensor)
    gamma = complex(gamma_mag, 0)
    z_norm = (1 + gamma) / (1 - gamma)
    chart.add_point(z_norm.real, z_norm.imag)
```

### 5. MQTT Real-Time Impedance Stream

Publish impedance data from VNA to MQTT, display on chart:

```python
# Publisher side (VNA)
from rf_bench.hp import HP8712B
import paho.mqtt.client as mqtt
import json
import time

vna = HP8712B("10.1.1.70", gpib_address=16)
client = mqtt.Client()
client.connect("10.1.0.20", 1883)

vna.set_frequency_range(14e6, 15e6)
vna.set_points(51)

while True:
    vna.trigger_sweep()
    time.sleep(1)
    
    freq, s11 = vna.get_trace_data()
    
    for f, gamma in zip(freq, s11):
        z_norm = (1 + gamma) / (1 - gamma)
        
        msg = json.dumps({
            'z': [z_norm.real, z_norm.imag],
            'freq': f
        })
        client.publish('bench/vna/impedance', msg)
        time.sleep(0.05)

# Smith chart subscribes via SCPI:
# echo "MQTT:CONF 10.1.0.20,bench/vna/impedance" | nc localhost 5025
```

### 6. Multi-Band Antenna Comparison

Compare 4 antennas across HF bands:

```python
from rf_bench.virtual import VirtualSmithChart
from rf_bench.hp import HP8712B
import time

vna = HP8712B("10.1.1.70", gpib_address=16)
chart = VirtualSmithChart("localhost")

antennas = [
    ("40m Dipole", 1, "#00ff00"),
    ("20m Yagi", 2, "#ff00ff"),
    ("10m GP", 3, "#00ffff"),
    ("Multiband", 4, "#ffff00")
]

chart.set_z0(50)
chart.set_title("Multi-Band Antenna Impedance")

for name, trace_id, color in antennas:
    print(f"Measuring {name}...")
    
    # Switch antenna via relay (not shown)
    
    chart.set_trace(trace_id)
    chart.set_trace_label(trace_id, name)
    chart.set_trace_color(trace_id, color)
    chart.clear_trace(trace_id)
    
    # Sweep 3-30 MHz
    vna.set_frequency_range(3e6, 30e6)
    vna.set_points(101)
    vna.trigger_sweep()
    time.sleep(2)
    
    freq, s11 = vna.get_trace_data()
    
    for f, gamma in zip(freq, s11):
        z_norm = (1 + gamma) / (1 - gamma)
        
        # Label ham bands
        if f in [7.1e6, 14.2e6, 21.2e6, 28.5e6]:
            chart.add_point_with_freq(z_norm.real, z_norm.imag, f)
        else:
            chart.add_point(z_norm.real, z_norm.imag)
    
    time.sleep(1)
```

### 7. Transmission Line Calculator

Visualize impedance transformation along transmission line:

```python
from rf_bench.virtual import VirtualSmithChart
import numpy as np

chart = VirtualSmithChart("localhost")

# Load impedance
z_load = 75 + 30j
z0_line = 50  # Coax impedance
freq = 14.2e6
vf = 0.66     # Velocity factor

# Normalize load
z_load_norm = z_load / z0_line

chart.set_z0(z0_line)
chart.set_trace(1)
chart.set_trace_label(1, f"Z_load = {z_load}")
chart.set_title(f"50Ω Line, {freq/1e6:.1f} MHz")

# Convert to reflection coefficient
gamma_load = (z_load_norm - 1) / (z_load_norm + 1)

# Plot impedance vs line length
for length_m in np.linspace(0, 10, 100):
    # Electrical length
    wavelength = 3e8 / (freq * vf)
    beta_l = 2 * np.pi * length_m / wavelength
    
    # Rotate reflection coefficient
    gamma_at_dist = gamma_load * np.exp(-2j * beta_l)
    
    # Convert back to impedance
    z_at_dist = z0_line * (1 + gamma_at_dist) / (1 - gamma_at_dist)
    z_norm = z_at_dist / z0_line
    
    # Mark quarter-wave points
    if abs(length_m - wavelength/4) < 0.01 or abs(length_m - wavelength/2) < 0.01:
        chart.add_point_with_freq(z_norm.real, z_norm.imag, length_m)
    else:
        chart.add_point(z_norm.real, z_norm.imag)

# Spiral traces inward toward center as line length increases
```

## Architecture

**Backend:** Python FastAPI + asyncio
- SCPI TCP server (port 5025)
- HTTP server (serves HTML frontend)
- WebSocket server (real-time updates)
- MQTT subscriber (impedance data streams)

**Frontend:** HTML5 Canvas + vanilla JavaScript
- Smith chart polar grid rendering
- Multiple trace plotting with colors
- Real-time WebSocket updates
- Responsive sizing

**MQTT Message Format:**
```json
{
    "z": [0.8, 0.5],     // Normalized impedance [real, imag]
    "freq": 14200000,    // Frequency in Hz (optional)
    "polar": false       // If true, z=[magnitude, angle_degrees]
}
```

## Dependencies

**Backend:**
```bash
pip install fastapi uvicorn websockets paho-mqtt --break-system-packages
```

**Frontend:** None (pure HTML5 + JavaScript)

## License

GPL-3.0-or-later

Copyright (C) 2026 Jeff Francis (N0GQ) <gjfrancis@protonmail.com>

## See Also

- `drivers/virtual-smith-chart/` — Python driver package
- `virtual/benchview/` — Multi-instrument panel manager
- `projects/vna/sparams/` — HP 8712B VNA S-parameter measurements
- `projects/rf/antenna-tuner-panel/` — Complete tuner control panel
- `projects/esp32/scpi-tuner/` — ESP32 automatic antenna tuner
