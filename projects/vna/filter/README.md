# rf-bench-vna-filter

**GitHub:** https://github.com/jfrancis42/rf-bench-vna-filter

> **⚠ Future project — requires HP 8712B VNA + KISS-488 Ethernet-GPIB adapter**

> **⚠ Untested — awaiting physical hardware.** This script was written from documentation
> but has not been run against a real HP 8712B. It will require debugging and verification
> once the KISS-488 Ethernet-GPIB adapter is installed and the VNA is connected.

Filter characterization with group delay. Measures S11 (return loss), S21 (insertion
loss), and phase. Computes group delay and annotates passband edges, stopband start,
and group delay variation.

Superior to `rf-bench-scalar-vna` which measures amplitude only.

## Hardware

| Instrument | Role |
|-----------|------|
| HP 8712B VNA (via KISS-488 at 10.1.1.70) | Full vector S-parameter measurement |

## Usage

```
python vna_filter.py [options]
```

### Options

| Flag | Default | Description |
|------|---------|-------------|
| `--start KHZ` | 300 | Start frequency |
| `--stop KHZ` | 1300000 | Stop frequency |
| `--points N` | 801 | Sweep points |
| `--power DBM` | −10 | Port power |
| `--smooth` | off | Smooth group delay (Savitzky-Golay) |
| `--use-cal` | off | Enable stored calibration |
| `--host HOST` | 10.1.1.70 | KISS-488 IP address |
| `--prefix TEXT` | timestamped | Output filename prefix |

## Output files

`{prefix}_filter.{png,txt,json}` — S11/S21 magnitude, S21 phase, group delay.
