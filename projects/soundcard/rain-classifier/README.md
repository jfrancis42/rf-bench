# rain-classifier — Rain Intensity Classifier

Classifies precipitation intensity in real-time from microphone audio.
Rain produces broadband noise whose spectral shape varies with drop
size and intensity — this tool uses spectral centroid, slope, flatness,
and impulsiveness to estimate what's falling from the sky.

## How it works

Rain hitting surfaces produces broadband noise with characteristics
that depend on drop size and intensity:

- **Small drops** (drizzle) produce mostly high-frequency energy
- **Large drops** (heavy rain) add significant low-frequency content
- **Hail** produces impulsive clicks with high kurtosis
- **Dryer conditions** show lower spectral flatness (more tonal/ambient)

The classifier extracts several features per analysis frame:
1. **Level** (dB) — overall loudness
2. **Spectral centroid** — center of mass of the spectrum
3. **Spectral slope** (dB/octave) — HF rolloff rate
4. **Spectral flatness** (0–1) — noise-like vs tonal
5. **Kurtosis** — impulsiveness (high = hail-like clicks)

## Classes

| Class | Level range | Rain rate | Description |
|-------|-------------|-----------|-------------|
| dry | < -50 dBFS | 0 mm/hr | No precipitation |
| mist | -55 to -45 | ~0.1 mm/hr | Barely audible |
| drizzle | -45 to -35 | ~1 mm/hr | Light, steady |
| moderate | -35 to -25 | ~5 mm/hr | Steady rain |
| heavy | -25 to -15 | ~20 mm/hr | Hard rain |
| downpour | > -15 | ~50 mm/hr | Torrential |
| hail | (any level) | ~30 mm/hr | Impulsive, high kurtosis |

## Usage

```bash
# Live classification from microphone
python rain_classifier.py --input-device 2

# Log to CSV (for overnight recording)
python rain_classifier.py --csv rain_log.csv --interval 5

# More averaging (smoother classification, slower response)
python rain_classifier.py --averaging 20

# Higher spectral resolution
python rain_classifier.py --fft-size 8192

# Test mode — simulates 5 rain intensities
python rain_classifier.py --test
```

## Flags

- `--fft-size N` — FFT size for spectral analysis (default: 4096)
- `--averaging N` — number of spectra to average (default: 10)
- `--csv FILE` — log classifications to CSV file
- `--interval SECS` — CSV logging interval (default: 2.0)
- Standard audio device args (`--input-device`, `--samplerate`, etc.)

## Output

Live display with intensity bar:
```
  [▒▒░░░░░░░░]   drizzle (75%) | -38.2 dB | ~1.0 mm/hr
```

CSV columns: `timestamp, classification, confidence, level_db, centroid_hz,
slope_db_oct, flatness, rain_rate_mm_hr`

## Placement tips

- Place mic under a solid overhang or inside a window pointing out
- Avoid wind noise (use a windscreen or sheltered location)
- Metal roof/surface gives stronger signal than soft ground
- Calibrate: run in dry conditions first to establish your "dry" baseline
- High ambient noise (traffic, AC) may confuse the flatness detector

## Limitations

- Level thresholds are uncalibrated — they assume a typical mic in a
  moderately quiet location. Urban noise floors may push "dry" readings
  into the "mist" range.
- Rain rate estimates are very rough — based only on classification
  category, not acoustic modeling of drop-size distribution.
- Wind noise has high flatness and can be misclassified as rain.
  Use a windscreen.
- Indoor recordings (rain on roof) vs outdoor have very different
  spectral characteristics. Indoor sounds darker (more LF).
- Hail detection requires genuinely impulsive impacts. Muffled hail
  on soft surfaces may classify as heavy rain.

## Requirements

- `numpy`, `scipy`
- `sounddevice` (for live mode)
