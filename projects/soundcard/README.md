# projects/soundcard/ — Soundcard DSP Projects

45 audio DSP projects built on a shared framework (`dsp_pipeline/`), all
using the PC soundcard as both signal source and measurement instrument.

## Framework

All projects share `dsp_pipeline/` which provides:
- `DSPBlock` — base class for processing blocks (subclass, override `process()`)
- `Pipeline` — chains blocks, supports real-time and offline modes
- `AudioStream` — sounddevice wrapper with device selection
- `TestSignal` — synthetic signal factory (sine, sweep, noise, DTMF, etc.)
- `add_audio_args` / `add_test_args` — shared CLI argument helpers

Every project supports `--test` mode (no hardware needed) and `--list-devices`.

## Project Status

| # | Project | Category | Description |
|---|---------|----------|-------------|
| 1 | `spectral-subtraction/` | Noise reduction | Spectral subtraction noise gate |
| 2 | `lms-noise-cancel/` | Noise reduction | Two-input LMS/NLMS adaptive canceller |
| 3 | `impulse-blanker/` | Noise reduction | Impulse detection + interpolation |
| 4 | `wiener-filter/` | Noise reduction | Optimal Wiener gain noise filter |
| 5 | `cw-bandpass/` | Filters | Adaptive CW bandpass with AFC |
| 6 | `auto-notch/` | Filters | Multi-carrier auto-detect notch |
| 7 | `parametric-eq/` | Filters | N-band parametric EQ with radio presets |
| 8 | `dehum/` | Filters | 50/60 Hz + harmonics auto-notch |
| 9 | `bandpass-slicer/` | Filters | Audio crossover with per-band panning |
| 10 | `binaural-cw/` | Spatial | Frequency-to-pan CW spatializer |
| 11 | `stereo-expander/` | Spatial | Pseudo-stereo (Haas/comb/allpass) |
| 12 | `iq-binaural/` | Spatial | Complex IQ → binaural stereo |
| 13 | `vad-squelch/` | Detection | Voice activity detection squelch |
| 14 | `signal-detector/` | Detection | General signal presence detector |
| 15 | `vox-filter/` | Detection | Speech-band anti-trip VOX |
| 16 | `ctcss-codec/` | Decode/encode | CTCSS tone encode/decode (50 tones + DCS) |
| 17 | `dtmf-decoder/` | Decode | DTMF digit decoder (Goertzel) |
| 18 | `selective-call-decoder/` | Decode | CCIR/ZVEI/EIA sequential tone decoder |
| 19 | `snr-meter/` | Measurement | SINAD/SNR/carrier-noise meter |
| 20 | `thd-analyzer/` | Measurement | THD+N with harmonic analysis |
| 21 | `two-tone-imd/` | Measurement | Two-tone IMD generator + analyzer |
| 22 | `freq-response/` | Measurement | Frequency response sweeper (Bode) |
| 23 | `spectrum-analyzer/` | Measurement | Live spectrum + waterfall + PDF |
| 24 | `spectrogram-logger/` | Recording | Continuous spectrogram PNG logger |
| 25 | `triggered-recorder/` | Recording | Level-triggered audio recorder |
| 26 | `scheduled-recorder/` | Recording | Time-scheduled recorder + radio control |
| 27 | `audio-delay/` | Utility | Precision delay line (circular buffer) |
| 28 | `speech-compressor/` | TX processing | 5-stage TX audio processor |
| 29 | `soundcard-cal/` | Calibration | Soundcard self-calibration (loopback) |
| 30 | `mic-response/` | Calibration | Microphone frequency response |
| 31 | `radio-audio-test/` | Calibration | End-to-end radio audio chain test |
| 32 | `audio-loopback-null/` | Calibration | Null test (subtract original, measure residual) |
| 33 | `bat-heterodyne/` | Ambient/Nature | Ultrasonic bat detector (heterodyne + freq divider) |
| 34 | `bird-time-stretch/` | Ambient/Nature | Time-stretch bird songs (phase vocoder) |
| 35 | `auto-tune-reality/` | Ambient/Nature | Pitch-correct ambient sounds to musical scales |
| 36 | `vocoder-nature/` | Ambient/Nature | Channel vocoder (nature modulates synth carrier) |
| 37 | `acoustic-magnifier/` | Ambient/Nature | Narrowband resonant amplifier (sweep scanner) |
| 38 | `doppler-speed/` | Ambient/Nature | Acoustic Doppler speed measurement (YIN pitch) |
| 39 | `resonance-finder/` | Ambient/Nature | Impulse response → resonant mode identification |
| 40 | `insect-classifier/` | Ambient/Nature | Classify insects by wingbeat frequency |
| 41 | `reverse-reality/` | Ambient/Nature | Time-reverse ambient audio chunks in real-time |
| 42 | `rain-classifier/` | Ambient/Nature | Rain intensity classification (spectral features) |
| 43 | `spatial-exaggerator/` | Ambient/Nature | Exaggerate stereo ITD/ILD for superhuman hearing |
| 44 | `beat-looper/` | Ambient/Nature | Capture transients → quantized rhythm loop |
| 45 | `ssb-sim/` | Radio Simulation | SSB signal simulator (bandwidth, noise, AGC, fading) |

## Categories

### Noise Reduction (4)
Audio noise reduction for weak-signal reception: spectral subtraction,
LMS adaptive cancellation, impulse blanking, Wiener filtering.

### Filters (5)
Frequency-selective processing: CW bandpass with AFC, auto-notch for
interfering carriers, parametric EQ with radio presets, 50/60 Hz hum
removal, audio crossover/slicer.

### Spatial Audio (3)
Stereo/binaural processing: CW frequency-to-pan, stereo widening
(Haas/comb/allpass), IQ-to-binaural for SDR receivers.

### Detection & Squelch (3)
Signal presence detection: multi-feature VAD squelch, general-purpose
signal detector (energy/spectral/autocorrelation), speech-optimized VOX.

### Decode/Encode (3)
Tone signaling: CTCSS (50 tones + DCS), DTMF (16 digits), sequential
selective calling (CCIR/ZVEI/EIA five-tone and two-tone).

### Measurement (4)
Audio measurement instruments: SINAD/SNR meter, THD+N analyzer,
two-tone IMD (IP3), frequency response sweeper.

### Spectrum & Recording (3)
Long-duration capture: live spectrum analyzer with waterfall,
continuous spectrogram logger (PNG rotation), level-triggered and
time-scheduled recorders.

### TX Processing & Utility (2)
Transmit audio: 5-stage speech compressor (HPF, compression, clipping,
LPF, leveling). Utility: precision audio delay line.

### Calibration & Test (4)
System characterization: soundcard self-cal (noise floor, THD,
crosstalk, freq response), microphone response measurement, end-to-end
radio audio chain test (SDG or soundcard stimulus), loopback null test.

### Ambient/Nature (12)
Mic + headphones creative projects: bat detection (heterodyne, frequency
division), bird song time-stretching (phase vocoder), auto-tune reality
(pitch-correct to scales), channel vocoder (nature-modulated synth),
acoustic magnifier (resonant boost + sweep), Doppler speed measurement,
resonance finder (impulse response), insect classifier (wingbeat),
reverse reality (backwards audio), rain classifier (spectral features),
spatial exaggerator (ITD/ILD widening), beat looper (transient capture
→ rhythm grid).

### Radio Simulation (1)
SSB signal simulator: bandwidth limiting (6 presets from 300 Hz CW to
3.5 kHz AM-equivalent), receiver noise, AGC with pumping, frequency
offset (mis-tune), and selective fading for propagation simulation.

## Quick start

```bash
cd projects/soundcard

# Run any project in test mode (no hardware)
python spectrum-analyzer/spectrum_analyzer.py --test --pdf spectrum.pdf
python thd-analyzer/thd_analyzer.py --test --pdf thd.pdf
python cw-bandpass/cw_bandpass.py --test

# Real-time with audio device
python spectral-subtraction/spectral_subtraction.py --input-device 2 --output-device 2
python vad-squelch/vad_squelch.py --input-device 2 --output-device 2

# List available audio devices
python dsp_pipeline/stream.py --list-devices
```

## Dependencies

All projects require:
- `numpy`
- `scipy`
- `sounddevice` (live audio; not needed for --test mode)
- `matplotlib` (PDF/plot output)

Some projects additionally use:
- `soundfile` (WAV/FLAC I/O — triggered-recorder, scheduled-recorder, speech-compressor)
- `rf_bench.siglent` (radio-audio-test with --sdg flag)
