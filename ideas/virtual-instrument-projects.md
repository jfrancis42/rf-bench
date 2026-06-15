# Virtual Instrument Integration Projects

**Phase 1 Status:** ✅ **COMPLETE** — All 8 virtual instruments built and tested with Python drivers

**Built instruments:**
- Analog meter (270° arc, spring-damper physics)
- LED indicator (on/off/blink, custom colors)
- 7-segment numeric display (DSEG7 font)
- Bar graph / level meter (colored zones)
- Rotary knob control
- Linear slider control
- Momentary push button
- Toggle switch

**BenchView:** ✅ Multi-instrument panel manager with iframe grid, HTTP/WebSocket proxy, dynamic port assignment

**Drivers:** ✅ Complete Python SCPI-over-TCP libraries for all 8 instruments (`rf_bench.virtual` namespace)

**Backend:** ✅ FastAPI servers with SCPI TCP (port 5025), WebSocket, multi-instance support (1-4 sub-instruments, 1-based indexing)

**Frontend:** ✅ HTML5 Canvas + WebSocket, real-time updates, no build step required

---

Projects below combine these virtual instruments with existing bench hardware. All projects are 💭 ideas (not yet started) that demonstrate integration patterns.

All virtual instruments expose SCPI TCP servers (port 5025), HTTP/WebSocket for browsers. BenchView loads YAML panel configs that define widget layout, instrument assignments, and refresh rates.

---

## Table of Contents

1. [RF / Spectrum Analysis](#rf--spectrum-analysis)
2. [Radio Operations](#radio-operations)
3. [Power / Battery Management](#power--battery-management)
4. [Signal Sources / Synthesis](#signal-sources--synthesis)
5. [Automated Testing / QC](#automated-testing--qc)
6. [GPS / Position Tracking](#gps--position-tracking)
7. [Multi-Instrument Coordination](#multi-instrument-coordination)
8. [Contest / Field Day](#contest--field-day)
9. [Propagation Science](#propagation-science)
10. [ESP32 + Virtual Instruments](#esp32--virtual-instruments)

---

## RF / Spectrum Analysis

### SSA Live Spectrum Monitor with Tracking Generator Control

`projects/rf/ssa-live-monitor/` — 💭 not started.

**Virtual instruments:** Waterfall display (spectrum trace history), analog meter (peak level dBm), numeric display (center frequency), toggle (tracking generator on/off), slider (TG output level −30 to 0 dBm).

**Hardware:** SSA3032X Plus.

**What it does:** Live spectrum waterfall with interactive TG control. User adjusts TG level via slider, toggles TG on/off via toggle switch, watches spectrum response in real-time. Analog meter shows peak marker level. Numeric display shows center frequency (can be controlled from SSA front panel or via text-input widget).

**Why:** Combines passive monitoring (waterfall, meter) with active control (TG toggle, level slider). Single web page replaces physical SSA front panel for remote operation. Mobile-friendly for field work.

**Python backend:** Polls SSA trace data (`TRAC:DATA? TRACE1`) at ~10 Hz, publishes to MQTT `bench/ssa/trace`. Commands from slider/toggle write to SSA via SCPI. Waterfall widget subscribes to `bench/ssa/trace`, meter subscribes to `bench/ssa/peak_level`.

**Panel layout:** Waterfall full-width top half, meter + frequency display middle, TG toggle + level slider bottom.

---

### Antenna Tuner with SWR and Impedance Display

`projects/rf/antenna-tuner-panel/` — 💭 not started.

**Virtual instruments:** Analog meter (SWR 1:1–5:1), XY plot (Smith chart impedance), numeric display (frequency MHz), button (Auto Tune), toggle (bypass/tune mode), bar graph (forward power), bar graph (reflected power).

**Hardware:** SSA3032X Plus (tracking generator as RF source), scpi-swr (ESP32 AD8307 SWR meter), scpi-tuner (ESP32 stepper motor L/C tuner), scpi-ptt (ESP32 PTT control).

**What it does:** Full antenna tuner control panel. User presses "Auto Tune" button → backend keys radio via scpi-ptt, enables SSA TG at specified frequency, reads SWR from scpi-swr, commands scpi-tuner to step L/C until SWR < 1.5:1, unkeys. Smith chart plots impedance (R + jX) computed from forward/reflected power. Analog meter shows real-time SWR during manual adjustment.

**Why:** Replaces dedicated tuner display with web-based panel accessible from anywhere. Smith chart provides impedance visualization impossible on typical analog SWR meters. Button automation eliminates manual tuning.

**Panel layout:** 2×3 grid. Smith chart top-left (large), SWR meter top-right, numeric frequency + button center, forward/reflected bar graphs bottom, toggle bottom-right.

---

### SSA Peak Marker Tracker with History

`projects/rf/ssa-peak-tracker/` — 💭 not started.

**Virtual instruments:** Line chart (peak frequency vs time), numeric display (current peak frequency MHz), numeric display (current peak level dBm), button (Peak Search), button (Mark), LED (marker active).

**Hardware:** SSA3032X Plus.

**What it does:** Tracks SSA peak marker over time. Backend runs SSA peak search on button press, logs peak frequency + level to SQLite, publishes to MQTT. Line chart scrolls peak frequency vs time (last 60 seconds). "Mark" button flags significant events (user annotation). LED shows whether marker is active.

**Why:** Long-term frequency stability monitoring, oscillator drift tracking, interference source identification. Chart reveals slow frequency changes invisible on static spectrum trace.

**Use cases:** TCXO aging, synthesizer pull-in, Doppler tracking, interference hunting.

**Panel layout:** Line chart full-width top, numeric displays center, buttons + LED bottom row.

---

### Scalar Network Analyzer with Touchstone Export

`projects/rf/scalar-vna-panel/` — 💭 not started.

**Virtual instruments:** Line chart (S11 magnitude dB vs frequency), line chart (S21 magnitude dB vs frequency), numeric display (start freq MHz), numeric display (stop freq MHz), slider (number of points 11-751), button (Sweep), button (Save .s2p), toggle (normalize on/off).

**Hardware:** SSA3032X Plus + RB3X25 reflection bridge (for S11), SDG1062X or SSA TG (for S21 source).

**What it does:** Automated scalar network analyzer. User sets start/stop frequencies via numeric inputs (or existing `projects/rf/scalar-vna/` script sets them), presses "Sweep" → backend runs frequency sweep with SSA, plots S11 and S21 on separate line charts. "Save .s2p" button writes Touchstone file (magnitude only, phase = 0). Toggle enables/disables through-normalization.

**Why:** Visual feedback during sweep. Remote operation without SSH. Touchstone export for use in other tools (SimSmith, Qucs, ADS). Slider allows trading speed vs resolution.

**Panel layout:** Two line charts stacked vertically (top half S11, bottom half S21), controls in bottom strip.

---

### RF Amplifier Gain and P1dB Monitor

`projects/rf/amp-monitor/` — 💭 not started.

**Virtual instruments:** Analog meter (gain dB), numeric display (P1dB dBm), line chart (gain vs frequency), bar graph (current input power dBm), slider (input power −40 to +10 dBm), button (Measure P1dB).

**Hardware:** SSA3032X Plus (measures output), SDG1062X (input source), 30 dB pad (between amplifier and SSA input).

**What it does:** Real-time amplifier monitoring. Slider controls SDG output level, SSA measures amplifier output, backend computes gain = output − input. Line chart plots gain vs frequency during sweep. "Measure P1dB" button runs automated compression test (sweep input power until gain drops 1 dB).

**Why:** Live gain monitoring during alignment or temperature cycling. P1dB button automates tedious manual compression testing. Bar graph warns if input power approaches damage threshold.

**Use cases:** Amplifier characterization, thermal testing (gain vs case temp), aging studies, production QC.

**Panel layout:** Gain meter + P1dB display top, line chart middle, input power slider + button bottom.

---

## Radio Operations

### HF Station Dashboard (IC-7300 / FT-891)

`projects/radio/hf-dashboard/` — 💭 not started.

**Virtual instruments:** Analog meter (S-meter), numeric display (frequency MHz), numeric display (mode), line chart (S-meter history 60s), bar graph (SWR), LED (PTT active), toggle (preamp on/off), slider (RF gain 0-100%), button (Tune Antenna).

**Hardware:** IC-7300 or FT-891 (via Hamlib rigctld), scpi-swr (ESP32 SWR meter), scpi-ptt (ESP32 PTT sense), scpi-tuner (optional antenna tuner).

**What it does:** Complete HF station status panel. S-meter shows real-time signal strength, frequency/mode read from radio via Hamlib. Line chart tracks S-meter over time (propagation monitoring). SWR bar graph shows antenna match. PTT LED lights red during transmit. Preamp toggle and RF gain slider control receiver front-end. "Tune Antenna" button triggers auto-tuner if connected.

**Why:** Unified web interface for remote station operation. Mobile-friendly (phone in shack shows status while operating). SWR + S-meter + PTT in one view reduces need for separate meters.

**Panel layout:** 3×3 grid. S-meter top-left, frequency + mode top-center, PTT LED top-right. Line chart middle row full-width. SWR bar bottom-left, controls bottom-center/right.

---

### VHF/UHF Satellite Tracker (IC-9700)

`projects/radio/satellite-tracker-panel/` — 💭 not started.

**Virtual instruments:** Compass (antenna azimuth 0-360°), analog meter (antenna elevation 0-90°), numeric display (Doppler shift Hz), line chart (signal strength S-meter), text LCD (pass info: AOS/LOS/max el/satellite name), LED (tracking active), button (Start Track), button (Stop Track).

**Hardware:** IC-9700 (VHF/UHF with Doppler correction via Hamlib), scpi-rotator (ESP32 servo antenna controller), scpi-gps (ESP32 GPS for observer position).

**What it does:** Automated satellite pass tracking. Python backend predicts passes via TLE (AMSAT/SatNOGS), displays next pass info in text LCD. User presses "Start Track" → backend commands scpi-rotator to aim antenna (compass + elevation meter show real-time position), tunes IC-9700 with Doppler correction (numeric display shows offset), logs S-meter to line chart. LED shows tracking status. "Stop Track" returns to idle.

**Why:** Visual confirmation of antenna aiming. Doppler shift monitoring validates prediction accuracy. S-meter chart reveals pass quality (max signal, duration above threshold). Single button replaces complex manual coordination of rotator + radio + Doppler.

**Use cases:** ISS SSTV capture, FM satellite QSOs, weather satellite APT, LEO beacon monitoring.

**Panel layout:** Compass + elevation meter top row, Doppler + S-meter chart middle, text LCD + buttons + LED bottom.

---

### Dual-Watch Monitor (IC-7300 + IC-9700)

`projects/radio/dual-watch/` — 💭 not started.

**Virtual instruments:** Analog meter (HF S-meter), analog meter (VHF S-meter), numeric display (HF frequency), numeric display (VHF frequency), line chart (dual trace: HF + VHF S-meter history), LED (HF PTT), LED (VHF PTT), gauge cluster (HF voltage/current/power), gauge cluster (VHF voltage/current/power).

**Hardware:** IC-7300 (HF), IC-9700 (VHF/UHF), both via Hamlib rigctld.

**What it does:** Simultaneous monitoring of two radios. Separate S-meters for each band. Line chart plots both S-meter traces (different colors) on shared timebase for propagation comparison. PTT LEDs show which radio is transmitting. Gauge clusters show PSU voltage/current/power per radio (if scpi-power monitors each PSU).

**Why:** SO2R (Single Operator Two Radio) monitoring. Cross-band coordination (HF DX + VHF local net). Propagation studies (is 20m opening while 2m is closed?). Power budget monitoring (detect overdraw before breaker trips).

**Panel layout:** Two-column. Left column = HF (meter, freq, LED, gauges). Right column = VHF (meter, freq, LED, gauges). Line chart full-width bottom.

---

### FM Repeater Monitor

`projects/radio/repeater-monitor/` — 💭 not started.

**Virtual instruments:** Analog meter (RSSI/S-meter), numeric display (CTCSS tone Hz), LED (squelch open), LED (CTCSS match), bar graph (audio level dBFS), line chart (RSSI history), text LCD (last 5 callsigns from voice ID or APRS), button (ID Repeater).

**Hardware:** IC-9700 or RTL-SDR (VHF/UHF FM receiver), scpi-gps (optional position logging).

**What it does:** Repeater activity monitor. RSSI meter shows carrier strength, CTCSS display decodes sub-audible tone, squelch LED shows when repeater is active. Audio level bar graph monitors deviation. Line chart tracks RSSI over time (propagation trends). Text LCD logs callsigns from voice IDs or decoded APRS. "ID Repeater" button keys attached transmitter to send ID (if configured).

**Why:** Unattended repeater monitoring (detect outages, interference, unauthorized access). Activity logging for coordination or regulatory compliance. CTCSS validation ensures only authorized tones open squelch.

**Use cases:** Repeater trustee monitoring, interference investigation, skip/ducting detection (distant repeater opens unexpectedly), APRS igate status.

**Panel layout:** Meter + tone display top, LEDs + bar graph middle, line chart + text LCD bottom.

---

## Power / Battery Management

### Multi-Cell Battery Monitor

`projects/power/battery-monitor-panel/` — 💭 not started.

**Virtual instruments:** Gauge cluster (16 cells: voltage per cell 0-4.2V), line chart (voltage vs time, 16 traces), bar graph (total pack voltage 0-67.2V for 16s), bar graph (state of charge 0-100%), numeric display (capacity mAh), analog meter (current A), text LCD (cell balance status: max delta mV).

**Hardware:** scpi-mux (CD4067 16-ch analog mux), scpi-adc (ADS1115 16-bit ADC), scpi-power (INA219 pack current), scpi-temp (DS18B20 per-cell temperature).

**What it does:** Multi-cell lithium battery pack monitoring. scpi-mux cycles through 16 cells, scpi-adc measures each cell voltage, gauge cluster shows per-cell voltage with color coding (green >3.5V, yellow 3.3-3.5V, red <3.3V). Line chart plots all 16 cell voltages vs time (detect imbalance, drift). Total pack voltage bar graph, SOC bar graph (computed from voltage), capacity numeric display (mAh integration from scpi-power current). Text LCD shows max cell delta (mV) to flag balance issues.

**Why:** Lithium pack safety requires per-cell monitoring. Imbalance detection prevents overcharge/overdischarge of individual cells (fire hazard). Visual trending reveals weak cells before failure.

**Use cases:** EV battery pack, solar storage bank, RC aircraft pack qualification, grid-scale ESS monitoring.

**Panel layout:** Gauge cluster left third, line chart center third, pack bars + numeric + meter right third, text LCD bottom strip.

---

### PSU Bench Monitor (SPD3303X-E)

`projects/power/psu-panel/` — 💭 not started.

**Virtual instruments:** Gauge cluster (CH1: V/I/P), gauge cluster (CH2: V/I/P), slider (CH1 voltage 0-32V), slider (CH1 current limit 0-3.2A), slider (CH2 voltage 0-32V), slider (CH2 current limit 0-3.2A), toggle (CH1 output on/off), toggle (CH2 output on/off), toggle (tracking mode: independent/series/parallel), LED (CH1 in current limit), LED (CH2 in current limit), line chart (CH1 + CH2 current vs time).

**Hardware:** SPD3303X-E programmable PSU.

**What it does:** Full PSU remote control. Sliders adjust voltage and current limits per channel. Toggles enable outputs and select tracking mode. Gauge clusters show real-time V/I/P per channel. LEDs indicate constant-current mode (output voltage drooped). Line chart plots current history (detect inrush, oscillation, thermal runaway).

**Why:** Remote PSU control for automated testing or DUT in thermal chamber (PSU outside chamber, only wires enter). Simultaneous V/I/P monitoring eliminates separate DMM. Current-limit LEDs warn of overload. Chart reveals current spikes invisible on DC meters.

**Panel layout:** Two columns (CH1 left, CH2 right). Gauges top, sliders + toggles + LEDs middle, line chart full-width bottom.

---

### Battery Discharge Tester with Live Curves

`projects/power/battery-discharge-panel/` — 💭 not started.

**Virtual instruments:** Line chart (voltage vs time), line chart (current vs time), XY plot (voltage vs capacity mAh), numeric display (capacity mAh), numeric display (energy Wh), numeric display (internal resistance mΩ), analog meter (state of charge 0-100%), bar graph (discharge rate C), toggle (discharge on/off), slider (discharge current 0-20A), button (Measure IR).

**Hardware:** ET5406A+ DC load (or scpi-load ESP32 electronic load), scpi-adc (terminal voltage), scpi-temp (battery temperature).

**What it does:** Automated battery discharge test with live visualization. User sets discharge current via slider, toggles discharge on/off. Backend commands load, logs voltage/current/temperature to SQLite, integrates for capacity (mAh) and energy (Wh). Line charts plot V and I vs time. XY plot shows classic discharge curve (V vs mAh). Numeric displays show running totals. "Measure IR" button pulses load (10A step), measures voltage drop, computes internal resistance (mΩ).

**Why:** Visual feedback during long discharge tests (hours). XY plot reveals battery chemistry (flat plateau = LiFePO4, sloped = Li-ion, exponential = lead-acid). IR measurement validates cell health (high IR = aged cell). Live SOC meter shows progress.

**Use cases:** Battery capacity verification, aging studies, cell matching for pack building, acceptance testing.

**Panel layout:** Two line charts stacked (top half), XY plot bottom-left, numeric displays + meter bottom-center, controls bottom-right.

---

## Signal Sources / Synthesis

### Dual-Channel Function Generator Control (SDG1062X)

`projects/signal-sources/sdg-panel/` — 💭 not started.

**Virtual instruments:** Numeric display (CH1 frequency Hz/kHz/MHz), numeric display (CH2 frequency Hz/kHz/MHz), slider (CH1 amplitude 0-10Vpp), slider (CH2 amplitude 0-10Vpp), slider (CH1 offset ±5V), slider (CH2 offset ±5V), slider (CH1 phase 0-360°), toggle (CH1 output on/off), toggle (CH2 output on/off), toggle (coupling: independent/tracking/inverted), text input (CH1 frequency entry), text input (CH2 frequency entry), button (Apply), button (Sync Phases).

**Hardware:** SDG1062X function generator.

**What it does:** Full SDG remote control. Text inputs allow precise frequency entry (e.g., "14.257 MHz"), button applies settings. Sliders adjust amplitude/offset/phase with live feedback. Toggles enable outputs and set coupling mode. "Sync Phases" button resets both channels to 0° phase (coherent start for two-tone measurements).

**Why:** Eliminates physical access to SDG front panel. Precise frequency entry via keyboard (faster than knob). Phase synchronization critical for IMD testing. Remote control for automated sweeps.

**Panel layout:** Two columns (CH1 left, CH2 right). Frequency displays + text inputs top, sliders middle, toggles + buttons bottom.

---

### Si5351 Synthesizer with Preset Recall

`projects/signal-sources/si5351-panel/` — 💭 not started.

**Virtual instruments:** Numeric display (CLK0 frequency Hz), numeric display (CLK1 frequency Hz), numeric display (CLK2 frequency Hz), slider (CLK0 drive strength 2-8mA), slider (CLK1 drive strength), slider (CLK2 drive strength), toggle (CLK0 enable), toggle (CLK1 enable), toggle (CLK2 enable), text input (CLK0 frequency), text input (CLK1 frequency), text input (CLK2 frequency), button (Preset 1), button (Preset 2), button (Preset 3), button (Save Preset).

**Hardware:** Bus Pirate + Si5351 breakout (existing `projects/signal-sources/si5351-gen/`).

**What it does:** Web-based Si5351 control (alternative to existing Tkinter panel). Text inputs for precise frequency entry. Drive strength sliders adjust output power. Preset buttons recall saved configurations (e.g., "10 MHz ref", "dual-tone 14.257/14.358 MHz", "VHF LO 144 MHz"). "Save Preset" writes current config to JSON.

**Why:** Mobile-friendly control (phone/tablet). Preset recall speeds common tasks (switch between test setups without re-entering frequencies). Web UI more accessible than Tkinter for remote users.

**Panel layout:** 3 columns (one per clock). Frequency display + text input top, slider + toggle middle per column. Preset buttons bottom row.

---

### MHS-5225A Dual-Tone IMD Source

`projects/signal-sources/mhs-two-tone-panel/` — 💭 not started.

**Virtual instruments:** Numeric display (f1 Hz/kHz/MHz), numeric display (f2 Hz/kHz/MHz), numeric display (Δf = f2−f1), slider (f1 amplitude 0-20Vpp), slider (f2 amplitude 0-20Vpp), slider (f1 phase 0-360°), slider (f2 phase 0-360°), toggle (CH1 output), toggle (CH2 output), text input (f1 entry), text input (f2 entry), button (Set Standard Spacing), button (Measure IMD on SSA).

**Hardware:** Koolertron MHS-5225A (dual DDS), resistive combiner (passive 4-port), SSA3032X (measures IMD products).

**What it does:** Two-tone IMD source control. User sets f1 and f2 (typically 100 kHz apart), adjusts amplitudes and phases independently. Numeric display shows Δf (validates spacing). "Set Standard Spacing" button presets common values (100 kHz, 1 MHz). "Measure IMD on SSA" button commands SSA to measure IM3 products at 2f1−f2 and 2f2−f1, displays result in numeric display or text LCD.

**Why:** Manual two-tone setup tedious (requires precise spacing, amplitude balance). Independent phase control required for repeatable IMD (phase-coherent sources give different IMD than independent sources). Automated SSA measurement eliminates marker placement errors.

**Use cases:** Amplifier IP3, mixer IMD, receiver intermodulation, filter intermodulation distortion.

**Panel layout:** Two columns (f1 left, f2 right). Frequency displays + text inputs top, amplitude + phase sliders middle, toggles + buttons bottom.

---

## Automated Testing / QC

### Multi-DUT Crystal Sorter

`projects/components/crystal-sorter-panel/` — 💭 not started.

**Virtual instruments:** Gauge cluster (16 crystals: series resonance frequency Hz), bar graph (per-crystal motional resistance Ω), text LCD (current DUT being measured), LED (measurement in progress), LED (pass/fail per DUT), button (Start Batch), button (Export CSV), numeric display (batch count), numeric display (pass count), numeric display (fail count).

**Hardware:** scpi-mux (16-ch for DUT switching), SDG1062X (sweep source), SDS2504X (response capture, or use scope FFT), scpi-relay (bins DUTs into pass/fail trays).

**What it does:** Automated crystal characterization. scpi-mux switches between 16 crystals sequentially. For each crystal: SDG sweeps frequency around nominal (e.g., 10.000 MHz ±500 Hz), scope captures response, Python backend extracts series resonance frequency (minimum impedance) and motional resistance (BVD model fit). Gauge cluster shows measured frequency per crystal with color coding (green within ±10 ppm, yellow ±10-50 ppm, red >50 ppm). Pass/fail LEDs per crystal. "Start Batch" button runs full 16-crystal sequence. "Export CSV" writes results for sorting (bins by frequency for filter matching).

**Why:** Manual crystal testing tedious (move probe between DUTs, record frequencies by hand). Automated bin sorting for filter manufacturing (need matched pairs within ±5 ppm). 16-DUT capacity allows batch testing during coffee break.

**Use cases:** Crystal filter production, oscillator frequency selection, batch QC.

**Panel layout:** Gauge cluster (4×4 grid) left half, pass/fail LEDs below each gauge. Text LCD + control buttons top-right, count displays bottom-right.

---

### RF Amplifier Production Test Station

`projects/rf/amp-production-panel/` — 💭 not started.

**Virtual instruments:** Analog meter (gain dB), numeric display (P1dB dBm), numeric display (IP3 dBm), line chart (gain vs frequency), bar graph (harmonic distortion dBc), LED (DUT connected), LED (pass/fail), text LCD (test sequence status), button (Run Test), button (Next DUT), gauge cluster (min/typ/max gain over frequency).

**Hardware:** scpi-matrix (relay routing for 4-8 DUTs), SDG1062X (two-tone source), SSA3032X (output measurement), scpi-relay (physical bin sorting: pass → right tray, fail → left tray).

**What it does:** Automated amplifier QC line. Operator places DUT in fixture, presses "Run Test" → backend sequences: (1) measure gain vs frequency (plot on line chart), (2) measure P1dB (display numeric), (3) measure IP3 with two-tone (display numeric), (4) measure harmonics (bar graph shows 2nd/3rd/4th harmonic levels). Pass/fail LED lights based on spec limits. Gauge cluster shows min/typ/max gain across sweep (validates flatness spec). "Next DUT" button increments counter, actuates scpi-relay to physically sort DUT into pass/fail bin, resets panel for next test.

**Why:** Manual amplifier testing takes 5-10 minutes per unit. Automated test reduces to ~30 seconds. Visual feedback (line chart, bar graph) confirms test validity (e.g., gain flatness, harmonic suppression). Physical bin sorting eliminates human error in sorting.

**Throughput:** 120 DUTs/hour (30s per unit) vs ~10 DUTs/hour manual.

**Panel layout:** Meter + P1dB + IP3 displays top row, line chart + bar graph middle (side by side), LEDs + text LCD + buttons bottom, gauge cluster bottom-right.

---

### Filter S21 Sweep QC

`projects/rf/filter-qc-panel/` — 💭 not started.

**Virtual instruments:** Line chart (S21 magnitude dB vs frequency, 16 traces color-coded), text LCD (per-filter results: passband ripple dB, stopband rejection dB, 3dB bandwidth kHz, bin grade A/B/C), button (Measure Batch), button (Export Touchstone), numeric display (batch progress X/16), LED (measurement active).

**Hardware:** scpi-mux (16 filters), SSA3032X + SDG1062X (scalar S21 measurement).

**What it does:** Batch filter QC. scpi-mux switches through 16 filters, measures S21 per filter, plots all 16 traces on single line chart (color-coded for visual comparison). Text LCD shows per-filter metrics extracted from trace (passband ripple, stopband rejection, bandwidth). Backend bins filters into grades: A (within ±0.5 dB passband ripple), B (±0.5-1.0 dB), C (>1.0 dB or fail stopband). "Export Touchstone" writes .s2p files per filter for downstream simulation.

**Why:** Visual trace comparison reveals outliers (shifted center frequency, extra resonance). Automated metric extraction eliminates manual marker placement. Grading supports mix-and-match filter banks (use A-grade for TX path, C-grade for non-critical).

**Use cases:** Crystal filter production, cavity filter tuning validation, LC filter batch QC.

**Panel layout:** Line chart full-width top two-thirds, text LCD left bottom third, buttons + progress + LED right bottom third.

---

## GPS / Position Tracking

### GPS Survey Station with Scatter Plot

`projects/gps/survey-panel/` — 💭 not started.

**Virtual instruments:** XY plot (position scatter: Northing vs Easting meters), numeric display (mean latitude), numeric display (mean longitude), numeric display (mean altitude m), numeric display (N scatter σ meters), numeric display (E scatter σ meters), numeric display (fix count), analog meter (HDOP 0-10), bar graph (satellite count 0-20), line chart (altitude vs time), text LCD (current lat/lon/alt), button (Reset Survey), button (Export GPX).

**Hardware:** scpi-gps (ESP32 GPS via serial NMEA) or rf_bench.gpsd (local gpsd daemon).

**What it does:** Static GPS position survey. Backend logs fixes continuously, computes mean position and scatter (1σ ellipse). XY plot shows real-time scatter (Northing vs Easting in meters relative to mean). Numeric displays show mean lat/lon/alt and scatter statistics. HDOP meter and satellite bar graph show fix quality. Line chart plots altitude vs time (detects altitude drift). "Reset Survey" clears accumulated data. "Export GPX" writes mean position to waypoint file.

**Why:** GPS accuracy assessment (compare scatter to claimed ±2.5 m CEP50). Site survey for antenna placement (validate position before bolting mast). Differential correction validation (compare scatter with/without SBAS or RTK).

**Use cases:** Antenna site survey, repeater location documentation, TDoA baseline calibration, mapping ground truth.

**Panel layout:** XY plot left half (large), numeric displays + HDOP meter + sat bar graph top-right, line chart bottom-right, text LCD + buttons bottom strip.

---

### Mobile Drive Test Mapper

`projects/gps/drivetest-panel/` — 💭 not started.

**Virtual instruments:** Map widget (shows GPS track with color-coded signal strength), analog meter (current signal strength dBm or S-units), numeric display (current speed km/h), numeric display (current heading degrees), line chart (signal strength vs time), text LCD (current position lat/lon), button (Start Logging), button (Stop Logging), button (Export GPX + CSV), LED (logging active).

**Hardware:** scpi-gps (ESP32 GPS), IC-7300 / IC-9700 / FT-891 (S-meter via Hamlib) OR RTL-SDR (power measurement) OR SSA3032X (tracking generator + power meter).

**What it does:** Drive test for RF coverage mapping. User presses "Start Logging" → backend logs GPS position + signal strength continuously. Map widget plots GPS track with points color-coded by signal level (green >S9, yellow S5-S9, red <S5). Analog meter shows live signal strength. Line chart plots signal vs time (detects dropouts). Speed and heading displays show vehicle state. "Export GPX + CSV" writes track for GIS analysis (QGIS, Google Earth) and signal-strength heatmap generation.

**Why:** Manual drive testing requires two people (driver + logger). Automated logging frees driver to focus on road. Real-time map shows coverage holes immediately (no post-processing delay). GPX + CSV export supports advanced analysis (Voronoi diagrams, kriging interpolation, LOS path loss modeling).

**Use cases:** Repeater coverage verification, antenna pattern measurement (drive circles around antenna at fixed radius), cellular signal mapping, propagation studies (compare predicted vs measured).

**Panel layout:** Map widget full-width top half, meter + speed/heading displays top-right, line chart bottom-left, text LCD + buttons bottom-right.

---

### GPS Status Dashboard with maps.n0gq.org Map

`projects/gps/gps-dashboard/` — 💭 not started.

**Virtual instruments:** Map widget (maps.n0gq.org PMTiles vector map centered on current position with marker), numeric display (latitude), numeric display (longitude), numeric display (altitude m), numeric display (speed km/h or knots), numeric display (course/heading degrees), numeric display (HDOP), numeric display (VDOP), numeric display (PDOP), bar graph (satellite count 0-20), bar graph (satellite SNR per satellite), text LCD (fix status: NO_FIX / 2D / 3D / DGPS / RTK_FLOAT / RTK_FIXED), text LCD (visible satellites with PRN/elevation/azimuth), LED (fix quality: red=no fix, yellow=2D, green=3D, cyan=DGPS/RTK), gauge cluster (DOP values: HDOP/VDOP/PDOP as small gauges), line chart (altitude vs time), line chart (speed vs time), button (Center Map on Position), button (Export Current Fix).

**Hardware:** scpi-gps (ESP32 GPS via serial NMEA) or rf_bench.gpsd (local gpsd daemon).

**What it does:** Comprehensive GPS status display with live map. Map widget loads PMTiles vector tiles from `maps.n0gq.org` (internal tile server at 10.1.0.37), displays OpenStreetMap-style basemap, centers on current GPS position with red marker. Position updates in real-time (marker moves on map). Numeric displays show all GPS parameters: lat/lon in decimal degrees, altitude MSL, speed, course (true heading), HDOP/VDOP/PDOP (dilution of precision). Bar graph shows satellite count (green bars = used in fix, gray bars = visible but not used). Second bar graph shows per-satellite SNR (signal-to-noise ratio, identifies weak signals). Text LCD lists visible satellites (PRN number, elevation angle, azimuth, SNR). Fix-quality LED color-codes solution type. Line charts plot altitude and speed history (last 60 seconds). "Center Map" button re-centers map on current position if user panned away. "Export Current Fix" writes current position to GPX waypoint.

**Why:** Unified GPS status replaces multiple terminal windows (`gpsmon`, `cgps`, `gpspipe`). Map integration shows position context (nearby roads, landmarks, terrain). maps.n0gq.org is local tile server (no internet dependency, fast tile delivery). DOP values and satellite SNR diagnose fix quality (high DOP or low SNR = poor geometry, multipath, or obstructions). Fix-type LED provides at-a-glance status. Satellite list shows which constellation (GPS PRN 1-32, GLONASS 65-96, Galileo 301-336, BeiDou 401-437) is used.

**Use cases:** GPS receiver testing, antenna placement validation, multipath detection, fix-quality troubleshooting, real-time position monitoring, mobile tracker, repeater site survey, antenna site documentation.

**Integration with maps.n0gq.org:** Map widget uses MapLibre GL JS to fetch PMTiles from `http://maps.n0gq.org/usa.pmtiles` (30 GB vector tileset covering USA). Queries tiles as user zooms/pans. Map supports query parameters: `?lat=&lon=&zoom=` (e.g., `http://maps.n0gq.org?lat=39.7392&lon=-104.9903&zoom=15` opens Denver at zoom level 15 with marker). Backend publishes GPS lat/lon to MQTT `bench/gps/position`, map widget subscribes and updates marker position. Map widget automatically centers on position at startup, user can pan/zoom, "Center Map" button resets to current position.

**Panel layout:** Map widget left two-thirds (large, dominant), right third split into three sections: top = numeric displays (lat/lon/alt/speed/course in 2×3 grid), middle = DOP gauge cluster + satellite bar graphs + fix LED, bottom = text LCD (satellites list) + line charts (altitude/speed stacked) + buttons. Map is always visible (primary navigation aid).

---

### GPS Info Page (Telemetry Display)

`projects/gps/gps-info-page/` — 💭 not started.

**Virtual instruments:** Numeric display (latitude decimal degrees), numeric display (longitude decimal degrees), numeric display (latitude DMS format), numeric display (longitude DMS format), numeric display (Maidenhead grid square 6-char), numeric display (altitude MSL meters), numeric display (altitude AGL meters if DEM available), numeric display (speed km/h), numeric display (speed knots), numeric display (speed mph), numeric display (course/heading degrees true), numeric display (course/heading degrees magnetic if declination known), numeric display (HDOP), numeric display (VDOP), numeric display (PDOP), numeric display (TDOP time DOP), numeric display (GDOP geometric DOP), numeric display (satellite count total), numeric display (satellites used in fix), numeric display (satellites visible), bar graph (per-satellite SNR 0-50 dB-Hz), text LCD (fix status with timestamp), text LCD (satellite list: PRN, el, az, SNR), text LCD (GPS receiver model/firmware from $GPTXT or gpsd VERSION), LED (fix quality: no fix / 2D / 3D / DGPS / RTK), LED (GPS time sync valid), numeric display (GPS time UTC), numeric display (local time), numeric display (time since last fix seconds), numeric display (position uncertainty CEP meters), button (Reset Trip Odometer), button (Export Fix to GPX), button (Copy Lat/Lon to Clipboard).

**Hardware:** scpi-gps (ESP32 GPS via serial NMEA) or rf_bench.gpsd (local gpsd daemon).

**What it does:** Dense information display of all GPS telemetry parameters. Designed for debugging, testing, and detailed analysis rather than at-a-glance monitoring (contrast with GPS Dashboard above which emphasizes map + status). Displays position in multiple formats: decimal degrees (39.7392, -104.9903), DMS (39°44'21"N, 104°59'25"W), and Maidenhead grid square (DM79qs). Shows speed in three units (km/h, knots, mph). Shows course as true heading and magnetic heading (if declination computed from position). Displays all five DOP values (HDOP/VDOP/PDOP/TDOP/GDOP — not all receivers report all five). Bar graph shows per-satellite SNR (identifies weak satellites, multipath, jamming). Text LCD shows satellite list with full details (PRN, elevation, azimuth, SNR, in-use flag). Second text LCD shows GPS receiver info (model, firmware version if available via $GPTXT NMEA sentence or gpsd VERSION response). Third text LCD shows fix status with timestamp (e.g., "3D FIX at 2026-06-14 18:32:45 UTC"). LEDs provide binary status indicators (fix yes/no, time sync yes/no). GPS time displayed as UTC, local time computed from system timezone. "Reset Trip Odometer" resets cumulative distance traveled (if backend integrates speed over time). "Export Fix" writes current position to GPX. "Copy Lat/Lon" copies decimal degrees to clipboard for paste into Google Maps or other tools.

**Why:** Comprehensive telemetry display for GPS receiver validation, acceptance testing, performance characterization, or troubleshooting. Answers questions like: "Which satellites are used in fix?", "Is WAAS/EGNOS DGPS active?", "What's the actual HDOP (not just 'good/bad')?", "Is GPS time synced (PPS output valid)?", "Why is position jumping (check PDOP spike, satellite drops)?". Multiple position formats convenient for logging (decimal degrees for software, DMS for verbal reporting, grid square for ham radio). Multiple speed units support international users (metric) and aviation/marine (knots).

**Use cases:** GPS receiver testing, troubleshooting poor fix quality, validating DGPS/RTK operation, time synchronization validation (PPS output, NTP server), antenna evaluation (satellite count, SNR), multipath detection (SNR variations), comparing receivers side-by-side (run two instances of this panel).

**Panel layout:** Dense grid layout (4×6 or 5×5 numeric displays), organized by category. Top rows: position (lat/lon decimal, DMS, grid square, altitude). Next rows: motion (speed in 3 units, course true/magnetic). Next rows: DOP values (HDOP/VDOP/PDOP/TDOP/GDOP). Next rows: satellite counts (total/used/visible). Next rows: time (GPS UTC, local, time-since-fix). Bottom section: bar graph (satellite SNR full-width), text LCDs (fix status, satellite list, receiver info stacked vertically), LEDs + buttons right column.

---

## Multi-Instrument Coordination

### Power Supply + Load Closed-Loop Test

`projects/power/psu-load-loop/` — 💭 not started.

**Virtual instruments:** Gauge cluster (PSU: V/I/P), gauge cluster (Load: V/I/P), line chart (PSU voltage vs load current), XY plot (V-I curve), numeric display (PSU load regulation %/V), numeric display (load CC/CV mode), slider (PSU voltage setpoint 0-32V), slider (load current setpoint 0-20A), toggle (PSU output on/off), toggle (load input on/off), button (Measure Load Reg), button (Measure Line Reg).

**Hardware:** SPD3303X-E (PSU), ET5406A+ (load), SDM3045X (voltage measurement at load terminals).

**What it does:** Automated PSU + load testing. User sets PSU voltage via slider, load current via slider. Toggles enable outputs. Backend logs PSU output V/I/P and load input V/I/P simultaneously. Line chart plots PSU voltage vs load current (validates regulation). XY plot shows V-I curve (load line). "Measure Load Reg" button sweeps load current 0-20A, measures PSU voltage droop, displays % regulation. "Measure Line Reg" button sweeps PSU input voltage (via external variac or second PSU), measures output voltage change.

**Why:** Manual PSU + load testing requires two operators (one per instrument) or tedious sequential adjustment. Automated coordination ensures synchronous measurement. V-I curve reveals dynamic behavior (oscillation, dropout). Numeric regulation displays validate specs.

**Use cases:** PSU acceptance testing, load characterization, battery discharge validation, transient response measurement.

**Panel layout:** Two gauge clusters top (PSU left, load right), line chart + XY plot middle (side by side), sliders + toggles + buttons bottom.

---

### SDG + Scope Bode Plotter with Live Plot

`projects/scope/bode-panel/` — 💭 not started.

**Virtual instruments:** Line chart (magnitude dB vs frequency), line chart (phase degrees vs frequency), numeric display (center frequency Hz), numeric display (−3dB bandwidth Hz), numeric display (Q factor), slider (start frequency 10Hz-10MHz log scale), slider (stop frequency), slider (points per decade), button (Run Sweep), button (Export CSV), toggle (magnitude/phase/both).

**Hardware:** SDG1062X (source), SDS2504X (scope CH1=input, CH2=output, math FFT for phase).

**What it does:** Automated Bode plot (extends existing `projects/scope/bode-plotter/`). User sets start/stop frequencies and resolution via sliders, presses "Run Sweep" → backend steps SDG frequency, captures scope CH1/CH2 at each point, computes magnitude (20 log10 |CH2/CH1|) and phase (∠CH2 − ∠CH1 via FFT), plots on line charts in real-time. Numeric displays extract filter metrics (center frequency, bandwidth, Q). Toggle selects which traces to display (magnitude only, phase only, or both). "Export CSV" writes magnitude/phase vs frequency for external plotting (Python matplotlib, MATLAB, Excel).

**Why:** Existing Bode plotter is CLI-only (no live feedback). Web panel shows plot building during sweep (detect early termination if DUT oscillates). Interactive sliders speed setup (no command-line arguments). Export supports publication-quality plots.

**Panel layout:** Two line charts stacked (magnitude top, phase bottom), numeric displays top-right, sliders + buttons bottom strip.

---

### SSA + SDG Two-Tone IMD Analyzer

`projects/rf/two-tone-imd-panel/` — 💭 not started.

**Virtual instruments:** Analog meter (fundamental power dBm), analog meter (IM3 power dBm), numeric display (IP3 dBm), line chart (IM3 vs input power), bar graph (2f1−f2 level dBc), bar graph (2f2−f1 level dBc), slider (f1 frequency), slider (f2 frequency), slider (input power dBm), toggle (SDG CH1 on/off), toggle (SDG CH2 on/off), button (Measure IP3), button (Auto-Balance Tones).

**Hardware:** SDG1062X (two-tone source, phase-locked CH1+CH2), SSA3032X (measures fundamental + IM3 products).

**What it does:** Two-tone IMD measurement panel. Sliders set f1, f2 (typically 100 kHz apart), and input power. Toggles enable SDG outputs. "Auto-Balance Tones" button adjusts SDG CH1/CH2 amplitudes until fundamental powers are equal on SSA (within 0.1 dB). Meters show fundamental and IM3 power. "Measure IP3" button sweeps input power, measures IM3 rise, extracts IP3 via intercept extrapolation, plots on line chart. Bar graphs show 2f1−f2 and 2f2−f1 levels (validates symmetry).

**Why:** Manual two-tone IMD testing requires: (1) tune two generators, (2) balance amplitudes (tedious marker adjustment), (3) sweep power, (4) plot, (5) extrapolate IP3 by hand. Automated panel reduces 30-minute manual test to 2-minute button press. Auto-balance eliminates human error in amplitude matching.

**Use cases:** Amplifier IP3, mixer IMD, receiver intermodulation, filter IMD.

**Panel layout:** Meters + IP3 display top, line chart + bar graphs middle, sliders + toggles + buttons bottom.

---

## Contest / Field Day

### N1MM+ Integration Dashboard

`projects/radio/n1mm-dashboard/` — 💭 not started.

**Virtual instruments:** Numeric display (N1MM+ frequency MHz), numeric display (N1MM+ mode), analog meter (SWR), numeric display (TX power W), line chart (QSO rate per hour), bar graph (band activity: 160m-10m), text LCD (last 5 QSOs: call, band, mode, time), LED (PTT active), LED (antenna tuned <1.5:1 SWR), button (Tune Antenna), button (QSY to Best Band).

**Hardware:** IC-7300 / FT-891 (via Hamlib), scpi-swr (ESP32 SWR meter), scpi-tuner (ESP32 antenna tuner), scpi-ptt (ESP32 PTT sense). N1MM+ UDP broadcast on port 12060.

**What it does:** Contest logging integration. Backend listens to N1MM+ UDP broadcasts, displays current frequency/mode. When frequency changes (QSY), backend auto-tunes antenna via scpi-tuner if SWR >1.5:1. SWR meter and LED provide visual feedback. TX power numeric display (from scpi-swr forward power). Line chart plots QSO rate (updates after each logged QSO). Bar graph shows per-band QSO count (highlights which bands are productive). Text LCD scrolls recent QSOs. "QSY to Best Band" button analyzes propagation (via KiwiSDR beacon S-meters or HF-conditions API) and sends frequency-change command to N1MM+ via UDP.

**Why:** Eliminates manual antenna tuning during contest QSYs (save 10-30 seconds per band change = 50-150 QSOs gained in 24-hour contest). SWR + power monitoring detects antenna problems before they damage radio. QSO rate chart motivates operator (gamification). "Best Band" recommendation uses propagation data for informed band changes.

**Panel layout:** Frequency + mode displays top-left, SWR meter + power + LEDs top-right, line chart + bar graph middle, text LCD + buttons bottom.

---

### SO2R Dual-Radio Coordinator

`projects/radio/so2r-panel/` — 💭 not started.

**Virtual instruments:** Two columns: Radio 1 (analog meter S-meter, numeric display frequency, LED PTT, toggle output enable) and Radio 2 (same widgets). Line chart (dual S-meter traces), text LCD (interlock status: which radio is active, lockout reasons), LED (interlock OK), LED (interlock FAIL), button (Swap Radios), button (Emergency All Off).

**Hardware:** IC-7300 (radio 1), SunSDR or second IC-7300 (radio 2), scpi-matrix (antenna routing), scpi-ptt (dual PTT sense + interlock logic).

**What it does:** SO2R (Single Operator Two Radio) coordination. Backend monitors both radios via Hamlib. Enforces interlocks: (1) no simultaneous TX on both radios (scpi-ptt hardware lockout), (2) no same-band operation (prevents self-interference), (3) antenna routing via scpi-matrix (band decoder routes each radio to appropriate antenna). Line chart plots both S-meters (CQ on radio 1 while searching-and-pouncing on radio 2). "Swap Radios" button exchanges which radio is "run" vs "mult". "Emergency All Off" button kills both radio outputs (footswitch panic button equivalent).

**Why:** Manual SO2R requires dedicated hardware controller (Microham, Top Ten Devices) costing $500-2000. Software-defined SO2R via rf-bench hardware costs <$100 (ESP32 + relays). Interlock logic prevents self-interference and accidental dual-TX (kills amplifiers). Antenna routing automation frees operator to focus on operating, not switching.

**Complexity:** SO2R is the hardest contest automation project. Requires sub-100ms switching, rock-solid interlock logic, and tight N1MM+ integration. Consider this a stretch goal.

**Panel layout:** Two columns (radio 1 left, radio 2 right), line chart full-width middle, text LCD + LEDs + buttons bottom strip.

---

## Propagation Science

### Multipath Fading Analyzer (KiwiSDR)

`projects/kiwisdr/multipath-panel/` — 💭 not started.

**Virtual instruments:** Waterfall display (delay vs Doppler shift), line chart (S-meter vs time, multiple beacons), XY plot (scatter diagram: delay vs Doppler per beacon), text LCD (propagation mode: F2, Es, TEP, auroral, scatter), numeric display (max Doppler shift Hz), numeric display (delay spread ms), button (Start Capture), button (Export Data).

**Hardware:** KiwiSDR (monitors HF beacons NCDXF/IARU simultaneously on multiple channels), scpi-gps (optional for local time + position).

**What it does:** Ionospheric multipath analysis. KiwiSDR receives beacon CW signals on multiple HF bands (14/18/21/24/28 MHz). Backend FFTs each beacon to extract Doppler shifts (propagation mode identification: zero Doppler = F2, wide spread = scatter, single offset = TEP). Delay-Doppler plot shows 2D distribution (multiple peaks = multipath). Text LCD identifies propagation mode based on Doppler/delay pattern. Line chart shows S-meter vs time per beacon (detect selective fading). Waterfall display (borrowed from virtual instrument library) shows delay-Doppler evolution over time.

**Why:** Propagation mode identification informs operating strategy (F2 = long-haul DX, Es = short-skip, TEP = tropical, auroral = high-latitude). Delay spread measurement predicts digital mode performance (wide spread = ISI = poor FT8). Doppler shift warns of auroral absorption (rapid flutter = signal loss imminent).

**Use cases:** Ionospheric research, propagation forecasting, contest band selection, digital mode suitability prediction.

**Panel layout:** Waterfall top-left, line chart top-right, XY plot bottom-left, text LCD + numeric displays + buttons bottom-right.

---

### Tropospheric Ducting Detector

`projects/rf/tropo-ducting-panel/` — 💭 not started.

**Virtual instruments:** Line chart (RSSI vs antenna height, 4 traces for 4 antennas), XY plot (refractive index vs height m), analog meter (refractive index gradient dn/dh × 10^6 m^−1), numeric display (predicted duct height m), text LCD (ducting status: none / weak / strong / super-refraction), LED (ducting detected), button (Measure Profile), button (Export Data).

**Hardware:** scpi-relay (switches between 4 antennas at heights 1m, 3m, 10m, 30m), RTL-SDR (VHF/UHF RSSI measurement), scpi-temp + barometer + hygrometer (environmental sensors at multiple heights).

**What it does:** Tropospheric duct detection. scpi-relay cycles through 4 antennas, RTL-SDR measures VHF beacon RSSI at each height. Backend computes refractive index N(h) from T/P/humidity at each height, plots N vs h (XY plot). Negative gradient dn/dh indicates ducting. Analog meter shows gradient magnitude. Text LCD classifies duct strength (none: dn/dh > −40 N-units/km, weak: −40 to −100, strong: −100 to −200, super: <−200). LED lights when ducting detected. Line chart shows RSSI vs height (validates measurement — ducting shows enhanced signal at low antennas relative to high antennas).

**Why:** Tropospheric ducting enables 200-1000 km VHF/UHF DX (normally 50-100 km). Advance warning allows scheduling contacts or contests. Quantitative duct-height prediction informs antenna aiming (aim below horizon for ducted path). Refractive index profile confirms ducting mechanism (evaporation duct, subsidence inversion, frontal).

**Use cases:** 2m/70cm DX prediction, EME scheduling (duct interferes with EME by reflecting signal back to Earth), microwave link planning.

**Panel layout:** Line chart (RSSI vs height) left, XY plot (N vs height) center, meter + numeric + text LCD right, buttons + LED bottom.

---

## ESP32 + Virtual Instruments

### ESP32 Relay Matrix Control Panel

`projects/esp32-combos/relay-matrix-panel/` — 💭 not started (blocked on XL9535 hardware).

**Virtual instruments:** 8×8 grid of toggle switches (visual matrix representation), text LCD (routing table: input X → output Y), LED per input (shows if input is routed), LED per output (shows if output is active), button (Clear All), button (Preset 1-4), button (Save Preset).

**Hardware:** scpi-matrix (ESP32 + XL9535 16-relay board, configured as 4×4 or 8×2 RF routing matrix).

**What it does:** Visual RF routing matrix control. 8×8 grid of toggles represents physical relay matrix. User clicks toggle at (row 3, col 5) → backend commands scpi-matrix to close relay connecting input 3 to output 5. Text LCD shows active routes ("IN3→OUT5, IN1→OUT2"). Input LEDs show which inputs are routed (green if routed, gray if disconnected). Output LEDs show which outputs are active. "Clear All" opens all relays (disconnect everything). Preset buttons recall saved routing configs (e.g., "Preset 1" = SSA TG → DUT1, SDG → DUT2).

**Why:** Visual matrix representation easier to understand than SCPI commands (`ROUT:CLOS (@3!5)` obscure). Toggle grid provides instant feedback on routing state. Preset recall speeds common configurations (test setup A vs B).

**Use cases:** Multi-DUT RF testing, antenna switching, signal routing for automated test sequences, filter bank selection.

**Panel layout:** 8×8 toggle grid center (large), text LCD top, input LEDs left margin (vertical), output LEDs bottom margin (horizontal), preset buttons bottom-right.

---

### ESP32 Temperature Chamber Controller

`projects/esp32-combos/thermal-chamber-panel/` — 💭 not started.

**Virtual instruments:** Gauge cluster (8 DS18B20 sensors: spatial temp distribution), analog meter (setpoint error °C), numeric display (setpoint °C), numeric display (actual mean temp °C), numeric display (max temp delta °C across all sensors), line chart (temperature vs time, 8 traces + setpoint), slider (setpoint −40 to +85°C), toggle (heater enable), button (PID Autotune), text LCD (PID parameters Kp/Ki/Kd), LED (at setpoint ± 0.5°C).

**Hardware:** scpi-heater (ESP32 + DS18B20 + heater element + SSR), scpi-temp (reads 8 DS18B20 sensors placed throughout chamber), SDM3045X (reference thermometer for calibration).

**What it does:** Thermal chamber control with spatial profiling. Slider sets setpoint, scpi-heater PID controller drives heater to maintain temp. Gauge cluster shows temp at 8 locations (reveals hot spots, cold spots). Line chart plots all 8 sensors + setpoint vs time. Numeric "max delta" display flags non-uniformity (>5°C delta = poor circulation). Analog meter shows setpoint error (validates PID tuning). "PID Autotune" button runs Ziegler-Nichols tuning, writes Kp/Ki/Kd to text LCD. LED lights green when chamber stable at setpoint.

**Why:** Manual chamber control (thermostat + thermometer) provides single-point measurement. Multi-sensor profiling reveals spatial gradients critical for component testing (DUT in hot corner reads 10°C higher than thermostat). PID autotune eliminates trial-and-error tuning. Visual stability indicator (LED) confirms test readiness.

**Use cases:** Component temperature cycling (−40 to +85°C stress testing), TCR measurement, crystal aging, TCXO characterization, thermal transient response.

**Panel layout:** Gauge cluster left, line chart center, setpoint controls + meter + LED right, text LCD + buttons bottom.

---

### ESP32 + IC-7300 Remote HF Station

`projects/esp32-combos/remote-hf-panel/` — 💭 not started.

**Virtual instruments:** Analog meter (S-meter), numeric display (frequency MHz), numeric display (mode), analog meter (SWR), numeric display (forward power W), numeric display (reflected power W), compass (antenna azimuth), analog meter (antenna elevation 0-90°), LED (PTT active), LED (antenna tuned <1.5:1 SWR), toggle (preamp on/off), slider (RF gain 0-100%), button (Tune Antenna), button (Aim Antenna), text input (frequency entry), text input (target azimuth).

**Hardware:** IC-7300 (via Hamlib rigctld), scpi-rotator (ESP32 antenna controller), scpi-swr (ESP32 SWR meter), scpi-ptt (ESP32 PTT sense), scpi-tuner (ESP32 antenna tuner).

**What it does:** Complete remote HF station control. All radio functions (frequency, mode, S-meter, preamp, RF gain) controlled via Hamlib. Antenna functions (azimuth, elevation, SWR, tuning) controlled via ESP32 SCPI. User enters frequency via text input → radio tunes. User enters target azimuth via text input → presses "Aim Antenna" → scpi-rotator slews to bearing, compass widget tracks real-time position. SWR meter monitors antenna match, "Tune Antenna" button triggers auto-tuner if SWR >1.5:1. PTT LED shows TX status. All widgets update in real-time (sub-second latency).

**Why:** Complete remote station eliminates need for operator at radio site. VPN + web panel allows control from anywhere (home to remote cabin, shack to DXpedition site). Integrated antenna control + radio control + SWR monitoring simplifies operating (single UI vs juggling multiple apps).

**Use cases:** Remote HF station, Field Day operation (control tent separate from antenna), permanent unattended beacon station.

**Panel layout:** 3×3 grid. S-meter + freq + mode top row. SWR meter + power + PTT LED middle row. Compass + elevation + controls bottom row. Text inputs + buttons bottom strip.

---

## New Virtual Instrument Widget Ideas

These are NEW widgets not in the existing Phase 1/2 set, discovered by analyzing the project ideas above.

### Map Widget (Phase 3)

`virtual/map/` — 💭 not started.

**Visual:** Interactive map (OpenStreetMap or MapLibre GL) with GPS track, markers, color-coded points by signal strength, zoom/pan controls.

**Config:** `center_lat`, `center_lon`, `zoom`, `marker_color_by` (MQTT topic for color value), `track_topic` (MQTT topic publishing lat/lon).

**Binding:** MQTT topics (lat/lon for position, signal strength for color).

**Use cases:** Drive test mapper, GPS survey station, antenna coverage map, propagation map, mobile APRS tracker.

**Why missing from Phase 1:** Maps require GIS library (Leaflet.js or MapLibre GL), larger than simple Canvas widgets. Higher complexity than gauges/charts.

---

### Matrix Grid (Phase 3)

`virtual/matrix-grid/` — 💭 not started.

**Visual:** M×N grid of toggle switches, color-coded cells (on=green, off=gray), labels for rows/columns.

**Config:** `rows`, `cols`, `row_labels`, `col_labels`, `default_state`.

**Binding:** SCPI write command per cell (e.g., `ROUT:CLOS (@row!col)`), read-back to confirm state.

**Use cases:** Relay matrix control, crosspoint switch, multi-DUT routing, antenna array phasing.

**Why missing from Phase 1/2:** Matrix is specialized (not a general-purpose display). Discovered when designing ESP32 relay matrix projects.

---

### 2D Heatmap (Phase 3)

`virtual/heatmap/` — 💭 not started.

**Visual:** 2D color map (frequency vs time, height vs temperature, azimuth vs elevation).

**Config:** `x_axis`, `y_axis`, `z_colormap` (viridis, plasma, jet), `z_min`, `z_max`.

**Binding:** MQTT topic publishing 2D array (JSON), or SCPI query returning 2D trace.

**Use cases:** Delay-Doppler plot, spatial temperature distribution, antenna pattern 3D surface, refractive index profile.

**Why missing from Phase 1:** 2D heatmaps require more sophisticated rendering than 1D charts (Plotly.js heatmap or custom Canvas). Higher data throughput (2D array vs 1D array).

---

### Gauge Cluster (Phase 1 — WAS in future ideas, NOW BUILT)

**Status update:** `virtual/gauge-cluster/` — ✅ BUILT (as of Phase 1, untested).

Multiple small gauges in a grid layout. Already in the Phase 1 list. Confirmed still needed for multi-cell battery monitor, PSU panel, dual-radio SO2R.

---

## Summary Statistics

**New project ideas created:** 41
- RF / Spectrum Analysis: 5
- Radio Operations: 4
- Power / Battery Management: 3
- Signal Sources / Synthesis: 3
- Automated Testing / QC: 3
- GPS / Position Tracking: 4 (GPS survey, drive test mapper, GPS dashboard with maps.n0gq.org, GPS info page)
- Multi-Instrument Coordination: 3
- Contest / Field Day: 2
- Propagation Science: 2
- ESP32 + Virtual Instruments: 3
- New widget types: 3 (map, matrix grid, 2D heatmap)

**Virtual instruments used:**
- Phase 1 (read-only): analog meter, bar graph, LED, numeric display, line chart, XY plot, text LCD, waterfall, compass, gauge cluster
- Phase 2 (interactive): toggle, button, knob, slider, text input
- Phase 3 (new): map, matrix grid, 2D heatmap

**Hardware integration:**
- Siglent bench instruments: SSA, SDG, SDS, SDM, SPD (21 projects)
- Radios: IC-7300, IC-9700, FT-891 (12 projects)
- ESP32 SCPI controllers: scpi-rotator, scpi-swr, scpi-ptt, scpi-tuner, scpi-mux, scpi-adc, scpi-temp, scpi-heater, scpi-matrix, scpi-gps, scpi-power (25 projects)
- SDRs: RTL-SDR, KiwiSDR, SunSDR (7 projects)
- Other: ET5406A+ load, MHS-5225A DDS, Bus Pirate, Flipper Zero, XL9535 relay, gpsd (9 projects)

**Key insight:** Virtual instrument clusters shine when combining:
1. Multiple instruments (SSA + SDG + scope = Bode plotter)
2. Hardware + software control (ESP32 actuators + bench measurements)
3. Real-time visualization + interactive control (sliders change setpoints, charts show response)
4. Remote operation (web panel replaces physical front panel)

**Most valuable projects** (by impact):
1. HF Station Dashboard — replaces $500+ physical meters with $0 web panel
2. Multi-Cell Battery Monitor — safety-critical for lithium packs
3. SSA Live Spectrum Monitor — remote spectrum analysis for field work
4. Antenna Tuner Panel — automated tuning saves minutes per band change
5. Multi-DUT Crystal Sorter — 10× throughput vs manual testing
