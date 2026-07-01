# audio-loopback-null — Loopback Null Test

Plays a known signal through the soundcard, captures it back via
loopback, aligns and subtracts the original, and analyzes what's left.
The residual reveals everything the audio system adds: noise,
distortion, jitter, and frequency-dependent artifacts.

## Concept

A perfect audio system would produce a null of -∞ dB. In practice,
the residual tells you exactly what the system contributes:

- **Broadband residual** = thermal noise + quantization noise
- **Discrete tones in residual** = harmonic distortion, hum
- **Impulsive residual** = clock glitches, buffer underruns
- **Frequency-shaped residual** = filter errors, DAC reconstruction

## Usage

```bash
# Basic sweep null test (requires loopback cable)
python audio_loopback_null.py --input-device 2 --output-device 2 --pdf null.pdf

# White noise (reveals frequency-dependent errors)
python audio_loopback_null.py --signal noise --pdf null_noise.pdf

# Single tone (most sensitive to THD)
python audio_loopback_null.py --signal tone --freq 1000 --pdf null_tone.pdf

# Multitone (tests IMD)
python audio_loopback_null.py --signal multitone --pdf null_multi.pdf

# Full output
python audio_loopback_null.py --pdf null.pdf --csv null.csv --json null.json

# Test mode (no hardware)
python audio_loopback_null.py --test --pdf test_null.pdf
```

## Flags

- `--signal {sweep,noise,tone,multitone}` — test signal type (default: sweep)
- `--duration SECS` — signal duration (default: 3)
- `--freq HZ` — tone frequency for --signal tone (default: 1000)
- `--amplitude` — test signal amplitude 0–1 (default: 0.5)
- `--pdf FILE` — PDF report (3 panels: time, residual spectrum, null depth)
- `--csv FILE` — CSV (freq, null_depth_db, residual_spectrum_dbfs)
- `--json FILE` — JSON summary metrics
- Standard audio device flags

## What the report shows

### Panel 1: Time domain
Reference (blue), captured/aligned (green), and residual (red) over
the first 2000 samples. Visually confirms alignment worked.

### Panel 2: Residual spectrum
Absolute level of the residual in dBFS. Shows what's been added.
Discrete spurs indicate harmonic distortion or hum.

### Panel 3: Null depth vs frequency
Ratio of residual to original at each frequency. Lower = better.
A flat -80 dB line means -80 dB of added error everywhere.
Frequencies where null depth degrades indicate system weaknesses.

## Interpreting results

| Null depth | Quality |
|-----------|---------|
| < -80 dB | Excellent (24-bit resolving) |
| -70 to -80 dB | Very good |
| -60 to -70 dB | Good (typical USB audio) |
| -50 to -60 dB | Moderate |
| > -50 dB | Poor (check cables, drivers) |

## Crest factor diagnostic

The crest factor of the residual diagnoses the error type:
- **> 12 dB** — impulsive (clock glitches, sample drops)
- **4–12 dB** — mixed (distortion + noise)
- **< 4 dB** — noise-like (thermal/quantization)

## Requirements

- `numpy`, `scipy`, `matplotlib`
- `sounddevice` (for live mode)
- Loopback cable (3.5mm M-M or equivalent)
