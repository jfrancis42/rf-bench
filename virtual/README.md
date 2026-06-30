# Virtual SCPI Instruments

Web-based virtual instruments with SCPI-over-TCP backends for RF bench automation. All instruments feature HTML5 Canvas frontends, FastAPI/WebSocket backends, and complete Python driver libraries.

## Status: 16 Instruments Built, All with Complete Drivers ✅

**COMPLETE (backend + frontend + Python driver):** 16 instruments
1. ✅ **Analog Meter** — 270° arc sweep, spring-damper needle physics, colored zones
2. ✅ **LED Indicator** — On/off/blink states, customizable colors, CSS glow effects
3. ✅ **7-Segment Display** — DSEG7 LED font, configurable precision and units
4. ✅ **Bar Graph** — Vertical level meter with colored zones (green/yellow/red)
5. ✅ **Rotary Knob** — Rotation animation with min/max range and label
6. ✅ **Linear Slider** — Smooth motion with value display and units
7. ✅ **Push Button** — Momentary press animation with label
8. ✅ **Toggle Switch** — Flip animation with on/off states
9. ✅ **Line Chart** — Time-series scrolling chart, auto-scaling, threshold zones, MQTT integration
10. ✅ **XY Plot** — 2D scatter plot, parametric curves, zoom/pan, grid overlay
11. ✅ **Waterfall** — Spectrum history display, frequency vs time heatmap
12. ✅ **Text LCD** — Multi-line text display with scrolling and word wrap
13. ✅ **Text Input** — Interactive parameter entry with validation
14. ✅ **Gauge Cluster** — Multi-meter dashboard (V/I/P triplets, battery cells)
15. ✅ **Compass** — Directional indicator (0-360°) for satellite/antenna tracking
16. ✅ **Smith Chart** — Complex impedance visualization with 4 traces, SWR circles, VNA integration

**Infrastructure:**
- ✅ **BenchView** — Multi-instrument panel manager with YAML config, iframe grid, HTTP/WebSocket proxy
- ✅ **Python drivers** — Complete for all 16 instruments, ready for PyPI publication

**Still needed (from integration project requirements):**
- 💭 Map widget (GPS track overlay with maps.n0gq.org integration)
- 💭 GPS status display (comprehensive gpsd telemetry dashboard)

## Quick Start

### Single Instrument

```bash
# Start analog meter backend
cd analog-meter/backend
python3 server-multi.py --scpi-port 5025 --http-port 8000 --count 2 --layout ROW

# Open browser
http://localhost:8000

# Control via SCPI
echo "CONF1:LAB TX Power" | nc localhost 5025
echo "CONF1:UNIT W" | nc localhost 5025
echo "CONF1:MIN 0" | nc localhost 5025
echo "CONF1:MAX 100" | nc localhost 5025
echo "MEAS1:VAL 45.3" | nc localhost 5025
```

### Multi-Instrument Panel (BenchView)

```bash
# Start BenchView with demo config
cd benchview/backend
python3 benchview.py configs/demo-panel.yaml --port 8350

# Open browser
http://localhost:8350
# See 3×3 grid with 5 instruments (2 meters, 4 LEDs, 3 bar graphs, 2 displays, 1 knob)

# Run demo animation
python3 demo-quick.py
# 30-second scripted animation of all instruments
```

### Python Automation

```bash
# Install driver (or use from source)
cd ~/Dropbox/build/rf-bench/drivers/virtual-analog-meter
pip install -e .

# Python script
python3 << 'EOF'
from rf_bench.virtual import VirtualAnalogMeter
import time

with VirtualAnalogMeter("localhost") as meter:
    meter.set_count(2)
    meter.configure(1, "TX Power", "W", 0, 100)
    meter.configure(2, "Voltage", "V", 0, 15)
    
    for i in range(10):
        meter.set_value(1, 45 + i)
        meter.set_value(2, 13.8 + i * 0.01)
        time.sleep(0.5)
EOF
```

## Architecture

### Backend (Python FastAPI)

Each instrument type has a `server-multi.py` backend:

- **SCPI TCP Server** (default port 5025) — IEEE 488.2 commands + instrument-specific SCPI
- **HTTP Server** — Serves frontend HTML/CSS/JS
- **WebSocket Server** — Real-time bidirectional updates
- **Multi-instance support** — 1-4 sub-instruments per backend (e.g., 4 LEDs on one server)
- **1-based indexing** — SCPI uses MEAS1, MEAS2, MEAS3, MEAS4 (not 0-based)
- **Layout control** — ROW, COL, or 2X2 grid arrangements

### Frontend (HTML5 Canvas + WebSocket)

Pure JavaScript, no build step required:

- **Canvas rendering** — All graphics drawn with Canvas 2D API
- **WebSocket client** — Auto-reconnect, real-time state updates
- **No frameworks** — Vanilla JS, minimal dependencies
- **Query params** — `?count=2&layout=row&ws_port=8000` configures display

### Python Drivers

Complete SCPI-over-TCP client libraries in `~/Dropbox/build/rf-bench/drivers/virtual-*/`:

- **Namespace package** — All drivers in `rf_bench.virtual.*`
- **Context manager support** — Use with `with` statement
- **IEEE 488.2 commands** — `*IDN?`, `*RST`, `SYST:ERR?`
- **Type hints** — Full type annotations
- **Comprehensive docs** — 280-400 line READMEs with examples

## Instrument Details

### Analog Meter

**Files:** `analog-meter/backend/server-multi.py`, `analog-meter/frontend/index-multi.html`  
**Driver:** `rf_bench.virtual.VirtualAnalogMeter`  
**SCPI commands:** `MEAS<N>:VAL`, `CONF<N>:MIN/MAX/UNIT/LAB/COL`

**Features:**
- 270° arc sweep (135° to 405°, SW to NE)
- Spring-damper needle physics (realistic overshoot and settling)
- 3 colored zones: green (0-70%), yellow (70-85%), red (85-100%)
- 11 tick marks with numeric labels
- Center value readout + units
- Configurable min/max range

**Use cases:** Power meter, S-meter, voltage/current monitor, SWR display

### LED Indicator

**Files:** `led/backend/server-multi.py`, `led/frontend/index-multi.html`  
**Driver:** `rf_bench.virtual.VirtualLED`  
**SCPI commands:** `LED<N>:STATE`, `LED<N>:COL`, `LED<N>:LAB`, `LED<N>:BLINK`

**Features:**
- On/off/toggle states
- Customizable on/off colors (CSS color strings)
- Blink mode (configurable rate in ms)
- CSS glow effects
- Configurable size

**Use cases:** PTT indicator, status light, alarm, connection state

### 7-Segment Numeric Display

**Files:** `numeric-display/backend/server-multi.py`, `numeric-display/frontend/index-multi.html`  
**Driver:** `rf_bench.virtual.VirtualNumericDisplay`  
**SCPI commands:** `DISP<N>:VAL`, `DISP<N>:UNIT`, `DISP<N>:LAB`, `DISP<N>:COL`, `DISP<N>:PREC`

**Features:**
- DSEG7 Classic font (authentic 7-segment LED look)
- Configurable precision (decimal places)
- Units display
- Customizable text color
- Auto-sizing based on container

**Use cases:** Frequency display, voltage/current readout, timer, counter

### Bar Graph / Level Meter

**Files:** `bar-graph/backend/server-multi.py`, `bar-graph/frontend/index-multi.html`  
**Driver:** `rf_bench.virtual.VirtualBarGraph`  
**SCPI commands:** `BAR<N>:VAL`, `BAR<N>:MIN/MAX`, `BAR<N>:UNIT`, `BAR<N>:LAB`, `BAR<N>:COL`

**Features:**
- Vertical bar with smooth fill animation
- Colored zones (green/yellow/red)
- Min/max range with tick marks
- Value display at top
- Units display

**Use cases:** Signal strength, audio level, battery charge, power level

### Rotary Knob

**Files:** `knob/backend/server-multi.py`, `knob/frontend/index-multi.html`  
**Driver:** `rf_bench.virtual.VirtualKnob`  
**SCPI commands:** `KNOB<N>:VAL`, `KNOB<N>:MIN/MAX`, `KNOB<N>:LAB`

**Features:**
- 270° rotation range
- Pointer/indicator line
- Value display in center
- Min/max labels at endpoints
- Smooth rotation animation

**Use cases:** Volume control display, frequency tuning indicator, gain setting

### Linear Slider

**Files:** `slider/backend/server-multi.py`, `slider/frontend/index-multi.html`  
**Driver:** `rf_bench.virtual.VirtualSlider`  
**SCPI commands:** `SLID<N>:VAL`, `SLID<N>:MIN/MAX`, `SLID<N>:LAB`

**Features:**
- Horizontal slider track
- Draggable thumb (display only, not interactive in Phase 1)
- Value display
- Min/max range with tick marks
- Smooth motion animation

**Use cases:** Power level indicator, frequency offset, balance/pan display

### Momentary Push Button

**Files:** `button/backend/server-multi.py`, `button/frontend/index-multi.html`  
**Driver:** `rf_bench.virtual.VirtualButton`  
**SCPI commands:** `BUTT<N>:STATE`, `BUTT<N>:LAB`

**Features:**
- Press animation (depth effect)
- On/off state colors
- Label text
- Shadow effects

**Use cases:** PTT display, transmit indicator, alarm acknowledge state

### Toggle Switch

**Files:** `toggle/backend/server-multi.py`, `toggle/frontend/index-multi.html`  
**Driver:** `rf_bench.virtual.VirtualToggle`  
**SCPI commands:** `TOGG<N>:STATE`, `TOGG<N>:LAB`

**Features:**
- Flip animation between on/off
- Two-position switch visualization
- On/off state colors
- Label text

**Use cases:** Mode indicator, bypass state, mute/unmute, enable/disable

## BenchView — Multi-Instrument Panel Manager

**Files:** `benchview/backend/benchview.py`, `benchview/backend/configs/*.yaml`  
**Purpose:** Manage multiple virtual instruments in a single web page with grid layout

### Features

- **YAML configuration** — Define grid size, instrument types, positions, counts
- **Dynamic port assignment** — Automatically assigns unique SCPI/HTTP ports
- **Iframe grid layout** — CSS Grid for responsive instrument arrangement
- **HTTP/WebSocket proxy** — All traffic routed through BenchView, bypasses firewall
- **CSS injection** — Fixes iframe sizing, font loading, adds disconnection overlay
- **Red X overlay** — Visual indicator when instrument backend disconnects
- **Process management** — Starts/stops all backend servers automatically

### Configuration File Format

```yaml
panel:
  name: "RF Bench Demo Panel"
  description: "Multi-instrument dashboard example"
  grid:
    columns: 3
    rows: 3
    gap: "10px"
  instruments:
    - name: power-meter          # Unique identifier
      type: analog-meter         # Instrument type
      count: 2                   # 2 meters
      layout: ROW                # Side-by-side
      position: {row: 0, col: 0}
      span: {rows: 1, cols: 2}

    - name: ptt-led
      type: led
      count: 4
      layout: 2X2                # 2×2 grid
      position: {row: 0, col: 2}
      span: {rows: 1, cols: 1}
```

### Demo Configs

- **demo-panel.yaml** — 3×3 grid with 5 instruments (meters, LEDs, bars, displays, knob)
- **demo-quick.py** — 30-second scripted animation of all instruments
- **demo_2x2.yaml** — Compact 2×2 layout
- **demo_flight.yaml** — Aviation instruments (airspeed, altitude, heading, VSI)

## Python Driver API

All 16 drivers share a common interface:

```python
from rf_bench.virtual import (
    VirtualAnalogMeter,
    VirtualLED,
    VirtualNumericDisplay,
    VirtualBarGraph,
    VirtualKnob,
    VirtualSlider,
    VirtualButton,
    VirtualToggle,
    VirtualLineChart,
    VirtualXYPlot,
    VirtualWaterfall,
    VirtualTextLCD,
    VirtualTextInput,
    VirtualGaugeCluster,
    VirtualCompass,
    VirtualSmithChart
)

# Connection
instrument = VirtualAnalogMeter(host="localhost", port=5025, timeout=2.0)

# IEEE 488.2 common commands
instrument.idn()           # → "N0GQ,Virtual-Analog-Meter-Multi,1.0,2026"
instrument.reset()         # Reset to defaults
instrument.get_error()     # → "0,No error"

# Multi-instance management
instrument.set_count(2)    # Display 2 meters
instrument.get_count()     # → 2
instrument.set_layout("ROW")
instrument.get_layout()    # → "ROW"

# Instrument-specific commands (vary by type)
# See individual driver READMEs for full API
```

### Example: Power Monitor

```python
from rf_bench.virtual import VirtualAnalogMeter, VirtualLED
from rf_bench.siglent import SPD3303X
import time

psu = SPD3303X("10.1.1.56")
meter = VirtualAnalogMeter("10.1.1.52")
led = VirtualLED("10.1.1.53")

meter.configure(1, "Voltage", "V", 0, 15)
meter.configure(2, "Current", "A", 0, 3)
led.configure(1, label="PSU ON", on_color="#00ff00")

psu.set_voltage(1, 13.8)
psu.set_current(1, 2.0)
psu.enable(1)
led.on(1)

while True:
    v = psu.measure_voltage(1)
    i = psu.measure_current(1)
    meter.set_value(1, v)
    meter.set_value(2, i)
    time.sleep(0.5)
```

## SCPI Command Reference

### IEEE 488.2 Common Commands (all instruments)

- `*IDN?` — Identification query
- `*RST` — Reset to defaults
- `SYST:ERR?` — Query error queue

### Multi-Instance Commands (all instruments)

- `INST:COUNT <1-4>` — Set number of sub-instruments
- `INST:COUNT?` — Query count
- `INST:LAY <ROW|COL|2X2>` — Set layout
- `INST:LAY?` — Query layout

### Instrument-Specific Commands

Commands use 1-based indexing (N=1,2,3,4):

**Analog Meter:**
- `MEAS<N>:VAL <float>` / `MEAS<N>:VAL?`
- `CONF<N>:MIN <float>` / `CONF<N>:MAX <float>`
- `CONF<N>:UNIT <string>` / `CONF<N>:LAB <string>` / `CONF<N>:COL <color>`

**LED:**
- `LED<N>:STATE <ON|OFF|TOGGLE>` / `LED<N>:STATE?`
- `LED<N>:COL <on_color>,<off_color>` / `LED<N>:BLINK <ms>`

**Numeric Display:**
- `DISP<N>:VAL <float>` / `DISP<N>:PREC <0-6>`
- `DISP<N>:UNIT <string>` / `DISP<N>:LAB <string>` / `DISP<N>:COL <color>`

**Bar Graph:**
- `BAR<N>:VAL <float>` / `BAR<N>:MIN <float>` / `BAR<N>:MAX <float>`
- `BAR<N>:UNIT <string>` / `BAR<N>:LAB <string>` / `BAR<N>:COL <color>`

(See individual instrument READMEs for complete command reference)

## Integration Examples

### SSA Spectrum Monitor with Analog Meter

```python
from rf_bench.siglent import SSA3000X
from rf_bench.virtual import VirtualAnalogMeter
import time

ssa = SSA3000X("10.1.1.60")
meter = VirtualAnalogMeter("localhost")

meter.configure(1, "Peak Level", "dBm", -50, 10)

ssa.set_center_span(14.2e6, 100e3)
while True:
    ssa.peak_search()
    _, power = ssa.get_peak()
    meter.set_value(1, power)
    time.sleep(0.1)
```

### IC-7300 S-Meter Display

```python
from rf_bench.icom import IC7300
from rf_bench.virtual import VirtualBarGraph
import time

radio = IC7300()
bar = VirtualBarGraph("localhost")

bar.configure(1, "S-Meter", "S", 0, 9)

radio.set_frequency(14_200_000)
radio.set_mode("USB")

while True:
    s_units = radio.get_strength_settled()
    bar.set_value(1, s_units)
    time.sleep(0.2)
```

### Battery Monitor Dashboard

```python
from rf_bench.siglent import SPD3303X
from rf_bench.virtual import VirtualAnalogMeter, VirtualLED, VirtualNumericDisplay
import time

psu = SPD3303X("10.1.1.56")
meter = VirtualAnalogMeter("localhost", port=5025)
led = VirtualLED("localhost", port=5026)
display = VirtualNumericDisplay("localhost", port=5027)

meter.set_count(2)
meter.configure(1, "Voltage", "V", 0, 15)
meter.configure(2, "Current", "A", 0, 3)

led.configure(1, label="CHARGING", on_color="#00ff00")
display.configure(1, label="Power", units="W")

psu.set_voltage(1, 13.8)
psu.set_current(1, 2.0)
psu.enable(1)

while True:
    v = psu.measure_voltage(1)
    i = psu.measure_current(1)
    p = psu.measure_power(1)
    
    meter.set_value(1, v)
    meter.set_value(2, i)
    display.set_value(1, p)
    
    if i > 0.1:
        led.on(1)
    else:
        led.off(1)
    
    time.sleep(0.5)
```

## Development Status

### Phase 1: Read-Only Displays — ✅ COMPLETE

All 16 instruments built, tested, and documented:
- [x] Analog meter
- [x] LED indicator
- [x] 7-segment numeric display
- [x] Bar graph
- [x] Rotary knob
- [x] Linear slider
- [x] Push button
- [x] Toggle switch
- [x] Line chart
- [x] XY plot
- [x] Waterfall
- [x] Text LCD
- [x] Text input
- [x] Gauge cluster
- [x] Compass
- [x] Smith chart
- [x] BenchView panel manager
- [x] Python drivers for all instruments

### Phase 2: Interactive Controls — 💭 FUTURE

Add user interaction to controls:
- [ ] Clickable buttons/toggles (send state changes via WebSocket → backend → SCPI clients)
- [ ] Draggable knobs/sliders (mouse/touch input)
- [ ] Text input fields (frequency, value entry)
- [ ] Bidirectional SCPI (instruments can query/command each other)

### Phase 3: Advanced Features — 💭 FUTURE

- [ ] Line chart / XY plot (time-series data)
- [ ] Waterfall display (spectrum history)
- [ ] Smith chart (impedance display)
- [ ] MQTT integration (pub/sub between instruments)
- [ ] Data logging (SQLite backend)
- [ ] Android app (Kotlin native UI)

## File Structure

```
virtual/
├── analog-meter/
│   ├── backend/
│   │   └── server-multi.py       ← FastAPI + SCPI server
│   ├── frontend/
│   │   └── index-multi.html      ← HTML5 Canvas UI
│   └── README.md                 ← Instrument-specific docs
├── led/
├── numeric-display/
├── bar-graph/
├── knob/
├── slider/
├── button/
├── toggle/
├── benchview/
│   ├── backend/
│   │   ├── benchview.py          ← Multi-panel manager
│   │   ├── demo-quick.py         ← 30-second animation script
│   │   └── configs/
│   │       ├── demo-panel.yaml   ← 3×3 grid config
│   │       ├── demo_2x2.yaml
│   │       └── demo_flight.yaml
│   └── README.md
└── README.md                     ← This file

drivers/
├── virtual-analog-meter/         ← Python driver package
│   ├── rf_bench/virtual/analog_meter.py
│   ├── README.md                 ← Full API docs + examples
│   ├── pyproject.toml
│   └── LICENSE                   ← GPL-3.0-or-later
├── virtual-led/
├── virtual-numeric-display/
├── virtual-bar-graph/
├── virtual-knob/
├── virtual-slider/
├── virtual-button/
└── virtual-toggle/
```

## Requirements

- **Python 3.7+**
- **FastAPI** + **uvicorn** (backend servers)
- **WebSocket support** (browsers, Python `websocket-client`)
- **Modern browser** (Chrome, Firefox, Safari — Canvas 2D + WebSocket)

## License

All virtual instruments and drivers: **GPL-3.0-or-later**  
Author: Jeff Francis (N0GQ) <gjfrancis@protonmail.com>

## See Also

- `~/Dropbox/build/rf-bench/ideas/virtual-instrument-projects.md` — Integration project ideas
- `~/Dropbox/build/rf-bench/ideas/virtual-panels.md` — Panel types and architecture
- `drivers/virtual-*/README.md` — Individual driver documentation
