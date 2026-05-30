# rf-bench-drivers-yaesu

Yaesu FT-891 radio driver for bench automation. Part of the `rf-bench-drivers` family of
packages that share the `rf_bench.*` namespace.

This package provides a Hamlib rigctld TCP client for the Yaesu FT-891 transceiver,
with an API intentionally compatible with the IC-7300 driver (`rf-bench-drivers-icom`)
for drop-in substitution in automated test scripts.

## Hardware requirements

- Yaesu FT-891 connected via USB-B cable to the host PC
- Hamlib 4.x installed (`sudo apt install libhamlib-utils` or build from source)
- rigctld running before any test starts:

```
rigctld -m 1036 -r /dev/ttyUSB0 -s 38400 &
```

The FT-891's CAT baud rate is set in **Menu 031 (CAT RATE)**; factory default is 38400.
The `-s` flag must match the menu setting.

If you are also running an IC-7300 on port 4532, run the FT-891 rigctld on a different port:

```
rigctld -m 1036 -r /dev/ttyUSB1 -s 38400 -t 4533 &
```

Then connect with `FT891("localhost", 4533)`.

## Installation

```
pip install rf-bench-drivers-yaesu
```

No external dependencies — uses only the Python standard library (`socket`, `math`, `time`).

## Virtual front panel

A Tkinter virtual instrument panel is included:

```bash
# Start rigctld first:
rigctld -m 1036 -r /dev/ttyUSB0 -s 38400 &

# Then run the panel:
python ft891_panel.py                   # default localhost:4532
python ft891_panel.py --demo            # simulated data, no hardware
python ft891_panel.py --interval 500    # UI refresh rate in ms
```

**Features:**
- Large frequency display (formatted as MHz/kHz)
- Mode, passband, S-meter, AGC, preamp, attenuator status tiles
- Working controls:
  - Mode buttons (USB/LSB/CW/AM/FM/RTTY/PKT-U)
  - AGC buttons (OFF/FAST/MID/SLOW)
  - Preamp buttons (IPO/AMP1)
  - Attenuator buttons (OFF/6 dB/12 dB)
  - Frequency entry (accepts Hz, kHz, MHz)
  - Quick band buttons (160m–10m)
- Demo mode for UI testing without hardware
- Thread-safe command queue
- Status feedback for all operations
- Yaesu green color theme

## Usage

```python
from rf_bench.yaesu import FT891, PREAMP_OFF, PREAMP_AMP1

# Connect (defaults to localhost:4532)
rig = FT891()

# Core interface — identical to IC7300
rig.set_frequency(14_200_000)          # Hz
rig.set_mode("usb")                    # 'usb','lsb','cw','cwr','am','fm','rtty'
rig.set_agc("slow")                    # 'off','fast','mid','slow'
strength = rig.get_strength()          # raw Hamlib STRENGTH value
strength = rig.get_strength_settled(settle_s=0.5, samples=3)
rig.set_rf_gain(1.0)                   # 0.0–1.0
mode, passband = rig.get_mode()        # e.g. ('USB', 2400)
freq = rig.get_frequency()             # Hz
rig.close()

# Context manager
with FT891() as rig:
    rig.set_frequency(7_100_000)
    print(rig.get_strength_settled())

# FT-891-specific: preamp / IPO control
rig.set_preamp(PREAMP_OFF)    # IPO engaged — preamp bypassed (strong-signal tests)
rig.set_preamp(PREAMP_AMP1)   # AMP1 active (~10 dB gain, MDS/sensitivity tests)
level = rig.get_preamp()      # 0 = IPO/off, 1 = AMP1

# FT-891-specific: front-end attenuator
rig.set_att(0)    # off
rig.set_att(6)    # 6 dB
rig.set_att(12)   # 12 dB
att = rig.get_att()
```

## AGC caveat

`set_agc("off")` is **not a true bypass** on the FT-891. Hamlib maps AGC=0 to the
slowest AGC time constant. The FT-891 has no hardware AGC-off path. For absolute
signal level measurements, use `set_agc("slow")` combined with `set_rf_gain()` and
verify linearity empirically.

This differs from the IC-7300, where `set_agc("off")` engages a true hardware bypass.

## STRENGTH scale

The Hamlib STRENGTH value returned by `get_strength()` / `get_strength_settled()` is
specific to the FT-891 + Hamlib version combination and is **not directly comparable**
to IC-7300 readings. Run a separate S-meter calibration sweep to map STRENGTH to dBm
for each rig.

## Related packages

| Package | Namespace | Description |
|---------|-----------|-------------|
| `rf-bench-drivers-icom` | `rf_bench.icom` | Icom IC-7300 driver |
| `rf-bench-drivers-siglent` | `rf_bench.siglent` | Siglent instrument drivers (SSA, SDG, SDS, SDM, SPD) |
| `rf-bench-utils` | `rf_bench.utils` | RF math utilities (power conversion, noise, IP3, etc.) |

## License

GPL-3.0-or-later. See [LICENSE](LICENSE).
