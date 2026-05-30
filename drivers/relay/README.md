> ⚠️ **UNTESTED** — This implementation has not been verified against physical hardware.
> Code is complete but has not been bench-tested. Verify behavior before relying on output.

# rf-bench-drivers-relay

XL9535 16-bit I2C relay board driver for the
[rf-bench](https://github.com/jfrancis42/rf-bench) bench automation suite.

Drives XL9535, PCA9535, and TCA9535 I²C I/O expanders (identical register maps)
as found on common 8-relay and 16-relay breakout boards.  Connects via a
[Bus Pirate](https://github.com/jfrancis42/rf-bench-drivers-buspirate) as the I2C master.

---

## Installation

```bash
pip install rf-bench-drivers-relay
# installs rf-bench-drivers-buspirate as a dependency
```

Or for the full rf-bench suite:

```bash
pip install rf-bench
```

---

## Quick start

```python
from rf_bench.buspirate import BusPirate
from rf_bench.relay import XL9535

with BusPirate("/dev/ttyUSB1") as bp:        # or /dev/ttyACM1 for Bus Pirate v5
    bp.set_pullups(True)
    bp.i2c_configure(speed_hz=100_000)

    # Context manager ensures all_off() is called on exit
    with XL9535(bp, i2c_addr=0x20, num_relays=16) as relay:
        relay.set(0, True)          # energize relay 0
        relay.set(1, True)          # also energize relay 1
        relay.set(0, False)         # de-energize relay 0

        relay.close_only(3)         # all off, then energize relay 3 only

        relay.set_all(0x00FF)       # energize relays 0–7, de-energize 8–15

        state = relay.get_all()     # read back internal state (no I2C)
        print(f"relay state: 0x{state:04X}")

        relay.all_off()             # de-energize everything

    bp.i2c_exit()
```

---

## API reference

### `XL9535(bp, i2c_addr=0x20, active_high=True, num_relays=16)`

Configures the chip as all-outputs and de-energizes all relays.

| Parameter | Default | Description |
|-----------|---------|-------------|
| `bp` | — | `BusPirate` instance; I2C mode must be entered before construction |
| `i2c_addr` | `0x20` | 7-bit I2C address, 0x20–0x27 (set by A0/A1/A2 pins) |
| `active_high` | `True` | `True` = output HIGH energizes relay (ULN2803 boards); `False` = active-low |
| `num_relays` | `16` | Number of relays: 4, 8, or 16 |

| Method | Description |
|--------|-------------|
| `configure_outputs()` | Set all I/O pins as outputs; called by `__init__` |
| `all_off()` | De-energize all relays (safe state) |
| `set(relay_num, energize)` | Energize or de-energize one relay |
| `set_all(bitmask)` | Set all relays from 16-bit bitmask (bit N → relay N) |
| `close_only(relay_num)` | `all_off()` then energize exactly one relay |
| `get_all()` → `int` | Return current 16-bit relay state (no I2C read-back) |
| `__enter__` / `__exit__` | Context manager; `__exit__` calls `all_off()` |

`set()` and `close_only()` raise `XL9535Error` if `relay_num` is out of range.

---

## Hardware notes

### I2C address selection

The XL9535 I2C address is set by the A0, A1, A2 hardware pins on the relay board.
Most boards expose these as solder jumpers or pull-down resistors.

| A2 | A1 | A0 | Address |
|----|----|----|---------|
| 0  | 0  | 0  | 0x20 (default — all jumpers open) |
| 0  | 0  | 1  | 0x21 |
| 0  | 1  | 0  | 0x22 |
| 0  | 1  | 1  | 0x23 |
| 1  | 0  | 0  | 0x24 |
| 1  | 0  | 1  | 0x25 |
| 1  | 1  | 0  | 0x26 |
| 1  | 1  | 1  | 0x27 |

Up to 8 boards can coexist on one I2C bus.

### Power supply

Relay coils require a **separate power supply** — typically 5 V DC at 50–100 mA per
energized relay.  The Bus Pirate's on-board 5 V supply (150 mA total limit) is not
adequate for more than one or two relays.  Use a bench supply or a USB power module.

The XL9535 logic supply (VCC) can be 3.3 V or 5 V — check your board's silkscreen.
Enable Bus Pirate pull-ups (`bp.set_pullups(True)`) before entering I2C mode.

### Active-high vs. active-low

Most boards using a **ULN2803A** Darlington sink array are **active-HIGH**
(default `active_high=True`): driving the XL9535 output HIGH sinks current through
the ULN2803 and energizes the relay coil.

Some boards use direct NPN transistors with base resistors.  Check which topology
your board uses, and set `active_high=False` if the logic is inverted.
The driver handles the inversion transparently — `set(N, True)` always means
"energize relay N."

### RF relay warning

The HK19F and SRD-05VDC relays found on typical Chinese breakout boards are
**not suitable for RF signal switching above approximately 5 MHz**:

- High contact inductance and stray capacitance degrade insertion loss rapidly above HF
- No 50 Ω characteristic impedance control
- Contact surfaces corrode and produce intermittent bounce at RF frequencies

For RF bench automation, use the XL9535 board's transistor outputs to drive proper
**RF relays** mounted close to the RF path:

| Relay | Configuration | Bandwidth | Notes |
|-------|---------------|-----------|-------|
| Omron G6Y-1 | SPDT | 500 MHz | SMA-compatible footprint, 50 Ω |
| Omron G6Y-2 | DPDT | 500 MHz | same |
| TE OAR-SS-112DM | SPDT | 3 GHz | SMD coil, through-hole contacts |
| Axicom IM series | SPDT/DPDT | 1–6 GHz | SMD, low-insertion-loss |

Drive the RF relay coils from the XL9535 output transistors and route the RF signal
through the RF relay contacts with controlled-impedance coax to SMA connectors.

---

## Bus Pirate connection

| Bus Pirate pin | XL9535 board |
|----------------|--------------|
| MOSI (SDA) | SDA |
| CLK (SCL) | SCL |
| +3.3V or +5V | VCC (logic supply — check board) |
| GND | GND |

Use a separate supply for the relay coil VCC rail.  Do not back-drive the Bus Pirate
+5V pin with relay kickback — ensure the relay board has flyback diodes (most do).

---

## License

GPL-3.0-or-later
