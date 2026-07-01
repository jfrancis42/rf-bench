# freq-response — Audio Frequency Response Sweeper

Measures the frequency response (magnitude and phase) of an audio path by
playing a logarithmic chirp and computing the transfer function H(f) = Y(f)/X(f).

Produces a Bode-plot PDF (magnitude dB + phase degrees vs log frequency) and
optional CSV export.

## Requirements

- Python 3.10+
- numpy, scipy, matplotlib, sounddevice, soundfile
- dsp_pipeline (parent directory)

## Modes

### Loopback (`--loopback`)

Plays the chirp from the soundcard output and simultaneously records on the
input.  Use for:

- **Soundcard self-test:** cable from output to input.  Measures the soundcard's
  own frequency response and latency.
- **DUT measurement:** soundcard output → DUT input, DUT output → soundcard input.
  The measured response is the DUT transfer function (soundcard contribution
  cancels if it's flat, or can be calibrated out with a loopback reference).

```bash
python3 freq_response.py --loopback --output response.pdf --csv response.csv
```

### Analyze WAV (`--analyze FILE`)

Computes the transfer function from a pre-recorded WAV file.  Useful when
capture and playback are done separately (different machines, different times).

Provide the original chirp as `--reference`:

```bash
python3 freq_response.py --analyze captured.wav --reference chirp.wav --output response.pdf
```

If `--reference` is omitted, the tool generates the default chirp internally
(assumes you used the same --start-freq, --stop-freq, --duration settings).

### Test (`--test`)

Synthetic self-test with no hardware.  Generates a chirp, applies a known
2nd-order Butterworth LPF at 5 kHz, and verifies the computed response
matches the expected -12 dB/octave rolloff.

```bash
python3 freq_response.py --test --output test.pdf
```

## Flags

| Flag | Default | Description |
|------|---------|-------------|
| `--start-freq` | 20 | Sweep start frequency (Hz) |
| `--stop-freq` | 20000 | Sweep stop frequency (Hz) |
| `--duration` | 5.0 | Chirp duration (seconds) |
| `--smoothing` | 0.083 (1/12 octave) | Fractional-octave smoothing (0 to disable) |
| `--output` | — | PDF output path |
| `--csv` | — | CSV output path |
| `--loopback` | — | Duplex play+record mode |
| `--analyze` | — | Analyze pre-recorded WAV |
| `--reference` | — | Reference WAV for --analyze |
| `--test` | — | Synthetic test mode |
| `--input-device` | default | Sounddevice input device ID |
| `--output-device` | default | Sounddevice output device ID |
| `--samplerate` | 48000 | Sample rate (Hz) |
| `--list-devices` | — | List audio devices and exit |

## Measurement Procedure

### Soundcard self-test

1. Connect a cable from your soundcard's line output to its line input.
2. Run: `python3 freq_response.py --loopback --output soundcard.pdf`
3. The result shows your soundcard's own frequency response (should be
   nearly flat from ~20 Hz to ~20 kHz on any decent interface).

### DUT testing

1. Connect: soundcard line out → DUT input, DUT output → soundcard line in.
2. Optionally run a soundcard self-test first for calibration reference.
3. Run: `python3 freq_response.py --loopback --output dut.pdf --csv dut.csv`
4. The result is the DUT's transfer function convolved with the soundcard's.
   If the soundcard is flat (or you have a calibration CSV), the deviation
   from 0 dB is the DUT's response.

### Typical DUTs

- Audio amplifiers (preamps, power amps)
- Equalizers and crossovers
- Radio audio chains (mic → modulator → demodulator → speaker)
- Cable runs (long runs may show HF rolloff)
- Transformers (audio coupling transformers, baluns)

## Output Format

### PDF

Two-panel Bode plot:
- **Top panel:** Magnitude in dB vs log frequency (Hz).  0 dB = unity gain.
- **Bottom panel:** Phase in degrees vs log frequency.  Range: -180 to +180.

### CSV

Three columns: `freq_hz`, `magnitude_db`, `phase_deg`.  One row per FFT bin
(within the start/stop frequency range).  Suitable for import into spreadsheets
or further processing.
