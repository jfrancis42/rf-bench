# auto-tune-reality — Auto-Tune Reality

Pitch-detects everything you hear and snaps it to the nearest note in a
musical scale. Car horns become musical, bird calls lock to intervals,
wind becomes a drone chord. The world becomes an accidental composition.

## How it works

1. **Pitch detection**: Normalized autocorrelation finds the fundamental
   frequency of whatever is sounding (60–4000 Hz range)
2. **Scale mapping**: Convert frequency to MIDI note, find nearest note
   in the chosen scale, compute the distance in semitones
3. **Pitch shifting**: Phase vocoder shifts the audio up or down to land
   on the target note

The result: everything with a detectable pitch snaps to the scale.
Atonal noise passes through unchanged.

## Usage

```bash
# Pentatonic scale (always sounds good)
python auto_tune_reality.py --input-device 2 --output-device 2

# Major scale in the key of G
python auto_tune_reality.py --scale major --root 7

# Blues scale
python auto_tune_reality.py --scale blues

# Whole tone (dreamy, Debussy-like)
python auto_tune_reality.py --scale whole_tone

# Partial correction (subtle, like slightly-in-tune reality)
python auto_tune_reality.py --strength 0.5

# Chromatic (every semitone — snaps micro-tones to nearest note)
python auto_tune_reality.py --scale chromatic

# Test mode
python auto_tune_reality.py --test --scale pentatonic
```

## Flags

- `--scale NAME` — musical scale (default: pentatonic)
- `--root N` — root note as semitones from C (0=C, 2=D, 4=E, 5=F, 7=G, 9=A, 11=B)
- `--strength 0-1` — correction strength (1.0 = full snap, 0.5 = halfway)
- `--fft-size N` — phase vocoder window (default: 2048)
- Standard audio device flags

## Available scales

| Scale | Notes | Character |
|-------|-------|-----------|
| `chromatic` | All 12 | Nearest semitone |
| `major` | C D E F G A B | Happy, bright |
| `minor` | C D Eb F G Ab Bb | Sad, dark |
| `pentatonic` | C D E G A | Always consonant |
| `minor_pentatonic` | C Eb F G Bb | Bluesy, modal |
| `blues` | C Eb F F# G Bb | Gritty, soulful |
| `whole_tone` | C D E F# G# A# | Dreamy, floating |
| `diminished` | C D Eb F Gb Ab A B | Tense, chromatic |

## Live display

While running, shows the detected pitch and what it's being corrected
to. Helps you understand what the algorithm is hearing and doing:

```
  349.0 Hz ( F) →   330.0 Hz ( E)
```

## What sounds good

- **Pentatonic** is the safest — no dissonances possible regardless
  of what the environment throws at it
- **Major** works well in environments with clear tonal content
  (bird song, sirens, horns)
- **Blues** gives urban soundscapes a funky quality
- **Whole tone** makes everything sound like an underwater dream
- **Chromatic** with strength 0.3–0.5 creates a subtle "the world
  is slightly more in tune" effect

## Limitations

- Pitch detection requires quasi-periodic signals. Pure noise, broad
  transients (claps, crashes) pass through unaffected.
- Phase vocoder introduces ~50 ms latency and mild artifacts on
  transients.
- Polyphonic content (multiple simultaneous pitches) confuses the
  monophonic pitch detector — it locks to the strongest harmonic.
- Rapid pitch changes (FM sweeps) may produce glitchy artifacts as
  the shift snaps between notes.

## Requirements

- `numpy`, `scipy`
- `sounddevice`
