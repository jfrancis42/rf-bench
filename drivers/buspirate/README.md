# rf-bench-drivers-buspirate

Bus Pirate v3/v4/v5 driver for the [rf-bench](https://github.com/jfrancis42/rf-bench)
bench automation suite.  Provides a Python interface to the Bus Pirate's legacy BBIO1
binary serial protocol — SPI master, I2C master, UART passthrough, and peripheral
(power/pull-up) control — without requiring pyvisa or any other middleware.

**Supported hardware:**
- Bus Pirate v3 (all PCB revisions), v4 — USB CDC serial via FTDI/PIC, appears as `/dev/ttyUSB*`
- Bus Pirate v5 (RP2040) — two USB CDC ACM ports; connect to the **binary port** (`/dev/ttyACM1`)

---

## Installation

```bash
pip install rf-bench-drivers-buspirate
# or, for the full rf-bench suite:
pip install rf-bench
```

---

## Bus Pirate v5 — connecting to the right port

The v5 presents two serial ports:

| Port | Linux | macOS | Windows | Purpose |
|------|-------|-------|---------|---------|
| Terminal | `/dev/ttyACM0` | `/dev/cu.usbmodem*1` | lower COM# | Interactive text terminal |
| **Binary** | **`/dev/ttyACM1`** | **`/dev/cu.usbmodem*3`** | **higher COM#** | **Use this for the driver** |

Connect the driver to the **binary port**.  Connecting to the terminal port will
fail at binary mode entry with a descriptive error message.

Use `BusPirate.find_devices()` to locate the correct port automatically (see
[Port auto-detection](#port-auto-detection) below).

### Linux udev rules (optional — creates stable symlinks)

```
SUBSYSTEM=="tty", ENV{ID_VENDOR_ID}=="1209", ENV{ID_MODEL_ID}=="7332", \
    ENV{ID_USB_INTERFACE_NUM}=="00", SYMLINK+="buspirate-terminal"
SUBSYSTEM=="tty", ENV{ID_VENDOR_ID}=="1209", ENV{ID_MODEL_ID}=="7332", \
    ENV{ID_USB_INTERFACE_NUM}=="02", SYMLINK+="buspirate-binary"
```

After saving to `/etc/udev/rules.d/99-buspirate.rules` and re-plugging:

```python
with BusPirate("/dev/buspirate-binary") as bp:
    ...
```

---

## Bus Pirate v5 — one-time BPIO2 setup

The v5 driver uses the **BPIO2 FlatBuffers protocol** (not the legacy BBIO1).
BPIO2 must be activated once via the terminal port and saves across reboots.

```
# Connect to the terminal port (NOT the binary port)
screen /dev/ttyACM0 115200

# At the Bus Pirate prompt:
binmode
# Select:  2. BPIO2 flatbuffer interface
# Confirm: save as default when prompted (persists across reboots)

# Disconnect from screen: Ctrl-A then \
```

After this one-time setup, connect the driver to `/dev/ttyACM1` (the binary port)
and BPIO2 is active on every power-up.  No further terminal interaction required.

If BPIO2 is not yet active, the driver raises `BusPirateError` with the above
instructions so you know exactly what to do.

---

## Quick start

### Port auto-detection

```python
from rf_bench.buspirate import BusPirate

devices = BusPirate.find_devices()
# [{'port': '/dev/ttyACM1', 'model': 'Bus Pirate v5', 'role': 'binary'},
#  {'port': '/dev/ttyACM0', 'model': 'Bus Pirate v5', 'role': 'terminal'}]

for dev in devices:
    if dev['role'] in ('binary', 'combined'):
        with BusPirate(dev['port']) as bp:
            print(bp.identify())   # "Bus Pirate v5" or "Bus Pirate v3.6"
```

### SPI (e.g. ADF4351 synthesizer, AD9851 DDS)

```python
from rf_bench.buspirate import BusPirate

# v3/v4
with BusPirate("/dev/ttyUSB1") as bp:
    print(bp.identify())                           # "Bus Pirate v3.6"
    bp.spi_configure(speed_hz=1_000_000, cpol=0, cpha=0)
    word = 0x00_2D_80_00
    bp.spi_write([(word >> s) & 0xFF for s in (24, 16, 8, 0)])
    rx = bp.spi_transfer([0xFF, 0x00])
    bp.spi_exit()

# v5 — same API, different port
with BusPirate("/dev/ttyACM1") as bp:
    print(bp.identify())                           # "Bus Pirate v5"
    bp.spi_configure(speed_hz=1_000_000, cpol=0, cpha=0)
    rx = bp.spi_transfer([0x40, 0x00, 0x00])
    bp.spi_exit()
```

### I2C (e.g. Si5351 synthesizer, MCP9808 temperature sensor)

```python
from rf_bench.buspirate import BusPirate

with BusPirate("/dev/ttyUSB1") as bp:             # or /dev/ttyACM1 for v5
    bp.set_pullups(True)
    bp.i2c_configure(speed_hz=100_000)

    devices = bp.i2c_scan()                        # [0x1C, 0x60, ...]
    bp.i2c_write(0x60, [0x03, 0xFF])               # write Si5351 register 3
    raw = bp.i2c_read(0x1C, reg=0x05, length=2)   # read MCP9808 temperature
    temp_c = ((raw[0] & 0x1F) << 8 | raw[1]) / 16.0
    bp.i2c_exit()
```

### UART passthrough

```python
from rf_bench.buspirate import BusPirate

with BusPirate("/dev/ttyUSB1") as bp:             # or /dev/ttyACM1 for v5
    bp.uart_configure(baud=9600)
    bp.uart_write(b"AT\r\n")
    resp = bp.uart_read(length=64, timeout_s=1.0)
    bp.uart_exit()
```

### Peripheral control (power/pull-ups)

```python
with BusPirate("/dev/ttyUSB1") as bp:
    bp.set_power(True)       # enable 3.3V + 5V supply pins
    bp.set_pullups(True)     # enable I2C pull-up resistors (3.3V)
    bp.set_aux(True)         # drive AUX pin high
```

---

## API reference

### `BusPirate(port, baud=115200, timeout=2.0)`

Opens the serial port and enters binary mode.  Raises `BusPirateError` if
binary mode cannot be entered within 25 attempts.

| Method | Description |
|--------|-------------|
| `find_devices()` | Class method — scan serial ports, return list of Bus Pirates found |
| `identify()` | Return firmware version string, e.g. `"Bus Pirate v3.6"` or `"Bus Pirate v5"` |
| `set_power(on)` | Enable/disable on-board 3.3V + 5V supply pins |
| `set_pullups(on)` | Enable/disable on-board I2C pull-up resistors |
| `set_aux(high)` | Drive AUX pin high or low |
| `spi_configure(speed_hz, cpol, cpha, output_pushpull)` | Enter SPI mode |
| `spi_transfer(data)` | CS low → full-duplex transfer → CS high; returns rx bytes |
| `spi_write(data)` | CS low → write → CS high (rx discarded) |
| `spi_cs_low()` / `spi_cs_high()` | Manual CS control |
| `spi_raw_transfer(data)` | Transfer without CS toggle (16-byte chunks) |
| `spi_exit()` | Return to BBIO mode |
| `i2c_configure(speed_hz)` | Enter I2C mode |
| `i2c_write(addr, data)` | START → addr(W) → data → STOP |
| `i2c_read(addr, reg, length)` | Write reg addr, repeated START, read bytes |
| `i2c_read_raw(addr, length)` | Read without writing register address first |
| `i2c_scan()` | Return list of responding 7-bit addresses |
| `i2c_exit()` | Return to BBIO mode |
| `uart_configure(baud, data_bits, parity, stop_bits)` | Enter UART mode |
| `uart_write(data)` | Write bytes to TX |
| `uart_read(length, timeout_s)` | Read bytes from RX |
| `uart_exit()` | Return to BBIO mode |
| `reset()` | Return to interactive text terminal |
| `close()` | Reset + close serial port |

### SPI clock modes

| cpol | cpha | SPI mode | Bus Pirate config byte |
|------|------|----------|------------------------|
| 0    | 0    | Mode 0   | 0x8A (push-pull)       |
| 0    | 1    | Mode 1   | 0x88 (push-pull)       |
| 1    | 0    | Mode 2   | 0x8E (push-pull)       |
| 1    | 1    | Mode 3   | 0x8C (push-pull)       |

### SPI speeds

30 kHz · 125 kHz · 250 kHz · **1 MHz** · 2 MHz · 2.6 MHz · 4 MHz · 8 MHz

### I2C speeds

5 kHz · 50 kHz · **100 kHz** · 400 kHz

---

## Hardware connection

| Bus Pirate pin | Function |
|----------------|----------|
| MOSI           | SPI MOSI / I2C SDA |
| CLK            | SPI CLK  / I2C SCL |
| MISO           | SPI MISO |
| CS             | SPI CS (active-low by default) |
| AUX            | Auxiliary GPIO |
| +3.3V / +5V    | Supply output (controlled by `set_power()`) |
| GND            | Common ground |

---

## Compatibility notes

### v3/v4

- Binary mode is entered by sending `0x00` bytes until `BBIO1` is received (up to 25 attempts).
- Appears as `/dev/ttyUSB0` or `/dev/ttyUSB1` depending on other USB serial devices.
  Use `dmesg | grep ttyUSB` to find it.
- Some early v3 firmware revisions have stricter timing.  If binary mode entry fails,
  power-cycle the Bus Pirate and retry.

### v5

- Exposes two USB CDC ACM ports.  **Connect to the binary port** (`/dev/ttyACM1`).
  Connecting to the terminal port (`ttyACM0`) will be rejected.
- Uses the **BPIO2 FlatBuffers protocol** (native to v5), not the legacy BBIO1.
  BPIO2 must be activated once via the terminal — see
  [One-time BPIO2 setup](#bus-pirate-v5--one-time-bpio2-setup) above.
- Supports I2C, SPI, and UART (all three modes fully supported, unlike BBIO1
  on v5 which only supports SPI).
- `identify()` returns `"Bus Pirate v5 fw{major}.{minor}"` from BPIO2 status.
- USB VID/PID: 0x1209 / 0x7332.  Use `BusPirate.find_devices()` or the udev
  rules above to create stable symlinks.
- Appears as `/dev/ttyACM0` (terminal) and `/dev/ttyACM1` (binary) on Linux.

---

## License

GPL-3.0-or-later
