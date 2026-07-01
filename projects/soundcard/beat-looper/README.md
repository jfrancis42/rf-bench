# beat-looper — Ambient Beat Looper

Turns your environment into a drum machine. Detects percussive
transients (taps, claps, knocks, footsteps), quantizes them to a
tempo grid, and layers them into an evolving rhythm loop that plays
back continuously through headphones.

## How it works

1. **Onset detection**: spectral flux (positive energy changes) with
   adaptive percentile-based threshold. Distinguishes percussive attacks
   from ambient noise.

2. **Tempo estimation**: auto-detects BPM from inter-onset intervals
   using histogram clustering. Handles half/double time ambiguity.

3. **Beat quantization**: snaps captured transients to the nearest 16th
   note position on the grid. Adjustable strength (0 = free-time, 1 =
   strictly quantized).

4. **Loop assembly**: each detected transient is captured (~100 ms),
   shaped with a fast attack/decay envelope, and layered into the loop
   buffer at its quantized position.

5. **Decay**: older layers gradually fade with each new addition,
   creating an evolving, living pattern rather than static buildup.

## Usage

```bash
# Auto-detect tempo from your tapping/clapping
python beat_looper.py --input-device 2 --output-device 2

# Fixed 120 BPM (ignore detected tempo)
python beat_looper.py --bpm 120 --input-device 2 --output-device 2

# 16-beat loop (2 bars of 4/4 at a danceable tempo)
python beat_looper.py --beats 16 --bpm 125

# Tight quantization (snap everything to grid)
python beat_looper.py --quantize 1.0

# Free-time (no quantization, layer raw timing)
python beat_looper.py --quantize 0

# Faster decay (pattern changes more quickly)
python beat_looper.py --decay 0.85

# Sensitive detection (quiet taps)
python beat_looper.py --threshold -35

# Test mode
python beat_looper.py --test
```

## Flags

- `--bpm FLOAT` — Fixed BPM. 0 = auto-detect from onset timing (default: 0)
- `--beats INT` — Number of beats per loop (default: 8)
- `--threshold FLOAT` — Onset detection sensitivity in dB (default: -25).
  Lower = more sensitive.
- `--quantize FLOAT` — Quantization strength, 0–1 (default: 0.5).
  0 = free-time, 1 = strict 16th-note grid.
- `--decay FLOAT` — Loop decay factor, 0–1 (default: 0.95).
  Lower = older layers fade faster.
- Standard audio device args

## Live display

```
  [████████░░░░░░░░] 120.0 BPM | Onsets: 24 | Layers: 18
```

The bar shows the current playback position within the loop.

## How to use it

1. Start the looper (with headphones on)
2. Start tapping or clapping a steady rhythm
3. After 4+ hits, tempo locks in
4. Each new hit gets captured and added to the loop
5. You hear the accumulated pattern playing back
6. Keep adding — the pattern evolves as old layers decay
7. Change your rhythm — the loop gradually transforms

## Tips

- **Start simple**: begin with quarter-note claps, then add offbeats
- **Use different sounds**: tap table (kick), clap (snare), snap (hat)
- **Fixed BPM**: if auto-detect is unstable, lock in with `--bpm`
- **Quiet environment**: works best without competing percussive sounds
- **Close mic**: hold mic close to sound source for clean captures
- **Layering**: the decay parameter controls how quickly old patterns
  are replaced. 0.99 = very slow evolution, 0.8 = fast turnover.

## Limitations

- **Mono only.** Input and output are mono. Stereo spatial placement
  of captured sounds is not implemented.
- **No pitch detection.** All transients are treated as percussion.
  Tonal sounds will be captured with their pitch intact but not
  pitch-shifted to match any key.
- **Tempo detection needs regularity.** Completely random tapping
  won't produce a stable BPM estimate. Tap at least 4 steady beats
  for the estimator to lock.
- **Crossfeed on loopback.** If headphone output is loud enough to
  reach the mic, you get a feedback loop where the loop triggers
  re-detection. Keep headphone volume moderate or use closed-backs.
- **100ms capture window.** Very long sounds (reverb tails, sustained
  notes) are truncated. This is by design — the tool is for
  percussive transients.
- **Quantization is position-only.** Duration and velocity of the
  captured transient are preserved as-is; no velocity quantization
  or dynamic leveling.

## Requirements

- `numpy`, `scipy`
- `sounddevice` (for live mode)
