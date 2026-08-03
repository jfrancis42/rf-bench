# solsdr project ideas — standalone + rf-bench-integrated

Projects built on **solsdr** (`~/Dropbox/build/solsdr/`, the ExpertSDR3-free
SunSDR2 PRO SDR). The unlock over every other radio on the bench is **full-duplex
of *arbitrary data*: raw IQ in AND raw IQ out, plus audio in and out** — none of
which TCI/ExpertSDR3 can do (TCI cannot transmit IQ at all). That single fact —
*you can synthesize any HF waveform in software and put it on the antenna, while
simultaneously capturing IQ* — is what makes the integrations below possible.

Status markers per `ideas/status-legend.md` (💭 idea · 🔨 spec'd · 🧪 code ·
🔶 partial · ✅ done). Everything here is 💭 unless noted.

Two buckets:
- **Standalone** — solsdr alone (radio + a dummy load or antenna).
- **Integrated** — solsdr + other rf-bench instruments (SSA3032X, SDG1062X,
  SDS2504X, SDM3045X, SPD3303X, NanoVNA-F, RTL-SDR, KiwiSDR, IC-9700, Yertai DC
  load, GPSDO, MQTT bus).

**⚠ TX safety on every "transmit" project below:** dummy load unless you hold the
licence and antenna for that frequency; solsdr will transmit out of band and
enforces nothing legal. Bench work = dummy load + attenuator into the SSA.

---

## Category A — Arbitrary-waveform HF transmit (the TX-IQ superpower)

These are **impossible on the TCI driver** and impossible on the IC-7300/9700/
FT-891 (no IQ transmit). solsdr is the only path.

### A1. Software-defined HF signal generator (💭) ★ flagship
Turn the PRO into a calibrated **HF arbitrary RF source**. Synthesize any
modulation in NumPy — BPSK/QPSK/QAM, MFSK, multitone, chirp, noise, PSK31,
RTTY, arbitrary I/Q — push it to solsdr's TX-IQ server (:5558), out the antenna.
Per-band power cal already gives you calibrated dBm. Replaces a benchtop vector
signal generator for HF at a fraction of the cost.
**Integrated:** verify output on the **SSA3032X** (via the TX tap/attenuator);
close the loop so the tool auto-levels to a requested dBm.

### A2. Two-tone IMD / IP3 test source (💭)
Generate a clean two-tone (e.g. 700 + 1900 Hz SSB, or two RF tones) in IQ, key
it, and measure 3rd/5th-order IMD products on the **SSA3032X**. Characterizes the
PRO's own PA linearity vs. drive, *and* becomes a portable two-tone source to
test external HF amplifiers/preamps. Sweep drive → IMD-vs-power curve automatically.

### A3. Transmit-side channel simulator (💭)
Impress fading, multipath, Doppler, and AWGN onto a clean signal *in IQ* before
transmitting — a real over-the-air (or over-the-coax-to-a-receiver) channel
emulator. Feed a known signal through a synthesized ionospheric channel (Watterson
model) and transmit it to a second receiver (RTL-SDR / KiwiSDR / IC-9700) to test
how modems cope. Bench version: solsdr TX → attenuator → RTL-SDR RX.

### A4. Arbitrary digital-mode transmitter (no app) (💭)
Encode FT8/FT4/JS8/WSPR/RTTY/PSK31 frames directly to IQ in Python and transmit
them — no WSJT-X, no soundcard, no modulator round-trip. Bit-exact control of the
transmitted waveform for protocol experiments (custom FEC, non-standard symbol
rates, deliberate impairments). Decode on a second receiver to verify.

### A5. Beacon / propagation sounder (💭)
Scheduled arbitrary-waveform beacon: transmit a known chirp or PN sequence at
timed intervals across bands, correlate at a remote receiver for path loss and
delay spread. Cron-driven via the bench scheduler; log to the MQTT bus / SQLite.

### A6. Radar / ranging experiments (💭)
FMCW or pulsed-CW chirp out on TX-IQ, capture the return on RX-IQ (or a second
SDR), correlate for range. HF ground-wave or NVIS ranging; or short-range
coax/cable-fault (TDR-style) with a directional coupler. Full control of the
transmitted chirp is the enabler.

---

## Category B — Full-duplex IQ (TX and RX at once, two radios)

solsdr can transmit from one radio/port while another receiver captures — the
basis for true measurement loops.

### B1. Closed-loop HF network analyzer (scalar) (💭) ★
solsdr TX-IQ sweeps a stepped or chirped tone across a band; a second receiver
(RTL-SDR, KiwiSDR, or solsdr RX2) captures amplitude → **transmission response of
whatever's between them**: an antenna+feedline, a filter, a coupler. It's a poor-
man's scalar network analyzer *at real antenna power over the real path*, where
the NanoVNA only does bench-level S-parameters.
**Integrated:** cross-check the passband against the **NanoVNA-F** on the bench.

### B2. Antenna pattern / gain vs. azimuth (💭)
Transmit a steady calibrated carrier (A1) while a rotator turns the antenna;
log received power at a fixed remote receiver vs. azimuth → measured azimuth
pattern. Or reciprocal: receive a remote beacon while rotating. Ties to the
station-monitor / MQTT logging already in rf-bench.

### B3. Real-time adaptive noise cancelling (dual-RX) (💭)
Two phase-coherent receivers (RX1 = antenna, RX2 = noise-sense antenna, γ²≈0.999
verified). LMS-adapt RX2 against RX1 to null local noise in software — a true
software MFJ-1026. Needs two separate antennas; the measured coherence is what
makes the phase subtraction valid.

### B4. Direction finding / interferometry (dual-RX) (🔶 in progress — `projects/solsdr/df/`)
Phase-coherent RX1/RX2 on two spaced antennas → phase-difference bearing on a
signal. **Built + validated offline (2026-07-09); awaiting two antennas (~1-2
weeks) for the first live bearings.** In `projects/solsdr/df/`:
- **Phase 0 DONE, on hardware:** γ²≈1.000, phase-noise floor **~0.1°** on a
  steady carrier (`df.py`). The receivers are nowhere near the limiting factor.
- **Calibration model MEASURED:** inter-channel phase is FLAT vs frequency
  (δ≈0, scalar offset −32.77° across 312.5 kHz — `phasecal.py`), so per-session
  calibration is a single scalar (refuted an earlier freq-dependent guess).
- **Full pipeline built + tested with NO hardware** (`test_df.py`, 23 checks):
  `geometry.py` (Δφ↔bearing, aliasing/mirror ambiguity, error propagation),
  `simulate.py` (two-channel IQ for a known arrival — the ground-truth fixture),
  `bearing.py` (engine + refuse-until-calibrated gate, single- and dual-baseline
  360° azimuth), `df_offline.py` (recovers known bearings to ~0.01–0.1°).
- **Uses the direct radio callback** (sample-aligned dual-RX), NOT the network IQ
  servers — alignment matters for the phase observable. Runs on the radio host.
- **Next (needs antennas):** see `README.md` "▶ RESUME HERE". Open decision:
  physical baseline length (≤~10.5 m at 20 m for unambiguous single-baseline) and
  single- vs dual-baseline. HF DF is hard (skywave); best on strong groundwave.

---

## Category C — Measurement & calibration loops (solsdr + bench instruments)

### C1. GPSDO-referenced frequency counter / source cal (💭)
The PRO's GPSDO-locked LO makes it a sub-Hz frequency reference. Measure any
source (SDG1062X, Koolertron DDS, an oscillator under test) by capturing its
tone in RX-IQ and reading the FFT peak (10 s capture → 0.1 Hz bins). Report
offset in Hz/PPM and Allan deviation. **Cross-validate** against the KiwiSDR
(also GPSDO). Also runs the *other* direction: transmit a GPSDO-locked carrier
(A1) as a calibration tone for other receivers.

### C2. Receiver MDS / noise-figure bench (💭)
Automated: **SDG1062X** or the A1 TX source injects a known calibrated level
(through step attenuators / the SSA tracking source) into the PRO's RX; solsdr
measures SNR in IQ; sweep level → MDS and noise figure vs. frequency. The DC load
/ PSU aren't needed, but the SDM3045X can log supply while you're at it.

### C3. PA efficiency & thermal characterization (💭) 🔶 partial
Already partly done in solsdr's own cal (DC-input efficiency cross-check). Extend
with the bench: **SPD3303X** or shack supply feeds the PRO through the **SDM3045X**
(or a current shunt) for precise keyed DC input; SSA reads RF output via the tap;
compute η = P_rf / P_dc vs. band and drive; log temperature from solsdr's 0x1F
telemetry. Produces the definitive efficiency + thermal map of the PRO's final.

### C4. Automated per-band TX power calibration with the SSA (💭)
Close solsdr's manual wattmeter-anchored cal loop: script steps drive 0→255 per
band, reads the **SSA3032X** through the calibrated TX tap, and writes
`tx_power_cal.json` automatically — no hand-reading a wattmeter. Uses the tap-loss
table already characterized in `ideas/hardware.md`.

### C5. Filter / preamp sweep at power (💭)
A1 as the source, SSA (or RX2) as the detector: sweep an external HF band-pass
filter, LPF, or preamp and plot insertion loss / gain across the band, at real
power levels the NanoVNA can't provide. Relay board (`arduino_relay_board`)
switches DUTs for an automated multi-filter sweep.

### C6. Phase-noise measurement of the PRO LO (💭)
Capture a GPSDO-locked CW carrier in RX-IQ (or transmit one and receive on a
reference SDR), compute the phase-noise spectrum. Compare against the SSA's own
phase-noise measurement. (There's an existing `projects/sunsdr/phase-noise/` for
the TCI path — this is the direct-IQ, ExpertSDR3-free version.)

---

## Category D — Audio-domain integrations (bidirectional audio bridge)

solsdr's virtual PulseAudio sinks (`solsdr-rx` / `solsdr-tx`) route demodulated
RX audio out and app TX audio in — a full soundcard-modem interface with no
ExpertSDR3.

### D1. Headless digital-mode station (💭) 🔶 works today
JS8Call / WSJT-X / fldigi already run against solsdr's bridge + rigctld with no
GUI radio software. Package it as a bench "appliance" service (systemd units
already exist): FT8/JS8/WSPR RX+TX on any HF band, remotely controlled. The
rf-bench angle: log all decodes to the **MQTT bus** and SQLite, correlate with
GPS/weather (Kestrel) for propagation studies.

### D2. HF↔VoIP / SIP bridge (💭)
Bridge solsdr RX/TX audio to a SIP extension (there's a FreePBX on the bench and
a prior `tci-sipphone` concept). Listen to / transmit on HF SSB from a softphone,
or auto-patch a remote net. solsdr replaces the TCI sidecar with a verified,
lower-latency path.

### D3. Soundcard-DSP chain over the air (💭)
The 45 soundcard-DSP projects (`ideas/soundcard-dsp-projects.md`) currently
process audio locally. Feed their output to `solsdr-tx` and their input from
`solsdr-rx` to run any of them *on live HF*: noise reduction on real received
SSB, a spatial-audio panorama of a busy band, an over-the-air vocoder, etc.

### D4. Automated audio-chain / SINAD tester for the PRO (💭)
A1 transmits a standard audio-modulated test signal; the SDS2504X or SDM3045X
(or software) measures recovered audio SINAD/THD after RX demod → receiver audio
quality vs. signal level and mode. Reuses the `projects/audio/` framework.

---

## Category E — Spectrum, monitoring, and the no-GUI panadapter

### E1. Networked panadapter feed (🔶 partial) ★ most on-brand
solsdr is no-GUI by design and streams raw IQ. **A standalone client panadapter
now exists** — `clients/panadapter.py` in the solsdr tree (PyQt/pyqtgraph, does
its own FFT off the :5555 stream): live spectrum + waterfall, auto/fixed scaling,
mouse readout, radio info bar, display-only. Still 💭 on the *server* side: a
thin service that FFTs the IQ and publishes power-spectrum bins over WebSocket/
MQTT, so a truly thin display (a `virtual/waterfall` panel, a browser, BenchView)
needs no local DSP and directly feeds rf-bench's existing virtual panels.

### E2. Wideband band-occupancy logger (💭)
At 312.5 kS/s, one capture covers a big chunk of a band. Periodically scan the
HF bands, measure occupancy/energy per sub-band, log to MQTT+SQLite for a
long-term "what's active when" propagation/usage database. Cross-reference the
GPSDO clock for precise timestamps.

### E3. Multi-SDR diversity / band-opening detector (💭)
Combine solsdr (HF) + RTL-SDR (VHF/UHF) + KiwiSDR (remote HF) into one monitor;
detect band openings by watching SNR of known beacons across all three, alert via
the MQTT alert daemon / SMS. Extends `projects/sunsdr/band-opening-relay/`.

### E4. IQ recorder with scheduled/triggered capture (💭)
A proper recording service (solsdr only has one-shot `capture_iq.py`): scheduled,
level-triggered, and rotating-buffer IQ capture to SigMF (mirror the RTL-SDR
recorder in `projects/rtlsdr/recorder/`). Records the raw 24-bit PRO IQ for later
replay — including replay back *out* the TX-IQ path.

---

## Suggested first builds

1. **A1 Software-defined HF signal generator** — the flagship; unlocks A2–A6 and
   half of Category C, and shows off the TX-IQ capability nothing else has.
2. **E1 Networked panadapter feed** — most aligned with the no-GUI design; makes
   solsdr pleasant to use and plugs into existing virtual panels.
3. **C4 Automated TX power cal with the SSA** — closes a loop that's currently
   manual, and is low-risk (bench-only, dummy load + tap).
4. **B1 Closed-loop scalar HF network analyzer** — the clearest "1+1=3" of
   solsdr TX-IQ + a second bench receiver.
