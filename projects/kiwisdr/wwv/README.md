# rf-bench-kiwisdr-wwv

Monitor WWV and WWVH HF time signal stations on all active frequencies simultaneously,
measuring signal-to-noise ratio to track which amateur bands are currently open.

## What it does

Opens one KiwiSDR channel per frequency and measures S/N every `--interval` seconds.
Displays a live colour-coded table: frequency, current S/N, trend (rising/falling/stable),
and a usability rating (good/marginal/poor/absent).  Logs all readings to SQLite for
historical propagation analysis.

WWV transmits from Fort Collins, CO on 2.5, 5, 10, 15, 20, and 25 MHz.
WWVH transmits from Kauai, HI on 2.5, 5, 10, and 15 MHz.
Both use the same carrier frequencies; this tool measures total signal power at each
frequency and cannot distinguish the two stations.

Optionally adds NCDXF/IARU beacon frequencies (14.100–28.200 MHz) for wider band
coverage.

## Hardware

| Component | Notes |
|-----------|-------|
| KiwiSDR   | 0–30 MHz HF receiver, networked, default port 8073 |
| HF antenna | Any wideband HF antenna (longwire, EFHW, loop) |

## Usage

```
python wwv_monitor.py [options]
```

| Flag | Default | Description |
|------|---------|-------------|
| `--host HOST` | kiwisdr.local | KiwiSDR hostname or IP |
| `--port N` | 8073 | KiwiSDR WebSocket port |
| `--password P` | (empty) | KiwiSDR password |
| `--max-channels N` | 4 | Simultaneous KiwiSDR connections |
| `--interval N` | 60 | Seconds between sweeps |
| `--samples N` | 12000 | IQ samples per measurement (12000 = 1 s) |
| `--log FILE` | wwv.db | SQLite log path |
| `--freqs Hz,...` | (all WWV) | Override frequency list (Hz, comma-separated) |
| `--beacons` | — | Add NCDXF/IARU beacon frequencies |

### Examples

```bash
# Basic: monitor all WWV/WWVH frequencies, 1-minute intervals
python wwv_monitor.py --host 192.168.1.100

# Fast sweep every 30s, up to 4 simultaneous connections
python wwv_monitor.py --host 192.168.1.100 --interval 30 --max-channels 4

# Include beacons for wider band coverage
python wwv_monitor.py --host 192.168.1.100 --beacons --log propagation.db

# Custom frequencies (e.g. just 10 and 15 MHz)
python wwv_monitor.py --host 192.168.1.100 --freqs 10000000,15000000
```

## What you'll see

```
WWV / WWVH Propagation Monitor  (sweeps: 12  next in: 47s  Ctrl-C to stop)

Frequency               S/N (dB)  Power (dBFS)     Trend    Rating      Age
--------------------------------------------------------------------------------
WWV/WWVH 2.5 MHz          +4.2         -38.1      stable    poor          58s
WWV/WWVH 5 MHz            +22.8        -21.4      rising    good          58s
WWV/WWVH 10 MHz           +18.1        -28.3      stable    marginal      57s
WWV/WWVH 15 MHz            +8.7        -41.2     falling    marginal      57s
WWV 20 MHz                 +2.1        -54.8      stable    absent        56s
WWV 25 MHz                 -1.3        -62.0      stable    absent        56s
```

Green = S/N ≥ 20 dB (good).  Yellow = S/N ≥ 10 dB (marginal).  Red = below 10 dB.

## SQLite schema

```sql
readings(id, ts_utc, ts_unix, freq_hz, label, snr_db, power_dbfs)
```

Query example — last 24 hours of 20m coverage:
```sql
SELECT ts_utc, snr_db FROM readings
WHERE freq_hz = 14100000
  AND ts_unix > strftime('%s','now') - 86400
ORDER BY ts_unix;
```

## Dependencies

```
pip install rf-bench-drivers-kiwisdr numpy
```
