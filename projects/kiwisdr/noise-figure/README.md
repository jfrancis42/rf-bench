# noise-figure — KiwiSDR Y-Factor Noise Figure Measurement

Measures the noise figure (NF) of an HF amplifier, LNA, preamplifier, or receive
chain using the Y-factor method.  The KiwiSDR acts as the calibrated receiver.
The noise source provides two known noise temperatures (OFF = cold, ON = hot).

## Theory

The Y-factor method:

```
Y_dB  = P_hot_dBFS - P_cold_dBFS        (power difference, hot vs cold)
NF_dB = ENR_dB - 10 × log10(10^(Y_dB/10) - 1)
```

Where ENR (Excess Noise Ratio) characterizes the noise source:

```
ENR_dB = 10 × log10((T_hot - T_cold) / T_0)
```

`T_0 = 290 K` (IEEE standard reference temperature).
A typical HP/Agilent 346B noise source has ENR ≈ 15 dB (T_hot ≈ 9,477 K).

**Result is invalid (Y ≤ 1) when:**
- The noise source ENR is too low for the DUT's noise figure (NF >> ENR)
- External RFI during the cold measurement masks the true noise floor
- The noise source is not actually switching (wiring error)

## Setup

```
Noise source → [DUT under test] → KiwiSDR antenna input
```

1. Connect the noise source output to the DUT input
2. Connect the DUT output to the KiwiSDR antenna port
3. For each frequency: capture with noise source OFF, then ON

In `--auto` mode, assume the noise source switches automatically (e.g. via a relay
controlled by a separate script) and skip the interactive prompts.

## Requirements

- `rf-bench-drivers-kiwisdr` (`pip install rf-bench-drivers-kiwisdr`)
- `numpy`
- Calibrated noise source (HP 346A/B, Noisecom, or similar)
- ENR value from the noise source calibration certificate

## Usage

```bash
# Interactive mode (default): prompts before each measurement
python noise_figure.py

# Specific frequencies, custom ENR
python noise_figure.py --freqs 7000000,14000000,21000000 --enr 14.8

# ENR from calibration file (recommended for accuracy)
python noise_figure.py --enr-file noise_source_cal.csv

# Longer capture for noisy environments
python noise_figure.py --samples 240000   # 20 seconds

# Automated noise source, write CSV
python noise_figure.py --auto --csv

# Quick spot-check at 14 MHz
python noise_figure.py --freqs 14000000 --enr 15.0 --samples 60000
```

## ENR calibration file format

Two-column CSV (no header required, lines starting with `#` are comments):

```csv
# Noise source serial: 12345, cal date: 2024-01-15
3500000,14.82
7000000,15.05
14000000,15.31
21000000,15.18
28000000,14.95
```

Values between table entries are linearly interpolated.  Frequencies outside the
table range use the nearest endpoint.

## CLI reference

| Option | Default | Description |
|--------|---------|-------------|
| `--host` | `kiwisdr.local` | KiwiSDR hostname or IP |
| `--port` | `8073` | KiwiSDR port |
| `--password` | _(empty)_ | KiwiSDR password |
| `--freqs` | 3.5/7/14/21/28 MHz | Test frequencies in Hz, comma-separated |
| `--enr` | `15.0` | Flat ENR of noise source in dB |
| `--enr-file` | _(none)_ | CSV with freq_hz,enr_db columns (overrides --enr) |
| `--samples` | `120000` | IQ samples per measurement (10 s at 12 kHz) |
| `--auto` | off | Skip interactive prompts |
| `--log` | `noise_figure.db` | SQLite output path |
| `--csv` | off | Also write CSV (auto-named) |
| `--no-color` | off | Disable ANSI colours |

## SQLite schema

```sql
CREATE TABLE measurements (
    id INTEGER PRIMARY KEY,
    ts_utc TEXT, ts_unix REAL,
    freq_hz INTEGER, freq_mhz REAL,
    enr_db REAL,
    p_cold_dbfs REAL, p_hot_dbfs REAL,
    y_factor_db REAL, nf_db REAL   -- nf_db is NULL when Y ≤ 1
);
```

## Example output

```
  Noise Figure Measurement — Y-factor method
  Host: kiwisdr.local:8073  |  samples: 120000 (10.0s)  |  flat ENR: 15.0 dB
  Test frequencies: 3.500 MHz, 7.000 MHz, 14.000 MHz, 21.000 MHz, 28.000 MHz

  [1/5] 3.500 MHz  ENR = 15.0 dB
  → Noise source OFF (cold).  Press Enter to capture:
    Capturing 120000 samples (10.0s) — cold...
    Power (cold): -68.124 dBFS
  → Noise source ON  (hot).  Press Enter to capture:
    Capturing 120000 samples (10.0s) — hot...
    Power (hot): -53.218 dBFS
  Result: Y = +14.91 dB  →  NF = +2.32 dB

  ...

  Noise Figure Results
  ──────────────────────────────────────────────────────────────────────────
  Frequency           ENR    P_cold    P_hot      Y       NF
  ──────────────────────────────────────────────────────────────────────────
     3.500 MHz    +15.0 dB  -68.12 dB  -53.22 dB  +14.91 dB    +2.32 dB
     7.000 MHz    +15.0 dB  -69.44 dB  -54.11 dB  +15.33 dB    +1.85 dB
    14.000 MHz    +15.0 dB  -70.12 dB  -55.28 dB  +14.84 dB    +2.39 dB
    21.000 MHz    +15.0 dB  -69.87 dB  -54.99 dB  +14.88 dB    +2.35 dB
    28.000 MHz    +15.0 dB  -68.55 dB  -53.72 dB  +14.83 dB    +2.40 dB
  ──────────────────────────────────────────────────────────────────────────

  Mean NF (5 valid points): +2.26 dB
```

## Accuracy considerations

- Longer `--samples` reduces measurement noise; 10 seconds (120000 samples) is a
  good starting point; 30–60 seconds improves accuracy in noisy HF bands
- The KiwiSDR's own noise figure is included in the measurement.  To measure the
  DUT alone, a two-measurement technique (with and without the DUT) is needed.
  This script measures the cascade (DUT + KiwiSDR).
- ENR accuracy directly limits NF accuracy; use the noise source calibration
  certificate for --enr-file if available
- HF bands above 10 MHz have lower man-made noise than lower bands; measurements
  on 80m/40m in urban environments may show higher apparent "NF" due to external
  noise entering through the antenna port
