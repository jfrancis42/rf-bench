# Relay Projects

Automation projects for the **XL9535 I2C relay board** controlled via
**Bus Pirate** I2C.

> ⚠️ **Hardware not yet connected** — relay board ordered 2026-06-03.
> Code is complete and waiting for hardware bring-up.

## Projects

| Project | What it does |
|---------|-------------|
| [`multidut/`](multidut/) | Step through up to 16 DUT sockets automatically; measure each with SDM or rf-impedance |
| [`solt/`](solt/) | Automated SOLT calibration for HP 8712B VNA — relay-switches OPEN/SHORT/LOAD/THRU |
| [`filterbank/`](filterbank/) | Band-switched LPF/BPF selector; auto-selects filter by frequency for transmitter-test |
| [`router/`](router/) | N×M RF/signal routing matrix; `router.connect(SOURCE, INSTRUMENT)` in one I2C write |
| [`normalize/`](normalize/) | 2-relay reference/DUT path switcher; eliminates cable swaps in scalar measurements |

## Hardware required

- Bus Pirate v3, v4, or v5 (I2C master)
- XL9535 relay board (4, 8, or 16 relay; I2C address 0x20–0x27)
- External 5V supply for relay coils (SPD3303X-E CH3 works)
- For RF path switching: Omron G6Y-1 or equivalent coaxial RF relays

## Quick start (once hardware arrives)

```bash
pip install rf-bench-drivers-buspirate

python -c "
from rf_bench.buspirate import BusPirate
from rf_bench.relay import XL9535
import time
with BusPirate('/dev/ttyACM1') as bp:
    bp.set_pullups(True)
    bp.i2c_configure(speed_hz=100_000)
    with XL9535(bp, i2c_addr=0x20, num_relays=8) as relay:
        relay.set(0, True); time.sleep(1); relay.all_off()
    bp.i2c_exit()
"
```
