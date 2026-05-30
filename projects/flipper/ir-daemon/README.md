> ⚠️ **UNTESTED** — This implementation has not been verified against physical hardware.
> Code is complete but has not been bench-tested. Verify behavior before relying on output.

# rf-bench-flipper-ir-daemon

**GitHub:** https://github.com/jfrancis42/rf-bench-flipper-ir-daemon

HTTP REST daemon for the Flipper Zero IR transmitter/receiver. Exposes four endpoints
for sending protocol-encoded codes, raw timings, replaying library entries, and
receiving incoming IR signals.

## Hardware

| Instrument | Role |
|-----------|------|
| Flipper Zero (/dev/ttyACM0) | IR transmitter + receiver |

## Usage

```
python ir_daemon.py [options]
```

### Options

| Flag | Default | Description |
|------|---------|-------------|
| `--port N` | 8099 | HTTP port |
| `--library FILE` | ir_library_db.json | Button library JSON |
| `--serial PORT` | /dev/ttyACM0 | Flipper serial port |

### Endpoints

| Method | Path | Body / Query | Description |
|--------|------|-------------|-------------|
| POST | `/ir/send` | `{"protocol":"NEC","address":7,"command":2}` | Send protocol code |
| POST | `/ir/raw` | `{"timings_us":[...], "frequency":38000}` | Send raw timings |
| POST | `/ir/replay` | `{"device":"TV","button":"POWER"}` | Replay library code |
| GET | `/ir/receive` | `?timeout=5` | Wait for incoming IR |

### Examples

```bash
# Start daemon
python ir_daemon.py --port 8099

# Send NEC code
curl -X POST http://localhost:8099/ir/send \
     -H 'Content-Type: application/json' \
     -d '{"protocol":"NEC","address":7,"command":2}'

# Replay from library
curl -X POST http://localhost:8099/ir/replay \
     -H 'Content-Type: application/json' \
     -d '{"device":"TV","button":"POWER"}'

# Receive (blocks up to 5 s)
curl http://localhost:8099/ir/receive?timeout=5
```

## Notes

- Uses Python stdlib http.server; no external web framework needed.
- Library is loaded once at startup; restart daemon to pick up library changes.
