# Text Lcd — part of `rf-bench-drivers-virtual`
Python driver for **Virtual Text LCD** SCPI instrument. Displays scrolling terminal-style text output with configurable color, font size, and scrollback buffer via SCPI-over-TCP (port 5006).

## Installation

```bash
pip install rf-bench-drivers-virtual
```

Or install from source:

```bash
cd drivers/virtual-text-lcd
pip install -e .
```

## Quick Start

```python
from rf_bench.virtual import VirtualTextLCD

# Basic text output
with VirtualTextLCD("10.1.1.52") as lcd:
    lcd.write("System initialized")
    lcd.write("Temperature: 25.3°C")
    lcd.write("Pressure: 1013 hPa")

# Styled terminal
with VirtualTextLCD("10.1.1.52") as lcd:
    lcd.configure(
        title="System Monitor",
        color="#00ff00",
        font_size=16,
        max_lines=100
    )
    
    for i in range(10):
        lcd.writeln(f"Processing item {i+1}/10")
```

## Backend Server

The driver connects to a virtual text LCD backend server:

```bash
cd ~/Dropbox/build/rf-bench/virtual/text-lcd/backend
python3 server.py
```

Server listens on:
- **SCPI TCP**: port 5006
- **HTTP/WebSocket**: port 8006
- **Web UI**: http://localhost:8006

Open browser at `http://localhost:8006` to see the virtual terminal.

## API Reference

### Connection

```python
VirtualTextLCD(host, port=5006, timeout=2.0)
```

- **host**: IP address or hostname of backend server
- **port**: SCPI TCP port (default 5006)
- **timeout**: Socket timeout in seconds

### IEEE 488.2 Commands

```python
lcd.idn()           # → "N0GQ,Virtual-Text-LCD,1.0,2026"
lcd.reset()         # Reset to default state, clear all text
lcd.get_error()     # → "0,No error"
```

### Display Commands

```python
# Write text (timestamp added automatically)
lcd.write("System initialized")
lcd.writeln("Temperature: 25.3°C")  # Alias for write()

# Clear display
lcd.clear()

# Query buffer status
lcd.get_line_count()  # → 42
```

**Terminal output example:**

```
[14:23:01] System initialized
[14:23:01] Temperature: 25.3°C
[14:23:02] Pressure: 1013 hPa
[14:23:02] Humidity: 45%
```

### Configuration Commands

```python
# Scrollback buffer (10-1000 lines)
lcd.set_max_lines(100)
lcd.get_max_lines()      # → 100

# Font size (10-24 points)
lcd.set_font_size(16)
lcd.get_font_size()      # → 16

# Text color (hex format)
lcd.set_color("#00ff00")  # Green
lcd.get_color()           # → "#00ff00"

# Window title
lcd.set_title("System Monitor")
lcd.get_title()           # → "System Monitor"

# Configure all at once
lcd.configure(
    title="Test Log",
    color="#00ff88",
    font_size=14,
    max_lines=50
)
```

### MQTT Integration

Subscribe to MQTT topic for remote text streaming:

```python
# Configure MQTT broker and topic
lcd.configure_mqtt("10.1.0.20", "sensors/temperature")

# Query configuration
lcd.get_mqtt_config()  # → "10.1.0.20,sensors/temperature"
```

MQTT messages published to the configured topic will appear in the terminal automatically.

### Convenience Methods

```python
# Print multiple lines
lines = [
    "Starting test sequence",
    "Phase 1: Initialization",
    "Phase 2: Calibration",
    "Phase 3: Measurement"
]
lcd.print_lines(lines, interval=0.5)  # 0.5s delay between lines
```

## Common Use Cases

### Test Script Output Logger

```python
from rf_bench.virtual import VirtualTextLCD
from rf_bench.siglent import SSA3000X
import time

lcd = VirtualTextLCD("10.1.1.52")
ssa = SSA3000X("10.1.1.60")

lcd.configure("Spectrum Sweep", "#00ff00", 14)
lcd.write("Starting frequency sweep")

for freq_mhz in range(100, 1000, 100):
    ssa.set_center_span(freq_mhz * 1e6, 10e6)
    time.sleep(0.5)
    ssa.peak_search()
    freq, power = ssa.get_peak()
    
    lcd.write(f"{freq_mhz} MHz: peak at {freq/1e6:.3f} MHz, {power:.1f} dBm")

lcd.write("Sweep complete")
```

**Terminal output:**

```
[15:42:10] Starting frequency sweep
[15:42:11] 100 MHz: peak at 100.234 MHz, -45.3 dBm
[15:42:12] 200 MHz: peak at 200.156 MHz, -38.7 dBm
[15:42:13] 300 MHz: peak at 300.089 MHz, -42.1 dBm
...
[15:42:19] Sweep complete
```

### Radio Monitoring Log (IC-7300)

```python
from rf_bench.virtual import VirtualTextLCD
from rf_bench.icom import IC7300
import time

lcd = VirtualTextLCD("10.1.1.52")
radio = IC7300()

lcd.configure("Band Monitor", "#00ff88", 14, 200)
lcd.write("Monitoring 20m band")

radio.set_frequency(14_200_000)
radio.set_mode("USB")

while True:
    strength = radio.get_strength_settled()
    if strength > 3:  # S3 threshold
        freq = radio.get_frequency()
        mode = radio.get_mode()
        lcd.write(f"Signal: {freq/1e6:.3f} MHz {mode} S{strength:.0f}")
    time.sleep(1)
```

**Terminal output:**

```
[16:05:00] Monitoring 20m band
[16:05:12] Signal: 14.200 MHz USB S5
[16:05:34] Signal: 14.245 MHz USB S7
[16:06:01] Signal: 14.195 MHz USB S4
```

### Multi-Instrument Status Dashboard

```python
from rf_bench.virtual import VirtualTextLCD
from rf_bench.siglent import SPD3303X, SDM3045X
import time

lcd = VirtualTextLCD("10.1.1.52")
psu = SPD3303X("10.1.1.56")
dmm = SDM3045X("10.1.1.63")

lcd.configure("Lab Status", "#0088ff", 14, 100)
lcd.write("Multi-instrument monitor started")

psu.set_voltage(1, 13.8)
psu.set_current(1, 2.0)
psu.enable(1)

while True:
    v_psu = psu.measure_voltage(1)
    i_psu = psu.measure_current(1)
    v_dmm = dmm.measure_voltage_dc()
    
    lcd.write(f"PSU: {v_psu:.3f}V {i_psu:.3f}A | DMM: {v_dmm:.4f}V")
    time.sleep(2)
```

**Terminal output:**

```
[17:30:00] Lab Status
[17:30:01] Multi-instrument monitor started
[17:30:01] PSU: 13.798V 0.234A | DMM: 5.0012V
[17:30:03] PSU: 13.801V 0.231A | DMM: 5.0009V
[17:30:05] PSU: 13.799V 0.236A | DMM: 5.0014V
```

### Temperature Logging with MQTT

**Python publisher:**

```python
import paho.mqtt.publish as publish
import random
import time

while True:
    temp = 20 + random.uniform(-2, 2)
    publish.single(
        "lab/temperature",
        f"Temperature: {temp:.1f}°C",
        hostname="10.1.0.20"
    )
    time.sleep(5)
```

**LCD subscriber:**

```python
from rf_bench.virtual import VirtualTextLCD

lcd = VirtualTextLCD("10.1.1.52")
lcd.configure("Temperature Monitor", "#ff8800", 16, 200)
lcd.configure_mqtt("10.1.0.20", "lab/temperature")

# Messages appear automatically in terminal
```

**Terminal output:**

```
[18:00:00] Temperature Monitor
[18:00:05] Temperature: 20.3°C
[18:00:10] Temperature: 21.7°C
[18:00:15] Temperature: 19.8°C
[18:00:20] Temperature: 20.9°C
```

### Long-Running Test Log

```python
from rf_bench.virtual import VirtualTextLCD
from rf_bench.siglent import SSA3000X
import time

lcd = VirtualTextLCD("10.1.1.52")
ssa = SSA3000X("10.1.1.60")

lcd.configure("Stability Test", "#ffff00", 14, 500)
lcd.write("24-hour oscillator stability test started")

ssa.set_center_span(10e6, 1e3)
start_time = time.time()
measurement_num = 0

while time.time() - start_time < 86400:  # 24 hours
    ssa.peak_search()
    freq, power = ssa.get_peak()
    elapsed_hours = (time.time() - start_time) / 3600
    
    lcd.write(f"[{elapsed_hours:.2f}h] Meas #{measurement_num}: "
              f"{freq/1e6:.6f} MHz, {power:.2f} dBm")
    
    measurement_num += 1
    time.sleep(300)  # Every 5 minutes

lcd.write("Test complete")
```

**Terminal output:**

```
[09:00:00] 24-hour oscillator stability test started
[09:00:00] [0.00h] Meas #0: 10.000234 MHz, -23.45 dBm
[09:05:00] [0.08h] Meas #1: 10.000238 MHz, -23.43 dBm
[09:10:00] [0.17h] Meas #2: 10.000241 MHz, -23.44 dBm
...
[08:55:00] [23.92h] Meas #287: 10.000256 MHz, -23.42 dBm
[09:00:00] Test complete
```

### Build Automation Log

```python
from rf_bench.virtual import VirtualTextLCD
import subprocess
import time

lcd = VirtualTextLCD("10.1.1.52")
lcd.configure("Build Monitor", "#00ff00", 14, 300)

projects = ["firmware", "bootloader", "application"]

for project in projects:
    lcd.write(f"Building {project}...")
    
    result = subprocess.run(
        ["make", "-C", project],
        capture_output=True,
        text=True
    )
    
    if result.returncode == 0:
        lcd.write(f"✓ {project} build successful")
    else:
        lcd.write(f"✗ {project} build FAILED")
        for line in result.stderr.split('\n')[:5]:  # First 5 errors
            lcd.write(f"  {line}")

lcd.write("Build process complete")
```

**Terminal output:**

```
[10:30:00] Building firmware...
[10:30:15] ✓ firmware build successful
[10:30:15] Building bootloader...
[10:30:22] ✓ bootloader build successful
[10:30:22] Building application...
[10:30:45] ✗ application build FAILED
[10:30:45]   error: undefined reference to 'init_peripheral'
[10:30:45]   error: 'CONFIG_VERSION' undeclared
[10:30:45] Build process complete
```

## SCPI Command Reference

### IEEE 488.2 Common Commands
- `*IDN?` — Identification query
- `*RST` — Reset to defaults, clear all text
- `SYST:ERR?` — Query error queue

### Display Commands
- `DISP:TEXT "<string>"` — Append text line with timestamp
- `DISP:TEXT?` — Query number of lines in buffer
- `DISP:CLEAR` — Clear all text

### Configuration Commands
- `CONF:LINES <10-1000>` — Set scrollback buffer size
- `CONF:LINES?` — Query scrollback buffer size
- `CONF:SIZE <10-24>` — Set font size (points)
- `CONF:SIZE?` — Query font size
- `CONF:COL "<#RRGGBB>"` — Set text color (hex)
- `CONF:COL?` — Query text color
- `CONF:TITLE "<string>"` — Set window title
- `CONF:TITLE?` — Query window title

### MQTT Commands
- `MQTT:CONF <host>,<topic>` — Configure MQTT broker and topic
- `MQTT:CONF?` — Query MQTT configuration

### Direct SCPI Example

```bash
# Using netcat
echo 'DISP:TEXT "System initialized"' | nc localhost 5006
echo 'CONF:TITLE "Test Log"' | nc localhost 5006
echo 'CONF:COL "#00ff00"' | nc localhost 5006
echo 'DISP:TEXT "Temperature: 25.3°C"' | nc localhost 5006
echo 'DISP:CLEAR' | nc localhost 5006
```

## Terminal Display

The virtual terminal displays:
- **Timestamp**: [HH:MM:SS] prefix added automatically to each line
- **Scrollback**: Configurable buffer (10-1000 lines, default 50)
- **Font**: Dot Matrix TTF monospace font
- **Color**: Configurable text color (default black)
- **Auto-scroll**: Newest text at bottom, auto-scrolls on update

## Error Handling

```python
from rf_bench.virtual import VirtualTextLCD, VirtualTextLCDError

try:
    lcd = VirtualTextLCD("10.1.1.99")  # Wrong IP
except VirtualTextLCDError as e:
    print(f"Connection failed: {e}")

try:
    lcd.set_font_size(50)  # Out of range
except ValueError as e:
    print(f"Invalid parameter: {e}")
```

## Requirements

- Python 3.7+
- No external dependencies (uses stdlib `socket`)

## Backend Requirements

Backend server requires:
- Python 3.7+
- FastAPI, uvicorn, websockets
- paho-mqtt (for MQTT support)

```bash
pip install fastapi uvicorn websockets paho-mqtt --break-system-packages
```

## License

GPL-3.0-or-later — see LICENSE file in package root.

## See Also

- Backend server: `~/Dropbox/build/rf-bench/virtual/text-lcd/`
- BenchView panel manager: `~/Dropbox/build/rf-bench/virtual/benchview/`
- Other virtual instruments: `~/Dropbox/build/rf-bench/virtual/`
- RF Bench drivers: `~/Dropbox/build/rf-bench/drivers/`
