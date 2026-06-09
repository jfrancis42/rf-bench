# beacon-logger

VHF/UHF propagation beacon signal-strength logger for the **Icom IC-9700**.

Tunes the radio to a fixed frequency, reads the S-meter at a configurable
interval, and logs each reading to a SQLite database.  Optionally geo-tags
readings with GPS and serves live data over HTTP.

## Use cases

- Track tropospheric ducting events via 2m or 70cm propagation beacons
- Monitor APRS or weak-signal beacon activity over time
- Log satellite (ISS, AO-91, etc.) visibility windows
- Characterise a long-term propagation path to a known transmitter
- Mobile coverage mapping with `--gps`

## Hardware required

- Icom IC-9700 transceiver (USB or LAN, rigctld running)
- (Optional) gpsd-connected GPS receiver for position tagging

## Setup

```bash
pip install rf-bench-drivers-icom rf-bench-drivers-gpsd

# Start rigctld for IC-9700 (USB):
rigctld -m 3081 -r /dev/ttyUSB0 -s 115200 &

# Or via LAN:
rigctld -m 3081 -r 192.168.1.50 &
```

## Usage

```bash
# Log W6YX 144.283 MHz beacon indefinitely:
python beacon_logger.py --freq 144283 --label "W6YX 2m"

# Log ISS APRS downlink (FM), alert when signal reaches -63 dBm (≈S9):
python beacon_logger.py --freq 145825 --mode fm --label "ISS" --alert-dbm -63

# 70cm EME frequency, USB, 10-second interval, with GPS:
python beacon_logger.py --freq 432000 --mode usb --label "70cm EME" \
    --interval 10 --gps

# Run for 24 hours with live HTTP monitor:
python beacon_logger.py --freq 144283 --label "W6YX" \
    --duration 86400 --http
# then: curl http://localhost:8088/data

# Custom output filename:
python beacon_logger.py --freq 144283 --label "W6YX" --out my_log.db
```

## Options

| Option | Default | Description |
|--------|---------|-------------|
| `--freq KHZ` | required | Receive frequency in kHz (e.g. `144283` = 144.283 MHz) |
| `--mode MODE` | `usb` | Demodulation mode: `usb lsb cw cwr fm am dv` |
| `--label TEXT` | `beacon` | Human-readable name used in filename and DB |
| `--interval S` | `5` | Seconds between S-meter readings |
| `--duration S` | unlimited | Total run time in seconds |
| `--alert-dbm DBM` | off | SMS alert when signal ≥ this level (dBm) |
| `--gps` | off | Tag readings with GPS position via gpsd |
| `--http` | off | Serve live JSON at `http://localhost:PORT/data` |
| `--http-port N` | `8088` | HTTP server port |
| `--out FILE` | auto | SQLite output path |
| `--rig-host HOST` | `localhost` | rigctld host |
| `--rig-port N` | `4532` | rigctld port |

## Output

SQLite database with one row per measurement:

| Column | Type | Description |
|--------|------|-------------|
| `ts_utc` | TEXT | ISO 8601 UTC timestamp |
| `ts_unix` | REAL | Unix epoch (seconds) |
| `signal_dbm` | REAL | S-meter reading in dBm |
| `lat` / `lon` | REAL | GPS coordinates (NULL if no GPS) |
| `alt_m` | REAL | GPS altitude in metres |
| `hdop` | REAL | Horizontal dilution of precision |

### Querying the database

```bash
sqlite3 beacon_W6YX_*.db \
  "SELECT ts_utc, round(signal_dbm,1) FROM beacon ORDER BY signal_dbm DESC LIMIT 20;"
```

```python
import sqlite3, pandas as pd
df = pd.read_sql("SELECT * FROM beacon", sqlite3.connect("beacon_W6YX_....db"))
df["ts"] = pd.to_datetime(df["ts_utc"])
df.plot(x="ts", y="signal_dbm")
```

## HTTP live data

When `--http` is active, `GET http://localhost:8088/data` returns:

```json
{
  "label": "W6YX 2m",
  "freq_khz": 144283.0,
  "mode": "usb",
  "signal_dbm": -87.5,
  "peak_dbm": -71.2,
  "mean_dbm": -91.3,
  "samples": 432,
  "timestamp": "2026-06-03T21:00:00Z",
  "lat": 39.3554,
  "lon": -104.6730
}
```

## S-meter calibration note

The IC-9700 S-meter is calibrated to ITU standards: S9 = −93 dBm on HF,
S9 = −73 dBm on VHF/UHF.  Each S-unit = 6 dB.  The `get_strength_settled()`
method in the IC-9700 driver returns the rigctld S-meter reading converted to
dBm using Hamlib's built-in calibration table.  For more precise calibration
against a known signal source, run `vhf-receiver-test` first.
