# Virtual Instrument Panels

Interactive Tkinter GUI panels for live readouts and control of bench instruments.
Run any panel directly; all support `--demo` for UI testing without hardware.

| Panel | File | Instrument | Notes |
|-------|------|-----------|-------|
| ET5406A+ DC Load | `et5406a_panel.py` | Yertai ET5406A+ | V/I/P/R readouts, mode/input control |
| SDG1062X Function Gen | `sdg1062x_panel.py` | Siglent SDG1062X | 2-ch freq/amplitude, waveform control |
| SPD3303X Power Supply | `spd3303x_panel.py` | Siglent SPD3303X-E | 3-ch V/I, tracking mode |
| SDM3045X Multimeter | `sdm3045x_panel.py` | Siglent SDM3045X | Large measurement display, all functions |
| SSA3032X Spectrum Analyzer | `ssa3032x_panel.py` | Siglent SSA3032X Plus | Live spectrum trace with embedded matplotlib |
| SDS2504X Oscilloscope | `sds2504x_panel.py` | Siglent SDS2504X Plus | 4-channel waveform display |

Panels for the IC-7300 and FT-891 radios live in their driver directories
(`drivers/icom/ic7300_panel.py`, `drivers/yaesu/ft891_panel.py`).

The Si5351 generator panel is at `projects/signal-sources/si5351-gen/si5351_panel.py`.
The RTL-SDR waterfall panel is at `drivers/rtlsdr/rtlsdr_panel.py`.
The Flipper Zero panel is at `drivers/flipper/flipper_panel.py`.
