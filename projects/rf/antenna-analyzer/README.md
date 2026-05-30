# siglent-antenna-analyzer

Python CLI for analyzing antennas using a Siglent spectrum analyzer and an external reflection bridge. Sweeps HF/VHF/UHF/microwave amateur bands (160m–2.4 GHz), CB, aviation VHF, marine VHF/HF, FRS, GMRS, and MURS. Computes VSWR and return loss from an open-circuit calibration and generates a text report and multi-panel VSWR plot.

**No REFL software license required.** This tool drives the instrument entirely over SCPI/LAN using the standard tracking generator — it does not use Siglent's optional reflection measurement firmware add-on.

Tested with a **Siglent SSA 3032X Plus** and **Siglent RB3X25 reflection bridge**. Should work with other Siglent SSA models that have a tracking generator and SCPI/LAN support, and with other reflection bridges wired the same way (TG output → bridge input, bridge output → RF input, antenna at DUT port).

## Requirements

- Siglent SSA with tracking generator and SCPI/LAN enabled (tested: SSA 3032X Plus)
- Reflection bridge (tested: Siglent RB3X25)
- Python 3.10+
- [`rf-bench`](https://pypi.org/project/rf-bench/) — SSA3000X driver and RF math utilities
- `numpy`, `matplotlib`

```bash
pip install -r requirements.txt
```

**`rf-bench` note:** `antenna_analyzer.py` imports the `SSA3000X` driver and RF utilities
from the `rf_bench` package (`SSA3000X`, `rl_to_vswr`, `rl_to_vswr_v`, `format_freq`,
`nearest_rbw`). When running from a checked-out `siglent/` tree, the script automatically
finds the sibling `rf-bench/` directory via `sys.path`. If running standalone, install via
`pip install rf-bench`.

## Hardware Setup

```
[SSA Gen Out] ──→ [Reflection Bridge] ──→ [SSA RF In]
                         │
                      DUT Port
                         │
                      Antenna
```

The reflection bridge couples the reflected signal from the antenna back to the SSA's RF input. The SSA measures reflected power level; the software converts this to return loss and VSWR using an open-circuit calibration reference.

## Usage

### Normal run (calibration cached automatically)

```bash
python antenna_analyzer.py
```

On the **first run**, the program prompts you to connect an open circuit to the DUT port, sweeps the calibration, and saves it to `~/.calibration.npz`. On every subsequent run it loads that file automatically — no calibration prompt, straight to measurement.

### Force a new calibration

Use this after moving the bridge, swapping cables, or any other change to the measurement path:

```bash
python antenna_analyzer.py --calibrate
```

This sweeps a fresh open-circuit calibration and overwrites `~/.calibration.npz` before proceeding to measurement.

### Selective band sweep

```bash
python antenna_analyzer.py --bands 40m 20m 15m 10m
```

If the calibration file is missing bands requested here, those bands are measured without calibration and flagged in the report.

### Named calibration files

Keep separate calibration files for different bridge setups:

```bash
python antenna_analyzer.py --cal-file shack_bridge.npz
python antenna_analyzer.py --cal-file portable_bridge.npz --calibrate
```

### Skip calibration entirely (raw power levels only)

```bash
python antenna_analyzer.py --no-cal
```

VSWR values will be estimates based on raw reflected power, not referenced to a known 0 dB return-loss standard. Useful for quick relative comparisons.

### Band selection flags (combinable; default is `--hf`)

| Flag | Coverage |
|------|----------|
| `--hf` | 160m 80m 60m 40m 30m 20m 17m 15m 12m 10m **(default)** |
| `--cb` | 11m — CB (26.965–27.405 MHz, channels 1–40) |
| `--vhf` | 6m, 2m, 1.25m (219–225 MHz) |
| `--uhf` | 70cm (420–450), 33cm (902–928), 23cm (1240–1300), 13cm (2300–2450), 2.4ghz (2400–2484 MHz) |
| `--frs` | FRS (462.5–467.8 MHz, 22 channels) |
| `--gmrs` | GMRS (same sweep as `--frs`; shares 462.5–467.8 MHz) |
| `--murs` | MURS (151.820–154.600 MHz, 5 channels) |
| `--aviation` | Aviation VHF (108–137 MHz: nav 108–118 + comms 118–137) |
| `--marine-vhf` | Marine VHF (156.0–162.6 MHz: channels 1–88 + WX1–WX7) |
| `--marine-hf` | Marine HF — 8 ITU bands: 4/6/8/12/16/18/22/25 MHz |
| `--all` | All of the above |
| `--bands BAND ...` | Explicit list, overrides group flags |

Flags are combinable: `--hf --vhf` scans HF + 6m + 2m + 1.25m. `--calibrate` always sweeps **all** bands regardless of which bands are selected for measurement, so the calibration file is always complete.

### All options

```
--host HOST         Instrument IP address (default: 10.1.1.60)
--port PORT         SCPI TCP port (default: 5025)
--points N          Sweep points per band (default: 1001)
--calibrate         Recalibrate ALL bands, then measure selected bands
--calibrate --yes   Calibrate ALL bands then exit — no measurement (for automation)
--no-cal            Skip calibration entirely (overrides --calibrate)
--cal-file FILE     Calibration file path (default: ~/.calibration.npz)
--hf/--cb/--vhf/--uhf/--frs/--gmrs/--murs/--aviation/--marine-vhf/--marine-hf/--all
                    Band group selection (combinable; default: --hf)
--bands BAND ...    Explicit band list: 160m 80m marine4 60m marine6 40m
                      marine8 30m marine12 20m marine16 17m marine18 15m
                      marine22 12m marine25 11m 10m 6m aviation 2m murs
                      marine 1.25m 70cm frs 33cm 23cm 13cm 2.4ghz
--watch             Live retune mode: continuously re-sweep (use with --bands BAND)
--averages N        Average N sweeps per band for noise reduction (default: 1)
--quick             Use 201 sweep points instead of 1001 (faster, less resolution)
--no-narrow         Skip precision narrowing sweep around resonance
--max-vswr X        Add PASS/FAIL column for VSWR ≤ X threshold
--tg-level DBM      Tracking generator level in dBm (default: 0; range: -20 to 0)
--yes               Skip all interactive prompts (for scripting/automation)
--output PREFIX     Output filename prefix (default: antenna_analysis_YYYYMMDD_HHMMSS)
--csv               Also write per-frequency-point CSV (<prefix>.csv)
--compare FILE      Overlay a previous result JSON file on the plot
```

## Output

Each run produces several files:

**`<prefix>.txt`** — text report:
```
========================================================================
  HF ANTENNA ANALYSIS REPORT
  Generated : 2026-05-22 19:01:46
  Instrument: Siglent SSA 3032X Plus @ 10.1.1.60
  Calibration: Open-circuit reference (return loss)
========================================================================

Band      Resonant Freq     VSWR   Ret.Loss        2:1 BW  Assessment
---------------------------------------------------------------------
160m         1.9157 MHz   1.21:1     20.6 dB     200.0 kHz  Excellent
80m          3.7893 MHz   1.21:1     20.5 dB     500.0 kHz  Excellent
60m          5.3727 MHz   1.18:1     21.8 dB      73.0 kHz  Excellent
40m          7.1736 MHz   1.20:1     20.9 dB     300.0 kHz  Excellent
30m         10.1289 MHz   1.17:1     21.9 dB      50.0 kHz  Excellent
20m         14.2025 MHz   1.17:1     22.3 dB     350.0 kHz  Excellent
17m         18.1259 MHz   1.15:1     23.4 dB     100.0 kHz  Excellent
15m         21.2604 MHz   1.13:1     24.1 dB     450.0 kHz  Excellent
12m         24.9479 MHz   1.12:1     25.0 dB     100.0 kHz  Excellent
10m         28.9837 MHz   1.11:1     25.5 dB      1.70 MHz  Excellent
6m          51.9253 MHz   1.10:1     26.7 dB      4.00 MHz  Excellent
```

**`<prefix>.png`** — multi-panel VSWR vs. frequency plot:
- Blue trace: VSWR across the band
- Green fill: VSWR ≤ 1.5:1 (excellent zone)
- Gold fill: VSWR 1.5–2.0:1 (good zone)
- Orange dashed line: 2:1 SWR threshold
- Purple dotted lines: US sub-band boundaries (CW/Phone splits, FM segments)
- Red star: minimum VSWR point (uses narrow-sweep result when available)
- Gray dashed trace: reference run (when `--compare` is used)
- Title shows PASS/FAIL when `--max-vswr` is set

**`<prefix>.json`** — per-band freq/VSWR/RL arrays; load with `--compare` to overlay on a future plot.

**`<prefix>.csv`** — per-frequency-point CSV with band, freq_hz, freq_mhz, vswr, return_loss_db columns (written only with `--csv`).

**`~/.antenna_log.csv`** — persistent history log; one row per band per run (always appended).

![Sample output plot](sample_output.png)

## Calibration Details

The open-circuit calibration works by recording the reflected power with no load connected (open circuit = 100% reflection = 0 dB return loss). This establishes the reference level for each frequency point across each band, compensating for the frequency-dependent response of the reflection bridge.

Calibration data is saved as a numpy `.npz` file containing one trace array per band plus a JSON metadata header (timestamp, instrument host, sweep points, band list). It can be reused across sessions as long as the measurement path (bridge, cables, connectors) has not changed.

```
return_loss (dB)  = P_open (dBm) − P_antenna (dBm)
reflection_coeff  = 10^(−RL / 20)
VSWR              = (1 + Γ) / (1 − Γ)
```

| VSWR  | Return Loss | Reflected Power |
|-------|-------------|-----------------|
| 1.0:1 | ∞ dB        | 0%              |
| 1.5:1 | 14.0 dB     | 4%              |
| 2.0:1 | 9.5 dB      | 11%             |
| 3.0:1 | 6.0 dB      | 25%             |

## SCPI Notes

The instrument must have SCPI/LAN enabled (typically found under System → Interface on the SSA front panel). The program connects to TCP port 5025.

The software uses only standard SCPI commands and the built-in tracking generator. It does **not** require Siglent's optional REFL (reflection measurement) firmware license.

Tested with SSA 3032X Plus firmware. If trace reads return empty data, try changing `:TRAC:DATA? TRC1` to `:TRACE1:DATA?` in `get_trace()` — firmware versions differ on this command.

## License

GPL-3.0-or-later
