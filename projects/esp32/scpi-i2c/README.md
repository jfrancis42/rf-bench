# SCPI I2C Controller for ESP32

Network-accessible I2C master bridge — scan, read, write any I2C device via Standard Commands for Programmable Instruments (SCPI) over TCP/IP.

## Hardware

- **ESP32 dev board** (any variant with I2C: ESP32, ESP32-S2, ESP32-S3, ESP32-C3)
- **I2C devices** (sensors, EEPROMs, RTCs, I/O expanders, displays, etc.)
- **Pull-up resistors** (4.7k or 10k to 3.3V on SDA/SCL — often built-in on modules)

## Pin Connections

```
ESP32    I2C Device
GPIO 21  → SDA
GPIO 22  → SCL
GND      → GND
3.3V     → VCC (if device is 3.3V)
```

**Pull-ups:** I2C requires pull-up resistors on SDA and SCL. Most I2C modules have on-board pull-ups. If using bare chips, add 4.7k resistors from SDA/SCL to 3.3V.

**5V devices:** ESP32 I2C is 3.3V only. For 5V devices, use a level shifter (TXS0108E, TXB0108) or a 5V-tolerant I2C bus buffer.

## I2C Protocol Basics

### Addressing

I2C uses **7-bit addresses** (0x00 to 0x7F). The Wire library handles the read/write bit automatically.

**Datasheets sometimes list 8-bit addresses:**
- Write address: 0xD0 → 7-bit: 0x68
- Read address: 0xD1 → 7-bit: 0x68
- Rule: Divide 8-bit address by 2 to get 7-bit address.

### Communication Modes

1. **Direct read/write** — no register addressing (simple devices like I/O expanders)
2. **Register-based** — write register address, then read/write data (most sensors, RTCs)

### Bus Speed

- **Standard mode:** 100 kHz (default)
- **Fast mode:** 400 kHz

## Common I2C Devices

| Address | Device | Type |
|---------|--------|------|
| 0x50 | AT24C32/64 | EEPROM (32/64 kbit) |
| 0x68 | DS1307/DS3231 | RTC (real-time clock) |
| 0x76, 0x77 | BMP280/BME280 | Temp/pressure/humidity sensor |
| 0x40 | PCA9685 | 16-channel PWM driver |
| 0x20-0x27 | PCF8574/MCP23008 | 8-bit I/O expander |
| 0x48-0x4B | ADS1115 | 16-bit ADC |
| 0x3C, 0x3D | SSD1306 | 128x64 OLED display |
| 0x1E | HMC5883L | 3-axis magnetometer |
| 0x5A | MPU-6050 | IMU (accel + gyro) |

Many devices have configurable addresses via solder jumpers or address pins.

## SCPI Commands

### IEEE 488.2 Common Commands

- `*IDN?` — identification
- `*RST` — reset (no-op for this device)
- `SYST:ERR?` — system error query

### I2C Subsystem

#### Bus Management

- `I2C:SCAN?` — scan bus, return comma-separated hex addresses
- `I2C:FREQ,<100000|400000>` — set bus frequency (100 kHz or 400 kHz)
- `I2C:FREQ?` — query bus frequency

#### Direct Read/Write

- `I2C:READ? <addr>,<count>` — read count bytes from device at addr
- `I2C:WRIT <addr>,<byte1>,<byte2>,...` — write bytes to device

#### Register Read/Write

- `I2C:READ:REG? <addr>,<reg>,<count>` — read count bytes from register
- `I2C:WRIT:REG <addr>,<reg>,<value>` — write value to register

**Address format:** Decimal or hex (0x68 or 104). Hex is recommended for clarity.

**Byte format:** Decimal or hex (0xFF or 255).

**Response format:** Hex CSV (e.g., `0x12,0x34,0xAB`)

## Examples

### Scan for devices

```bash
telnet 192.168.1.42 5025
I2C:SCAN?
# Returns: 0x68,0x76
```

### Read device ID (BMP280 at 0x76, register 0xD0)

```bash
I2C:READ:REG? 0x76,0xD0,1
# Returns: 0x58
```

### Write to RTC (DS1307 at 0x68, set seconds register to 0)

```bash
I2C:WRIT:REG 0x68,0x00,0x00
# Returns: OK
```

### Read temperature from BMP280 (registers 0xFA-0xFC)

```bash
I2C:READ:REG? 0x76,0xFA,3
# Returns: 0x80,0x4D,0x00
```

### Direct write to I/O expander (PCF8574 at 0x20, set all outputs high)

```bash
I2C:WRIT 0x20,0xFF
# Returns: OK
```

### Direct read from I/O expander

```bash
I2C:READ? 0x20,1
# Returns: 0xFF
```

### Change bus speed to 400 kHz

```bash
I2C:FREQ,400000
I2C:FREQ?
# Returns: 400000
```

## Python Integration

### Simple socket client

```python
import socket

def scpi_cmd(ip, cmd):
    s = socket.socket()
    s.connect((ip, 5025))
    s.sendall((cmd + '\n').encode())
    if '?' in cmd:
        resp = s.recv(1024).decode().strip()
        s.close()
        return resp
    s.close()

# Scan for devices
devices = scpi_cmd('192.168.1.42', 'I2C:SCAN?')
print(f"Devices found: {devices}")

# Read BMP280 chip ID
chip_id = scpi_cmd('192.168.1.42', 'I2C:READ:REG? 0x76,0xD0,1')
print(f"BMP280 ID: {chip_id}")
```

### pyvisa (instrument automation)

```python
import pyvisa

rm = pyvisa.ResourceManager('@py')
i2c = rm.open_resource('TCPIP::192.168.1.42::5025::SOCKET')

# Scan bus
devices = i2c.query('I2C:SCAN?')
print(f"Devices: {devices}")

# Read register
value = i2c.query('I2C:READ:REG? 0x76,0xD0,1')
print(f"Value: {value}")

# Write register
i2c.write('I2C:WRIT:REG 0x68,0x00,0x00')
```

## Use Cases

### 1. Sensor Prototyping

Rapidly test I2C sensors without writing firmware. Query sensor registers over SCPI from Python/MATLAB to validate sensor behavior before integrating into application.

### 2. I2C Debugging

Diagnose I2C communication issues. Scan for devices, verify register addresses, check read/write access, monitor bus errors.

### 3. Device Characterization

Automate data collection from I2C sensors for calibration curves, temperature sweeps, repeatability tests.

### 4. EEPROM Programming

Read/write I2C EEPROMs for configuration data storage, calibration constants, serial numbers.

### 5. Lab Automation

Control I2C peripherals (I/O expanders, PWM drivers, DACs, ADCs) from test scripts. Integrate with existing SCPI-based ATE systems.

### 6. Educational Tool

Teach I2C protocol by allowing students to interact with sensors via simple SCPI commands without learning embedded C.

## Installation

1. Open Arduino IDE
2. Tools → Board → ESP32 Dev Module (or your ESP32 variant)
3. Edit WiFi credentials at top of `scpi-i2c.ino`
4. Tools → Port → (select your ESP32)
5. Click Upload
6. Open Serial Monitor (115200 baud) to see IP address

## Error Codes

Wire library `endTransmission()` results:
- 0: Success
- 1: Data too long to fit in transmit buffer
- 2: NACK on address (device not found)
- 3: NACK on data (device rejected data)
- 4: Other error
- 5: Timeout

## Troubleshooting

### I2C:SCAN? returns NONE

- Check SDA/SCL connections
- Verify pull-up resistors (4.7k or 10k to 3.3V)
- Check device power (VCC/GND)
- Try different bus speed (`I2C:FREQ,100000`)
- Some devices require initialization before responding (e.g., write to config register first)

### ERROR: I2C error 2 (NACK on address)

- Device not connected or powered
- Wrong I2C address (check datasheet — may be 8-bit address that needs to be divided by 2)
- Device address conflicts (multiple devices on same address)

### ERROR: I2C error 3 (NACK on data)

- Register address invalid
- Device in wrong mode (e.g., sensor in sleep mode)
- Write-protected (EEPROMs often need write-enable sequence)

### ERROR: No data received

- Device doesn't have readable data at that register
- Register address out of range
- Device requires specific read sequence (check datasheet)

## Limitations

- **Single bus** — only one I2C bus (Wire library). ESP32 has two I2C hardware peripherals; could add Wire1 support for dual-bus.
- **3.3V only** — ESP32 I2C is 3.3V. Use level shifter for 5V devices.
- **No multi-master** — acts as master only. Cannot detect or arbitrate with other masters.
- **No clock stretching timeout** — Wire library supports clock stretching but no configurable timeout. Some devices may cause hangs.
- **No repeated start on register read** — Wire library implementation uses stop between write and read phases of register read. Most devices tolerate this; some (e.g., multi-byte atomic reads) may not.
- **No 10-bit addressing** — only 7-bit addresses (0x00-0x7F) supported.
- **No SMBus packet error checking (PEC)** — no CRC validation.

## Future Enhancements

- **Dual bus support** — add Wire1 commands for second I2C bus (SDA2/SCL2)
- **10-bit addressing** — support extended address range
- **I2C:READ:BLOCK?** — read until NACK (auto-detect count)
- **I2C:WRIT:BLOCK** — write from CSV or hex string
- **I2C:PING? <addr>** — test if device responds (just address, no data)
- **I2C:RESET** — send I2C bus reset sequence (9 clocks with SDA high)
- **Error logging** — track and report I2C error history
- **Web UI** — HTML interface for manual I2C transactions
- **MQTT publish** — push sensor data to MQTT broker

## Related Projects

- `~/rf-bench/projects/esp32/scpi-relay/` — ESP32 relay controller (GPIO outputs)
- `~/rf-bench/projects/esp32/scpi-gps/` — ESP32 GPS receiver (serial input)
- `~/rf-bench/projects/esp32/scpi-servo/` — ESP32 servo controller (PWM outputs)
- `~/rf-bench/drivers/buspirate/` — Bus Pirate I2C/SPI master (USB-serial Python driver)
- `~/rf-bench/drivers/relay/` — XL9535 I2C relay driver (Python client, not ESP32 bridge)

## References

- [I2C Bus Specification](https://www.nxp.com/docs/en/user-guide/UM10204.pdf) — NXP I2C-bus specification
- [ESP32 I2C Documentation](https://docs.espressif.com/projects/esp-idf/en/latest/esp32/api-reference/peripherals/i2c.html)
- [Arduino Wire Library](https://www.arduino.cc/reference/en/language/functions/communication/wire/)

## Version

1.0 (2026-06-12)
