> ⚠️ **UNTESTED** — This implementation has not been verified against physical hardware.
> Code is complete but has not been bench-tested. Verify behavior before relying on output.

# rf-bench-flipper-ir-library

**GitHub:** https://github.com/jfrancis42/rf-bench-flipper-ir-library

Interactive IR code capture and management. Names devices and remotes, captures IR signals
from the Flipper, and exports to JSON, Flipper .ir format, LIRC lircd.conf, and Pronto hex.

## Hardware

| Instrument | Role |
|-----------|------|
| Flipper Zero (/dev/ttyACM0) | IR receiver + transmitter |

## Usage

```
python ir_library.py COMMAND [options]
```

### Commands

| Command | Description |
|---------|-------------|
| `capture --device NAME --remote MODEL` | Capture IR codes interactively |
| `replay --device NAME --button BTN` | Replay a stored code |
| `search --protocol PROTO` | Search by protocol name |
| `list` | List all devices and button counts |
| `import PATH` | Import a Flipper .ir file |

### Options

| Flag | Default | Description |
|------|---------|-------------|
| `--serial PORT` | /dev/ttyACM0 | Flipper serial port |
| `--library FILE` | ir_library_db.json | Library JSON file |

### Examples

```bash
# Start a capture session for a Samsung TV
python ir_library.py capture --device TV --remote "Samsung UN55"

# Replay power button
python ir_library.py replay --device TV --button POWER

# Find all NEC protocol codes
python ir_library.py search --protocol NEC

# List all devices
python ir_library.py list

# Import from Flipper SD card export
python ir_library.py import ~/flipper/my_remote.ir
```

## Output files

| File | Description |
|------|-------------|
| `ir_library_db.json` | Master library (all devices) |
| `{device}.ir` | Flipper .ir format (after capture) |
| `{device}.lircd.conf` | LIRC config (after capture) |
