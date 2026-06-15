# ESP32 SCPI DC Motor Controller

Network-controlled DC motor driver using SCPI (Standard Commands for Programmable Instruments) over TCP/IP. Controls 2 DC motors via L298N H-bridge driver with PWM speed control and bidirectional operation.

## Hardware Requirements

- ESP32 development board (any variant with WiFi)
- L298N H-bridge motor driver module
- 2× DC motors (6-12V rated, <2A per motor)
- External 12V power supply (2A minimum, 5A recommended for high-load motors)
- Jumper wires

## Wiring

### ESP32 to L298N

| ESP32 GPIO | L298N Pin | Function |
|------------|-----------|----------|
| GPIO 25 | IN1 (Motor A) | Motor 1 direction control |
| GPIO 26 | IN2 (Motor A) | Motor 1 direction control |
| GPIO 27 | ENA (Motor A) | Motor 1 PWM speed control |
| GPIO 14 | IN3 (Motor B) | Motor 2 direction control |
| GPIO 32 | IN4 (Motor B) | Motor 2 direction control |
| GPIO 33 | ENB (Motor B) | Motor 2 PWM speed control |
| GND | GND | Common ground |

### L298N Power

| L298N Pin | Connection |
|-----------|------------|
| 12V | External 12V power supply + |
| GND | External 12V power supply - (shared with ESP32 GND) |
| 5V | Optional: 5V logic power (or use onboard regulator from 12V input) |
| OUT1, OUT2 | Motor 1 terminals |
| OUT3, OUT4 | Motor 2 terminals |

**CRITICAL:** 
- Common ground connection is required (ESP32 GND ↔ 12V PSU GND ↔ L298N GND)
- Motors are powered from external 12V supply, NOT from ESP32
- L298N can draw several amps under load - do not power from USB

### L298N Jumper Settings

- **ENA/ENB jumpers:** REMOVE jumpers (ESP32 controls PWM on these pins)
- **5V regulator jumper:** Keep installed if using onboard 5V regulator for logic power

## Motor Control Modes

### H-Bridge Truth Table

| IN1 | IN2 | EN (PWM) | Result |
|-----|-----|----------|--------|
| LOW | LOW | any | **Coast** - Motor freewheels (no current) |
| LOW | HIGH | PWM | **Forward** - Motor runs forward at PWM speed |
| HIGH | LOW | PWM | **Reverse** - Motor runs reverse at PWM speed |
| HIGH | HIGH | any | **Brake** - Motor terminals shorted, active braking |

### Speed/Direction Control

Speed is specified as **-100 to +100**:
- `-100` = full speed reverse
- `0` = stop (coast mode by default)
- `+100` = full speed forward

PWM duty cycle is linearly mapped from speed percentage (1 kHz PWM frequency, 8-bit resolution).

### Brake vs Coast

- **Brake** (`MOT:BRA` or `MOT:STOP`): Both IN1 and IN2 HIGH → motor terminals shorted → active braking (motor resists rotation)
- **Coast** (`MOT:COAS` or `MOT:SPEED (@n),0`): Both IN1 and IN2 LOW → motor freewheels (motor spins freely)

Brake mode provides faster stopping and holding torque. Coast mode allows motor to spin freely (useful for testing, back-driving).

## Installation

### Arduino IDE Setup

1. Install ESP32 board support:
   - File → Preferences → Additional Board Manager URLs:
   - Add: `https://raw.githubusercontent.com/espressif/arduino-esp32/gh-pages/package_esp32_index.json`
   - Tools → Board → Boards Manager → search "esp32" → Install

2. Open `scpi-motor.ino` in Arduino IDE

3. Edit WiFi credentials at top of file:
   ```cpp
   const char* ssid = "YourSSID";
   const char* password = "YourPassword";
   ```

4. Select board:
   - Tools → Board → ESP32 Dev Module

5. Select USB port:
   - Tools → Port → (your ESP32 serial port)

6. Click Upload

7. Open Serial Monitor (115200 baud) to see IP address

## SCPI Commands

All commands are case-insensitive, terminated by newline (`\n`), carriage return (`\r`), or semicolon (`;`).

### IEEE 488.2 Common Commands

| Command | Response | Description |
|---------|----------|-------------|
| `*IDN?` | `N0GQ,ESP32-SCPI-Motor,1.0,2026` | Identification query |
| `*RST` | `OK` | Reset (coast all motors) |
| `SYST:ERR?` | `0,"No error"` | System error query |

### Motor Control Commands

| Command | Response | Description |
|---------|----------|-------------|
| `MOT:SPEED (@n),<-100..100>` | `OK` | Set motor n speed/direction |
| `MOT:SPEED? (@n)` | `<speed>` | Query motor n speed |
| `MOT:BRA (@n)` | `OK` | Brake motor n (active braking) |
| `MOT:COAS (@n)` | `OK` | Coast motor n (freewheel) |
| `MOT:STOP (@n)` | `OK` | Stop motor n (alias for brake) |

**Motor numbering:** `(@1)` = Motor 1, `(@2)` = Motor 2

## Usage Examples

### Telnet (Quick Test)

```bash
telnet 192.168.1.42 5025

*IDN?
# Response: N0GQ,ESP32-SCPI-Motor,1.0,2026

MOT:SPEED (@1),50
# Motor 1 runs forward at 50% speed

MOT:SPEED (@1),-75
# Motor 1 runs reverse at 75% speed

MOT:SPEED? (@1)
# Response: -75

MOT:STOP (@1)
# Motor 1 stops with active braking

MOT:COAS (@1)
# Motor 1 coasts (freewheels)
```

### Python (socket)

```python
import socket
import time

def scpi_cmd(ip, port, cmd):
    """Send SCPI command, return response if query."""
    s = socket.socket()
    s.connect((ip, port))
    s.sendall((cmd + '\n').encode())
    if '?' in cmd:
        resp = s.recv(1024).decode().strip()
        s.close()
        return resp
    s.close()

# Connect to ESP32 at 192.168.1.42
ip = '192.168.1.42'

# Identify device
print(scpi_cmd(ip, 5025, '*IDN?'))

# Motor 1: ramp forward
for speed in range(0, 101, 10):
    scpi_cmd(ip, 5025, f'MOT:SPEED (@1),{speed}')
    time.sleep(0.2)

# Motor 1: stop with brake
scpi_cmd(ip, 5025, 'MOT:STOP (@1)')
time.sleep(1)

# Motor 1: ramp reverse
for speed in range(0, -101, -10):
    scpi_cmd(ip, 5025, f'MOT:SPEED (@1),{speed}')
    time.sleep(0.2)

# Motor 1: coast
scpi_cmd(ip, 5025, 'MOT:COAS (@1)')

# Query current speed
speed = int(scpi_cmd(ip, 5025, 'MOT:SPEED? (@1)'))
print(f"Motor 1 speed: {speed}%")
```

### Python (pyvisa)

```python
import pyvisa

rm = pyvisa.ResourceManager('@py')
motor = rm.open_resource('TCPIP::192.168.1.42::5025::SOCKET')

# Identify
print(motor.query('*IDN?'))

# Motor 2: forward 80%
motor.write('MOT:SPEED (@2),80')

# Query speed
speed = int(motor.query('MOT:SPEED? (@2)'))
print(f"Motor 2: {speed}%")

# Stop
motor.write('MOT:STOP (@2)')

motor.close()
```

## Use Cases

- **Automated test equipment (ATE):** Controlled sample rotation, conveyor belts
- **Antenna positioning:** Pan/tilt mechanisms
- **Linear stages:** Belt-driven linear motion (with encoder feedback)
- **Turntable control:** RF antenna pattern measurement
- **Sample changers:** Automated sample handling in test fixtures
- **Optical alignment:** Mirror/lens positioning
- **Conveyor systems:** Material handling automation
- **Robotic actuators:** Wheeled robots, tank treads

## Troubleshooting

### Motor doesn't run

1. **Check power supply:** Verify 12V at L298N 12V terminal
2. **Check GND connection:** ESP32 GND must connect to PSU GND and L298N GND
3. **Check motor connections:** Verify OUT1/OUT2 to Motor 1, OUT3/OUT4 to Motor 2
4. **Check ENA/ENB jumpers:** Must be REMOVED (ESP32 controls PWM on these pins)
5. **Check command:** Use `MOT:SPEED (@1),100` to test at full speed

### Motor runs but wrong direction

- Swap motor wires (swap OUT1 ↔ OUT2 or OUT3 ↔ OUT4)
- Or invert speed sign in software (send `-100` instead of `100`)

### Motor runs intermittently

- **Insufficient power supply:** Check PSU current rating (2A minimum, 5A recommended)
- **Loose connections:** Verify all screw terminals on L298N are tight
- **Overheating:** L298N heatsink gets very hot under load; add fan or reduce duty cycle
- **Brown-out:** Voltage drop under load; use thicker wires, add bulk capacitor (1000µF) across 12V terminals

### ESP32 reboots when motor starts

- **Power supply noise:** Add 100µF capacitor across ESP32 VIN/GND
- **Ground loop:** Verify common ground between ESP32 and motor PSU
- **Insufficient motor PSU:** Check voltage doesn't drop below 10V when motor starts

### Motor overheats

- L298N is inefficient (~50-70% efficiency) and generates significant heat
- Add heatsink or fan to L298N chip
- Reduce PWM duty cycle if motor doesn't need full power
- Consider more efficient driver (DRV8871, TB6612FNG, BTS7960) for continuous operation

### Motor PWM noise

- 1 kHz PWM frequency is audible (can hear whine from motor)
- Increase `pwm_freq` to 10000 (10 kHz) in code for quieter operation
- Higher frequencies reduce efficiency but improve acoustic noise

## Performance Specifications

- **PWM frequency:** 1 kHz (configurable up to 40 kHz)
- **PWM resolution:** 8-bit (256 levels, 0-255 duty cycle)
- **Speed resolution:** 1% (100 levels via speed parameter)
- **Max motor current:** 2A per channel (L298N limit)
- **Motor voltage range:** 6-35V (L298N VCC range)
- **Logic voltage:** 3.3V (ESP32) to 5V (L298N logic) - compatible
- **TCP command latency:** <10ms typical on local network
- **Direction change time:** <1ms (instant H-bridge switching)

## Safety Notes

- **Pinch hazard:** Keep hands clear of rotating motors
- **Electrical shock:** 12V is generally safe but avoid touching exposed terminals
- **Thermal:** L298N heatsink can reach 80-100°C under load
- **Short circuit:** Never short motor terminals while motor is running
- **Back-EMF:** Motors generate voltage when coasting; L298N has internal protection diodes

## Hardware Limitations

### L298N Efficiency

L298N is a Darlington transistor H-bridge with ~1.5-2V voltage drop per side → ~3-4V total drop. At 12V supply:
- Effective motor voltage: 8-9V (not 12V)
- Efficiency: 50-70% typical
- Heat dissipation: 3-5W per motor at 1A load

For higher efficiency (>90%), consider:
- **DRV8871** (MOSFET H-bridge, 3.6-45V, 5.5A peak)
- **TB6612FNG** (MOSFET H-bridge, 4.5-13.5V, 1.2A continuous)
- **BTS7960** (MOSFET H-bridge, 5.5-27V, 43A peak) for very high-power motors

### Current Sensing

L298N has no current sensing. For overcurrent protection or power measurement, add:
- INA219 sensor on motor supply (measure voltage/current via I2C)
- Shunt resistor + ADC (ESP32 analog input)
- ACS712 current sensor module (hall-effect, 5A/20A/30A variants)

### Encoder Feedback

For closed-loop speed or position control, add:
- Rotary encoder (quadrature output, 2 GPIO interrupts per motor)
- Hall-effect tachometer (single pulse per revolution)
- Implement PID control in firmware to maintain target speed

## Firmware Architecture

- **Non-blocking:** No delays in `loop()`, commands processed while motors run
- **PWM control:** Uses ESP32 LEDC (LED PWM) peripheral for hardware PWM generation
- **Single client:** One TCP connection at a time (additional clients rejected)
- **256-byte command buffer:** Handles long commands, overflow protection
- **Case-insensitive:** All commands converted to uppercase for matching

## Related Projects

- **`scpi-stepper/`** — Stepper motor controller (step/direction instead of PWM/H-bridge)
- **`scpi-servo/`** — RC servo controller (PWM position control)
- **`scpi-relay/`** — Relay controller (digital on/off switching)
- **`~/rf-bench/drivers/yertai/`** — ET5406A+ DC load driver (similar motor driver use cases)

## Version

**Firmware:** 1.0 (2026-06-12)

**License:** GPL-3.0-or-later

**Author:** N0GQ

**Repository:** ~/Dropbox/build/rf-bench/projects/esp32/scpi-motor/
