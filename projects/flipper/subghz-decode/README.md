
# rf-bench-flipper-subghz-decode

**GitHub:** https://github.com/jfrancis42/rf-bench-flipper-subghz-decode

Receives ISM band packets via the Flipper Zero, logs protocol name and decoded data to
SQLite. Optionally triggers an SSA narrow-span sweep after each decode to measure the
transmission bandwidth and frequency error in ppm.

## Hardware

| Instrument | Role |
|-----------|------|
| Flipper Zero (/dev/ttyACM0) | CC1101 RX — packet receiver |
| Siglent SSA3032X Plus (10.1.1.60) | Optional RF characterization after each decode |

## Usage

```
python subghz_decode.py [options]
```

### Options

| Flag | Default | Description |
|------|---------|-------------|
| `--freq MHZ` | 433.92 | Receive frequency in MHz |
| `--duration S` | 300 | Run duration; 0 = forever |
| `--db FILE` | subghz_packets.db | SQLite output database |
| `--ssa HOST` | (none) | SSA IP for RF characterization |
| `--serial PORT` | /dev/ttyACM0 | Flipper serial port |

### Examples

```bash
# Passive 5-minute capture at 433.92 MHz
python subghz_decode.py --freq 433.92 --duration 300

# With SSA characterization, custom DB
python subghz_decode.py --freq 315 --ssa 10.1.1.60 --db garage.db

# Run forever until Ctrl+C
python subghz_decode.py --freq 433.92 --duration 0
```

## Database schema

Table `packets`:

| Column | Type | Description |
|--------|------|-------------|
| `id` | INTEGER | Auto-increment PK |
| `ts` | TEXT | ISO timestamp |
| `freq_hz` | REAL | Receive frequency |
| `protocol` | TEXT | Protocol name from Flipper |
| `code` | TEXT | Decoded code/value |
| `raw_data` | TEXT | Raw Flipper output |
| `bw_hz` | REAL | 3 dB bandwidth (SSA, optional) |
| `freq_err_ppm` | REAL | Frequency error ppm (SSA, optional) |

## Notes

- Without `--ssa`, bandwidth and ppm columns are NULL.
- The Flipper raw capture window is 2 seconds per poll cycle.
- Use `sqlite3 subghz_packets.db "SELECT ts,protocol,code FROM packets"` to review logs.
