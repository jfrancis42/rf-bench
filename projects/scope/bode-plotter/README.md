# siglent-bode-plotter

Bode plot tool for the Siglent SDS2504X Plus oscilloscope. Sweeps gain (dB) and phase (°)
versus frequency across any linear DUT and generates a two-panel log-frequency plot.

Uses two-channel FFT phase extraction from `rf_bench.utils.gain_phase_from_fft`.

## Hardware required

- Siglent SDS2504X Plus (LAN, `10.1.1.58`)
- For `--source awg` (default): no extra hardware — uses scope's built-in AWG
- For `--source sdg`: Siglent SDG1062X (LAN, `10.1.1.55`)

## Cable setup

```
Source ──┬─── BNC T ─── CH1 probe (reference)
         └─── DUT input
                DUT output ─── CH2 probe
```

Source is either:
- **AWG** ("Gen Out" BNC on scope front panel) — default, no SDG needed, 25 MHz max
- **SDG CH1** — required above 25 MHz, 60 MHz max

## Generator options

| | AWG | SDG |
|---|---|---|
| Max frequency | 25 MHz | 60 MHz |
| Phase coherence | Yes (same instrument) | No (separate; negligible for most work) |
| Extra hardware | None | SDG1062X + BNC cable |
| Best for | Audio filters, op-amp circuits, speaker crossovers | RF filters, HF amplifiers |

## Usage

```bash
# Audio-frequency filter (AWG, 10 Hz–1 MHz)
python bode_plotter.py

# Full audio band explicitly
python bode_plotter.py --start 20 --stop 20000 --points 200

# HF using SDG (up to 10 MHz)
python bode_plotter.py --source sdg --start 100000 --stop 10000000

# Lower drive level (fragile DUT)
python bode_plotter.py --level -20

# Fixed capture duration (override auto-heuristic)
python bode_plotter.py --duration-s 0.05

# Linear frequency spacing (useful for resonance zoom)
python bode_plotter.py --lin-freq --start 900 --stop 1100 --points 100

# Custom output prefix
python bode_plotter.py --output my_filter_20250526
```

## Output files

| File | Contents |
|------|----------|
| `<prefix>_bode.png` | Two-panel Bode plot: gain (dB) + phase (°) vs frequency (log scale) |
| `<prefix>_bode.csv` | freq_hz, gain_db, phase_deg |
| `<prefix>_bode.txt` | Summary: –3 dB frequency, phase at –3 dB point |

## Dependencies

```
rf-bench >= 0.2.0
numpy >= 1.20
matplotlib >= 3.4
```

Install: `pip install rf-bench numpy matplotlib --break-system-packages`

## Notes

- Capture duration is auto-selected: 20 complete cycles per frequency (slower at low Hz)
- At 10 Hz, each point takes ~2 s; a 100-point sweep from 10 Hz–1 MHz takes ~3–5 min
- Phase accuracy degrades at high frequencies when cable delays are not calibrated out
- Ctrl+C saves partial results and exits cleanly
