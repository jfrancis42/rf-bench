# bandpass-slicer — Audio Crossover / Frequency Band Slicer

Splits incoming mono audio into N configurable frequency bands and
routes each to a different stereo position. Low-pitched signals go
left, high-pitched signals go right (or any distribution you choose).

## Primary use case: CW pile-ups

On a crowded CW band, multiple stations call simultaneously at
different audio pitches. The radio's passband is wide enough to hear
them all, but they stack on top of each other in mono. This tool
separates them spatially:

- Low-pitched stations (400-600 Hz) appear on the left
- Mid-pitched stations (600-900 Hz) appear in the center
- High-pitched stations (900-1200 Hz) appear on the right

Your brain's spatial hearing instantly resolves what mono cannot.
This is sometimes called "poor man's binaural CW" — it approximates
what dedicated binaural receivers do, using only audio-domain
filtering and panning.

## Other uses

- **QRM separation:** isolate a wanted CW signal at 700 Hz from an
  interfering carrier at 1000 Hz by putting them in different ears
- **Multi-channel monitoring:** spread an audio spectrum across the
  stereo field for improved situational awareness
- **Audio crossover for analysis:** split audio into sub-bands for
  per-band level metering or recording

## Usage

```bash
# Default: 4 bands from 200-1400 Hz, linear pan
python bandpass_slicer.py --input-device 2 --output-device 4

# CW pile-up: 3 bands covering typical CW audio range
python bandpass_slicer.py --bands "500,800" --low 300 --high 1100

# More granular: 6 narrow bands for fine spatial resolution
python bandpass_slicer.py --bands "350,500,650,800,950" --low 200 --high 1100

# Hard L/C/R panning instead of smooth spread
python bandpass_slicer.py --bands "500,900" --pan-mode discrete

# Test mode: generate multi-tone signal and process
python bandpass_slicer.py --test --output sliced.wav

# List audio devices
python bandpass_slicer.py --list-devices
```

## How the --bands argument works

The `--bands` flag specifies the *split points* between bands.
Combined with `--low` and `--high`, these define the band edges:

```
--low 200 --bands "400,700,1000" --high 1400
```

Creates 4 bands:
- Band 1: 200-400 Hz (panned full left)
- Band 2: 400-700 Hz (panned left-of-center)
- Band 3: 700-1000 Hz (panned right-of-center)
- Band 4: 1000-1400 Hz (panned full right)

## Flags

- `--bands SPLITS` — comma-separated split frequencies in Hz (default "400,700,1000")
- `--low HZ` — lower edge of the lowest band (default 200)
- `--high HZ` — upper edge of the highest band (default 1400)
- `--pan-mode {linear,discrete}` — pan law (default linear)
  - `linear`: smooth spread across L-R; each band gets a proportional position
  - `discrete`: hard-pan to L, C, or R based on position
- `--order N` — Butterworth filter order per band (default 4). Higher = steeper rolloff but more ringing.
- `--output WAV` — write processed audio to WAV (test mode only)
- Standard audio I/O flags (--input-device, --output-device, --samplerate, --blocksize, etc.)
- Standard test flags (--test, --test-duration)

## Pan modes

### Linear (default)

Each band is positioned proportionally across the stereo field.
With 4 bands: band 1 = full left (L=1.0, R=0.0), band 2 = left-of-center
(L=0.67, R=0.33), band 3 = right-of-center (L=0.33, R=0.67),
band 4 = full right (L=0.0, R=1.0).

### Discrete

Bands are hard-panned to left, center, or right based on their
position index. Left quarter goes L, right quarter goes R, middle
goes C. Sharper spatial separation but less natural.

## Typical CW configurations

| Situation | Bands | Low | High | Notes |
|-----------|-------|-----|------|-------|
| General pile-up | 400,700,1000 | 200 | 1400 | 4-band, covers most CW audio |
| Narrow split | 600,800 | 400 | 1000 | 3-band, typical CW pitch range |
| Fine resolution | 400,550,700,850,1000 | 300 | 1100 | 6 bands for crowded contests |
| Wide SSB crossover | 500,1500,3000 | 200 | 4000 | Spread SSB audio spatially |

## Limitations

- Input must be mono (or the first channel of a multi-channel input).
  If your radio provides stereo, only channel 1 is processed.
- Butterworth filters have gentle rolloff in the transition band.
  Adjacent bands overlap somewhat. For most CW use this is fine —
  a tone near a band edge appears in both adjacent channels, which
  sounds natural.
- At very narrow bands (<100 Hz) with high filter order (>6), filter
  numerical instability can produce artifacts. Order 4 is safe for
  all practical band widths.
- Processing latency is one block (~21 ms at 48 kHz / 1024). Not
  perceptible for CW copy.
