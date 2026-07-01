# two-tone-imd — Two-Tone Intermodulation Distortion Analyzer

Generates two equal-amplitude test tones and measures the
intermodulation distortion products produced by a device under test
(amplifier, transmitter, soundcard, etc.). The standard SSB two-tone
test uses 700 + 1900 Hz — this is the default.

IMD is the primary measure of amplifier linearity. When two tones pass
through a nonlinear device, mixing products appear at frequencies that
are sums and differences of the input frequencies and their harmonics.
The strongest (and most damaging) are the 3rd-order products at
2f1-f2 and 2f2-f1, which fall close to the original signals and cannot
be filtered out. In an SSB transmitter, these products appear as
"splatter" on adjacent channels.

## Usage

```bash
# Test mode — synthetic distorted signal, no hardware needed
python two_tone_imd.py --test --output imd_test.pdf

# Generate tones only (feed into transmitter audio input)
python two_tone_imd.py --generate-only --output-device 4

# Analyze only (capture from receiver or monitor output)
python two_tone_imd.py --analyze-only --input-device 2 --output imd.pdf

# Loopback (generate + capture simultaneously)
python two_tone_imd.py --loopback --input-device 2 --output-device 4 --output imd.pdf

# Custom tone frequencies
python two_tone_imd.py --f1 600 --f2 1500 --test --output custom.pdf

# Longer capture for more frequency resolution
python two_tone_imd.py --analyze-only --duration 5 --input-device 2 --output imd.pdf

# List available audio devices
python two_tone_imd.py --list-devices
```

## Flags

### Mode selection

- `--generate-only` — Output tones continuously until Ctrl-C. No capture.
- `--analyze-only` — Capture audio from input device and measure IMD.
- `--loopback` — Generate tones on output while capturing on input
  simultaneously. This is the default if no mode flag is given.
- `--test` — Use a synthetic distorted signal with known IMD levels
  (IMD3=-30 dBc, IMD5=-50 dBc, IMD7=-65 dBc). No audio hardware needed.

### IMD parameters

- `--f1 HZ` — First tone frequency (default 700 Hz)
- `--f2 HZ` — Second tone frequency (default 1900 Hz)
- `--duration SEC` — Capture duration in seconds (default 2.0). Longer
  captures give finer frequency resolution (df = 1/duration Hz).
- `--label TEXT` — Optional label for the PDF chart title

### Output

- `--output FILE.pdf` — Write PDF spectrum plot with labeled IMD products

### Standard audio flags

- `--input-device ID` / `--output-device ID` — sounddevice IDs
- `--samplerate HZ` — sample rate (default 48000)
- `--blocksize N` — processing block size (default 1024)
- `--channels-in N` / `--channels-out N` — channel counts
- `--list-devices` — show available audio devices and exit
- `--test` — use synthetic test signal
- `--test-duration SEC` — test signal length (default 5.0)

## IMD Products and Linearity

Given two input tones at f1 and f2, a nonlinear device produces mixing
products at:

| Order | Products | Typical location |
|-------|----------|-----------------|
| 2nd | f2-f1, f1+f2 | Far from carriers (usually filtered) |
| 3rd | 2f1-f2, 2f2-f1 | Close to carriers (cannot be filtered) |
| 5th | 3f1-2f2, 3f2-2f1 | Close to carriers |
| 7th | 4f1-3f2, 4f2-3f1 | Close to carriers |

With the standard 700 + 1900 Hz tones:
- 3rd order: 2(700)-1900 = -500 Hz (aliases to 500), 2(1900)-700 = 3100 Hz
- 5th order: 3(700)-2(1900) = -1700 (aliases to 1700), 3(1900)-2(700) = 4300 Hz
- 7th order: 4(700)-3(1900) = -2900 (aliases to 2900), 4(1900)-3(700) = 5500 Hz

The 3rd-order products are most critical because:
1. They fall closest to the fundamental tones
2. They are the strongest distortion products
3. They represent "splatter" in an SSB signal

## Interpreting Results

- **IMD3 -25 dBc or worse**: Poor linearity. Excessive ALC compression
  or amplifier saturation. Reduce drive level.
- **IMD3 -30 to -35 dBc**: Typical for a moderately-driven SSB
  transmitter. Acceptable for casual operation.
- **IMD3 -35 to -40 dBc**: Good linearity. Well-designed Class AB
  amplifier at moderate power.
- **IMD3 below -40 dBc**: Excellent. Contest-grade amplifier running
  well below saturation.

## SSB Transmitter Testing Procedure

1. Connect the soundcard output to the transmitter's audio input
   (mic jack or line input, depending on radio).
2. Connect a dummy load to the transmitter output.
3. If available, connect a monitor output or directional coupler
   sample to the soundcard input for the return path measurement.
4. Set the transmitter to USB or LSB mode, disable speech processing
   and compression.
5. Run in generate-only mode first to set drive level:
   ```bash
   python two_tone_imd.py --generate-only --output-device 4
   ```
   Adjust audio level until the transmitter shows approximately 2/3
   to 3/4 of full output on the power meter. The two-tone signal has
   a higher peak-to-average ratio than speech, so don't push to full
   power.
6. Run the full loopback or analyze-only measurement:
   ```bash
   python two_tone_imd.py --analyze-only --input-device 2 \
       --duration 3 --output my_radio_imd.pdf
   ```

## PDF Output

The PDF contains a single-page magnitude spectrum plot showing:
- The full captured spectrum in the region around the tones
- Both fundamental tones marked in green with their absolute levels
- All detected IMD products marked with their level in dBc:
  - 3rd order in red
  - 5th order in orange
  - 7th order in purple
  - 2nd order in gray
- A summary line with the worst-case IMD3 figure

## Dependencies

- numpy
- sounddevice
- matplotlib (for PDF output only)
- scipy (optional, for better windowing)
