# spatial-exaggerator — Superhuman Directional Hearing

Exaggerates stereo spatial cues to create dramatically widened sound
perception. Makes it easier to pinpoint direction and distance of
sounds in the environment. Like turning the "stereo width" knob to 11.

## How it works

Human spatial hearing depends on two main cues:

- **ITD** (Interaural Time Difference): sounds arrive at the nearer ear
  first. Maximum natural ITD is ~0.7 ms (head width / speed of sound).
  Dominant below ~1500 Hz.

- **ILD** (Interaural Level Difference): the head shadows high-frequency
  sounds, making them quieter at the far ear. Dominant above ~1500 Hz.

This tool separates the stereo signal into low-frequency (ITD-relevant)
and high-frequency (ILD-relevant) bands using a 1500 Hz crossover. In
each band, it converts to Mid/Side representation and amplifies the
Side channel — this exaggerates whichever spatial cue is dominant in
that frequency range.

A crossfeed parameter prevents the extreme isolation from causing
headaches on extended listening.

## Usage

```bash
# Default settings (good starting point)
python spatial_exaggerator.py --input-device 2 --output-device 2

# Subtle widening (more natural)
python spatial_exaggerator.py --itd-gain 1.5 --ild-gain 1.5 --width 1.2

# Extreme widening (disorienting but fun)
python spatial_exaggerator.py --itd-gain 5.0 --ild-gain 4.0 --width 3.0

# Reduce crossfeed for maximum separation
python spatial_exaggerator.py --crossfeed 0

# More crossfeed for comfort on long sessions
python spatial_exaggerator.py --crossfeed -0.3

# Test mode — verify widening effect
python spatial_exaggerator.py --test
```

## Flags

- `--itd-gain FLOAT` — ITD exaggeration multiplier (default: 3.0).
  Higher = more time-difference amplification in the low-frequency band.
- `--ild-gain FLOAT` — ILD exaggeration multiplier (default: 2.0).
  Higher = more level-difference amplification in the high-frequency band.
- `--width FLOAT` — Overall stereo width multiplier applied after
  frequency-dependent processing (default: 1.5). 1.0 = no change.
- `--crossfeed FLOAT` — Amount of opposite-channel bleed (default: -0.2).
  Negative values add a small amount of the opposite channel to prevent
  extreme isolation discomfort. 0 = no crossfeed.
- Standard audio device args

## Algorithm details

1. Split stereo into L and R channels
2. Crossover filter at 1500 Hz (3rd-order Butterworth):
   - Low band: ITD-dominated spatial cues
   - High band: ILD-dominated spatial cues
3. For each band, convert to M/S:
   - M = (L + R) / 2 (center image)
   - S = (L - R) / 2 (spatial difference)
4. Amplify S by the respective gain factor
5. Reconstruct L/R from boosted M/S
6. Recombine frequency bands
7. Apply overall width multiplier (another M/S pass)
8. Apply crossfeed
9. Soft-clip via tanh() to prevent harsh distortion

## Suggested settings

| Use case | ITD | ILD | Width | Crossfeed |
|----------|-----|-----|-------|-----------|
| Nature walk (subtle) | 1.5 | 1.5 | 1.2 | -0.2 |
| Birdwatching | 3.0 | 2.5 | 1.5 | -0.2 |
| Urban environment | 2.0 | 2.0 | 1.5 | -0.3 |
| Music (widen mix) | 2.0 | 1.5 | 1.8 | -0.15 |
| Extreme (demo) | 5.0 | 4.0 | 3.0 | 0 |
| Mono recovery | 1.0 | 1.0 | 2.0 | 0 |

## Limitations

- **Requires stereo mic input.** A single mono mic has no spatial info
  to exaggerate. Use a binaural mic pair (ear-mounted) for best results.
- **Headphones only.** Playing through speakers adds room acoustics
  that defeat the spatial processing.
- **Can cause fatigue.** Extreme settings widen the image beyond
  natural head geometry. Take breaks, use moderate crossfeed.
- **Phase artifacts.** At high gains, M/S processing can introduce
  subtle comb-filtering. The crossover minimizes this but doesn't
  eliminate it.
- **Mono content passes through unchanged.** Centered sounds
  (M-only, S=0) are not affected by the processing.

## Requirements

- `numpy`, `scipy`
- `sounddevice` (for live mode)
- Stereo input (binaural mic recommended)
- Headphones for output
