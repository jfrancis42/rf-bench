# ESP32 SCPI RF Attenuator Controller

USB-controlled digital RF attenuator using PE4302 or HMC472 SPI attenuator ICs.

## Hardware

### Supported Attenuators

| Device | Range | Steps | Frequency | Interface |
|--------|-------|-------|-----------|-----------|
| PE4302 | 0-31.5 dB | 0.5 dB | DC-4 GHz | 6-bit SPI |
| HMC472 | 0-31 dB | 1 dB | DC-6 GHz | 5-bit SPI |

### Connections

| ESP32 Pin | Signal | Attenuator Pin |
|-----------|--------|----------------|
| GPIO 18 | CLK | CLK |
| GPIO 23 | DATA | DATA / SDI |
| GPIO 5 | LE | LE / CS |
| GND | GND | GND |
| 3.3V | VCC | VDD |

### PE4302 Pinout (8-MSOP)
```
   1: VDD     5: DB4
   2: DB0     6: DB5
   3: DB1     7: CLK
   4: DB2     8: LE
         (GND on bottom pad)
```

### HMC472 Pinout (8-MSOP)
```
   1: VDD     5: D3
   2: D0      6: D4
   3: D1      7: CLK
   4: D2      8: LE
         (GND on bottom pad)
```

## SCPI Commands

### Attenuation Control

| Command | Description | Example |
|---------|-------------|---------|
| `ATT,<db>` | Set attenuation (dB) | `ATT,10.5` |
| `ATT?` | Query current attenuation | Returns `15.5` |
| `ATT:STEP?` | Query step size | Returns `0.5` or `1.0` |
| `ATT:MAX?` | Query max attenuation | Returns `31.5` or `31.0` |

### Device Configuration

| Command | Description | Example |
|---------|-------------|---------|
| `ATT:DEV,<type>` | Set device type | `ATT:DEV,PE4302` |
| `ATT:DEV?` | Query device type | Returns `PE4302` |

### System Commands

| Command | Description |
|---------|-------------|
| `*IDN?` | Identification string |
| `*RST` | Reset to 0 dB |

## Usage Examples

### Python

```python
import serial

atten = serial.Serial('/dev/ttyUSB0', 115200, timeout=1)

# Set device type
atten.write(b'ATT:DEV,PE4302\n')
print(atten.readline().decode().strip())  # "OK"

# Set 15.5 dB
atten.write(b'ATT,15.5\n')
print(atten.readline().decode().strip())  # "OK"

# Query attenuation
atten.write(b'ATT?\n')
print(atten.readline().decode().strip())  # "15.5"

# Query step size
atten.write(b'ATT:STEP?\n')
print(atten.readline().decode().strip())  # "0.5"
```

### Command Line (Linux)

```bash
# Set device type
echo "ATT:DEV,HMC472" > /dev/ttyUSB0
cat /dev/ttyUSB0

# Set 20 dB
echo "ATT,20" > /dev/ttyUSB0
cat /dev/ttyUSB0

# Query attenuation
echo "ATT?" > /dev/ttyUSB0
cat /dev/ttyUSB0
```

## Building and Flashing

### Arduino IDE

1. Install ESP32 board support:
   - Add `https://espressif.github.io/arduino-esp32/package_esp32_index.json` to Additional Board Manager URLs
   - Install "esp32" by Espressif Systems

2. Select board: **ESP32 Dev Module**

3. Configure:
   - Upload Speed: 921600
   - CPU Frequency: 240MHz
   - Flash Frequency: 80MHz
   - Flash Mode: QIO
   - Flash Size: 4MB
   - Partition Scheme: Default 4MB with spiffs

4. Connect ESP32 via USB and upload

### PlatformIO

```ini
[env:esp32dev]
platform = espressif32
board = esp32dev
framework = arduino
monitor_speed = 115200
```

```bash
pio run -t upload
pio device monitor
```

## Application: Digital Step Attenuator Calibration

Use this controller with an RF generator and spectrum analyzer to calibrate stepped attenuators:

```python
import serial
import pyvisa

atten = serial.Serial('/dev/ttyUSB0', 115200)
rm = pyvisa.ResourceManager()
sa = rm.open_resource('TCPIP::192.168.1.10::INSTR')  # Your spectrum analyzer

# Calibrate 0-30 dB in 1 dB steps
print("dB,Expected,Measured,Error")
for db in range(0, 31):
    atten.write(f'ATT,{db}\n'.encode())
    atten.readline()  # Read "OK"
    
    # Measure power on SA
    power = float(sa.query(':CALC:MARK:Y?'))
    
    # Compare to 0 dB reference
    error = power - ref_power + db
    print(f"{db},{-db},{power:.2f},{error:.2f}")
```

## Integration with rf-bench

This controller can be integrated into the rf-bench ecosystem:

```python
from rf_bench.attenuator import SCPI_Attenuator

atten = SCPI_Attenuator('/dev/ttyUSB0', device='PE4302')
atten.set_attenuation(12.5)
print(f"Current: {atten.get_attenuation()} dB")
print(f"Step: {atten.step_size} dB")
print(f"Max: {atten.max_attenuation} dB")
```

## Performance

- **Switching speed**: < 1 ms per step
- **Accuracy**: ±0.5 dB (PE4302), ±1 dB (HMC472) per datasheet
- **Repeatability**: ±0.25 dB
- **Temperature coefficient**: ±0.02 dB/°C

## Troubleshooting

### No response from attenuator
- Check serial port and baud rate (115200)
- Verify USB cable supports data (not charge-only)
- Check ESP32 is enumerated: `ls /dev/ttyUSB*` or `ls /dev/ttyACM*`

### Incorrect attenuation
- Verify device type is set correctly: `ATT:DEV?`
- Check SPI wiring (CLK, DATA, LE)
- Ensure attenuator has power (3.3V)
- Measure DC voltage on attenuator data pins during operation

### Attenuation won't exceed 31 dB (HMC472)
- This is correct. HMC472 max is 31 dB (not 31.5).
- PE4302 goes to 31.5 dB.

## License

Public domain. Use freely.

## Author

Jeff Francis / N0GQ  
Part of the rf-bench project: https://github.com/jfrancis42/rf-bench
