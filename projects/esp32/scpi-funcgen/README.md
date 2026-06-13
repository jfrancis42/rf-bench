# ESP32 SCPI Function Generator

Low-frequency arbitrary waveform generator using ESP32 internal 8-bit DAC with SCPI control over USB serial.

## Hardware

- **ESP32 DevKit** or compatible board
- **Output:** GPIO 25 (internal DAC1, 8-bit resolution)
- **Range:** 0 - 3.3V (limited by DAC voltage range)
- **No external components required**

## Specifications

| Parameter | Range | Resolution |
|-----------|-------|------------|
| Frequency | 0.1 Hz - 10 kHz | 0.1 Hz |
| Amplitude | 0 - 3.3V pk-pk | ~13 mV (8-bit) |
| DC Offset | -1.65V - +1.65V | ~13 mV (8-bit) |
| Waveforms | Sine, Square, Triangle, Sawtooth | — |
| Update Rate | 50 kHz | Fixed |
| Accuracy | ~2% typical | DAC INL/DNL limited |

## Waveforms

- **SINE:** 256-sample lookup table, low THD
- **SQUARE:** 50% duty cycle, fast edges (limited by DAC settling)
- **TRIANGLE:** Linear ramp up/down
- **SAWTOOTH:** Linear ramp up, instant flyback

## Installation

### Arduino IDE

1. Install ESP32 board support:
   - File → Preferences → Additional Board Manager URLs
   - Add: `https://raw.githubusercontent.com/espressif/arduino-esp32/gh-pages/package_esp32_index.json`
   - Tools → Board → Boards Manager → Search "ESP32" → Install

2. Configure:
   - Tools → Board → ESP32 Dev Module
   - Tools → Upload Speed → 921600
   - Tools → Port → (select your ESP32's serial port)

3. Upload `scpi-funcgen.ino`

### PlatformIO

```ini
[env:esp32dev]
platform = espressif32
board = esp32dev
framework = arduino
monitor_speed = 115200
```

## Usage

### Serial Connection

- **Baud rate:** 115200
- **Data bits:** 8
- **Parity:** None
- **Stop bits:** 1
- **Flow control:** None
- **Line ending:** CR, LF, or CRLF (all accepted)

### SCPI Commands

All commands are case-insensitive. Responses end with `\n`.

#### Identification

```
*IDN?
→ ESP32 SCPI Function Generator,v1.0,SN00001,FW1.0

*RST
→ OK
```

#### Waveform Selection

```
FUNC,<SIN|SQU|TRI|SAW>    Set waveform
FUNC?                      Query waveform
→ SIN | SQU | TRI | SAW
```

#### Frequency

```
FREQ,<hz>    Set frequency (0.1 - 10000 Hz)
FREQ?        Query frequency
→ <frequency in Hz, 3 decimal places>
```

#### Amplitude

```
VOLT,<volts>    Set amplitude pk-pk (0 - 3.3V)
VOLT?           Query amplitude
→ <amplitude in volts, 3 decimal places>
```

#### DC Offset

```
OFFS,<volts>    Set DC offset (-1.65 - +1.65V)
OFFS?           Query offset
→ <offset in volts, 3 decimal places>
```

#### Output Enable

```
OUTP,<0|1>    Disable/enable output (0=off, 1=on)
OUTP?         Query output state
→ 0 | 1
```

### Example Session

```
*IDN?
ESP32 SCPI Function Generator,v1.0,SN00001,FW1.0

FUNC,SIN
OK

FREQ,440
OK

VOLT,3.3
OK

OUTP,1
OK

FUNC?
SIN

FREQ?
440.000

OUTP,0
OK
```

## Python Control Example

```python
import serial
import time

# Open serial connection
ser = serial.Serial('/dev/ttyUSB0', 115200, timeout=1)
time.sleep(2)  # Wait for ESP32 boot

def scpi_write(cmd):
    ser.write(f"{cmd}\n".encode())
    response = ser.readline().decode().strip()
    print(f"{cmd} → {response}")
    return response

def scpi_query(cmd):
    return scpi_write(cmd)

# Configure and enable
scpi_write("*RST")
scpi_write("FUNC,SIN")
scpi_write("FREQ,1000")
scpi_write("VOLT,2.5")
scpi_write("OFFS,0")
scpi_write("OUTP,1")

# Query state
print(f"Waveform: {scpi_query('FUNC?')}")
print(f"Frequency: {scpi_query('FREQ?')} Hz")
print(f"Amplitude: {scpi_query('VOLT?')} V pk-pk")
print(f"Output: {scpi_query('OUTP?')}")

ser.close()
```

## Performance Notes

### Frequency Range

- **0.1 - 10 Hz:** Clean waveforms, good for low-frequency testing
- **10 Hz - 1 kHz:** Optimal range, low distortion
- **1 kHz - 10 kHz:** Usable, but square wave edges soften due to DAC settling time

### Waveform Quality

- **Sine:** ~256 samples per cycle at 195 Hz (50 kHz / 256). THD increases at higher frequencies due to fewer samples per cycle.
- **Square:** Rise/fall time ~1-2 μs (DAC settling + output stage)
- **Triangle/Sawtooth:** Linear within DAC INL spec (~±2 LSB)

### DAC Limitations

The ESP32 internal DAC is an 8-bit resistor ladder with:
- INL: ±2 LSB typical
- DNL: ±1 LSB typical
- Output impedance: ~30Ω
- No built-in output buffer

For critical applications, add an external op-amp buffer stage.

## Output Filter (Optional)

For cleaner output at higher frequencies, add a simple RC low-pass filter:

```
GPIO25 ────┬──── 1kΩ ────┬──── OUTPUT
           │             │
          GND          100nF
                        │
                       GND
```

Cutoff: ~1.6 kHz, removes DAC quantization steps.

## Troubleshooting

**No output / stuck at mid-scale:**
- Check `OUTP,1` was sent to enable output
- Verify GPIO 25 is not used by another peripheral
- Measure with a high-impedance probe (>1 MΩ) or buffer stage

**Frequency drift at high rates:**
- Normal for 10 kHz range due to sample quantization
- Use external frequency counter to verify actual output

**Serial commands not responding:**
- Check baud rate is 115200
- Try sending `*IDN?` first to verify communication
- Arduino serial monitor: set "Newline" line ending

**Distorted waveforms:**
- Square wave at 10 kHz will show ringing/overshoot (DAC settling limit)
- Sine at 10 kHz has only 5 samples per cycle (expected staircase)
- Add output filter for smoother waveforms

## Technical Details

### DDS Algorithm

The generator uses Direct Digital Synthesis (DDS):

1. **Phase accumulator:** 32-bit, wraps at 2³²
2. **Phase increment:** `(frequency × 2³²) / sample_rate`
3. **Table lookup:** Top 8 bits of accumulator = index into 256-sample LUT
4. **DAC output:** Scaled and offset sample written at 50 kHz rate

### Memory Usage

- **Program:** ~22 KB flash
- **RAM:** ~4 KB (mostly sine table and stack)
- **DAC ISR:** <10 μs execution time (safe for 50 kHz rate)

### Timer Configuration

- **Timer 0** at 1 MHz (80 MHz / 80 prescaler)
- **Alarm period:** 20 μs (50 kHz update rate)
- **ISR priority:** High (attached to L1 interrupt)

## Extensions

### Higher Frequency Range

Increase `SAMPLE_RATE` to 100 kHz or 200 kHz:
- Extends usable range to 20-40 kHz
- Test DAC ISR timing to ensure no overruns
- May need to reduce LUT size to 128 or 64 samples

### More Waveforms

Add pulse, noise, or arbitrary waveform support:
- Pulse: duty cycle parameter, similar to square
- Noise: LFSR or hardware RNG at each sample
- Arbitrary: user-uploaded 256-byte waveform table

### Sweep/Modulation

Implement frequency/amplitude sweeps in main loop:
- Linear/log frequency sweep
- AM/FM modulation from second waveform
- Burst mode with gate control

## License

Public domain. Use freely.

## Author

Created 2026-06-12 for rf-bench ESP32 projects.
