> ⚠️ **UNTESTED** — This implementation has not been verified against physical hardware.
> Code is complete but has not been bench-tested. Verify behavior before relying on output.

# rf-bench-flipper-tpms

**GitHub:** https://github.com/jfrancis42/rf-bench-flipper-tpms

Decodes TPMS tire pressure sensor broadcasts at 315 MHz (Schrader/Ford/GM) and
433.92 MHz (Continental/VW/Audi). Logs pressure and temperature to SQLite.
Learn mode captures sensor IDs and prompts for tire position labels.
Alert mode sends SMS via ~/Dropbox/build/money/sms.py when pressure drops below threshold.

## Hardware

| Instrument | Role |
|-----------|------|
| Flipper Zero (/dev/ttyACM0) | CC1101 receiver |

## Usage

```
python tpms.py [options]
```

### Options

| Flag | Default | Description |
|------|---------|-------------|
| `--freq MHZ` | 315 | Frequency: 315 or 433.92 |
| `--duration S` | 60 | Run time; 0=forever |
| `--db FILE` | tpms.db | SQLite database |
| `--learn` | off | Learn sensor IDs interactively |
| `--alert PSI` | (none) | SMS alert threshold (PSI) |
| `--serial PORT` | /dev/ttyACM0 | Flipper serial port |

### Examples

```bash
# Monitor 315 MHz for 60 seconds
python tpms.py --freq 315 --duration 60

# Learn sensor IDs (drive slowly)
python tpms.py --freq 315 --learn

# Monitor forever with low-pressure alert
python tpms.py --freq 315 --alert 28 --duration 0
```

## Supported protocols

| Protocol | Frequency | Vehicles |
|----------|-----------|---------|
| Schrader | 315 MHz | Ford, GM, Chrysler |
| Continental | 433.92 MHz | VW, Audi, Mercedes, BMW |

## Notes

- Sensor IDs are saved to `tpms_known_sensors.json` after learn mode.
- SMS alert requires `~/Dropbox/build/money/sms.py` to be present.
