# rf-bench-vna-tline

**GitHub:** https://github.com/jfrancis42/rf-bench-vna-tline

> **⚠ Future project — requires HP 8712B VNA + KISS-488 Ethernet-GPIB adapter**

> **⚠ Untested — awaiting physical hardware.** This script was written from documentation
> but has not been run against a real HP 8712B. It will require debugging and verification
> once the KISS-488 Ethernet-GPIB adapter is installed and the VNA is connected.

Transmission line characterizer. Measures velocity factor, propagation loss (dB/m),
and electrical length using S21 from the HP 8712B.

## Hardware

| Instrument | Role |
|-----------|------|
| HP 8712B VNA (via KISS-488 at 10.1.1.70) | S21 magnitude and phase |

## Setup

```
VNA Port 1 ──→ [Cable under test] ──→ VNA Port 2
```

## Usage

```
python vna_tline.py --length-m LENGTH [options]
```

### Options

| Flag | Default | Description |
|------|---------|-------------|
| `--length-m M` | required | Physical cable length (meters) |
| `--start KHZ` | 300 | Start frequency |
| `--stop KHZ` | 1300000 | Stop frequency |
| `--points N` | 401 | Sweep points |
| `--measure-z0` | off | Measure Z0 with open/short termination |
| `--power DBM` | −10 | Port power |
| `--host HOST` | 10.1.1.70 | KISS-488 IP address |
| `--prefix TEXT` | timestamped | Output filename prefix |

## Output files

`{prefix}_tline.{png,txt,json}` — S21 magnitude, phase, velocity factor, loss/m.
