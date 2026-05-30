> ⚠️ **UNTESTED** — This implementation has not been verified against physical hardware.
> Code is complete but has not been bench-tested. Verify behavior before relying on output.

# rf-bench-flipper-subghz-sensitivity

**GitHub:** https://github.com/jfrancis42/rf-bench-flipper-subghz-sensitivity

Maps CC1101 receiver sensitivity. The SSA3032X Plus tracking generator steps its output
level from −20 to −120 dBm at each ISM frequency; the Flipper reports RSSI at each step.
Produces a per-band RSSI calibration table and minimum detectable signal (MDS) estimate.

## Hardware

| Instrument | Role |
|-----------|------|
| Siglent SSA3032X Plus (10.1.1.60) | Tracking generator — calibrated signal source |
| Flipper Zero (/dev/ttyACM0) | CC1101 RX — reports RSSI |

Connect SSA tracking generator output → attenuator → Flipper Sub-GHz SMA input.

## Usage

```
python subghz_sensitivity.py [options]
```

### Options

| Flag | Default | Description |
|------|---------|-------------|
| `--ssa HOST` | 10.1.1.60 | SSA IP address |
| `--serial PORT` | /dev/ttyACM0 | Flipper serial port |
| `--freqs LIST` | 315,433.92,868,915 | Comma-separated MHz |
| `--output PREFIX` | timestamped | Output filename prefix |

### Examples

```bash
# All four ISM bands
python subghz_sensitivity.py --freqs 315,433.92,868,915

# Single band with custom serial
python subghz_sensitivity.py --freqs 433.92 --serial /dev/ttyACM0
```

## Output files

| File | Description |
|------|-------------|
| `{prefix}_sensitivity.png` | RSSI vs. applied level plot per band |
| `{prefix}_cal.json` | RSSI calibration table + MDS per band |

## Notes

- MDS estimated where RSSI departs >3 dB from the linear high-signal trend.
- Level steps: −20 to −120 dBm in 5 dBm steps (21 points per band).
- SSA tracking generator output accuracy: ±1 dB typical.
