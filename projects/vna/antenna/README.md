# rf-bench-vna-antenna

**GitHub:** https://github.com/jfrancis42/rf-bench-vna-antenna

> **⚠ Future project — requires HP 8712B VNA + KISS-488 Ethernet-GPIB adapter**

> **⚠ Untested — awaiting physical hardware.** This script was written from documentation
> but has not been run against a real HP 8712B. It will require debugging and verification
> once the KISS-488 Ethernet-GPIB adapter is installed and the VNA is connected.

Antenna feed-point impedance measurement via calibrated S11. Returns Z(f) = R(f) + jX(f),
VSWR, and return loss. Plots a Smith chart with the Z locus colored by frequency.
Backwards-compatible with `rf-bench-antenna-analyzer` VSWR output format.

The key advantage over `rf-bench-antenna-analyzer` (scalar): this tool provides R and X
separately, enabling direct matching network design.

## Hardware

| Instrument | Role |
|-----------|------|
| HP 8712B VNA (via KISS-488 at 10.1.1.70) | Calibrated port 1 S11 |
| SOLT standard set | Port 1 calibration (at the measurement cable end) |

## Setup

```
VNA Port 1 ──→ measurement cable ──→ [SOLT calibration plane] ──→ Antenna feed connector
```

Calibrate at the far end of the measurement cable for best accuracy.

## Usage

```
python vna_antenna.py [options]
```

### Options

| Flag | Default | Description |
|------|---------|-------------|
| `--start KHZ` | 1800 | Start frequency |
| `--stop KHZ` | 30000 | Stop frequency |
| `--points N` | 401 | Sweep points |
| `--power DBM` | −10 | Port power |
| `--use-cal` | off | Enable stored SOLT calibration |
| `--host HOST` | 10.1.1.70 | KISS-488 IP address |
| `--prefix TEXT` | timestamped | Output filename prefix |

## Output files

`{prefix}_antenna.{png,txt,json}` — VSWR, R+X, return loss, Smith chart.
