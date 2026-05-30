# rf-bench-vna-group-delay

**GitHub:** https://github.com/jfrancis42/rf-bench-vna-group-delay

> **⚠ Future project — requires HP 8712B VNA + KISS-488 Ethernet-GPIB adapter**

> **⚠ Untested — awaiting physical hardware.** This script was written from documentation
> but has not been run against a real HP 8712B. It will require debugging and verification
> once the KISS-488 Ethernet-GPIB adapter is installed and the VNA is connected.

Group delay measurement from S21 phase data. Plots S21 magnitude, phase, and computed
group delay in nanoseconds. Useful for filter characterization, cable dispersion, and
amplifier phase distortion analysis.

## Hardware

| Instrument | Role |
|-----------|------|
| HP 8712B VNA (via KISS-488 at 10.1.1.70) | S21 complex measurement |

## Usage

```
python vna_group_delay.py --start KHZ --stop KHZ [options]
```

### Options

| Flag | Default | Description |
|------|---------|-------------|
| `--start KHZ` | 300 | Start frequency |
| `--stop KHZ` | 1300000 | Stop frequency |
| `--points N` | 401 | Sweep points |
| `--power DBM` | −10 | Port power |
| `--smooth` | off | Savitzky-Golay smoothing on group delay |
| `--host HOST` | 10.1.1.70 | KISS-488 IP address |
| `--prefix TEXT` | timestamped | Output filename prefix |

## Output files

`{prefix}_group_delay.{png,txt,json}` — S21 magnitude, phase, and group delay.

## Method

Group delay: τ(f) = −dφ/dω where φ is unwrapped S21 phase. Computed via numpy
gradient. The HP 8712B can also compute group delay directly via the GDEL format.
