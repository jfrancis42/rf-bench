# SCPI CW Keyer

Network-controlled CW (Morse code) keyer for ESP32 with iambic paddle support, straight key mode, and automatic text transmission via SCPI commands over TCP/IP.

**Hardware:** ESP32 dev board + iambic paddles (or straight key) + speaker (optional sidetone)

**Control:** SCPI commands over WiFi → KEY subsystem for speed, mode, text sending, and status query

**Use case:** Remote CW operation, automated beacon transmission, contest logging integration, test equipment control, educational CW practice, SOTA/POTA activation automation.

---

## Features

- **Iambic mode B:** Both paddles pressed → alternating dits/dahs with latching
- **Straight key mode:** Direct key control via GPIO input
- **Network text sending:** `KEY:SEND,<text>` transmits any text as Morse code
- **Configurable speed:** 5-60 WPM with automatic PARIS timing
- **Optional sidetone:** PWM audio feedback (300-1200 Hz configurable)
- **PTT sequencing:** Configurable lead/tail timing for amp/rig control
- **Open-drain outputs:** Compatible with most rigs (pull-to-ground keying)
- **Abort capability:** Stop text transmission mid-sequence

---

## Hardware Wiring

### Outputs (Open-Drain)

| GPIO | Function | Connection |
|------|----------|-----------|
| 25 | KEY | To rig key input (tip of 3.5mm jack, or "KEY" on amp) |
| 26 | PTT | To rig PTT input (optional, for amp sequencing) |
| 23 | Sidetone | Speaker (100-500Ω) between GPIO 23 and GND |

**Open-drain keying:** Both KEY and PTT are idle-high (3.3V), pull to GND when active. This matches most rig keying inputs (Icom, Yaesu, Elecraft, etc.). If your rig requires active-high logic, add an inverter (2N7000 FET or 2N2222 NPN).

**Sidetone speaker:** Connect directly to GPIO 23 (PWM output) and GND. Use a small 8Ω-32Ω speaker or piezo buzzer. For higher volume, add a simple transistor amplifier.

### Inputs (Active-Low with Internal Pull-Up)

| GPIO | Function | Connection |
|------|----------|-----------|
| 32 | DIT paddle | Connect paddle dit contact between GPIO 32 and GND |
| 33 | DAH paddle | Connect paddle dah contact between GPIO 33 and GND |
| 34 | Straight key | Connect key between GPIO 34 and GND (optional) |

**Paddle wiring:** Most iambic paddles have three terminals: common (ground), dit, and dah. Connect common to ESP32 GND, dit to GPIO 32, dah to GPIO 33. Internal pull-up resistors are enabled in firmware.

**Straight key:** If using straight key mode, connect key between GPIO 34 and GND. Paddles are ignored in straight key mode.

### Example: Icom IC-7300 Keying

IC-7300 rear panel has a 3.5mm "KEY" jack (tip = key, sleeve = ground):

```
ESP32 GPIO 25 (KEY) → 3.5mm plug tip
ESP32 GND           → 3.5mm plug sleeve
```

If using PTT for external amp:

```
ESP32 GPIO 26 (PTT) → Amp PTT input (or rig ACC connector)
ESP32 GND           → Amp PTT ground
```

---

## SCPI Command Reference

All commands over TCP port **5025** (standard SCPI port).

### Common Commands

| Command | Response | Description |
|---------|----------|-------------|
| `*IDN?` | `N0GQ,ESP32-SCPI-Keyer,1.0,2026` | Identification query |
| `*RST` | `OK` | Reset to defaults (20 WPM, iambic mode, sidetone off) |
| `SYST:ERR?` | `0,"No error"` | System error query |

### KEY Subsystem

| Command | Response | Description |
|---------|----------|-------------|
| `KEY:WPM,<5-60>` | `OK` | Set CW speed (5-60 WPM) |
| `KEY:WPM?` | `<wpm>` | Query current speed |
| `KEY:MODE,<IAMB\|STRK>` | `OK` | Set mode (IAMB = iambic B, STRK = straight key) |
| `KEY:MODE?` | `IAMB` or `STRK` | Query current mode |
| `KEY:SEND,<text>` | `OK` | Send text as CW (A-Z, 0-9, space supported) |
| `KEY:TON,<ms>` | `OK` | Set sidetone duration (0 = disabled, >0 = enabled) |
| `KEY:TON?` | `<ms>` | Query sidetone duration |
| `KEY:FREQ,<hz>` | `OK` | Set sidetone frequency (300-1200 Hz) |
| `KEY:FREQ?` | `<hz>` | Query sidetone frequency |
| `KEY:STAT?` | `0` or `1` | Query keying state (0 = idle, 1 = keying) |
| `KEY:ABOR` | `OK` | Abort current text transmission |

**Short forms accepted:** `KEY:TON` = `KEY:TONE`, `KEY:STAT` = `KEY:STATUS`, `KEY:ABOR` = `KEY:ABORT`

**Text encoding:** Only uppercase A-Z, digits 0-9, and spaces are supported in `KEY:SEND`. Other characters are ignored.

---

## Python Examples

### Basic usage (raw socket)

```python
import socket
import time

def scpi_cmd(ip, port, cmd):
    s = socket.socket()
    s.connect((ip, port))
    s.sendall((cmd + '\n').encode())
    if '?' in cmd:
        resp = s.recv(1024).decode().strip()
        s.close()
        return resp
    s.close()

# Identification
print(scpi_cmd('192.168.1.42', 5025, '*IDN?'))
# N0GQ,ESP32-SCPI-Keyer,1.0,2026

# Set speed to 25 WPM
scpi_cmd('192.168.1.42', 5025, 'KEY:WPM,25')

# Query speed
print(scpi_cmd('192.168.1.42', 5025, 'KEY:WPM?'))
# 25

# Send CW text
scpi_cmd('192.168.1.42', 5025, 'KEY:SEND,CQ CQ CQ DE N0GQ K')
```

### Using pyvisa (instrument automation)

```python
import pyvisa
rm = pyvisa.ResourceManager('@py')
keyer = rm.open_resource('TCPIP::192.168.1.42::5025::SOCKET')

keyer.write('KEY:WPM,30')
keyer.write('KEY:MODE,IAMB')
keyer.write('KEY:TON,100')      # Enable sidetone (100 ms duration)
keyer.write('KEY:FREQ,700')     # Sidetone at 700 Hz
keyer.write('KEY:SEND,TEST TEST')

# Query state
wpm = int(keyer.query('KEY:WPM?'))
mode = keyer.query('KEY:MODE?').strip()
print(f"Speed: {wpm} WPM, Mode: {mode}")
```

### Automated beacon (every 10 minutes)

```python
import socket
import time

def send_cw(ip, port, text):
    s = socket.socket()
    s.connect((ip, port))
    s.sendall(f'KEY:SEND,{text}\n'.encode())
    s.recv(1024)  # Wait for OK response
    s.close()

while True:
    send_cw('192.168.1.42', 5025, 'CQ CQ CQ DE N0GQ K')
    time.sleep(600)  # 10 minutes
```

### Contest integration (send exchange)

```python
import socket

def send_exchange(callsign, rst, serial):
    s = socket.socket()
    s.connect(('192.168.1.42', 5025))
    text = f'{callsign} UR 599 {serial} K'
    s.sendall(f'KEY:SEND,{text}\n'.encode())
    s.recv(1024)
    s.close()

send_exchange('W1AW', '599', '001')
```

---

## Timing and WPM Calculation

CW speed is based on the **PARIS standard**: the word "PARIS" contains exactly 50 dit-lengths (including spaces).

**Timing formulas:**

```
Dit duration (ms) = 1200 / WPM
Dah duration (ms) = 3 × dit
Element space (ms) = 1 × dit (space between dits/dahs within character)
Character space (ms) = 3 × dit (space between characters)
Word space (ms) = 7 × dit (space between words)
```

**Examples:**

| WPM | Dit (ms) | Dah (ms) | Char space (ms) | Word space (ms) |
|-----|----------|----------|-----------------|-----------------|
| 10  | 120      | 360      | 360             | 840             |
| 20  | 60       | 180      | 180             | 420             |
| 30  | 40       | 120      | 120             | 280             |
| 40  | 30       | 90       | 90              | 210             |

Firmware automatically recalculates all timing when `KEY:WPM,<n>` is sent.

---

## Iambic Mode B Behavior

**Mode B** is the standard iambic keying mode used by most commercial keyers (Elecraft, MFJ, N3ZN, etc.).

**Key features:**

- **Alternating dits/dahs:** Press both paddles → alternating sequence until one released
- **Latching:** If you press dah paddle during a dit, the keyer remembers it and sends a dah after the dit completes (and vice versa)
- **Squeeze keying:** Press both paddles → dit-dah-dit-dah... (useful for letter C, R, L, etc.)
- **Single element memory:** Only one element is remembered (Mode B), not multiple (unlike Mode A)

**Example: Letter C (-.-.):**

1. Press dah paddle → sends dah
2. While dah is sending, press dit paddle → latches dit
3. Release dah paddle
4. Keyer sends dit (from latch)
5. While dit is sending, press dah paddle → latches dah
6. Release dit paddle
7. Keyer sends dah (from latch)
8. Release dah paddle
9. Keyer returns to idle

With practice, this allows smooth high-speed CW with minimal hand motion.

---

## Straight Key Mode

When `KEY:MODE,STRK` is set, the keyer operates as a simple straight key:

- GPIO 34 input directly controls KEY output
- Pressing key (GPIO 34 to GND) → KEY output activates (and PTT if configured)
- Releasing key → KEY output deactivates (PTT releases after tail delay)
- Iambic paddles (GPIO 32, 33) are ignored
- No automatic timing or latching

Useful for:
- Traditional straight key operation
- External keyer integration (bug, vibroplex, etc.)
- Test equipment control (manual keying for transmitter testing)

---

## PTT Sequencing

PTT output (GPIO 26) provides pre-TX and post-TX delays for amplifier/rig sequencing:

1. **Paddle pressed or `KEY:SEND` starts:**
   - PTT activates (GPIO 26 goes LOW)
   - Wait **ptt_lead_ms** (default 50 ms) — allows rig to switch to TX, amp relays to close
   - KEY activates (GPIO 25 goes LOW) — CW keying begins

2. **Last dit/dah ends:**
   - KEY deactivates (GPIO 25 goes HIGH)
   - PTT remains active for **ptt_tail_ms** (default 200 ms) — prevents hot-switching amp
   - PTT deactivates (GPIO 26 goes HIGH)

**Adjusting timing in firmware:**

Edit these constants in `scpi-keyer.ino`:

```cpp
int ptt_lead_ms = 50;   // PTT lead time before KEY (ms)
int ptt_tail_ms = 200;  // PTT hang time after KEY (ms)
```

Typical values:
- **QRP/barefoot:** `ptt_lead_ms = 10`, `ptt_tail_ms = 50`
- **100W transceiver:** `ptt_lead_ms = 50`, `ptt_tail_ms = 100`
- **Amp with slow relays:** `ptt_lead_ms = 100-200`, `ptt_tail_ms = 300-500`

---

## Sidetone

Optional audio feedback for monitoring CW transmission. Useful when operating headphones or in noisy environments where you can't hear the rig's monitor.

**Configuration:**

- **Enable:** `KEY:TON,100` (any value >0 enables sidetone during keying)
- **Disable:** `KEY:TON,0`
- **Frequency:** `KEY:FREQ,700` (300-1200 Hz, default 700 Hz)

**Hardware:**

Connect a small speaker (8Ω-32Ω) or piezo buzzer between GPIO 23 and GND. ESP32 PWM output can drive small speakers directly (limited volume). For louder output, add a simple amplifier:

```
GPIO 23 → 10kΩ resistor → NPN transistor base (2N2222)
Transistor collector → speaker (+) → 5V
Transistor emitter → GND
```

**Tone duration:**

`KEY:TON,<ms>` sets the duration. Firmware uses this value to determine if sidetone is enabled (>0) or disabled (0). The actual tone continues for the duration of the key-down event (dit or dah), not a fixed `<ms>` period. The parameter name is historical (from keyers with timed sidetone after key-up).

---

## Testing and Verification

### Serial Monitor Output on Boot

```
SCPI CW Keyer
==============
Mode: Iambic B
Speed: 20 WPM
Dit: 60 ms, Dah: 180 ms
PTT lead: 50 ms, tail: 200 ms
Sidetone: disabled (700 Hz)

Connecting to YourSSID.... connected!
IP address: 192.168.1.42
SCPI port: 5025

Ready for SCPI commands
```

### Manual Paddle Test (Iambic Mode)

1. Press **dit paddle** (GPIO 32 to GND) → KEY output pulses short (dit)
2. Press **dah paddle** (GPIO 33 to GND) → KEY output pulses long (dah)
3. Press **both paddles** → alternating dit-dah-dit-dah... until released

If no response:
- Check paddle wiring (common to GND, dit to GPIO 32, dah to GPIO 33)
- Verify `KEY:MODE?` returns `IAMB` (not `STRK`)
- Check KEY output with LED or multimeter (should pulse LOW when keying)

### Network Test (telnet)

```bash
telnet 192.168.1.42 5025
*IDN?
# N0GQ,ESP32-SCPI-Keyer,1.0,2026

KEY:WPM,15
# OK

KEY:SEND,TEST
# OK (should hear/see CW transmission)

KEY:STAT?
# 0 (idle) or 1 (keying)
```

### Oscilloscope Verification

Monitor GPIO 25 (KEY) and GPIO 26 (PTT) with scope:

- **Idle:** Both outputs at 3.3V (HIGH)
- **Keying:** PTT goes LOW first, then KEY pulses LOW during dits/dahs
- **Timing:** Verify dit/dah ratio = 1:3, element spacing = 1 dit, char spacing = 3 dits

At 20 WPM (60 ms dit):
- Dit: 60 ms LOW
- Dah: 180 ms LOW
- Element space: 60 ms HIGH between dits/dahs
- Character space: 180 ms HIGH between letters

---

## Troubleshooting

### Keyer doesn't respond to paddles

- **Check wiring:** Paddle common to ESP32 GND, dit to GPIO 32, dah to GPIO 33
- **Verify pull-ups:** Internal pull-ups are enabled in firmware (no external resistors needed)
- **Test continuity:** Paddle contacts should short to GND when pressed
- **Check mode:** `KEY:MODE?` should return `IAMB` (not `STRK`)

### KEY output doesn't key rig

- **Check rig keying type:** Most rigs use tip-to-ground keying (compatible with ESP32 open-drain). Some rigs need positive voltage (add transistor inverter).
- **Verify output:** Measure GPIO 25 with multimeter — should be 3.3V idle, 0V when keying
- **Check jack wiring:** Tip = KEY, sleeve = GND (not tip = GND, ring = KEY)
- **Bypass test:** Short rig key input to ground manually to confirm rig keying works

### Sidetone not working

- **Enable sidetone:** `KEY:TON,100` (must be >0)
- **Check speaker:** Connect 8Ω-32Ω speaker or piezo buzzer between GPIO 23 and GND
- **Test PWM:** Monitor GPIO 23 with scope during keying — should see ~700 Hz square wave
- **Volume:** ESP32 PWM output is low-power (~10 mA) — speaker volume will be quiet. Use amplifier for louder output.

### PTT activates but rig doesn't transmit

- **Check PTT wiring:** Some rigs need PTT on rear ACC connector, not front mic jack
- **Verify PTT polarity:** Most rigs use ground-activated PTT (LOW = TX). Check rig manual.
- **Timing issue:** If rig requires long PTT lead (slow relays), increase `ptt_lead_ms` in firmware
- **Bypass test:** Short rig PTT input to ground manually to confirm rig goes to TX

### Text sending doesn't work or stops mid-word

- **Check command format:** `KEY:SEND,TEXT` (no spaces around comma, uppercase recommended)
- **Supported characters:** Only A-Z, 0-9, and spaces. Special characters are ignored.
- **Client timeout:** Some SCPI clients timeout during long text. Use raw socket (not pyvisa) or increase timeout.
- **Abort flag:** Previous `KEY:ABOR` command sets abort flag — send `*RST` to clear

---

## Use Cases

### Remote CW Operation

Control CW keyer from anywhere on the network (LAN or internet via VPN):

```python
import socket

def send_cw(text):
    s = socket.socket()
    s.connect(('192.168.1.42', 5025))
    s.sendall(f'KEY:SEND,{text}\n'.encode())
    s.recv(1024)
    s.close()

send_cw('CQ CQ CQ DE N0GQ K')
```

### Automated Beacon

Unattended beacon transmission (e.g., SOTA summit, propagation study):

```python
import socket
import time

def beacon():
    s = socket.socket()
    s.connect(('192.168.1.42', 5025))
    s.sendall(b'KEY:WPM,20\n')
    s.recv(1024)
    while True:
        s.sendall(b'KEY:SEND,DE N0GQ QRP 5W\n')
        s.recv(1024)
        time.sleep(600)  # Every 10 minutes

beacon()
```

### Contest Logging Integration

Integrate with logging software (N1MM, WriteLog, etc.) via custom macro:

```python
import socket

def send_exchange(call, rst, serial):
    s = socket.socket()
    s.connect(('192.168.1.42', 5025))
    text = f'{call} UR {rst} {serial} K'
    s.sendall(f'KEY:SEND,{text}\n'.encode())
    s.recv(1024)
    s.close()

# Called from logging software macro
send_exchange('W1AW', '599', '001')
```

### Test Equipment Control

Automated transmitter testing (harmonics, power, spurious emissions):

```python
import socket
import time
from rf_bench.siglent import SSA3000X

keyer = socket.socket()
keyer.connect(('192.168.1.42', 5025))
ssa = SSA3000X('10.1.1.60')

# Key transmitter and measure harmonics
keyer.sendall(b'KEY:SEND,EEEEEEEEEEE\n')  # Continuous E (. . . . .) for testing
time.sleep(1)
ssa.set_center_freq(14.1e6)  # 20m fundamental
ssa.set_span(100e6)
ssa.trigger_single()
trace = ssa.get_trace()
# Analyze trace for harmonics...
```

### SOTA/POTA Activation Automation

Automate CQ calls during activation:

```python
import socket
import time

def sota_cq():
    s = socket.socket()
    s.connect(('192.168.1.42', 5025))
    s.sendall(b'KEY:WPM,22\n')
    s.recv(1024)
    while True:
        s.sendall(b'KEY:SEND,CQ SOTA DE N0GQ K\n')
        s.recv(1024)
        time.sleep(30)  # CQ every 30 seconds

sota_cq()
```

---

## Firmware Compilation and Upload

1. **Install Arduino IDE** (1.8.x or 2.x)
2. **Add ESP32 board support:**
   - File → Preferences → Additional Board Manager URLs:
     `https://dl.espressif.com/dl/package_esp32_index.json`
   - Tools → Board → Boards Manager → Search "ESP32" → Install "ESP32 by Espressif"
3. **Edit WiFi credentials** in `scpi-keyer.ino`:
   ```cpp
   const char* ssid = "YourSSID";
   const char* password = "YourPassword";
   ```
4. **Select board:** Tools → Board → ESP32 Dev Module (or your specific board)
5. **Select port:** Tools → Port → (USB serial port, e.g., `/dev/ttyUSB0` or `COM3`)
6. **Upload:** Sketch → Upload (or click upload button)
7. **Open Serial Monitor** (115200 baud) to see IP address

---

## Integration with rf-bench

This keyer is a standalone ESP32 project. Future integration possibilities:

1. **Python driver package:** `~/rf-bench/drivers/keyer/` wrapping SCPI commands in a `CWKeyer` class
2. **Virtual instrument panel:** GUI with speed slider, mode selector, text entry, and real-time status
3. **Automated testing:** `~/rf-bench/projects/radio/transmitter-test/` integration for TX burst generation
4. **Remote HF operation:** `~/remote-hf/` integration for remote CW operation over internet

Not yet implemented.

---

## License

Public domain. Use as you wish.

---

## References

- **PARIS standard:** [Wikipedia - Morse code timing](https://en.wikipedia.org/wiki/Morse_code#Timing)
- **Iambic keying:** [Wikipedia - Iambic key](https://en.wikipedia.org/wiki/Iambic_key)
- **SCPI standard:** [Wikipedia - Standard Commands for Programmable Instruments](https://en.wikipedia.org/wiki/Standard_Commands_for_Programmable_Instruments)
- **ESP32 Arduino core:** [Espressif ESP32 Arduino GitHub](https://github.com/espressif/arduino-esp32)

---

**Version:** 1.0 (2026-06-12)

**Author:** N0GQ

**Project:** rf-bench/projects/esp32/scpi-keyer/
