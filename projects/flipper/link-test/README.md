> ⚠️ **UNTESTED** — This implementation has not been verified against physical hardware.
> Code is complete but has not been bench-tested. Verify behavior before relying on output.

# rf-bench-flipper-link-test

**GitHub:** https://github.com/jfrancis42/rf-bench-flipper-link-test

Range and link budget test for the Flipper Zero CC1101. In single-Flipper mode,
alternates TX and RSSI measurement to estimate received signal level vs. distance.
In --rx-mode, operates as a passive receiver for a second Flipper (or external TX).

## Hardware

| Instrument | Role |
|-----------|------|
| Flipper Zero (/dev/ttyACM0) | CC1101 TX+RX (single mode) or RX only (--rx-mode) |
| Second Flipper (optional) | TX side for --rx-mode |

## Usage

```
python link_test.py [options]
```

### Options

| Flag | Default | Description |
|------|---------|-------------|
| `--freq MHZ` | 433.92 | Test frequency |
| `--packets N` | 50 | Packets per distance step |
| `--power IDX` | 4 | PATABLE index 0-7 |
| `--distance M [...]` | 1 2 5 10 20 50 100 | Distance steps (meters) |
| `--rx-mode` | off | RX-only (second TX required) |
| `--serial PORT` | /dev/ttyACM0 | Flipper serial port |

### Examples

```bash
# Single-Flipper distance test
python link_test.py --freq 433.92 --packets 50

# Custom distance steps
python link_test.py --distance 1 5 10 20 --freq 315

# Two-Flipper: RX side
python link_test.py --rx-mode --packets 100 --freq 433.92
```

## Notes

- Single-Flipper mode TX and RX use the same antenna simultaneously.
  RSSI readings in this mode include the Flipper's own transmitted signal.
  This is useful for verifying the CC1101 is transmitting but not a true
  isolation test. Use --rx-mode with two Flippers for genuine link tests.
- RSSI accuracy: ±3 dB typical.
