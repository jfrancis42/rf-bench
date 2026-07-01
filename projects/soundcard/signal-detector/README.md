# signal-detector — Signal-Presence Detector / Audio Squelch

Carrier-detect for audio. Opens the squelch for ANY signal above the
noise floor: CW, data bursts, carriers, voice, DTMF, tones. Think of
it as a level-based or spectral-based carrier-sense mechanism, as
opposed to vad-squelch which opens only for human speech.

## Detection methods

### Energy (default)

Tracks a noise floor estimate (exponential moving average of quiet
blocks). When block power exceeds the noise floor by a configurable
margin, the squelch opens.

- **Pros:** Fast, simple, low CPU, no frequency assumptions.
- **Cons:** Any broadband energy spike opens it (QRM, impulse noise).
- **Best for:** Strong signals, clean channels, trigger for recorder.

### Spectral flatness

Measures the ratio of geometric mean to arithmetic mean of the power
spectrum. Pure noise has a flat spectrum (ratio near 1); any signal
with spectral peaks (tones, speech, data) drives the ratio toward 0.

- **Pros:** Distinguishes signals from broadband noise even at moderate SNR.
- **Cons:** Slightly higher CPU (one FFT per block). Narrowband noise
  (e.g., hum) can fool it.
- **Best for:** Noisy channels where energy alone would chatter.

### Autocorrelation

Computes the normalized autocorrelation of each block and looks for
peaks in the 2-20 ms lag range (50-500 Hz fundamental). Periodic or
quasi-periodic signals (CW, tones, voice, FSK) produce strong peaks;
random noise does not.

- **Pros:** Excellent for periodic signals; ignores impulsive noise.
- **Cons:** Aperiodic signals (spread-spectrum, very short bursts) may
  not trigger. Higher CPU than energy method.
- **Best for:** Detecting CW, carriers, tones, and data modes in noise.

## Usage

```bash
# Real-time squelch on scanner audio (energy method)
python signal_detector.py --input-device 2 --output-device 4

# Spectral flatness method, lower threshold
python signal_detector.py --method spectral_flatness --threshold 0.2

# Autocorrelation with longer hang time
python signal_detector.py --method autocorrelation --hang-ms 400

# Log squelch events to CSV
python signal_detector.py --output events.csv

# Test mode: noise/CW/noise/carrier/noise sequence
python signal_detector.py --test --method energy

# Test mode: save gated output as WAV
python signal_detector.py --test --output gated.wav
```

## Flags

- `--method {energy,spectral_flatness,autocorrelation}` — detection
  algorithm (default: energy)
- `--threshold FLOAT` — confidence threshold 0-1 (default 0.3).
  Lower = more sensitive.
- `--hang-ms MS` — hold squelch open after signal disappears (default
  200 ms). Prevents rapid open/close on fading signals.
- `--attack-ms MS` — gate opening speed (default 5 ms)
- `--release-ms MS` — gate closing speed (default 30 ms)
- `--output PATH` — CSV event log (real-time) or WAV file (test mode,
  if path ends in .wav)
- Standard audio I/O flags (`--input-device`, `--output-device`,
  `--samplerate`, `--blocksize`, `--channels-in`, `--channels-out`)

## Threshold tuning

| Threshold | Behavior |
|-----------|----------|
| 0.1 | Very sensitive — opens on faint signals, may chatter |
| 0.3 | Default — opens on moderate signals (default) |
| 0.5 | Conservative — needs clear signal |
| 0.7 | Strict — only strong/clean signals |

## Use cases

- **Squelch for recording:** pipe into triggered-recorder to capture
  only active transmissions on a scanner feed.
- **Trigger for other tools:** use the event CSV output to drive
  external recording/alerting scripts.
- **Channel activity monitor:** log open/close events over time to
  measure channel occupancy.
- **Signal-present gate for measurement tools:** mute the output when
  there is no signal, preventing noise from contaminating downstream
  analysis (SNR meter, audio analyzer, etc.).

## CSV event log format

```
timestamp,event,confidence,noise_floor_dbfs
1719756000.123,open,0.452,-58.3
1719756003.456,close,0.180,-57.9
```

Events are logged only on state transitions (open/close).

## Comparison with vad-squelch

| Feature | signal-detector | vad-squelch |
|---------|----------------|-------------|
| Opens for CW | Yes | No |
| Opens for data (RTTY, packet) | Yes | No |
| Opens for carriers/tones | Yes | No |
| Opens for voice | Yes | Yes |
| Rejects noise | Yes | Yes |
| CPU usage | Low-medium | Medium-high |
| Feature count | 1 (selected method) | 4 (weighted) |

Use signal-detector when you want to capture everything that is not
noise. Use vad-squelch when you want only human speech.
