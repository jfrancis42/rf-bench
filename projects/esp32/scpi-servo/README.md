# ESP32 SCPI Servo Controller

Network-controlled RC servo driver using Standard Commands for Programmable Instruments (SCPI) over TCP/IP. Controls up to 4 standard hobby servos with precise angle positioning.

## Features

- **SCPI over TCP/IP** on port 5025 (industry standard)
- **4 independent servo channels** with individual control
- **WiFi connectivity** with configurable credentials
- **Standard SCPI commands** compatible with test equipment automation
- **Precise angle control** 0-180 degrees
- **Sweep function** for automated motion sequences
- **Position query** for verification and monitoring

## Hardware Requirements

- ESP32 development board (any variant with WiFi and PWM)
- 4× RC hobby servos (SG90, MG996R, or similar)
- **External 5V power supply** (2-5A depending on servo count/load)
- Jumper wires

### Wiring

#### Servo Connections

| ESP32 GPIO | Servo # | Servo Signal Wire |
|------------|---------|-------------------|
| GPIO 25    | Servo 1 | Signal (yellow/white/orange) |
| GPIO 26    | Servo 2 | Signal (yellow/white/orange) |
| GPIO 27    | Servo 3 | Signal (yellow/white/orange) |
| GPIO 14    | Servo 4 | Signal (yellow/white/orange) |

#### Power Wiring

**CRITICAL:** Servos draw significant current (each servo can draw 100-800mA under load). **DO NOT power servos from the ESP32's 5V pin** — this will damage the ESP32 or cause brownouts/reboots.

**Correct wiring:**
```
External 5V PSU (+) ──→ Servo VCC (red wire, all servos)
External 5V PSU (−) ──→ Common GND
ESP32 GND          ──→ Common GND (shared with PSU and servos)
```

All grounds must be connected together (ESP32 GND, power supply GND, servo GND).

**Power supply sizing:**
- Small servos (SG90): 100-200mA each, max 500mA stalled
- Standard servos (MG996R): 200-400mA each, max 1.5A stalled
- **Recommendation:** 5V 2-3A power supply for 4 small servos, 5V 5A for 4 standard servos

### Typical RC Servos

- **SG90** (micro servo) — 0-180°, 9g, plastic gears, ~100-200mA, 1.5kg·cm torque
- **MG90S** (micro metal gear) — 0-180°, 14g, metal gears, ~150-250mA, 2.2kg·cm torque
- **MG996R** (standard) — 0-180°, 55g, metal gears, ~200-400mA, 11kg·cm torque
- **DS3218** (high-torque) — 0-180°, 60g, metal gears, ~300-600mA, 20kg·cm torque

**All standard RC servos use 50 Hz PWM:**
- 1000 µs pulse = 0° position
- 1500 µs pulse = 90° position (center)
- 2000 µs pulse = 180° position

Some servos may have slightly different ranges (e.g., 600-2400 µs). The code defaults to 1000-2000 µs (adjustable via `servo_min_us` and `servo_max_us` constants).

## Software Setup

1. **Install Arduino IDE** with ESP32 board support
   - File → Preferences → Additional Board Manager URLs: `https://dl.espressif.com/dl/package_esp32_index.json`
   - Tools → Board → Boards Manager → Search "ESP32" → Install

2. **Install ESP32Servo library**
   - Tools → Manage Libraries → Search "ESP32Servo" by Kevin Harrington → Install

3. **Configure WiFi credentials**
   - Edit `scpi-servo.ino`
   - Change `ssid` and `password` near the top of the file

4. **Upload to ESP32**
   - Tools → Board → ESP32 Dev Module (or your specific board)
   - Tools → Port → (select your ESP32's serial port)
   - Click Upload

5. **Find the IP address**
   - Open Serial Monitor (115200 baud)
   - Reset the ESP32
   - Note the IP address printed (e.g., `192.168.1.42`)

6. **Connect servos and power**
   - Wire servos to GPIOs as shown above
   - Connect external 5V power supply
   - **Ensure all grounds are connected together**

## SCPI Command Reference

Connect to the ESP32 on port 5025 using any TCP client (`telnet`, `nc`, or Python `socket`).

### Identification

```
*IDN?
```
Returns device identification string: `N0GQ,ESP32-SCPI-Servo,1.0,2026`

### Reset

```
*RST
```
Moves all servos to center position (90°).

### Set Servo Position

```
SERV:POS (@1),<angle>    # Set servo 1 to angle (0-180)
SERV:POS (@2),<angle>    # Set servo 2 to angle
SERV:POS (@3),<angle>    # Set servo 3 to angle
SERV:POS (@4),<angle>    # Set servo 4 to angle
```

**Example:**
```
SERV:POS (@1),45         # Servo 1 to 45°
SERV:POS (@2),135        # Servo 2 to 135°
```

**Note:** Angle is clamped to 0-180° range. Values outside this range are automatically limited.

### Query Servo Position

```
SERV:POS? (@1)           # Query servo 1 position
SERV:POS? (@2)           # Query servo 2 position
SERV:POS? (@3)           # Query servo 3 position
SERV:POS? (@4)           # Query servo 4 position
```

Returns current servo angle in degrees (0-180).

### Preset Positions

```
SERV:MIN (@1)            # Move servo 1 to minimum (0°)
SERV:CENT (@1)           # Move servo 1 to center (90°)
SERV:MAX (@1)            # Move servo 1 to maximum (180°)
```

### Control All Servos

```
SERV:ALL,<angle>         # Set all servos to angle
SERV:ALL:CENT            # Center all servos (90°)
```

**Example:**
```
SERV:ALL,45              # All servos to 45°
SERV:ALL:CENT            # All servos to 90° (center)
```

### Servo Sweep

```
SERV:SWEEP (@n),<start>,<end>,<step>,<delay_ms>
```

Sweeps servo from `start` angle to `end` angle in increments of `step`, waiting `delay_ms` milliseconds between each step.

**Parameters:**
- `start` — starting angle (0-180°)
- `end` — ending angle (0-180°)
- `step` — angle increment per step (positive integer)
- `delay_ms` — delay between steps in milliseconds

**Examples:**
```
SERV:SWEEP (@1),0,180,5,20      # Sweep servo 1 from 0° to 180° in 5° steps, 20ms delay
SERV:SWEEP (@2),180,0,10,50     # Sweep servo 2 from 180° to 0° in 10° steps, 50ms delay
SERV:SWEEP (@3),60,120,1,10     # Sweep servo 3 from 60° to 120° in 1° steps, 10ms delay
```

**Note:** Sweep is blocking — the SCPI command does not return until sweep completes. Client will wait for "OK" response.

### System Error Query

```
SYST:ERR?
```
Returns `0,"No error"` (always, for this simple device).

### Command Format Notes

- Commands can be uppercase or lowercase (case-insensitive)
- Short form allowed: `SERV:POS` = `SERVO:POSITION`
- Commands can be terminated with newline (`\n`), carriage return (`\r`), or semicolon (`;`)
- Multiple commands can be sent in one line separated by semicolons: `SERV:POS (@1),45;SERV:POS (@2),90`

## Usage Examples

### Telnet (interactive)

```bash
telnet 192.168.1.42 5025
*IDN?
SERV:POS (@1),90
SERV:POS? (@1)
SERV:SWEEP (@1),0,180,5,20
SERV:ALL:CENT
```

### Netcat (command-line)

```bash
echo "SERV:POS (@1),45" | nc 192.168.1.42 5025
echo "SERV:ALL,90" | nc 192.168.1.42 5025
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

# Move servo 1 to 45°
scpi_command('192.168.1.42', 5025, 'SERV:POS (@1),45')

# Query servo 1 position
pos = scpi_command('192.168.1.42', 5025, 'SERV:POS? (@1)')
print(f"Servo 1 position: {pos}°")

# Sweep servo 2 from 0 to 180
scpi_command('192.168.1.42', 5025, 'SERV:SWEEP (@2),0,180,5,20')

# Center all servos
scpi_command('192.168.1.42', 5025, 'SERV:ALL:CENT')
```

### Python with pyvisa (instrument automation)

If you have `pyvisa` and `pyvisa-py` installed:

```python
import pyvisa
import time

rm = pyvisa.ResourceManager('@py')
servo = rm.open_resource('TCPIP::192.168.1.42::5025::SOCKET',
                         read_termination='\n',
                         write_termination='\n')

print(servo.query('*IDN?'))

# Position control
servo.write('SERV:POS (@1),0')
time.sleep(1)
servo.write('SERV:POS (@1),90')
time.sleep(1)
servo.write('SERV:POS (@1),180')

# Query position
pos = int(servo.query('SERV:POS? (@1)'))
print(f"Servo 1: {pos}°")

servo.close()
```

### Coordinated Multi-Servo Motion

```python
import socket
import time

s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
s.connect(('192.168.1.42', 5025))

def command(cmd):
    s.sendall((cmd + '\n').encode())
    time.sleep(0.05)  # Small delay for command processing

# Choreographed sequence
command('SERV:ALL:CENT')  # Start at center
time.sleep(1)

command('SERV:POS (@1),0;SERV:POS (@2),180;SERV:POS (@3),0;SERV:POS (@4),180')
time.sleep(1)

command('SERV:POS (@1),180;SERV:POS (@2),0;SERV:POS (@3),180;SERV:POS (@4),0')
time.sleep(1)

command('SERV:ALL:CENT')  # Return to center

s.close()
```

### Complete Test Script

A complete test script `test_servo.py` is included that demonstrates all functionality:

```bash
# Edit the IP address in test_servo.py first, then run:
python3 test_servo.py
```

This script:
- Identifies the device
- Tests each servo individually (min, center, max)
- Queries positions
- Performs sweep operations
- Demonstrates coordinated motion

## Debugging

- **Serial Monitor (115200 baud)** shows WiFi connection status, IP address, and servo commands
- **Connection refused:** Check IP address, port number (5025), and firewall settings
- **Servos don't move:**
  - Check signal wire connections (ESP32 GPIO → servo signal wire)
  - Check power: servo VCC to external 5V, GND to common ground
  - Verify ESP32 GND is connected to power supply GND
- **Servos jitter/twitch:** Insufficient power supply or poor ground connection
- **ESP32 reboots when servos move:** Servos drawing too much current from ESP32 pin — use external 5V power supply
- **Servo moves to wrong angle:**
  - Some servos have non-standard pulse ranges (not 1000-2000 µs)
  - Adjust `servo_min_us` and `servo_max_us` constants in code
  - Common alternatives: 600-2400 µs, 500-2500 µs
- **Servo only moves to ~90° regardless of command:** Signal wire not connected or wrong GPIO pin

### Power Supply Issues

**Symptoms of insufficient power:**
- Servos jitter or buzz
- Servos don't reach commanded positions
- ESP32 reboots or WiFi disconnects when servos move
- Servos work individually but fail when multiple servos move simultaneously

**Solutions:**
- Use larger 5V power supply (increase current rating, not voltage)
- Add 1000-2200 µF bulk capacitor across power supply +/− near servos
- Shorten power wires between supply and servos
- Use thicker wire for power connections (reduce voltage drop)

## Integration with Test Systems

This SCPI servo controller integrates with:

- **LabVIEW** via VISA driver (use TCPIP SOCKET resource)
- **MATLAB** via `tcpip` or Instrument Control Toolbox
- **Python** via `pyvisa`, `socket`, or `PySerial`
- **Keysight VEE, TestStand, etc.** via standard SCPI/VISA interface

The standard SCPI command set and SERVO subsystem make this compatible with automated test equipment (ATE) frameworks.

## Use Cases

- **Antenna positioning** — pan/tilt servos for antenna pattern measurement
- **Sample holder positioning** — rotate DUT for multi-angle RF testing
- **Optical alignment** — mirror/lens positioning for laser/optical test rigs
- **Mechanical actuation** — buttons, switches, valves in automated test fixtures
- **Camera/sensor positioning** — PTZ control for visual inspection or thermal imaging
- **Turntable control** — rotate objects under test
- **Gripper/manipulator** — pick-and-place for PCB/component testing

## Servo Specifications

### Standard RC Servo Interface

- **Signal:** PWM pulse width modulation
- **Frequency:** 50 Hz (20 ms period)
- **Pulse width range:** 1000-2000 µs (standard), some servos 600-2400 µs
- **Signal voltage:** 3.3V (ESP32) is sufficient for most servos (designed for 5V but 3.3V works)
- **Power voltage:** 4.8-6V (most servos), some high-voltage servos accept 7.4V

### Angle-to-Pulse Mapping

```
  0° ────→ 1000 µs pulse
 90° ────→ 1500 µs pulse (center)
180° ────→ 2000 µs pulse
```

Linear interpolation for intermediate angles:
```
pulse_width = 1000 + (angle / 180) * 1000
```

### Servo Response Time

- **Speed:** Typically 0.1-0.2 sec/60° at no load
- **Fast servos:** 0.05-0.08 sec/60° (digital servos, high-speed servos)
- **Slow servos:** 0.3-0.5 sec/60° (large/heavy-duty servos)

When sending rapid position changes, allow sufficient time for servo to reach position before next command (or servo will lag behind and may never reach intermediate positions).

## License

Public domain. Use freely.

## Author

N0GQ — 2026-06-12
