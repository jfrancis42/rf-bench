# rf-bench-vna-sparams

**GitHub:** https://github.com/jfrancis42/rf-bench-vna-sparams

> **⚠ Future project — requires HP 8712B VNA + KISS-488 Ethernet-GPIB adapter**

> **⚠ Untested — awaiting physical hardware.** This script was written from documentation
> but has not been run against a real HP 8712B. It will require debugging and verification
> once the KISS-488 Ethernet-GPIB adapter is installed and the VNA is connected.

Full two-port S-parameter suite (S11, S21, S12, S22) with SOLT calibration using the
HP 8712B Vector Network Analyzer. Measures magnitude and phase for all S-parameters and
saves data in Touchstone .s2p format.

## Hardware

| Instrument | Role |
|-----------|------|
| HP 8712B VNA (via KISS-488 at 10.1.1.70) | Two-port S-parameter measurement |
| SOLT calibration standard set | SOL on port 1, THRU between ports |

## Usage

```
python vna_sparams.py [options]
```

### Options

| Flag | Default | Description |
|------|---------|-------------|
| `--start KHZ` | 300 | Start frequency (kHz) |
| `--stop KHZ` | 1300000 | Stop frequency (kHz) |
| `--points N` | 401 | Sweep points |
| `--params TEXT` | S11,S21,S12,S22 | Comma-separated parameter list |
| `--power DBM` | −10 | Port power |
| `--averages N` | 0 | Trace averages (0 = off) |
| `--calibrate` | off | Run interactive SOLT calibration first |
| `--use-cal` | off | Enable stored calibration correction |
| `--host HOST` | 10.1.1.70 | KISS-488 IP address |
| `--prefix TEXT` | timestamped | Output filename prefix |

## Output files

| File | Description |
|------|-------------|
| `{prefix}_sparams.png` | 2×2 magnitude + 2×2 phase grid |
| `{prefix}_sparams.s2p` | Touchstone S2P file |
| `{prefix}_sparams.txt` | Tabular data |
| `{prefix}_sparams.json` | Full numerical data |
