# auto-notch — Automatic Heterodyne Notch Filter

Detects and removes steady-state carriers (birdies, adjacent-channel
heterodynes, tuner-upper carriers) from audio. Spawns a narrow IIR
notch at each detected frequency and tracks drift. Removes up to N
simultaneous heterodynes without affecting speech or CW.

Similar to the auto-notch in high-end radios (Icom twin PBT, Yaesu
contour) but in software with configurable notch count.

## Usage

```bash
# Real-time, up to 5 notches
python auto_notch.py --input-device 2 --output-device 4

# Narrower notches (higher Q) for closely-spaced signals
python auto_notch.py --notch-q 100

# Only look for carriers in the speech band
python auto_notch.py --min-freq 200 --max-freq 3000

# Test: speech + two heterodynes
python auto_notch.py --test --output notched.wav
```

## Flags

- `--max-notches N` — maximum simultaneous notch filters (default 5)
- `--notch-q Q` — notch quality factor (default 50). Higher = narrower
  notch, less signal damage, but less tolerance for drift.
- `--threshold-db DB` — how far above noise floor a carrier must be
  to trigger a notch (default 15 dB)
- `--min-freq HZ` / `--max-freq HZ` — search range (default 100–4000)
- `--tracking-rate RATE` — how fast notches follow drift (default 0.2)
- Standard audio flags

## How detection works

1. Compute magnitude spectrum of each block.
2. Smooth with exponential average (α=0.8) to distinguish steady
   carriers from transient speech peaks.
3. Find peaks above threshold relative to median noise floor.
4. Cluster adjacent bins, take peak of each cluster.
5. Match detected peaks to existing notches (within 50 Hz = same
   carrier). Track existing, add new, drop vanished.

## Limitations

- Detection delay: ~200 ms for the spectrum average to build up.
  A new heterodyne is audible for a fraction of a second before
  the notch locks on.
- Very narrow notches (Q>100) may ring on transient signals. Q=50
  is a good balance for most situations.
- Cannot notch a carrier that overlaps the desired signal's
  frequency. If the desired CW tone IS at the same frequency as
  the birdie, use the CW bandpass filter instead.
