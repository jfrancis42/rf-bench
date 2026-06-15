# rf-bench-drivers-virtual-gauge-cluster

Python driver for **Virtual Gauge Cluster** SCPI instrument. Controls 2-4 analog panel gauges in dashboard layout via SCPI-over-TCP (port 5025).

## Installation

```bash
pip install rf-bench-drivers-virtual-gauge-cluster
```

Or install from source:

```bash
cd drivers/virtual-gauge-cluster
pip install -e .
```

## Quick Start

```python
from rf_bench.virtual import VirtualGaugeCluster

# Four-gauge dashboard (power supply monitoring)
with VirtualGaugeCluster("10.1.1.52") as cluster:
    cluster.configure_gauge(1, "Voltage", "V", 0, 15, "#00ff00")
    cluster.configure_gauge(2, "Current", "A", 0, 10, "#0088ff")
    cluster.configure_gauge(3, "Power", "W", 0, 150, "#ff8800")
    cluster.configure_gauge(4, "Temperature", "°C", 0, 100, "#ff0000")
    
    cluster.set_value(1, 13.8)
    cluster.set_value(2, 8.2)
    cluster.set_value(3, 113.2)
    cluster.set_value(4, 45.3)

# Two-gauge layout (TX forward/reflected power)
with VirtualGaugeCluster("10.1.1.52") as cluster:
    cluster.set_layout(2)
    cluster.configure_gauge(1, "Forward", "W", 0, 100, "#00ff00")
    cluster.configure_gauge(2, "Reflected", "W", 0, 20, "#ff0000")
    cluster.update_all([50.2, 3.1])
```

## Backend Server

The driver connects to a virtual gauge cluster backend server:

```bash
cd ~/Dropbox/build/rf-bench/virtual/gauge-cluster/backend
python3 server.py
```

Default ports:
- **SCPI**: TCP 5009 (configurable in server.py, line 230)
- **HTTP/WebSocket**: 8009 (configurable in server.py, line 456)

Open browser at `http://localhost:8009` to see the virtual gauge cluster.

**Production deployment:** Edit server.py lines 230 and 456 to use standard ports (5025 for SCPI, 8010 for HTTP).

## API Reference

### Connection

```python
VirtualGaugeCluster(host, port=5025, timeout=2.0)
```

- **host**: IP address or hostname of backend server
- **port**: SCPI TCP port (default 5025)
- **timeout**: Socket timeout in seconds

### IEEE 488.2 Commands

```python
cluster.idn()           # → "N0GQ,Virtual-Gauge-Cluster,1.0,2026"
cluster.reset()         # Reset to default state
cluster.get_error()     # → "0,No error"
```

### Layout Management

```python
cluster.set_layout(2)     # 2 or 4 gauges
cluster.get_layout()      # → 2
```

### Gauge Configuration (1-based indexing)

```python
# Full configuration
cluster.configure_gauge(1,
    label="Voltage",
    units="V",
    min_val=0,
    max_val=15,
    color="#00ff00"  # Optional, default green
)

# Individual settings
cluster.set_label(1, "Voltage")
cluster.set_units(1, "V")
cluster.set_min(1, 0)
cluster.set_max(1, 15)
cluster.set_color(1, "#00ff00")

# Query settings
cluster.get_label(1)      # → "Voltage"
cluster.get_units(1)      # → "V"
cluster.get_min(1)        # → 0.0
cluster.get_max(1)        # → 15.0
cluster.get_color(1)      # → "#00ff00"
```

### Gauge Value Control

```python
cluster.set_value(1, 13.8)    # Set gauge 1 to 13.8 V
cluster.update(1, 13.9)       # Shorter alias
cluster.get_value(1)          # → 13.9

# Update all gauges at once
cluster.update_all({1: 13.8, 2: 8.2, 3: 113.2, 4: 45.3})
cluster.update_all([13.8, 8.2, 113.2, 45.3])  # List is 1-indexed

# Values are clamped to min/max range
cluster.set_min(1, 0)
cluster.set_max(1, 15)
cluster.set_value(1, 20)     # Clamped to 15
```

### Animation

```python
import numpy as np

# Smooth sweep on gauge 1
values = np.linspace(0, 100, 50)
cluster.animate(1, values, interval=0.05)

# Sine wave on gauge 2
t = np.linspace(0, 4*np.pi, 100)
values = 50 + 30 * np.sin(t)
cluster.animate(2, values, interval=0.02)
```

### MQTT Integration

```python
# Configure MQTT subscription for gauge 1
cluster.configure_mqtt(1, "localhost", "radio/power")

# Query MQTT configuration
config = cluster.get_mqtt_config()
print(config)  # → "1:localhost,radio/power; 2:localhost,radio/voltage"
```

Backend subscribes to MQTT topics and updates gauges automatically when messages arrive. Published values must be numeric (int or float).

## Common Use Cases

### Power Supply Monitoring (SPD3303X)

```python
from rf_bench.siglent import SPD3303X
from rf_bench.virtual import VirtualGaugeCluster
import time

psu = SPD3303X("10.1.1.56")
cluster = VirtualGaugeCluster("10.1.1.52")

cluster.set_layout(4)
cluster.configure_gauge(1, "Voltage", "V", 0, 15, "#00ff00")
cluster.configure_gauge(2, "Current", "A", 0, 10, "#0088ff")
cluster.configure_gauge(3, "Power", "W", 0, 150, "#ff8800")
cluster.configure_gauge(4, "Load", "%", 0, 100, "#ff0000")

psu.set_voltage(1, 13.8)
psu.set_current(1, 10.0)
psu.enable(1)

while True:
    v = psu.measure_voltage(1)
    i = psu.measure_current(1)
    p = v * i
    load = (i / 10.0) * 100
    
    cluster.update_all({1: v, 2: i, 3: p, 4: load})
    time.sleep(0.2)
```

### Radio Dashboard (IC-7300)

```python
from rf_bench.icom import IC7300
from rf_bench.siglent import SSA3000X
from rf_bench.virtual import VirtualGaugeCluster
import time

radio = IC7300()
ssa = SSA3000X("10.1.1.60")
cluster = VirtualGaugeCluster("10.1.1.52")

cluster.set_layout(4)
cluster.configure_gauge(1, "S-Meter", "S", 0, 9, "#00ff00")
cluster.configure_gauge(2, "TX Power", "W", 0, 100, "#0088ff")
cluster.configure_gauge(3, "SWR", "", 1, 3, "#ff8800")
cluster.configure_gauge(4, "ALC", "%", 0, 100, "#ff0000")

radio.set_frequency(14_200_000)
radio.set_mode("USB")

while True:
    s_units = radio.get_strength_settled()
    
    # Measure TX power via SSA tracking generator
    ssa.set_center_span(14.2e6, 10e3)
    ssa.tracking_on()
    ssa.peak_search()
    _, power_dbm = ssa.get_peak()
    power_w = 10 ** ((power_dbm - 30) / 10)
    
    swr = 1.5  # From antenna analyzer or SWR meter
    alc = 0.0  # From radio CAT commands
    
    cluster.update_all({1: s_units, 2: power_w, 3: swr, 4: alc})
    time.sleep(0.5)
```

### TX Forward/Reflected Power Monitor

```python
from rf_bench.virtual import VirtualGaugeCluster
import time
import random

cluster = VirtualGaugeCluster("10.1.1.52")
cluster.set_layout(2)

cluster.configure_gauge(1, "Forward", "W", 0, 100, "#00ff00")
cluster.configure_gauge(2, "Reflected", "W", 0, 20, "#ff0000")

while True:
    fwd = random.uniform(45, 55)
    ref = random.uniform(0, 5)
    
    cluster.update_all([fwd, ref])
    time.sleep(0.1)
```

### Environmental Sensors (MQTT)

```python
from rf_bench.virtual import VirtualGaugeCluster

cluster = VirtualGaugeCluster("10.1.1.52")

cluster.set_layout(4)
cluster.configure_gauge(1, "Temperature", "°C", -10, 50, "#00ff00")
cluster.configure_gauge(2, "Humidity", "%", 0, 100, "#0088ff")
cluster.configure_gauge(3, "Pressure", "hPa", 980, 1040, "#ff8800")
cluster.configure_gauge(4, "Air Quality", "AQI", 0, 500, "#ff0000")

# Subscribe to MQTT topics (backend handles updates)
cluster.configure_mqtt(1, "localhost", "home/temperature")
cluster.configure_mqtt(2, "localhost", "home/humidity")
cluster.configure_mqtt(3, "localhost", "home/pressure")
cluster.configure_mqtt(4, "localhost", "home/aqi")

print("Gauges configured. Backend listening to MQTT topics.")
input("Press Enter to exit...")
```

### Battery Discharge Monitor

```python
from rf_bench.siglent import SPD3303X
from rf_bench.yertai import ET5406A
from rf_bench.virtual import VirtualGaugeCluster
import time

psu = SPD3303X("10.1.1.56")
load = ET5406A("/dev/ttyUSB0")
cluster = VirtualGaugeCluster("10.1.1.52")

cluster.set_layout(4)
cluster.configure_gauge(1, "Voltage", "V", 10, 14, "#00ff00")
cluster.configure_gauge(2, "Current", "A", 0, 20, "#0088ff")
cluster.configure_gauge(3, "Capacity", "Ah", 0, 10, "#ff8800")
cluster.configure_gauge(4, "SOC", "%", 0, 100, "#ff0000")

# Discharge 12V lead-acid battery at 5A
load.set_mode("CC")
load.set_current(5.0)
load.enable()

start_time = time.time()
capacity_ah = 0.0
nominal_capacity = 7.0  # 7 Ah battery

while True:
    v = load.measure_voltage()
    i = load.measure_current()
    elapsed_h = (time.time() - start_time) / 3600
    capacity_ah = i * elapsed_h
    soc = max(0, (1 - capacity_ah / nominal_capacity) * 100)
    
    cluster.update_all({1: v, 2: i, 3: capacity_ah, 4: soc})
    
    if v < 10.5:  # Cutoff voltage
        load.disable()
        print(f"Discharge complete. Capacity: {capacity_ah:.2f} Ah")
        break
    
    time.sleep(1)
```

### Multi-Channel Spectrum Monitor (RTL-SDR)

```python
from rf_bench.rtlsdr import RTLSDR
from rf_bench.virtual import VirtualGaugeCluster
import numpy as np
import time

sdr = RTLSDR()
cluster = VirtualGaugeCluster("10.1.1.52")

cluster.set_layout(4)
cluster.configure_gauge(1, "2m Band", "dBm", -120, -40, "#00ff00")
cluster.configure_gauge(2, "70cm Band", "dBm", -120, -40, "#0088ff")
cluster.configure_gauge(3, "APRS", "dBm", -120, -40, "#ff8800")
cluster.configure_gauge(4, "ISM", "dBm", -120, -40, "#ff0000")

channels = [
    (144.39e6, 1),  # 2m APRS
    (446.0e6, 2),   # 70cm calling
    (144.39e6, 3),  # APRS repeat
    (433.92e6, 4),  # ISM band
]

while True:
    for freq, gauge_idx in channels:
        sdr.set_center_frequency(freq)
        samples = sdr.read_samples(256 * 1024)
        psd = np.abs(np.fft.fft(samples)) ** 2
        peak_power_dbfs = 10 * np.log10(np.max(psd) / len(psd))
        peak_power_dbm = peak_power_dbfs - 10  # Rough calibration
        
        cluster.set_value(gauge_idx, peak_power_dbm)
    
    time.sleep(0.5)
```

### Antenna Rotator Status

```python
from rf_bench.virtual import VirtualGaugeCluster
import socket
import time

cluster = VirtualGaugeCluster("10.1.1.52")

cluster.set_layout(2)
cluster.configure_gauge(1, "Azimuth", "°", 0, 360, "#00ff00")
cluster.configure_gauge(2, "Elevation", "°", 0, 90, "#0088ff")

# Connect to ESP32 SCPI rotator controller
rotator = socket.socket()
rotator.connect(("10.1.1.70", 5025))

while True:
    rotator.sendall(b"ROT:AZ?\n")
    az = float(rotator.recv(1024).decode().strip())
    
    rotator.sendall(b"ROT:EL?\n")
    el = float(rotator.recv(1024).decode().strip())
    
    cluster.update_all([az, el])
    time.sleep(0.2)
```

## SCPI Command Reference

All commands use 1-based indexing (N=1,2,3,4):

### IEEE 488.2 Common Commands
- `*IDN?` — Identification query
- `*RST` — Reset to defaults
- `SYST:ERR?` — Query error queue

### Layout Commands
- `CONF:LAYOUT <2|4>` — Set number of gauges
- `CONF:LAYOUT?` — Query layout

### Gauge Commands (N = 1-4)
- `MEAS<N>:VAL <float>` — Set gauge value
- `MEAS<N>:VAL?` — Query gauge value
- `CONF<N>:MIN <float>` — Set minimum scale value
- `CONF<N>:MIN?` — Query minimum
- `CONF<N>:MAX <float>` — Set maximum scale value
- `CONF<N>:MAX?` — Query maximum
- `CONF<N>:UNIT <string>` — Set units
- `CONF<N>:UNIT?` — Query units
- `CONF<N>:LABEL <string>` — Set label
- `CONF<N>:LABEL?` — Query label
- `CONF<N>:COL <color>` — Set needle color (e.g. #00ff00)
- `CONF<N>:COL?` — Query color

### MQTT Commands
- `MQTT:CONF <N>,<host>,<topic>` — Configure MQTT for gauge N
- `MQTT:CONF?` — Query MQTT configuration

### Direct SCPI Example

```bash
# Using netcat
echo "*IDN?" | nc localhost 5025
echo "CONF:LAYOUT 4" | nc localhost 5025
echo "CONF1:LABEL Voltage" | nc localhost 5025
echo "CONF1:UNIT V" | nc localhost 5025
echo "CONF1:MIN 0" | nc localhost 5025
echo "CONF1:MAX 15" | nc localhost 5025
echo "MEAS1:VAL 13.8" | nc localhost 5025
```

## Gauge Display

Each gauge displays:
- **Needle**: Moves smoothly with spring-damper physics
- **Arc**: 270° sweep (configurable angle in frontend)
- **Zones**: Color-coded regions (green/yellow/red by default)
- **Scale**: Numeric tick marks at regular intervals
- **Value**: Large numeric readout at center
- **Units**: Below numeric value
- **Label**: Above gauge arc

Layout options:
- **2 gauges**: Side-by-side horizontal
- **4 gauges**: 2×2 grid

## MQTT Integration

The backend server can subscribe to MQTT topics and update gauges automatically:

```python
cluster.configure_mqtt(1, "localhost", "radio/power")
cluster.configure_mqtt(2, "localhost", "radio/swr")
```

MQTT messages must be numeric (int or float). Non-numeric payloads are logged as errors but don't crash the server.

### Publishing to MQTT (Python)

```python
import paho.mqtt.client as mqtt

client = mqtt.Client()
client.connect("localhost", 1883, 60)
client.publish("radio/power", "50.2")
client.publish("radio/swr", "1.3")
```

### Publishing to MQTT (bash)

```bash
mosquitto_pub -h localhost -t radio/power -m 50.2
mosquitto_pub -h localhost -t radio/swr -m 1.3
```

## Error Handling

```python
from rf_bench.virtual import VirtualGaugeCluster, VirtualGaugeClusterError

try:
    cluster = VirtualGaugeCluster("10.1.1.99")  # Wrong IP
except VirtualGaugeClusterError as e:
    print(f"Connection failed: {e}")

try:
    cluster.set_value(5, 100)  # Index out of range
except ValueError as e:
    print(f"Invalid index: {e}")
```

## Requirements

- Python 3.7+
- No external dependencies (uses stdlib `socket`)

## License

GPL-3.0-or-later — see LICENSE file in package root.

## See Also

- Backend server: `~/Dropbox/build/rf-bench/virtual/gauge-cluster/`
- BenchView panel manager: `~/Dropbox/build/rf-bench/virtual/benchview/`
- Other virtual instruments:
  - `rf-bench-drivers-virtual-analog-meter` — Single/multi-instance analog meters
  - `rf-bench-drivers-virtual-led` — LED indicator panel
  - Virtual bar graph, line chart, text LCD, waterfall, xy-plot (in development)
- RF Bench drivers: `~/Dropbox/build/rf-bench/drivers/`
