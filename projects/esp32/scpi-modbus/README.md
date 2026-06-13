# SCPI Modbus RTU Bridge

ESP32-based network-accessible Modbus RTU master bridge. Provides read/write access to Modbus slave devices via SCPI commands over TCP/IP on port 5025.

## Hardware

### Components

- ESP32 dev board (any variant with WiFi and UART2)
- MAX485 or MAX3485 RS-485 transceiver module
- Modbus RTU slave device(s)

### Wiring

```
ESP32 GPIO 17 (UART2 TX) → MAX485 DI (data in)
ESP32 GPIO 16 (UART2 RX) → MAX485 RO (receiver output)
ESP32 GPIO 4            → MAX485 DE and RE tied together (driver enable)
ESP32 GND, 3.3V         → MAX485 GND, VCC
MAX485 A, B             → RS-485 bus A, B (twisted pair to Modbus slave)
```

**Note:** The MAX485 DE (driver enable) and RE (receiver enable, active low) pins are tied together and controlled by GPIO 4. HIGH = transmit mode, LOW = receive mode.

**RS-485 bus termination:** For long cable runs (>10 meters) or high baud rates (>38400), install 120-ohm termination resistors across A-B at both ends of the bus. For short runs or single slave, termination is often optional.

**Bus topology:** Daisy-chain (linear) topology is required — star/tree topologies don't work with RS-485.

## Setup

1. Install ModbusMaster library in Arduino IDE:
   - Sketch → Include Library → Manage Libraries → search "ModbusMaster" → Install

2. Edit `scpi-modbus.ino`:
   - Change `ssid` and `password` to your WiFi network

3. Upload to ESP32:
   - Tools → Board → ESP32 Dev Module
   - Tools → Port → (select USB serial port)
   - Click Upload

4. Open Serial Monitor (115200 baud) to see IP address

5. Connect MAX485 transceiver to ESP32 and Modbus slave device (see wiring above)

6. Test via telnet or Python:
   ```bash
   telnet <ip> 5025
   *IDN?
   # should return: N0GQ,ESP32-SCPI-Modbus,1.0,2026
   ```

## SCPI Commands

### Common Commands (IEEE 488.2)

- `*IDN?` — identification query
- `*RST` — reset to defaults (baud 9600, slave address 1)
- `SYST:ERR?` — system error query (always "0,No error")

### Modbus Configuration

- `MODB:BAUD,<rate>` — set baud rate (9600, 19200, 38400, or 115200)
- `MODB:BAUD?` — query baud rate
- `MODB:ADDR,<1-247>` — set target slave address
- `MODB:ADDR?` — query target slave address

### Modbus Read Operations

- `MODB:READ:HOLD,<reg>,<count>` — read holding registers (function code 0x03)
- `MODB:READ:INPU,<reg>,<count>` — read input registers (function code 0x04)

**Response format:** CSV of decimal values, e.g., "1234,5678,910"

**Register address:** 0-65535 (Modbus protocol addresses)

**Count:** 1-125 registers (Modbus RTU max is 125 registers per transaction)

### Modbus Write Operations

- `MODB:WRIT:HOLD,<reg>,<value>` — write single holding register (function code 0x06)
- `MODB:WRIT:COIL,<addr>,<0|1>` — write single coil (function code 0x05)

**Response:** "OK" on success, "ERROR: Modbus error 0xXX" on failure

**Holding register value:** 0-65535 (16-bit unsigned)

**Coil value:** 0 (off) or 1 (on)

## Modbus Error Codes

ModbusMaster library returns error codes on failure. Common codes:

- **0xE0** — Invalid slave ID
- **0xE1** — Invalid function code
- **0xE2** — Response timeout (slave didn't respond within 2 seconds)
- **0xE3** — Invalid CRC (corrupted packet)

Modbus exception codes (from slave):
- **0x01** — Illegal function
- **0x02** — Illegal data address (register doesn't exist)
- **0x03** — Illegal data value
- **0x04** — Slave device failure

## Python Example

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

# Configure for slave address 1, baud 9600
scpi_cmd('192.168.1.42', 'MODB:ADDR,1')
scpi_cmd('192.168.1.42', 'MODB:BAUD,9600')

# Read 2 holding registers starting at address 0
values = scpi_cmd('192.168.1.42', 'MODB:READ:HOLD,0,2')
print(f"Holding registers: {values}")  # e.g., "1234,5678"

# Write value 42 to holding register 10
scpi_cmd('192.168.1.42', 'MODB:WRIT:HOLD,10,42')

# Write coil 5 to ON
scpi_cmd('192.168.1.42', 'MODB:WRIT:COIL,5,1')

# Read 4 input registers starting at address 100
inputs = scpi_cmd('192.168.1.42', 'MODB:READ:INPU,100,4')
print(f"Input registers: {inputs}")
```

## Common Modbus Devices

### Energy Meters (e.g., Carlo Gavazzi EM340)

- **Slave address:** 1 (default, configurable via meter display)
- **Baud rate:** 9600 (default)
- **Registers:**
  - 0x0000: Voltage L1-N (×10, e.g., 2300 = 230.0V)
  - 0x0002: Voltage L2-N
  - 0x000C: Current L1 (×1000, e.g., 5000 = 5.000A)
  - 0x0028: Total active power (×10, e.g., 1500 = 150.0W)

Example:
```
MODB:ADDR,1
MODB:BAUD,9600
MODB:READ:HOLD,0,1
# Returns voltage L1-N (e.g., "2300" = 230.0V)
```

### Temperature Controllers (e.g., Omega CNi3244)

- **Slave address:** 1 (default)
- **Baud rate:** 9600 (default)
- **Registers:**
  - 0x1000: Process value (PV, temperature ×10)
  - 0x1001: Setpoint (SP, temperature ×10)
  - 0x1002: Output power (0-1000 = 0-100.0%)

Example:
```
MODB:ADDR,1
MODB:READ:HOLD,4096,1
# Returns PV (e.g., "235" = 23.5°C)

MODB:WRIT:HOLD,4097,300
# Sets SP to 30.0°C
```

### Variable Frequency Drives (VFDs)

- **Slave address:** 1 (default, configurable via VFD keypad)
- **Baud rate:** 9600 or 19200 (varies by model)
- **Common registers (varies by manufacturer):**
  - Status (running/stopped)
  - Speed setpoint (Hz ×10)
  - Output frequency (Hz ×10)
  - Motor current (A ×10)

Example (generic):
```
MODB:ADDR,1
MODB:BAUD,9600
MODB:WRIT:HOLD,0,500
# Sets speed to 50.0 Hz

MODB:READ:HOLD,10,1
# Reads actual output frequency
```

### Generic Modbus RTU Sensors

Many industrial sensors (humidity, pressure, flow, level) use Modbus RTU with similar patterns:
- Slave address 1 (often configurable via DIP switches or setup mode)
- Baud 9600 (sometimes 19200)
- Input registers (function code 0x04) for sensor readings
- Holding registers (function code 0x03) for configuration

**Always consult the device's Modbus register map (datasheet or manual) for specific addresses and scaling.**

## Use Cases

- **Energy monitoring:** Read power meters in industrial/building automation
- **Temperature logging:** Poll temperature controllers and log to time-series DB
- **HVAC control:** Read/write setpoints on building automation controllers
- **Process automation:** Interface PLCs with Python test scripts
- **Motor control:** Set VFD speed and monitor status
- **Sensor networks:** Poll multiple Modbus sensors on one bus (change `MODB:ADDR` between reads)
- **Lab automation:** Control programmable power supplies, electronic loads, thermal chambers

## Integration with rf-bench

Could be added as `~/rf-bench/drivers/modbus-bridge/` driver package wrapping SCPI commands in a Python class. Future use cases:

- **Thermal chamber control** (temperature sweep for component characterization)
- **Programmable load automation** (battery discharge curves)
- **Power supply control** (PSRR testing, voltage sweep)
- **Energy meter data logging** (RF amplifier power consumption measurement)

## Troubleshooting

### No response / timeout errors

1. Check wiring (TX/RX swapped? A/B reversed?)
2. Verify baud rate matches slave device (try `MODB:BAUD,9600`)
3. Verify slave address (consult device manual or try addresses 1-10)
4. Check RS-485 bus termination (120-ohm resistors at both ends for long cables)
5. Check DE/RE control (should be HIGH during transmit, LOW during receive — firmware handles this automatically)
6. Verify MAX485 power (should have 3.3V on VCC, GND connected)
7. Use oscilloscope to verify UART TX pulses on GPIO 17

### CRC errors / corrupted data

1. Check for loose connections on A/B bus
2. Add termination resistors if missing (120-ohm across A-B at both ends)
3. Lower baud rate (try 9600 instead of 115200)
4. Shorten cable length or use shielded twisted pair
5. Check for electrical noise sources near cable (motors, relays, fluorescent lights)

### Illegal data address errors (exception code 0x02)

1. Verify register address in device manual (Modbus register map)
2. Some devices use 1-indexed addresses (holding register 40001 = address 0)
3. Input registers vs holding registers (use correct read command)

### Invalid slave ID (error 0xE0)

1. Verify slave address setting on device (check DIP switches or menu)
2. Try addresses 1-10 (common defaults)
3. Some devices respond to broadcast address 0 (not supported by this firmware)

## Technical Notes

### Modbus RTU Frame Format

```
[Slave Address] [Function Code] [Data...] [CRC-16]
```

- Slave address: 1 byte (1-247)
- Function code: 1 byte (0x03, 0x04, 0x05, 0x06, etc.)
- Data: N bytes (register addresses, values, counts)
- CRC: 2 bytes (CRC-16-MODBUS, calculated by ModbusMaster library)

**Inter-frame delay:** Minimum 3.5 character times (handled by ModbusMaster library)

### Holding Registers vs Input Registers

- **Holding registers (0x03 read, 0x06 write):** Read/write — for configuration, setpoints, control
- **Input registers (0x04 read only):** Read-only — for sensor readings, status

Some devices use the same register numbers for both types (e.g., holding register 100 and input register 100 are different physical registers). Consult device manual.

### Coils vs Discrete Inputs

- **Coils (0x01 read, 0x05 write):** Read/write digital outputs (relay control, etc.)
- **Discrete inputs (0x02 read only):** Read-only digital inputs (switch states, etc.)

This firmware implements coil write (0x05). Read coils/discrete inputs not yet implemented (future enhancement).

### Register Addressing: 0-indexed vs 1-indexed

Modbus protocol uses **0-indexed** register addresses (0-65535). Some device manuals use **1-indexed** notation:
- Holding register 40001 = protocol address 0
- Holding register 40100 = protocol address 99
- Input register 30001 = protocol address 0

**Always subtract 1 (or 40001/30001) when converting from manual notation to SCPI command addresses.**

Example: Manual says "read holding register 40005" → use `MODB:READ:HOLD,4,1`

## Future Enhancements

- **Read coils** (function code 0x01)
- **Read discrete inputs** (function code 0x02)
- **Write multiple holding registers** (function code 0x10)
- **Write multiple coils** (function code 0x0F)
- **Read/write 32-bit registers** (two 16-bit registers as one 32-bit value)
- **Floating-point register conversion** (IEEE 754 float from two registers)
- **Automatic retry on timeout** (configurable retry count)
- **Bus scan** (try slave addresses 1-247 and report which respond)
- **MQTT publish** (push Modbus data to MQTT broker for integration with home automation)
- **Web UI** (HTTP server for manual Modbus transactions via browser)

## License

Public domain / CC0. No warranty. Use at your own risk.

## References

- Modbus RTU specification: https://modbus.org/docs/Modbus_over_serial_line_V1_02.pdf
- ModbusMaster library: https://github.com/4-20ma/ModbusMaster
- MAX485 datasheet: https://www.maximintegrated.com/en/products/interface/transceivers/MAX485.html
