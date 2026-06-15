# rf-bench-drivers-virtual-button

Python driver for **Virtual Push Button** SCPI instrument. Controls button press simulation, press counter, colors, size, and label via SCPI-over-TCP (port 5025).

## Installation

```bash
pip install rf-bench-drivers-virtual-button
```

Or install from source:

```bash
cd drivers/virtual-button
pip install -e .
```

## Quick Start

```python
from rf_bench.virtual import VirtualButton

# Spectrum sweep trigger button
with VirtualButton("10.1.1.52") as btn:
    btn.configure(
        label="Sweep",
        color="#4488ff",
        pressed_color="#88bbff"
    )
    # Wait for user to press button in browser
    while not btn.is_pressed():
        time.sleep(0.1)
    print("Starting sweep...")

# Calibration button with press counter
with VirtualButton("10.1.1.52") as btn:
    btn.configure(label="Calibrate")
    while True:
        count = btn.get_count()
        if count > 0:
            print(f"Running calibration #{count}...")
            # ... perform calibration ...
            time.sleep(2)
```

## Backend Server

The driver connects to a virtual button backend server:

```bash
cd ~/Dropbox/build/rf-bench/virtual/button/backend
python3 server.py --scpi-port 5025 --http-port 8000
```

Open browser at `http://localhost:8000` to see the virtual button.

## API Reference

### Connection

```python
VirtualButton(host, port=5025, timeout=2.0)
```

- **host**: IP address or hostname of backend server
- **port**: SCPI TCP port (default 5025)
- **timeout**: Socket timeout in seconds

### IEEE 488.2 Commands

```python
btn.idn()           # → "N0GQ,Virtual-Button,1.0,2026"
btn.reset()         # Reset to default state
btn.get_error()     # → "0,No error"
```

### Button State Control

```python
btn.press()              # Programmatically press button (500ms pulse)
btn.is_pressed()         # → True if currently pressed (hardware or software)
btn.get_count()          # → Total press count since reset
btn.clear_count()        # Reset press counter to 0
```

**IMPORTANT:** `btn.press()` triggers a momentary 500ms press and returns immediately. The button automatically returns to unpressed state. Use `btn.is_pressed()` to detect active presses (browser clicks or software-triggered).

### Button Configuration

```python
# Full configuration
btn.configure(
    color="#4488ff",           # Normal color (blue)
    pressed_color="#88bbff",   # Pressed color (lighter blue)
    label="Start",
    size=100                   # Width in pixels
)

# Individual settings
btn.set_color("#00cc44")           # Green button
btn.set_pressed_color("#44ff88")   # Light green when pressed
btn.set_label("Sweep")
btn.set_size(120)                  # Larger button

# Query settings
btn.get_color()            # → "#00cc44"
btn.get_pressed_color()    # → "#44ff88"
btn.get_label()            # → "Sweep"
btn.get_size()             # → 120
```

## Common Use Cases

### Spectrum Sweep Trigger

```python
from rf_bench.siglent import SSA3000X
from rf_bench.virtual import VirtualButton
import time

ssa = SSA3000X("10.1.1.60")
btn = VirtualButton("10.1.1.52")

btn.configure(
    label="Sweep",
    color="#4488ff",
    pressed_color="#88bbff"
)

print("Press button to trigger sweep...")
while True:
    if btn.is_pressed():
        print("Sweeping...")
        ssa.single_sweep()
        time.sleep(0.5)  # Debounce
    time.sleep(0.1)
```

### Calibration Trigger with Counter

```python
from rf_bench.virtual import VirtualButton
import time

btn = VirtualButton("10.1.1.52")
btn.configure(label="Calibrate", color="#ff8800")
btn.clear_count()

print("Press button to run calibration...")
last_count = 0

while True:
    count = btn.get_count()
    if count > last_count:
        print(f"Running calibration #{count}...")
        # ... perform calibration steps ...
        print(f"Calibration #{count} complete")
        last_count = count
    time.sleep(0.1)
```

### Measurement Start/Stop Toggle

```python
from rf_bench.virtual import VirtualButton
import time

btn = VirtualButton("10.1.1.52")
btn.configure(label="Start/Stop", color="#00cc44")

running = False
btn.clear_count()

while True:
    count = btn.get_count()
    if count % 2 == 1:  # Odd count = running
        if not running:
            print("Starting measurement...")
            running = True
    else:  # Even count = stopped
        if running:
            print("Stopping measurement...")
            running = False
    
    if running:
        # ... perform measurement ...
        print(".", end="", flush=True)
    
    time.sleep(0.5)
```

### Remote Trigger from Script

```python
from rf_bench.virtual import VirtualButton
import time

btn = VirtualButton("10.1.1.52")
btn.configure(label="Trigger", color="#ff0000")

# Programmatically press button (simulates browser click)
btn.press()
print("Button pressed programmatically")

# Check if button is currently pressed
time.sleep(0.2)  # During 500ms pulse
if btn.is_pressed():
    print("Button is active")

time.sleep(0.5)
if not btn.is_pressed():
    print("Button returned to unpressed state")
```

### Multi-Button Control Panel

Run multiple backend servers on different ports:

```python
from rf_bench.virtual import VirtualButton

# Start button (green)
start = VirtualButton("10.1.1.52", port=5025)
start.configure(label="Start", color="#00cc44")

# Stop button (red)
stop = VirtualButton("10.1.1.52", port=5026)
stop.configure(label="Stop", color="#cc0000")

# Reset button (blue)
reset = VirtualButton("10.1.1.52", port=5027)
reset.configure(label="Reset", color="#4488ff")

# Monitor buttons
while True:
    if start.is_pressed():
        print("Start pressed")
    if stop.is_pressed():
        print("Stop pressed")
    if reset.is_pressed():
        print("Reset pressed")
        start.clear_count()
        stop.clear_count()
        reset.clear_count()
    time.sleep(0.1)
```

## SCPI Command Reference

### IEEE 488.2 Common Commands
- `*IDN?` — Identification query
- `*RST` — Reset to defaults
- `SYST:ERR?` — Query error queue

### Button State Commands
- `STAT:PRESS` — **Momentary press** (500ms pulse, no parameter)
- `STAT:PRESS?` — Query current pressed state (returns 0 or 1)
- `STAT:COUNT?` — Query total press count
- `STAT:COUNT 0` — Clear press counter

**IMPORTANT:** `STAT:PRESS` takes **no parameter**. It triggers a momentary 500ms press. The button automatically returns to unpressed state. This differs from the LED's `STAT:VAL` command which takes an ON/OFF parameter for persistent state.

### Configuration Commands
- `CONF:COL <color>` — Set normal color (hex: #RGB or #RRGGBB)
- `CONF:COL?` — Query normal color
- `CONF:PRECOL <color>` — Set pressed color (hex: #RGB or #RRGGBB)
- `CONF:PRECOL?` — Query pressed color
- `CONF:SIZE <pixels>` — Set button width (60-200)
- `CONF:SIZE?` — Query button size
- `CONF:LABEL <string>` — Set label text
- `CONF:LABEL?` — Query label text

### Direct SCPI Example

```bash
# Using netcat
echo "*IDN?" | nc localhost 5025
echo "STAT:PRESS" | nc localhost 5025          # Press button (500ms pulse)
echo "STAT:PRESS?" | nc localhost 5025         # Query if currently pressed
echo "STAT:COUNT?" | nc localhost 5025         # Query press count
echo "CONF:COL #00cc44" | nc localhost 5025    # Green button
echo "CONF:LABEL Start" | nc localhost 5025
```

## Button Display

The virtual button displays:
- **Unpressed**: Normal color with raised (3D) appearance
- **Pressed**: Pressed color with recessed (inset) appearance
- **Size**: Configurable width (60-200 pixels, default 100)
- **Label**: Text on button face
- **Press duration**: Software-triggered presses last 500ms (browser clicks last as long as mouse is held)

## Error Handling

```python
from rf_bench.virtual import VirtualButton, VirtualButtonError

try:
    btn = VirtualButton("10.1.1.99")  # Wrong IP
except VirtualButtonError as e:
    print(f"Connection failed: {e}")

try:
    btn.set_size(300)  # Out of range
except ValueError as e:
    print(f"Invalid size: {e}")

# Verify counter increments
btn.clear_count()
btn.press()
time.sleep(0.6)  # Wait for press to complete
assert btn.get_count() == 1, "Press didn't register"
```

## Requirements

- Python 3.7+
- No external dependencies (uses stdlib `socket`)

## License

GPL-3.0-or-later — see LICENSE file in package root.

## See Also

- Backend server: `~/Dropbox/build/rf-bench/virtual/button/`
- BenchView panel manager: `~/Dropbox/build/rf-bench/virtual/benchview/`
- Other virtual instruments: `~/Dropbox/build/rf-bench/virtual/`
- RF Bench drivers: `~/Dropbox/build/rf-bench/drivers/`
