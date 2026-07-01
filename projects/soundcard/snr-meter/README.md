# snr-meter — Audio SNR / SINAD Meter

Real-time signal-to-noise ratio estimation with three measurement
methods:

- **SINAD** — notch the fundamental, measure (S+N+D)/(N+D). Standard
  for FM receiver sensitivity (12 dB SINAD = usable sensitivity).
- **SNR** — spectral: signal power in peak bins vs total noise power.
- **Carrier** — energy-based: current RMS vs running noise floor
  estimate. Good for AM/SSB where you can't always identify a single
  carrier frequency.

## Usage

```bash
# SINAD measurement on 1 kHz test tone
python snr_meter.py --method sinad --notch-freq 1000

# Spectral SNR, 10-second measurement
python snr_meter.py --method snr --duration 10

# Continuous monitoring with CSV logging
python snr_meter.py --continuous --output snr_log.csv

# Test mode (synthetic 1 kHz + noise)
python snr_meter.py --test
```

## Flags

- `--method {sinad,snr,carrier}` — measurement type (default sinad)
- `--notch-freq HZ` — SINAD notch frequency (default 1000 Hz)
- `--duration SEC` — measurement window (default 5 s)
- `--continuous` — run indefinitely, updating display
- `--output CSV` — log timestamped measurements to CSV
- `--test` — use synthetic test signal
- Standard input audio flags (no output device needed)

## FM sensitivity measurement procedure

1. Connect signal generator → radio antenna input (through attenuator)
2. Set generator to carrier + 1 kHz FM deviation
3. Connect radio audio output → soundcard line-in
4. Run: `python snr_meter.py --method sinad --notch-freq 1000 --continuous`
5. Reduce generator level until SINAD reads 12.0 dB
6. Generator level at that point = receiver sensitivity

## Limitations

- SINAD method requires a single-frequency test tone. Not suitable
  for broadband audio.
- Carrier method uses a simple energy estimator. Needs a few seconds
  of quiet to establish the noise floor.
- No weighting filters (A-weighting, CCITT). Measurements are flat.
  Apply external weighting if needed for ITU-T compliance.
