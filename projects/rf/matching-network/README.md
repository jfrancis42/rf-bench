> ⚠️ **UNTESTED** — This implementation has not been verified against physical hardware.
> Code is complete but has not been bench-tested. Verify behavior before relying on output.

# rf-bench-matching-network

**GitHub:** https://github.com/jfrancis42/rf-bench-matching-network

Impedance matching network designer and optional verifier. Synthesises L, Pi, and T
matching networks for any source/load impedance ratio at any frequency. Outputs component
values with E24 nearest-standard-value recommendations, a Smith chart, and optionally
measures the network's actual frequency response using the SDG and scope.

## No instruments required for synthesis

The design calculations are purely mathematical. Instruments are only needed for the
optional `--measure` verification mode.

## Usage

```
python matching_network.py --rs RS_OHM --rl RL_OHM --freq FREQ_KHZ --type {l|pi|t} [options]
```

### Options

| Flag | Default | Description |
|------|---------|-------------|
| `--rs OHM` | 50 | Source impedance (Ω) |
| `--rl OHM` | 200 | Load impedance (Ω) |
| `--freq KHZ` | 7000 | Design frequency (kHz) |
| `--type {l\|pi\|t}` | l | Network topology |
| `--q VALUE` | 5.0 | Loaded Q (Pi/T only; L-network Q is fixed by impedance ratio) |
| `--measure` | off | Measure frequency response with SDG + scope |
| `--measure-points N` | 21 | Points in the frequency sweep |
| `--sdg-host HOST` | 10.1.1.55 | SDG IP address |
| `--scope-host HOST` | 10.1.1.58 | Scope IP address |
| `--prefix TEXT` | timestamped | Output filename prefix |

### Examples

```bash
# 50 → 200 Ω L-network at 7 MHz
python matching_network.py --rs 50 --rl 200 --freq 7000 --type l

# 50 → 300 Ω Pi-network at 14 MHz, Q=5
python matching_network.py --rs 50 --rl 300 --freq 14000 --type pi --q 5

# T-network with measure mode
python matching_network.py --rs 75 --rl 300 --freq 1800 --type t --q 3 --measure
```

## L-network notes

The L-network Q is determined by the impedance ratio: Q = √(R_high/R_low − 1). No
Q choice is available. Both low-pass (shunt C, series L) and high-pass (shunt L, series C)
configurations are shown.

## Pi/T-network notes

Pi networks require Q > Q_min = √(R_high/R_low − 1). For ratios below this minimum,
use an L-network instead. T networks give higher Q for a given impedance ratio, making
them better for higher-impedance transformations.

## Fixtures and cabling (--measure mode)

```
SDG CH1 ──BNC-T──┬──→ Scope CH1 (reference)
                  └──→ 50 Ω ref resistor ──→ Matching network input
                                                      │
                                           Matching network output ──→ Scope CH2
```

## Output files

| File | Description |
|------|-------------|
| `{prefix}_schematic.png` | Component values + Smith chart |
| `{prefix}_results.txt` | Full component table with E24 values |
| `{prefix}_results.json` | Machine-readable design data |
| `{prefix}_measured.png` | Gain/phase vs. frequency (--measure mode) |
