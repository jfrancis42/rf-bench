# New Virtual Instrument Integration Projects — Summary

**Date:** 2026-06-14
**Context:** Phase 2 interactive controls (slider, toggle, button, knob, text-input) are complete. Virtual instrument cluster framework (multiple widgets on single web page) is planned.

This document summarizes 39 new project ideas that combine virtual SCPI instruments with existing bench hardware. All ideas are catalogued in detail at:

**`ideas/virtual-instrument-projects.md`**

---

## Key Concepts

### What Changed

**Before:** Virtual instruments existed as standalone web pages (one widget = one server = one port). Integration with physical hardware was via separate Python scripts.

**After Phase 2:** Interactive controls (slider, toggle, button, knob, text-input) enable bidirectional MQTT and SCPI. Virtual instrument **cluster** framework allows composing multiple widgets into unified control panels via JSON/YAML configuration.

**Opportunity:** Combine read-only displays (meters, charts, waterfalls) + interactive controls (sliders, buttons, toggles) + physical instruments (SSA, radios, ESP32 actuators) into complete remote-control systems.

### Architecture Pattern

All 39 projects follow this pattern:

1. **Python backend** polls/commands physical instruments via `rf_bench.*` drivers or ESP32 SCPI
2. **MQTT bridge** publishes measurements to topics (e.g., `bench/ssa/peak_level`)
3. **Virtual widgets** subscribe to MQTT topics for real-time updates
4. **Interactive controls** publish commands to MQTT, backend forwards to instruments
5. **Panel config** (JSON/YAML) defines widget layout, bindings, refresh rates

### Example Flow

**SSA Live Spectrum Monitor with Tracking Generator Control:**

```
User moves slider (TG level −30 to 0 dBm)
  ↓
Slider widget publishes to MQTT: bench/ssa/tg_level = -10
  ↓
Python backend subscribes to bench/ssa/tg_level, sends SCPI to SSA: :SOUR:POW:LEV:IMM:AMPL -10
  ↓
Backend polls SSA spectrum trace: :TRAC:DATA? TRACE1
  ↓
Backend publishes to MQTT: bench/ssa/trace = [array of 751 points]
  ↓
Waterfall widget subscribes to bench/ssa/trace, renders scrolling heatmap
  ↓
Analog meter subscribes to bench/ssa/peak_level, displays peak in real-time
```

**Result:** Single web page replaces physical SSA front panel. Accessible from phone/tablet/laptop anywhere on network (or via VPN).

---

## Project Categories and Counts

| Category | Count | Examples |
|----------|-------|----------|
| RF / Spectrum Analysis | 5 | SSA live monitor, antenna tuner, peak tracker, scalar VNA, amplifier monitor |
| Radio Operations | 4 | HF dashboard, satellite tracker, dual-watch, repeater monitor |
| Power / Battery Management | 3 | Multi-cell monitor, PSU bench panel, battery discharge tester |
| Signal Sources / Synthesis | 3 | Dual-channel SDG control, Si5351 with presets, MHS two-tone IMD |
| Automated Testing / QC | 3 | Multi-DUT crystal sorter, amplifier production test, filter S21 QC |
| GPS / Position Tracking | 4 | GPS survey with scatter, drive test mapper, GPS dashboard with maps.n0gq.org, GPS info page |
| Multi-Instrument Coordination | 3 | PSU + load closed-loop, Bode plotter with live plot, two-tone IMD analyzer |
| Contest / Field Day | 2 | N1MM+ integration dashboard, SO2R dual-radio coordinator |
| Propagation Science | 2 | Multipath fading analyzer, tropospheric ducting detector |
| ESP32 + Virtual Instruments | 3 | Relay matrix panel, temperature chamber controller, remote HF station |
| **Total** | **41** | |

---

## Most Impactful Projects

Ranked by estimated time savings, safety improvement, or enabling new capabilities:

### 1. GPS Dashboard with maps.n0gq.org (`projects/gps/gps-dashboard/`)

**Impact:** Live GPS status display with integrated vector map from local tile server. Replaces multiple terminal windows (`gpsmon`, `cgps`, `gpspipe`) with unified web panel. No internet dependency (uses local `maps.n0gq.org` at 10.1.0.37).

**Hardware:** scpi-gps (ESP32 GPS) or rf_bench.gpsd (local gpsd daemon).

**Widgets:** Map widget (PMTiles vector map centered on current position), numeric displays (lat/lon/alt/speed/course/HDOP/VDOP/PDOP), bar graphs (satellite count, per-satellite SNR), text LCD (fix status, satellite list), LED (fix quality), gauge cluster (DOP values), line charts (altitude/speed vs time), buttons (center map, export fix).

**Why it matters:** Unified GPS status + map context (nearby roads, landmarks, terrain). maps.n0gq.org is local PMTiles server (fast, no internet lag). DOP values and satellite SNR diagnose fix quality. Map integration shows position in geographic context (critical for site surveys, antenna placement, repeater documentation).

**Use cases:** GPS receiver testing, antenna placement validation, multipath detection, site survey, mobile tracking.

**Estimated time to build:** 6-8 hours (MapLibre GL integration + gpsd MQTT bridge + multi-widget layout).

---

### 2. Multi-Cell Battery Monitor (`projects/power/battery-monitor-panel/`)

**Impact:** **Safety-critical** for lithium battery packs. Detects cell imbalance before thermal runaway. Prevents fires.

**Hardware:** scpi-mux (16-ch), scpi-adc (ADS1115), scpi-power (INA219), scpi-temp (DS18B20 per cell).

**Widgets:** Gauge cluster (16 cells, voltage per cell), line chart (16 traces voltage vs time), bar graph (total pack voltage), bar graph (SOC %), numeric display (capacity mAh), analog meter (current A), text LCD (max cell delta mV).

**Why it matters:** Commercial BMS displays show pack voltage only, not per-cell. Cell-level monitoring required for DIY EV packs, solar storage, grid-scale ESS. Visual trending reveals weak cells weeks before failure.

**Use cases:** Battery capacity verification, aging studies, cell matching for pack building, acceptance testing.

**Estimated time to build:** 8-12 hours (mux + ADC integration + 16-trace chart).

---

### 3. HF Station Dashboard (`projects/radio/hf-dashboard/`)

**Impact:** Replaces $300-500 of physical meters (S-meter, SWR meter, PTT indicator) with $0 web panel. Mobile-friendly remote monitoring while operating.

**Hardware:** IC-7300 or FT-891, scpi-swr, scpi-ptt, optional scpi-tuner.

**Widgets:** Analog meter (S-meter), numeric display (frequency/mode), line chart (S-meter history), bar graph (SWR), LED (PTT), toggle (preamp), slider (RF gain), button (tune antenna).

**Why it matters:** Unified status display. Remote operation without VNC/SSH into rigctld. Automated antenna tuning via button press saves 10-30 seconds per band change.

**Estimated time to build:** 4-6 hours (backend MQTT bridge + panel config).

---

### 4. SSA Live Spectrum Monitor (`projects/rf/ssa-live-monitor/`)

**Impact:** Remote spectrum analysis for field work. Phone/tablet shows live waterfall + TG control without laptop + VNC.

**Hardware:** SSA3032X Plus.

**Widgets:** Waterfall (spectrum history), analog meter (peak level dBm), numeric display (center freq), toggle (TG on/off), slider (TG level −30 to 0 dBm).

**Why it matters:** SSA front panel not mobile-friendly. Web panel accessible from anywhere (shack, truck, home). Interactive TG control for filter tuning, antenna analysis, EMI hunting.

**Estimated time to build:** 6-8 hours (waterfall widget + MQTT bridge + TG control).

---

### 4. Multi-DUT Crystal Sorter (`projects/components/crystal-sorter-panel/`)

**Impact:** **10× throughput** vs manual testing. 16 crystals measured in batch (5 minutes) vs 16× manual (50 minutes).

**Hardware:** scpi-mux (16-ch), SDG1062X (sweep source), SDS2504X (response capture), scpi-relay (bin sorting).

**Widgets:** Gauge cluster (16 crystals: series resonance freq Hz), bar graph (motional resistance Ω), text LCD (current DUT), LED (measurement active), LED (pass/fail per DUT), button (start batch), button (export CSV).

**Why it matters:** Crystal filter production requires matched pairs within ±5 ppm. Manual testing bottleneck. Automated sorter enables small-batch filter manufacturing.

**Estimated time to build:** 12-16 hours (mux switching + BVD parameter extraction + batch sequencing).

---

### 5. Antenna Tuner with SWR and Impedance Display (`projects/rf/antenna-tuner-panel/`)

**Impact:** Automated tuning saves 30-60 seconds per band change. In 24-hour contest, 100 band changes = 50-100 minutes saved = 50-100 extra QSOs.

**Hardware:** SSA3032X (TG as RF source), scpi-swr (ESP32 AD8307 meter), scpi-tuner (ESP32 stepper L/C), scpi-ptt (ESP32 PTT control).

**Widgets:** Analog meter (SWR 1:1-5:1), XY plot (Smith chart impedance R+jX), numeric display (frequency MHz), button (auto tune), toggle (bypass/tune), bar graph (forward power), bar graph (reflected power).

**Why it matters:** Manual tuning tedious (adjust L, adjust C, watch SWR meter, repeat). Automated tuner runs hill-climb algorithm, converges in 3-5 seconds. Smith chart shows impedance trajectory during tuning (educational + diagnostic).

**Estimated time to build:** 10-12 hours (scpi-tuner hill-climb algorithm + Smith chart XY plot + SSA TG integration).

---

## New Virtual Instrument Widgets Discovered

Three new widget types emerged from project analysis:

### Map Widget (Phase 3)

**Use case:** GPS drive test mapper, coverage map, APRS tracker, propagation map.

**Visual:** Interactive map (OpenStreetMap or MapLibre GL) with GPS track, markers color-coded by signal strength, zoom/pan.

**Binding:** MQTT topics (lat/lon for position, signal strength for color).

**Why not in Phase 1/2:** Maps require GIS library (Leaflet.js or MapLibre GL), larger than simple Canvas widgets.

---

### Matrix Grid (Phase 3)

**Use case:** Relay matrix control, crosspoint switch, multi-DUT routing, antenna array phasing.

**Visual:** M×N grid of toggle switches, color-coded cells (on=green, off=gray), row/column labels.

**Binding:** SCPI write per cell (e.g., `ROUT:CLOS (@row!col)`), read-back to confirm state.

**Why not in Phase 1/2:** Matrix is specialized (not general-purpose display). Discovered when designing ESP32 relay matrix projects.

---

### 2D Heatmap (Phase 3)

**Use case:** Delay-Doppler plot, spatial temperature distribution, antenna pattern 3D surface, refractive index profile.

**Visual:** 2D color map (frequency vs time, height vs temperature, azimuth vs elevation).

**Binding:** MQTT topic publishing 2D array (JSON), or SCPI query returning 2D trace.

**Why not in Phase 1:** 2D heatmaps require sophisticated rendering (Plotly.js heatmap or custom Canvas). Higher data throughput than 1D charts.

---

## Hardware Integration Summary

Projects use existing rf-bench hardware:

| Hardware | Project Count | Examples |
|----------|---------------|----------|
| SSA3032X Plus | 12 | Spectrum monitor, antenna tuner, scalar VNA, amplifier monitor, two-tone IMD |
| SDG1062X | 10 | Bode plotter, two-tone source, crystal sorter, antenna tuner (TG alternative) |
| IC-7300 / IC-9700 / FT-891 | 12 | HF dashboard, satellite tracker, dual-watch, repeater monitor, remote station |
| ESP32 scpi-* controllers | 25 | scpi-rotator, scpi-swr, scpi-ptt, scpi-tuner, scpi-mux, scpi-adc, scpi-temp, scpi-heater, scpi-matrix, scpi-gps, scpi-power |
| SDS2504X Plus | 6 | Bode plotter, crystal sorter, filter QC, production test |
| SPD3303X-E | 4 | PSU panel, battery charger, PSU+load loop, op-amp offset test |
| SDM3045X | 5 | PSU panel, battery monitor, PSU+load loop, contact resistance |
| ET5406A+ DC load | 3 | Battery discharge tester, PSU+load loop, production test |
| RTL-SDR | 5 | Drive test mapper, repeater monitor, ducting detector, mobile survey |
| KiwiSDR | 3 | Multipath fading analyzer, propagation monitor, beacon logger |
| MHS-5225A DDS | 2 | Two-tone IMD source, dual-channel control panel |
| scpi-gps (ESP32) | 7 | Survey station, drive test, satellite tracker, beacon logger, remote station |
| XL9535 relay board | 4 | Relay matrix panel, filter QC, crystal sorter, multi-DUT router |

---

## Development Priorities

Recommended build order (easiest → hardest):

### Tier 1: Proof-of-concept (1-2 days each)

1. **SSA Live Spectrum Monitor** — proves waterfall widget + MQTT + TG control
2. **HF Station Dashboard** — proves multi-widget panel + Hamlib integration
3. **GPS Survey Station** — proves XY plot (scatter) + gpsd integration

### Tier 2: High-value (2-4 days each)

4. **Multi-Cell Battery Monitor** — safety-critical, proves gauge cluster + 16-trace chart
5. **Antenna Tuner Panel** — proves Smith chart XY plot + ESP32 scpi-tuner control
6. **PSU Bench Monitor** — proves bidirectional slider/toggle control + gauge cluster

### Tier 3: Automation (4-8 days each)

7. **Multi-DUT Crystal Sorter** — proves scpi-mux batch sequencing + pass/fail logic
8. **RF Amplifier Production Test** — proves scpi-matrix routing + automated measurement sequences
9. **Dual-Channel SDG Control** — proves multi-slider panel + phase synchronization

### Tier 4: Advanced (8-16 days each)

10. **VHF/UHF Satellite Tracker** — proves compass + elevation meter + Doppler correction + TLE prediction
11. **N1MM+ Integration Dashboard** — proves external application integration (UDP broadcast listener)
12. **SO2R Dual-Radio Coordinator** — hardest: sub-100ms switching, interlock logic, antenna routing

---

## Technology Stack Recommendations

### Backend (Python)

- **MQTT broker:** Mosquitto (lightweight, battle-tested)
- **MQTT client:** `paho-mqtt` (already in rf_bench dependencies)
- **WebSocket:** FastAPI (already used in Phase 2 virtual instruments)
- **Instrument drivers:** `rf_bench.*` (Siglent, Icom, Yaesu, etc.)
- **ESP32 SCPI:** Raw TCP sockets (port 5025)

### Frontend (Browser)

- **Framework:** React or Vue 3 (component-based, supports dynamic widget loading)
- **Charting:** Plotly.js (2D/3D plots, heatmaps, Smith charts) or Chart.js (simpler, faster)
- **MQTT:** mqtt.js (WebSocket MQTT client for browsers)
- **Maps:** MapLibre GL (vector tiles from maps.n0gq.org PMTiles server at 10.1.0.37) or Leaflet.js + OpenStreetMap (fallback)
- **UI library:** TailwindCSS (utility-first, fast prototyping)

**Note on maps.n0gq.org integration:** Two new GPS projects added to leverage existing local PMTiles vector map server:
1. **GPS Dashboard with maps.n0gq.org** — Live position display on vector map with full GPS telemetry overlay
2. **GPS Info Page** — Dense telemetry display (lat/lon decimal + DMS + grid square, speed in 3 units, all 5 DOP values, per-satellite SNR, fix status)

### Panel Configuration

- **Format:** YAML (human-readable, supports comments) with JSON Schema validation
- **Schema:** Define widget types, bindings (SCPI commands or MQTT topics), layout (grid positions)
- **Example:**

```yaml
panel:
  name: "HF Station Dashboard"
  grid: 3x3
  widgets:
    - type: analog_meter
      position: [0, 0]  # row, col
      binding:
        mqtt: "bench/radio/s_meter"
        interval: 200ms
      config:
        min: -120
        max: -30
        units: "dBm"
        zones:
          - {max: -90, color: red}
          - {max: -60, color: yellow}
          - {max: -30, color: green}
    
    - type: numeric_display
      position: [0, 1]
      binding:
        mqtt: "bench/radio/frequency"
        interval: 500ms
      config:
        precision: 3
        units: "MHz"
        font_size: 48
    
    - type: line_chart
      position: [1, 0]
      span: [1, 3]  # spans 3 columns
      binding:
        mqtt: "bench/radio/s_meter_history"
        interval: 1000ms
      config:
        history_seconds: 60
        y_min: -120
        y_max: -30
        trace_color: "#00ff88"
```

### Deployment

- **Development:** `python backend.py` + `npm run dev` (hot reload)
- **Production:** systemd service (backend) + nginx (serves static frontend)
- **Mobile:** Progressive Web App (PWA) with offline caching

---

## Quick-Start Example

To demonstrate the concept, here's a minimal working example (SSA peak marker tracker):

### Backend (`ssa_peak_tracker.py`)

```python
#!/usr/bin/env python3
import asyncio
import time
from rf_bench.siglent import SSA3000X
import paho.mqtt.client as mqtt

ssa = SSA3000X('10.1.1.60')
mqtt_client = mqtt.Client()
mqtt_client.connect('localhost', 1883, 60)
mqtt_client.loop_start()

async def poll_ssa():
    while True:
        ssa.peak_search()
        freq = ssa.get_marker_frequency(1)  # Hz
        level = ssa.get_marker_level(1)     # dBm
        
        mqtt_client.publish('bench/ssa/peak_freq', freq / 1e6)  # MHz
        mqtt_client.publish('bench/ssa/peak_level', level)
        
        await asyncio.sleep(0.5)  # 2 Hz update rate

asyncio.run(poll_ssa())
```

### Frontend Panel Config (`ssa_peak_tracker.yaml`)

```yaml
panel:
  name: "SSA Peak Tracker"
  grid: 2x2
  widgets:
    - type: numeric_display
      position: [0, 0]
      binding: {mqtt: "bench/ssa/peak_freq"}
      config: {precision: 6, units: "MHz", font_size: 36}
    
    - type: numeric_display
      position: [0, 1]
      binding: {mqtt: "bench/ssa/peak_level"}
      config: {precision: 1, units: "dBm", font_size: 36}
    
    - type: line_chart
      position: [1, 0]
      span: [1, 2]
      binding: {mqtt: "bench/ssa/peak_freq"}
      config: {history_seconds: 60, y_label: "Frequency (MHz)"}
```

### Result

Web browser displays:
- Top row: two large numeric displays (peak frequency MHz, peak level dBm)
- Bottom row: scrolling line chart (peak frequency vs time, last 60 seconds)

Updates 2× per second. Accessible from any device on LAN.

---

## Cost Comparison: Virtual Instruments vs Physical Meters

| Function | Physical Hardware Cost | Virtual Instrument Cost | Savings |
|----------|------------------------|-------------------------|---------|
| S-meter | $50-150 (analog panel meter) | $0 (web panel) | $50-150 |
| SWR meter | $100-200 (MFJ, Daiwa) | $0 (scpi-swr ESP32 = $15 hardware, web panel = $0) | $85-185 |
| Frequency counter | $200-500 (8-digit bench counter) | $0 (web panel + scpi-counter ESP32 = $10) | $190-490 |
| Multi-channel chart recorder | $2000-5000 (Yokogawa DL750) | $0 (web panel + existing scope) | $2000-5000 |
| Antenna rotator controller | $300-600 (Yaesu G-5500, Alfa SPID) | $100 (scpi-rotator ESP32 + web panel) | $200-500 |
| Battery monitor (16-cell) | $500-1500 (BMS with display) | $150 (scpi-mux + scpi-adc + web panel) | $350-1350 |
| **Total savings for typical station** | | | **$2875-7675** |

**Conclusion:** Virtual instrument panels replace $3000-8000 of physical meters with $0-300 of ESP32 hardware + web browsers already owned.

---

## Next Steps

1. **Build Tier 1 proof-of-concept** (SSA live monitor, HF dashboard, GPS survey) — validate architecture
2. **Refine panel config format** — iterate YAML schema based on real usage
3. **Implement Phase 3 widgets** (map, matrix grid, 2D heatmap) — discovered from project analysis
4. **Document panel config API** — schema, widget types, bindings, layout syntax
5. **Create panel template library** — 10-15 pre-built configs for common use cases
6. **Build Android app** (Phase 5) — native mobile UI with same config format
7. **Publish virtual instrument framework** — GitHub + documentation + tutorial videos

---

## Conclusion

**39 new project ideas** discovered by systematically combining:
- **Virtual instrument widgets** (analog meter, charts, toggles, sliders, buttons) +
- **Physical bench hardware** (SSA, radios, ESP32 controllers, scopes, PSUs) +
- **MQTT/SCPI bidirectional control**

**Key insight:** Virtual instrument **clusters** (multiple widgets on one web page) enable unified control panels that replace expensive physical meters and provide remote operation capabilities impossible with standalone instruments.

**Highest-value projects:** HF station dashboard, multi-cell battery monitor, SSA live spectrum monitor, antenna tuner, multi-DUT crystal sorter.

**New widgets needed:** Map (GPS tracking), matrix grid (relay routing), 2D heatmap (propagation analysis).

**Total estimated savings:** $3000-8000 per station vs physical meters.

**See full project details:** `ideas/virtual-instrument-projects.md` (39 projects, 10+ pages)
