# ESP32 SCPI Infrared TX/RX Controller

Network-controlled infrared transceiver using Standard Commands for Programmable Instruments (SCPI) over TCP/IP. Send and receive IR remote control signals for automation and reverse engineering.

## Features

- **SCPI over TCP/IP** on port 5025 (industry standard)
- **IR transmit** with hardware PWM carrier generation (36-60 kHz configurable)
- **IR receive** with interrupt-driven edge timing capture (TSOP38238 receiver)
- **Multiple protocols**: NEC, RC5, Sony SIRC, raw timings
- **WiFi connectivity** with configurable credentials
- **Circular RX buffer** holds up to 16 captured IR frames
- **Standard SCPI commands** compatible with test equipment automation

## Hardware Requirements

- ESP32 development board (any variant with WiFi)
- IR LED (940nm, clear case)
- 100-220Ω current-limiting resistor for IR LED
- TSOP38238 IR receiver module (or similar 38 kHz demodulating receiver)
- Breadboard and jumper wires

### Wiring

#### IR LED (Transmitter)

| ESP32 GPIO | Component | Notes |
|------------|-----------|-------|
| GPIO 25    | IR LED anode (via 100-220Ω resistor) | PWM carrier output |
| GND        | IR LED cathode | Common ground |

**Resistor selection:**
- 100Ω: ~15mA drive current (brighter, shorter range ~5m)
- 150Ω: ~10mA drive current (balanced, ~3m range)
- 220Ω: ~7mA drive current (dimmer, ~2m range)

**Power:** ESP32 GPIO can source ~20mA max. For longer range (>5m), use a transistor driver (2N2222 NPN) and external 5V supply.

**LED polarity:** Clear IR LEDs usually have the shorter leg = cathode (to GND), longer leg = anode (to resistor). Verify with datasheet or test with a camera (IR LED will glow purple/white on phone camera when forward-biased).

#### TSOP38238 IR Receiver

| ESP32 GPIO | TSOP38238 Pin | Notes |
|------------|---------------|-------|
| GPIO 26    | OUT           | Demodulated IR signal (active-low) |
| 3.3V       | VCC           | Power (3.3V or 5V, 3.3V works fine) |
| GND        | GND           | Common ground |

**TSOP38238 pinout (facing front bulge):**
```
   ___
  |   |   Left: OUT
  |   |   Center: GND
  |   |   Right: VCC
  |___|
```

**Note:** TSOP38238 output is **active-low** and has built-in AGC and bandpass filter centered at 38 kHz. It demodulates the carrier automatically, so the ESP32 sees only the modulation envelope (mark/space timing edges).

**Alternative receivers:** TSOP4838, VS1838B, IRM-3638T all work identically (38 kHz center frequency, active-low output, 3-pin package).

## Software Setup

1. **Install Arduino IDE** with ESP32 board support
   - File → Preferences → Additional Board Manager URLs: `https://dl.espressif.com/dl/package_esp32_index.json`
   - Tools → Board → Boards Manager → Search "ESP32" → Install

2. **Configure WiFi credentials**
   - Edit `scpi-ir.ino`
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
Returns device identification string: `N0GQ,ESP32-SCPI-IR,1.0,2026`

### Reset

```
*RST
```
Clears the RX buffer (discards all captured IR frames).

### Transmit Commands

#### Send NEC Protocol

```
IR:SEND:NEC,<address>,<command>
```

**NEC protocol:** Most common IR protocol (used by TVs, air conditioners, generic remotes). 32-bit format with address, inverted address, command, inverted command.

**Examples:**
```
IR:SEND:NEC,0,12        # Address 0, command 12 (typical TV power)
IR:SEND:NEC,4,21        # Address 4, command 21
IR:SEND:NEC,255,128     # Address 255, command 128
```

**Range:** Address 0-255 (8-bit), Command 0-255 (8-bit)

#### Send RC5 Protocol

```
IR:SEND:RC5,<address>,<command>
```

**RC5 protocol:** Philips standard, Manchester-encoded, 13-bit format. Common in older European equipment.

**Examples:**
```
IR:SEND:RC5,0,12        # Address 0 (TV), command 12 (power)
IR:SEND:RC5,5,16        # Address 5 (VCR), command 16
```

**Range:** Address 0-31 (5-bit), Command 0-63 (6-bit)

**Note:** Toggle bit is currently fixed (not auto-toggled between presses). For proper RC5 operation, toggle bit should flip on each button press.

#### Send Sony SIRC Protocol

```
IR:SEND:SONY,<address>,<command>,<bits>
```

**Sony SIRC protocol:** 3 variants (12-bit, 15-bit, 20-bit). Used by Sony TVs, A/V equipment.

**Examples:**
```
IR:SEND:SONY,1,21,12    # 12-bit SIRC: device 1, command 21
IR:SEND:SONY,48,21,15   # 15-bit SIRC: device 48, command 21
IR:SEND:SONY,1,21,20    # 20-bit SIRC: device 1, command 21
```

**Range:**
- 12-bit: Address 0-31 (5-bit), Command 0-127 (7-bit)
- 15-bit: Address 0-255 (8-bit), Command 0-127 (7-bit)
- 20-bit: Address 0-8191 (13-bit), Command 0-127 (7-bit)

**Note:** Sony remotes typically send each code 3 times (with ~25ms gap). This firmware sends once — caller should repeat if needed.

#### Send Raw Timings

```
IR:SEND:RAW,<freq_hz>,<us1>,<us2>,<us3>,...
```

Send arbitrary mark/space timings at a specified carrier frequency. Alternates mark (carrier on) and space (carrier off).

**Examples:**
```
IR:SEND:RAW,38000,9000,4500,560,560,560,1690  # NEC-like header + 2 bits
IR:SEND:RAW,36000,2400,600,600,600,600,1200   # Sony-like at 36 kHz
```

**Parameters:**
- `freq_hz`: Carrier frequency in Hz (30000-60000 typical; 38000 most common)
- `us1,us2,...`: Mark/space durations in microseconds (even index = mark, odd = space)

**Use case:** Replay captured unknown protocols, generate arbitrary IR waveforms, test IR receiver sensitivity.

### Receive Commands

#### Read Next Decoded Frame

```
IR:RECV?
```

Returns the next decoded frame from the circular buffer, then removes it.

**Response formats:**
- `NEC,<address>,<command>` — NEC protocol frame
- `RAW,<count>` — Unknown protocol, raw timings available
- `EMPTY` — No frames in buffer

**Examples:**
```
IR:RECV?
NEC,0,12

IR:RECV?
RAW,68

IR:RECV?
EMPTY
```

**Note:** Frames are consumed (FIFO). If buffer fills (16 frames), oldest frames are overwritten.

#### Read Raw Timings from Last Frame

```
IR:RECV:RAW?
```

Returns comma-separated list of edge timings (in microseconds) for the last frame read by `IR:RECV?`, then removes it from the buffer.

**Response format:**
- `<us1>,<us2>,<us3>,...\n` — Mark/space durations (even index = mark, odd = space)
- `EMPTY` — No frames in buffer

**Example:**
```
IR:RECV:RAW?
9000,4500,560,560,560,1690,560,560,560,1690,...
```

**Use case:** Capture and replay unknown protocols via raw timings, analyze timing variations, reverse-engineer proprietary remotes.

#### Query Frames Available

```
IR:AVAI?
```

Returns the number of frames currently in the RX buffer (0-16).

**Example:**
```
IR:AVAI?
3
```

**Use case:** Poll before reading to avoid `EMPTY` responses, or use in automation to wait for IR traffic.

### Carrier Frequency Commands

#### Set Carrier Frequency

```
IR:CARR,<khz>
```

Set the IR carrier frequency in kHz (30-60 kHz range supported).

**Examples:**
```
IR:CARR,36          # 36 kHz carrier (some Panasonic equipment)
IR:CARR,38          # 38 kHz carrier (most common)
IR:CARR,40          # 40 kHz carrier (some RCA equipment)
IR:CARR,56          # 56 kHz carrier (rare, some B&O equipment)
```

**Default:** 38 kHz (most universal)

**Note:** TSOP38238 receiver is centered at 38 kHz ±2 kHz. It will still receive 36 kHz and 40 kHz signals (with reduced sensitivity). For 56 kHz, use a TSOP4856 receiver instead.

#### Query Carrier Frequency

```
IR:CARR?
```

Returns current carrier frequency in kHz.

**Example:**
```
IR:CARR?
38
```

### System Error Query

```
SYST:ERR?
```
Returns `0,"No error"` (always, for this simple device).

### Command Format Notes

- Commands can be uppercase or lowercase (case-insensitive)
- Commands can be terminated with newline (`\n`), carriage return (`\r`), or semicolon (`;`)
- Multiple commands can be sent in one line separated by semicolons: `IR:SEND:NEC,0,12;IR:AVAI?`

## Usage Examples

### Telnet (interactive)

```bash
telnet 192.168.1.42 5025
*IDN?
IR:SEND:NEC,0,12
IR:AVAI?
IR:RECV?
```

### Netcat (command-line)

```bash
echo "IR:SEND:NEC,0,12" | nc 192.168.1.42 5025
echo "IR:AVAI?" | nc 192.168.1.42 5025
echo "IR:RECV?" | nc 192.168.1.42 5025
```

### Python (Basic)

```python
import socket

def scpi_command(ip, port, command):
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.connect((ip, port))
        s.sendall((command + '\n').encode())
        if '?' in command:
            response = s.recv(1024).decode().strip()
            return response

# Send NEC power command (typical TV remote)
scpi_command('192.168.1.42', 5025, 'IR:SEND:NEC,0,12')

# Check for received frames
count = int(scpi_command('192.168.1.42', 5025, 'IR:AVAI?'))
print(f"Frames available: {count}")

# Read decoded frame
if count > 0:
    frame = scpi_command('192.168.1.42', 5025, 'IR:RECV?')
    print(f"Received: {frame}")
```

### Python (Advanced - Capture and Replay)

```python
import socket
import time

def scpi_query(ip, port, cmd):
    s = socket.socket()
    s.connect((ip, port))
    s.sendall((cmd + '\n').encode())
    resp = s.recv(4096).decode().strip()
    s.close()
    return resp

def scpi_write(ip, port, cmd):
    s = socket.socket()
    s.connect((ip, port))
    s.sendall((cmd + '\n').encode())
    s.close()

IP = '192.168.1.42'
PORT = 5025

# Wait for user to press remote button
print("Press a button on your IR remote...")
time.sleep(0.5)

# Check if frame was captured
count = int(scpi_query(IP, PORT, 'IR:AVAI?'))
if count > 0:
    # Read decoded frame
    frame = scpi_query(IP, PORT, 'IR:RECV?')
    print(f"Captured: {frame}")
    
    # If NEC, replay it
    if frame.startswith('NEC'):
        parts = frame.split(',')
        addr = parts[1]
        cmd = parts[2]
        print(f"Replaying NEC address={addr} command={cmd}")
        scpi_write(IP, PORT, f'IR:SEND:NEC,{addr},{cmd}')
    
    # If unknown, capture raw and replay
    elif frame.startswith('RAW'):
        raw = scpi_query(IP, PORT, 'IR:RECV:RAW?')
        timings = raw.replace('\n', '')
        print(f"Replaying raw: {len(timings.split(','))} edges")
        scpi_write(IP, PORT, f'IR:SEND:RAW,38000,{timings}')
else:
    print("No frame captured")
```

### Python with pyvisa (instrument automation)

If you have `pyvisa` and `pyvisa-py` installed:

```python
import pyvisa

rm = pyvisa.ResourceManager('@py')
ir = rm.open_resource('TCPIP::192.168.1.42::5025::SOCKET', 
                      read_termination='\n',
                      write_termination='\n')

print(ir.query('*IDN?'))

# Send power command
ir.write('IR:SEND:NEC,0,12')

# Poll for received frames
while True:
    count = int(ir.query('IR:AVAI?'))
    if count > 0:
        frame = ir.query('IR:RECV?')
        print(f"Received: {frame}")
    time.sleep(0.1)

ir.close()
```

## Typical Use Cases

### 1. Remote Control Automation

Replace physical remote controls with network commands for home theater, HVAC, etc.

**Example:** Schedule air conditioner to turn on 30 minutes before you get home.

```python
# Send Mitsubishi AC power-on command at 5:30 PM
import schedule
schedule.every().day.at("17:30").do(
    lambda: scpi_command('192.168.1.42', 5025, 'IR:SEND:NEC,130,64')
)
```

### 2. Reverse Engineering Unknown Remotes

Capture IR codes from proprietary remotes (garage doors, ceiling fans, obscure A/V equipment) for replication or analysis.

**Workflow:**
1. Press button on unknown remote
2. Query `IR:RECV?` to get NEC/RC5/Sony code (if recognized)
3. If `RAW`, query `IR:RECV:RAW?` to get timing sequence
4. Log codes to database for later replay
5. Replay with `IR:SEND:NEC` or `IR:SEND:RAW`

### 3. Test Equipment Integration

Control IR-equipped devices from automated test scripts (LabVIEW, MATLAB, Python).

**Example:** ATE system that tests TV power consumption must turn TV on/off via IR remote.

```python
# Turn TV on via IR
scpi_command('192.168.1.42', 5025, 'IR:SEND:NEC,0,12')
time.sleep(2)

# Measure power via Siglent SPD3303X PSU
from rf_bench.siglent import SPD3303X
psu = SPD3303X('10.1.1.56')
power = psu.get_ch1_power()
print(f"TV power draw: {power:.2f}W")
```

### 4. IR Protocol Analysis

Compare timing variations between different brands/models implementing "the same" protocol.

**Workflow:**
1. Capture raw timings from multiple remotes
2. Export CSV of timings
3. Analyze in Python/MATLAB (histogram of mark/space durations, deviation from nominal)

### 5. IR Blaster for Multi-Room Control

Deploy multiple ESP32 IR controllers in different rooms, all controlled from central automation server.

**Example:** Single Raspberry Pi sends SCPI commands to 5 ESP32s (living room, bedroom, office, etc.) to control all TVs/ACs from one interface.

## Debugging

- **Serial Monitor (115200 baud)** shows WiFi connection status, IP address, and TX/RX events
- **Connection refused:** Check IP address, port number (5025), and firewall settings
- **IR LED not transmitting:**
  - Verify wiring and resistor value
  - Check IR LED polarity (short leg = cathode to GND)
  - Test with phone camera (IR LED should glow purple/white when transmitting)
  - Verify PWM output with oscilloscope (GPIO 25 should show ~38 kHz square wave during marks)
- **IR receiver not capturing:**
  - Verify TSOP38238 wiring (OUT to GPIO 26, VCC to 3.3V, GND to GND)
  - Test with known-working remote (TV remote, any NEC protocol)
  - Check serial monitor for "RX NEC" or "RX Raw" messages when button pressed
  - TSOP38238 output is active-low (idles HIGH, pulses LOW during marks)
- **Captured IR codes don't replay correctly:**
  - Some remotes send codes 2-3 times per button press (Sony, Apple) — replay multiple times
  - Some protocols use toggle bits (RC5) — firmware currently doesn't auto-toggle
  - Carrier frequency mismatch — try `IR:CARR,36` or `IR:CARR,40` instead of default 38 kHz
- **Range too short:**
  - Use lower resistor value (100Ω instead of 220Ω)
  - Add transistor driver for higher LED current (~50-100mA)
  - Use multiple IR LEDs in parallel
  - Use IR LED with narrower beam angle (focused vs wide-angle)
- **RX buffer overflows (missed frames):**
  - Poll `IR:AVAI?` more frequently
  - Increase `MAX_RX_FRAMES` in code (currently 16)
  - Process frames faster on client side

## IR Protocol Background

### NEC Protocol (Most Common)

**Timing:**
- Header: 9ms mark, 4.5ms space
- Logical 0: 560µs mark, 560µs space
- Logical 1: 560µs mark, 1690µs space
- Stop bit: 560µs mark
- Carrier: 38 kHz, 33% duty cycle

**Format:** 32 bits (8-bit address, 8-bit inverted address, 8-bit command, 8-bit inverted command)

**Repeat code:** If button held, 9ms mark + 2.25ms space + 560µs mark every 110ms

**Devices:** Most Chinese/generic IR remotes, TVs, air conditioners, LED strips

### RC5 Protocol (Philips Standard)

**Timing:**
- Bit period: 1.778ms (889µs per half-bit)
- Manchester encoding (transition in middle of each bit)
- Carrier: 36 kHz, 25% duty cycle

**Format:** 14 bits (2 start bits, 1 toggle bit, 5-bit address, 6-bit command)

**Toggle bit:** Flips on each new button press (distinguishes new press from repeat)

**Devices:** Philips, some European brands, older A/V equipment

### Sony SIRC Protocol

**Timing:**
- Header: 2.4ms mark
- Logical 0: 600µs mark, 600µs space
- Logical 1: 600µs mark, 1200µs space
- Carrier: 40 kHz, 33% duty cycle

**Format:** 12/15/20 bits (7-bit command + 5/8/13-bit device/address)

**Repeat:** Code sent 3 times per button press (~45ms frame time)

**Devices:** Sony TVs, PlayStation, some A/V equipment

## Integration with Test Systems

This SCPI IR controller integrates with:

- **LabVIEW** via VISA driver (use TCPIP SOCKET resource)
- **MATLAB** via `tcpip` or Instrument Control Toolbox
- **Python** via `pyvisa`, `socket`, or `PySerial`
- **Keysight VEE, TestStand, etc.** via standard SCPI/VISA interface

The standard SCPI command set makes this compatible with automated test equipment (ATE) frameworks.

## License

Public domain. Use freely.

## Author

N0GQ — 2026-06-12
