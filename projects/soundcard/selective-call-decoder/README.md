# selective-call-decoder — Sequential Tone Signaling Decoder

Decodes two-tone and five-tone sequential selective calling used by
commercial and public-safety radios in the pre-digital era:

- **CCIR** (International, most common worldwide)
- **ZVEI** (German standard, common in Europe)
- **EIA** (US/Canada standard)

## How it works

Sequential tone signaling encodes each digit (0–9 plus special codes)
as a burst of a specific audio frequency, transmitted one after
another. Typically 33–100 ms per tone, 5 tones per call for five-tone
systems or 2 tones for two-tone paging.

The decoder uses the Goertzel algorithm (efficient single-frequency
DFT) at each tone table frequency, identifies the strongest tone per
analysis window, validates timing, and assembles the digit sequence.

## Usage

```bash
# Real-time CCIR 5-tone decode
python selective_call_decoder.py --input-device 2

# ZVEI system
python selective_call_decoder.py --system zvei

# Two-tone paging mode
python selective_call_decoder.py --tones 2

# Log decoded calls to CSV
python selective_call_decoder.py --output calls.csv

# Test mode (generates and decodes a synthetic sequence)
python selective_call_decoder.py --test
```

## Flags

- `--system {ccir,zvei,eia}` — tone table (default ccir)
- `--tones N` — tones per call sequence (default 5, use 2 for paging)
- `--threshold-db DB` — detection threshold (default 10 dB above
  other tones)
- `--min-tone-ms MS` — minimum tone duration (default 33 ms)
- `--output CSV` — log calls with timestamps
- Standard input audio flags

## Tone tables

### CCIR (most common)

| Digit | Frequency (Hz) |
|-------|----------------|
| 0 | 1981 |
| 1 | 1124 |
| 2 | 1197 |
| 3 | 1275 |
| 4 | 1358 |
| 5 | 1446 |
| 6 | 1540 |
| 7 | 1640 |
| 8 | 1747 |
| 9 | 1860 |
| Repeat | 2110 |

### ZVEI-1

| Digit | Frequency (Hz) |
|-------|----------------|
| 0 | 2400 |
| 1 | 1060 |
| 2 | 1160 |
| 3 | 1270 |
| 4 | 1400 |
| 5 | 1530 |
| 6 | 1670 |
| 7 | 1830 |
| 8 | 2000 |
| 9 | 2200 |
| Repeat | 2600 |

## Companion project

The transmit side of selective calling is implemented in
`~/selcall/` (Qt6/C++ with REST API on port 8073). This decoder
handles the receive/monitoring side.

## Limitations

- Goertzel-based detection requires the analysis window to be at
  least one full cycle of the tone. At 33 ms minimum and 1060 Hz
  lowest tone, this gives ~35 cycles — adequate.
- No "repeat" tone handling (CCIR digit 10 means "same as previous
  digit"). Currently decoded as literal digit 10.
- DCS (Digital Coded Squelch) not yet implemented. Would require
  134.4 bps NRZI FSK decoder at 136.5/131.8 Hz.
- Two-tone mode may accumulate stale tones if there's a long gap.
  Timeout resets the sequence after ~200 ms of silence.
