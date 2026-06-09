# hf-monitor

KiwiSDR HF band activity scanner — the HF analogue of bubba-detector's log mode.

Sweeps configurable amateur HF bands (160m–10m), detects signals above a
configurable squelch threshold, logs all detections to SQLite, and shows a
rolling terminal display of recent activity and top active frequencies.

---

## Hardware required

- KiwiSDR connected to HF antenna (covers 0–30 MHz)
- KiwiSDR reachable on the local network

---

## Setup

```bash
pip install rf-bench-drivers-kiwisdr numpy
```

---

## Usage

```bash
# Default: 40m/20m/15m/10m, squelch +12 dB, host kiwisdr.local
python hf_monitor.py

# All 9 amateur bands
python hf_monitor.py --all-amateur

# Specific bands
python hf_monitor.py --bands 40m,20m,17m,15m,12m,10m

# Specify host and tighter squelch
python hf_monitor.py --host 10.1.0.5 --squelch 15

# Finer step and longer dwell for weaker signal detection
python hf_monitor.py --step 5000 --dwell 4096

# Custom log file
python hf_monitor.py --log /tmp/hf.db
```

---

## Band reference

| Band | Range | Notes |
|------|-------|-------|
| 160m | 1.800–2.000 MHz | Topband; local nighttime paths |
| 80m  | 3.500–4.000 MHz | CW/SSB; nighttime DX |
| 60m  | 5.3305–5.4035 MHz | US channelized; USB |
| 40m  | 7.000–7.300 MHz | All-day workhorse; CW + FT8 + SSB |
| 30m  | 10.100–10.150 MHz | CW + WSPR; no SSB allowed |
| 20m  | 14.000–14.350 MHz | Primary DX band |
| 17m  | 18.068–18.168 MHz | Small band; good propagation indicator |
| 15m  | 21.000–21.450 MHz | Solar-dependent; good during high SFI |
| 12m  | 24.890–24.990 MHz | Like 10m but slightly more reliable |
| 10m  | 28.000–29.700 MHz | Wide band; dead at solar minimum |

---

## CLI options

| Option | Default | Description |
|--------|---------|-------------|
| `--host HOST` | `kiwisdr.local` | KiwiSDR hostname or IP |
| `--port PORT` | `8073` | WebSocket port |
| `--password PW` | (empty) | KiwiSDR password |
| `--bands B,B,...` | `40m,20m,15m,10m` | Comma-separated band names |
| `--all-amateur` | off | Sweep all 9 amateur bands |
| `--step HZ` | `10000` | Frequency step (Hz) |
| `--dwell N` | `2048` | IQ samples per step (~171 ms) |
| `--squelch DB` | `12` | dB above noise floor to detect |
| `--gain DB` | `0` | AGC threshold (0 = auto AGC) |
| `--log FILE` | `hf_monitor.db` | SQLite output path |
| `--tail N` | `20` | Recent detections in display |
| `--no-color` | off | Disable ANSI colours |

---

## SQLite schema

```sql
CREATE TABLE detections (
    id          INTEGER PRIMARY KEY,
    ts_utc      TEXT,       -- ISO 8601 UTC
    ts_unix     REAL,       -- Unix epoch
    freq_hz     INTEGER,    -- centre frequency of detected signal
    freq_mhz    REAL,       -- same in MHz
    band        TEXT,       -- e.g. "40m"
    power_dbfs  REAL,       -- peak power in dBFS
    noise_dbfs  REAL,       -- median noise floor in dBFS
    snr_db      REAL        -- peak minus noise floor
)
```

Query examples:

```bash
# All activity in the last hour
sqlite3 hf_monitor.db \
  "SELECT ts_utc, band, freq_mhz, snr_db FROM detections
   WHERE ts_unix > strftime('%s','now') - 3600
   ORDER BY ts_unix;"

# Top 10 most active frequencies
sqlite3 hf_monitor.db \
  "SELECT freq_mhz, band, COUNT(*) AS hits
   FROM detections GROUP BY freq_hz
   ORDER BY hits DESC LIMIT 10;"

# 20m activity only
sqlite3 hf_monitor.db \
  "SELECT ts_utc, freq_mhz, snr_db FROM detections
   WHERE band='20m' ORDER BY ts_unix;"
```

---

## What you will see

- **40m:** FT8 traffic at 7.074 MHz is almost always present during the day.
  CW signals in the low end (7.000–7.125 MHz), SSB higher.
- **20m:** FT8 at 14.074 MHz. SSB DX in the 14.200–14.350 MHz range.
- **10m/12m:** Quiet at solar minimum; bursting with activity at solar maximum.
  Sporadic-E openings (summer afternoons) show sudden strong signals.
- **Noise floor changes:** A rising noise floor across all bands usually means
  nearby interference or a geomagnetic storm.

---

## Sweep timing

At default settings (10 kHz step, 2048 samples = 171 ms dwell, 40 ms settle):

| Band | Steps | Sweep time |
|------|-------|-----------|
| 40m  | 30    | ~6 s      |
| 20m  | 35    | ~7 s      |
| 15m  | 45    | ~9 s      |
| 10m  | 170   | ~36 s     |
| All 9 amateur | ~850 | ~3.0 min |

Use `--step 20000` to halve sweep time at the cost of missing narrow signals.
