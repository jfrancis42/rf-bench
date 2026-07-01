# insect-classifier

Classify flying insects by their wing-beat frequency using a microphone.

Wing-beat frequency is species-specific and remarkably stable — determined
by wing geometry and muscle physiology. This tool detects periodic energy
in species-specific frequency bands using autocorrelation and Goertzel
filters, then identifies what is flying near the microphone.

## Quick start

```bash
# Test mode (no hardware needed)
python3 insect_classifier.py --test

# Real-time from default microphone
python3 insect_classifier.py

# List audio devices
python3 insect_classifier.py --list-devices

# Use specific microphone
python3 insect_classifier.py --input-device 3

# Log detections to CSV
python3 insect_classifier.py --csv detections.csv

# Show species database
python3 insect_classifier.py --list-species
```

## How it works

1. **Bandpass prefilter** (80-850 Hz FIR) isolates the wing-beat frequency range
2. **Block accumulation** — multiple audio blocks are accumulated for better
   frequency resolution (default 4 blocks = ~85 ms at 48 kHz/1024)
3. **Autocorrelation** finds the fundamental frequency with sub-sample precision
   via parabolic interpolation on the ACF peak
4. **Goertzel filters** measure band energy at the detected fundamental and
   harmonics for SNR estimation
5. **Species matching** against a database of 18 known species/variants with
   frequency ranges, scored by how centered the detection is within each range
6. **Confidence scoring** combines periodicity strength with SNR above the
   adaptive noise floor

## Species database

| Species | Frequency range | Notes |
|---------|----------------|-------|
| Dragonfly | 25-45 Hz | Very slow wingbeat |
| Crane fly | 45-65 Hz | Daddy longlegs |
| Hornet | 100-140 Hz | Larger than wasp |
| Bumblebee | 110-150 Hz | Large, slow wingbeat |
| Wasp | 140-180 Hz | Yellowjacket/paper wasp |
| Blowfly | 140-170 Hz | Bluebottle/greenbottle |
| Hover fly | 160-200 Hz | Mimics bees |
| Housefly | 170-210 Hz | Common housefly |
| Honeybee (loaded) | 180-220 Hz | Heavy with pollen |
| Fruit fly | 200-240 Hz | Small, fast wingbeat |
| Honeybee | 210-250 Hz | Worker in flight |
| Mosquito (female, Anopheles) | 350-420 Hz | Malaria vector |
| Mosquito (female, Culex) | 360-440 Hz | Common house mosquito |
| Mosquito (female, Aedes) | 380-470 Hz | Dengue vector |
| Midge | 450-550 Hz | Non-biting midge |
| Mosquito (male, Anopheles) | 500-620 Hz | Higher than female |
| Mosquito (male, Culex) | 520-600 Hz | Higher than female |
| Mosquito (male, Aedes) | 550-650 Hz | Higher than female |

Female mosquitoes always have a lower wing-beat frequency than males of
the same species — the classifier can sex mosquitoes by frequency alone.

## Options

```
Audio I/O:
  --input-device ID     Input device ID
  --samplerate HZ       Sample rate (default 48000)
  --blocksize N         Block size (default 1024)
  --channels-in N       Input channels (default 1)
  --list-devices        List audio devices and exit

Test mode:
  --test                Use synthetic test signals
  --test-duration SEC   Duration of test (default 5.0)

Classification:
  --min-confidence F    Minimum confidence to report (0-1, default 0.3)
  --noise-gate DB       Noise gate in dBFS (default -50)
  --analysis-window N   Blocks to accumulate (default 4)
  --csv PATH            Log detections to CSV
  --list-species        Print species database and exit
```

## CSV output format

When `--csv` is specified, detections are logged with columns:

- `timestamp` — ISO 8601 timestamp
- `species` — matched species name
- `frequency_hz` — detected wing-beat frequency
- `confidence` — overall confidence (0-1)
- `periodicity` — autocorrelation peak strength (0-1)
- `band_energy_db` — energy in the wing-beat band (dBFS)

## Practical tips

- **Microphone placement**: within 1-2 meters of the insect's flight path.
  Omnidirectional mics work best. Clip-on lapel mics are surprisingly good.
- **Background noise**: the bandpass filter rejects most environmental noise,
  but fans, HVAC, and machinery that produce tones in the 100-800 Hz range
  will cause false positives. Use `--noise-gate` to raise the threshold.
- **Multiple insects**: the autocorrelation picks up the strongest periodic
  signal. If two insects of different species are equally close, results
  are unpredictable. In practice, one is usually dominant.
- **Temperature**: wing-beat frequency varies slightly with temperature
  (insects fly faster when warm). The species ranges in the database are
  wide enough to accommodate typical outdoor temperatures.
- **Wind**: wind noise is broadband and non-periodic — it will not trigger
  false classifications but can reduce SNR and confidence.

## Dependencies

- numpy
- sounddevice (real-time mode only)
- dsp_pipeline (parent directory)
