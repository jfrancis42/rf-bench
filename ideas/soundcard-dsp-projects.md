# Soundcard DSP Projects

Audio-frequency signal processing via the PC soundcard (or USB audio
interface). NOT digital-mode modems — these are filters, noise
reducers, analyzers, and signal-enhancement tools for ham radio and
bench use.

All projects assume Linux ALSA/PipeWire, numpy/scipy for DSP, and
real-time streaming via `sounddevice` or PyAudio. All projects live
under `projects/soundcard/`.

## Status: ALL 45 PROJECTS BUILT (2026-07-01)

All projects below are implemented in `projects/soundcard/`, each with
a .py script and README.md. They share a common framework (`dsp_pipeline/`)
providing DSPBlock base class, Pipeline chaining, AudioStream I/O,
TestSignal factory, and standard CLI arguments.

### Batch 2: Mic + Headphones Ambient/Nature (12 projects, 2026-06-30)
- `bat-heterodyne/` — Ultrasonic bat detector (heterodyne + freq divider)
- `bird-time-stretch/` — Phase vocoder time-stretch for birdsong
- `auto-tune-reality/` — Pitch-correct ambient sounds to musical scales
- `vocoder-nature/` — Channel vocoder (nature modulates synth carrier)
- `acoustic-magnifier/` — Narrowband resonant amplifier with sweep
- `doppler-speed/` — Acoustic Doppler speed measurement (YIN pitch)
- `resonance-finder/` — Impulse response → resonant mode identification
- `insect-classifier/` — Classify insects by wingbeat frequency
- `reverse-reality/` — Time-reverse ambient audio chunks in real-time
- `rain-classifier/` — Rain intensity classification (spectral features)
- `spatial-exaggerator/` — Exaggerate stereo ITD/ILD for superhuman hearing
- `beat-looper/` — Capture percussive transients → quantized rhythm loop

### Batch 3: Radio Simulation (1 project, 2026-07-01)
- `ssb-sim/` — SSB radio signal simulator (bandwidth, noise, AGC, fading)

---

## Real-time noise reduction

### Spectral subtraction noise reducer

Classic two-pass approach: sample the noise floor during a quiet
interval (operator presses a key, or auto-detect no-signal), build a
noise spectral profile, subtract it frame-by-frame from live audio.
Same algorithm as the old TimeWave DSP-599zx. Works best on
stationary noise (hiss, fan noise, band noise); poor on impulse noise.

Parameters: noise-floor capture duration, subtraction depth (dB),
spectral floor (prevents musical artifacts from over-subtraction).

### LMS adaptive noise cancellation

Two-input design: primary mic/radio audio + reference mic picking up
ambient noise (fan, AC, computer). LMS algorithm adapts filter taps to
predict and subtract the correlated noise component. Classic Widrow
approach. Works on non-stationary noise that spectral subtraction
can't handle (intermittent fans, people talking nearby).

Requires a second audio input — USB soundcard with stereo line-in
works (one channel = signal, one channel = reference).

### Impulse noise blanker

Detect short-duration impulse spikes (ignition noise, switching PSU
clicks, LED dimmer hash) by amplitude threshold + duration test. Blank
the spike by interpolating adjacent samples (linear or AR-model
prediction). Operates in time domain — much faster than spectral
methods.

Parameters: threshold (dB above RMS), max blank duration (ms), attack
time, interpolation method (zero-fill, linear, AR-extrapolate).

### Wiener filter (optimal SNR)

Estimate signal and noise power spectra, apply the frequency-domain
Wiener gain H(f) = Pss/(Pss + Pnn) per bin. Theoretically optimal
linear filter for stationary signals in stationary noise. More
mathematically rigorous than spectral subtraction; fewer musical
artifacts.

Can cascade with the impulse blanker: blank first (time-domain), then
Wiener-filter (frequency-domain).

---

## Audio filters (real-time)

### Adaptive CW bandpass filter

Tight audio bandpass (user-selectable 25–500 Hz bandwidth) that
auto-tracks the CW tone via a PLL or peak-detector. Sharper than any
radio's built-in IF filter. The AFC tracking means you don't lose the
signal when the other station drifts.

Outputs: filtered audio to speakers + optional decoded-text estimate
(threshold + Farnsworth timing from the cw-modem library).

### Automatic heterodyne notch filter

Detect steady-state carriers (birdies, adjacent-channel heterodynes,
tuner-upper carriers) via spectral peak detection, spawn a narrow IIR
notch at each detected frequency. Track frequency drift. Remove up to
N simultaneous heterodynes without affecting the desired signal.

Similar to the auto-notch in high-end radios (Icom's twin PBT, Yaesu's
contour) but in software with unlimited notch count.

### Parametric equalizer for receiver audio

N-band parametric EQ (center frequency, Q, gain per band) for shaping
receiver audio to taste. Useful for:
- Compensating tinny laptop speakers when operating portable
- Matching headphone frequency response to hearing-aid audiogram
- Cutting 3 kHz+ hiss on AM broadcast
- Boosting low-frequency presence on SSB

Store presets per mode (CW, SSB, AM, FM).

### De-hum filter (50/60 Hz comb)

Detect fundamental hum frequency (50 or 60 Hz, auto-detected via
spectral peak), notch it and all harmonics up to N (typically 10–20
harmonics covers everything audible). Very narrow IIR notches (~1 Hz
BW) so speech/music damage is negligible.

Solves ground-loop hum, RF-contaminated audio cables, and poorly
filtered shack PSUs — all common in ham installations.

### Bandpass slicer / audio crossover

Split incoming audio into N frequency bands, route each to a
different output or apply independent processing. Use cases:
- CW pile-up: route low-pitched signals left, high-pitched right
  (poor man's binaural CW)
- Separate a CW signal at 600 Hz from QRM at 800 Hz into
  different headphone ears
- Feed a narrow slice to a decoder while full audio goes to
  speakers

---

## Binaural / spatial audio

### Binaural CW processor

Mono CW audio in → stereo out with frequency-dependent spatial
positioning. Each CW signal at a different audio pitch appears to
come from a different direction in the headphone soundstage.
Dramatically improves pile-up copy by leveraging the brain's spatial
separation (cocktail-party effect).

Implementation: per-frequency-bin ITD (interaural time delay) and ILD
(interaural level difference) applied via short FIR HRTF filters.

### Stereo field expander for SSB

Take mono SSB audio, synthesize a pseudo-stereo field via comb
filtering or Haas effect. Reduces listener fatigue on long ragchews.
Purely cosmetic — no information gain — but noticeably more
comfortable.

---

## Audio analysis and measurement

### Real-time audio spectrum analyzer

Live scrolling spectrum + optional waterfall of soundcard input.
Useful for:
- Monitoring radio audio output for birdies or spurs
- Verifying transmit audio bandwidth before going on-air
- Checking microphone frequency response
- Identifying interference sources by their spectral signature

Configurable FFT size, averaging, peak hold, dBFS or dBV scale.
Output to terminal (ASCII art), matplotlib live window, or headless
CSV logging.

### Audio THD+N analyzer

Inject a sine tone (from SDG1062X or soundcard output looped back),
measure THD+N of the captured signal. Separates harmonic distortion
from noise floor. Reports THD as percentage and dB, plus individual
harmonic levels (2nd through 10th).

Use cases: characterize radio receiver audio chain distortion,
verify soundcard quality, test audio amplifier stages, measure
microphone preamp THD.

### Two-tone IMD generator + analyzer

Generate two equal-amplitude tones (e.g., 700 + 1900 Hz — the
standard SSB two-tone test) from the soundcard output, feed into
radio mic input, capture transmitted audio (via monitor output or
second radio), measure 3rd/5th/7th-order IMD products.

Automated transmitter linearity test without an external two-tone
generator. Works with any radio that accepts line-level audio input.

### Audio SNR meter

Real-time signal-to-noise estimation. Methods:
- SINAD (signal + noise + distortion to noise + distortion ratio)
  for FM receiver sensitivity measurement
- Carrier-to-noise for AM
- Signal-present/signal-absent gated measurement for SSB

Reports in dB; optional threshold-triggered logging for long-term
monitoring.

### Audio frequency response sweeper

Sweep a tone from 20 Hz to 20 kHz (or narrower) through the DUT
(radio audio chain, amplifier, filter), capture at the other end,
plot magnitude and phase response. Essentially a Bode plot at audio
frequencies using the soundcard as both source and analyzer.

Can use the SDG1062X as the source for better amplitude accuracy, or
soundcard-only for a self-contained portable solution.

---

## Transmit audio processing

### Speech compressor / clipper

Real-time speech processing chain for SSB transmit:
1. High-pass filter (remove sub-200 Hz rumble)
2. Compressor (reduce dynamic range, adjustable ratio + threshold)
3. Hard clipper or soft clipper (add ~6 dB of speech power)
4. Low-pass filter at 2700 Hz (remove clipper harmonics)
5. Output level control

Equivalent to an outboard speech processor (Heil ProSet, W2IHY
EQplus, etc.) but in software. Feed output to radio's line-in or
USB audio input.

### VOX with anti-trip filtering

Software VOX that triggers PTT based on audio level, but with
configurable filtering to reject:
- Keyboard clicks
- Background music
- Fan noise

Uses a frequency-weighted detector (speech energy is 300–3000 Hz;
ignore energy outside that band). Adjustable delay, hang time, and
anti-trip threshold.

### Audio delay line

Add a precise, adjustable delay (0–2000 ms in 1 ms steps) to the
audio path. Use cases:
- Synchronize multiple audio sources (e.g., WebSDR + local radio)
- Test echo-cancellation algorithms
- Simulate propagation delay for contest practice
- Break-in delay matching for CW full-QSK operation

---

## Decoding / detection (non-modem)

### CTCSS / DCS encoder-decoder

Detect and display CTCSS sub-audible tones (67.0–254.1 Hz) or DCS
codes in received FM audio. Also generate CTCSS/DCS on transmit
audio output. Useful for:
- Identifying which repeater tone an unknown signal is using
- Adding tone encode to a radio that lacks it (old Motorola mobiles)
- Monitoring multiple tones simultaneously

### DTMF decoder

Goertzel-algorithm DTMF detection on received audio. Logs digits
with timestamps. Use cases:
- Decode repeater control codes
- Autopatch number logging
- Identify DTMF-based selective calling (pre-P25 era)

### Selective calling tone decoder

Sequential tone signaling (two-tone, five-tone, CCIR/ZVEI) used by
commercial/public-safety radios pre-digital era. Detect the tone
sequence and display the called ID. Pairs with the selcall project
at `~/selcall/` for the transmit side.

### Signal-presence detector / squelch

Carrier-detect / signal-presence algorithm for raw audio streams
(no FM discriminator squelch available). Methods:
- Energy threshold (simple, fast)
- Spectral flatness (speech has peaks; noise is flat)
- Autocorrelation (voice is quasi-periodic; noise is not)

Outputs: squelch gate for recording, PTT trigger for relay, or
event log with timestamps.

---

## Recording and capture

### Triggered audio recorder

Like a scope trigger for audio: continuously buffers the last N
seconds in a ring buffer. When signal is detected (level, spectral,
or squelch-open trigger), saves pre-trigger + post-trigger audio
to a WAV/FLAC file with UTC timestamp filename.

Automatically captures interesting signals without recording hours
of dead air. Configurable pre-trigger (1–30 s) and post-trigger
hang (1–60 s).

### Scheduled recorder with metadata

Cron-friendly: record audio for a specified duration at a specified
time. Tags output files with frequency, mode, antenna, and any
other metadata. Builds a searchable archive of band activity over
time.

Pairs with radio drivers — can auto-tune the radio to a specific
frequency before recording, then move to the next frequency.

### Wideband audio spectrogram logger

Continuous FFT of soundcard input → PNG spectrogram image saved
hourly/daily. Visual record of band activity. Low storage cost
(one PNG per hour vs. gigabytes of raw audio). Useful for:
- Identifying periodic interference patterns
- Documenting repeater activity timing
- Spotting band openings in archived spectrograms

---

## IQ-to-binaural stereo converter

Accept stereo L/R I/Q audio (the standard convention where Left = I,
Right = Q) from a radio or SDR's analog output, and produce binaural
stereo audio for headphones. The I/Q pair represents a complex
baseband signal; by applying a frequency-dependent stereo panning,
signals at different offsets from the carrier appear to come from
different positions in the stereo field.

Implementation: FFT the complex IQ stream, map each frequency bin to
a pan position (e.g., −3 kHz = hard left, 0 = center, +3 kHz = hard
right), apply HRTF-style ITD/ILD per bin, IFFT back to stereo audio.
The result is that stations on opposite sides of the passband sound
spatially separated — dramatically improves intelligibility in
pile-ups and crowded bands.

Modes:
- **Linear pan:** frequency offset maps linearly to stereo position.
  Simple, effective.
- **Logarithmic pan:** compresses near-zero offsets, expands edges.
  Better for CW where signals cluster near the BFO.
- **Discrete binning:** assign fixed spatial slots to detected
  signals (nearest-neighbor clustering). Each station gets its own
  "chair" in the soundstage.

Input: any stereo soundcard input carrying L=I, R=Q (e.g., IC-7300
"I/Q output" mode, SDRplay, RTL-SDR via `rtl_fm -E direct` with
I/Q to soundcard, or a SoftRock receiver).

Parameters: passband width, pan law (linear/log/discrete), HRTF
model (simple ITD or measured HRTF), output sample rate.

---

## Voice activity detection (VAD) squelch

Audio-domain squelch that opens ONLY for human speech — ignores data
bursts, SSTV, RTTY, CW, pager signals, and noise. Useful on scanner
feeds, busy repeaters with mixed traffic, or HF monitoring where you
want to record/alert only on voice activity.

Detection features:
- **Spectral envelope:** human speech has formant peaks (F1 ~300–900
  Hz, F2 ~900–2500 Hz, F3 ~2500–3500 Hz) with valleys between them.
  Data signals and noise have flat or wrong-shaped envelopes.
- **Periodicity / pitch:** voiced speech has strong autocorrelation
  at the fundamental frequency (80–400 Hz). Noise and most data
  modes do not.
- **Zero-crossing rate:** speech alternates between high ZCR
  (unvoiced consonants) and low ZCR (vowels). Pure noise has
  uniformly high ZCR; data tones have uniformly low ZCR.
- **Modulation rate:** speech amplitude varies at syllabic rate
  (3–8 Hz). Steady carriers, data tones, and noise lack this
  modulation pattern.

Can use a simple heuristic combination of the above, or a small
pre-trained neural network (WebRTC VAD is BSD-licensed and tiny — a
few hundred KB, runs in real-time on any CPU).

Outputs: gate signal (open/close), confidence score (0–1), optional
classification label (speech / music / data / noise). Feed the gate
to the triggered recorder for speech-only capture.

---

## Integration with rf-bench instruments

### Soundcard-as-instrument calibration

Characterize the PC soundcard itself as a measurement instrument:
- Frequency response (loopback: output → input)
- THD+N floor
- Dynamic range / noise floor
- Channel crosstalk
- Sample-clock accuracy (vs GPS PPS or SDG reference)

Store results as a cal file; other soundcard projects apply the
correction automatically.

### Radio audio chain automated test

End-to-end automated test sequence:
1. SDG1062X injects calibrated tone into radio antenna input (via
   attenuator)
2. Soundcard captures radio's audio output
3. Measure: frequency response, THD, SNR, AGC response time, audio
   bandwidth, filter shape

Produces a PDF report of receiver audio performance. Pairs with
`projects/radio/receiver-test/` which does the same thing at RF
but doesn't characterize the audio chain specifically.

### Microphone frequency response

Play a known sweep (pink noise or log-sweep) from a calibrated
speaker, capture on the microphone under test via soundcard. Compute
transfer function. Compare against a reference mic to get relative
response. Useful for evaluating ham radio desk mics and headsets.

---

## Utility / infrastructure

### Real-time DSP pipeline framework

A common framework that all the above projects can plug into:
- PipeWire/JACK client that inserts between any source and sink
- Chain multiple DSP blocks in series (e.g., blanker → notch →
  compressor → EQ)
- Hot-swap blocks without glitching
- REST API on localhost for remote control from other rf-bench
  scripts
- Terminal UI showing levels, spectrum, and active block status

This would be the audio equivalent of the ESP32 SCPI framework —
a standard harness that individual DSP algorithms plug into.

### Audio loopback null test

Route processed audio back into the input, subtract the original,
measure the residual. Quantifies what a DSP block is *adding* to
or *removing* from the signal. Essential for validating that noise
reduction isn't eating the signal along with the noise.

---

## Hardware notes

- **Soundcard selection:** Any USB audio interface with line-in
  works. For serious measurement, something with known specs
  (Focusrite Scarlett, Behringer UMC series) gives <-100 dBFS noise
  floor and flat response 20 Hz–20 kHz. The laptop's built-in HDA
  codec works for casual use but has higher noise and uncalibrated
  gain.
- **Radio connection:** Most modern radios have USB audio (IC-7300,
  IC-9700). Others need a cable from the radio's headphone/line-out
  jack to the soundcard's line-in. For transmit processing, connect
  soundcard line-out to radio mic/line-in (or use USB audio for
  radios that support it).
- **Latency:** PipeWire with 256-sample buffers at 48 kHz gives
  ~10 ms round-trip. Adequate for all monitoring/analysis tasks.
  For live filtering in the audio path (e.g., noise reduction
  between radio and headphones), verify latency is acceptable —
  >50 ms is noticeable on voice.
- **Sample rate:** 48 kHz is standard and sufficient for all ham
  audio (which tops out at 3 kHz for SSB, 5 kHz for AM). 96 kHz
  only needed for hi-fi music applications or ultrasonic work.

## Dependencies

- `sounddevice` (PortAudio wrapper) or `pyaudio`
- `numpy`, `scipy` (filtering, FFT, signal processing)
- `matplotlib` (for analysis/spectrogram output)
- Optionally: `jack` or PipeWire for inter-application routing
