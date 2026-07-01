# binaural-cw — Binaural CW Spatial Processor

Mono CW audio → stereo headphone output where each station at a
different pitch appears to come from a different direction. Leverages
the brain's cocktail-party effect for dramatically improved pile-up
copy.

## How it works

Splits the audio spectrum into per-frequency-bin spatial positions:
- Low-pitched CW signals (e.g., 300 Hz) → hard left
- High-pitched signals (e.g., 1200 Hz) → hard right
- Mid-range → center / proportional pan

Uses both ITD (interaural time delay — phase shift between ears) and
ILD (interaural level difference — amplitude difference between ears)
to create a convincing spatial impression.

## Usage

```bash
# Real-time: radio audio in → headphones out
python binaural_cw.py --input-device 2 --output-device 4

# Wider frequency spread
python binaural_cw.py --low-freq 200 --high-freq 1500

# Stronger spatial effect
python binaural_cw.py --itd-ms 0.8 --ild-db 12

# Test: 3 CW signals at different pitches
python binaural_cw.py --test --output binaural.wav
```

## Flags

- `--low-freq HZ` — frequency that maps to full-left (default 300)
- `--high-freq HZ` — frequency that maps to full-right (default 1200)
- `--itd-ms MS` — maximum interaural time delay (default 0.6 ms).
  Human hearing uses 0.0–0.63 ms. Larger values exaggerate the
  spatial effect.
- `--ild-db DB` — maximum interaural level difference (default 8 dB).
  Human hearing uses 0–20 dB depending on frequency.
- `--output WAV` — save stereo output (test mode)
- Standard audio flags

## CW pile-up workflow

1. Tune to a pile-up. Hear multiple stations calling at different
   pitches (because their frequencies differ slightly).
2. Run binaural-cw with radio audio as input, headphones as output.
3. Each station now occupies a different spatial position. Your
   brain separates them automatically — same as following one voice
   in a noisy room.
4. Combine with `cw-bandpass/` (after binaural processing) to
   further isolate a specific station.

## The science

Human binaural hearing uses two cues for spatial localization:
- **ITD** (interaural time difference): the same sound arrives at
  one ear slightly before the other. Maximum ~0.63 ms for sounds
  directly to one side. Dominant below ~1500 Hz.
- **ILD** (interaural level difference): the head shadows high
  frequencies. One ear hears louder than the other. Dominant above
  ~1500 Hz.

Both cues together create a compelling spatial image even through
headphones. This processor applies both, scaled by the pan position
derived from frequency.

## Limitations

- Requires headphones. On speakers, the binaural effect is lost
  (or worse — creates comb filtering).
- Frequency-to-position mapping is fixed. Two stations at the same
  pitch will overlap spatially (same as they overlap spectrally).
- The ITD implementation uses per-bin phase shift, which is exact
  for steady tones but slightly smears transients (CW keying edges).
  In practice this is inaudible.
