> ⚠️ **UNTESTED** — This implementation has not been verified against physical hardware.
> Code is complete but has not been bench-tested. Verify behavior before relying on output.

# rf-bench-flipper-sensor-hub

**GitHub:** https://github.com/jfrancis42/rf-bench-flipper-sensor-hub

Receives 433 MHz OOK broadcast packets from consumer weather sensors. Decodes
Oregon Scientific v3 and Nexus/Fine Offset/AcuRite protocols inline (no external
decoder dependency). Logs temperature/humidity/battery to SQLite and serves current
sensor readings at GET /sensors.

## Hardware

| Instrument | Role |
|-----------|------|
| Flipper Zero (/dev/ttyACM0) | CC1101 receiver at 433.92 MHz |

## Usage

```
python sensor_hub.py [options]
```

### Options

| Flag | Default | Description |
|------|---------|-------------|
| `--freq MHZ` | 433.92 | Receive frequency |
| `--port N` | 8095 | HTTP API port |
| `--db FILE` | sensor_hub.db | SQLite database |
| `--duration S` | 0 (forever) | Run duration |
| `--serial PORT` | /dev/ttyACM0 | Flipper serial port |

### Examples

```bash
# Run forever, serve at port 8095
python sensor_hub.py

# Query current readings
curl http://localhost:8095/sensors
```

## Supported protocols

| Protocol | Devices |
|----------|---------|
| Nexus / Fine Offset | AcuRite, WH2, TH02, many clones |
| Oregon Scientific v3 | THGN132N, THN132N, and similar |

## Output

- SQLite `readings` table: ts, sensor_id, protocol, channel, temp_c, humidity, battery_ok
- HTTP GET /sensors: JSON dict of latest reading per sensor ID
