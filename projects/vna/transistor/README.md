# rf-bench-vna-transistor

**GitHub:** https://github.com/jfrancis42/rf-bench-vna-transistor

> **⚠ Future project — requires HP 8712B VNA + KISS-488 Ethernet-GPIB adapter + bias fixture**

> **⚠ Untested — awaiting physical hardware.** This script was written from documentation
> but has not been run against a real HP 8712B. It will require debugging and verification
> once the KISS-488 Ethernet-GPIB adapter is installed and the VNA is connected.

Transistor S-parameter characterization with DC bias sweep. Measures all 4 S-parameters
at each bias point and computes gain, stability factor (K), maximum stable gain (MSG),
and stability circles.

## Hardware

| Instrument | Role |
|-----------|------|
| HP 8712B VNA (via KISS-488 at 10.1.1.70) | Two-port S-parameter measurement |
| Siglent SPD3303X-E (10.1.1.56) | DC bias supply |
| Custom bias-T fixture | RF choke + bypass cap on each port |

## Bias-T fixture

Each VNA port needs a bias-T to inject DC bias:
```
VNA port ──→ [DC block cap (100 nF)] ──→ DUT RF port
                  │
              [RF choke (1 mH)] ──→ SPD channel
```

## Usage

```
python vna_transistor.py [options]
```

### Options

| Flag | Default | Description |
|------|---------|-------------|
| `--start KHZ` | 300 | Start frequency |
| `--stop KHZ` | 1300000 | Stop frequency |
| `--points N` | 201 | Sweep points |
| `--vce-min V` | 1.0 | Minimum Vce/Vds (V) |
| `--vce-max V` | 10.0 | Maximum Vce/Vds (V) |
| `--vce-step V` | 1.0 | Bias voltage step (V) |
| `--ib-ua UA` | 100 | Collector/drain bias current (µA) |
| `--power DBM` | −10 | VNA port power |
| `--host HOST` | 10.1.1.70 | KISS-488 IP address |
| `--psu-host HOST` | 10.1.1.56 | SPD IP address |
| `--prefix TEXT` | timestamped | Output filename prefix |

## Output files

`{prefix}_transistor.{png,txt,json}` — |S21|, K-factor, MSG, stability circles per bias.
