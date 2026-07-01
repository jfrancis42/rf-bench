# thd-analyzer — Audio THD+N Analyzer

Measures Total Harmonic Distortion (THD), THD+N, and SINAD of an audio
signal captured from a soundcard. Identifies and reports individual
harmonics (2nd through 10th) with their levels.

## Usage

```bash
# Basic measurement from soundcard (auto-detect fundamental)
python thd_analyzer.py --duration 2

# Specify expected fundamental frequency
python thd_analyzer.py --fundamental 1000 --duration 3

# Generate PDF report
python thd_analyzer.py --fundamental 1000 --output thd_report.pdf

# Export harmonic data to CSV
python thd_analyzer.py --fundamental 1000 --csv harmonics.csv

# Test mode (generates 1 kHz with known distortion)
python thd_analyzer.py --test

# Test mode with PDF output
python thd_analyzer.py --test --output test_thd.pdf

# Select input device
python thd_analyzer.py --input-device 3 --fundamental 1000 --duration 5
```

## Flags

- `--fundamental HZ` — expected fundamental frequency. If not given,
  auto-detects the strongest peak between 20 Hz and 20 kHz.
- `--duration SEC` — capture duration (default 2.0 s). Longer captures
  improve frequency resolution but only the center 65536 samples
  (1.37 s at 48 kHz) are used for FFT analysis.
- `--output PDF` — write a single-page PDF with the magnitude spectrum,
  harmonic markers, and measurement summary.
- `--csv CSV` — write harmonic levels and summary metrics to a CSV file.
- `--window {blackmanharris,hann,flattop,hamming,kaiser}` — FFT window
  function (default blackmanharris). Blackman-Harris gives excellent
  sidelobe suppression (-92 dB) for THD measurement. Flat-top is better
  for absolute amplitude accuracy.
- `--samplerate HZ` — sample rate (default 48000).
- `--input-device ID` — soundcard input device (use --list-devices).
- `--list-devices` — show available audio devices and exit.
- `--test` — generate a synthetic signal with known distortion instead
  of capturing from soundcard.
- `--test-duration SEC` — duration of test signal (default 5.0 s).

## Measurements reported

| Metric | Definition |
|--------|-----------|
| THD (%) | sqrt(V2^2 + V3^2 + ... + Vn^2) / V1 * 100 |
| THD (dB) | 20*log10(THD_ratio) |
| THD+N (%) | RMS(signal with fundamental notched) / RMS(total) * 100 |
| SINAD (dB) | Signal / (Noise + Distortion), = -20*log10(THD+N_ratio) |

## Radio audio chain testing

Connect the signal generator output to the radio's audio input (mic or
line), and the radio's audio output (speaker or line) to the soundcard
input. Use a 1 kHz tone at a level that produces typical modulation:

```bash
# Measure audio chain of an HF transceiver in loopback
# (requires external tone source into mic input)
python thd_analyzer.py --fundamental 1000 --duration 3 --output radio_thd.pdf
```

For a full automated test, pair with the `radio-audio-test/` project
which drives the SDG1062X to inject the tone.

## Soundcard verification

Use `--test` mode to verify your measurement setup and confirm the
analyzer itself is working correctly. The test signal has known
distortion (H2=-40 dB, H3=-50 dB, H4=-60 dB) so you can validate
the computed THD matches the expected ~1.056%.

To characterize your soundcard itself, use a loopback cable (output to
input) with a clean signal source:

```bash
# Loopback test: send pure tone out, measure what comes back
# (requires external loopback or use soundcard-cal project)
python thd_analyzer.py --fundamental 1000 --duration 5 --output soundcard_thd.pdf
```

A good 24-bit audio interface should show THD below 0.002% (-94 dB).
A typical motherboard soundcard will be 0.01-0.1% (-80 to -60 dB).

## Limitations

- Frequency resolution is determined by FFT size (65536 samples at
  48 kHz = 0.73 Hz/bin). Fundamental must be stable within one bin.
- Harmonics above Nyquist/2 are not measured (aliased harmonics are
  not tracked).
- Best results with a pure tone input. Multi-tone or speech signals
  will produce misleading THD readings.
- The notch-based THD+N measurement includes all non-fundamental energy
  (noise, hum, spurs) — this is by design per the AES/IEC definition.
