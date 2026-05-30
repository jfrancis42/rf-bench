# rf-bench-vna-impedance

**GitHub:** https://github.com/jfrancis42/rf-bench-vna-impedance

> **⚠ Future project — requires HP 8712B VNA + KISS-488 Ethernet-GPIB adapter**

> **⚠ Untested — awaiting physical hardware.** This script was written from documentation
> but has not been run against a real HP 8712B. It will require debugging and verification
> once the KISS-488 Ethernet-GPIB adapter is installed and the VNA is connected.

True RF impedance analyzer using HP 8712B calibrated S11. Converts S11 to complex
impedance Z = R + jX and plots Z(f), |Z|(f), and a Smith chart.

Superior to `rf-bench-rf-impedance` (series injection): that method is accurate only
below ~30 MHz; this tool uses full SOLT calibration accurate to 1.3 GHz.

## Hardware

| Instrument | Role |
|-----------|------|
| HP 8712B VNA (via KISS-488 at 10.1.1.70) | Calibrated S11 measurement |
| SOLT standard set | For port 1 calibration |

## Usage

```
python vna_impedance.py [options]
```

### Options

| Flag | Default | Description |
|------|---------|-------------|
| `--start KHZ` | 300 | Start frequency |
| `--stop KHZ` | 1300000 | Stop frequency |
| `--points N` | 401 | Sweep points |
| `--power DBM` | −10 | Port power |
| `--use-cal` | off | Enable stored calibration |
| `--host HOST` | 10.1.1.70 | KISS-488 IP address |
| `--prefix TEXT` | timestamped | Output filename prefix |

## Output files

`{prefix}_impedance.{png,txt,json}` — |Z|, R, X, phase, Smith chart.
