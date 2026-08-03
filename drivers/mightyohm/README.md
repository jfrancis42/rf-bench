# rf-bench-drivers-mightyohm

MightyOhm Geiger Counter driver for rf-bench.

Supports the MightyOhm Geiger Counter kit (all versions) with FTDI USB serial interface.
Compatible with various GM tubes including SBM-20, LND-712, SI-29BG, J305, and SI-22G.

## Installation

```bash
pip install rf-bench-drivers-mightyohm
```

## Quick Start

```python
from rf_bench.mightyohm import MightyOhmGeiger

# Auto-detect FTDI adapter
with MightyOhmGeiger() as geiger:
    reading = geiger.read()
    print(f"CPM: {reading['cpm']}")
    print(f"Dose: {reading['dose_usv_hr']:.2f} µSv/hr")
    print(f"Mode: {reading['mode']}")
```

## Features

- Auto-detection of FTDI USB serial adapter
- Support for multiple GM tube types with correct conversion factors
- Streaming mode with callback support
- Statistical analysis over time periods
- Simple property-based access to current readings

## Usage Examples

### Single Reading

```python
from rf_bench.mightyohm import MightyOhmGeiger

geiger = MightyOhmGeiger()
reading = geiger.read()

print(f"Counts per second: {reading['cps']}")
print(f"Counts per minute: {reading['cpm']}")
print(f"Dose rate: {reading['dose_usv_hr']:.2f} µSv/hr")
print(f"Averaging mode: {reading['mode']}")  # SLOW, FAST, or INST
```

### Streaming with Callback

```python
def log_reading(reading):
    print(f"{reading['timestamp']:.0f}: {reading['cpm']} CPM, "
          f"{reading['dose_usv_hr']:.2f} µSv/hr")

with MightyOhmGeiger() as geiger:
    # Stream for 60 seconds
    geiger.stream(callback=log_reading, duration=60)
```

### Collect Multiple Readings

```python
# Collect 100 readings
readings = geiger.stream(count=100)

# Calculate average
avg_cpm = sum(r['cpm'] for r in readings) / len(readings)
print(f"Average CPM: {avg_cpm:.1f}")
```

### Statistical Analysis

```python
# Collect statistics for 5 minutes
stats = geiger.get_statistics(duration=300)

print(f"CPM: {stats['cpm']['mean']:.1f} ± {stats['cpm']['stdev']:.1f}")
print(f"Dose: {stats['dose_usv_hr']['mean']:.2f} ± {stats['dose_usv_hr']['stdev']:.2f} µSv/hr")
```

### Different Tube Types

```python
# Use LND-712 tube instead of default SBM-20
geiger = MightyOhmGeiger(tube_type='LND-712')

# Supported tubes: SBM-20, LND-712, SI-29BG, J305, SI-22G
```

## Protocol

The device outputs CSV data once per second over serial at 9600 baud:

```
CPS, #####, CPM, #####, uSv/hr, ###.##, SLOW|FAST|INST
```

**Fields:**
- `CPS`: Counts per second (current detection rate)
- `CPM`: Counts per minute (averaged)
- `uSv/hr`: Microsieverts per hour (dose rate)
- `Mode`: 
  - `SLOW` - 60 second averaging (default, CPM < 1000)
  - `FAST` - 5 second averaging (CPM > 1000)
  - `INST` - Instant mode (CPS > 255)

## Hardware

**MightyOhm Geiger Counter Kit:**
- ATtiny2313 microcontroller
- FTDI USB serial interface (FT232RL)
- GM tube support: SBM-20, LND-712, SI-29BG, J305, SI-22G
- 9600 baud, 8-N-1

**USB Interface:**
- VID:PID `0403:6001` (FTDI FT232R)
- Auto-detected as `/dev/ttyUSB*` on Linux
- Appears as `COMx` on Windows

## Conversion Factors

The driver supports multiple GM tube types with their respective CPM → µSv/hr conversion factors:

| Tube Type | Factor (×10⁴) | Notes |
|-----------|---------------|-------|
| SBM-20    | 57            | Default, Russian beta/gamma |
| LND-712   | 108           | US alpha/beta/gamma |
| SI-29BG   | 57            | Similar to SBM-20 |
| J305      | 153           | Chinese beta/gamma |
| SI-22G    | 57            | Russian beta/gamma |

Factors are scaled by 10,000 per the firmware implementation.

## API Reference

### MightyOhmGeiger

**Constructor:**
```python
MightyOhmGeiger(port=None, baudrate=9600, timeout=5.0, tube_type='SBM-20')
```

**Methods:**
- `read()` → Dict - Read one measurement
- `stream(callback=None, duration=None, count=None)` → List - Stream readings
- `get_statistics(duration=60)` → Dict - Collect statistics over time
- `close()` - Close serial connection

**Properties:**
- `cps` → int - Current counts per second
- `cpm` → int - Current counts per minute
- `dose_usv_hr` → float - Current dose rate (µSv/hr)
- `mode` → str - Current averaging mode

**Class methods:**
- `find_device()` → MightyOhmGeiger | None - Auto-detect device

## Requirements

- Python ≥ 3.8
- pyserial ≥ 3.5

## License

GPL-3.0-or-later

## Links

- [MightyOhm Geiger Counter](http://mightyohm.com/geiger)
- [rf-bench on GitHub](https://github.com/jfrancis42/rf-bench)
