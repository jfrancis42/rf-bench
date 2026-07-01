# ShuttleXpress Application Ideas

The Contour Design ShuttleXpress provides three control types:
- **Jog wheel** — free-spinning rotary encoder, one tick per detent (fine adjust)
- **Shuttle ring** — spring-return, -7 to +7 positions (speed/rate control)
- **5 buttons** — momentary (mode select, toggle, trigger)

Driver: `rf_bench.shuttlexpress`

---

## Radio Tuning

### SunSDR2 Pro (TCI WebSocket)

- Jog: fine tune (10 Hz/tick in SSB, 100 Hz in AM/FM)
- Shuttle: fast sweep — speed proportional to deflection (up to 50 kHz/sec at full throw)
- Button 1: cycle band up
- Button 2: cycle band down
- Button 3: toggle mode (USB/LSB/AM/FM/CW)
- Button 4: toggle step size (10/50/100/1000 Hz per jog tick)
- Button 5: toggle RIT on/off

### Icom IC-7300 / IC-9700 (Hamlib rigctld)

Same mapping via rigctld TCP. Works with any Hamlib-supported radio.

### KiwiSDR (WebSocket)

Remote tuning of KiwiSDR receivers. Jog for fine, shuttle for band-scanning.
Buttons select preset frequencies or switch antenna inputs.

### RTL-SDR Center Frequency

Scroll through the spectrum — shuttle pans across a wide band, jog fine-tunes
within the visible window. Useful with the classifier or FM-RDS scanner.

---

## Instrument Control

### Signal Generator (SDG1062X / MHS-5200A)

- Jog: adjust output frequency (step size depends on range)
- Shuttle: fast frequency sweep (for finding resonances by ear/eye)
- Button 1: toggle output on/off
- Button 2: cycle waveform (sine, square, triangle)
- Button 3: switch between frequency and amplitude adjust modes
- Button 4: 10x step size multiplier (hold)
- Button 5: store current frequency to memory

### Spectrum Analyzer (SSA3032X)

- Jog: move center frequency
- Shuttle: adjust span (zoom in/out around center)
- Button 1: marker to peak
- Button 2: cycle reference level
- Button 3: toggle between center-freq and marker-freq adjust
- Button 4: single sweep trigger
- Button 5: screenshot/save trace

### Oscilloscope (SDS2504X)

- Jog: adjust timebase or trigger level
- Shuttle: scroll through waveform history (segmented acquisition)
- Button 1: single trigger
- Button 2: auto/normal trigger toggle
- Button 3: switch between timebase / trigger-level / vertical-scale adjust
- Button 4: cursor on/off
- Button 5: run/stop

### DC Load (Yertai ET5406A+)

- Jog: adjust current setpoint (10 mA/tick)
- Shuttle: coarse adjust (100 mA/sec at full deflection)
- Button 1: output on/off
- Button 2: cycle mode (CC/CV/CP/CR)
- Button 3: toggle between current/voltage/power adjust
- Button 4: step size toggle (1/10/100 mA)
- Button 5: start/stop data logging

### Power Supply (SPD3303X)

- Jog: adjust voltage (10 mV/tick)
- Shuttle: coarse voltage sweep
- Button 1: output on/off
- Button 2: select channel (CH1/CH2/CH3)
- Button 3: switch between voltage and current-limit adjust
- Button 4: step size toggle
- Button 5: OVP/OCP toggle

### Digital Step Attenuator

- Jog: step attenuation (0.5 or 1 dB/tick)
- Shuttle: fast ramp for finding MDS or compression point
- Button 1: 0 dB (bypass)
- Button 2: max attenuation
- Button 3: toggle step size (0.5/1/5/10 dB)

---

## VNA / Antenna Work

### Live Filter Tuning (vna/filter-tuning)

- Jog: move marker along S21 trace
- Shuttle: adjust center frequency of sweep window
- Button 1: recenter sweep on marker
- Button 2: toggle between narrow/wide span
- Button 3: save current trace as reference overlay
- Button 4: toggle live/hold mode
- Button 5: export PDF

### Antenna Tuner Adjustment

While `vna/swr-pdf` or `vna/impedance-pdf` runs in live mode:
- Jog: step through frequencies to find worst VSWR point
- Shuttle: adjust sweep span
- Button 1: recenter on current minimum
- Dedicated for hands-free adjustment of antenna tuner while watching Smith chart

---

## Audio / DSP

### Vocoder Parameter Control

- Jog: adjust vocoder pitch (cylon mode) or band count
- Shuttle: mix wet/dry
- Buttons: preset recall, effect bypass, mode switch

### HF Channel Simulator (educational/iq)

- Jog: adjust SNR in real time
- Shuttle: sweep fading rate (Doppler spread)
- Button 1: cycle preset (clear → moderate → rough → dx → aurora)
- Button 2: toggle QRN on/off
- Button 3: toggle multipath echo
- Button 4: toggle ionospheric chirp
- Button 5: passthrough (bypass all effects)

### Soundcard Projects (EQ / Filters)

- Jog: adjust selected parameter (cutoff freq, Q, gain)
- Shuttle: sweep filter cutoff in real time
- Buttons: select which parameter to adjust, bypass

---

## Measurement Automation

### Manual Sweep Controller

For measurements that need human pacing (e.g., adjusting a trimmer and
recording at each point):
- Jog: advance to next measurement point
- Button 1: record current reading
- Button 2: mark point as outlier/skip
- Button 3: undo last point
- Button 4: finish and generate report
- Button 5: pause/resume

### Relay Matrix Navigator

With the XL9535 relay board:
- Jog: step through DUT positions
- Shuttle: fast scan (measure each briefly)
- Button 1: connect selected DUT
- Button 2: disconnect all
- Button 3: mark current DUT as pass/fail
- Button 4: next test in sequence
- Button 5: generate report

---

## Non-RF Applications

### Video / Media Scrubbing

- Jog: frame-by-frame advance
- Shuttle: variable-speed playback (proportional to ring deflection)
- Buttons: play/pause, mark in/out, chapter skip

### Map Navigation (MapLibre / Leaflet)

- Jog: zoom in/out
- Shuttle: pan east/west (or rotate bearing)
- Buttons: drop marker, toggle layers, center on GPS position

### Terminal Scrollback

- Jog: scroll terminal history line-by-line
- Shuttle: page-speed scroll
- Buttons: top, bottom, search, mark

### 3D Print / CNC Jog

- Jog: move selected axis by step (0.1 mm)
- Shuttle: continuous jog at speed proportional to ring
- Buttons: select axis (X/Y/Z), home, set zero, step size
