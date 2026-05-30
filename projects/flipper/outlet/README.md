> ⚠️ **UNTESTED** — This implementation has not been verified against physical hardware.
> Code is complete but has not been bench-tested. Verify behavior before relying on output.

# rf-bench-flipper-outlet

**GitHub:** https://github.com/jfrancis42/rf-bench-flipper-outlet

Learn 433 MHz wireless outlet on/off codes via Flipper Zero raw capture, store them
in outlets.json, and control them via CLI or a lightweight REST API.

## Hardware

| Instrument | Role |
|-----------|------|
| Flipper Zero (/dev/ttyACM0) | CC1101 RX (learn) + TX (send) |

## Usage

```
python outlet.py COMMAND [options]
```

### Commands

| Command | Description |
|---------|-------------|
| `learn --name NAME` | Capture on/off codes interactively |
| `send --name NAME --state on\|off` | Transmit a stored code |
| `serve --port N` | Start REST daemon |

### Options

| Flag | Default | Description |
|------|---------|-------------|
| `--serial PORT` | /dev/ttyACM0 | Flipper serial port |
| `--outlets FILE` | outlets.json | Storage file |

### REST endpoints

| Method | Path | Description |
|--------|------|-------------|
| GET | `/outlets` | List outlets and state capability |
| POST | `/outlets/NAME/on` | Turn outlet on |
| POST | `/outlets/NAME/off` | Turn outlet off |

### Examples

```bash
# Learn a lamp outlet
python outlet.py learn --name "Desk Lamp"

# Turn it on
python outlet.py send --name "Desk Lamp" --state on

# Start daemon
python outlet.py serve --port 8096

# Control via curl
curl -X POST http://localhost:8096/outlets/Desk%20Lamp/on
```
