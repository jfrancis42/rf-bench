# soundcard-cal — Soundcard Self-Calibration

Characterizes the PC soundcard as a measurement instrument by running
automated loopback tests (output → input). Produces a calibration JSON
file that other soundcard projects can load to apply frequency response
correction, know their noise floor, and understand crosstalk limits.

## What it measures

| Measurement | Method |
|-------------|--------|
| Noise floor (dBFS) | Record silence, compute RMS |
| Dynamic range (dB) | Full-scale – noise floor |
| Frequency response | Log-swept sine, cross-spectral H(f) = Y(f)/X(f) |
| THD (1 kHz) | Single-tone, Blackman-Harris window, harmonic search |
| Channel crosstalk | Tone on L only, measure leakage on R |

## Usage

```bash
# Loopback cable required: connect output to input
python soundcard_cal.py

# Specify devices
python soundcard_cal.py --input-device 2 --output-device 2

# Generate PDF report
python soundcard_cal.py --pdf report.pdf

# Custom output file
python soundcard_cal.py --output my_soundcard.json

# Test mode (no hardware, synthetic impairments)
python soundcard_cal.py --test --pdf test_report.pdf
```

## Flags

- `--output FILE` — calibration JSON output (default: `soundcard_cal.json`)
- `--pdf FILE` — generate calibration report PDF
- `--duration SECS` — test signal duration (default: 3.0)
- Standard audio device flags (`--input-device`, `--output-device`, etc.)
- `--test` — run with synthetic data (no soundcard needed)

## Output format

```json
{
  "timestamp": "2025-01-01T00:00:00+00:00",
  "samplerate": 48000,
  "noise_floor_dbfs": -96.2,
  "dynamic_range_db": 96.2,
  "thd_1khz_pct": 0.0032,
  "thd_1khz_db": -89.9,
  "crosstalk_db": -62.4,
  "freq_response": {
    "freqs_hz": [0, 33, 66, ...],
    "magnitude_db": [0.0, -0.1, -0.2, ...]
  }
}
```

## Using the calibration

Other projects can load the JSON and apply correction:

```python
import json, numpy as np

with open("soundcard_cal.json") as f:
    cal = json.load(f)

# Correction curve (inverse of measured response)
freqs = np.array(cal["freq_response"]["freqs_hz"])
mag = np.array(cal["freq_response"]["magnitude_db"])
correction_db = -mag  # invert to flatten
```

## What makes a good soundcard?

| Parameter | Typical onboard | Good external | Excellent |
|-----------|----------------|---------------|-----------|
| Noise floor | -80 dBFS | -96 dBFS | -110 dBFS |
| THD (1 kHz) | 0.01% | 0.001% | 0.0005% |
| Freq response | ±3 dB | ±0.5 dB | ±0.1 dB |
| Crosstalk | -50 dB | -70 dB | -90 dB |

## Requirements

- `numpy`, `scipy`, `matplotlib`
- `sounddevice` (for live mode)
- Loopback cable (3.5mm TRS M-M or equivalent)
