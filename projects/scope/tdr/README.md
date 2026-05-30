# siglent-tdr

Time-Domain Reflectometer. Launches a fast step edge down a coaxial cable and
measures round-trip echo delay to locate impedance discontinuities (bad connectors,
kinks, shorts, opens, water ingress). X-axis displayed in meters.

## Hardware required

- Siglent SDS2504X Plus (LAN, `10.1.1.58`)
- SMA T-splitter (or BNC T-connector)
- For `--source sdg` (recommended): Siglent SDG1062X (LAN, `10.1.1.55`)
- The cable under test

## Cable setup

```
Source ──── SMA T-splitter ─┬─── CH1 probe (monitor launch edge + reflections)
                             └─── Coax cable under test ──── open / short / load
```

## Generator choice

| | SDG (default) | AWG |
|---|---|---|
| Rise time | ~3.5 ns (60 MHz) | ~14 ns (25 MHz) |
| Resolution at VF=0.66 | ~35 cm | ~138 cm |
| **Recommendation** | **Use SDG for TDR** | Emergency fallback only |

The SDG's faster edge gives ~4× better spatial resolution. Use `--source awg` only if
no SDG is available and fault location precision is not critical.

## Usage

```bash
# Default: SDG, RG-58 (VF=0.66), 100 m max length
python tdr.py

# Named cable type preset
python tdr.py --cable-type lmr400         # VF=0.85, LMR-400
python tdr.py --cable-type rg213          # VF=0.66, RG-213

# Custom velocity factor
python tdr.py --vf 0.82 --max-length-m 200

# More averaging for noisy cables
python tdr.py --averages 32

# AWG source (lower resolution)
python tdr.py --source awg
```

## Cable type presets

| Flag | VF | Cable |
|------|----|-------|
| `rg58` (default) | 0.66 | RG-58, RG-8X |
| `rg8` | 0.66 | RG-8, RG-213 |
| `lmr400` | 0.85 | LMR-400 |
| `lmr240` | 0.84 | LMR-240 |
| `custom` | `--vf` value | User-specified |

## Output files

| File | Contents |
|------|----------|
| `<prefix>_tdr.png` | TDR trace: voltage vs distance (meters) with fault markers |
| `<prefix>_tdr.csv` | distance_m, voltage columns |
| `<prefix>_tdr.txt` | Detected fault locations and reflection types |

## Interpreting the trace

- **Positive step** after the launch edge: open circuit (higher impedance)
- **Negative step** after the launch edge: short circuit or impedance decrease
- **Partial reflections**: impedance changes (connector, splice, moisture)
- No echo until end: matched termination (cable is correct impedance)

## Dependencies

```
rf-bench >= 0.2.0
numpy >= 1.20
matplotlib >= 3.4
```
