# Multi-Instance Virtual Instrument Drivers

## Overview

All virtual instrument drivers now support multi-instance operation via dedicated `*Multi` driver classes. These drivers work with the multi-instance backends (`server-multi.py`) and BenchView's dynamic port assignment system.

## Architecture

```
Bridge Script
    ↓
Python Driver API (*Multi classes)
    ↓
SCPI-over-TCP (dynamic ports from BenchView)
    ↓
Multi-Instance Backend (server-multi.py)
    ↓
WebSocket
    ↓
HTML5 Frontend (index-multi.html)
```

**Key principles:**
1. **No raw SCPI in application code** - only use Python driver methods
2. **Dynamic port assignment** - read ports from BenchView's `*_ports.yaml` file
3. **1-based indexing** - all multi-instance commands use index 1-4
4. **Stateless connections** - each SCPI command opens/closes a TCP socket

## Available Multi-Instance Drivers

All 16 virtual instruments have multi-instance drivers:

| Instrument | Driver Class | Value Command | Package |
|------------|--------------|---------------|---------|
| analog-meter | `VirtualAnalogMeterMulti` | `MEAS<n>:VAL` | `rf-bench-drivers-virtual-analog-meter` |
| bar-graph | `VirtualBarGraphMulti` | `MEAS<n>:VAL` | `rf-bench-drivers-virtual-bar-graph` |
| button | `VirtualButtonMulti` | `STAT<n>:VAL` | `rf-bench-drivers-virtual-button` |
| compass | (single-instance only) | `MEAS:HEAD` | `rf-bench-drivers-virtual-compass` |
| gauge-cluster | (single-instance only) | `MEAS<n>:VAL` | `rf-bench-drivers-virtual-gauge-cluster` |
| knob | `VirtualKnobMulti` | `SOUR<n>:VAL` | `rf-bench-drivers-virtual-knob` |
| led | `VirtualLEDMulti` | `STAT<n>:VAL` | `rf-bench-drivers-virtual-led` |
| line-chart | (single-instance only) | `MEAS:VAL` | `rf-bench-drivers-virtual-line-chart` |
| numeric-display | `VirtualNumericDisplayMulti` | `MEAS<n>:VAL` | `rf-bench-drivers-virtual-numeric-display` |
| slider | `VirtualSliderMulti` | `SOUR<n>:VAL` | `rf-bench-drivers-virtual-slider` |
| smith-chart | (single-instance only) | N/A | `rf-bench-drivers-virtual-smith-chart` |
| text-input | `VirtualTextInputMulti` | `SOUR<n>:VAL` | `rf-bench-drivers-virtual-text-input` |
| text-lcd | (single-instance only) | `TEXT:LINE<n>` | `rf-bench-drivers-virtual-text-lcd` |
| toggle | `VirtualToggleMulti` | `STAT<n>:VAL` | `rf-bench-drivers-virtual-toggle` |
| waterfall | (single-instance only) | `MEAS:SPEC` | `rf-bench-drivers-virtual-waterfall` |
| xy-plot | (single-instance only) | `MEAS:XY` | `rf-bench-drivers-virtual-xy-plot` |

**Note:** Some instruments (compass, gauge-cluster, line-chart, smith-chart, text-lcd, waterfall, xy-plot) currently only support single-instance operation due to their specialized nature.

## Usage Pattern

### 1. Start BenchView with your panel configuration

```bash
cd ~/Dropbox/build/rf-bench/virtual/benchview/backend
python3 benchview.py my-panel.yaml
```

BenchView will:
- Assign unique SCPI ports to each instrument (starting at 5100)
- Launch backend servers with assigned ports
- Export port assignments to `~/.rf-bench/my-panel_ports.yaml`

### 2. Read port assignments in your bridge script

```python
import yaml
from pathlib import Path

# Read port assignments from BenchView
ports_file = Path.home() / '.rf-bench' / 'my-panel_ports.yaml'
with open(ports_file) as f:
    port_config = yaml.safe_load(f)

# Extract ports for your instruments
input_port = port_config['instruments']['my-inputs']['scpi_port']
display_port = port_config['instruments']['my-displays']['scpi_port']
```

### 3. Initialize drivers with dynamic ports

```python
from rf_bench.virtual import VirtualTextInputMulti, VirtualNumericDisplayMulti

inputs = VirtualTextInputMulti('localhost', port=input_port)
displays = VirtualNumericDisplayMulti('localhost', port=display_port)
```

### 4. Control instrument instances (1-based indexing)

```python
# Read user input from text-input #1
voltage = float(inputs.get_value(1))

# Update numeric display #2
displays.set_value(2, voltage)

# Configure display #1
displays.set_label(1, "Voltage")
displays.set_units(1, "V")
displays.set_precision(1, 3)
```

## Common Driver Methods

All multi-instance drivers share these common methods:

```python
# Instance configuration
driver.get_count()          # Query number of instances
driver.set_count(count)     # Set number of instances (1-4)

# IEEE 488.2 commands
driver.idn()                # Query identification
driver.reset()              # Reset to defaults

# Connection
driver.close()              # Close (no-op for stateless drivers)
```

## Value Command Patterns

### MEAS<n>:VAL (Measurement Output)

Used by: analog-meter, bar-graph, numeric-display, gauge-cluster

```python
display.set_value(index, value)   # Set displayed value
value = display.get_value(index)  # Query displayed value
```

### SOUR<n>:VAL (Source Input)

Used by: knob, slider, text-input

```python
control.set_value(index, value)   # Set control value (backend)
value = control.get_value(index)  # Query control value (user input)
```

### STAT<n>:VAL (Status/State)

Used by: button, led, toggle

```python
indicator.set_state(index, True)  # Turn on
indicator.set_state(index, False) # Turn off
state = indicator.get_state(index)  # Query state (bool)

# Convenience methods
indicator.on(index)               # Turn on
indicator.off(index)              # Turn off
```

## Port Assignment YAML Format

BenchView exports port assignments in this format:

```yaml
panel: "My Panel Name"
instruments:
  my-inputs:
    scpi_port: 5100
    http_port: 8100
    ws_port: 8100
    type: text-input
    count: 2
    layout: col
    indexing: 1-based
  
  my-displays:
    scpi_port: 5101
    http_port: 8101
    ws_port: 8101
    type: numeric-display
    count: 4
    layout: 2x2
    indexing: 1-based
```

## Example Bridge Script

See `/tmp/bridge-final.py` for a complete working example that:
- Reads port assignments from YAML
- Uses multi-instance drivers for all virtual instruments
- Uses physical instrument drivers (SPD3303X, SDM3000X)
- Implements power limiting and safety shutdown
- NO raw SCPI anywhere in application code

## Development Guidelines

When creating bridge scripts or applications using virtual instruments:

1. **Always read ports from YAML** - never hardcode port numbers
2. **Use driver methods only** - never send raw SCPI commands
3. **Handle exceptions** - network operations can fail
4. **Use 1-based indexing** - all multi-instance commands use index 1-4
5. **Close drivers** - call `driver.close()` when done (even though stateless)

## Driver Installation

Multi-instance drivers are included in the standard driver packages:

```bash
# Install from PyPI (when published)
pip install rf-bench-drivers-virtual-led

# Or install from source
cd ~/Dropbox/build/rf-bench/drivers/virtual-led
pip install -e .
```

Import multi-instance drivers:

```python
from rf_bench.virtual import VirtualLEDMulti
from rf_bench.virtual import VirtualNumericDisplayMulti
from rf_bench.virtual import VirtualTextInputMulti
```

## Testing

To test a multi-instance driver without BenchView:

```bash
# Start backend manually
cd ~/Dropbox/build/rf-bench/virtual/led/backend
python3 server-multi.py --scpi-port 5025 --http-port 8000 --count 3 --layout row

# In another terminal, test the driver
python3 << 'EOF'
from rf_bench.virtual import VirtualLEDMulti

leds = VirtualLEDMulti('localhost', port=5025)
leds.set_label(1, "Status")
leds.set_label(2, "Error")
leds.set_label(3, "Ready")
leds.on(3)
print(f"LED 3 state: {leds.get_state(3)}")
EOF
```

## See Also

- Individual driver READMEs in `drivers/virtual-*/README.md`
- BenchView documentation in `virtual/benchview/`
- Example configurations in `virtual/benchview/backend/*.yaml`
