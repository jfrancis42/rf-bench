# rf-bench-rtlsdr-adsb

**GitHub:** https://github.com/jfrancis42/rf-bench-rtlsdr-adsb

ADS-B local receiver: decodes Mode S / ADS-B transmissions at 1090 MHz using an
RTL-SDR dongle, enriches aircraft with N-number and registration data from the
govt-data `/aircraft` API, logs to SQLite, and serves live JSON over HTTP.

Complements [Vestigare](https://github.com/jfrancis42/vestigare) (which aggregates
internet feeds) by showing what is actually audible at your antenna.

## Hardware

| Component | Notes |
|-----------|-------|
| RTL-SDR Blog v4 | Any RTL2832U dongle works; v4 has better sensitivity |
| 1090 MHz antenna | Coaxial collinear or simple dipole at 6.9 cm per element |
| 1090 MHz bandpass filter | Strongly recommended; dramatically reduces overload |
| Inline LNA (optional) | Enable bias tee: `--bias-tee` |

## Usage

```
python adsb.py [options]
```

| Flag | Default | Description |
|------|---------|-------------|
| `--gain DB` | 40 | Receiver gain in dB |
| `--port N` | 8090 | HTTP server port |
| `--db FILE` | adsb.db | SQLite database path |
| `--no-enrich` | — | Disable govt-data aircraft lookup |
| `--dump-only` | — | Print raw hex to stdout, no HTTP |
| `--csv FILE` | — | Append position fixes to CSV |
| `--serial S` | first | RTL-SDR serial number |
| `--block-size N` | 131072 | IQ block size |

### Examples

```bash
# Start receiver with HTTP API
python adsb.py

# Higher gain, specific dongle, no enrichment
python adsb.py --gain 48 --serial 00000001 --no-enrich

# Raw hex dump for piping to other tools
python adsb.py --dump-only | tee raw.hex
```

## HTTP API

| Endpoint | Response |
|----------|----------|
| `GET /aircraft` | JSON array of all currently tracked aircraft |
| `GET /aircraft/{icao}` | JSON object for one aircraft by ICAO hex |
| `GET /status` | `{"aircraft_count": N, "status": "ok"}` |

### Aircraft JSON fields

`icao`, `callsign`, `n_number`, `type_code`, `owner`, `lat`, `lon`,
`alt_ft`, `speed_kt`, `heading`, `vert_rate`, `last_seen`, `msg_count`, `rssi_db`

## SQLite schema

```sql
aircraft(icao_hex, callsign, n_number, type_code, owner, enriched_at)
positions(timestamp, icao_hex, lat, lon, alt_ft, speed_kt, heading, vert_rate, rssi_db)
```

## Dependencies

System packages (pacman):
```
rtl-sdr
```

Python:
```
pip install rf-bench-drivers-rtlsdr pyModeS
```
