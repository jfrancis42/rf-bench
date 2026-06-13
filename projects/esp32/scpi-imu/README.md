# SCPI IMU Controller for ESP32

Network-accessible 6-axis IMU (Inertial Measurement Unit) using MPU6050 accelerometer + gyroscope with SCPI control over TCP/IP.

## Overview

Reads acceleration, rotation rate, temperature, and calculates orientation (roll/pitch/yaw) from a MPU6050 6-axis IMU via I2C. Provides Standard Commands for Programmable Instruments (SCPI) interface over WiFi on port 5025.

**Hardware:**
- ESP32 development board
- MPU6050 6-axis IMU module (accelerometer + gyroscope)
- I2C interface (GPIO 21 SDA, GPIO 22 SCL)
- 3.3V or 5V power (most modules have onboard regulator)

**Use cases:**
- Motion sensing and logging
- Vibration measurement
- Tilt/orientation monitoring
- Automated test equipment (ATE) with motion input
- Robotics platform orientation
- Antenna mount stabilization
- Earthquake/seismic data logger

## Hardware Setup

### MPU6050 Connections

```
MPU6050     →  ESP32
────────────────────────
VCC         →  3.3V (or 5V if module has regulator)
GND         →  GND
SDA         →  GPIO 21 (I2C SDA)
SCL         →  GPIO 22 (I2C SCL)
AD0         →  GND (I2C address 0x68) or VCC (address 0x69)
```

**I2C Address Selection:**
- AD0 pin LOW (GND): address 0x68 (default)
- AD0 pin HIGH (VCC): address 0x69
- If you have multiple MPU6050s on the same I2C bus, one must use 0x68 and the other 0x69

**Note:** Most cheap MPU6050 modules (GY-521, etc.) have built-in pull-up resistors on SDA/SCL. No external pull-ups needed.

### MPU6050 Module Variants

**GY-521** (most common):
- MPU6050 + 3.3V regulator
- Can be powered from 3.3V or 5V
- I2C pull-ups included (10kΩ)
- Small size: 20mm × 16mm

**GY-521 with DMP** (Digital Motion Processor):
- Same hardware, but supports on-chip sensor fusion
- This firmware does NOT use DMP (implements complementary filter instead)
- DMP could be added in future for more accurate orientation

## Software Setup

### Arduino Libraries Required

Install via Arduino IDE Library Manager:
1. **Adafruit MPU6050** by Adafruit
2. **Adafruit Unified Sensor** by Adafruit (dependency)
3. **Adafruit BusIO** by Adafruit (dependency)

### Upload to ESP32

1. Open `scpi-imu.ino` in Arduino IDE
2. Edit WiFi credentials at top of file:
   ```cpp
   const char* ssid = "YourSSID";
   const char* password = "YourPassword";
   ```
3. Tools → Board → ESP32 Dev Module
4. Tools → Port → (select your ESP32 serial port)
5. Click Upload
6. Open Serial Monitor (115200 baud)
7. Note the IP address displayed after WiFi connection

## SCPI Command Reference

### Standard IEEE 488.2 Commands

| Command | Response | Description |
|---------|----------|-------------|
| `*IDN?` | `N0GQ,ESP32-SCPI-IMU,1.0,2026` | Identification query |
| `*RST` | `OK` | Reset (zero orientation, default ranges) |
| `SYST:ERR?` | `0,"No error"` | System error query |

### IMU Measurement Commands

| Command | Response | Description |
|---------|----------|-------------|
| `IMU:ACC?` | `ax,ay,az` | Acceleration (m/s²) X,Y,Z |
| `IMU:GYRO?` | `gx,gy,gz` | Rotation rate (°/s) X,Y,Z |
| `IMU:TEMP?` | `temp` | Die temperature (°C) |
| `IMU:ORIE?` | `roll,pitch,yaw` | Orientation (degrees) |
| `IMU:ALL?` | `ax,ay,az,gx,gy,gz,temp,roll,pitch,yaw` | All data (10 values) |

**Acceleration:**
- X: forward/back (+ = forward)
- Y: left/right (+ = right)
- Z: up/down (+ = up)
- At rest on flat surface: approximately (0, 0, 9.81) m/s²

**Rotation rate:**
- X: roll rate (rotation about X axis)
- Y: pitch rate (rotation about Y axis)
- Z: yaw rate (rotation about Z axis)
- At rest: approximately (0, 0, 0) °/s

**Orientation:**
- Roll: tilt left/right (±180°)
- Pitch: tilt forward/back (±90°)
- Yaw: compass heading (±180°, drifts without magnetometer)

### Range Configuration Commands

| Command | Response | Description |
|---------|----------|-------------|
| `IMU:RANG:ACC,<2\|4\|8\|16>` | `OK` | Set accelerometer range (g) |
| `IMU:RANG:GYRO,<250\|500\|1000\|2000>` | `OK` | Set gyroscope range (°/s) |
| `IMU:RANG:ACC?` | `2`, `4`, `8`, or `16` | Query accel range |
| `IMU:RANG:GYRO?` | `250`, `500`, `1000`, or `2000` | Query gyro range |

**Range selection tradeoffs:**

**Accelerometer:**
- **±2g**: High precision (±0.061 mg/LSB), low noise, best for tilt sensing
- **±4g**: Good precision, suitable for most applications
- **±8g**: Moderate precision, for higher acceleration
- **±16g**: Low precision (±0.488 mg/LSB), high noise, for shock/impact measurement

**Gyroscope:**
- **±250°/s**: High precision (±0.0076 °/s/LSB), low noise, best for slow motion
- **±500°/s**: Good precision, suitable for most applications
- **±1000°/s**: Moderate precision, for faster motion
- **±2000°/s**: Low precision (±0.061 °/s/LSB), high noise, for rapid motion

## Usage Examples

### Telnet (manual testing)

```bash
telnet 192.168.1.42 5025
*IDN?
# N0GQ,ESP32-SCPI-IMU,1.0,2026

IMU:ACC?
# 0.1234,-0.0567,9.7890

IMU:GYRO?
# 0.0012,-0.0034,0.0056

IMU:TEMP?
# 28.45

IMU:ORIE?
# 2.34,-1.56,0.12

IMU:ALL?
# 0.1234,-0.0567,9.7890,0.0012,-0.0034,0.0056,28.45,2.34,-1.56,0.12
```

### Python Socket (simplest)

```python
import socket

def scpi_query(ip, port, cmd):
    s = socket.socket()
    s.connect((ip, port))
    s.sendall((cmd + '\n').encode())
    resp = s.recv(1024).decode().strip()
    s.close()
    return resp

# Read all IMU data
data = scpi_query('192.168.1.42', 5025, 'IMU:ALL?')
fields = [float(x) for x in data.split(',')]
ax, ay, az, gx, gy, gz, temp, roll, pitch, yaw = fields

print(f"Acceleration: X={ax:.3f} Y={ay:.3f} Z={az:.3f} m/s²")
print(f"Rotation: X={gx:.3f} Y={gy:.3f} Z={gz:.3f} °/s")
print(f"Temperature: {temp:.1f}°C")
print(f"Orientation: Roll={roll:.1f}° Pitch={pitch:.1f}° Yaw={yaw:.1f}°")
```

### PyVISA (instrument automation)

```python
import pyvisa

rm = pyvisa.ResourceManager('@py')
imu = rm.open_resource('TCPIP::192.168.1.42::5025::SOCKET')

# Query identification
print(imu.query('*IDN?'))

# Set high-g range for impact measurement
imu.write('IMU:RANG:ACC,16')

# Read acceleration
accel = imu.query('IMU:ACC?')
ax, ay, az = [float(x) for x in accel.split(',')]
print(f"Accel: {ax:.3f}, {ay:.3f}, {az:.3f} m/s²")
```

### Continuous Data Logging

```python
import socket
import time
import csv

def scpi_query(ip, port, cmd):
    s = socket.socket()
    s.connect((ip, port))
    s.sendall((cmd + '\n').encode())
    resp = s.recv(1024).decode().strip()
    s.close()
    return resp

ip = '192.168.1.42'
port = 5025

with open('imu_log.csv', 'w', newline='') as f:
    writer = csv.writer(f)
    writer.writerow(['time', 'ax', 'ay', 'az', 'gx', 'gy', 'gz', 'temp', 'roll', 'pitch', 'yaw'])
    
    while True:
        data = scpi_query(ip, port, 'IMU:ALL?')
        fields = [float(x) for x in data.split(',')]
        writer.writerow([time.time()] + fields)
        f.flush()
        time.sleep(0.1)  # 10 Hz logging
```

## Orientation Calculation

The firmware implements a **complementary filter** to fuse accelerometer and gyroscope data:

**Accelerometer (tilt sensing):**
- Measures gravity vector → gives absolute roll/pitch
- Accurate when stationary
- Noisy during motion (measures both gravity and motion)
- Cannot measure yaw (no magnetic reference)

**Gyroscope (rate integration):**
- Measures rotation rate → integrate to get angle change
- Accurate short-term
- Drifts over time (integration error accumulates)
- Works during motion

**Complementary filter:**
```
roll = 0.96 * (roll + gyro_roll_rate * dt) + 0.04 * accel_roll
pitch = 0.96 * (pitch + gyro_pitch_rate * dt) + 0.04 * accel_pitch
yaw += gyro_yaw_rate * dt  (no correction, drifts)
```

**Alpha = 0.96** means:
- Trust gyro 96% (short-term accuracy)
- Trust accel 4% (long-term drift correction)

## Limitations

1. **No magnetometer** → Yaw (compass heading) drifts over time. Only roll/pitch are accurate long-term.
2. **No Kalman filter** → Simple complementary filter is fast but less optimal than Kalman filter.
3. **Motion affects tilt** → Accelerometer-based roll/pitch incorrect during acceleration (e.g., car turning, elevator).
4. **Single client** → One TCP connection at a time.
5. **No authentication** → Any device on network can query IMU.
6. **Update rate** → ~100 Hz orientation update (10 ms loop time). Could be increased for faster motion.
7. **No calibration** → Uses factory calibration. Could add user calibration for better accuracy.

## Troubleshooting

### "MPU6050 not found" error

**Check I2C address:**
- Most modules default to 0x68 (AD0 = GND)
- Some use 0x69 (AD0 = VCC)
- Firmware tries 0x68 first; edit code if yours uses 0x69

**Check wiring:**
- SDA → GPIO 21
- SCL → GPIO 22
- VCC → 3.3V or 5V (depending on module)
- GND → GND

**Scan I2C bus:**
```cpp
#include <Wire.h>

void setup() {
  Serial.begin(115200);
  Wire.begin(21, 22);
  Serial.println("Scanning I2C bus...");
  for (byte addr = 1; addr < 127; addr++) {
    Wire.beginTransmission(addr);
    if (Wire.endTransmission() == 0) {
      Serial.printf("Device found at 0x%02X\n", addr);
    }
  }
}
```

### Orientation drifts over time

**Expected:**
- Yaw (compass heading) drifts ~1-5°/minute without magnetometer (normal)
- Roll/pitch should NOT drift significantly

**If roll/pitch drift:**
- Gyro bias error (improve with calibration)
- Temperature drift (MPU6050 spec: ±2000 LSB over -40 to +85°C)
- Mechanical vibration causing accel noise

**Solutions:**
- Add magnetometer (HMC5883L, QMC5883L) for absolute yaw reference
- Implement Kalman filter (more complex but better drift rejection)
- Calibrate gyro at startup (average 100 samples, subtract bias)

### Noisy readings

**Accelerometer noise:**
- Mechanical vibration → add damping/isolation
- High-g range selected → use ±2g for stationary applications
- Add digital low-pass filter (already enabled at 21 Hz in firmware)

**Gyroscope noise:**
- High rate range selected → use ±250°/s for slow motion
- Temperature sensitivity → wait for thermal stabilization
- Read multiple samples and average

### Temperature seems wrong

MPU6050 die temperature:
- Reads internal chip temperature (not ambient)
- Typically 5-10°C above ambient due to self-heating
- Accuracy: ±2°C typical
- Use external thermistor for accurate ambient measurement

## MPU6050 Specifications

**Accelerometer:**
- 16-bit ADC (±2g: 0.061 mg/LSB, ±16g: 0.488 mg/LSB)
- Noise: 400 µg/√Hz typical
- Full-scale ranges: ±2g, ±4g, ±8g, ±16g
- Bandwidth: 5-260 Hz configurable

**Gyroscope:**
- 16-bit ADC (±250°/s: 0.0076 °/s/LSB, ±2000°/s: 0.061 °/s/LSB)
- Noise: 0.005 °/s/√Hz typical
- Full-scale ranges: ±250, ±500, ±1000, ±2000 °/s
- Bandwidth: 5-256 Hz configurable

**Temperature sensor:**
- 16-bit ADC
- Sensitivity: 340 LSB/°C
- Range: -40 to +85°C
- Accuracy: ±2°C typical

**Interface:**
- I2C up to 400 kHz (Fast Mode)
- Two addresses: 0x68 (AD0=0) or 0x69 (AD0=1)

**Power:**
- Supply: 2.375V to 3.46V (typical 3.3V)
- Operating current: 3.8 mA typical
- Sleep mode: 8 µA

## Version History

**1.0 (2026-06-12)**
- Initial release
- MPU6050 support via Adafruit library
- Complementary filter orientation
- SCPI commands for accel, gyro, temp, orientation
- Configurable ranges

## Related Projects

- `~/rf-bench/projects/esp32/scpi-relay/` — Relay controller sibling
- `~/rf-bench/projects/esp32/scpi-gps/` — GPS receiver sibling
- `~/rf-bench/projects/esp32/scpi-servo/` — Servo controller sibling
- `~/gps/` — GPS position tracking (could combine with IMU for INS)
- `~/aprs-server/` — APRS position beacon (could add IMU for motion detection)

## Future Enhancements

- **Magnetometer support** (HMC5883L, QMC5883L) for absolute yaw reference
- **Kalman filter** for improved sensor fusion
- **DMP support** (Digital Motion Processor) for on-chip sensor fusion
- **Gyro calibration** at startup (bias removal)
- **Temperature compensation** for gyro drift
- **Multiple IMU support** (compare units, redundancy)
- **Data buffering** for burst reads
- **Web UI** with live 3D orientation visualization
- **Data logging** to SD card or MQTT
- **Gesture recognition** (tap, shake, freefall detection)
- **Shock/impact detection** with timestamp

## License

MIT License — free to use, modify, and distribute.

## Author

N0GQ — 2026-06-12
