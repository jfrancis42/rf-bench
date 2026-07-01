# spectral-subtraction — Real-Time Spectral Noise Reduction

Classic noise reduction algorithm: capture a noise spectral profile
during silence, then subtract it from live audio frame-by-frame.
Same principle as the TimeWave DSP-599zx and similar outboard DSP
noise reducers.

## How it works

1. During the first ~0.5 seconds (configurable), the script captures
   audio and averages the magnitude spectrum → this becomes the noise
   profile.
2. On every subsequent block: FFT, subtract the noise profile from
   the magnitude spectrum (scaled by `--subtraction-db`), enforce a
   spectral floor (prevents musical artifacts), IFFT back.
3. Output is the cleaned audio, played to speakers or written to WAV.

Works best on **stationary** noise: band noise, fan hiss, power
supply whine, thermal noise. Poor on intermittent noise (use the
impulse blanker or LMS canceller for those).

## Usage

```bash
# Real-time: mic in → cleaned audio out
python spectral_subtraction.py --input-device 2 --output-device 4

# Keep quiet for the first second, then talk

# Test mode: synthetic signal + noise
python spectral_subtraction.py --test --test-duration 10

# Write processed audio to file
python spectral_subtraction.py --test --output cleaned.wav
```

## Flags

- `--subtraction-db DB` — how aggressively to subtract noise
  (default 12 dB). Higher = more noise removed but more artifacts.
- `--floor-db DB` — spectral floor relative to input magnitude
  (default -40 dB). Prevents over-subtraction from creating silence
  holes ("musical noise").
- `--noise-frames N` — number of initial blocks to average for noise
  profile (default 20, about 0.4 seconds at default settings).
- `--input-device ID`, `--output-device ID` — audio device selection.
- `--samplerate HZ` — default 48000.
- `--blocksize N` — FFT/block size (default 1024).
- `--test` — use synthetic test signal.
- `--output WAV` — write output to file (test mode only).
- `--list-devices` — show available audio devices and exit.

## Limitations

- Noise profile is captured once at startup. If the noise floor
  changes significantly during operation, the subtraction becomes
  less effective. Future enhancement: adaptive noise tracking.
- Not suitable for non-stationary interference (QRM, SSB signals
  on adjacent frequencies). Use auto-notch or LMS for those.
- The overlap-add implementation uses a simplified 50% crossfade
  rather than full WOLA. Adequate for speech/CW; not bit-perfect
  for measurement applications.
