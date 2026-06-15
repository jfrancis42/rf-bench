# rf-bench-drivers-fx2lafw

FX2LAFW-based logic analyzer driver for rf-bench. Supports "24MHz 8CH" Saleae-compatible logic analyzers using the fx2lafw firmware.

## Hardware

- **Channels:** 8 digital inputs
- **Sample rates:** 1, 2, 3, 4, 6, 8, 12, 16, 24 MHz
- **Protocol:** USB 2.0 (Cypress FX2)
- **Typical VID:PID:** 08a9:0014 (Saleae compatible)
- **Firmware:** fx2lafw (open source)

## Dependencies

Requires sigrok-cli and libsigrok:

```bash
sudo apt-get install sigrok-cli libsigrok-dev
```

## Installation

```bash
cd ~/Dropbox/build/rf-bench/drivers/fx2lafw
pip install -e .
```

## Quick Start

### Basic Capture

```python
from rf_bench.fx2lafw import FX2LAFWLogicAnalyzer

la = FX2LAFWLogicAnalyzer()

# Capture 1 second at 8 MHz on channels 0-3
samples = la.capture(
    channels=[0, 1, 2, 3],
    sample_rate=8e6,
    duration=1.0
)

# samples is a dict: {channel_num: numpy_bool_array}
print(f"Captured {len(samples[0])} samples on channel 0")

# Save to VCD format (open in GTKWave, PulseView, etc.)
la.save_vcd('capture.vcd', samples)
```

### Sample Rate Options

Valid sample rates (Hz):
- 1 MHz
- 2 MHz
- 3 MHz
- 4 MHz
- 6 MHz
- 8 MHz
- 12 MHz
- 16 MHz
- 24 MHz (maximum)

```python
# Capture at maximum rate
samples = la.capture(
    channels=[0, 1, 2, 3, 4, 5, 6, 7],
    sample_rate=24e6,
    num_samples=1_000_000  # 1M samples = 41.7 ms at 24 MHz
)
```

### Protocol Decode (Future)

Protocol decode methods are planned but not yet implemented:

```python
# UART decode (future)
decoded = la.decode_uart(samples, channel=0, baud=115200)

# SPI decode (future)
decoded = la.decode_spi(samples, clk=0, mosi=1, miso=2, cs=3)

# I2C decode (future)
decoded = la.decode_i2c(samples, scl=0, sda=1)
```

For now, use sigrok-cli directly for protocol decode or save to VCD and open in PulseView.

## Usage Patterns

### Pattern 1: Digital Bus Capture

```python
from rf_bench.fx2lafw import FX2LAFWLogicAnalyzer

la = FX2LAFWLogicAnalyzer()

# Capture SPI bus (4 channels: CLK, MOSI, MISO, CS)
samples = la.capture(
    channels=[0, 1, 2, 3],
    sample_rate=8e6,
    duration=0.1  # 100 ms
)

# Save for analysis
la.save_vcd('spi_capture.vcd', samples)
print("Open spi_capture.vcd in PulseView or GTKWave")
```

### Pattern 2: Trigger on Edge (Manual)

```python
import numpy as np

la = FX2LAFWLogicAnalyzer()

# Capture long duration
samples = la.capture(
    channels=[0, 1],
    sample_rate=8e6,
    duration=5.0
)

# Find rising edge on channel 0
ch0 = samples[0]
rising_edges = np.where((ch0[:-1] == False) & (ch0[1:] == True))[0]

print(f"Found {len(rising_edges)} rising edges")

if len(rising_edges) > 0:
    # Extract 1000 samples around first rising edge
    trigger_idx = rising_edges[0]
    pre_trigger = 200
    post_trigger = 800

    start = max(0, trigger_idx - pre_trigger)
    end = min(len(ch0), trigger_idx + post_trigger)

    triggered_samples = {
        ch: samples[ch][start:end] for ch in samples.keys()
    }

    la.save_vcd('triggered_capture.vcd', triggered_samples)
```

### Pattern 3: Measure Frequency

```python
import numpy as np

la = FX2LAFWLogicAnalyzer()

samples = la.capture(
    channels=[0],
    sample_rate=24e6,
    duration=1.0
)

# Count rising edges
ch0 = samples[0]
rising_edges = np.where((ch0[:-1] == False) & (ch0[1:] == True))[0]

frequency = len(rising_edges) / 1.0  # Hz
print(f"Frequency: {frequency:.2f} Hz")
```

### Pattern 4: Measure Pulse Width

```python
import numpy as np

la = FX2LAFWLogicAnalyzer()

samples = la.capture(
    channels=[0],
    sample_rate=24e6,
    duration=0.1
)

ch0 = samples[0]

# Find transitions
rising = np.where((ch0[:-1] == False) & (ch0[1:] == True))[0]
falling = np.where((ch0[:-1] == True) & (ch0[1:] == False))[0]

if len(rising) > 0 and len(falling) > 0:
    # Find first falling edge after first rising edge
    pulse_start = rising[0]
    pulse_end = falling[falling > pulse_start][0]

    pulse_width_samples = pulse_end - pulse_start
    pulse_width_seconds = pulse_width_samples / 24e6

    print(f"Pulse width: {pulse_width_seconds*1e6:.2f} µs")
```

## Integration with rf-bench Registry

The logic analyzers are pre-configured in `~/.rf-bench/instruments.yaml`:

```python
from rf_bench.instruments import Registry

registry = Registry()

# Get any available logic analyzer
la = registry.get('logic-analyzer')

# Get specific one by tag
la = registry.get('logic-analyzer', tag='primary')

# Use it
samples = la.capture([0,1,2,3], sample_rate=8e6, duration=1.0)
```

## VCD File Format

The `save_vcd()` method creates standard VCD files that can be opened in:

- **GTKWave** — Popular waveform viewer (`sudo apt-get install gtkwave`)
- **PulseView** — Sigrok's GUI with protocol decoders (`sudo apt-get install pulseview`)
- **Any text editor** — VCD is a text format

VCD header example:
```vcd
$date
  rf-bench fx2lafw capture
$end
$version
  rf_bench.fx2lafw 0.1.0
$end
$timescale
  41666 ps
$end
$scope module logic $end
$var wire 1 ! CH0 $end
$var wire 1 " CH1 $end
$upscope $end
$enddefinitions $end
#0
0!
0"
#42
1!
```

## Troubleshooting

### No device found

```python
FX2LAFWNotFoundError: No fx2lafw device found. Check USB connection.
```

**Solution:**
1. Check USB connection
2. Verify device is recognized: `lsusb | grep 08a9:0014`
3. Try manual device scan: `sigrok-cli --scan`
4. Install udev rules if needed (see sigrok documentation)

### sigrok-cli not found

```python
FX2LAFWError: sigrok-cli not found. Install with: sudo apt-get install sigrok-cli
```

**Solution:**
```bash
sudo apt-get install sigrok-cli libsigrok-dev
```

### Sample rate not supported

```python
ValueError: Sample rate 10 MHz not supported. Valid rates: 1 MHz, 2 MHz, ...
```

**Solution:**
Use one of the supported sample rates (1, 2, 3, 4, 6, 8, 12, 16, 24 MHz).

## Limitations

- **No hardware triggering** — Capture always starts immediately. Use software triggering in Python to extract interesting sections.
- **USB bandwidth** — At 24 MHz with 8 channels, capture duration is limited by USB buffer size.
- **Protocol decode not yet implemented** — Use sigrok-cli or PulseView for protocol analysis.
- **No streaming mode** — Captures are finite length (num_samples or duration).

## Future Enhancements

- [ ] Protocol decode (UART, SPI, I2C) via sigrok-cli
- [ ] Hardware trigger support (if available in device)
- [ ] Streaming capture mode
- [ ] Real-time display via matplotlib
- [ ] Direct libsigrok Python bindings (bypass sigrok-cli subprocess)

## API Reference

### FX2LAFWLogicAnalyzer

```python
la = FX2LAFWLogicAnalyzer(device=None)
```

**Methods:**

- `capture(channels, sample_rate=24e6, num_samples=None, duration=None)` — Capture logic data
  - Returns: `Dict[int, np.ndarray]` mapping channel → bool array

- `save_vcd(filename, samples, sample_rate=24e6)` — Save to VCD format

- `decode_uart(samples, channel, baud=115200, ...)` — Decode UART (not yet implemented)

- `decode_spi(samples, clk, mosi, miso, cs, ...)` — Decode SPI (not yet implemented)

- `decode_i2c(samples, scl, sda)` — Decode I2C (not yet implemented)

- `close()` — Close connection (no-op)

**Attributes:**

- `SAMPLE_RATES` — List of supported sample rates (Hz)

## Examples

See `examples/` directory (to be created) for complete working examples:
- `basic_capture.py` — Simple capture and VCD export
- `measure_frequency.py` — Count edges to measure frequency
- `pulse_width.py` — Measure pulse widths
- `trigger.py` — Software triggering

## License

MIT
