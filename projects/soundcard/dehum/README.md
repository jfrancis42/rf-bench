# dehum — Power-Line Hum Removal Filter

Removes 50/60 Hz mains hum and all its harmonics from audio using a
cascade of very narrow IIR notch filters. Each notch is ~1 Hz wide
(Q=50), so speech and music pass through with negligible damage.

Ground-loop hum is a common problem in audio systems where two pieces
of equipment are plugged into different outlets, creating a voltage
difference on their ground references. This manifests as a strong
fundamental at the mains frequency (50 Hz in most of the world, 60 Hz
in North America) plus harmonics that extend well into the audio band.
The harmonics give it the characteristic "buzz" rather than a pure
tone. Typical sources: microphone cables near transformers, unbalanced
audio connections between PC and radio, USB ground loops.

## Usage

```bash
# Real-time, auto-detect 50/60 Hz
python dehum.py --input-device 2 --output-device 4

# Force 60 Hz (skip detection)
python dehum.py --freq 60 --input-device 2 --output-device 4

# More harmonics for heavily distorted hum (square-wave ground loop)
python dehum.py --harmonics 25

# Wider notches if fundamental drifts (poor mains regulation)
python dehum.py --notch-q 30

# Test mode: generates 60 Hz hum + speech, removes hum, reports
python dehum.py --test --output dehummed.wav

# Test with longer duration for verification
python dehum.py --test --test-duration 10 --output dehummed.wav
```

## Flags

### De-hum parameters

- `--auto` — auto-detect whether hum is 50 or 60 Hz (default)
- `--freq {50,60}` — force fundamental frequency, skip auto-detection
- `--harmonics N` — number of harmonics to notch (default 15). At 60 Hz
  this covers up to 900 Hz; at 50 Hz up to 750 Hz. Increase for
  heavily clipped/distorted hum that has significant energy above 1 kHz.
- `--notch-q Q` — quality factor of each notch (default 50). Higher Q
  means narrower notch (less speech damage) but less tolerance for
  frequency drift. Q=50 gives roughly 1 Hz bandwidth at 50/60 Hz.
- `--output WAV` — write processed audio to WAV file (test mode only)

### Standard audio flags

- `--input-device ID` / `--output-device ID` — sounddevice IDs
- `--samplerate HZ` — sample rate (default 48000)
- `--blocksize N` — processing block size (default 1024)
- `--channels-in N` / `--channels-out N` — channel counts
- `--list-devices` — show available audio devices and exit
- `--test` — run with synthetic test signal
- `--test-duration SEC` — test signal length (default 5.0)

## How auto-detection works

1. Accumulate a smoothed magnitude spectrum over ~5 blocks (~100 ms).
2. Compare total harmonic energy at 50 Hz harmonics vs 60 Hz harmonics
   (first 5 harmonics of each candidate).
3. Whichever set has clearly higher energy (and exceeds a noise floor
   threshold) wins.
4. Once locked, the notch bank is built and detection stops.

Detection takes roughly 100 ms. During that time, hum passes through
unfiltered. Use `--freq` to skip detection and notch immediately.

## Limitations

- Detection delay: ~100 ms while spectrum average builds up.
- If both 50 and 60 Hz are present (rare but possible with mixed
  equipment), only the dominant one is notched. Use `--freq` for each
  and cascade two instances if needed.
- Very low-Q notches (Q<10) will audibly affect speech formants near
  the notch frequencies.
- Mains frequency can drift +/- 0.5 Hz under heavy grid load. Q=50 is
  wide enough to handle this; if you observe drift beyond that, reduce
  Q to 30.
