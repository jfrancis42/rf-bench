> ⚠️ **UNTESTED** — This implementation has not been verified against physical hardware.
> Code is complete but has not been bench-tested. Verify behavior before relying on output.

# rf-bench-rtlsdr-fm-rds

**GitHub:** https://github.com/jfrancis42/rf-bench-rtlsdr-fm-rds

FM band monitor with RDS decode: scans 87.5–108 MHz, demodulates FM stations,
and decodes RDS metadata (station name / PS, PI code, program type, radiotext).
Identifies distant stations by their PI code region — the signature of a
tropospheric ducting event.

Extends the SSA FM propagation monitor (#64): the SSA tracks power levels and
produces a waterfall; this tool adds station identity and RDS data.

## Hardware

| Component | Notes |
|-----------|-------|
| RTL-SDR Blog v4 | Any RTL2832U dongle works |
| FM antenna | Simple dipole (72 cm total length) or telescoping whip |

## System dependencies

```bash
pacman -S rtl-sdr sox
# RDS decode (strongly recommended)
# redsea: https://github.com/windytan/redsea
# Build from source: git clone && cmake && make
```

Without `redsea`, the script still logs power and frequency but cannot decode PI / PS / radiotext.

## Usage

```
python fm_rds.py [options]
```

| Flag | Default | Description |
|------|---------|-------------|
| `--freq MHZ` | — | Monitor a single station continuously |
| `--gain DB` | auto | Gain in dB or `auto` |
| `--db FILE` | fm_rds.db | SQLite database path |
| `--ssa HOST` | — | SSA host (future: triggered demodulation) |
| `--alert` | — | SMS alert when a new PI code region is detected |
| `--dwell S` | 5 | Seconds per station in scan mode |
| `--no-rds` | — | Power scan only, skip RDS decode |
| `--serial S` | first | RTL-SDR serial number |

### Examples

```bash
# Full band scan with RDS
python fm_rds.py

# Monitor one station continuously
python fm_rds.py --freq 96.5

# Band scan, SMS alert on new PI region (tropospheric ducting)
python fm_rds.py --alert

# Quick power survey, no RDS decode
python fm_rds.py --no-rds
```

### Example output

```
Time      Freq    PI      Region    PS        PTY  Radiotext
------------------------------------------------------------------------
[14:23]   96.5  A123    US        KXXX     pop  Taylor Swift - ...
[14:24]  101.1  A456    US        KYYZ     rock Led Zeppelin - ...
[14:25]   98.7  E2B4    DE        AFN      —    (no RT)             <<<  NEW REGION
```

The `<<<` flag marks a PI code from a new geographic region — a likely
tropospheric ducting event when seen on a normally-clear frequency.

## Tropospheric ducting detection

Each PI code encodes a transmitter's country and region in the upper nibble.
When a PI code from a distant region appears on a frequency that normally carries
a local station, it indicates that the ionosphere (or troposphere) is refracting
signals beyond their normal range.  The `--alert` flag sends an SMS via
`~/money/sms.py` when this occurs.

## SQLite schema

```sql
stations(pi_code, ps_name, pty, region, first_seen, last_seen, seen_count)
observations(timestamp, freq_mhz, pi_code, ps_name, pty, radiotext, power_db, is_new_pi)
```

## Python dependencies

```
pip install rf-bench-drivers-rtlsdr numpy
```
