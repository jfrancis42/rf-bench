# propagation-logger

Periodic HF noise floor and signal strength logger using the KiwiSDR.

Monitors a configurable list of frequencies — WWV time signals, NCDXF beacons,
and quiet noise-reference frequencies — at regular intervals.  At each interval
it captures IQ at every monitored frequency and logs power, noise floor, and
carrier SNR to SQLite.

Useful for tracking long-term HF propagation conditions, solar flux effects,
day/night path changes, and local noise floor variations.

---

## Hardware required

- KiwiSDR connected to an HF antenna
- KiwiSDR reachable on the local network

---

## Setup

```bash
pip install rf-bench-drivers-kiwisdr numpy
```

---

## Usage

```bash
# Defaults: WWV 5/10/15 MHz + NCDXF 14.1 MHz + CHU 3.33 MHz, every 60s
python propagation_logger.py

# Specify host
python propagation_logger.py --host 10.1.0.5

# Custom frequencies
python propagation_logger.py --freqs 5000000,10000000,15000000,20000000

# Custom frequencies with labels
python propagation_logger.py \
  --freqs 5000000,10000000,15000000 \
  --freq-names "WWV 5,WWV 10,WWV 15"

# More frequent measurements, longer capture
python propagation_logger.py --interval 30 --samples 12000

# Write CSV in addition to SQLite
python propagation_logger.py --csv
```

---

## Default monitored frequencies

| Label | Frequency | What it tells you |
|-------|-----------|-------------------|
| WWV 5 MHz | 5.000 MHz | Day/night indicator; strong at night in western US |
| WWV 10 MHz | 10.000 MHz | Transition frequency; useful all day |
| WWV 15 MHz | 15.000 MHz | Good daytime; fades at night |
| NCDXF 20m | 14.100 MHz | NCDXF/IBP beacon network; 18 transmitters worldwide |
| CHU 3.330 | 3.330 MHz | NRC Canada time signal; excellent night path |

WWV is located in Fort Collins, Colorado (NIST).  It transmits AM carriers on
2.5, 5, 10, 15, and 20 MHz with voice announcements each minute.

NCDXF/IBP beacons transmit on 14.100, 18.110, 21.150, 24.930, and 28.200 MHz
in a 3-minute cycle.  A strong 20m reading with nothing on 10m/12m/15m indicates
moderate propagation; strong readings across all bands indicates excellent conditions.

---

## CLI options

| Option | Default | Description |
|--------|---------|-------------|
| `--host HOST` | `kiwisdr.local` | KiwiSDR hostname or IP |
| `--port PORT` | `8073` | WebSocket port |
| `--password PW` | (empty) | KiwiSDR password |
| `--freqs F,F,...` | (WWV + NCDXF + CHU) | Comma-separated Hz |
| `--freq-names N,N,...` | auto | Labels matching --freqs |
| `--interval SEC` | `60` | Measurement interval in seconds |
| `--samples N` | `6000` | IQ samples per measurement (0.5s) |
| `--log FILE` | `propagation.db` | SQLite output path |
| `--csv` | off | Also write a .csv file |
| `--no-color` | off | Disable ANSI colours |

---

## SQLite schema

```sql
CREATE TABLE readings (
    id          INTEGER PRIMARY KEY,
    ts_utc      TEXT,       -- ISO 8601 UTC
    ts_unix     REAL,       -- Unix epoch
    freq_hz     INTEGER,    -- frequency in Hz
    label       TEXT,       -- e.g. "WWV 10 MHz"
    power_dbfs  REAL,       -- 10*log10(mean(|iq|^2))
    noise_dbfs  REAL,       -- median FFT bin (noise floor estimate)
    snr_db      REAL        -- peak FFT bin - noise_dbfs
)
```

Query examples:

```bash
# WWV 10 MHz readings over the last 24 hours
sqlite3 propagation.db \
  "SELECT ts_utc, power_dbfs, snr_db FROM readings
   WHERE label='WWV 10 MHz'
     AND ts_unix > strftime('%s','now') - 86400
   ORDER BY ts_unix;"

# Noise floor trend by hour of day (all frequencies)
sqlite3 propagation.db \
  "SELECT label,
          strftime('%H', ts_utc) AS hour_utc,
          AVG(noise_dbfs) AS avg_noise,
          AVG(snr_db) AS avg_snr
   FROM readings
   GROUP BY label, hour_utc
   ORDER BY label, hour_utc;"

# Best propagation times (highest SNR across all bands)
sqlite3 propagation.db \
  "SELECT ts_utc, SUM(snr_db) AS total_snr
   FROM readings
   GROUP BY ts_utc
   ORDER BY total_snr DESC LIMIT 20;"
```

---

## CSV output

With `--csv`, a `propagation.csv` is written alongside the database.  Columns:

```
ts_utc, ts_unix, freq_hz, label, power_dbfs, noise_dbfs, snr_db
```

The CSV is appended (not overwritten) across runs.  Import into gnuplot, Python,
or a spreadsheet for time-series plots.

---

## What to expect

**WWV SNR by time of day (Colorado antenna, approximate):**

| Frequency | Day | Night |
|-----------|-----|-------|
| 5 MHz     | −5 to 5 dB | 10–25 dB |
| 10 MHz    | 10–20 dB | 5–15 dB |
| 15 MHz    | 15–25 dB | 0–5 dB |

Geomagnetic storms (K-index ≥ 5) will cause sudden drops across all frequencies.
Solar flares cause sudden ionospheric disturbances (SIDs) visible as brief SNR
dips on high bands (10–15 MHz) during daytime.

**Long-term patterns to look for:**
- Summer: higher 10m/15m SNR (sporadic-E)
- Solar maximum: higher SNR on all bands vs solar minimum
- Winter: stronger 80m/40m paths due to lower QRN

---

## Notes

The `power_dbfs` column is `10*log10(mean(|iq|^2))` — the total in-band power.
The `noise_dbfs` column is the median of the FFT bins — dominated by the noise
floor rather than any carrier.  `snr_db` is the peak FFT bin above that median.

For a strong carrier like WWV: `snr_db` will be 10–30 dB.
For a quiet noise-reference frequency: `snr_db` will be 0–3 dB (just noise peaks).

Adding a quiet frequency (e.g. 16.000 MHz during daytime) gives a noise floor
reference that tracks local interference and ionospheric absorption independently
of any signal activity on that frequency.
