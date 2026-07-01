# doppler-speed — Acoustic Doppler Speed Gun

Measures the speed of passing vehicles by detecting the pitch shift
between approach and departure. A passing car's engine note drops in
pitch as it goes by — the size of that drop reveals the speed.

## The physics

The Doppler effect shifts frequency proportional to radial velocity:

```
v = c × (f_approach - f_recede) / (f_approach + f_recede)
```

where c = 343 m/s (speed of sound at 20°C).

A car at 50 km/h produces a frequency shift of about 8% (1.3 semitones).
At 100 km/h it's about 16% (2.5 semitones). Easily measurable.

## Usage

```bash
# Point mic at a road, detect passing vehicles
python doppler_speed.py --input-device 2

# Log events to CSV
python doppler_speed.py --csv traffic_log.csv

# More sensitive (detect quieter/distant vehicles)
python doppler_speed.py --min-level -50

# Less pitch smoothing (faster response, noisier)
python doppler_speed.py --smoothing 0.5

# Test mode (simulated 50 km/h pass)
python doppler_speed.py --test
```

## Flags

- `--min-level DB` — minimum audio level for pitch detection (default: -40 dBFS)
- `--window-ms MS` — analysis window size (default: 100 ms)
- `--smoothing 0-1` — pitch smoothing factor (default: 0.7)
- `--csv FILE` — log events with timestamps
- Standard audio device flags

## How it detects a pass

State machine:
1. **Idle**: waiting for signal above threshold
2. **Approaching**: tracking pitch, level rising toward peak
3. **Receding**: level dropped >6 dB from peak, tracking lower pitch
4. **Event complete**: signal drops below threshold, compute speed

## Output

Each detected pass prints:
```
  PASS DETECTED: 52 km/h (32 mph) | 208→192 Hz
```

CSV columns: timestamp, f_approach_hz, f_recede_hz, speed_kmh, speed_mph, shift_semitones

## Accuracy

| Factor | Effect on accuracy |
|--------|-------------------|
| Engine harmonics | Vehicle must have a tonal component (most do) |
| Angle | Best at 90° to road; oblique angle underestimates |
| Distance | Farther = smaller angular rate = longer measurement |
| Wind | Adds/subtracts from apparent speed |
| Multiple vehicles | May confuse pitch tracker |

Typical accuracy: ±5-10 km/h for a single vehicle on a quiet road.
Better with a strong tonal harmonic (motorcycles, trucks with gear whine).

## Best practices

- Position mic perpendicular to traffic flow, 5-10 m from road
- Works best with a single vehicle passing (not rush hour)
- Motorcycles and trucks give strongest readings (more tonal)
- Electric vehicles may not produce enough tonal content
- Wind noise can overwhelm at roadside — use a windscreen

## Pitch detection

Uses the YIN algorithm (simplified):
- Computes difference function d(τ) = Σ(x(n) - x(n+τ))²
- Normalizes cumulatively (CMNDF)
- Finds first dip below threshold in valid lag range
- Parabolic interpolation for sub-sample accuracy

More robust than autocorrelation for noisy, complex signals like
engine noise with multiple harmonics.

## Limitations

- Requires a tonal sound source. Broadband noise (tire noise alone)
  has no detectable pitch and won't produce a speed reading.
- Single source only. Multiple simultaneous vehicles confuse the
  monophonic pitch tracker.
- Temperature affects speed of sound: ±1 m/s per ±2°C.
  Default assumes 20°C (343 m/s).
- Minimum speed ~20 km/h (below this, the shift is < 1 Hz and
  below detection resolution).

## Requirements

- `numpy`, `scipy`
- `sounddevice`
