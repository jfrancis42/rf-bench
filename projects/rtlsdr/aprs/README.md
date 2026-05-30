> ⚠️ **UNTESTED** — This implementation has not been verified against physical hardware.
> Code is complete but has not been bench-tested. Verify behavior before relying on output.

# rf-bench-rtlsdr-aprs

**GitHub:** https://github.com/jfrancis42/rf-bench-rtlsdr-aprs

APRS direct-RF receiver: decodes 1200-baud AFSK packets on 144.390 MHz via RTL-SDR
and direwolf, enriches each callsign from the govt-data `/callsigns` API, logs to
SQLite, and optionally compares heard-locally coverage against the APRS-IS database.

## Hardware

| Component | Notes |
|-----------|-------|
| RTL-SDR Blog v4 | Any RTL2832U dongle works |
| 144 MHz vertical antenna | 2m co-linear or simple 5/8 vertical |
| Inline LNA (optional) | Enable bias tee: `--bias-tee` |

## System dependencies

```bash
pacman -S rtl-sdr direwolf
```

## Usage

```
python aprs.py [options]
```

| Flag | Default | Description |
|------|---------|-------------|
| `--freq KHZ` | 144390 | Receive frequency in kHz |
| `--gain DB` | 40 | Receiver gain in dB |
| `--db FILE` | aprs_local.db | SQLite log path |
| `--no-enrich` | — | Disable FCC callsign lookup |
| `--compare` | — | Print APRS-IS coverage comparison after session |
| `--duration S` | 0 | Stop after N seconds (0 = run forever) |
| `--serial S` | first | RTL-SDR serial number |

### Examples

```bash
# Basic receive
python aprs.py

# One-hour session then compare against APRS-IS
python aprs.py --duration 3600 --compare

# Raw logging, no enrichment
python aprs.py --no-enrich
```

## Coverage comparison (--compare)

Compares locally heard callsigns against the aprs-server PostgreSQL database
(`10.1.0.20`, database `aprs`).  Reports three categories:

- **Gated**: heard locally AND on APRS-IS
- **Local only**: heard locally but never gated (missing igate coverage)
- **APRS-IS only**: on the internet but not heard locally (out of RF range)

Requires `psycopg2` and access to the aprs-server database.

## Decode pipeline

```
rtl_fm → AFSK audio → direwolf → AX.25 packets → Python
```

direwolf handles all AFSK demodulation; the Python script parses its output.

## SQLite schema

```sql
callsign_info(callsign, name, address, license, enriched_at)
packets(timestamp, callsign, path, packet_type, data, rssi_db, raw)
```
