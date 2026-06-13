# ESP32 SCPI PTT Controller

Network-controlled Push-to-Talk (PTT) and Voice Operated Transmit (VOX) controller using Standard Commands for Programmable Instruments (SCPI) over TCP/IP.

## Features

- **SCPI over TCP/IP** on port 5025 (industry standard)
- **PTT output** with open-drain/relay control (suitable for most radios)
- **COS input** (Carrier Operated Squelch / carrier detect)
- **VOX input** (audio level monitoring with configurable threshold)
- **Automatic VOX trigger** with hang time
- **Optional amplifier relay** control output
- **WiFi connectivity** with configurable credentials
- **Standard SCPI commands** compatible with test equipment automation

## Hardware Requirements

- ESP32 development board (any variant with WiFi)
- Optional: relay module or transistor for PTT keying
- Optional: amplifier relay for external power amplifier control
- Jumper wires

### Wiring

#### PTT Output

| ESP32 GPIO | Function | Notes |
|------------|----------|-------|
| GPIO 25    | PTT output | Active-low (LOW = TX). Connect to radio PTT input via relay or open-collector transistor |
| GND        | Ground   | Common ground with radio |

**PTT logic:** Most radios ground PTT to transmit. The code defaults to **active-low** (GPIO LOW = TX, HIGH = RX). If your radio is active-high, change `const bool ptt_active_high = false;` to `true` in the source.

**Wiring options:**
- **Direct (3.3V logic radios):** Connect GPIO 25 directly to radio PTT input
- **Relay:** Connect GPIO 25 to relay module IN1, relay NO/COM to radio PTT and ground
- **Transistor (most common):** Use 2N2222 or 2N7000 FET with GPIO 25 → gate/base, drain/collector → radio PTT, source/emitter → ground

#### COS Input (Carrier Detect)

| ESP32 GPIO | Function | Logic Levels |
|------------|----------|--------------|
| GPIO 26    | COS input | 0V = no carrier (0), 3.3V = carrier detected (1) |

**Pull-down enabled:** Input reads LOW (0) when floating or no carrier. Connect squelch output or COS pin from radio to GPIO 26. **DO NOT exceed 3.3V** — use a voltage divider for 5V logic.

**Use cases:** Monitor repeater squelch, detect incoming signals, interlock TX with carrier presence.

#### VOX Input (Audio Level)

| ESP32 GPIO | Function | Range |
|------------|----------|-------|
| GPIO 36 (ADC1_CH0) | Audio level | 0-3.3V (12-bit: 0-4095 counts, reported as 0-100 scale) |

**Voltage range:** 0-3.3V maximum. The ADC is configured with 11dB attenuation for full-scale 3.3V reading. **DO NOT exceed 3.3V** — overvoltage will damage the ESP32.

**Typical connection:** Rectified and filtered audio from radio microphone or line output. Use peak detector circuit (diode + capacitor + resistor) to convert AC audio to DC level.

**VOX operation:** When enabled (`VOX:EN,1`), the controller monitors audio level continuously. If level exceeds `VOX:THRE` threshold, PTT activates automatically. PTT remains active for hang time (default 1000ms) after audio drops below threshold.

#### Amplifier Relay (Optional)

| ESP32 GPIO | Function | Notes |
|------------|----------|-------|
| GPIO 27    | Amplifier relay | Active-low (LOW = amp on). For external power amplifier sequencing |

**Use case:** Control external linear amplifier. Typically, you want amp relay to activate *before* PTT (for hot-switching protection) and release *after* PTT drops (to avoid RF spike at amp input). This is left to the user's automation script to sequence properly.

## Software Setup

1. **Install Arduino IDE** with ESP32 board support
   - File → Preferences → Additional Board Manager URLs: `https://dl.espressif.com/dl/package_esp32_index.json`
   - Tools → Board → Boards Manager → Search "ESP32" → Install

2. **Configure WiFi credentials**
   - Edit `scpi-ptt.ino`
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
Returns device identification string: `N0GQ,ESP32-SCPI-PTT,1.0,2026`

### Reset

```
*RST
```
Sets PTT to RX mode, amplifier off, VOX disabled, threshold to 30%.

### PTT Control

```
PTT,0               # Set to RX (receive) mode
PTT,1               # Set to TX (transmit) mode

PTT?                # Query PTT state (returns 0 = RX, 1 = TX)
```

**Note:** Manual PTT commands work independently of VOX. If VOX is enabled and triggers while you've manually set PTT, VOX will take over control.

### COS (Carrier Detect) Input

```
COS?                # Query COS input state (returns 0 = no carrier, 1 = carrier detected)
```

### VOX (Voice Operated Transmit)

```
VOX:LEV?            # Read current audio level (returns 0-100)
VOX:THRE,<0-100>    # Set VOX threshold (0 = least sensitive, 100 = most sensitive)
VOX:THRE?           # Query VOX threshold (returns 0-100)
VOX:EN,0            # Disable auto VOX
VOX:EN,1            # Enable auto VOX
VOX:EN?             # Query VOX enabled state (returns 0 = disabled, 1 = enabled)
```

**VOX threshold examples:**
- `VOX:THRE,10` — very low sensitivity (only loud signals trigger)
- `VOX:THRE,30` — moderate sensitivity (default)
- `VOX:THRE,70` — high sensitivity (even quiet audio triggers)

**VOX hang time:** Hard-coded to 1000ms (1 second) in the source. This is the delay between audio dropping below threshold and PTT releasing. Adjust `vox_hangtime` variable if needed.

### Amplifier Relay Control

```
AMP,0               # Turn amplifier relay off
AMP,1               # Turn amplifier relay on

AMP?                # Query amplifier relay state (returns 0 = off, 1 = on)
```

**Sequencing:** For safe amplifier operation, activate AMP before PTT and deactivate AMP after PTT drops. Example:
```
AMP,1               # Turn on amplifier
(wait 100ms for relay settling)
PTT,1               # Key radio
(transmit)
PTT,0               # Unkey radio
(wait 100ms for RF to stop)
AMP,0               # Turn off amplifier
```

### System Error Query

```
SYST:ERR?
```
Returns `0,"No error"` (always, for this simple device).

### Command Format Notes

- Commands can be uppercase or lowercase (case-insensitive)
- Short form allowed: `VOX:EN` instead of `VOX:ENABLE`, `VOX:THRE` instead of `VOX:THRESHOLD`
- Commands can be terminated with newline (`\n`), carriage return (`\r`), or semicolon (`;`)
- Multiple commands can be sent in one line separated by semicolons: `PTT,1;AMP,1`

## Usage Examples

### Telnet (interactive)

```bash
telnet 192.168.1.42 5025
*IDN?
PTT,1               # Key transmitter
PTT?                # Check PTT state
VOX:LEV?            # Check audio level
PTT,0               # Unkey transmitter
```

### Netcat (command-line)

```bash
echo "PTT,1" | nc 192.168.1.42 5025          # Key TX
echo "PTT?" | nc 192.168.1.42 5025           # Query PTT
echo "VOX:LEV?" | nc 192.168.1.42 5025       # Read audio level
echo "COS?" | nc 192.168.1.42 5025           # Read carrier detect
echo "PTT,0" | nc 192.168.1.42 5025          # Key RX
```

### Python

```python
import socket
import time

def scpi_command(ip, port, command):
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.connect((ip, port))
        s.sendall((command + '\n').encode())
        if '?' in command:
            response = s.recv(1024).decode().strip()
            return response

# Identify device
print(scpi_command('192.168.1.42', 5025, '*IDN?'))

# Key transmitter
scpi_command('192.168.1.42', 5025, 'PTT,1')
print("TX")
time.sleep(2)

# Unkey transmitter
scpi_command('192.168.1.42', 5025, 'PTT,0')
print("RX")

# Check carrier detect
cos_state = scpi_command('192.168.1.42', 5025, 'COS?')
print(f"Carrier detect: {'yes' if cos_state == '1' else 'no'}")

# Monitor audio level
audio_level = scpi_command('192.168.1.42', 5025, 'VOX:LEV?')
print(f"Audio level: {audio_level}%")
```

### Python VOX Configuration

```python
import socket

def scpi_command(ip, port, command):
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.connect((ip, port))
        s.sendall((command + '\n').encode())
        if '?' in command:
            response = s.recv(1024).decode().strip()
            return response

# Set VOX threshold to 40%
scpi_command('192.168.1.42', 5025, 'VOX:THRE,40')

# Enable VOX
scpi_command('192.168.1.42', 5025, 'VOX:EN,1')
print("VOX enabled - speak into microphone to trigger PTT")

# Monitor VOX state
while True:
    audio = scpi_command('192.168.1.42', 5025, 'VOX:LEV?')
    ptt = scpi_command('192.168.1.42', 5025, 'PTT?')
    print(f"Audio: {audio}%  PTT: {'TX' if ptt == '1' else 'RX'}")
    time.sleep(0.1)
```

### Python Amplifier Sequencing

```python
import socket
import time

def scpi_command(ip, port, command):
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.connect((ip, port))
        s.sendall((command + '\n').encode())

# Safe amplifier + PTT sequence
scpi_command('192.168.1.42', 5025, 'AMP,1')    # Amp on first
time.sleep(0.1)                                 # Wait for relay
scpi_command('192.168.1.42', 5025, 'PTT,1')    # PTT on

# (transmit for some duration)
time.sleep(5)

# Safe shutdown sequence
scpi_command('192.168.1.42', 5025, 'PTT,0')    # PTT off first
time.sleep(0.1)                                 # Wait for RF to stop
scpi_command('192.168.1.42', 5025, 'AMP,0')    # Amp off last
```

### Python with pyvisa (instrument automation)

If you have `pyvisa` and `pyvisa-py` installed:

```python
import pyvisa

rm = pyvisa.ResourceManager('@py')
ptt = rm.open_resource('TCPIP::192.168.1.42::5025::SOCKET', 
                       read_termination='\n',
                       write_termination='\n')

print(ptt.query('*IDN?'))
ptt.write('PTT,1')
print(ptt.query('PTT?'))  # Should return "1"

# Read audio level
audio = int(ptt.query('VOX:LEV?'))
print(f"Audio level: {audio}%")

# Enable VOX with 50% threshold
ptt.write('VOX:THRE,50')
ptt.write('VOX:EN,1')

ptt.close()
```

## Debugging

- **Serial Monitor (115200 baud)** shows WiFi connection status, IP address, received SCPI commands, and VOX trigger events
- **Connection refused:** Check IP address, port number (5025), and firewall settings
- **PTT doesn't key radio:** Verify GPIO 25 wiring, check `ptt_active_high` setting in code, measure voltage at GPIO 25 (should toggle between 0V and 3.3V)
- **PTT inverted (TX when should be RX):** Change `const bool ptt_active_high` from `false` to `true`
- **COS always reads LOW:** Check 3.3V connection and pull-down resistor configuration
- **VOX doesn't trigger:** Increase threshold (`VOX:THRE,70`), verify audio input voltage with multimeter, check ADC reading with `VOX:LEV?`
- **VOX triggers too easily:** Decrease threshold (`VOX:THRE,10`)
- **Audio input reads 0V or 3.3V when mid-range expected:** Check ADC attenuation setting (`ADC_11db` for 0-3.3V full scale)
- **Audio input noisy/inaccurate:** ESP32 ADC has known non-linearity; consider external ADC (ADS1115) for precision
- **5V logic damage warning:** ESP32 is NOT 5V tolerant! Use voltage divider (e.g., 2.2kΩ + 3.3kΩ) for 5V → 3.3V level shifting

## Integration with Test Systems

This SCPI PTT controller integrates with:

- **LabVIEW** via VISA driver (use TCPIP SOCKET resource)
- **MATLAB** via `tcpip` or Instrument Control Toolbox
- **Python** via `pyvisa`, `socket`, or `PySerial`
- **Keysight VEE, TestStand, etc.** via standard SCPI/VISA interface

The standard SCPI command set makes this compatible with automated test equipment (ATE) frameworks and repeater controllers.

## Use Cases

- **Remote radio control** — PTT over network for remote HF/VHF/UHF stations
- **Repeater controller** — Monitor COS, key transmitter, control amplifier
- **Automated testing** — Script transmitter keying for RF bench measurements
- **VOX autopatch** — Voice-activated transmitter for phone patches or voice control
- **Amplifier sequencing** — Safe hot-switching protection for linear amplifiers
- **Link controller** — Coordinate multiple radios in a simulcast or link system
- **APRS/packet digipeater** — PTT control for TNC-based packet radio

## License

Public domain. Use freely.

## Author

N0GQ — 2026-06-12
