# rf-bench-drivers-yertai

Yertai ET5406A+ programmable DC load driver for the `rf_bench` bench automation framework.

200 W / 120 V / 20 A. USB connection via CH340 serial adapter. Wrapper around the upstream `philpagel/ET54.py` library with a simplified API and automatic CH340 detection.

## Install

```bash
pip install rf-bench-drivers-yertai
```

## Usage

```python
from rf_bench.yertai import ET5406A

with ET5406A() as load:       # auto-detects CH340 adapter
    load.CC_mode(1.0)         # 1 A constant current
    load.on()
    v, i, p, r = load.read_all()
    print(f"{v:.3f} V  {i:.3f} A  {p:.3f} W")
    load.off()
```

## Virtual front panel

A Tkinter virtual instrument panel with working controls is included:

```bash
python et5406a_panel.py                    # auto-detects CH340 adapter
python et5406a_panel.py --port /dev/ttyUSB0
python et5406a_panel.py --demo             # simulated data, no hardware
python et5406a_panel.py --interval 3000    # UI refresh rate in ms
```

**Features:**
- Live V/I/P/R readouts with 3-decimal precision
- Mode badge (CC/CV/CP/CR/CC-CV), input state (ON/OFF), protection status
- Working controls:
  - Mode selection (CC/CV/CP/CR/CC-CV) with set-point entry
  - Input relay on/off
  - Safety OFF button (immediate disable)
- Thread-safe command queue (UI callbacks queue commands executed by poll thread)
- Demo mode cycles through all operating modes every ~8 seconds
- Status bar with automatic timeout for operation feedback
- Safety shutdown: attempts to disable load input on window close
- Controls disabled in demo mode to prevent confusion

**Note:** Connected to greybox (10.1.0.16) at `/dev/ttyUSB0`. To view the panel remotely: `ssh -X 10.1.0.16 python /home/jfrancis/Dropbox/build/rf-bench/rf-bench-drivers-yertai/et5406a_panel.py`

## Acknowledgments

This driver wraps the [ET54 library](https://github.com/philpagel/ET54.py) by Philipp Pagel, providing a simplified API with CH340 auto-detection.

## License

GPL-3.0-or-later
