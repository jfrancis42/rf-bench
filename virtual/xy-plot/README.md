# Virtual XY Plot

✅ **Status: Tested 2026-06-14** — SCPI commands, WebSocket updates, scatter plot, axes, grid, auto-scaling verified

SCPI-controlled XY scatter/line plot for two-dimensional data visualization. Features automatic axis scaling, grid lines, and configurable appearance.

## Features

- **SCPI TCP server** on port 5005 (IEEE 488.2 standard)
- **WebSocket real-time updates** for instant plot updates
- **Scatter or line plot** modes
- **Automatic axis scaling** or manual range setting
- **Grid lines and labels** with configurable colors
- **Point markers** with adjustable size and color

## Ports

- **SCPI:** `tcp://0.0.0.0:5005`
- **HTTP:** `http://0.0.0.0:8005`
- **WebSocket:** `ws://0.0.0.0:8005/ws`
- **MQTT:** Configurable via `MQTT:CONF` command

## SCPI Commands

### Data Input
- `DATA:POINT <x>,<y>` — Add a single XY point
- `DATA:POINTS <x1>,<y1>,<x2>,<y2>,...` — Add multiple points (comma-separated pairs)
- `DATA:CLEAR` — Clear all points

### Configuration
- `CONF:XMIN <float>` — Set X-axis minimum (manual scaling)
- `CONF:XMIN?` — Query X-axis minimum
- `CONF:XMAX <float>` — Set X-axis maximum
- `CONF:XMAX?` — Query X-axis maximum
- `CONF:YMIN <float>` — Set Y-axis minimum
- `CONF:YMIN?` — Query Y-axis minimum
- `CONF:YMAX <float>` — Set Y-axis maximum
- `CONF:YMAX?` — Query Y-axis maximum
- `CONF:XAUTO <bool>` — Enable/disable X-axis auto-scaling
- `CONF:XAUTO?` — Query X-axis auto-scaling
- `CONF:YAUTO <bool>` — Enable/disable Y-axis auto-scaling
- `CONF:YAUTO?` — Query Y-axis auto-scaling
- `CONF:XLABEL <string>` — Set X-axis label
- `CONF:XLABEL?` — Query X-axis label
- `CONF:YLABEL <string>` — Set Y-axis label
- `CONF:YLABEL?` — Query Y-axis label
- `CONF:TITLE <string>` — Set plot title
- `CONF:TITLE?` — Query plot title
- `CONF:COL <color>` — Set point color (hex, e.g., "#00ff00")
- `CONF:COL?` — Query point color
- `CONF:SIZE <int>` — Set point marker size (pixels)
- `CONF:SIZE?` — Query point marker size

### IEEE 488.2 Standard
- `*IDN?` — Identification query
- `*RST` — Reset to defaults (clears data)
- `SYST:ERR?` — Query error queue

### MQTT
- `MQTT:CONF <host>,<topic>` — Configure MQTT broker and topic (expects "x,y" string)
- `MQTT:CONF?` — Query MQTT configuration

## Quick Start

```bash
# Start the server
cd ~/Dropbox/build/rf-bench/virtual/xy-plot/backend
python3 server.py

# Open in browser
xdg-open http://localhost:8005

# Configure plot
echo "CONF:TITLE Antenna Pattern" | nc localhost 5005
echo "CONF:XLABEL Azimuth (degrees)" | nc localhost 5005
echo "CONF:YLABEL Gain (dBi)" | nc localhost 5005
echo "CONF:COL #ff8800" | nc localhost 5005

# Add data points
echo "DATA:POINT 0,-3.2" | nc localhost 5005
echo "DATA:POINT 45,2.1" | nc localhost 5005
echo "DATA:POINT 90,5.8" | nc localhost 5005
echo "DATA:POINT 135,3.2" | nc localhost 5005
echo "DATA:POINT 180,-2.5" | nc localhost 5005
```

## Display Behavior

- Points are displayed as circles with configurable size and color
- Axes auto-scale by default to fit all data points
- Manual scaling can be set via `CONF:XMIN/XMAX/YMIN/YMAX`
- Grid lines are drawn at regular intervals
- Origin (0,0) is marked with crosshairs if in view

## Integration Examples

### Antenna pattern plotter
```python
from rf_bench.siglent import SSA3000X
import socket, time
import numpy as np

ssa = SSA3000X('10.1.1.60')
sock = socket.socket()
sock.connect(('localhost', 5005))

# Configure
sock.sendall(b'CONF:TITLE Antenna Pattern - 2.4 GHz\n')
sock.sendall(b'CONF:XLABEL Azimuth (deg)\n')
sock.sendall(b'CONF:YLABEL Power (dBm)\n')
sock.sendall(b'DATA:CLEAR\n')

# Rotate antenna and measure
for angle in range(0, 360, 5):
    # Rotate antenna to angle (via rotator controller)
    # set_rotator_angle(angle)
    time.sleep(0.5)  # Wait for settling
    
    power = ssa.get_marker_level(1)
    sock.sendall(f'DATA:POINT {angle},{power}\n'.encode())
```

### S-parameter sweep (S11)
```python
from rf_bench.siglent import SDG1000X, SSA3000X
import socket, time

sig = SDG1000X('10.1.1.55')
ssa = SSA3000X('10.1.1.60')
sock = socket.socket()
sock.connect(('localhost', 5005))

sock.sendall(b'CONF:TITLE S11 Return Loss\n')
sock.sendall(b'CONF:XLABEL Frequency (MHz)\n')
sock.sendall(b'CONF:YLABEL Return Loss (dB)\n')
sock.sendall(b'DATA:CLEAR\n')

for freq_mhz in np.linspace(1, 30, 100):
    freq_hz = freq_mhz * 1e6
    
    # Set signal generator frequency
    sig.set_frequency(1, freq_hz)
    sig.set_amplitude(1, 0.0)  # 0 dBm
    sig.set_output(1, True)
    
    # Measure at spectrum analyzer
    ssa.set_center_frequency(freq_hz)
    time.sleep(0.05)
    power = ssa.get_marker_level(1)
    return_loss = -power  # S11 in dB
    
    sock.sendall(f'DATA:POINT {freq_mhz},{return_loss}\n'.encode())
```

### Oscilloscope XY mode
```python
from rf_bench.siglent import SDS2000X
import socket, time

scope = SDS2000X('10.1.1.58')
sock = socket.socket()
sock.connect(('localhost', 5005))

sock.sendall(b'CONF:TITLE Lissajous Figure\n')
sock.sendall(b'CONF:XLABEL CH1 (V)\n')
sock.sendall(b'CONF:YLABEL CH2 (V)\n')
sock.sendall(b'DATA:CLEAR\n')

# Get waveform data from both channels
ch1_data = scope.get_waveform(1)
ch2_data = scope.get_waveform(2)

# Plot as XY pairs
for x, y in zip(ch1_data, ch2_data):
    sock.sendall(f'DATA:POINT {x},{y}\n'.encode())
```

### I-V curve tracer
```python
from rf_bench.siglent import SPD3303X, SDM3000X
import socket, time

psu = SPD3303X('10.1.1.56')
dmm = SDM3000X('10.1.1.63')
sock = socket.socket()
sock.connect(('localhost', 5005))

sock.sendall(b'CONF:TITLE Diode I-V Curve\n')
sock.sendall(b'CONF:XLABEL Voltage (V)\n')
sock.sendall(b'CONF:YLABEL Current (mA)\n')
sock.sendall(b'DATA:CLEAR\n')

for voltage in np.linspace(0, 2.0, 50):
    psu.set_voltage(1, voltage)
    psu.set_output(1, True)
    time.sleep(0.1)
    
    current_a = dmm.measure_current_dc()
    current_ma = current_a * 1000
    
    sock.sendall(f'DATA:POINT {voltage},{current_ma}\n'.encode())
```

### MQTT Integration
```bash
# Configure MQTT (expects "x,y" string)
echo "MQTT:CONF localhost,xyplot/point" | nc localhost 5005

# Publish points from elsewhere
mosquitto_pub -h localhost -t xyplot/point -m "10.5,25.3"
mosquitto_pub -h localhost -t xyplot/point -m "11.2,27.8"
```

## Use Cases

- Antenna radiation patterns
- S-parameter plots (return loss, insertion loss)
- Oscilloscope XY mode (Lissajous figures)
- I-V curve tracing
- Filter frequency response
- Phase noise plots
- Constellation diagrams
- Swept measurements
- Calibration curves

## Files

```
xy-plot/
├── backend/
│   └── server.py          # FastAPI SCPI + WebSocket server
├── frontend/
│   └── index.html         # Canvas XY plot
└── README.md              # This file
```

## See Also

- [PORT-ASSIGNMENTS.md](../PORT-ASSIGNMENTS.md) — Port allocations for all instruments
- [BUILDING-STATUS.md](../BUILDING-STATUS.md) — Phase 1 completion status
- [line-chart](../line-chart/) — Time-series line chart display
- [waterfall](../waterfall/) — Spectrum waterfall display
