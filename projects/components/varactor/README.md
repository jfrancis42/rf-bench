> ⚠️ **UNTESTED** — This implementation has not been verified against physical hardware.
> Code is complete but has not been bench-tested. Verify behavior before relying on output.

# rf-bench-varactor

**GitHub:** https://github.com/jfrancis42/rf-bench-varactor

Varactor (varicap) diode characterizer. Sweeps DC reverse-bias voltage and measures complex
impedance at a fixed RF frequency using the two-channel scope injection circuit. Extracts
C(V) and Q(V) curves, annotates the tuning ratio (C_max/C_min), and saves the data for
VCO and tunable filter design.

## Hardware

| Instrument | Role |
|-----------|------|
| Siglent SPD3303X-E (10.1.1.56) | DC bias supply (CH1, 10 mA limit) |
| Siglent SDG1062X (10.1.1.55) | RF test signal source |
| Siglent SDS2504X Plus (10.1.1.58) | Two-channel capture for impedance measurement |

## Fixture

```
SDG CH1 ──→ [50 Ω ref resistor] ──→ [100 nF bypass cap] ──→ Varactor anode
                                                                      │
                                               [1 mH RF choke] ──→ SPD CH1 (+)
Scope CH1 ↑ (before ref R)    Scope CH2 ↑ (after ref R)
Varactor cathode ──→ GND = SPD CH1 (−) = Scope GND
```

The RF choke keeps the DC bias out of the RF path. The bypass capacitor blocks DC from
the SDG output. Use a ceramic 100 nF cap (low series inductance) for the bypass.

## Usage

```
python varactor.py --freq FREQ_KHZ [options]
```

### Options

| Flag | Default | Description |
|------|---------|-------------|
| `--freq KHZ` | 14000 | RF test frequency (kHz) |
| `--vmin V` | 1.0 | Minimum bias voltage (V) |
| `--vmax V` | 15.0 | Maximum bias voltage (V) |
| `--vstep V` | 0.5 | Voltage step (V) |
| `--zref OHM` | 50 | Series reference resistor (Ω) |
| `--psu-ch N` | 1 | SPD channel for DC bias (1 or 2) |
| `--psu-host HOST` | 10.1.1.56 | SPD IP address |
| `--sdg-host HOST` | 10.1.1.55 | SDG IP address |
| `--scope-host HOST` | 10.1.1.58 | Scope IP address |
| `--prefix TEXT` | timestamped | Output filename prefix |

### Examples

```bash
# Characterize a BB833 varactor at 14 MHz, 1–15 V
python varactor.py --freq 14000 --vmin 1 --vmax 15 --vstep 0.5

# UHF characterization at 430 MHz
python varactor.py --freq 430000 --vmin 2 --vmax 20

# 40m varactor with fine-grain voltage steps
python varactor.py --freq 7000 --vmin 0.5 --vmax 12 --vstep 0.25
```

## Output files

| File | Description |
|------|-------------|
| `{prefix}_varactor.png` | C(V) and Q(V) plots with tuning ratio |
| `{prefix}_varactor.txt` | Tabular: V, C (pF), Q, R_s (Ω) |
| `{prefix}_varactor.json` | Full numerical data |
