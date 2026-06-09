# swbc-scanner

KiwiSDR shortwave broadcast band scanner.

Scans international shortwave broadcast (SWBC) bands looking for active AM
carriers.  Logs detected stations to SQLite with band, frequency, and SNR.
Annotates detections with known station names where possible (WWV, CHU, etc.).

Covers 14 SWBC bands from 2.3 MHz (120m) to 26.1 MHz (11m).

---

## Hardware required

- KiwiSDR connected to an HF antenna
- KiwiSDR reachable on the local network

An antenna with reasonable coverage from 2–30 MHz (long wire, EFHW, or
magnetic loop) will give better results than a resonant single-band antenna.

---

## Setup

```bash
pip install rf-bench-drivers-kiwisdr numpy
```

---

## Usage

```bash
# Default: all 14 SWBC bands, continuous loop, 5-minute interval
python swbc_scanner.py

# Single sweep and exit
python swbc_scanner.py --once

# Specific bands
python swbc_scanner.py --bands 49m,41m,31m,25m,19m

# Specify host
python swbc_scanner.py --host 10.1.0.5

# Tighter squelch (fewer false triggers)
python swbc_scanner.py --squelch 12

# Finer step for thorough sweep (slower)
python swbc_scanner.py --step 5000 --dwell 4000

# Sweep every 10 minutes
python swbc_scanner.py --interval 600
```

---

## SWBC band reference

| Band | Range | Notes |
|------|-------|-------|
| 120m | 2.300–2.495 MHz | Tropical/regional; strong at night |
| 90m  | 3.200–3.400 MHz | Tropical; night paths |
| 75m  | 3.900–4.000 MHz | Shared with amateur; SWBC on international side |
| 60m  | 4.750–5.060 MHz | Regional; night |
| 49m  | 5.900–6.200 MHz | Night workhorse; many stations |
| 41m  | 7.200–7.450 MHz | Evening; medium paths |
| 31m  | 9.400–9.900 MHz | Day/evening; very active |
| 25m  | 11.600–12.100 MHz | Day/evening; many international stations |
| 22m  | 13.570–13.870 MHz | Day; moderate activity |
| 19m  | 15.100–15.800 MHz | Day; best at solar maximum |
| 16m  | 17.480–17.900 MHz | Day; good at high SFI |
| 15m  | 18.900–19.020 MHz | Narrow band; Russian/Chinese utilities |
| 13m  | 21.450–21.850 MHz | Day; solar maximum favoured |
| 11m  | 25.600–26.100 MHz | Day; high SFI required |

---

## Known stations annotated by the scanner

The scanner matches detections to a built-in table of well-known stations:
WWV/WWVH (2.5/5/10/15/20/25 MHz), CHU Canada (3.330/7.850/14.670 MHz),
Radio New Zealand International, Radio Habana Cuba, China Radio International,
Voice of America, Radio Exterior de Espana, and UVB-76.

The table is approximate — SWBC broadcast schedules change seasonally.
Unmatched frequencies show the raw frequency only.

---

## CLI options

| Option | Default | Description |
|--------|---------|-------------|
| `--host HOST` | `kiwisdr.local` | KiwiSDR hostname or IP |
| `--port PORT` | `8073` | WebSocket port |
| `--password PW` | (empty) | KiwiSDR password |
| `--bands B,B,...` | all 14 | Comma-separated band names |
| `--step HZ` | `9000` | Frequency step (AM channel spacing) |
| `--dwell N` | `3000` | IQ samples per step (~250 ms) |
| `--squelch DB` | `10` | dB above noise floor to detect |
| `--once` | off | Single sweep and exit |
| `--interval SEC` | `300` | Seconds between sweeps (loop mode) |
| `--log FILE` | `swbc.db` | SQLite output path |
| `--no-color` | off | Disable ANSI colours |

---

## SQLite schema

```sql
CREATE TABLE detections (
    id          INTEGER PRIMARY KEY,
    ts_utc      TEXT,       -- ISO 8601 UTC
    ts_unix     REAL,       -- Unix epoch
    freq_hz     INTEGER,    -- detected frequency (centre of scan step)
    freq_mhz    REAL,       -- same in MHz
    band        TEXT,       -- SWBC band name, e.g. "31m"
    power_dbfs  REAL,       -- peak FFT power (dBFS)
    snr_db      REAL        -- peak minus median noise floor
)
```

Query examples:

```bash
# All detections this session
sqlite3 swbc.db \
  "SELECT ts_utc, band, freq_mhz, snr_db FROM detections ORDER BY ts_unix;"

# Most active SWBC frequencies
sqlite3 swbc.db \
  "SELECT freq_mhz, band, COUNT(*) AS hits
   FROM detections GROUP BY freq_hz
   ORDER BY hits DESC LIMIT 15;"

# Active stations by band right now (last sweep)
sqlite3 swbc.db \
  "SELECT band, freq_mhz, snr_db
   FROM detections
   WHERE ts_unix > strftime('%s','now') - 600
   ORDER BY band, freq_mhz;"

# Strongest signals ever
sqlite3 swbc.db \
  "SELECT ts_utc, band, freq_mhz, snr_db FROM detections
   ORDER BY snr_db DESC LIMIT 20;"
```

---

## What to expect

**31m (9.4–9.9 MHz):** usually the most active band.  Chinese Radio International,
Voice of America relays, Radio Romania International, BBC, Deutsche Welle.
Active during both day and evening in North America.

**49m (5.9–6.2 MHz):** strong evening/night band.  Many Latin American and
Asian broadcasters active after local sunset.

**120m/90m (2.3–3.4 MHz):** tropical broadcasting services; active at night,
especially for Latin American and African regional broadcasters.  Significant
amateur QRM in parts of the 75m band.

**High bands (19m–11m):** activity depends heavily on the solar cycle (SFI).
During solar maximum (current cycle 25 approaching peak ~2025): significant
activity from BBC, Voice of America, Radio China, etc.  During solar minimum:
these bands may be mostly empty.

---

## Sweep timing

At default settings (9 kHz step, 3000 samples = 250 ms dwell, 40 ms settle):

| Band | Width | Steps | Sweep time |
|------|-------|-------|-----------|
| 49m  | 300 kHz | ~33  | ~10 s |
| 31m  | 500 kHz | ~55  | ~16 s |
| 25m  | 500 kHz | ~55  | ~16 s |
| All 14 bands | ~11 MHz | ~1200 | ~5–6 min |

Use `--step 10000` to reduce sweep time; `--step 5000` for a more thorough scan.

---

## Frequency accuracy

The KiwiSDR has a GPS-disciplined oscillator (TCXO) — frequency readings are
accurate to within a few Hz, making it easy to identify specific stations by
their exact carrier frequency.

SWBC stations use 5 kHz channel spacing per ITU; most transmitters are within
±1 Hz of their assigned frequency.  The `freq_hz` in the database is the centre
of the scan step, which may be up to 4.5 kHz away from the actual carrier at
default 9 kHz step size.  Use `--step 5000` for better frequency accuracy.
