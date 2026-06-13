# ESP32 SCPI Distance Sensor

SCPI-controlled HC-SR04 ultrasonic distance sensor for automated test fixtures, tank level monitoring, and proximity detection.

## Hardware

- **ESP32 Dev Board** (any variant with USB serial)
- **HC-SR04 Ultrasonic Sensor**
  - VCC → 5V
  - GND → GND
  - TRIG → GPIO 25
  - ECHO → GPIO 26
- **Range:** 2–400 cm (±3 mm accuracy)
- **Measurement Rate:** ~10 Hz (single), ~1 Hz (averaged)

## Features

- **SCPI Interface** — Standard Commands for Programmable Instruments
- **Multiple Units** — Millimeters, centimeters, inches
- **Averaging Mode** — 10-sample average with outlier rejection (2σ filter)
- **Alarm Thresholds** — High/low configurable limits
- **USB Serial** — 115200 baud, plug-and-play

## SCPI Commands

| Command | Description | Example Response |
|---------|-------------|------------------|
| `*IDN?` | Identification string | `N0GQ,ESP32-SCPI-DISTANCE,HC-SR04,v1.0` |
| `*RST` | Reset to defaults | `OK` |
| `DIST:MEAS?` | Single measurement | `245.32 MM` |
| `DIST:CONT?` | Averaged measurement (10 samples) | `244.98 MM` |
| `DIST:UNIT,<MM\|CM\|IN>` | Set distance unit | `OK` |
| `DIST:UNIT?` | Query unit | `MM` |
| `DIST:ALAR:HIGH,<mm>` | Set high alarm (in mm) | `OK` |
| `DIST:ALAR:LOW,<mm>` | Set low alarm (in mm) | `OK` |
| `DIST:ALAR?` | Query alarm state | `0` (0=OK, 1=LOW, 2=HIGH) |

## Installation

### Arduino IDE

1. Install **ESP32 board support** via Board Manager
2. Select **ESP32 Dev Module** (or your specific board)
3. Open `scpi-distance.ino`
4. Upload to ESP32

### PlatformIO

```ini
[env:esp32dev]
platform = espressif32
board = esp32dev
framework = arduino
monitor_speed = 115200
```

## Usage

### Interactive (Serial Monitor)

```
*IDN?
→ N0GQ,ESP32-SCPI-DISTANCE,HC-SR04,v1.0

DIST:MEAS?
→ 123.45 MM

DIST:UNIT,CM
→ OK

DIST:MEAS?
→ 12.35 CM
```

### Python Example

```python
import serial

ser = serial.Serial('/dev/ttyUSB0', 115200, timeout=1)

def scpi_query(cmd):
    ser.write((cmd + '\n').encode())
    return ser.readline().decode().strip()

# Identify device
print(scpi_query('*IDN?'))

# Measure distance
print(scpi_query('DIST:MEAS?'))

# Set unit to inches and measure
scpi_query('DIST:UNIT,IN')
print(scpi_query('DIST:MEAS?'))

# Check alarm state
scpi_query('DIST:ALAR:LOW,50')   # 50mm low threshold
scpi_query('DIST:ALAR:HIGH,500') # 500mm high threshold
print(scpi_query('DIST:ALAR?'))  # 0=OK, 1=too close, 2=too far
```

### Bash Example

```bash
# Single measurement
echo "DIST:MEAS?" > /dev/ttyUSB0
cat /dev/ttyUSB0

# Averaged measurement
echo "DIST:CONT?" > /dev/ttyUSB0
cat /dev/ttyUSB0
```

## Applications

- **Test Fixture Positioning** — Verify DUT placement before RF measurements
- **Tank Level Monitoring** — Non-contact liquid level in chemical tanks
- **Garage Door Safety** — Detect obstructions before closing
- **Automated Sorting** — Height-based component binning
- **Z-Axis Control** — Feedback for CNC, pick-and-place, or probe positioning
- **Proximity Detection** — Trigger actions when object enters/exits zone

## Specifications

| Parameter | Value |
|-----------|-------|
| Range | 20–4000 mm |
| Resolution | ~3 mm |
| Accuracy | ±3 mm (typical) |
| Update Rate | ~10 Hz (single), ~1 Hz (averaged) |
| Interface | USB serial (CDC), 115200 baud |
| Power | 5V via USB |

## Notes

- **Temperature Dependency:** Speed of sound varies ~0.6 m/s per °C. Accuracy degrades in extreme temperatures. Add compensation if needed.
- **Beam Angle:** HC-SR04 has ~15° cone. Target must be perpendicular and larger than beam spot at distance.
- **Acoustic Noise:** Ultrasonic interference from nearby sensors or machinery may cause false readings. Space sensors ≥30 cm apart.
- **Surface Reflectivity:** Soft, angled, or porous surfaces (foam, fabric, liquids) may not reflect sufficient echo. Use smooth, flat targets.

## Troubleshooting

**No echo / timeout:**
- Check wiring (TRIG=GPIO25, ECHO=GPIO26)
- Verify 5V power to HC-SR04
- Ensure target is within 2–400 cm and perpendicular to sensor

**Unstable readings:**
- Use `DIST:CONT?` instead of `DIST:MEAS?` for averaging
- Ensure target is stationary during measurement
- Move away from ultrasonic noise sources (motors, PWM)

**Wrong distance:**
- Verify unit setting (`DIST:UNIT?`)
- Check for acoustic reflections from nearby surfaces
- Ensure clear line-of-sight to target

## License

MIT

## Author

JF8Call / N0GQ  
Part of the rf-bench instrument automation suite.
