# ctcss-codec — CTCSS (PL Tone) Encoder/Decoder

Detect and generate sub-audible CTCSS tones used by FM repeaters and
simplex channels for squelch control. Also detects DCS (Digital Coded
Squelch) when present.

## Usage

```bash
# Decode CTCSS from radio audio (default mode)
python ctcss_codec.py --decode

# Decode with continuous output
python ctcss_codec.py --continuous

# Test mode — synthetic FM audio with 100.0 Hz (PL 1Z) tone
python ctcss_codec.py --test

# Encode 100.0 Hz tone onto input audio, output to speakers
python ctcss_codec.py --encode --tone 100.0

# Encode tone to WAV file (test signal)
python ctcss_codec.py --encode --tone 141.3 --test --output encoded.wav

# Encode live audio + tone to WAV
python ctcss_codec.py --encode --tone 100.0 --output tx_audio.wav --duration 10

# Print full tone table
python ctcss_codec.py --tone-table

# Use specific audio device and blocksize
python ctcss_codec.py --input-device 3 --blocksize 8192
```

## Flags

- `--decode` — detect CTCSS/DCS on input audio (default)
- `--encode` — generate CTCSS tone mixed with input
- `--tone HZ` — tone frequency for encode (default 100.0)
- `--tone-level FRAC` — tone amplitude, 0.0-1.0 (default 0.15)
- `--tone-table` — print the full EIA tone table and exit
- `--threshold DB` — detection threshold in dB (default -35)
- `--integration N` — number of blocks to average (default 4)
- `--duration SEC` — decode/encode duration (default 5)
- `--continuous` — run until Ctrl-C
- `--output WAV` — write encoded audio to WAV file
- `--test` — use synthetic test signal
- Standard audio I/O flags (`--input-device`, `--samplerate`, `--blocksize`)

## Standard CTCSS/PL Tone Table

All 50 EIA standard tones:

| Freq (Hz) | PL Code | Freq (Hz) | PL Code |
|-----------|---------|-----------|---------|
| 67.0      | XZ      | 156.7     | 5A      |
| 69.3      | WZ      | 159.8     | 5B      |
| 71.9      | XA      | 162.2     | 6Z      |
| 74.4      | WA      | 165.5     | 6A      |
| 77.0      | XB      | 167.9     | 6B      |
| 79.7      | WB      | 171.3     | 7Z      |
| 82.5      | YZ      | 173.8     | 7A      |
| 85.4      | YA      | 177.3     | 7B      |
| 88.5      | YB      | 179.9     | 8Z      |
| 91.5      | ZZ      | 183.5     | 8A      |
| 94.8      | ZA      | 186.2     | 8B      |
| 97.4      | ZB      | 189.9     | 9Z      |
| 100.0     | 1Z      | 192.8     | 9A      |
| 103.5     | 1A      | 196.6     | 9B      |
| 107.2     | 1B      | 199.5     | 0Z      |
| 110.9     | 2Z      | 203.5     | 0A      |
| 114.8     | 2A      | 206.5     | 0B      |
| 118.8     | 2B      | 210.7     | A1      |
| 123.0     | 3Z      | 218.1     | A2      |
| 127.3     | 3A      | 225.7     | B1      |
| 131.8     | 3B      | 229.1     | B2      |
| 136.5     | 4Z      | 233.6     | B3      |
| 141.3     | 4A      | 241.8     | B4      |
| 146.2     | 4B      | 250.3     | C1      |
| 151.4     | 5Z      | 254.1     | C2      |

## Repeater Identification

Connect your radio's audio output (line-out or headphone jack) to your
soundcard's line-in. Tune to a repeater and listen:

```bash
python ctcss_codec.py --continuous --threshold -40
```

The decoder will report which CTCSS tone the repeater is transmitting.
This is useful for:

- Identifying an unknown repeater's access tone
- Verifying your radio is sending the correct tone
- Monitoring for tone changes or interference
- Detecting DCS-encoded repeaters

## Encoding for Radios Without CTCSS

Some older radios (or modified radios with tone boards removed) lack
built-in CTCSS encode. Use encode mode to add tone to your transmit
audio:

1. Route your microphone through the soundcard
2. Run the encoder with the correct tone for the repeater
3. Feed the soundcard output to the radio's mic/line input

```bash
# Add 100.0 Hz (PL 1Z) to mic audio and send to radio
python ctcss_codec.py --encode --tone 100.0 --continuous
```

The tone level defaults to 15% of full scale, which produces
approximately 500-750 Hz of sub-audible deviation on most radios —
within the typical 300-1000 Hz CTCSS deviation spec.

Adjust `--tone-level` if the repeater doesn't open (too low) or if
you hear the tone bleeding into audio (too high).

## DCS Detection

DCS (Digital Coded Squelch) uses 134.4 bps FSK below 300 Hz instead of
a continuous tone. The decoder automatically checks for DCS alongside
CTCSS. If a DCS code is detected, it appears as `D023`, `D754`, etc.
in the output (octal notation, standard format).

## Blocksize and Resolution

Processing blocksize is 4096 samples at 48 kHz (~85 ms per callback).
Internally, the decoder accumulates a 20480-sample sliding analysis
window (~427 ms) giving ~2.34 Hz frequency resolution. This is the
minimum window that guarantees all 50 standard tones map to unique
Goertzel bins (closest pair: 67.0/69.3 Hz, 2.3 Hz apart). Integration
over 4 analysis windows provides reliable detection with first result
in ~1.7 seconds from start.

The processing blocksize (4096) controls callback rate and latency to
the audio system. The analysis window length controls frequency
resolution. These are independent parameters.
