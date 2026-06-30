# ook-power-detector — VNA as a single-frequency power detector

Tunes the VNA to a 2-point sweep around one frequency and samples
S21 repeatedly. Useful for:

- OOK / ASK link envelope tests
- Transmitter-key envelopes
- AGC behaviour vs time
- Slow on/off-keyed signals where you don't have a power-meter chain

## Usage

```bash
# Watch the envelope of a 145.5 MHz signal for 30 seconds
python ook_power_detector.py --freq 145.5 --duration 30 \
    --log envelope.csv --plot envelope.pdf
```

## Output

CSV: `t_s, s21_db, s21_mag, s21_phase_rad` per sample.
Optional PDF: |S21| dB vs time.

## Flags

- `--vna`, `--port`, `--host`
- `--freq MHZ` — required; sample frequency
- `--span MHZ` — sweep span around freq (default 1 kHz)
- `--duration SEC` — how long to sample (default 10)
- `--log FILE.csv` — required
- `--plot FILE.pdf` — optional

## Notes

- Time resolution = sweep cycle. NanoVNA: ~50–150 ms per sample.
- For higher rate, use a true RF power detector or a real CW mode
  in the HP 8712B (not yet exposed by the driver).
