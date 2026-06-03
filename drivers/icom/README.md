# rf-bench-drivers-icom

Icom IC-7300 and IC-9700 radio drivers for bench automation. Part of the `rf-bench-drivers` family of packages.

Communicates with the IC-7300 via [Hamlib](https://hamlib.github.io/) `rigctld` over a plain TCP socket — no pyvisa, no direct CI-V, no external Python dependencies.

## Radios supported

| Class | Radio | Bands | Modes |
|-------|-------|-------|-------|
| `IC7300` | Icom IC-7300 | HF + 6m (1.8–54 MHz) | USB, LSB, CW, CWR, AM, FM, RTTY |
| `IC9700` | Icom IC-9700 | 2m / 70cm / 23cm | USB, LSB, CW, CWR, AM, FM, DV (D-STAR) |

Both classes share the same core API (`get_frequency`, `set_frequency`, `get_mode`,
`set_mode`, `get_strength`, `set_agc`, `set_rf_gain`, `close`) for drop-in
substitution in bench scripts.

The IC-9700 adds VFO A/B selection, split/duplex, PTT, TX-side frequency and mode
control, and satellite operation helpers.

## Related packages

| Package | Namespace | Description |
|---------|-----------|-------------|
| `rf-bench-drivers-icom` | `rf_bench.icom` | This package — Icom IC-7300 driver |
| `rf-bench-drivers-yaesu` | `rf_bench.yaesu` | Yaesu FT-891 driver |
| `rf-bench-drivers-siglent` | `rf_bench.siglent` | Siglent instrument drivers (SSA3000X, SDG1000X, SDS2000X, SDM3000X, SPD3303X) |
| `rf-bench-drivers-utils` | `rf_bench.utils` | RF math utilities (power conversions, noise, IP3, etc.) |

## Hardware requirements

- Icom IC-7300 or IC-9700 connected via USB-B cable to `/dev/ttyUSB0` (or another serial port)
- **Hamlib** installed (`sudo pacman -S hamlib` / `sudo apt install hamlib` / `brew install hamlib`)
- `rigctld` running before instantiating the driver class

### Starting rigctld

**IC-7300 (USB):**
```bash
rigctld -m 3073 -r /dev/ttyUSB0 -s 115200
```

**IC-9700 (USB):**
```bash
rigctld -m 3081 -r /dev/ttyUSB0 -s 115200
```

**IC-9700 (LAN / built-in Ethernet, Hamlib ≥ 4.3):**
```bash
rigctld -m 3081 -r 192.168.1.10      # replace with your IC-9700's IP
```

IC-9700 LAN setup: Menu → Set → Network → WLAN/LAN: ON, note the IP address.
The IC-9700's CI-V-over-LAN uses UDP port 50001/50002; Hamlib ≥ 4.3 handles
this automatically when an IP address is passed to `--rig-file`.

Use `IC9700.rigctld_cmd()` to generate the correct command from Python:
```python
print(IC9700.rigctld_cmd("/dev/ttyUSB0"))       # USB
print(IC9700.rigctld_cmd("192.168.1.10"))        # LAN
print(IC9700.rigctld_cmd("/dev/ttyUSB1", rigctld_port=4533))  # second radio
```

| Radio | Hamlib model | Notes |
|-------|-------------|-------|
| IC-7300 | 3073 (Hamlib 4.x) / 373 (Hamlib 3.x) | CI-V baud: Menu → Set → Connectors → CI-V Baud Rate |
| IC-9700 | 3081 (Hamlib 4.x) | USB or LAN; default CI-V address 0xA2 |

Default rigctld listen port is 4532 (TCP).

To run both radios simultaneously, start a second `rigctld` on a different port:

```bash
rigctld -m 3073 -r /dev/ttyUSB0 -s 115200 --port 4532 &   # IC-7300 (USB)
rigctld -m 3081 -r 192.168.1.10       --port 4533 &        # IC-9700 (LAN)
```

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

---

## IC-9700 (`rf_bench.icom.IC9700`)

### Starting rigctld

```bash
rigctld -m 3081 -r /dev/ttyUSB0 -s 115200
```

### Usage

```python
from rf_bench.icom import IC9700, VFO_A, VFO_B

# Simple receive
with IC9700() as rig:
    rig.set_mode("fm")
    rig.set_frequency(145_500_000)
    print(rig.get_strength())

# Satellite cross-band operation (AO-91: 145.960 FM down / 435.250 FM up)
with IC9700() as rig:
    rig.set_satellite_mode(
        rx_freq_hz=145_960_000, rx_mode="FM",
        tx_freq_hz=435_250_000, tx_mode="FM",
    )
    rig.set_ptt(True)
    # ... transmit ...
    rig.set_ptt(False)
    rig.clear_satellite_mode()
```

### Core methods (identical API to IC7300)

| Method | Description |
|--------|-------------|
| `get_frequency()` | Active VFO frequency in Hz |
| `set_frequency(freq_hz)` | Set active VFO frequency in Hz |
| `get_mode()` | `(mode_str, passband_hz)` |
| `set_mode(mode, passband_hz=0)` | `'usb'`, `'lsb'`, `'cw'`, `'cwr'`, `'am'`, `'fm'`, `'dv'`, `'digi'` |
| `get_strength()` | Hamlib STRENGTH float (dB re S9) |
| `get_strength_settled(settle_s=0.5, samples=3)` | Averaged strength after settling |
| `set_agc(mode)` | `'off'`, `'fast'`, `'mid'`, `'slow'` |
| `get_agc()` | 0=off, 1=fast, 2=mid, 3=slow |
| `set_rf_gain(gain)` | 0.0–1.0 |
| `close()` | Releases PTT if held, then closes connection |

### IC-9700-specific methods

| Method | Description |
|--------|-------------|
| `get_vfo()` | Returns `'VFOA'` or `'VFOB'` |
| `set_vfo(vfo)` | Select `VFO_A` (main/downlink) or `VFO_B` (sub/uplink) |
| `get_split()` | `True` if split (duplex) is active |
| `set_split(enabled, tx_vfo=VFO_B)` | Enable/disable cross-band split |
| `get_tx_frequency()` | TX (uplink) VFO frequency in Hz |
| `set_tx_frequency(freq_hz)` | Set TX frequency (split must be enabled) |
| `get_tx_mode()` | `(mode_str, passband_hz)` for TX VFO |
| `set_tx_mode(mode, passband_hz=0)` | Set TX mode (split must be enabled) |
| `get_ptt()` | `True` if transmitting |
| `set_ptt(tx)` | Key (`True`) or unkey (`False`) the transmitter |
| `set_satellite_mode(rx_freq_hz, rx_mode, tx_freq_hz, tx_mode, ...)` | One-call satellite cross-band setup |
| `clear_satellite_mode()` | Release PTT and disable split |
| `update_doppler(rx_freq_hz, tx_freq_hz)` | Update both VFOs for Doppler correction |
| `band_of(freq_hz)` | Static: returns `'2m'`, `'70cm'`, `'23cm'`, or `'unknown'` |

### Module constants

```python
from rf_bench.icom import VFO_A, VFO_B   # "VFOA", "VFOB"
from rf_bench.icom import PTT_RX, PTT_TX  # 0, 1
```

### Satellite operation notes

- VFO A is the **downlink (receive)** VFO; VFO B is the **uplink (transmit)** VFO.
- Always call `clear_satellite_mode()` or use the context manager — `close()` releases PTT automatically.
- For real-time Doppler correction during a pass, call `update_doppler()` every 1–2 seconds with the Doppler-shifted frequencies computed from the satellite's TLE and your GPS position.  The `radio/doppler/doppler.py` project integrates GPS and Hamlib for this purpose.

---

## Notes (both radios)

- All frequency values are in Hz throughout the API.
- `get_strength()` returns Hamlib's raw STRENGTH (dB re S9 for Hamlib 4.x; range approx −54 to +60). Build a calibration table with a signal generator and `get_strength_settled()`.
- `set_agc("off")` is a true hardware bypass on both the IC-7300 and IC-9700.
- `rigctld` must be running before instantiating either class; the constructor connects immediately.
- No external Python dependencies — pure stdlib (`socket`, `time`).

## License

GPL-3.0-or-later. See [LICENSE](LICENSE).
