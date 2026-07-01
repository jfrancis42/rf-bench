# ssb-sim — SSB Radio Signal Simulator

Makes any audio input sound like it's being received on a single-sideband
radio. Applies bandwidth limiting, receiver noise, AGC, optional mis-tune
offset, and propagation fading.

## Bandwidth presets

| Preset | Passband | Width | Typical use |
|--------|----------|-------|-------------|
| `cw-narrow` | 250–550 Hz | 300 Hz | Narrow CW filter |
| `cw` | 400–900 Hz | 500 Hz | Standard CW |
| `ssb-narrow` | 300–2100 Hz | 1.8 kHz | Narrow SSB (DX) |
| `ssb` | 300–2700 Hz | 2.4 kHz | Standard SSB (default) |
| `ssb-wide` | 300–3000 Hz | 2.7 kHz | Wide SSB (local) |
| `am` | 100–3600 Hz | 3.5 kHz | AM-equivalent width |

Custom bandwidth: use `--low` and `--high` to specify any passband.

## Usage

```bash
# Standard SSB sound
python ssb_sim.py --input-device 15 --output-device 15

# Narrow SSB (DX contest sound)
python ssb_sim.py --preset ssb-narrow --input-device 15 --output-device 15

# CW filter (only passes ~500 Hz band)
python ssb_sim.py --preset cw --input-device 15 --output-device 15

# Noisy band conditions
python ssb_sim.py --noise -25 --input-device 15 --output-device 15

# Mis-tuned (that characteristic SSB "duck voice" sound)
python ssb_sim.py --offset 150 --input-device 15 --output-device 15

# Fading (HF propagation sim)
python ssb_sim.py --fading --fading-rate 0.5 --input-device 15 --output-device 15

# Full HF DX experience: narrow, noisy, fading, slightly off-frequency
python ssb_sim.py --preset ssb-narrow --noise -30 --fading --offset 50

# Custom passband (e.g. 500-2000 Hz)
python ssb_sim.py --low 500 --high 2000

# Disable AGC (raw signal, no leveling)
python ssb_sim.py --no-agc

# Test mode
python ssb_sim.py --test
```

## Flags

### Bandwidth
- `--preset NAME` — bandwidth preset (default: `ssb`)
- `--low HZ` — custom low cutoff (overrides preset)
- `--high HZ` — custom high cutoff (overrides preset)

### Effects
- `--offset HZ` — frequency offset simulating mis-tune (default: 0).
  Positive shifts up, negative shifts down. ±50-200 Hz for that
  classic "not quite tuned in" sound.
- `--noise DB` — receiver noise floor (default: -40). Use -25 for
  noisy conditions, -60 for very quiet.
- `--fading` — enable selective fading (propagation simulation)
- `--fading-rate HZ` — fading speed (default: 0.3 Hz). Slower =
  more realistic HF fading.
- `--agc-attack MS` — AGC attack time (default: 5 ms)
- `--agc-release MS` — AGC release time (default: 300 ms)
- `--no-agc` — disable AGC entirely

### Audio
- Standard device args (`--input-device`, `--output-device`,
  `--samplerate`, `--blocksize`)

## Signal chain

```
Input → Freq Offset → Bandpass Filter → Add Noise → Fading → AGC → Soft Clip → Output
```

1. **Frequency offset**: multiplies by cos(2πft) to shift spectrum.
   Simulates being tuned off-frequency.
2. **Bandpass filter**: 6th-order Butterworth. Steep skirts (~36 dB/oct)
   like a real crystal/ceramic SSB filter.
3. **Noise**: band-limited white noise added at configurable level.
   Filtered through the same bandpass for realism.
4. **Fading**: slow sinusoidal amplitude modulation (0.3× to 1.0×).
   Simulates ionospheric multipath on HF.
5. **AGC**: per-sample envelope follower with asymmetric attack/release.
   Fast attack prevents clipping on strong signals. Slow release
   causes the characteristic "pumping" sound.
6. **Soft clip**: tanh() prevents output exceeding ±1.0.

## Suggested settings for different scenarios

| Scenario | Command |
|----------|---------|
| Local net (strong, clean) | `--preset ssb-wide --noise -55` |
| Casual HF QSO | `--preset ssb --noise -40` |
| DX pileup | `--preset ssb-narrow --noise -30 --fading` |
| Weak signal DX | `--preset ssb-narrow --noise -25 --fading --offset 30` |
| AM broadcast feel | `--preset am --noise -50 --no-agc` |
| CW through QRM | `--preset cw --noise -30 --fading` |

## Requirements

- `numpy`, `scipy`
- `sounddevice` (for live mode)
