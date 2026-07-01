# parametric-eq — N-Band Parametric Equalizer

Cascaded peaking EQ biquad filters for shaping receiver audio per
mode. Each band has independently adjustable center frequency, Q
(bandwidth), and gain (boost/cut). Ships with tuned presets for CW,
SSB, AM, and FM receive paths.

Useful for compensating radio speaker deficiencies, tailoring audio
to headphones vs speakers, or optimizing intelligibility per mode.

## Usage

```bash
# Real-time with SSB preset (default)
python parametric_eq.py --input-device 2 --output-device 4

# CW preset — tight peak at 700 Hz, steep rolloff above and below
python parametric_eq.py --preset cw

# FM broadcast preset — bass boost + de-emphasis recovery
python parametric_eq.py --preset fm

# Custom bands: boost 700 Hz by 6 dB (Q=5), cut 1200 Hz by 4 dB (Q=3)
python parametric_eq.py --bands "700:5:+6,1200:3:-4"

# Test mode: process synthetic speech, write to file
python parametric_eq.py --test --preset cw --output eq_cw.wav

# List all presets with their band definitions
python parametric_eq.py --list-presets

# Flat (bypass) — all EQ disabled, clean passthrough
python parametric_eq.py --preset flat
```

## Flags

- `--preset {cw,ssb,am,fm,flat}` — load a mode-specific EQ curve
- `--bands SPEC` — custom bands as comma-separated `freq:q:gain_db`
  triplets (overrides `--preset` if both given)
- `--list-presets` — print all presets with band details and exit
- `--output WAV` — write processed audio to file (test mode only)
- Standard audio flags (`--input-device`, `--output-device`,
  `--samplerate`, `--blocksize`, `--channels-in`, `--channels-out`,
  `--list-devices`)
- Standard test flags (`--test`, `--test-duration`)

## Presets

### CW

Peaked around 700 Hz with aggressive rolloff. Maximizes CW tone
SNR by rejecting everything outside a narrow band.

| Freq   | Q   | Gain   | Purpose              |
|--------|-----|--------|----------------------|
| 400 Hz | 4.0 | -6 dB  | Cut low rumble       |
| 700 Hz | 5.0 | +6 dB  | Boost CW tone center |
| 1200 Hz| 3.0 | -4 dB  | Cut above passband   |
| 2500 Hz| 2.0 | -12 dB | Steep HF rolloff     |

### SSB

Optimized for speech intelligibility on sideband. Mild low-end
warmth, presence lift, sibilance control.

| Freq    | Q   | Gain   | Purpose            |
|---------|-----|--------|--------------------|
| 250 Hz  | 1.5 | +3 dB  | Low-end warmth     |
| 800 Hz  | 1.0 | +2 dB  | Presence lift      |
| 1800 Hz | 1.2 | +1.5 dB| Clarity            |
| 2700 Hz | 2.5 | -3 dB  | Tame filter edge   |

### AM

Compensates for AM receiver characteristics: removes carrier hum,
adds body, controls hiss.

| Freq    | Q   | Gain   | Purpose            |
|---------|-----|--------|--------------------|
| 100 Hz  | 1.0 | -6 dB  | Carrier hum cut    |
| 400 Hz  | 0.8 | +2 dB  | Body               |
| 1500 Hz | 0.7 | +1 dB  | Midrange presence  |
| 4000 Hz | 1.5 | -4 dB  | Hiss control       |
| 6000 Hz | 2.0 | -10 dB | Steep HF cut       |

### FM

Tailored for FM broadcast audio (VHF). Recovers bass lost to
de-emphasis, adds air/sparkle.

| Freq     | Q   | Gain   | Purpose              |
|----------|-----|--------|----------------------|
| 80 Hz    | 1.2 | +3 dB  | Bass recovery        |
| 400 Hz   | 0.7 | +1 dB  | Warmth               |
| 2500 Hz  | 0.8 | +2 dB  | Presence / clarity   |
| 6000 Hz  | 1.0 | +1.5 dB| Air / sparkle        |
| 12000 Hz | 2.0 | -3 dB  | Tame excessive HF    |

### Flat

No bands — clean passthrough. Useful for A/B comparison.

## Band specification format

Each band is `freq:q:gain_db`:

- **freq** — center frequency in Hz (positive)
- **q** — quality factor (positive; higher = narrower bandwidth)
- **gain_db** — boost (+) or cut (-) in dB

Multiple bands separated by commas:

```
"300:2:+3,800:4:-2,2000:1.5:+4"
```

## Limitations

- Gain stacking across multiple boosted bands can push the output
  above 0 dBFS. Soft clipping (tanh) prevents hard clipping but
  adds subtle distortion at extreme settings.
- Filter redesign is not per-block (bands are fixed at startup).
  No runtime band adjustment without restart.
- No high-pass or low-pass shelf filters — only peaking EQ. Use
  the bandpass-slicer or cw-bandpass projects for shelf behavior.
