# vox-filter — VOX with Anti-Trip Filtering

Software voice-operated transmit (VOX) that triggers PTT based on
speech-band energy while rejecting:
- Keyboard clicks (broadband, energy outside speech band)
- Background music (typically has more energy above 3 kHz)
- Fan/AC noise (broadband, steady state)

## How it works

1. Bandpass filter input to 300–3000 Hz (speech band)
2. Compute RMS of speech band and total signal
3. Trigger PTT only when:
   - Speech-band RMS exceeds threshold (adjustable)
   - Speech-band energy dominates out-of-band energy by anti-trip
     margin (default 10 dB)
4. Hang timer keeps PTT active between words

## Usage

```bash
# Basic VOX monitoring (displays PTT state changes)
python vox_filter.py --input-device 2

# More sensitive threshold for quiet speakers
python vox_filter.py --threshold-db -35

# Stronger anti-trip for noisy environments
python vox_filter.py --anti-trip-db 15

# Log PTT events with timestamps
python vox_filter.py --output ptt_log.csv

# Test: speech + clicks sequence
python vox_filter.py --test
```

## Flags

- `--threshold-db DBFS` — speech-band trigger level (default -30)
- `--hang-ms MS` — PTT hold time after speech stops (default 500)
- `--anti-trip-db DB` — speech must exceed out-of-band by this margin
  (default 10 dB). Higher = more rejection of non-speech.
- `--speech-low HZ` — speech band lower edge (default 300)
- `--speech-high HZ` — speech band upper edge (default 3000)
- `--output CSV` — log PTT transitions with timestamps
- Standard input audio flags

## Integration with radio PTT

This script currently outputs PTT state to the terminal and CSV.
To actually key a radio:

- Use with Hamlib: pipe PTT state to `rigctld` via a simple script
- Use with ESP32 `scpi-ptt`: send PTT commands over TCP
- Use with serial DTR/RTS: toggle a COM port pin for hardware PTT

A future enhancement could add `--ptt-command` flag to execute an
arbitrary command on PTT transitions.

## Limitations

- Audio-only detection. Cannot use radio squelch status or signal
  strength as input (unlike radio-integrated VOX).
- Anti-trip is ratio-based. A very loud broadband noise source that
  also has energy in the speech band can still trigger. Threshold
  must be set above the noise floor.
- Blocksize 512 at 48 kHz = ~10 ms latency. Fast enough for PTT
  but there's ~10 ms of speech before PTT keys. In practice the
  radio's TX attack time is similar, so first syllable clipping is
  minimal.
