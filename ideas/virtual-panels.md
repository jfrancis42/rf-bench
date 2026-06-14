## Virtual instrument panels

All panels are Tkinter-based, share a common architecture (state dataclass +
poll thread + UI refresh loop + thread-safe command queue + `--demo` mode +
safety shutdown on close), and live next to the driver they exercise.

| Panel | Path | Status | Working controls |
|-------|------|--------|------------------|
| SDG1062X | `drivers/siglent/sdg1062x_panel.py` | ✅ | Output on/off per ch, waveform, frequency, level |
| SDM3045X | `drivers/siglent/sdm3045x_panel.py` | ✅ | All measurement functions (VDC/VAC/IDC/IAC/2W/4W Ω/FREQ/DIODE/CONT) |
| SPD3303X | `drivers/siglent/spd3303x_panel.py` | ✅ | Output on/off per ch, tracking mode (INDEP/SERIES/PARA), V and I setpoints |
| SSA3032X | `virtual-instruments/ssa3032x_panel.py` | ✅ | Live spectrum trace; tracking gen on/off + level; markers; peak search |
| SDS2504X | `virtual-instruments/sds2504x_panel.py` | ✅ | 4-channel waveform plot; timebase / V/div / trigger / on-off; Vpp / freq / RMS readouts |
| ET5406A+ | `drivers/yertai/et5406a_panel.py` | ✅ | Mode (CC/CV/CP/CR/CC-CV), input on/off, set points; demo mode |
| IC-7300 | `drivers/icom/ic7300_panel.py` | ✅ | Mode, AGC, frequency entry, band buttons (160m–10m); blue/amber Icom theme |
| FT-891 | `drivers/yaesu/ft891_panel.py` | ✅ | Mode, AGC, preamp, attenuator, frequency, bands; green Yaesu theme |
| RTL-SDR | `drivers/rtlsdr/rtlsdr_panel.py` | ✅ | Live waterfall + FFT |
| Flipper | `drivers/flipper/flipper_panel.py` | ✅ | Multi-tab: Sub-GHz / IR / RFID-NFC / GPIO |
| Si5351 | `projects/signal-sources/si5351-gen/si5351_panel.py` | ✅ | 3-channel freq + drive strength; Tkinter alternative to the curses TUI |

All panels accept `--demo` (no hardware required) for UI testing and `--interval MS` for refresh rate. All panels that command outputs (PSU, load, function gen, radios) safely disable the output on window close.

---

