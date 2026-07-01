# mic-response — Microphone Frequency Response Measurement

Measures the frequency response of a microphone by playing a known
excitation signal through a speaker and analyzing the captured audio.
Compensates for speaker/room coloration when a reference measurement
or calibration file is provided.

## Methods

| Method | Signal | Best for |
|--------|--------|----------|
| `sweep` (default) | Log-swept sine | Highest accuracy, single shot |
| `mls` | Maximum Length Sequence | Low-level signals, good noise rejection |
| `pink` | Pink noise (averaged) | Quick/dirty, no playrec sync needed |

## Usage

```bash
# Measure mic via speaker playback (sweep method)
python mic_response.py --input-device 2 --output-device 2 --pdf mic.pdf

# MLS method (better noise rejection)
python mic_response.py --method mls --pdf mic_mls.pdf

# Pink noise method
python mic_response.py --method pink --duration 10 --pdf mic_pink.pdf

# With speaker compensation (subtract known speaker response)
python mic_response.py --compensate speaker_cal.json --pdf mic.pdf

# Generate calibration JSON for use by other projects
python mic_response.py --output-json my_mic.json

# Test mode (no hardware)
python mic_response.py --test --pdf test_mic.pdf --csv test_mic.csv
```

## Flags

- `--method {sweep,mls,pink}` — excitation signal type (default: sweep)
- `--duration SECS` — test signal length (default: 5)
- `--reference JSON` — reference mic calibration to apply
- `--compensate JSON` — speaker response JSON to subtract (from soundcard-cal)
- `--smoothing N` — fractional-octave smoothing denominator (default: 3 = 1/3 octave)
- `--pdf FILE` — output PDF frequency response plot
- `--csv FILE` — output CSV (freq_hz, magnitude_db, smoothed_db)
- `--output-json FILE` — save response as calibration JSON
- Standard audio device flags

## Measurement procedure

1. Place microphone under test near the speaker (10–30 cm, on-axis)
2. Run in a quiet room (ambient noise raises the noise floor)
3. First run: use a known-flat reference mic to characterize
   speaker+room → save as `--output-json speaker_cal.json`
4. Second run: swap in mic under test, use `--compensate speaker_cal.json`
   to subtract speaker/room contribution

For casual use without a reference mic, the raw response still shows
the mic's general character (roll-off, peaks, resonances) — just
contaminated by the speaker and room.

## Compensation

The `--compensate` flag loads a calibration JSON (same format as
`soundcard-cal` output) and subtracts it point-by-point from the
measured response. This removes the speaker+room contribution,
leaving only the mic's response.

## Output

- **PDF**: Semi-log frequency response plot, raw + smoothed, ±3 dB
  reference lines, normalized to 0 dB at 1 kHz
- **CSV**: Three columns (freq_hz, magnitude_db, smoothed_db)
- **JSON**: Calibration file compatible with `--compensate` in other
  projects

## Limitations

- Requires speaker capable of reproducing the full test band. Most
  small speakers roll off below 100 Hz and above 15 kHz.
- Room reflections color the measurement. For accurate results,
  use close-mic technique (< 15 cm) or anechoic environment.
- Pink noise method has lower frequency resolution than sweep.
- MLS method requires the MLS length to be compatible with the
  capture duration.

## Requirements

- `numpy`, `scipy`, `matplotlib`
- `sounddevice` (for live mode)
