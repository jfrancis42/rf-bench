# cw-bandpass — Adaptive CW Audio Bandpass with AFC

Ultra-tight audio bandpass filter for CW reception. User-selectable
bandwidth from 25 to 500 Hz, with automatic frequency control (AFC)
that tracks the CW tone as it drifts. Sharper than any radio's
built-in IF crystal filter.

## Usage

```bash
# Default: 700 Hz center, 100 Hz bandwidth, AFC on
python cw_bandpass.py --input-device 2 --output-device 4

# Narrower for crowded CW bands
python cw_bandpass.py --bandwidth 50

# Fixed frequency (no AFC) for pile-ups where you know exactly
# which station you want
python cw_bandpass.py --freq 650 --bandwidth 80 --no-afc

# Test mode: CW + interference
python cw_bandpass.py --test --output filtered.wav
```

## How AFC works

1. Each audio block is FFT'd.
2. Peak detection finds the dominant tone within ±2× bandwidth of
   the current center frequency.
3. If the peak is significantly above the noise floor (>3× median),
   the center frequency is slewed toward it at `--afc-rate`.
4. The bandpass filter is recomputed at the new center.

AFC rate 0.1 (default) means the filter moves 10% of the
frequency error per block (~21 ms). Slow enough to ignore brief
QRM spikes; fast enough to track typical drift.

## Flags

- `--freq HZ` — initial center frequency (default 700)
- `--bandwidth HZ` — filter width (default 100). Range 25–500.
- `--no-afc` — disable AFC, lock at --freq
- `--afc-rate RATE` — tracking speed 0–1 (default 0.1)
- `--output WAV` — save processed audio (test mode)
- Standard audio flags

## Typical ham radio CW bandwidths

| Situation | Bandwidth |
|-----------|-----------|
| Quiet band, single signal | 50–100 Hz |
| Moderate QRM | 100–200 Hz |
| Pile-up, known station | 25–50 Hz |
| Casual tuning / searching | 200–500 Hz |

## Limitations

- Filter is 4th-order Butterworth. At 25 Hz BW, the transition
  band is fairly gentle — true brick-wall requires higher order
  (at the cost of ringing). Good enough for subjective CW copy.
- AFC can lose lock if the CW signal is absent for more than a
  few seconds (between transmissions). It will re-acquire when
  the signal returns.
- Recomputing the filter coefficients every block (butterworth
  design) is heavier than a fixed filter. On modern hardware this
  is negligible at 48 kHz.
