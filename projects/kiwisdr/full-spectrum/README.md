# full-spectrum — Simultaneous HF + VHF/UHF Scanner

Combines a KiwiSDR (0–30 MHz HF) and an RTL-SDR (24 MHz–1766 MHz VHF/UHF) into a
single scanner, logging all detections to a unified SQLite database.  Each receiver
runs in its own daemon thread.  A shared queue feeds the main display loop.

## Architecture

```
HFScanner thread (KiwiSDR)  ──┐
                               ├──▶ queue.Queue ──▶ main loop ──▶ SQLite + display
VHFScanner thread (RTL-SDR) ──┘
```

- `HFScanner`: sweeps configured amateur HF bands using KiwiSDR `capture_iq()`,
  one 10 kHz step at a time with a Hanning-windowed FFT for noise+peak detection.
- `VHFScanner`: tunes the RTL-SDR to cover the configured VHF range in 2.4 MHz
  chunks, captures 131072 samples, finds peaks above the local noise floor.
- Both threads push `Detection(ts_unix, freq_hz, snr_db, power_dbfs, source, band)`
  namedtuples to a shared queue; the main thread drains the queue and updates the
  display at 2 Hz.

## Requirements

- `rf-bench-drivers-kiwisdr` (`pip install rf-bench-drivers-kiwisdr`)
- `rf-bench-drivers-rtlsdr`  (`pip install rf-bench-drivers-rtlsdr`)
- `numpy`
- KiwiSDR and/or RTL-SDR connected and reachable
- Either device can be absent; use `--no-hf` or `--no-vhf` accordingly

## Usage

```bash
# Default: 40m/20m/15m/10m HF + 144–148 MHz VHF
python full_spectrum.py

# HF only (no RTL-SDR)
python full_spectrum.py --no-vhf

# VHF only (no KiwiSDR)
python full_spectrum.py --no-hf

# Custom VHF range (GMRS/FRS + 70cm)
python full_spectrum.py --vhf-start 462000000 --vhf-stop 468000000

# Custom HF bands, different squelch levels
python full_spectrum.py --hf-bands 40m,20m --hf-squelch 10 --vhf-squelch 8

# Specific RTL-SDR by serial number, with PPM correction
python full_spectrum.py --rtl-serial 00000001 --rtl-ppm -5
```

## CLI reference

| Option | Default | Description |
|--------|---------|-------------|
| `--kiwi-host` | `kiwisdr.local` | KiwiSDR hostname or IP |
| `--kiwi-port` | `8073` | KiwiSDR port |
| `--kiwi-password` | _(empty)_ | KiwiSDR password |
| `--rtl-serial` | _(auto)_ | RTL-SDR serial number |
| `--rtl-ppm` | `0` | RTL-SDR frequency correction (PPM) |
| `--hf-bands` | `40m,20m,15m,10m` | HF bands to sweep |
| `--vhf-start` | `144000000` | VHF/UHF scan start (Hz) |
| `--vhf-stop` | `148000000` | VHF/UHF scan stop (Hz) |
| `--hf-squelch` | `12` | HF squelch: dB above noise floor |
| `--vhf-squelch` | `10` | VHF squelch: dB above noise floor |
| `--no-hf` | off | Disable KiwiSDR HF scanner |
| `--no-vhf` | off | Disable RTL-SDR VHF/UHF scanner |
| `--log` | `full_spectrum.db` | SQLite output path |
| `--tail` | `30` | Rolling display lines |
| `--no-color` | off | Disable ANSI colours |

## SQLite schema

```sql
CREATE TABLE detections (
    id INTEGER PRIMARY KEY,
    ts_utc TEXT, ts_unix REAL,
    freq_hz INTEGER, freq_mhz REAL,
    band TEXT, source TEXT,
    snr_db REAL, power_dbfs REAL
);
```

The `source` column is `"HF"` or `"VHF"` so you can filter easily:
```sql
SELECT * FROM detections WHERE source = 'HF' ORDER BY ts_unix DESC LIMIT 20;
SELECT COUNT(*) FROM detections WHERE source = 'VHF' AND freq_hz > 144e6;
```

## Example output

```
  Full-Spectrum Scanner  —  2026-06-03 14:33:02  |  detections: 47
  ────────────────────────────────────────────────────────────────────────────
  HF     cycle #12      detections: 34
  VHF    cycle #89      detections: 13
  ────────────────────────────────────────────────────────────────────────────
  [14:32:55] HF  40m               7.235  MHz  SNR +18.2 dB  pwr -42.1 dBFS  ██████████
  [14:32:58] VHF 144–148 MHz     144.200  MHz  SNR +22.4 dB  pwr -38.7 dBFS  ████████████
  [14:33:01] HF  20m              14.225  MHz  SNR +15.6 dB  pwr -44.8 dBFS  ████████░░
```

## VHF scan implementation note

The RTL-SDR usable bandwidth is approximately 80% of the 2.4 MHz sample rate
(~1.92 MHz) due to roll-off at the edges.  If the requested VHF range is wider
than 1.92 MHz, VHFScanner automatically steps through multiple center frequencies.
Each step captures 131072 samples (~55 ms) for ~18 Hz/bin resolution.
