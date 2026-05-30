> ⚠️ **UNTESTED** — This implementation has not been verified against physical hardware.
> Code is complete but has not been bench-tested. Verify behavior before relying on output.

# rf-bench-band-occupancy

**GitHub:** https://github.com/jfrancis42/rf-bench-band-occupancy

Continuous spectrum waterfall logger using the SSA3032X Plus. Records SSA sweeps over time,
builds a waterfall image, and saves data as `.npz` archives for offline analysis. Supports
triggered narrow-band captures when a peak exceeds a threshold. Multi-band cycling mode
visits multiple frequency ranges in sequence.

## Hardware

| Instrument | Role |
|-----------|------|
| Siglent SSA3032X Plus (10.1.1.60) | Spectrum analyzer — continuous sweep |

No external connections needed beyond the SSA antenna input.

## Usage

```
python band_occupancy.py --band BAND [options]
```

### Predefined bands

`hf40`, `hf20`, `hf15`, `hf10`, `vhf2m`, `uhf70cm`, `70cm_repeaters`, and custom via
`--start`/`--stop`.

### Options

| Flag | Default | Description |
|------|---------|-------------|
| `--band NAME` | hf20 | Predefined band name |
| `--start KHZ` | — | Custom start frequency (kHz) |
| `--stop KHZ` | — | Custom stop frequency (kHz) |
| `--duration S` | 3600 | Total recording duration (seconds) |
| `--dwell S` | 60 | Seconds per band per cycle (multi-band mode) |
| `--threshold DBM` | −90 | Trigger threshold for narrow-band capture |
| `--points N` | 601 | SSA sweep points |
| `--averages N` | 1 | SSA trace averages per sweep |
| `--bands NAME,...` | — | Multi-band cycling (comma-separated list) |
| `--plot FILE.npz` | — | Offline: regenerate waterfall from saved file |
| `--ssa-host HOST` | 10.1.1.60 | SSA IP address |
| `--prefix TEXT` | timestamped | Output filename prefix |

### Examples

```bash
# Log 20m band for 2 hours
python band_occupancy.py --band hf20 --duration 7200

# Multi-band cycling: 40m, 20m, 15m, 10m
python band_occupancy.py --bands hf40,hf20,hf15,hf10 --duration 3600 --dwell 30

# 2m repeater monitor with triggered captures
python band_occupancy.py --band vhf2m --threshold -95 --duration 3600

# Regenerate waterfall from saved data (no instrument needed)
python band_occupancy.py --plot 20260101_120000_hf20.npz
```

## Output files

| File | Description |
|------|-------------|
| `{prefix}_{band}.npz` | Time × frequency matrix + metadata |
| `{prefix}_{band}_waterfall.png` | Waterfall plot (inferno colormap) |
| `{prefix}_{band}.txt` | Summary statistics |
| `{prefix}_triggered_NNNNNN.npz` | Triggered narrow-band captures |

## Data format

The `.npz` archive contains:
- `times` — timestamps (seconds since start)
- `traces` — 2D array [time × frequency] in dBm
- `freqs` — frequency array (Hz)
- `metadata` — JSON string with band name, start/stop, date, instrument info
