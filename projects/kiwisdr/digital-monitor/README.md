# rf-bench-kiwisdr-digital-monitor

HF digital mode activity monitor and IQ recorder for FT8, FT4, JS8, and WSPR
via KiwiSDR.  Detects active signals and saves IQ to SigMF format files for
external decoding.

## What it does

Cycles through configured digital mode frequencies (FT8/FT4/JS8/WSPR on all
bands), performs a short activity check on each, and when activity is detected
(S/N above threshold), captures a full recording block to disk as a SigMF file
pair.  All activity (detected or not) is logged to SQLite.

The recorded `.sigmf-data` files can be decoded offline by WSJT-X, JTDX,
or JS8Call by pointing them at the IQ files with the correct sample rate
(12000 S/s) and centre frequency.

## Hardware

| Component | Notes |
|-----------|-------|
| KiwiSDR   | 0–30 MHz HF receiver, networked, default port 8073 |
| HF antenna | Any wideband HF antenna (longwire, EFHW, loop) |

## Usage

```
python digital_monitor.py [options]
```

| Flag | Default | Description |
|------|---------|-------------|
| `--host HOST` | kiwisdr.local | KiwiSDR hostname or IP |
| `--port N` | 8073 | KiwiSDR WebSocket port |
| `--password P` | (empty) | KiwiSDR password |
| `--freqs KEYS` | FT8_40m,FT8_20m,FT8_15m,FT8_10m | Mode keys to monitor |
| `--all` | — | Monitor all 16 defined frequencies |
| `--squelch DB` | 10 | dB above noise to trigger recording |
| `--record-s N` | 15 | Seconds to record (FT8 period = 15 s) |
| `--rec-dir DIR` | recordings/ | Directory for SigMF output files |
| `--log FILE` | digital_monitor.db | SQLite log path |
| `--dwell N` | 3000 | IQ samples for activity check (~250 ms) |

### Available mode keys

```
FT8_160m  FT8_80m  FT8_60m  FT8_40m  FT8_30m  FT8_20m  FT8_17m
FT8_15m   FT8_12m  FT8_10m  FT4_40m  FT4_20m  JS8_40m  JS8_20m
WSPR_40m  WSPR_20m
```

### Examples

```bash
# Monitor the four busiest FT8 bands (default)
python digital_monitor.py --host 192.168.1.100

# Monitor all FT8 bands + WSPR
python digital_monitor.py --host 192.168.1.100 --freqs FT8_40m,FT8_20m,FT8_15m,FT8_10m,WSPR_40m,WSPR_20m

# All frequencies, save to a specific directory
python digital_monitor.py --host 192.168.1.100 --all --rec-dir /data/kiwi-recordings/

# Lower squelch for weak signal search
python digital_monitor.py --host 192.168.1.100 --squelch 6 --record-s 15

# WSPR recording (WSPR period = 2 minutes)
python digital_monitor.py --host 192.168.1.100 --freqs WSPR_40m,WSPR_20m --record-s 120
```

## What you'll see

```
HF Digital Mode Activity Monitor  (cycles: 8  recordings: 12  Ctrl-C to stop)
Current: FT8_20m

Mode/Band       Freq (kHz)   S/N (dB)   Activity   Recs  Last recording
-------------------------------------------------------------------------------------
FT8_10m          28074.000     +6.2      142s ago      2  FT8_10m_28074000_20260603T...
FT8_15m          21074.000    +18.7       14s ago      4  FT8_15m_21074000_20260603T...
FT8_20m          14074.000    +24.1     ACTIVE         6  FT8_20m_14074000_20260603T...
FT8_40m           7074.000    +11.3       89s ago      0
```

When activity is detected:
```
  RECORDED FT8_20m @ 14074.000 kHz  S/N=+24.1 dB  → FT8_20m_14074000_20260603T142301Z.sigmf-data
```

## SigMF output format

Each recording produces two files:

```
FT8_20m_14074000_20260603T142301Z.sigmf-data   # raw complex64 little-endian IQ
FT8_20m_14074000_20260603T142301Z.sigmf-meta   # JSON metadata
```

Metadata includes `sample_rate=12000`, `center_frequency`, datetime, and
`hardware="KiwiSDR"`.  The datatype is `cf32_le` (complex float32, little-endian).

## Decoding recordings externally

To decode FT8 from a recording in WSJT-X:
1. Convert the `.sigmf-data` file to WAV using `sigmf-convert` or a simple
   Python script (read complex64, take real part, write as 16-bit PCM at 12 kHz).
2. Open in WSJT-X File → Open and set mode to FT8.

Alternatively, use the `decode65` utility directly from the WSJT-X source.

## SQLite schema

```sql
activity(id, ts_utc, ts_unix, freq_hz, label, snr_db, recorded, sigmf_path)
```

Query example — all FT8 20m recordings:
```sql
SELECT ts_utc, snr_db, sigmf_path FROM activity
WHERE label = 'FT8_20m' AND recorded = 1
ORDER BY ts_unix DESC LIMIT 20;
```

## Dependencies

```
pip install rf-bench-drivers-kiwisdr numpy
```
