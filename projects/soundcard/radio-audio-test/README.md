# radio-audio-test — End-to-End Radio Audio Chain Tester

Automates audio-quality testing of a complete radio link: stimulus
source → TX audio → RF path → RX audio → measurement capture.
Produces a one-page PDF report with frequency response, THD, and SNR
at multiple test frequencies.

## Signal path options

```
Option 1 (SDG1062X stimulus):
  SDG1062X ──→ Radio TX mic input ──RF──→ Radio RX ──→ Soundcard ──→ Analysis

Option 2 (soundcard-only):
  Soundcard out ──→ Radio TX mic input ──RF──→ Radio RX ──→ Soundcard in ──→ Analysis

Option 3 (repeater test):
  Soundcard out ──→ HT TX ──RF──→ Repeater ──RF──→ HT RX ──→ Soundcard in ──→ Analysis
```

## Usage

```bash
# With SDG1062X as stimulus
python radio_audio_test.py --sdg 10.1.1.55 --input-device 2 --pdf radio.pdf

# Soundcard loopback through radio
python radio_audio_test.py --input-device 2 --output-device 2 --pdf radio.pdf

# Custom test frequencies (for narrow-band modes)
python radio_audio_test.py --freqs "300,500,700,1000,1500,2000,2500" --pdf ssb.pdf

# Full output
python radio_audio_test.py --sdg 10.1.1.55 --pdf radio.pdf --csv radio.csv --json radio.json

# Test mode (no hardware)
python radio_audio_test.py --test --pdf test_radio.pdf
```

## Flags

- `--sdg IP` — SDG1062X IP for stimulus (omit for soundcard output)
- `--sdg-amplitude VPP` — SDG output level (default: 0.1 Vpp)
- `--duration SECS` — capture duration per frequency (default: 2)
- `--freqs LIST` — comma-separated test frequencies in Hz
  (default: 200,400,700,1000,1500,2000,2500,3000)
- `--pdf FILE` — PDF report output
- `--csv FILE` — CSV results
- `--json FILE` — JSON results
- Standard audio device flags

## What it measures

| Metric | Method |
|--------|--------|
| Frequency response | RMS level at each test frequency, normalized to 1 kHz |
| THD per frequency | Blackman-Harris FFT, harmonic search to 7th |
| SNR per frequency | Signal power in ±100 Hz vs rest of spectrum |
| Hum | Power at 50/60 Hz + harmonics (5 harmonics each) |
| Latency | Cross-correlation between TX reference and RX capture |
| In-band ripple | Max−min of 300–3000 Hz response points |

## Expected results (typical FM radio)

| Metric | Good | Acceptable | Poor |
|--------|------|-----------|------|
| Freq response (300–3000) | ±2 dB | ±4 dB | >±6 dB |
| THD | <2% | <5% | >5% |
| SNR | >40 dB | >30 dB | <30 dB |
| Hum | <-50 dBFS | <-40 dBFS | >-40 dBFS |

## Radio setup notes

- FM: set deviation appropriately for test level (1 kHz @ 3 kHz dev typical)
- SSB: operate well below ALC threshold to avoid clipping
- Repeater tests: ensure repeater courtesy tone doesn't overlap captures
- For TX audio via soundcard, level is critical — too high clips the
  radio's modulator, too low gives poor SNR

## Requirements

- `numpy`, `scipy`, `matplotlib`
- `sounddevice` (for live mode)
- `rf_bench.siglent` (only if using `--sdg`)
