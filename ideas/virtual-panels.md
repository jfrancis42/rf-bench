## Virtual instrument panels

### Tkinter Desktop Panels

All Tkinter panels share a common architecture (state dataclass +
poll thread + UI refresh loop + thread-safe command queue + `--demo` mode +
safety shutdown on close), and live next to the driver they exercise.

| Panel | Path | Status | Working controls |
|-------|------|--------|------------------|
| SDG1062X | `drivers/siglent/sdg1062x_panel.py` | ✅ | Output on/off per ch, waveform, frequency, level |
| SDM3045X | `drivers/siglent/sdm3045x_panel.py` | ✅ | All measurement functions (VDC/VAC/IDC/IAC/2W/4W Ω/FREQ/DIODE/CONT) |
| SPD3303X | `drivers/siglent/spd3303x_panel.py` | ✅ | Output on/off per ch, tracking mode (INDEP/SERIES/PARA), V and I setpoints |
| SSA3032X | `virtual-instruments/ssa3032x_panel.py` | ✅ | Live spectrum trace; tracking gen on/off + level; markers; peak search |
| SDS2504X | `virtual-instruments/sds2504x_panel.py` | ✅ | 4-channel waveform plot; timebase / V/div / trigger / on-off; Vpp / freq / RMS readouts |
| ET5406A+ | `drivers/yertai/et5406a_panel.py` | ✅ | Mode (CC/CV/CP/CR/CC-CV), input on/off, set points; demo mode |
| IC-7300 | `drivers/icom/ic7300_panel.py` | ✅ | Mode, AGC, frequency entry, band buttons (160m–10m); blue/amber Icom theme |
| FT-891 | `drivers/yaesu/ft891_panel.py` | ✅ | Mode, AGC, preamp, attenuator, frequency, bands; green Yaesu theme |
| RTL-SDR | `drivers/rtlsdr/rtlsdr_panel.py` | ✅ | Live waterfall + FFT |
| Flipper | `drivers/flipper/flipper_panel.py` | ✅ | Multi-tab: Sub-GHz / IR / RFID-NFC / GPIO |
| Si5351 | `projects/signal-sources/si5351-gen/si5351_panel.py` | ✅ | 3-channel freq + drive strength; Tkinter alternative to the curses TUI |

All panels accept `--demo` (no hardware required) for UI testing and `--interval MS` for refresh rate. All panels that command outputs (PSU, load, function gen, radios) safely disable the output on window close.

### Web-Based Virtual SCPI Instruments (Phase 1 — COMPLETE ✅)

HTML5 Canvas instruments with SCPI-over-TCP backends. Multi-instrument panels managed by BenchView.

| Instrument | Backend | Frontend | Status |
|------------|---------|----------|--------|
| Analog meter | `virtual/analog-meter/backend/server-multi.py` | HTML5 Canvas, 270° arc, spring-damper physics | ✅ |
| LED indicator | `virtual/led/backend/server-multi.py` | HTML5 Canvas, on/off/blink, custom colors | ✅ |
| 7-segment display | `virtual/numeric-display/backend/server-multi.py` | HTML5 Canvas, DSEG7 font | ✅ |
| Bar graph | `virtual/bar-graph/backend/server-multi.py` | HTML5 Canvas, colored zones | ✅ |
| Rotary knob | `virtual/knob/backend/server-multi.py` | HTML5 Canvas, rotation animation | ✅ |
| Linear slider | `virtual/slider/backend/server-multi.py` | HTML5 Canvas, smooth motion | ✅ |
| Push button | `virtual/button/backend/server-multi.py` | HTML5 Canvas, press animation | ✅ |
| Toggle switch | `virtual/toggle/backend/server-multi.py` | HTML5 Canvas, flip animation | ✅ |
| **BenchView** | `virtual/benchview/backend/benchview.py` | Multi-instrument panel manager, YAML config | ✅ |

**Architecture:**
- **SCPI:** Port 5025 (default), 1-based indexing (MEAS1, MEAS2, etc.), IEEE 488.2 commands
- **WebSocket:** Real-time bidirectional updates, auto-reconnect
- **Multi-instance:** 1-4 sub-instruments per backend (e.g., 2 meters on one server)
- **Layouts:** ROW, COL, 2X2 grid arrangements
- **Python drivers:** Complete `rf_bench.virtual` packages for automation (353-472 lines each)

**Usage:**
```bash
# Start backend
cd virtual/analog-meter/backend
python3 server-multi.py --scpi-port 5025 --http-port 8000 --count 2 --layout ROW

# Python automation
from rf_bench.virtual import VirtualAnalogMeter
with VirtualAnalogMeter("10.1.1.52") as meter:
    meter.configure(1, "TX Power", "W", 0, 100)
    meter.set_value(1, 45.3)

# BenchView multi-panel
cd virtual/benchview/backend
python3 benchview.py configs/demo-panel.yaml --port 8350
# Open http://localhost:8350 for 3×3 grid with 5 instruments
```

---

