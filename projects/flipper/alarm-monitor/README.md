> ⚠️ **UNTESTED** — This implementation has not been verified against physical hardware.
> Code is complete but has not been bench-tested. Verify behavior before relying on output.

# rf-bench-flipper-alarm-monitor

**GitHub:** https://github.com/jfrancis42/rf-bench-flipper-alarm-monitor

Monitors 433 MHz EV1527/PT2262 fixed-code wireless alarm sensors (door/window/PIR).
Looks up sensor codes in a named registry JSON, logs trigger events to SQLite, and
optionally POSTs a JSON webhook on each trigger. New codes are auto-registered.

## Hardware

| Instrument | Role |
|-----------|------|
| Flipper Zero (/dev/ttyACM0) | CC1101 receiver |

## Usage

```
python alarm_monitor.py [options]
```

### Options

| Flag | Default | Description |
|------|---------|-------------|
| `--freq MHZ` | 433.92 | Receive frequency |
| `--db FILE` | alarm_events.db | SQLite event log |
| `--registry FILE` | sensors.json | Named sensor registry |
| `--webhook URL` | (none) | POST webhook on trigger |
| `--duration S` | 0 (forever) | Run duration |
| `--serial PORT` | /dev/ttyACM0 | Flipper serial port |

### Examples

```bash
# Run forever, log events
python alarm_monitor.py

# With Home Assistant webhook
python alarm_monitor.py --webhook http://homeassistant:8123/api/webhook/alarm

# Custom registry
python alarm_monitor.py --registry my_house.json
```

## Sensor registry format

```json
{
  "sensors": {
    "A1B2C3": {"name": "Front Door", "type": "door"},
    "D4E5F6": {"name": "Garage PIR", "type": "pir"}
  }
}
```

New codes seen for the first time are auto-added as `Sensor_XXXXXX` with type `unknown`.
Edit the registry to give them meaningful names.
