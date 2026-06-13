# ESP32 SCPI Relay Controller

Network-controlled 4-channel relay board using Standard Commands for Programmable Instruments (SCPI) over TCP/IP.

## Features

- **SCPI over TCP/IP** on port 5025 (industry standard)
- **4 independent relay outputs** with individual control
- **4 digital inputs** (3.3V logic, pulled-down, read HIGH/LOW state)
- **1 analog input** (0-3.3V, 12-bit ADC, returns voltage or raw counts)
- **WiFi connectivity** with configurable credentials
- **Active-low/active-high** relay board support (configurable)
- **Standard SCPI commands** compatible with test equipment automation
- **Query all I/O states** for verification and monitoring

## Hardware Requirements

- ESP32 development board (any variant with WiFi)
- 4-channel relay module (typical Amazon/AliExpress 5V relay board)
- 5V power supply for relay board
- Jumper wires

### Wiring

#### Relay Outputs

| ESP32 GPIO | Relay Board Pin | Function |
|------------|----------------|----------|
| GPIO 25    | IN1            | Relay 1 output |
| GPIO 26    | IN2            | Relay 2 output |
| GPIO 27    | IN3            | Relay 3 output |
| GPIO 14    | IN4            | Relay 4 output |
| GND        | GND            | Ground   |

**Power:** Most relay boards require separate 5V power (VCC and GND). The ESP32 GPIO pins provide only control signals, not relay coil power.

**Active-Low vs Active-High:** Most cheap relay boards are **active-low** (relay energizes when GPIO is LOW). The code defaults to active-low. If your board is active-high, change `const bool active_high = false;` to `true` in the source.

#### Digital Inputs

| ESP32 GPIO | Function | Logic Levels |
|------------|----------|--------------|
| GPIO 32    | Digital Input 1 | 0V = LOW (0), 3.3V = HIGH (1) |
| GPIO 33    | Digital Input 2 | 0V = LOW (0), 3.3V = HIGH (1) |
| GPIO 35    | Digital Input 3 | 0V = LOW (0), 3.3V = HIGH (1) |
| GPIO 34    | Digital Input 4 | 0V = LOW (0), 3.3V = HIGH (1) |

**Pull-down enabled:** Inputs read LOW (0) when floating. Connect to 3.3V to read HIGH (1). **DO NOT exceed 3.3V** — ESP32 GPIOs are not 5V tolerant. Use a voltage divider if interfacing with 5V logic.

#### Analog Input

| ESP32 GPIO | Function | Range |
|------------|----------|-------|
| GPIO 36 (ADC1_CH0) | Analog Input | 0-3.3V (12-bit: 0-4095 counts) |

**Voltage range:** 0-3.3V maximum. The ADC is configured with 11dB attenuation for full-scale 3.3V reading. **DO NOT exceed 3.3V** — overvoltage will damage the ESP32.

## Software Setup

1. **Install Arduino IDE** with ESP32 board support
   - File → Preferences → Additional Board Manager URLs: `https://dl.espressif.com/dl/package_esp32_index.json`
   - Tools → Board → Boards Manager → Search "ESP32" → Install

2. **Configure WiFi credentials**
   - Edit `scpi-relay.ino`
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
Returns device identification string: `N0GQ,ESP32-SCPI-Relay,1.0,2026`

### Reset

```
*RST
```
Turns off all relays (reset to safe state).

### Control Individual Relays

```
ROUTE:CLOSE (@1)        # Turn on relay 1
ROUTE:CLOSE (@2)        # Turn on relay 2
ROUTE:CLOSE (@3)        # Turn on relay 3
ROUTE:CLOSE (@4)        # Turn on relay 4

ROUTE:OPEN (@1)         # Turn off relay 1
ROUTE:OPEN (@2)         # Turn off relay 2
ROUTE:OPEN (@3)         # Turn off relay 3
ROUTE:OPEN (@4)         # Turn off relay 4
```

**Note:** SCPI relay numbers are 1-indexed (1-4), not 0-indexed.

### Control All Relays

```
ROUTE:CLOSE:ALL         # Turn on all relays
ROUTE:OPEN:ALL          # Turn off all relays
```

### Query Relay State

```
ROUTE:CLOSE:STATE? (@1)  # Returns 1 if relay 1 is on, 0 if off
ROUTE:CLOSE:STATE? (@2)  # Query relay 2 state
ROUTE:CLOSE:STATE? (@3)  # Query relay 3 state
ROUTE:CLOSE:STATE? (@4)  # Query relay 4 state
```

### Read Digital Inputs

```
MEAS:DIG? (@1)           # Read digital input 1 (returns 0 or 1)
MEAS:DIG? (@2)           # Read digital input 2
MEAS:DIG? (@3)           # Read digital input 3
MEAS:DIG? (@4)           # Read digital input 4

MEAS:DIG:ALL?            # Read all 4 digital inputs (returns "0,1,0,1")
```

**Returns:** `0` = LOW (0V/floating), `1` = HIGH (3.3V connected)

### Read Analog Input

```
MEAS:VOLT?               # Read analog input in volts (e.g., "2.4567")
MEAS:VOLT:RAW?           # Read raw ADC counts 0-4095 (e.g., "3021")
```

**Voltage formula:** `voltage = (raw_counts / 4095) × 3.3V`

### System Error Query

```
SYST:ERR?
```
Returns `0,"No error"` (always, for this simple device).

### Command Format Notes

- Commands can be uppercase or lowercase (case-insensitive)
- Short form allowed: `ROUT:CLOS` instead of `ROUTE:CLOSE`
- Commands can be terminated with newline (`\n`), carriage return (`\r`), or semicolon (`;`)
- Multiple commands can be sent in one line separated by semicolons: `ROUT:CLOS (@1);ROUT:CLOS (@2)`

## Usage Examples

### Telnet (interactive)

```bash
telnet 192.168.1.42 5025
*IDN?
ROUTE:CLOSE (@1)
ROUTE:CLOSE:STATE? (@1)
MEAS:DIG? (@1)
MEAS:VOLT?
ROUTE:OPEN (@1)
```

### Netcat (command-line)

```bash
echo "ROUTE:CLOSE (@1)" | nc 192.168.1.42 5025
echo "MEAS:VOLT?" | nc 192.168.1.42 5025
echo "MEAS:DIG:ALL?" | nc 192.168.1.42 5025
echo "ROUTE:OPEN:ALL" | nc 192.168.1.42 5025
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

# Turn on relay 1
scpi_command('192.168.1.42', 5025, 'ROUTE:CLOSE (@1)')

# Query relay 1 state
state = scpi_command('192.168.1.42', 5025, 'ROUTE:CLOSE:STATE? (@1)')
print(f"Relay 1 state: {state}")

# Read analog voltage
voltage = scpi_command('192.168.1.42', 5025, 'MEAS:VOLT?')
print(f"Analog input: {voltage}V")

# Read all digital inputs
dig_inputs = scpi_command('192.168.1.42', 5025, 'MEAS:DIG:ALL?')
print(f"Digital inputs: {dig_inputs}")

# Turn off all relays
scpi_command('192.168.1.42', 5025, 'ROUTE:OPEN:ALL')
```

### Python with pyvisa (instrument automation)

If you have `pyvisa` and `pyvisa-py` installed:

```python
import pyvisa

rm = pyvisa.ResourceManager('@py')
relay = rm.open_resource('TCPIP::192.168.1.42::5025::SOCKET', 
                         read_termination='\n',
                         write_termination='\n')

print(relay.query('*IDN?'))
relay.write('ROUTE:CLOSE (@1)')
state = relay.query('ROUTE:CLOSE:STATE? (@1)')
print(f"Relay 1 is {'ON' if state == '1' else 'OFF'}")

# Read inputs
voltage = float(relay.query('MEAS:VOLT?'))
print(f"Analog input: {voltage:.3f}V")

dig_state = relay.query('MEAS:DIG? (@1)')
print(f"Digital input 1: {'HIGH' if dig_state == '1' else 'LOW'}")

relay.close()
```

### Complete Test Script

A complete test script `test_io.py` is included that demonstrates all functionality:

```bash
# Edit the IP address in test_io.py first, then run:
python3 test_io.py
```

This script:
- Identifies the device
- Tests all 4 relays (turn on, verify, turn off)
- Reads all 4 digital inputs
- Reads analog input (voltage and raw ADC counts)
- Continuously monitors inputs for 5 seconds
- Resets all relays to off

## Debugging

- **Serial Monitor (115200 baud)** shows WiFi connection status, IP address, and received SCPI commands
- **Connection refused:** Check IP address, port number (5025), and firewall settings
- **Relays don't switch:** Verify GPIO wiring and check `active_high` setting in code
- **Relays switch inverted:** Change `const bool active_high` from `false` to `true` (or vice versa)
- **Digital inputs always read LOW:** Check 3.3V connection and pull-down resistor configuration
- **Digital inputs always read HIGH:** Wiring short to 3.3V, or `INPUT_PULLDOWN` should be `INPUT_PULLUP` (but pull-down is correct default)
- **Analog input reads 0V or 3.3V when mid-range expected:** Check ADC attenuation setting (`ADC_11db` for 0-3.3V full scale)
- **Analog input noisy/inaccurate:** ESP32 ADC has known non-linearity; consider external ADC (ADS1115) for precision
- **5V logic damage warning:** ESP32 is NOT 5V tolerant! Use voltage divider (e.g., 2.2kΩ + 3.3kΩ) for 5V → 3.3V level shifting

## Integration with Test Systems

This SCPI relay controller integrates with:

- **LabVIEW** via VISA driver (use TCPIP SOCKET resource)
- **MATLAB** via `tcpip` or Instrument Control Toolbox
- **Python** via `pyvisa`, `socket`, or `PySerial`
- **Keysight VEE, TestStand, etc.** via standard SCPI/VISA interface

The standard SCPI command set and ROUTE subsystem make this compatible with automated test equipment (ATE) frameworks.

## License

Public domain. Use freely.

## Author

N0GQ — 2026-06-12
