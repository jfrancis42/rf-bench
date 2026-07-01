# bird-time-stretch — Bird Song Time-Stretcher

Slows down audio 4-8× without changing pitch, revealing hidden
micro-structure in bird calls, insect sounds, and any fast transient
audio. A wren song becomes a whale song — you hear individual
frequency sweeps, vibrato, and harmonics that are invisible at
normal speed.

## Modes

### Triggered (default)
Continuously buffers the last N seconds. When audio exceeds a level
threshold (bird call detected), stretches the buffer and plays it
through the headphones. You hear the environment normally, then get
an instant replay in slow motion.

### Continuous
Stretches everything in real-time. Output always lags input by the
stretch factor. At 4×, you're hearing what happened 4 seconds ago
at quarter speed. Meditative and surreal.

### Capture
Record a fixed duration, stretch offline, play once. Simplest mode
for deliberate recording sessions.

## Usage

```bash
# Triggered mode: auto-detect bird calls, replay stretched
python bird_time_stretch.py --input-device 2 --output-device 2

# Higher stretch for more detail
python bird_time_stretch.py --stretch 8

# Lower trigger threshold for quieter calls
python bird_time_stretch.py --trigger-db -40

# Longer buffer (catch longer songs)
python bird_time_stretch.py --buffer-seconds 10

# Continuous mode (everything slowed, always behind)
python bird_time_stretch.py --mode continuous --stretch 4

# Capture mode (record 5s, stretch, play)
python bird_time_stretch.py --mode capture --buffer-seconds 5

# Save stretched audio to file
python bird_time_stretch.py --output-file bird_slow.wav

# Test mode (synthetic bird call)
python bird_time_stretch.py --test --output-file test_stretched.wav
```

## Flags

- `--stretch N` — time stretch factor (default: 4.0)
- `--mode {triggered,continuous,capture}` — operation mode
- `--buffer-seconds N` — ring buffer / capture size (default: 5)
- `--trigger-db DB` — trigger threshold in dBFS (default: -30)
- `--fft-size N` — phase vocoder window size (default: 2048)
- `--output-file FILE` — save stretched audio to WAV
- Standard audio device flags

## Algorithm: Phase Vocoder

Time-stretching without pitch change uses the phase vocoder:

1. **Analysis**: STFT the input with overlapping windows
2. **Phase propagation**: compute instantaneous frequency per bin
   from frame-to-frame phase differences
3. **Synthesis**: reconstruct frames at the new (stretched) rate,
   accumulating phase at the instantaneous frequency
4. **Overlap-add**: window and sum synthesized frames

The stretch factor determines the ratio between analysis hop
(how fast we step through input) and synthesis hop (how fast we
produce output). A factor of 4 means 4 synthesis frames per 1
analysis frame advance.

## What to listen for

At 4-8× stretch:
- **Trills** resolve into individual notes with distinct attack/decay
- **FM sweeps** become audible frequency glides
- **Harmonics** separate into individual partials
- **Vibrato** becomes a slow modulation you can count
- **Double/triple notes** that sound like one note split apart
- **Breathing sounds** between phrases become audible

## Species-specific notes

| Bird | Normal character | What stretching reveals |
|------|-----------------|----------------------|
| Wren | Rapid trill | Complex FM sweeps, 3+ harmonics |
| Warbler | Fast phrases | Distinct syllable types, micro-pauses |
| Thrush | Fluty | Vibrato detail, harmonic shifts |
| Woodpecker | Drum roll | Individual strikes, inter-strike timing |
| Hawk | Screech | Spectral shape, formant-like resonances |

## Limitations

- Phase vocoder introduces some "phasiness" — metallic quality on
  transients. Higher FFT size reduces this but blurs time resolution.
- Triggered mode has ~0.5s processing latency (stretch computation).
- Continuous mode accumulates drift — output falls further behind
  input over time. Eventually must discard audio to catch up.
- Very high stretch factors (>16×) produce audible artifacts.

## Requirements

- `numpy`, `scipy`
- `sounddevice`
- `soundfile` (for WAV output)
