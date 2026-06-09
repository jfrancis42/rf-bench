# rf-bench-kiwisdr-cw-skimmer

Energy-based CW activity scanner for HF amateur band CW sub-bands via KiwiSDR.

## What it does

Steps through the CW portions of all nine amateur HF bands (160m through 10m),
capturing a short IQ block at each frequency with a narrow ±500 Hz passband.
Signals above a configurable S/N threshold are reported as spots and logged to
SQLite.  The terminal display shows recent spots with band, frequency, and S/N.

Detection is energy-only: the script reports active CW frequencies but does not
decode text, measure WPM, or identify callsigns.

## Hardware

| Component | Notes |
|-----------|-------|
| KiwiSDR   | 0–30 MHz HF receiver, networked, default port 8073 |
| HF antenna | Any wideband HF antenna (longwire, EFHW, loop) |

## Usage

```
python cw_skimmer.py [options]
```

| Flag | Default | Description |
|------|---------|-------------|
| `--host HOST` | kiwisdr.local | KiwiSDR hostname or IP |
| `--port N` | 8073 | KiwiSDR WebSocket port |
| `--password P` | (empty) | KiwiSDR password |
| `--bands LIST` | all | Comma-separated bands (160m,80m,40m,30m,20m,17m,15m,12m,10m) |
| `--step HZ` | 500 | Frequency step in Hz |
| `--dwell N` | 1024 | IQ samples per step (~85 ms) |
| `--squelch DB` | 15 | dB above noise floor to report a spot |
| `--log FILE` | cw_skimmer.db | SQLite log path |
| `--interval S` | 0 | Seconds between sweeps (0 = continuous) |

### Examples

```bash
# Scan all CW bands continuously
python cw_skimmer.py --host 192.168.1.100

# Only 40m and 20m, repeat every 5 minutes
python cw_skimmer.py --host 192.168.1.100 --bands 40m,20m --interval 300

# Sensitive detection (lower squelch, finer step)
python cw_skimmer.py --host 192.168.1.100 --step 250 --squelch 10

# Log to custom database
python cw_skimmer.py --host 192.168.1.100 --log /tmp/cw_spots.db
```

## What you'll see

```
CW Band Skimmer  (sweeps: 3  total spots: 47  Ctrl-C to stop)
Scanning: 20m  @ 14022.0 kHz

Time (UTC)    Band    Freq (kHz)   S/N (dB)  Power (dBFS)
------------------------------------------------------------
14:23:01      40m       7025.0       +28.4         -31.2
14:23:04      40m       7043.5       +19.7         -38.8
14:23:11      40m       7088.0       +14.2         -44.1
14:24:45      20m      14024.0       +31.1         -27.5
14:24:52      20m      14035.5       +22.8         -34.0
```

## SQLite schema

```sql
spots(id, ts_utc, ts_unix, freq_hz, freq_khz, band, power_dbfs, snr_db)
```

Query example — most active frequencies on 40m:
```sql
SELECT freq_khz, COUNT(*) as count, AVG(snr_db) as avg_snr
FROM spots WHERE band = '40m'
GROUP BY freq_hz ORDER BY count DESC LIMIT 20;
```

## Sweep time estimate

With `--step 500` (default), 40m has ~250 steps, 20m has ~140 steps.  At
1024 samples/step (~85 ms) plus ~50 ms settle, expect roughly:
- Single band (40m): ~35 seconds per sweep
- All bands: ~15–20 minutes per sweep

Use `--dwell 512` and a 2-minute `--interval` for a lighter background scan.

## Dependencies

```
pip install rf-bench-drivers-kiwisdr numpy
```
