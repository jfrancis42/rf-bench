# rf-bench-drivers-icom

Icom IC-7300 radio driver for bench automation. Part of the `rf-bench-drivers` family of packages.

Communicates with the IC-7300 via [Hamlib](https://hamlib.github.io/) `rigctld` over a plain TCP socket — no pyvisa, no direct CI-V, no external Python dependencies.

## Related packages

| Package | Namespace | Description |
|---------|-----------|-------------|
| `rf-bench-drivers-icom` | `rf_bench.icom` | This package — Icom IC-7300 driver |
| `rf-bench-drivers-yaesu` | `rf_bench.yaesu` | Yaesu FT-891 driver |
| `rf-bench-drivers-siglent` | `rf_bench.siglent` | Siglent instrument drivers (SSA3000X, SDG1000X, SDS2000X, SDM3000X, SPD3303X) |
| `rf-bench-drivers-utils` | `rf_bench.utils` | RF math utilities (power conversions, noise, IP3, etc.) |

## Hardware requirements

- **Icom IC-7300** connected via USB-B cable to `/dev/ttyUSB0` (or another serial port)
- **Hamlib** installed (`sudo pacman -S hamlib` / `sudo apt install hamlib` / `brew install hamlib`)
- `rigctld` running before you instantiate `IC7300`

### Starting rigctld

```bash
rigctld -m 3073 -r /dev/ttyUSB0 -s 115200
```

- Model `3073` is the IC-7300 in Hamlib 4.x (use `373` for Hamlib 3.x)
- Baud rate must match the radio: Menu → Set → Connectors → CI-V Baud Rate = 115200
- Default listen port is 4532 (TCP)

If you need to run two radios simultaneously, start the second `rigctld` on a different port (e.g. `--port 4533`) and pass that port to the driver.

## Install

```bash
pip install rf-bench-drivers-icom
```

## Virtual front panel

A Tkinter virtual instrument panel is included:

```bash
# Start rigctld first:
rigctld -m 3073 -r /dev/ttyUSB0 -s 115200 &

# Then run the panel:
python ic7300_panel.py                  # default localhost:4532
python ic7300_panel.py --demo           # simulated data, no hardware
python ic7300_panel.py --interval 500   # UI refresh rate in ms
```

**Features:**
- Large frequency display (formatted as MHz/kHz)
- Mode, passband, S-meter, AGC status tiles
- Working controls:
  - Mode buttons (USB/LSB/CW/AM/FM/RTTY)
  - AGC buttons (OFF/FAST/MID/SLOW)
  - Frequency entry (accepts Hz, kHz, MHz)
  - Quick band buttons (160m–10m)
- Demo mode for UI testing without hardware
- Thread-safe command queue
- Status feedback for all operations

## Usage

```python
from rf_bench.icom import IC7300

# Connect (rigctld must already be running on localhost:4532)
rig = IC7300()

# Or specify host/port explicitly
rig = IC7300("localhost", 4532)

# Context manager form (auto-closes)
with IC7300() as rig:
    rig.set_mode("usb")
    rig.set_frequency(14_200_000)   # Hz
    rig.set_agc("off")
    strength = rig.get_strength()
    print(f"Signal: {strength:.1f} dB")
```

## API

### Constructor

```python
IC7300(host="localhost", port=4532)
```

### Methods

| Method | Description |
|--------|-------------|
| `get_frequency()` | Returns VFO-A frequency in Hz (float) |
| `set_frequency(freq_hz)` | Sets VFO-A frequency in Hz |
| `get_mode()` | Returns `(mode_str, passband_hz)` — e.g. `("USB", 2400)` |
| `set_mode(mode, passband_hz=0)` | Sets mode; mode is `'usb'`, `'lsb'`, `'cw'`, `'cwr'`, `'am'`, `'fm'`, `'rtty'`; `passband_hz=0` uses radio default |
| `get_strength()` | Returns raw Hamlib STRENGTH float (dB re S9 for Hamlib 4.x; range approx -54 to +60) |
| `get_strength_settled(settle_s=0.5, samples=3)` | Waits `settle_s` seconds, then averages `samples` strength readings |
| `set_agc(mode)` | Sets AGC: `'off'`, `'fast'`, `'mid'`, `'slow'` — `'off'` is a true hardware bypass on IC-7300 |
| `get_agc()` | Returns AGC value: 0=off, 1=fast, 2=mid, 3=slow |
| `set_rf_gain(gain)` | Sets RF gain, 0.0–1.0 (1.0 = maximum) |
| `close()` | Closes the rigctld TCP connection |

The class also supports the context manager protocol (`with IC7300() as rig:`).

### Default passband widths

| Mode | Passband |
|------|----------|
| USB / LSB | 2400 Hz |
| CW / CWR | 500 Hz |
| AM | 6000 Hz |
| FM | 15000 Hz |
| RTTY | 500 Hz |

## Notes

- All frequency values are in Hz throughout the API.
- `get_strength()` returns Hamlib's raw STRENGTH value. For Hamlib 4.x with the IC-7300 this is dB relative to S9 (S9 = 0, S9+10 = 10, S1 ≈ −48). The exact calibration varies — use a signal generator and `get_strength_settled()` to build a calibration table.
- `set_agc("off")` achieves a true hardware AGC bypass on the IC-7300. This is not the case on all radios.
- `rigctld` must be running before you call `IC7300()`. The constructor connects immediately and will raise `ConnectionRefusedError` if rigctld is not listening.
- No external Python dependencies — pure stdlib (`socket`, `time`).

## License

GPL-3.0-or-later. See [LICENSE](LICENSE).
