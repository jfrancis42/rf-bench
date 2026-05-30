> ⚠️ **UNTESTED** — This implementation has not been verified against physical hardware.
> Code is complete but has not been bench-tested. Verify behavior before relying on output.

# rf-bench-flipper-ir-discover

**GitHub:** https://github.com/jfrancis42/rf-bench-flipper-ir-discover

Systematically transmits all 256 command codes for a given IR protocol and device
address. The user watches the target device and presses Enter when they observe a
response. Prints a summary of flagged codes at the end.

## Hardware

| Instrument | Role |
|-----------|------|
| Flipper Zero (/dev/ttyACM0) | IR transmitter |
| Target device | Device under test (TV, A/V receiver, etc.) |

## Usage

```
python ir_discover.py --protocol PROTO --address HEX [options]
```

### Options

| Flag | Default | Description |
|------|---------|-------------|
| `--protocol` | NEC | IR protocol: NEC, SIRC, RC5, Samsung32 |
| `--address HEX` | (required) | Device address in hex (e.g. 0x07) |
| `--delay S` | 0.08 | Seconds between codes |
| `--serial PORT` | /dev/ttyACM0 | Flipper serial port |

### Examples

```bash
# Discover codes for an NEC device at address 0x07
python ir_discover.py --protocol NEC --address 0x07

# Slower scan for slower devices
python ir_discover.py --protocol SIRC --address 0x01 --delay 0.15

# Samsung TV
python ir_discover.py --protocol Samsung32 --address 0x07
```

## Notes

- Press **Enter** or **Space** when you see the device respond to flag that code.
- Press **Ctrl+C** to stop the scan early and see results so far.
- Adjust `--delay` if the device misses codes at the default speed.
- Typical scan time: ~20 seconds at default 0.08 s/code.
