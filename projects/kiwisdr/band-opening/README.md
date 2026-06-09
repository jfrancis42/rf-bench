# band-opening — KiwiSDR HF Band Opening Monitor

Monitors the five NCDXF/IARU international beacon network frequencies to detect
HF band openings using a KiwiSDR receiver.  Measures S/N at each beacon frequency
on a configurable interval, computes a rolling percentile baseline, and declares an
opening when S/N exceeds baseline + threshold.

## What it monitors

Default frequencies are the NCDXF/IARU International Beacon Project network:

| Band | Frequency |
|------|-----------|
| 20m  | 14.100 MHz |
| 17m  | 18.110 MHz |
| 15m  | 21.150 MHz |
| 12m  | 24.930 MHz |
| 10m  | 28.200 MHz |

These beacons transmit on a 3-minute rotation cycle.  Signal above the rolling
baseline indicates a band path is open to one or more of the 18 beacon stations
around the world.

## Detection logic

- Per-frequency rolling window of S/N readings (default: last 20 measurements)
- Baseline = percentile-20 of the rolling window (ignores signal peaks, tracks
  the noise floor)
- Opening = current S/N > baseline + threshold (default: +10 dB)
- A minimum of 3 readings must be in the window before openings are declared

## Alert file

When `--alert-file path` is given, an atomic JSON file is written whenever an
opening is detected in any measurement cycle:

```json
{
  "ts_unix": 1748000000.123,
  "openings": [
    {"freq_hz": 28200000, "snr_db": 25.3, "label": "28.200 MHz (10m)"}
  ]
}
```

Other tools (e.g. bubba-detector) can poll this file at low cost.  The file is
written atomically via rename so readers never see a partial write.

## Requirements

- `rf-bench-drivers-kiwisdr` (`pip install rf-bench-drivers-kiwisdr`)
- `numpy`
- KiwiSDR reachable on the network

## Usage

```bash
# Default: NCDXF beacons, 120-second interval, 10 dB threshold
python band_opening.py

# Custom host and tighter threshold
python band_opening.py --host 10.1.0.5 --threshold 12 --interval 60

# Write alert file for integration with other tools
python band_opening.py --alert-file /tmp/band_opening.json

# Monitor custom frequencies (e.g. 10m calling + beacon)
python band_opening.py --freqs 28200000,28300000,28400000 --interval 30

# Long run: 30-reading baseline window, write to named database
python band_opening.py --window 30 --log /var/log/band_opening.db
```

## CLI reference

| Option | Default | Description |
|--------|---------|-------------|
| `--host` | `kiwisdr.local` | KiwiSDR hostname or IP |
| `--port` | `8073` | KiwiSDR port |
| `--password` | _(empty)_ | KiwiSDR password |
| `--freqs` | NCDXF 5-band | Override: comma-separated Hz values |
| `--interval` | `120` | Measurement interval in seconds |
| `--samples` | `12000` | IQ samples per reading (≈1 s) |
| `--threshold` | `10` | dB above baseline to declare opening |
| `--window` | `20` | Rolling window size for baseline |
| `--alert-file` | _(none)_ | Path to write JSON alert on opening |
| `--log` | `band_opening.db` | SQLite output path |
| `--no-color` | off | Disable ANSI colours |

## SQLite schema

```sql
-- All S/N readings
CREATE TABLE readings (
    id INTEGER PRIMARY KEY,
    ts_utc TEXT, ts_unix REAL,
    freq_hz INTEGER, label TEXT,
    snr_db REAL, power_dbfs REAL, baseline_db REAL
);

-- Detected openings only
CREATE TABLE openings (
    id INTEGER PRIMARY KEY,
    ts_utc TEXT, ts_unix REAL,
    freq_hz INTEGER, label TEXT,
    snr_db REAL, peak_snr_db REAL
);
```

## Example output

```
  Band Opening Monitor  —  2026-06-03 14:22:11  |  cycle #4  |  interval: 120s
  Threshold: +10 dB above baseline  |  openings: 1
  ────────────────────────────────────────────────────────────────────────────
  Frequency                    S/N    Baseline   Above  Bar             Status
  ────────────────────────────────────────────────────────────────────────────
  14.100 MHz (20m)            +8.2 dB    +7.1 dB   +1.1 dB  ████████░░░░   quiet
  18.110 MHz (17m)            +9.5 dB    +7.3 dB   +2.2 dB  █████████░░░   quiet
  21.150 MHz (15m)           +11.8 dB    +7.4 dB   +4.4 dB  ██████████░░   elevated
  24.930 MHz (12m)            +6.1 dB    +6.8 dB   -0.7 dB  ██████░░░░░░   quiet
  28.200 MHz (10m)           +24.7 dB    +7.2 dB  +17.5 dB  ████████████   OPENING

  Recent openings:
    14:20:11  28.200 MHz (10m)  S/N +24.7 dB  (+17.5 dB above baseline)
```

## Hardware notes

- KiwiSDR sample rate is fixed at 12,000 S/s; `--samples 12000` = 1-second capture
- All five default beacon frequencies are within the KiwiSDR 0–30 MHz range
- The script warns and skips any frequency above 30 MHz
- Beacon transmissions are 100W into omnidirectional antennas; propagation paths
  vary.  A strong 10m reading reliably indicates an open path to at least one of
  the 18 beacon sites.
