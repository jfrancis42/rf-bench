> ⚠️ **UNTESTED** — This implementation has not been verified against physical hardware.
> Code is complete but has not been bench-tested. Verify behavior before relying on output.

# rf-bench-drivers-flipper

Flipper Zero USB driver for RF bench automation.  Part of the `rf_bench` namespace package.

PyPI: `rf-bench-drivers-flipper` · Import: `rf_bench.flipper` · License: GPL-3.0-or-later

## Hardware

| USB VID | USB PID | Linux device | Protocol |
|---------|---------|-------------|---------|
| 0x0483 | 0x5740 | `/dev/ttyACM0` | CLI (text) + RPC (protobuf) |

Connect via the single USB-C port.  The driver auto-detects by VID/PID.

## Installation

```bash
pip install rf-bench-drivers-flipper
```

Or for local editable development:

```bash
pip install -e rf-bench-drivers-flipper --break-system-packages
```

## Quick Start

```python
from rf_bench.flipper import FlipperZero, FlipperError
import time

# Auto-detect connected Flipper
with FlipperZero() as fz:
    print(fz.identify())

    # Sub-GHz carrier
    fz.subghz_tx_carrier(433_920_000)
    time.sleep(1)
    fz.subghz_stop()

    # RSSI at 433.92 MHz
    readings = fz.subghz_get_rssi(433_920_000, duration_s=0.5)
    print(f"RSSI: {readings}")

    # GPIO
    fz.gpio_set_mode("PA4", "output")
    fz.gpio_write("PA4", 1)
    val = fz.gpio_read("PA6")
```

## License

GPL-3.0-or-later
