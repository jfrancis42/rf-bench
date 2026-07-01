# impulse-blanker — Real-Time Impulse Noise Blanker

Detects and removes short-duration impulse noise: ignition clicks,
switching power supply spikes, LED dimmer hash, static crashes.
Operates in the time domain for minimum latency.

## How it works

1. Maintains a running RMS estimate of signal level.
2. When a sample exceeds the threshold (configurable dB above RMS),
   it's flagged as an impulse.
3. The impulse extent is traced forward until signal drops below
   threshold or max-blank-duration is reached.
4. The blanked region is filled by interpolation (linear, zero, or
   sample-hold).

## Usage

```bash
# Real-time blanking
python impulse_blanker.py --input-device 2 --output-device 4

# More aggressive: lower threshold, allow longer blanks
python impulse_blanker.py --threshold-db 8 --max-blank-ms 5

# Test mode with synthetic impulse noise
python impulse_blanker.py --test --output blanked.wav
```

## Flags

- `--threshold-db DB` — trigger level above running RMS (default 12).
  Lower = more sensitive (catches smaller spikes). Too low = blanks
  speech peaks.
- `--max-blank-ms MS` — maximum contiguous blank duration (default
  2.0 ms). Prevents blanking entire words if threshold is set low.
- `--method {linear,zero,hold}` — how to fill blanked samples:
  - `linear`: interpolate between last good sample before and first
    good sample after. Least audible artifact.
  - `zero`: replace with silence. Simple but produces clicks at
    edges.
  - `hold`: repeat the last sample before the impulse. Good for CW.
- `--output WAV` — write processed audio to file (test mode).
- Standard audio flags.

## Cascade with other tools

The impulse blanker is most effective as the FIRST stage in a chain:

```bash
# Blank impulses → then spectral denoise for residual hiss
# (would use the pipeline framework for chaining)
```

Impulse blanking before spectral subtraction prevents the impulses
from corrupting the noise profile estimate.

## Limitations

- Short impulses (1–2 samples) are removed cleanly. Longer bursts
  (>5 ms) may leave audible interpolation artifacts.
- Not effective against repetitive interference at a fixed rate
  (e.g., 120 Hz power-line buzzing). Use de-hum for that.
- The threshold is relative to running RMS, so the blanker adapts
  to changing signal levels. But sudden signal changes (start of a
  transmission) may briefly trigger false blanks.
