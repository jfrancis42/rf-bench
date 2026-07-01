# wiener-filter — Optimal Wiener Noise Reduction

Frequency-domain Wiener filter: the theoretically optimal linear
filter for recovering a stationary signal from stationary noise.
Produces fewer "musical noise" artifacts than spectral subtraction
because the gain function is smoother (ratio, not difference).

## How it works

The Wiener gain at each frequency bin is:

```
H(f) = Pss(f) / (Pss(f) + Pnn(f))
```

Where Pss is signal power, Pnn is noise power. When SNR is high,
H→1 (pass through). When SNR is low, H→0 (attenuate). The
transition is smooth — no hard threshold, no musical artifacts.

1. Capture noise PSD during initial silence (same as spectral
   subtraction).
2. Estimate instantaneous signal+noise PSD from each block.
3. Subtract noise PSD estimate to get signal-only PSD.
4. Compute Wiener gain per bin, apply to spectrum, IFFT.

The signal PSD estimate is exponentially smoothed (configurable α)
to prevent the gain from chattering on transients.

## Usage

```bash
# Real-time
python wiener_filter.py --input-device 2 --output-device 4

# More aggressive noise reduction (lower floor)
python wiener_filter.py --floor-db -40

# Faster tracking of signal changes
python wiener_filter.py --alpha 0.8

# Test mode
python wiener_filter.py --test --output wiener_out.wav
```

## Flags

- `--noise-frames N` — initial blocks for noise PSD (default 20)
- `--alpha FACTOR` — signal PSD smoothing (default 0.95). Lower =
  faster adaptation to signal changes but noisier gain estimate.
- `--floor-db DB` — minimum gain floor (default -30). Prevents
  complete silence in noise-only bins (which sounds unnatural).
- `--output WAV` — save output to file (test mode)
- Standard audio flags

## Wiener vs spectral subtraction

| | Spectral subtraction | Wiener filter |
|-|---------------------|---------------|
| Gain function | max(|X| - α|N|, floor) | Pss / (Pss + Pnn) |
| Musical artifacts | Common at high subtraction depths | Rare |
| Computational cost | Lower | Slightly higher |
| Theoretical basis | Heuristic | Optimal (MMSE) |
| Noise tracking | None (fixed profile) | Smoothed PSD estimate |

## Limitations

- Same noise-is-stationary assumption as spectral subtraction.
- PSD smoothing (alpha) trades noise reduction depth against signal
  transient preservation. No single setting is optimal for both CW
  and SSB voice.
- Initial noise capture period required. During capture, no
  processing occurs.
