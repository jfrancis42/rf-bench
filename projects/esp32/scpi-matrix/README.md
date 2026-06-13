# ESP32 SCPI Signal Routing Matrix

4×4 crosspoint signal routing switch using Standard Commands for Programmable Instruments (SCPI) over TCP/IP. Routes any of 4 input signals to any of 4 output channels with independent relay control at each crosspoint. Multiple connections can be active simultaneously.

## Features

- **SCPI over TCP/IP** on port 5025 (industry standard)
- **4×4 crosspoint matrix** (16 relay-controlled intersections)
- **Multiple simultaneous connections** — any input can feed multiple outputs
- **Individual crosspoint control** — close/open any (row, col) intersection
- **Query matrix state** — read individual crosspoint or full 16-bit state word
- **Standard SCPI ROUTE subsystem** — compatible with test equipment automation
- **WiFi connectivity** with configurable credentials

## Hardware Requirements

- ESP32 development board (any variant with WiFi)
- 16-channel relay board (or 2× 8-channel boards) with 5V coils
- 5V power supply for relay board (2-3A recommended)
- Jumper wires

### Physical Implementation Options

The ESP32 does not have enough GPIO pins to directly drive 16 relays. Choose one of these approaches:

#### Option 1: Shift Registers (recommended for simplicity)
- 2× 74HC595 8-bit shift registers (cascaded for 16 outputs)
- 3 GPIO pins control all 16 relays (data, clock, latch)
- Add ULN2803 or similar transistor array for relay coil drive current

#### Option 2: I2C GPIO Expanders
- 1× MCP23017 (16 GPIO) or 2× MCP23008 (8 GPIO each)
- Uses 2 GPIO pins (SDA, SCL) plus I2C address lines
- Add ULN2803 or transistor array for relay drive

#### Option 3: Direct GPIO (requires GPIO-rich board)
- Use ESP32-S3 or similar with 16+ available GPIO pins
- Requires external relay driver (ULN2803, MOSFET array, etc.)

#### Option 4: Commercial Matrix Board
- Pre-built 4×4 or 8×8 relay matrix module
- Often includes USB or serial control (adapt driver to match)

### Wiring (Conceptual — adapt to your relay driver hardware)

#### Row Select GPIO (4 pins)
| ESP32 GPIO | Function | Controls |
|------------|----------|----------|
| GPIO 25    | Row 1    | Relays connecting row 1 to columns 1-4 |
| GPIO 26    | Row 2    | Relays connecting row 2 to columns 1-4 |
| GPIO 27    | Row 3    | Relays connecting row 3 to columns 1-4 |
| GPIO 14    | Row 4    | Relays connecting row 4 to columns 1-4 |

#### Column Output GPIO (4 pins)
| ESP32 GPIO | Function | Controls |
|------------|----------|----------|
| GPIO 32    | Column 1 | Relays connecting rows 1-4 to column 1 |
| GPIO 33    | Column 2 | Relays connecting rows 1-4 to column 2 |
| GPIO 23    | Column 3 | Relays connecting rows 1-4 to column 3 |
| GPIO 19    | Column 4 | Relays connecting rows 1-4 to column 4 |

**Note:** The GPIO assignments above are logical placeholders. In a real implementation using shift registers or I2C expanders, you'll connect the ESP32 to the driver chip, which then controls the 16 relay coils. Adapt `set_crosspoint()` function to match your hardware.

**Power:** Relay boards require separate 5V supply. 16 relays can draw 1-2A when all energized.

**Active-Low vs Active-High:** Most relay boards are **active-low** (relay energizes when control pin is LOW). The code defaults to active-low. If your board is active-high, change `const bool active_high = false;` to `true`.

## Software Setup

1. **Install Arduino IDE** with ESP32 board support
   - File → Preferences → Additional Board Manager URLs: `https://dl.espressif.com/dl/package_esp32_index.json`
   - Tools → Board → Boards Manager → Search "ESP32" → Install

2. **Configure WiFi credentials**
   - Edit `scpi-matrix.ino`
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
Returns device identification string: `N0GQ,ESP32-SCPI-Matrix,1.0,2026`

### Reset

```
*RST
```
Opens all crosspoints (disconnects all routes).

### Query Matrix Size

```
ROUT:SIZE?
```
Returns matrix dimensions as `rows,cols` (e.g., `4,4`).

### Close Connection (Connect Row to Column)

```
ROUT:CLOS (@row!col)
```

Closes the relay at intersection (row, col), connecting the row input to the column output.

**Examples:**
```
ROUT:CLOS (@1!1)    # Connect row 1 to column 1
ROUT:CLOS (@2!3)    # Connect row 2 to column 3
ROUT:CLOS (@4!2)    # Connect row 4 to column 2
```

**Note:** Rows and columns are **1-indexed** (1-4, not 0-3). The `!` separator is required.

### Open Connection (Disconnect Row from Column)

```
ROUT:OPEN (@row!col)
```

Opens the relay at intersection (row, col), disconnecting the route.

**Examples:**
```
ROUT:OPEN (@1!1)    # Disconnect row 1 from column 1
ROUT:OPEN (@2!3)    # Disconnect row 2 from column 3
```

### Query Individual Crosspoint State

```
ROUT:CLOS? (@row!col)
```

Returns `1` if the crosspoint is closed (connected), `0` if open (disconnected).

**Examples:**
```
ROUT:CLOS? (@1!3)   # Query state of row 1, column 3
```

### Open All Connections

```
ROUT:OPEN:ALL
```

Opens all 16 crosspoints (full disconnect).

### Query Full Matrix State

```
ROUT:STAT?
```

Returns a 16-bit unsigned integer where each bit represents one crosspoint state.

**Bit mapping:**
- Bit 0 → (row 1, col 1)
- Bit 1 → (row 1, col 2)
- Bit 2 → (row 1, col 3)
- Bit 3 → (row 1, col 4)
- Bit 4 → (row 2, col 1)
- ...
- Bit 15 → (row 4, col 4)

**Example:** `ROUT:STAT?` returns `9` (binary `0000000000001001`), meaning crosspoints (1,1) and (4,1) are closed.

### System Error Query

```
SYST:ERR?
```
Returns `0,"No error"` (always, for this simple device).

### Command Format Notes

- Commands can be uppercase or lowercase (case-insensitive)
- Short form allowed: `ROUT:CLOS` instead of `ROUTE:CLOSE`
- Commands terminated with newline (`\n`), carriage return (`\r`), or semicolon (`;`)
- Multiple commands in one line: `ROUT:CLOS (@1!1);ROUT:CLOS (@2!2)`

## Usage Examples

### Telnet (interactive)

```bash
telnet 192.168.1.42 5025
*IDN?
ROUT:SIZE?
ROUT:CLOS (@1!1)
ROUT:CLOS (@1!2)
ROUT:CLOS? (@1!1)
ROUT:STAT?
ROUT:OPEN:ALL
```

### Netcat (command-line)

```bash
echo "ROUT:CLOS (@1!3)" | nc 192.168.1.42 5025
echo "ROUT:CLOS? (@1!3)" | nc 192.168.1.42 5025
echo "ROUT:STAT?" | nc 192.168.1.42 5025
echo "ROUT:OPEN:ALL" | nc 192.168.1.42 5025
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

# Connect row 1 to columns 1 and 3 (fan-out)
scpi_command('192.168.1.42', 5025, 'ROUT:CLOS (@1!1)')
scpi_command('192.168.1.42', 5025, 'ROUT:CLOS (@1!3)')

# Connect rows 2 and 4 to column 2 (fan-in)
scpi_command('192.168.1.42', 5025, 'ROUT:CLOS (@2!2)')
scpi_command('192.168.1.42', 5025, 'ROUT:CLOS (@4!2)')

# Query state of crosspoint (1,1)
state = scpi_command('192.168.1.42', 5025, 'ROUT:CLOS? (@1!1)')
print(f"Crosspoint (1,1) state: {'CLOSED' if state == '1' else 'OPEN'}")

# Query full matrix state
state_word = int(scpi_command('192.168.1.42', 5025, 'ROUT:STAT?'))
print(f"Matrix state (16-bit): {state_word:016b}")

# Disconnect all
scpi_command('192.168.1.42', 5025, 'ROUT:OPEN:ALL')
```

### Python with pyvisa

```python
import pyvisa

rm = pyvisa.ResourceManager('@py')
matrix = rm.open_resource('TCPIP::192.168.1.42::5025::SOCKET',
                          read_termination='\n',
                          write_termination='\n')

print(matrix.query('*IDN?'))

# Get matrix dimensions
rows, cols = matrix.query('ROUT:SIZE?').split(',')
print(f"Matrix: {rows}×{cols}")

# Route row 2 to column 4
matrix.write('ROUT:CLOS (@2!4)')

# Verify
state = matrix.query('ROUT:CLOS? (@2!4)')
print(f"Crosspoint (2,4): {'CLOSED' if state == '1' else 'OPEN'}")

# Disconnect all routes
matrix.write('ROUT:OPEN:ALL')

matrix.close()
```

### Example: Audio Router (4 sources, 4 destinations)

```python
import socket

def route(ip, port, src, dst):
    """Route audio source to destination."""
    cmd = f'ROUT:CLOS (@{src}!{dst})'
    with socket.socket() as s:
        s.connect((ip, port))
        s.sendall((cmd + '\n').encode())

def unroute_all(ip, port):
    """Disconnect all audio routes."""
    with socket.socket() as s:
        s.connect((ip, port))
        s.sendall(b'ROUT:OPEN:ALL\n')

# Connect CD player (row 1) to living room (column 1) and bedroom (column 3)
route('192.168.1.42', 5025, 1, 1)
route('192.168.1.42', 5025, 1, 3)

# Connect radio (row 2) to kitchen (column 2)
route('192.168.1.42', 5025, 2, 2)

# Later: disconnect everything
unroute_all('192.168.1.42', 5025)
```

### Example: RF Antenna Routing (4 radios, 4 antennas)

```python
import socket

def connect_radio_to_antenna(ip, port, radio, antenna):
    """Connect radio (1-4) to antenna (1-4)."""
    with socket.socket() as s:
        s.connect((ip, port))
        # First, disconnect radio from all antennas
        for ant in range(1, 5):
            s.sendall(f'ROUT:OPEN (@{radio}!{ant})\n'.encode())
        # Then connect to desired antenna
        s.sendall(f'ROUT:CLOS (@{radio}!{antenna})\n'.encode())

# Connect radio 1 (IC-7300) to antenna 2 (40m dipole)
connect_radio_to_antenna('192.168.1.42', 5025, 1, 2)

# Connect radio 3 (VHF) to antenna 4 (2m vertical)
connect_radio_to_antenna('192.168.1.42', 5025, 3, 4)
```

### Example: Test Equipment DUT Switching

```python
import socket

class RoutingMatrix:
    def __init__(self, ip, port=5025):
        self.ip = ip
        self.port = port

    def cmd(self, command):
        with socket.socket() as s:
            s.connect((self.ip, self.port))
            s.sendall((command + '\n').encode())
            if '?' in command:
                return s.recv(1024).decode().strip()

    def connect(self, row, col):
        """Connect row input to column output."""
        self.cmd(f'ROUT:CLOS (@{row}!{col})')

    def disconnect(self, row, col):
        """Disconnect row from column."""
        self.cmd(f'ROUT:OPEN (@{row}!{col})')

    def disconnect_all(self):
        """Open all connections."""
        self.cmd('ROUT:OPEN:ALL')

    def is_connected(self, row, col):
        """Check if crosspoint is closed."""
        return self.cmd(f'ROUT:CLOS? (@{row}!{col})') == '1'

    def get_state(self):
        """Get 16-bit state word."""
        return int(self.cmd('ROUT:STAT?'))

# Use in automated test
matrix = RoutingMatrix('192.168.1.42')

# Connect signal generator (row 1) to DUT input (column 1)
matrix.connect(1, 1)

# Connect DUT output (row 2) to oscilloscope (column 2)
matrix.connect(2, 2)

# ... perform measurements ...

# Cleanup
matrix.disconnect_all()
```

## Debugging

- **Serial Monitor (115200 baud)** shows WiFi connection, IP address, and SCPI command log
- **Connection refused:** Check IP address, port (5025), and firewall
- **Relays don't switch:** Verify hardware driver wiring (shift registers, expanders, etc.)
- **Relays switch inverted:** Change `const bool active_high` from `false` to `true`
- **Wrong crosspoint closes:** Check relay indexing in `set_crosspoint()` function
- **Multiple clients:** Only one TCP connection at a time is supported

## Hardware Implementation Notes

The provided code is a **template** — it demonstrates the SCPI command structure but requires hardware-specific relay control logic.

To complete the implementation:

1. Choose a relay driver method (shift registers, I2C expander, etc.)
2. Update `set_crosspoint()` function to control the specific relay at (row, col)
3. If using shift registers, add SPI/bit-bang code to update the relay states
4. If using I2C expanders (MCP23017), include Wire library and I2C transactions
5. Add external relay driver transistors (ULN2803, MOSFETs, etc.) for coil current

**Reference implementations:**
- Shift register relay control: Arduino ShiftOut library
- MCP23017 I2C: Adafruit_MCP23017 library
- Direct GPIO: Similar to `~/rf-bench/projects/esp32/scpi-relay/` (but 16 relays)

## Integration with Test Systems

This SCPI routing matrix integrates with:

- **LabVIEW** via VISA driver (use TCPIP SOCKET resource)
- **MATLAB** via `tcpip` or Instrument Control Toolbox
- **Python** via `pyvisa`, `socket`, or custom drivers
- **Keysight VEE, TestStand, etc.** via standard SCPI/VISA interface

The SCPI ROUTE subsystem commands match industry standards for relay matrices (Keysight 34980A, etc.), making this a drop-in replacement for automated test applications.

## Use Cases

- **RF bench:** Route 4 radios to 4 antennas with arbitrary connections
- **Audio distribution:** 4 audio sources to 4 zones (multiroom audio)
- **Test equipment:** Switch signal generator, DUT, and instruments
- **Video routing:** 4 video sources to 4 displays
- **Sensor switching:** Connect 4 sensors to 4 measurement channels
- **Multi-DUT testing:** Route power supplies, loads, and instruments to multiple devices under test

## License

Public domain. Use freely.

## Author

N0GQ — 2026-06-12
