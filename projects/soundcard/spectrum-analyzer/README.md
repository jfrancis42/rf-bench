# spectrum-analyzer — Real-Time Audio Spectrum Analyzer

Live scrolling spectrum display with configurable FFT size, averaging,
peak hold, and dBFS scale. Supports terminal text bars, matplotlib live
window with optional waterfall/spectrogram, headless CSV logging, and
single-page PDF snapshot.

## Usage

```bash
# Live spectrum display (matplotlib)
python spectrum_analyzer.py --input-device 2

# Live with waterfall spectrogram
python spectrum_analyzer.py --input-device 2 --waterfall

# Terminal text-mode bars (no GUI needed)
python spectrum_analyzer.py --input-device 2 --terminal

# Higher spectral resolution (larger FFT)
python spectrum_analyzer.py --fft-size 8192

# More averaging for cleaner display
python spectrum_analyzer.py --averaging 16

# Peak hold overlay
python spectrum_analyzer.py --peak-hold

# Capture 10 seconds and save PDF
python spectrum_analyzer.py --output spectrum.pdf --capture-duration 10

# Capture and log to CSV
python spectrum_analyzer.py --log spectrum.csv --capture-duration 5

# Both PDF and CSV
python spectrum_analyzer.py --output spectrum.pdf --log spectrum.csv

# Test mode (synthetic two-tone + noise, no audio hardware needed)
python spectrum_analyzer.py --test
python spectrum_analyzer.py --test --output test_spectrum.pdf
python spectrum_analyzer.py --test --terminal
```

## Flags

### Spectrum

- `--fft-size N` — FFT size in samples (default 4096). Larger = better
  frequency resolution but slower update. Must accommodate blocksize.
- `--averaging N` — number of FFT frames to average before display update
  (default 8). Higher = smoother, slower.
- `--peak-hold` — overlay a red peak-hold trace showing the maximum
  level ever seen at each frequency bin.
- `--waterfall` — show a scrolling spectrogram/waterfall below the
  spectrum trace (matplotlib mode only).

### Output

- `--terminal` — text-mode bar display instead of matplotlib. Works
  over SSH, in tmux, without X11.
- `--log FILE.csv` — capture audio and write averaged spectrum as CSV
  with columns `freq_hz, magnitude_dbfs`. Non-real-time.
- `--output FILE.pdf` — capture audio and save spectrum plot as
  single-page PDF. Non-real-time.
- `--capture-duration SEC` — seconds of audio to capture for PDF/CSV
  modes (default 5.0).

### Standard audio flags

- `--input-device ID` — input device (use `--list-devices` to find)
- `--samplerate HZ` — sample rate (default 48000)
- `--blocksize N` — block size (default 2048)
- `--channels-in N` — input channels (default 1)
- `--list-devices` — list available audio devices and exit
- `--test` — use synthetic test signal instead of live audio
- `--test-duration SEC` — test signal length (default 5.0)

## Use cases

### Monitoring radio audio
Check the audio bandwidth of an SSB or FM receiver. Identify spurs,
birdies, and adjacent-channel leakage in demodulated audio.

### Checking transmitter bandwidth
Feed TX monitor audio into the soundcard. Verify speech bandwidth
is within limits and no spurious tones are present.

### Microphone response
Connect a mic and play a known signal (sweep or noise) from a speaker.
Save PDF for documentation of mic frequency response.

### Identifying interference
Use peak hold and high averaging to find steady-state carriers buried
in noise — power line harmonics, switching supply artifacts, computer
hash. The peak-hold trace reveals intermittent signals.

### Audio equipment characterization
Measure the noise floor of a preamp, mixer, or audio interface by
leaving the input terminated and capturing a PDF.

## CSV format

```
freq_hz,magnitude_dbfs
0.00,-120.00
11.72,-98.43
23.44,-95.12
...
```

One row per FFT bin. Frequency resolution = samplerate / fft_size.

## Dependencies

- numpy
- scipy (for windowing)
- sounddevice (live audio)
- matplotlib (live display and PDF output)
- dsp_pipeline (parent directory)
