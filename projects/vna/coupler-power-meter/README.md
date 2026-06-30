# coupler-power-meter — Absolute-dBm calibration via coupler + SSA xref

Build a per-frequency offset that converts VNA S21 readings to
absolute dBm using a directional coupler routed to an SSA.

**⚠ Untested against hardware.**

## Setup

```
SDG ─── coupler ─┬─ SSA   (coupled port → calibrated dBm marker)
                 └─ VNA   (through arm → S21 relative dB)
```

## Usage

```bash
python coupler_power_meter.py --start 1 --stop 1000 --n 31 \
    --coupler-db 10 --ssa-host 10.1.1.60 --output coupler.json
```

## Output

JSON: per-frequency `vna_db`, `ssa_dbm`, `through_dbm`,
`offset_db`. Add `offset_db` to NanoVNA S21 dB to get absolute dBm.

## Flags

- `--vna`, `--port`, `--host`
- `--ssa-host`, `--ssa-port`
- `--coupler-db` — coupler factor (10 for a 10-dB coupler)
- `--start MHZ` / `--stop MHZ` / `--n`
- `--output FILE.json`
