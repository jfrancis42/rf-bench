# stereo-expander — Pseudo-Stereo Field Expander

Takes mono SSB/AM audio and synthesizes a stereo field. Reduces
listener fatigue on long ragchews by spreading the audio across
the headphone soundstage. Purely cosmetic — no information gain.

## Methods

### Haas effect (default)

One ear gets the original signal; the other gets a delayed copy
(15 ms default). The brain perceives this as spatial width rather
than echo because the delay is below the echo threshold (~40 ms).
Width parameter controls how much the delayed channel differs from
the direct channel.

### Comb filter

Complementary comb filters on left/right channels create frequency-
dependent L/R differences. The result is that each frequency
"lives" preferentially in one ear. More obvious stereo effect but
can sound colored.

### Allpass

A first-order allpass filter on one channel creates phase
differences without changing magnitude. Subtle, natural-sounding
width. Least coloration but least dramatic effect.

## Usage

```bash
# Real-time Haas
python stereo_expander.py --input-device 2 --output-device 4

# Wider stereo image
python stereo_expander.py --width 0.9

# Comb method with shorter delay
python stereo_expander.py --method comb --delay-ms 8

# Test mode
python stereo_expander.py --test --output stereo.wav
```

## Flags

- `--delay-ms MS` — inter-channel delay (default 15). Used by Haas
  and comb methods. 10–30 ms typical; below echo threshold.
- `--width FLOAT` — stereo width 0–1 (default 0.7). 0 = pure mono.
- `--method {haas,comb,allpass}` — synthesis algorithm
- `--output WAV` — save stereo output (test mode)
- Standard audio flags

## When to use which method

| Situation | Method | Why |
|-----------|--------|-----|
| General SSB listening | haas | Natural, low coloration |
| Crowded band / multiple voices | comb | Stronger separation |
| Music relay / AM broadcast | allpass | No coloration |
| CW | Use binaural-cw instead | Pitch-based spatial is better |

## Limitations

- Headphones only. Speaker playback cancels the stereo effect
  (or creates comb filtering / spatial confusion).
- Not a substitute for true binaural processing when signals need
  to be separated (use binaural-cw or iq-binaural for that).
- Haas method: at large delays (>30 ms), the effect transitions
  from "width" to audible echo. Stay below 25 ms.
