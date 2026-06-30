# SunSDR2 Pro TCI 2.0 + Audio Sidecar Project Ideas

New project proposals leveraging the TCI 2.0 Hamlib backend with audio/IQ sidecar support and GPSDO-referenced frequency accuracy.

## Architecture Overview

**New capabilities from TCI 2.0 backend:**
- Dual sidecar streams: audio (demodulated, bidirectional) + IQ (raw, RX-only) on independent TCP ports
- Audio sidecar: RX + TX audio (for SSB/voice modes) — enables VoIP integration
- IQ sidecar: RX only (192 kHz) — for analysis, recording, GNURadio processing
- **TX IQ: NOT SUPPORTED** — neither TCI protocol, radio hardware, nor sidecar support transmitting IQ samples
- TX audio: supported via audio sidecar for voice modes (SSB/AM/FM)
- Simultaneous access: Hamlib CAT control + GNURadio IQ processing + audio apps
- Background thread: handles TCI push events without blocking CAT commands
- GPSDO-disciplined frequency accuracy (SunSDR2 Pro, IC-9700, KiwiSDR all have GPSDO)
- FreePBX integration: local PBX available for SIP extensions, IVR, conference bridges

**Hardware accuracy:**
- SunSDR2 Pro: GPSDO reference, 14-bit ADC
- IC-9700: GPSDO reference
- KiwiSDR: GPSDO reference
- Oscilloscope: Can be GPSDO-synced (not currently configured)

---

## Category: Precision Frequency Measurement

### 1. GPSDO-Referenced Frequency Counter (💭)
**Instruments:** SunSDR2 Pro + signal generator under test  
**Use:** Calibrate any signal source against GPSDO-disciplined reference

Use SunSDR's GPSDO-referenced LO to measure signal generator accuracy. At 192 kHz 
IQ, measure frequency via FFT peak with sub-Hz resolution (0.34s capture = 2.9 Hz 
bins; 10s = 0.1 Hz). Compare against KiwiSDR measurement for cross-validation.

**Outputs:**
- Frequency offset in Hz and PPM
- Allan deviation for stability measurement
- Time-series log for drift characterization
- Temperature correlation (if available from instrument)

**Advantage over counter:** Long integration time + GPSDO ref = better than 
handheld counter for precision oscillator characterization.

---

### 2. Three-Way GPSDO Cross-Check (💭)
**Instruments:** SunSDR2 Pro + IC-9700 + KiwiSDR  
**Use:** Validate GPSDO accuracy, detect reference failures

All three have independent GPSDOs. Generate test signal (or use WWV), measure on 
all three simultaneously, compare. Any outlier indicates GPSDO lock loss or 
hardware issue.

**Real-world use case:** Before precision measurements, verify bench references 
are all agreeing. Catches GPS antenna disconnect, holdover mode, etc.

---

### 3. Oscillator Aging Tracker (💭)
**Instruments:** SunSDR2 Pro + signal generator  
**Use:** Long-term frequency stability measurement

Daily automated measurement of signal generator frequency against GPSDO. Log to 
SQLite for months/years. Characterizes oscillator aging rate (e.g., TCXO aging 
is typically 1-5 PPM/year).

**Outputs:**
- Long-term drift plot (Hz/day, PPM/month)
- Aging acceleration (PPM/year²)
- Temperature coefficient extraction

**Integration:** Cron job + automated report generation.

---

## Category: Two-Way Audio + CAT Integration

### 4. Digital Mode Automated Logger (💭)
**Instruments:** SunSDR2 Pro (audio sidecar) + fldigi/JS8Call  
**Use:** Fully automated HF digital monitoring station

Audio sidecar feeds demodulated audio to digital mode app via PulseAudio. Python 
script controls SunSDR via Hamlib (frequency, mode) and scrapes decoded messages 
from app. Logs all contacts to SQLite with: frequency, mode, SNR, callsign, grid, 
message.

**Advantage over existing tci-audiopipe:** Adds Hamlib CAT automation for 
multi-band scanning and metadata enrichment (S-meter, mode, etc.).

**Modes supported:** FT8, JS8, PSK31, RTTY, Olivia, Contestia (anything fldigi supports)

**Use cases:**
- Propagation monitoring: scan all HF bands for FT8, log when/where stations heard
- JS8 net monitor: join JS8 calling frequencies, log all messages
- Contestia beacon tracker: monitor maritime/utility stations

---

### 5. SSB Voice Logger with Transcription (💭)
**Instruments:** SunSDR2 Pro (audio sidecar) + Whisper STT  
**Use:** Record + transcribe SSB/AM voice activity

Audio sidecar → VAD (voice activity detection) → record to WAV → Whisper 
transcription → SQLite. Builds searchable archive of voice activity: "show me all 
transmissions containing 'emergency' on 14.300 MHz last month."

**Privacy note:** Local Whisper model, no cloud API. User controls retention policy.

**Use cases:**
- Net logging: transcribe ARES/RACES nets for record-keeping
- DX spotting: "callsign mentioned W1AW" → auto-spot
- Research: linguistic analysis of ham radio communication patterns

---

### 6. Remote HF Station with Phone Patch (💭)
**Instruments:** SunSDR2 Pro (audio sidecar + TCI) + FreePBX  
**Use:** Operate HF station remotely via smartphone or desk phone

Extends existing `tci-sipphone` project with full duplex + PTT control via DTMF. 
Audio sidecar provides bidirectional audio: RX audio → SIP caller, SIP caller → 
TX audio back to radio.

**Call flows:**
1. **External mobile:** Call FreePBX DID → IVR menu → connect to radio extension
2. **Internal extension:** Dial radio extension directly from office desk phone
3. **Conference mode:** Multiple callers join FreePBX conference → all hear RX, 
   one talker at a time keys PTT

**DTMF control:**
- `*` = PTT on/off toggle (or press-and-hold)
- `#` = Switch RX/TX VFO (split operation)
- `0` = Read back current frequency via TTS
- `1-9` = Preset frequencies (e.g., 1=14.300 USB, 2=7.200 LSB)
- `**` = Increment frequency 5 kHz
- `##` = Decrement frequency 5 kHz

**Web dashboard integration:**
- WebSocket push: live waterfall, S-meter, frequency display
- Click-to-tune: click on waterfall → radio retunes
- Voice command: FreePBX Asterisk AGI script → "QSY to fourteen point two hundred USB"

**Multi-user modes:**
1. **Exclusive:** First caller locks the radio, others get busy signal
2. **Monitor:** Multiple callers hear RX, only one can transmit (request via DTMF)
3. **Net control:** Conference bridge with moderator controls PTT assignments

**Advantage over existing sipphone:** Uses local FreePBX → no external SIP provider 
needed, full IVR customization, integrates with office phones.

---

### 7. FreePBX Radio Gateway with Multiple Radios (💭)
**Instruments:** SunSDR2 Pro + IC-7300 + IC-9700 + FreePBX  
**Use:** Phone-dial-accessible radio bank, select band/mode via extension

Map each radio to a FreePBX extension:
- Ext 7300: IC-7300 (HF)
- Ext 9700: IC-9700 (VHF/UHF)
- Ext 2000: SunSDR2 Pro TRX 0 (HF)
- Ext 2001: SunSDR2 Pro TRX 1 (VHF)

**Features:**
- Dial 7300 from any phone → connected to HF radio
- Transfer call between extensions → switch bands without hanging up
- Conference bridge: monitor multiple bands simultaneously (one earpiece per radio)
- IVR menu: "Press 1 for HF, 2 for VHF, 3 for UHF"

**Use cases:**
- Remote monitoring: call from car, select which band to check
- Multi-band net: net control on 40m, check-ins on 2m, bridge via conference
- Guest operation: visitor dials in from hotel, operates your station

**Implementation:** Separate rigctld instance per radio, Python script per 
extension handles audio sidecar + CAT control.

---

### 8. Automated Phone Answering Service for Radio Status (💭)
**Instruments:** All radios + FreePBX IVR  
**Use:** Call station, get spoken status report

Dial station phone number → FreePBX IVR → TTS reads current status:
- "SunSDR is on 14.205 MHz upper sideband, signal strength S7"
- "IC-9700 is monitoring 146.520 FM, no activity in the last 10 minutes"
- "20 meter band is currently open to Europe with signals up to S9"

**Menu options:**
- Press 1: Connect to HF radio
- Press 2: Connect to VHF radio
- Press 3: Hear last 5 received CW messages (decoded)
- Press 4: Hear propagation summary (band-by-band)
- Press 9: Leave voicemail (gets transcribed, emailed)

**Use case:** Check station status without computer (just phone), useful when 
traveling or from non-internet locations.

---

### 9. Phone-to-Radio Bridge for ARES/RACES (💭)
**Instruments:** SunSDR2 Pro + FreePBX + external phone line  
**Use:** Emergency communications: phone network ↔ HF radio bridge

Bidirectional gateway:
1. **Phone → Radio:** Caller dials in → audio to HF SSB → reaches distant station
2. **Radio → Phone:** Remote HF station → FreePBX dials out → reaches phone 
   subscriber (with permission)

**Use case:** Phone network down in disaster area, but HF radio works. Route 
health-and-welfare calls through your station:
- Family in disaster area has HF radio, no phone
- Family outside area has phone, no radio
- Your station bridges: phone ↔ FreePBX ↔ audio sidecar ↔ HF ↔ remote station

**Features:**
- PTT on voice activity (VOX) or DTMF signaling
- Recording: all calls logged with timestamp, frequency, audio archive
- Access control: PIN code required, whitelist of authorized callers
- Two-way: HF station can "dial out" via DTMF (sends phone number via FSK data 
  burst, FreePBX places outbound call)

**Regulatory note:** Requires proper third-party traffic handling per FCC Part 97.

---

### 10. Radio-Activated Phone Notifications (💭)
**Instruments:** SunSDR2 Pro (audio sidecar) + FreePBX + decoding  
**Use:** Radio hears keyword → places phone call to notify you

Monitor frequency with decoder (CW, digital mode, or voice-to-text). On keyword 
match → FreePBX places outbound call to your cell:

**Trigger examples:**
- CW: callsign "N0GQ" decoded → calls your phone
- Voice: "emergency" or "mayday" → immediate call + recording
- Digital: FT8 message contains your grid square → SMS or call
- APRS: specific station heard on 144.390 → notification

**Call flow:**
1. Keyword detected → FreePBX dials your cell
2. You answer → TTS: "Emergency traffic detected on 14.300 MHz at 2024 UTC"
3. Press 1: connect to live audio from radio
4. Press 2: hear recording of last 60 seconds
5. Press 3: key PTT and respond

**Use cases:**
- Monitor calling frequency while away from shack
- ARES/RACES: alert on "net check-in" request
- DX: alert when rare station appears on band
- Utility monitoring: alert on specific maritime/military calls

---

## Category: IQ Processing + GNURadio

### 11. GNURadio Live Spectrum Monitor (💭)
**Instruments:** SunSDR2 Pro (IQ sidecar, RX-only) + GNURadio  
**Use:** Real-time DSP on SunSDR IQ stream

IQ sidecar (192 kHz RX stream) → GNURadio → custom processing → live display. 
Unlike ExpertSDR3's built-in waterfall, this enables custom DSP: channelizers, 
matched filters, decoders, direction finding, etc.

**Example flowgraphs:**
- **Channelizer:** split 192 kHz into 16× 12 kHz channels, demodulate all simultaneously
- **Radar detector:** matched filter for known radar waveforms (OTH, aviation)
- **Interference tracker:** adaptive notch + direction finding (if using dual RX)
- **Custom decoder:** implement decoders for non-ham modes (utility, maritime)

**Advantage:** GNURadio's DSP blocks + SunSDR's clean IQ + GPSDO accuracy = 
research-grade SDR platform.

---

### 12. IQ Recording with Automatic Classification (💭)
**Instruments:** SunSDR2 Pro (IQ sidecar, RX-only) + ML classifier  
**Use:** Record RX IQ, auto-classify modulation type

IQ sidecar (RX stream) → SigMF format recorder → ML model (CNN or decision tree) 
→ labeled database. Build training set by recording known signals, then 
auto-classify unknowns.

**Classifications:** CW, SSB, AM, FM, FSK, PSK, OFDM, chirp, noise, etc.

**Use cases:**
- Band survey: "what % of 20m is SSB vs FT8 vs noise at 2PM UTC?"
- Interference hunting: "classify this repeating signal on 14.205 MHz"
- Propagation research: "how does mode distribution change during contests?"

**Integration:** Uses existing `rtlsdr/classify` CNN architecture, adapted for HF.

---

### 13. Coherent Multi-SDR Phase Lock (💭)
**Instruments:** SunSDR2 Pro (IQ sidecar, RX) + KiwiSDR (both GPSDO) + phase calibration  
**Use:** Coherent RX signal processing across two independent SDRs

Both have GPSDO → frequency-locked but not phase-locked. Transmit calibration 
tone (using separate TX radio), measure phase offset on both SDR RX streams, 
apply correction in post-processing. Enables:

- **Interferometry:** bearing estimation via phase difference (requires 
  calibration per frequency)
- **Diversity combining:** coherent addition of two antenna signals (max SNR gain)
- **Adaptive beamforming:** null out interference direction

**Limitation:** Phase drift over ~1 minute requires periodic recalibration. Best 
for burst signals or continuously-transmitted carriers.

---

### 14. Wideband IQ Spectrum Stitching (💭)
**Instruments:** SunSDR2 Pro (IQ sidecar, RX) + automated sweep  
**Use:** Capture entire HF spectrum at full IQ resolution

192 kHz RX IQ covers ±96 kHz. To capture 160m-6m (1.8–54 MHz = 52.2 MHz span):
- 273 captures @ 192 kHz steps
- 20 ms settle + 1 s capture per step = **5.7 minutes for full HF survey**
- Stitch IQ into SigMF, build spectrogram

**Outputs:**
- Time-lapse spectrogram: full HF spectrum vs time
- Waterfall movie: "watch 40m band contest activity over 24 hours"
- Signal census: "count all CW/SSB/FT8 stations across all bands"

**Advantage over SSA:** IQ preserves phase → can decode signals in post-processing.  
**Advantage over KiwiSDR:** 19× faster (KiwiSDR ±5 kHz requires 10,440 captures).

---

## Category: Multi-Instrument Coordination

### 15. Radar Cross-Section Measurement (💭)
**Instruments:** IC-9700 (TX CW) + SunSDR2 Pro (RX IQ sidecar) + motor controller  
**Use:** Measure RCS of small objects (PCBs, antennas, etc.)

TX continuous wave via IC-9700, RX on separate antenna via SunSDR IQ sidecar, 
object on motor-controlled turntable. Measure reflected power vs angle. Compute RCS.

**Frequencies:** VHF (2m) for wavelength comparable to PCB sizes.

**Integration:** ESP32 scpi-stepper for turntable, SunSDR TRX 1 (VHF RX via IQ 
sidecar), TX via IC-9700.

---

### 16. Over-the-Air Frequency Response (💭)
**Instruments:** Signal generator (e.g., SDG1062X) + IC-7300/IC-9700 (TX) + SunSDR2 Pro (RX IQ) + KiwiSDR (RX)  
**Use:** Measure antenna/propagation transfer function

TX swept-frequency CW (via radio + external signal generator driving mic input for 
swept tone), RX on both SunSDR and KiwiSDR, compute H(f). Characterizes:
- Antenna bandwidth (VSWR equivalent but via radiated field)
- Propagation multipath (delay spread in impulse response)
- EMI coupling (place antennas near DUT, measure transfer function)

**Advantage:** SunSDR + KiwiSDR both GPSDO-referenced → coherent measurement even 
with independent RX.

---

### 17. Oscilloscope + SDR Triggered Capture (💭)
**Instruments:** SunSDR2 Pro (RX IQ) + SDS2504X Plus (scope)  
**Use:** Time-domain waveform correlated with RF spectrum

Trigger scope on RF event detected by SunSDR RX. Example: transmitter comes on → 
SDR detects carrier → triggers scope to capture PA drain current inrush. Enables:
- TX transient analysis: key click, turn-on overshoot
- Amplifier characterization: correlate RF out (SDR RX) with bias current (scope)
- Interference debugging: capture power supply glitch (scope) at moment of RF 
  spur (SDR RX)

**Implementation:** SunSDR Python script sends scope trigger via SCPI when RX IQ 
power exceeds threshold.

**Enhancement with GPSDO scope sync:** If scope is GPSDO-synced, phase-coherent 
measurements possible (e.g., measure amplifier phase delay at RF).

---

### 18. Three-Receiver Diversity Combining (💭)
**Instruments:** SunSDR2 Pro TRX 0 + TRX 1 + KiwiSDR  
**Use:** Maximum-ratio combining for weak-signal reception

Three independent receivers (all GPSDO-referenced):
- SunSDR TRX 0 → antenna 1 (HF)
- SunSDR TRX 1 → antenna 2 (VHF or second HF)
- KiwiSDR → antenna 3 (HF)

Coherent combining in software: phase-align via calibration tone, weight by SNR, 
sum IQ. Theoretical SNR improvement: 10×log₁₀(3) = 4.8 dB.

**Use cases:**
- Beacon reception: marginal signals become solid copy
- Satellite: combine multiple ground stations for uplink
- EME: every dB matters

---

## Category: Automation & Monitoring

### 19. Unattended Propagation Monitor (💭)
**Instruments:** SunSDR2 Pro + automated scheduler  
**Use:** 24/7 HF propagation logging with zero user intervention

Cron-triggered script cycles through frequencies (e.g., WWV 5/10/15/20/25 MHz, 
amateur beacons, time stations). Logs signal strength + IQ capture every 10 
minutes. Builds long-term propagation database.

**Outputs:**
- Band-open probability heatmap (hour of day × frequency → % chance > S5)
- Seasonal variation plots
- Predictive model: "80m will open to EU in ~2 hours with 85% confidence"

**Integration:** SQLite logging, Grafana dashboard, SMS alert on 6m opening.

---

### 20. Spectrum Occupancy Census (💭)
**Instruments:** SunSDR2 Pro + wideband sweep  
**Use:** Measure band utilization over time

Sweep entire HF spectrum every hour, detect signals (threshold + bandwidth), 
classify (CW/SSB/digital), log. Builds dataset:
- "40m is 73% occupied during contest, 18% normal weeknight"
- "FT8 usage grew 340% year-over-year"
- "20m noise floor rises 6 dB from 9AM-5PM (industrial QRM)"

**Use case:** Regulatory monitoring, spectrum engineering, research.

---

### 21. Multi-Mode Decoder Farm (💭)
**Instruments:** SunSDR2 Pro (IQ sidecar, RX) + parallel decoders  
**Use:** Simultaneously decode multiple modes on one frequency

IQ sidecar (RX stream) → split to multiple decoders (CW, RTTY, PSK31, FT8) running 
in parallel → aggregate all decoded messages. Useful for:
- Contest monitoring: catch CW and SSB contacts on same frequency (split ops)
- Utility monitoring: decode all possible modes, log anything that decodes
- Archaeological mode hunting: "is this FSK or PSK or something else?"

**Implementation:** GNURadio channelizer → N parallel demod chains → unified log.

---

### 22. Interference Geolocation (💭)
**Instruments:** SunSDR2 Pro + IC-9700 + GPS + mobile setup  
**Use:** Drive around, triangulate interference source

Laptop + GPS + two SDRs (SunSDR + IC-9700, both GPSDO) → bearing estimation via 
phase difference (if spaced antennas) or signal strength mapping. Log GPS + 
signal strength → plot heatmap → converge on source.

**Use case:** RFI hunting, repeater interference, spectrum enforcement.

**Integration:** Uses existing `gps/survey` GPS logging, adds SDR power 
measurement.

---

## Implementation Priority

### Immediate (hardware ready, high value):
1. **GPSDO-Referenced Frequency Counter** — validate bench references
2. **GNURadio Live Spectrum Monitor** — unlock custom DSP
3. **Digital Mode Automated Logger** — leverages existing tci-audiopipe work
4. **Wideband IQ Spectrum Stitching** — powerful survey tool

### Near-term (requires minor setup):
5. **Three-Way GPSDO Cross-Check** — bench validation essential
6. **Oscilloscope + SDR Triggered Capture** — enables new measurement class
7. **Unattended Propagation Monitor** — valuable long-term dataset
8. **FreePBX Radio Gateway** — phone integration unlocks remote operation

### Future (requires additional hardware or integration work):
- Multi-SDR diversity combining (need antenna infrastructure)
- Radar cross-section (need turntable)
- Interference geolocation (need mobile setup)
- SSB voice transcription (need Whisper model tuning for ham radio QSO patterns)

---

## Technical Notes

### Audio Sidecar Format
- TCP server (Hamlib listens, client connects)
- Binary format: 8-byte header + audio data
- Header: `stream_type` (1=RX_AUDIO, 2=TX_AUDIO, 3=TX_CHRONO) + sample count
- Audio: int16 PCM, mono, sample rate matches TCI setting (typically 48 kHz)

### IQ Sidecar Format
- Independent TCP server (parallel to audio sidecar)
- Binary format: same 64-byte TCI header + IQ data
- IQ: float32 interleaved I/Q pairs, sample rate 48/96/192/384 kHz
- Use `iq_port` config parameter to enable, `iq_rate` to set sample rate

### GNURadio Integration
```python
# Example: connect to IQ sidecar in GNURadio
from gnuradio import blocks
iq_source = blocks.file_descriptor_source(
    itemsize=gr.sizeof_gr_complex,
    fd=socket.socket().connect(('localhost', IQ_PORT)).fileno(),
    repeat=False
)
```

### Frequency Accuracy Budget
- GPSDO: ±1×10⁻¹² when locked (±0.001 Hz @ 10 GHz)
- SunSDR2 Pro: GPSDO-disciplined, expect <1 Hz error @ 50 MHz
- IC-9700: GPSDO-disciplined
- KiwiSDR: GPSDO-disciplined
- Oscilloscope: Can be GPSDO-synced (currently not configured)

**Implication:** Coherent measurements at HF (0.1-55 MHz) are practical with 
<0.1 Hz frequency uncertainty over multi-second integrations.

---

## Cross-Reference

Related existing projects:
- `projects/sunsdr/tci-audiopipe/` — audio bridge (extends with this work)
- `projects/sunsdr/hf-scanner/` — HF sweep (add IQ recording)
- `projects/radio/phase-noise/` — phase noise measurement (add GPSDO coherence)
- `projects/rtlsdr/classify/` — signal classifier (port to HF/SunSDR)
- `projects/signal-sources/koolertron-cal/` — signal gen cal (use as freq counter)

Related drivers:
- `drivers/sunsdr/` — SunSDR2 Pro TCI driver
- `drivers/icom/` — IC-9700 (GPSDO, VHF/UHF for cross-check)
- `drivers/kiwisdr/` — KiwiSDR (GPSDO, HF diversity/comparison)
- `drivers/gpsd/` — GPS for mobile projects
