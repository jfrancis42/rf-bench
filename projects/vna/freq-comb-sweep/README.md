# freq-comb-sweep — S21 at a discrete list of frequencies

Skip linear sweeps when you only need specific tones (WSPR/FT8
channels, harmonic mixer tests, comb-receiver verification).

## Usage

```bash
# Arithmetic comb: 10, 11, ..., 30 MHz
python freq_comb_sweep.py --comb 10 1 21 \
    --label "1-MHz spaced HF probe" --output comb.csv

# Custom tone list from CSV
python freq_comb_sweep.py --freqs-csv hf_bands.csv --output rsp.csv
```

`hf_bands.csv` is one frequency in MHz per line:

```
3.560
7.040
14.070
21.070
28.070
```

## Output

CSV: `freq_hz, s21_db, s21_phase_deg` per tone.

## Flags

- `--vna`, `--port`, `--host`
- `--freqs-csv FILE` or `--comb START STEP N` (one required)
- `--span MHZ` — small per-tone sweep span (default 1 kHz)
- `--average N` (default 4)
- `--label`, `--output`
