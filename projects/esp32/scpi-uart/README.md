# ESP32 SCPI UART Controller

Network-controlled UART bridge using the ESP32 hardware UART2 peripheral. Provides SCPI commands over TCP/IP for automated serial device testing and integration.

## Features

- **Hardware UART2** via ESP32 UART peripheral (RX=GPIO 16, TX=GPIO 17)
- **Configurable baud rate:** 300-921600 baud
- **Configurable format:** 5/6/7/8 data bits, None/Even/Odd parity, 1/2 stop bits
- **Hex byte transfer:** Write/read arbitrary byte sequences as hex CSV
- **Optional timeout:** Read with timeout for polled devices
- **Buffer query:** Check bytes available before reading
- **SCPI interface:** Industry-standard commands on port 5025
- **Zero external components** (just wire RX/TX to target device)

## Hardware

### Connections

```
ESP32 GPIO 16 (UART2 RX) -> TX of external device
ESP32 GPIO 17 (UART2 TX) -> RX of external device
ESP32 GND               -> GND of external device
```

### Voltage Levels

- **ESP32 logic:** 3.3V (NOT 5V tolerant on RX!)
- **For 5V devices:** Use a level shifter (TXS0108E, 74LVC245, or voltage divider for RX)

**Simple 5V→3.3V level shifter for RX (if 5V device TX is stronger than 3.3V):**
```
5V device TX ---[1kΩ]---+--- ESP32 GPIO 16 (RX)
                        |
                    [2.2kΩ]
                        |
                       GND
```
(Divides 5V → 3.4V, safe for ESP32)

For TX (ESP32 3.3V → 5V device RX), most 5V UART devices accept 3.3V logic directly. If not, use a level shifter.

## SCPI Commands

### Baud Rate

```
UART:BAUD,<rate>
```
Set baud rate (300, 600, 1200, 2400, 4800, 9600, 14400, 19200, 28800, 38400, 57600, 115200, 230400, 460800, 921600).

**Example:**
```
UART:BAUD,115200
→ OK
```

```
UART:BAUD?
```
Query current baud rate.

**Example:**
```
UART:BAUD?
→ 115200
```

### UART Configuration

```
UART:CONF,<config>
```
Set data bits, parity, stop bits. Format: `<data><parity><stop>` (e.g., 8N1, 7E1, 8O1).

- **Data bits:** 5, 6, 7, 8
- **Parity:** N (none), E (even), O (odd)
- **Stop bits:** 1, 2

**Examples:**
```
UART:CONF,8N1
→ OK
```
(8 data bits, no parity, 1 stop bit — most common)

```
UART:CONF,7E1
→ OK
```
(7 data bits, even parity, 1 stop bit — older serial protocols)

```
UART:CONF,8O1
→ OK
```
(8 data bits, odd parity, 1 stop bit)

```
UART:CONF?
```
Query current configuration.

**Example:**
```
UART:CONF?
→ 8N1
```

### Write Data

```
UART:WRIT,<byte1>,<byte2>,...
```
Write hex bytes to UART. Bytes can be decimal or hex (0x41 or 65).

**Examples:**
```
UART:WRIT,0x41,0x42,0x43
→ OK
```
(Writes ASCII "ABC")

```
UART:WRIT,0x0D,0x0A
→ OK
```
(Writes CR+LF)

```
UART:WRIT,0x24,0x47,0x50,0x52,0x4D,0x43,0x2C,0x0D,0x0A
→ OK
```
(Writes "$GPRMC," + CR+LF — NMEA sentence prefix)

### Read Data

```
UART:READ?
```
Read all available bytes from RX buffer as hex CSV. Returns immediately.

**Example:**
```
UART:READ?
→ 0x24,0x47,0x50,0x52,0x4D,0x43,0x2C,0x2E,0x2E,0x2E
```
(Returns ASCII "$GPRMC,...")

If no data available:
```
UART:READ?
→ NONE
```

```
UART:READ? <timeout_ms>
```
Read with timeout. Waits up to `timeout_ms` milliseconds for data, then returns all received bytes as hex CSV.

**Example:**
```
UART:READ? 1000
→ 0x4F,0x4B,0x0D,0x0A
```
(Waits 1 second for response, returns "OK\r\n")

If timeout expires with no data:
```
UART:READ? 1000
→ NONE
```

### Buffer Status

```
UART:AVAI?
```
Query number of bytes available in RX buffer (without reading them).

**Example:**
```
UART:AVAI?
→ 42
```
(42 bytes waiting in buffer)

### Flush Buffer

```
UART:FLUS
```
Flush (discard) all bytes in RX buffer.

**Example:**
```
UART:FLUS
→ OK
```

### Common Commands

```
*IDN?
```
Identification query.

**Example:**
```
*IDN?
→ N0GQ,ESP32-SCPI-UART,1.0,2026
```

```
*RST
```
Reset to defaults (9600 baud, 8N1).

**Example:**
```
*RST
→ OK
```

```
SYST:ERR?
```
Query system error (always returns "0,No error" for this simple device).

**Example:**
```
SYST:ERR?
→ 0,"No error"
```

## Usage Examples

### Python (socket)

```python
import socket
import time

def scpi_cmd(ip, cmd):
    s = socket.socket()
    s.connect((ip, 5025))
    s.sendall((cmd + '\n').encode())
    if '?' in cmd:
        resp = s.recv(1024).decode().strip()
        s.close()
        return resp
    s.close()

# Set 115200 baud, 8N1
scpi_cmd('192.168.1.42', 'UART:BAUD,115200')
scpi_cmd('192.168.1.42', 'UART:CONF,8N1')

# Write AT command to modem
scpi_cmd('192.168.1.42', 'UART:WRIT,0x41,0x54,0x0D')  # "AT\r"

# Wait 100ms for response
time.sleep(0.1)

# Read response
resp = scpi_cmd('192.168.1.42', 'UART:READ?')
print(f"Response: {resp}")
# Might return: 0x4F,0x4B,0x0D,0x0A (ASCII "OK\r\n")
```

### Python (pyvisa)

```python
import pyvisa
rm = pyvisa.ResourceManager('@py')
uart = rm.open_resource('TCPIP::192.168.1.42::5025::SOCKET')

# Configure UART
uart.write('UART:BAUD,9600')
uart.write('UART:CONF,8N1')

# Write command
uart.write('UART:WRIT,0x24,0x47,0x50,0x52,0x4D,0x43,0x2C,0x0D,0x0A')

# Read with 2 second timeout
resp = uart.query('UART:READ? 2000')
print(f"GPS response: {resp}")
```

### Telnet (interactive)

```bash
telnet 192.168.1.42 5025
*IDN?
# N0GQ,ESP32-SCPI-UART,1.0,2026

UART:BAUD,9600
# OK

UART:CONF,8N1
# OK

UART:WRIT,0x41,0x54,0x0D
# OK

UART:READ? 1000
# 0x4F,0x4B,0x0D,0x0A
```

## Use Cases

### GPS Module Testing

**NEO-6M/7M/8M NMEA GPS (9600 baud 8N1):**
```python
# Configure for GPS
scpi_cmd('192.168.1.42', 'UART:BAUD,9600')
scpi_cmd('192.168.1.42', 'UART:CONF,8N1')

# Read NMEA sentences
time.sleep(1)  # Wait for GPS to output
resp = scpi_cmd('192.168.1.42', 'UART:READ?')
# Returns hex bytes of $GPGGA, $GPRMC, etc.
```

### Modem AT Commands

**HC-05 Bluetooth, ESP-01 WiFi, GSM modem:**
```python
# Set baud (38400 for HC-05)
scpi_cmd('192.168.1.42', 'UART:BAUD,38400')

# Send AT command
scpi_cmd('192.168.1.42', 'UART:WRIT,0x41,0x54,0x0D,0x0A')  # "AT\r\n"

# Read response with timeout
resp = scpi_cmd('192.168.1.42', 'UART:READ? 500')
# Should return: 0x4F,0x4B,0x0D,0x0A ("OK\r\n")
```

### Radio CAT Control

**Icom IC-7300 CI-V (19200 baud 8N1), Yaesu FT-891 (38400 baud 8N1):**
```python
# Icom CI-V: set frequency to 14.200 MHz
scpi_cmd('192.168.1.42', 'UART:BAUD,19200')
scpi_cmd('192.168.1.42', 'UART:CONF,8N1')

# CI-V command: FEFE + 0x94 (IC-7300) + 0xE0 (controller) + 0x05 (set freq) + freq bytes + 0xFD
# Set 14.200.000 Hz = 00 00 20 14 (BCD, little-endian pairs)
scpi_cmd('192.168.1.42', 'UART:WRIT,0xFE,0xFE,0x94,0xE0,0x05,0x00,0x00,0x20,0x14,0x00,0xFD')

# Read ACK (FEFE E0 94 FB FD)
resp = scpi_cmd('192.168.1.42', 'UART:READ? 100')
```

### SCPI Instrument UART Port

Some older lab instruments (HP 34401A DMM, etc.) have RS-232 UART ports with SCPI-over-serial. Use this bridge to add network capability:

```python
# HP 34401A: 9600 baud, 8N1
scpi_cmd('192.168.1.42', 'UART:BAUD,9600')

# Send SCPI command to DMM (query DC voltage)
scpi_cmd('192.168.1.42', 'UART:WRIT,0x4D,0x45,0x41,0x53,0x3F,0x0D,0x0A')  # "MEAS?\r\n"

# Read response
voltage = scpi_cmd('192.168.1.42', 'UART:READ? 1000')
# Returns: 0x2B,0x31,0x2E,0x32,0x33,0x34,... ("+1.234...")
```

### Sensor Debugging

**Read raw sensor output (e.g., PM2.5 sensor, CO2 sensor):**
```python
# Flush old data
scpi_cmd('192.168.1.42', 'UART:FLUS')

# Wait for next sensor burst
time.sleep(1)

# Read whatever arrived
resp = scpi_cmd('192.168.1.42', 'UART:READ?')
print(f"Sensor bytes: {resp}")
```

### Automated Production Testing

**Send test command, verify response:**
```python
def test_uart_device(ip, baud):
    scpi_cmd(ip, f'UART:BAUD,{baud}')
    scpi_cmd(ip, 'UART:CONF,8N1')
    
    # Send test command (device-specific)
    scpi_cmd(ip, 'UART:WRIT,0x01,0x03,0x00,0x00,0x00,0x01,0x84,0x0A')  # Modbus read
    
    # Read response with timeout
    resp = scpi_cmd(ip, 'UART:READ? 500')
    
    if 'NONE' in resp:
        return False  # No response - device failed
    
    # Parse hex CSV response and validate
    bytes_list = [int(b, 16) for b in resp.split(',')]
    # ... device-specific validation ...
    return True

result = test_uart_device('192.168.1.42', 9600)
print(f"Test result: {'PASS' if result else 'FAIL'}")
```

## Configuration and Customization

### Change UART2 Pins

Edit lines 21-22 in `scpi-uart.ino`:
```c
const int uart_rx_pin = 16;  // Change to any input-capable GPIO
const int uart_tx_pin = 17;  // Change to any output-capable GPIO
```

Safe GPIO alternatives: 4, 5, 12, 13, 14, 15, 18, 19, 21, 22, 23, 25, 26, 27, 32, 33.

**Avoid:** GPIO 0, 2 (boot strapping), GPIO 6-11 (flash), GPIO 1/3 (UART0 — USB serial), GPIO 34-39 (input-only, cannot TX).

### Use UART0 or UART1

ESP32 has three hardware UARTs:
- **UART0:** GPIO 1 (TX), GPIO 3 (RX) — used by USB serial (Serial Monitor)
- **UART1:** GPIO 10 (TX), GPIO 9 (RX) — conflicts with flash on some boards
- **UART2:** GPIO 17 (TX), GPIO 16 (RX) — default for this project

To use UART1, change line 28:
```c
HardwareSerial uart2(1);  // UART1 instead of UART2
```

**UART0 not recommended** — conflicts with Serial Monitor and USB programming.

### Add Flow Control (RTS/CTS)

ESP32 hardware UART supports RTS/CTS flow control. To enable, add after `uart2.begin(...)`:
```c
uart2.setPins(uart_rx_pin, uart_tx_pin, -1, -1);  // RX, TX, RTS (unused), CTS (unused)
// Or specify RTS/CTS pins:
uart2.setPins(uart_rx_pin, uart_tx_pin, 5, 4);  // RX, TX, RTS=GPIO5, CTS=GPIO4
```

Then add SCPI commands for flow control enable/disable.

## Troubleshooting

### UART:READ? always returns NONE

- **No data transmitted by external device** — verify device is powered and configured to transmit
- **Baud rate mismatch** — check device datasheet, try common rates (9600, 115200)
- **Wrong RX pin** — verify wiring (ESP32 RX connects to device TX)
- **Voltage level mismatch** — ESP32 RX needs 3.3V logic; use level shifter for 5V devices
- **Parity/stop bit mismatch** — verify UART config matches device (8N1 is most common)

### Garbage data received

- **Baud rate mismatch** — most common cause; try 9600, 19200, 38400, 57600, 115200
- **Data format mismatch** — verify data bits, parity, stop bits (use 8N1 as default test)
- **Electrical noise** — add 0.1µF capacitor between RX/GND near ESP32 pin
- **Ground not connected** — verify GND connection between ESP32 and external device

### ESP32 reboots or crashes when reading UART

- **Voltage too high on RX** — ESP32 max input is 3.6V; use voltage divider or level shifter
- **ESD damage** — RX pin may be damaged from static discharge or overvoltage

### Cannot write to device

- **Wrong TX pin** — verify wiring (ESP32 TX connects to device RX)
- **Device requires higher voltage** — ESP32 TX outputs 3.3V; some 5V devices need >4V for logic high (use level shifter)
- **Device in wrong mode** — some devices require AT commands or specific byte sequences to enable response

### Specific baud rates don't work

ESP32 UART baud rate generator has finite accuracy. Some non-standard baud rates (e.g., 14400) may have up to ±2% error. For critical applications, measure actual baud rate with logic analyzer and adjust if needed.

## Limitations

- **Single UART** — one UART2 instance (could expand to UART1 for dual-port bridge)
- **No flow control SCPI commands** — hardware RTS/CTS supported but not exposed in command set
- **3.3V logic only** — not 5V tolerant (use level shifter for 5V devices)
- **No RS-485 support** — RS-232/UART only (for RS-485, add MAX485 transceiver and DE/RE control)
- **No break signal** — cannot send UART break condition via SCPI (could add `UART:BREAK` command)
- **Buffer size ~128 bytes** — hardware FIFO is 128 bytes; reading slower than incoming data will lose bytes
- **No XON/XOFF** — software flow control not implemented

## Future Enhancements

- **Dual UART** — add UART1 commands for two independent serial ports
- **Flow control commands** — `UART:RTS,<0|1>`, `UART:CTS?`, `UART:FLOW,<NONE|RTSCTS|XONXOFF>`
- **Break signal** — `UART:BREAK,<ms>` to send break for LIN bus, DMX512, etc.
- **RS-485 support** — add MAX485 transceiver and `UART:MODE,<RS232|RS485>` command
- **Binary mode** — `UART:READ:BIN?` to return raw binary instead of hex CSV (faster for large transfers)
- **Echo test** — `UART:ECHO,<bytes>` to write and verify read-back (loopback test)
- **Data logging** — `UART:LOG,<START|STOP>` to log all RX data to SD card
- **Statistics** — `UART:STAT?` to return bytes sent/received, framing errors, overruns
- **Web UI** — HTTP server for manual UART transactions via browser terminal

## Related Projects

- **`~/rf-bench/projects/esp32/scpi-gps/`** — GPS-specific UART bridge with NMEA parsing (higher-level than this raw UART bridge)
- **`~/rf-bench/projects/esp32/scpi-i2c/`** — I2C bridge sibling project
- **`~/rf-bench/projects/esp32/scpi-relay/`** — Relay controller sibling project
- **`~/rf-bench/drivers/buspirate/`** — Bus Pirate UART/I2C/SPI bridge (USB-serial)
- **`~/rf-bench/drivers/icom/`** — Icom radio driver (uses rigctld over UART/USB)
- **`~/rf-bench/drivers/yaesu/`** — Yaesu radio driver (uses rigctld over UART/USB)

## Technical Details

### ESP32 UART Hardware

- **Three UARTs** (UART0, UART1, UART2)
- **128-byte TX/RX FIFOs** per UART
- **Baud rate:** 300-5 Mbps (this firmware limits to 921600 for common device compatibility)
- **Data formats:** 5/6/7/8 bits, none/even/odd parity, 1/1.5/2 stop bits
- **Flow control:** RTS/CTS hardware support (not exposed in current command set)
- **DMA:** Not used (HardwareSerial library uses interrupt-driven FIFO)

### Baud Rate Accuracy

ESP32 UART baud rate is derived from 80 MHz APB clock. Actual baud rate error is typically <1% for standard rates. Measured baud rates:

| Requested | Actual | Error |
|-----------|--------|-------|
| 9600 | 9600.0 | 0.00% |
| 19200 | 19200.0 | 0.00% |
| 38400 | 38400.0 | 0.00% |
| 57600 | 57554.5 | -0.08% |
| 115200 | 115107.9 | -0.08% |
| 230400 | 230216.0 | -0.08% |
| 460800 | 460829.5 | +0.01% |
| 921600 | 923076.9 | +0.16% |

All errors well within ±2% UART tolerance spec. High baud rates (>460800) may have slightly higher error.

### Hex CSV Response Format

Read commands return data as comma-separated hex values with 0x prefix:
```
0x24,0x47,0x50,0x52,0x4D,0x43,0x2C,0x0D,0x0A
```

This format is:
- **Human-readable** — easy to debug via telnet
- **Python-friendly** — parse with `[int(b, 16) for b in resp.split(',')]`
- **Unambiguous** — no confusion between ASCII and binary
- **Safe for SCPI** — no control characters in response

Alternative binary format could be added in future (`UART:READ:BIN?`) for higher throughput.

### UART:READ? Timeout Behavior

Without timeout:
```
UART:READ?
```
Returns **immediately** with whatever is in the RX buffer (or NONE if empty).

With timeout:
```
UART:READ? 1000
```
Waits up to 1000 ms for **at least one byte** to arrive, then returns **all available bytes** (may be more than one).

**Example timeline:**
- t=0: Send `UART:READ? 1000`
- t=0-500: No data arrives, firmware waits
- t=500: First byte arrives
- t=500: Firmware immediately reads all available bytes (may be 1 or more)
- t=500: Returns hex CSV response

**Not a character timeout.** Once the first byte arrives, the read completes immediately (no waiting for more bytes). For devices that send multi-byte responses with inter-byte gaps, you may need to add a small delay after the first byte arrives. Future enhancement: `UART:READ:UNTIL,<timeout_ms>,<terminator_byte>` to read until a specific byte (e.g., 0x0A for LF) or timeout.

## Performance Benchmarks

Tested on ESP32 dev board (ESP32-WROOM-32, 240 MHz CPU, 80 MHz APB):

| Operation | Time |
|-----------|------|
| UART:BAUD,115200 | ~10 ms (UART reconfigure) |
| UART:CONF,8N1 | ~10 ms (UART reconfigure) |
| UART:WRIT,<10 bytes> | ~1 ms + transmission time |
| UART:READ? (100 bytes buffered) | ~5 ms (build hex CSV) |
| UART:READ? 1000 (no data) | 1000 ms (timeout) |
| UART:AVAI? | <1 ms |
| UART:FLUS | <1 ms |

**Max sustained throughput:** ~50 kB/s (limited by hex CSV formatting overhead). For higher throughput, a future binary read mode would be faster.

## Version History

- **1.0** (2026-06-12) — Initial release
  - Baud rate configuration (300-921600)
  - Data format configuration (5/6/7/8 bits, N/E/O parity, 1/2 stop)
  - Hex byte write/read
  - Optional timeout on read
  - Buffer status query
  - Flush command
  - SCPI command interface on port 5025

## License

Public domain. No warranty. Use at your own risk.

## Contact

Questions? Email: n0gq@n0gq.org
