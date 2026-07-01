# reverse-reality

Real-time audio temporal reversal effect. Buffers 2-5 seconds of audio
and plays it backwards, mixed quietly under the forward stream. You hear
ghostly reversed precursors of events before they actually happen.

Rain becomes an alien language. Speech turns demonic. Music dissolves
into a temporal soup where the future bleeds into the present.

## Usage

```bash
# Real-time with default settings (3s buffer, 0.3 reverse level)
python3 reverse_reality.py

# Longer buffer, louder reverse, pitched down 3 semitones
python3 reverse_reality.py --buffer-seconds 5 --reverse-level 0.5 --pitch-shift -3

# Test mode (no audio hardware needed)
python3 reverse_reality.py --test

# List audio devices
python3 reverse_reality.py --list-devices

# Select specific devices
python3 reverse_reality.py --input-device 3 --output-device 5
```

## Options

| Flag | Default | Description |
|------|---------|-------------|
| `--buffer-seconds` | 3.0 | Ring buffer length (2-5 seconds) |
| `--reverse-level` | 0.3 | Mix level of reversed audio (0-1) |
| `--crossfade-ms` | 20 | Crossfade between reversed chunks (ms) |
| `--pitch-shift` | 0 | Pitch-shift reversed audio (semitones, negative = down) |
| `--samplerate` | 48000 | Sample rate |
| `--blocksize` | 1024 | Processing block size |
| `--input-device` | default | Input device ID |
| `--output-device` | default | Output device ID |
| `--channels-in` | 1 | Input channels |
| `--channels-out` | 2 | Output channels |
| `--test` | off | Run with synthetic test signal |
| `--test-duration` | 5.0 | Test signal duration (seconds) |
| `--list-devices` | — | Show audio devices and exit |

## How it works

1. Audio from the microphone passes through to the output at full level
   (forward stream).
2. Simultaneously, input is written to a ring buffer of configurable
   length (2-5 seconds).
3. The ring buffer content is read out in reversed chunks (half the
   buffer length each). Each chunk is the most recent N seconds of audio
   played backwards.
4. Crossfading between chunks prevents clicks at boundaries.
5. The reversed stream is mixed into the output at a lower level
   (default 0.3).
6. Optional pitch shift (resampling) on the reversed stream adds
   otherworldly character.

## Suggested settings

| Scene | Buffer | Level | Pitch | Effect |
|-------|--------|-------|-------|--------|
| Rain/nature | 4-5s | 0.3 | -2 | Alien atmosphere |
| Speech/podcast | 3s | 0.2 | 0 | Subliminal whispers |
| Music | 2-3s | 0.4 | 0 | Temporal echo |
| Maximum creepy | 5s | 0.5 | -5 | Horror soundtrack |

## Dependencies

- numpy
- sounddevice (real-time mode)
- dsp_pipeline (parent directory framework)

## Latency

The effect has inherent latency equal to the buffer length: you hear the
reversed version of audio that occurred buffer-seconds ago. The forward
path has no added latency (just the sounddevice block size, ~21 ms at
1024/48000).
