# dtmf-decoder — DTMF Tone Decoder

Real-time DTMF (Dual-Tone Multi-Frequency) decoder using the Goertzel
algorithm. Detects all 16 DTMF digits with timing validation and twist
detection per ITU-T Q.24.

## DTMF Frequency Table

Each DTMF digit is encoded as the sum of one low-group frequency and
one high-group frequency:

```
            1209 Hz   1336 Hz   1477 Hz   1633 Hz
 697 Hz        1         2         3         A
 770 Hz        4         5         6         B
 852 Hz        7         8         9         C
 941 Hz        *         0         #         D
```

## Usage

```bash
# Real-time decode from soundcard
python dtmf_decoder.py

# Continuous decode with CSV logging
python dtmf_decoder.py --continuous --output dtmf_log.csv

# Test mode (synthetic 1234567890*#ABCD sequence)
python dtmf_decoder.py --test

# Adjust detection threshold for weak signals
python dtmf_decoder.py --threshold -40

# Stricter twist limits
python dtmf_decoder.py --max-twist 3 --max-reverse-twist 6
```

## Flags

- `--threshold DB` — detection threshold (default -30 dB)
- `--max-twist DB` — max normal twist, high/low ratio (default 4 dB)
- `--max-reverse-twist DB` — max reverse twist, low/high (default 8 dB)
- `--min-on MS` — minimum tone-on duration (default 40 ms, ITU-T Q.24)
- `--min-off MS` — minimum gap between digits (default 40 ms)
- `--output CSV` — log detected digits to CSV (timestamp, digit columns)
- `--continuous` — run indefinitely
- `--test` — synthetic DTMF test sequence
- Standard input audio flags (no output device needed)

## CSV Output Format

```csv
timestamp,digit,low_db,high_db
0.050,1,-18.2,-17.8
0.200,2,-18.1,-17.9
...
```

## Use Cases

- **Repeater control codes** — log DTMF commands sent to amateur
  repeaters (link/unlink, autopatch, IRLP/EchoLink nodes)
- **Autopatch logging** — decode dialled digits from autopatch audio
- **Telephone system debugging** — verify DTMF generation from handsets
  or PBX equipment
- **Security audit** — detect DTMF digits in recorded audio
- **Amateur radio** — decode DTMF sequences on VHF/UHF repeater inputs

## Twist

"Twist" is the power difference between the high-group and low-group
tones. Telephone lines attenuate higher frequencies more, so the high
group is typically transmitted at a higher level. Standards allow:

- Normal twist (high > low): up to 4 dB
- Reverse twist (low > high): up to 8 dB

The decoder rejects tones where twist exceeds these limits (configurable).

## Timing (ITU-T Q.24)

- Minimum tone-on: 40 ms (digit must be present for at least this long)
- Minimum tone-off: 40 ms (gap between consecutive digits)
- Typical DTMF generators produce 50-100 ms on, 50-100 ms off

## Limitations

- Block-based detection (1024 samples = ~21 ms at 48 kHz). Timing
  resolution is limited to the block size. For sub-block precision,
  reduce blocksize at the cost of frequency resolution.
- No talk-off protection beyond second-tone rejection. Speech energy
  at DTMF frequencies can occasionally trigger false detects.
- Single-channel mono input only.
