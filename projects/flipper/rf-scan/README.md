
# rf-bench-flipper-rf-scan

**GitHub:** https://github.com/jfrancis42/rf-bench-flipper-rf-scan

Sweeps CC1101 RSSI across ISM frequencies (300-928 MHz) using subghz_scan_rssi().
Displays a live Unicode block bar chart in the terminal. Optional CSV logging mode.

**Firmware compatibility:** Tested with official and Momentum (mntm-012) firmware.
On official firmware, continuous RSSI samples are streamed at each step.
On Momentum/RogueMaster/Xtreme/Unleashed, RSSI is only reported when a packet is
decoded — frequencies with no active transmitters show `---`. This is an upstream
firmware limitation; `subghz rx_carrier` was removed from fork firmware.

## Hardware

| Instrument | Role |
|-----------|------|
| Flipper Zero (/dev/ttyACM0) | CC1101 RSSI scanner |

## Usage

```
python rf_scan.py [options]
```

### Options

| Flag | Default | Description |
|------|---------|-------------|
| `--start MHZ` | 300 | Start frequency |
| `--stop MHZ` | 928 | Stop frequency |
| `--step KHZ` | 200 | Step size |
| `--dwell S` | 0.05 | Dwell per step |
| `--log FILE` | (none) | CSV log (append) |
| `--continuous` | off | Loop until Ctrl+C |
| `--serial PORT` | /dev/ttyACM0 | Flipper serial port |

### Examples

```bash
# Full ISM scan, single sweep
python rf_scan.py

# Continuous scan of 433 MHz band
python rf_scan.py --start 430 --stop 440 --step 50 --continuous

# Log to CSV
python rf_scan.py --log scan.csv --continuous
```

## Notes

- Bar chart uses Unicode block characters (U+2581-U+2588) for 8-level resolution.
- RSSI range displayed: -120 to -20 dBm.
- CC1101 RSSI is approximate (+/- 3 dB typical).
