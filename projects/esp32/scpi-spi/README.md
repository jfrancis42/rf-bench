# ESP32 SCPI SPI Controller

Network-controlled SPI master bridge using Standard Commands for Programmable Instruments (SCPI) over TCP/IP.

## Features

- **SCPI over TCP/IP** on port 5025 (industry standard)
- **4 independent chip select lines** (CS0-CS3) for multi-device control
- **Configurable SPI settings** — frequency (100 kHz-10 MHz), mode (0-3), bit order (MSB/LSB)
- **Full-duplex SPI** — all transfers return MISO data
- **WiFi connectivity** with configurable credentials
- **Standard SCPI commands** compatible with test equipment automation
- **Three transfer modes** — transfer (write+read), write-only, read-only

## Hardware Requirements

- ESP32 development board (any variant with WiFi)
- SPI slave devices (ADCs, DACs, displays, sensors, memory, etc.)
- Jumper wires

### Wiring

#### SPI Bus (Shared by All Devices)

| ESP32 GPIO | SPI Signal | Function |
|------------|-----------|----------|
| GPIO 23    | MOSI      | Master Out, Slave In |
| GPIO 19    | MISO      | Master In, Slave Out |
| GPIO 18    | SCK       | Clock |
| GND        | GND       | Ground |

**Power:** Connect 3.3V or 5V to each SPI device as required by its datasheet. ESP32 SPI pins are 3.3V logic — use level shifters for 5V devices.

#### Chip Select Lines (One per Device)

| ESP32 GPIO | CS Signal | Use |
|------------|----------|-----|
| GPIO 5     | CS0      | Device 0 |
| GPIO 15    | CS1      | Device 1 |
| GPIO 4     | CS2      | Device 2 |
| GPIO 16    | CS3      | Device 3 |

**CS behavior:** Active-low (ESP32 pulls LOW to select device, HIGH to deselect). Each device gets its own CS line.

**Example wiring (MCP3008 ADC on CS0):**
```
ESP32 GPIO 23 → MCP3008 DIN (pin 11)
ESP32 GPIO 19 → MCP3008 DOUT (pin 12)
ESP32 GPIO 18 → MCP3008 CLK (pin 13)
ESP32 GPIO 5  → MCP3008 CS (pin 10)
ESP32 GND     → MCP3008 DGND (pin 9) and AGND (pin 14)
ESP32 3.3V    → MCP3008 VDD (pin 16) and VREF (pin 15)
```

## Software Setup

1. **Install Arduino IDE** with ESP32 board support
   - File → Preferences → Additional Board Manager URLs: `https://dl.espressif.com/dl/package_esp32_index.json`
   - Tools → Board → Boards Manager → Search "ESP32" → Install

2. **Configure WiFi credentials**
   - Edit `scpi-spi.ino`
   - Change `ssid` and `password` near the top of the file

3. **Upload to ESP32**
   - Tools → Board → ESP32 Dev Module (or your specific board)
   - Tools → Port → (select your ESP32's serial port)
   - Click Upload

4. **Find the IP address**
   - Open Serial Monitor (115200 baud)
   - Reset the ESP32
   - Note the IP address printed (e.g., `192.168.1.42`)

## SCPI Command Reference

Connect to the ESP32 on port 5025 using any TCP client (`telnet`, `nc`, or Python `socket`).

### Identification

```
*IDN?
```
Returns device identification string: `N0GQ,ESP32-SCPI-SPI,1.0,2026`

### Reset

```
*RST
```
Returns SPI settings to defaults: 1 MHz, mode 0, MSB first.

### SPI Configuration

```
SPI:FREQ,<hz>          # Set clock frequency (100000-10000000)
SPI:FREQ?              # Query clock frequency

SPI:MODE,<0-3>         # Set SPI mode (CPOL/CPHA combination)
SPI:MODE?              # Query SPI mode

SPI:ORD,<MSB|LSB>      # Set bit order
SPI:ORD?               # Query bit order
```

**SPI modes:**
- Mode 0: CPOL=0, CPHA=0 (clock idle low, sample on rising edge) — most common
- Mode 1: CPOL=0, CPHA=1 (clock idle low, sample on falling edge)
- Mode 2: CPOL=1, CPHA=0 (clock idle high, sample on falling edge)
- Mode 3: CPOL=1, CPHA=1 (clock idle high, sample on rising edge)

**Frequency range:** 100 kHz to 10 MHz (default 1 MHz)

**Bit order:**
- MSB: Most significant bit first (default) — standard for most devices
- LSB: Least significant bit first — rare, some LED drivers

### SPI Transfers

```
SPI:TRAN (@cs),<hex bytes>   # Transfer (write and read, return MISO)
SPI:WRIT (@cs),<hex bytes>   # Write only (ignore MISO)
SPI:READ (@cs),<count>        # Read only (send 0x00 on MOSI)
```

**CS channel:** 0-3 (matches CS0-CS3 pins)

**Hex format:** Decimal or hex with 0x prefix, comma-separated. Examples:
- `0x12,0x34,0xAB`
- `18,52,171` (same as above in decimal)
- `0x12,52,0xAB` (mixed hex and decimal)

**Returns (TRAN/READ):** Hex CSV with 0x prefix, e.g., `0x00,0xFF,0x42`

**Returns (WRIT):** `OK\n`

### System Error Query

```
SYST:ERR?
```
Returns `0,"No error"` (always, for this simple device).

### Command Format Notes

- Commands can be uppercase or lowercase (case-insensitive)
- Short form allowed: `SPI:TRAN` = `SPI:TRANSFER`
- Commands can be terminated with newline (`\n`), carriage return (`\r`), or semicolon (`;`)
- Multiple commands can be sent in one line separated by semicolons

## Usage Examples

### Telnet (interactive)

```bash
telnet 192.168.1.42 5025
*IDN?
# Returns: N0GQ,ESP32-SCPI-SPI,1.0,2026

SPI:FREQ,1000000
# Set 1 MHz clock

SPI:MODE,0
# Set mode 0 (CPOL=0, CPHA=0)

SPI:TRAN (@0),0x01,0x80,0x00
# Send 3 bytes to CS0, receive 3 bytes
# Returns: 0x00,0x03,0xFF (example MISO data)
```

### Netcat (command-line)

```bash
echo "SPI:FREQ,1000000" | nc 192.168.1.42 5025
echo "SPI:TRAN (@0),0x01,0x80,0x00" | nc 192.168.1.42 5025
echo "SPI:READ (@0),4" | nc 192.168.1.42 5025
```

### Python

```python
import socket

def scpi_command(ip, port, command):
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.connect((ip, port))
        s.sendall((command + '\n').encode())
        if '?' in command:
            response = s.recv(1024).decode().strip()
            return response

# Configure SPI
scpi_command('192.168.1.42', 5025, 'SPI:FREQ,1000000')
scpi_command('192.168.1.42', 5025, 'SPI:MODE,0')

# Transfer 3 bytes to CS0 and read response
miso = scpi_command('192.168.1.42', 5025, 'SPI:TRAN (@0),0x01,0x80,0x00')
print(f"MISO: {miso}")
# Output: MISO: 0x00,0x03,0xFF

# Parse response
values = [int(x, 16) for x in miso.split(',')]
print(f"Bytes: {values}")
# Output: Bytes: [0, 3, 255]

# Read-only transfer (send zeros, read MISO)
miso = scpi_command('192.168.1.42', 5025, 'SPI:READ (@0),4')
print(f"MISO: {miso}")
```

### Python with pyvisa (instrument automation)

```python
import pyvisa

rm = pyvisa.ResourceManager('@py')
spi = rm.open_resource('TCPIP::192.168.1.42::5025::SOCKET', 
                       read_termination='\n',
                       write_termination='\n')

print(spi.query('*IDN?'))
spi.write('SPI:FREQ,1000000')
spi.write('SPI:MODE,0')

# Transfer and read
miso = spi.query('SPI:TRAN (@0),0x01,0x80,0x00')
print(f"MISO: {miso}")

spi.close()
```

## Device-Specific Examples

### MCP3008 (8-channel 10-bit ADC)

```python
def read_mcp3008(channel):
    # MCP3008 command format: 
    # Byte 1: 0x01 (start bit)
    # Byte 2: 0x80 | (channel << 4) for single-ended
    # Byte 3: 0x00 (dummy byte for clock cycles)
    
    cmd = f"SPI:TRAN (@0),0x01,{0x80 | (channel << 4)},0x00"
    miso = scpi_command('192.168.1.42', 5025, cmd)
    
    # Parse response
    values = [int(x, 16) for x in miso.split(',')]
    
    # Extract 10-bit result from last 2 bytes
    adc_value = ((values[1] & 0x03) << 8) | values[2]
    voltage = (adc_value / 1023.0) * 3.3
    
    return adc_value, voltage

# Read channel 0
adc_val, voltage = read_mcp3008(0)
print(f"Channel 0: {adc_val} ({voltage:.3f}V)")
```

### MCP4921 (12-bit DAC)

```python
def set_mcp4921(voltage):
    # MCP4921 command format (16-bit word):
    # Bits 15-12: 0011 (write to DAC, unbuffered, 1x gain, active)
    # Bits 11-0:  12-bit DAC value
    
    dac_value = int((voltage / 3.3) * 4095)
    dac_value = max(0, min(4095, dac_value))  # Clamp to 0-4095
    
    word = 0x3000 | (dac_value & 0x0FFF)
    
    # Send as 2 bytes (MSB first)
    high_byte = (word >> 8) & 0xFF
    low_byte = word & 0xFF
    
    cmd = f"SPI:WRIT (@0),{high_byte},{low_byte}"
    scpi_command('192.168.1.42', 5025, cmd)

# Set output to 2.5V
set_mcp4921(2.5)
```

### W25Q32 (SPI Flash Memory)

```python
# Read flash ID
def read_flash_id():
    # Command 0x9F: JEDEC ID
    miso = scpi_command('192.168.1.42', 5025, 'SPI:TRAN (@0),0x9F,0x00,0x00,0x00')
    values = [int(x, 16) for x in miso.split(',')]
    
    manufacturer = values[1]
    device_type = values[2]
    capacity = values[3]
    
    return manufacturer, device_type, capacity

mfr, dev, cap = read_flash_id()
print(f"Flash ID: Manufacturer={mfr:02X}, Device={dev:02X}, Capacity={cap:02X}")
```

## Debugging

- **Serial Monitor (115200 baud)** shows WiFi connection status, IP address, and received SCPI commands
- **Connection refused:** Check IP address, port number (5025), and firewall settings
- **Device not responding:** Verify CS wiring, SPI mode, and clock frequency (try 100 kHz if 1 MHz fails)
- **Incorrect data returned:** Check SPI mode (CPOL/CPHA), bit order (MSB/LSB), and device datasheet
- **Clock too fast:** Some devices (e.g., slow EEPROMs) may only work at 100-400 kHz — reduce frequency
- **5V device damage warning:** ESP32 is 3.3V logic! Use level shifters (TXS0108E, 74LVC245) for 5V SPI devices

## Integration with Test Systems

This SCPI SPI controller integrates with:

- **LabVIEW** via VISA driver (use TCPIP SOCKET resource)
- **MATLAB** via `tcpip` or Instrument Control Toolbox
- **Python** via `pyvisa`, `socket`
- **Keysight VEE, TestStand, etc.** via standard SCPI/VISA interface

The standard SCPI command set and SPI subsystem make this compatible with automated test equipment (ATE) frameworks.

## Common SPI Devices

| Device | Type | Typical Mode | Typical Freq | Notes |
|--------|------|-------------|-------------|--------|
| MCP3008 | 10-bit ADC | 0 | 1 MHz | 8 channels, single-ended/differential |
| MCP3202 | 12-bit ADC | 0 | 1 MHz | 2 channels, differential |
| MCP4921 | 12-bit DAC | 0 | 20 MHz | Single channel |
| MAX7219 | LED driver | 0 | 10 MHz | 8-digit 7-segment or 8×8 matrix |
| NRF24L01 | 2.4 GHz radio | 0 | 10 MHz | Wireless transceiver |
| W25Q32 | 32 Mbit flash | 0 | 50 MHz | SPI NOR flash memory |
| BME280 | Temp/RH/pressure | 0 or 3 | 10 MHz | Also supports I2C |
| MCP23S17 | 16-bit I/O | 0 | 10 MHz | SPI version of MCP23017 |
| AD9833 | Function gen IC | 2 | 40 MHz | Waveform generator |
| ADS1118 | 16-bit ADC | 1 | 4 MHz | 4 channels, PGA |

**Most common:** Mode 0, MSB first, 1-10 MHz.

## License

Public domain. Use freely.

## Author

N0GQ — 2026-06-12
