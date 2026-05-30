# rf-bench-drivers-siglent

Siglent instrument drivers for bench automation, part of the **rf-bench-drivers** family.

Provides SCPI-over-raw-TCP drivers for five Siglent bench instruments. No pyvisa or NI-VISA required — all instruments connect via a plain TCP socket to port 5025.

## Instruments

| Driver class | Instrument | Default IP | Key capabilities |
|---|---|---|---|
| `SSA3000X` | SSA3032X Plus spectrum analyzer | 10.1.1.60 | 9 kHz–3.2 GHz sweep, tracking generator, trace readback, RBW auto-select |
| `SDG1000X` | SDG1062X function generator | 10.1.1.55 | 2-channel, 60 MHz, sine/square/ramp, dBm-level API (50 Ω), EasyWave protocol |
| `SDS2000X` | SDS2354X Plus oscilloscope | 10.1.1.58 | Waveform capture, FFT-ready audio acquisition, PAVA measurements, built-in AWG, MSO digital channels (D0–D15) |
| `SDM3000X` | SDM3045X bench multimeter | 10.1.1.63 | DC/AC V/I, 2W/4W resistance, frequency, continuity, diode, multi-sample acquisition |
| `SPD3303X` | SPD3303X-E triple-output PSU | 10.1.1.56 | CH1/CH2: 0–32 V / 0–3.2 A CC/CV; CH3: fixed 2.5/3.3/5 V; series/parallel tracking |

All connect via **raw TCP/SCPI to port 5025**. No pyvisa, no NI-VISA, no GPIB required. Configure the static IP on each instrument via its front-panel Utility → LAN menu.

## Installation

```
pip install rf-bench-drivers-siglent
```

This automatically installs `rf-bench-drivers-utils` (RF math functions used internally by the SSA and SDG drivers).

## Quick start

```python
from rf_bench.siglent import SSA3000X, SDG1000X, SDS2000X, SDM3000X, SPD3303X

# Spectrum analyzer
ssa = SSA3000X("10.1.1.60")
ssa.enable_tracking_generator(tg_level_dbm=0)
ssa.setup_band(7_000_000, 7_300_000, points=1001)
ssa.single_sweep()
trace = ssa.get_trace()   # numpy array of dBm values
ssa.close()

# Function generator
sdg = SDG1000X("10.1.1.55")
sdg.set_sine(1, freq_hz=14_001_000, level_dbm=-20)
sdg.output_on(1)
sdg.output_off_all()
sdg.close()

# Oscilloscope
scope = SDS2000X("10.1.1.58")
voltages, sample_rate_hz = scope.capture_audio(channel=1, duration_s=2.0)
scope.close()

# Multimeter
dmm = SDM3000X("10.1.1.63")
v = dmm.measure_vdc()
r = dmm.measure_resistance()
dmm.close()

# Power supply
psu = SPD3303X("10.1.1.56")
psu.set_voltage(1, 5.0)
psu.set_current(1, 0.5)
psu.enable(1)
v = psu.measure_voltage(1)
psu.disable_all()
psu.close()
```

Context managers are supported on all drivers:

```python
with SSA3000X("10.1.1.60") as ssa:
    ssa.setup_band(144_000_000, 148_000_000)
    ssa.single_sweep()
    trace = ssa.get_trace()
```

## Virtual instrument panels

Three Tkinter virtual front panels with working controls are included:

```bash
# SDG1062X function generator panel
python sdg1062x_panel.py                   # default 10.1.1.55:5025
python sdg1062x_panel.py --demo            # simulated data, no hardware
python sdg1062x_panel.py --interval 500    # UI refresh rate in ms

# SPD3303X power supply panel
python spd3303x_panel.py                   # default 10.1.1.56:5025
python spd3303x_panel.py --demo            # simulated data, no hardware

# SDM3045X multimeter panel
python sdm3045x_panel.py                   # default 10.1.1.63:5025
python sdm3045x_panel.py --demo            # simulated data, no hardware
```

**Features:**
- Live instrument state display with appropriate formatting
- Working controls for all common operations (output on/off, mode selection, set points, etc.)
- Thread-safe command queue (UI callbacks queue commands executed by poll thread)
- Demo mode for UI testing without hardware
- Status bar with automatic timeout for operation feedback
- Safety shutdown: all outputs disabled on window close
- Input validation for all entry fields

**SDG1062X controls:** CH1/CH2 output on/off, waveform (SINE/SQUARE/RAMP), frequency (Hz/kHz/MHz), level (dBm/Vpp)  
**SPD3303X controls:** CH1/CH2/CH3 output on/off, tracking mode (INDEP/SERIES/PARA), voltage, current  
**SDM3045X controls:** Measurement function (VDC/VAC/IDC/IAC/2W Ω/4W Ω/FREQ/DIODE/CONT)

## Driver notes

### SSA3000X — spectrum analyzer

- Model tested: Siglent SSA3032X Plus (9 kHz to 3.2 GHz)
- `setup_band()` auto-selects RBW using the Siglent 1-3-10 step sequence
- `get_trace()` handles both ASCII CSV and IEEE 488.2 binary block response formats
- Firmware quirk: some versions use `:TRACE1:DATA?` instead of `:TRAC:DATA? TRC1` — subclass and override `get_trace()` if the trace comes back empty

### SDG1000X — function generator

- Model tested: Siglent SDG1062X (2-channel, 60 MHz)
- Uses Siglent EasyWave protocol (`C1:BSWV` / `C2:BSWV`), not standard IEEE SCPI
- All public methods use dBm (into 50 Ω) for levels; Vpp conversion is internal
- Always call `output_on()` to set `LOAD,50` — some firmware ignores the BSWV LOAD field

### SDS2000X — oscilloscope

- Model tested: Siglent SDS2354X Plus (500 MHz, firmware 5.4.x)
- `capture_audio()` handles the 5.4.x firmware bug where it returns 1000 display-buffer samples instead of deep memory — automatically retries once
- Waveform preamble (`:WAVeform:PREamble?`) returns a 346-byte binary WAVEDESC block, not ASCII
- MSO digital channels (D0–D15) via `capture_digital()` and `capture_all_digital()` — requires MSO hardware probe pod; **not yet physically tested**
- Built-in AWG available via `set_awg_sine()`, `set_awg_square()`, `set_awg_ramp()`, `set_awg_dc()`

### SDM3000X — bench multimeter

- Model tested: Siglent SDM3045X (4.5-digit)
- Capacitance and temperature measurement require SDM3055 or SDM3065X
- Use `configure_*()` + `read_multiple()` for efficient multi-sample acquisition

### SPD3303X — power supply

- Model tested: Siglent SPD3303X-E
- CH3 voltage is hardware-fixed (2.5 V / 3.3 V / 5 V front-panel switch); `set_voltage(3, ...)` raises `ValueError`
- CH1+CH2 tracking modes: `TRACKING_INDEPENDENT`, `TRACKING_SERIES` (up to 64 V), `TRACKING_PARALLEL` (up to 6.4 A)

## Dependencies

- **numpy** — used by SSA3000X for trace data and SDS2000X for waveform data
- **rf-bench-drivers-utils** — RF math (dBm/Vpp conversion, RBW selection) used internally by SSA3000X and SDG1000X

## Related packages

This package is part of the rf-bench-drivers family:

- `rf-bench-drivers-siglent` — this package (Siglent instrument drivers)
- `rf-bench-drivers-utils` — RF math utilities (required dependency)
- `rf-bench-drivers-icom` — Icom radio drivers (IC-7300 via Hamlib rigctld)
- `rf-bench-drivers-yaesu` — Yaesu radio drivers (FT-891 via Hamlib rigctld)

All four packages share the `rf_bench.*` namespace and can be installed independently or together.

## License

GPL-3.0-or-later
