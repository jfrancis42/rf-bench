# ESP32 SCPI Stepper Motor Controller

Network-controlled stepper motor driver using Standard Commands for Programmable Instruments (SCPI) over TCP/IP. Controls up to 2 bipolar stepper motors via A4988 or DRV8825 drivers.

## Features

- **2 independent stepper motors** via SCPI commands
- **Speed control** in RPM (revolutions per minute)
- **Relative positioning** with step counting
- **Enable/disable** individual motors
- **Emergency stop** command
- **Non-blocking motion** (motors move asynchronously)
- **Standard SCPI interface** on port 5025
- **IEEE 488.2 compliance** (*IDN?, *RST, SYST:ERR?)

## Hardware Requirements

### Components

- ESP32 development board (any variant with WiFi)
- 2× A4988 or DRV8825 stepper motor driver boards
- 2× Bipolar stepper motors (NEMA 17, NEMA 23, or similar)
- External power supply (8-35V for A4988, 8-45V for DRV8825)
- Breadboard or PCB for wiring
- 100µF capacitor across power supply terminals (recommended)

### A4988 vs DRV8825

| Feature | A4988 | DRV8825 |
|---------|-------|---------|
| Max current | 2A/phase | 2.5A/phase |
| Voltage range | 8-35V | 8.2-45V |
| Microstepping | 1, 1/2, 1/4, 1/8, 1/16 | 1, 1/2, 1/4, 1/8, 1/16, 1/32 |
| Step pulse | >1µs | >1.9µs |
| Logic voltage | 3-5.5V | 2.5-5.25V |
| Cost | ~$1-2 | ~$2-3 |

**Both use identical pinout and interface** — STEP, DIR, EN pins work the same way. Code supports both without modification.

**Current adjustment:** Both drivers have a potentiometer to set max motor current. Measure VREF with multimeter and adjust:
- A4988: VREF = 8 × max_current
- DRV8825: VREF = max_current / 2

Start with VREF = 0.4V (A4988: 50mA, DRV8825: 800mA) and increase gradually while testing. Motor should not overheat (touchable after 5 min of operation).

### Wiring Diagram

```
ESP32 GPIO 25 ──→ A4988/DRV8825 #1 STEP
ESP32 GPIO 26 ──→ A4988/DRV8825 #1 DIR
ESP32 GPIO 27 ──→ A4988/DRV8825 #1 EN

ESP32 GPIO 14 ──→ A4988/DRV8825 #2 STEP
ESP32 GPIO 32 ──→ A4988/DRV8825 #2 DIR
ESP32 GPIO 33 ──→ A4988/DRV8825 #2 EN

External PSU +  ──→ Driver VMOT (both drivers)
External PSU -  ──→ Driver GND (both drivers) ──→ ESP32 GND (CRITICAL!)

Stepper Motor 1:
  A4988/DRV8825 #1: 1A → Motor coil 1A
                    1B → Motor coil 1B
                    2A → Motor coil 2A
                    2B → Motor coil 2B

Stepper Motor 2:
  A4988/DRV8825 #2: 1A → Motor coil 1A
                    1B → Motor coil 1B
                    2A → Motor coil 2A
                    2B → Motor coil 2B
```

**CRITICAL: Common ground connection**

ESP32 GND MUST connect to motor power supply GND. Without common ground, the 3.3V logic signals from ESP32 have no voltage reference and drivers won't recognize them.

**Motor coil identification:**

Bipolar steppers have 4 wires (2 coils, 2 wires per coil). To identify coil pairs:
1. Use multimeter in resistance mode
2. Measure between all wire pairs
3. Wires with ~2-10Ω resistance are in the same coil
4. Wires with infinite resistance are in different coils

Example: Motor has red, blue, green, black wires:
- Red-Blue: 4Ω → coil A (connect to 1A, 1B)
- Green-Black: 4Ω → coil B (connect to 2A, 2B)
- Red-Green: infinite → different coils

### Microstepping Configuration

Microstepping is set via hardware pins on the driver (MS1/MS2/MS3 on A4988, M0/M1/M2 on DRV8825). NOT configurable via SCPI.

**A4988 microstepping pins:**

| MS1 | MS2 | MS3 | Resolution | Steps/rev (1.8° motor) |
|-----|-----|-----|------------|------------------------|
| LOW | LOW | LOW | Full step | 200 |
| HIGH | LOW | LOW | Half step | 400 |
| LOW | HIGH | LOW | Quarter step | 800 |
| HIGH | HIGH | LOW | Eighth step | 1600 |
| HIGH | HIGH | HIGH | Sixteenth step | 3200 |

**DRV8825 microstepping pins:**

| M0 | M1 | M2 | Resolution | Steps/rev (1.8° motor) |
|----|----|----|------------|------------------------|
| LOW | LOW | LOW | Full step | 200 |
| HIGH | LOW | LOW | Half step | 400 |
| LOW | HIGH | LOW | Quarter step | 800 |
| HIGH | HIGH | LOW | Eighth step | 1600 |
| LOW | LOW | HIGH | Sixteenth step | 3200 |
| HIGH | LOW | HIGH | Thirty-second step | 6400 |

Connect MS/M pins to GND (LOW) or 3.3V/5V (HIGH) or leave floating (internal pull-down to LOW on most driver boards).

**Recommended: 1/8 or 1/16 step for smoothness.** Full step is coarse and can cause vibration at low speeds. Higher microstepping = smoother motion, lower torque, slower max speed.

### Power Supply Sizing

**Voltage:** Match motor rated voltage (typically 12V or 24V). Higher voltage = higher top speed, but don't exceed driver max (35V for A4988, 45V for DRV8825).

**Current:** Motor rated current × number of motors × 1.5 safety margin.

Example: 2× NEMA 17 motors (1.5A each) → PSU should be ≥2 × 1.5 × 1.5 = 4.5A

Common PSU choices:
- **12V 5A** (60W) — sufficient for 2× NEMA 17 motors
- **24V 5A** (120W) — sufficient for 2× NEMA 23 motors

**DO NOT power motors from ESP32 VIN or 5V pins.** Stepper drivers can draw several amps under load. Use a dedicated bench power supply or wall adapter rated for continuous operation.

## Installation

### Arduino IDE Setup

1. Install ESP32 board support:
   - File → Preferences → Additional Board Manager URLs:
   - Add: `https://raw.githubusercontent.com/espressif/arduino-esp32/gh-pages/package_esp32_index.json`
   - Tools → Board → Boards Manager → search "ESP32" → Install

2. Open `scpi-stepper.ino` in Arduino IDE

3. Edit WiFi credentials (lines 33-34):
   ```cpp
   const char* ssid = "YourSSID";
   const char* password = "YourPassword";
   ```

4. Connect ESP32 via USB

5. Tools → Board → ESP32 Dev Module

6. Tools → Port → (select USB serial port)

7. Click Upload

8. Open Serial Monitor (115200 baud) to see IP address

### Testing

1. Power on external supply (motors + drivers)
2. Verify ESP32 boots and connects to WiFi
3. Note IP address from Serial Monitor
4. Test connectivity: `telnet <ip> 5025`
5. Send test command: `*IDN?` → should return identification string

## SCPI Command Reference

### Common Commands (IEEE 488.2)

- `*IDN?` — Identification query
  - Returns: `N0GQ,ESP32-SCPI-Stepper,1.0,2026`
- `*RST` — Reset (stop all motors, home positions to 0)
- `SYST:ERR?` — System error query
  - Returns: `0,"No error"`

### STEP Subsystem

#### Position Commands

- `STEP:POS (@n),<steps>` — Move motor n by relative steps
  - Positive steps = forward/CW
  - Negative steps = backward/CCW
  - Example: `STEP:POS (@1),800` — move motor 1 forward 800 steps

- `STEP:POS? (@n)` — Query motor n position in steps
  - Returns: Current step count (signed integer)
  - Example response: `1600`

- `STEP:HOME (@n)` — Reset motor n position counter to zero
  - Does NOT physically move motor (just resets counter)
  - Use after manually positioning motor at home/reference position

#### Speed Commands

- `STEP:SPEED (@n),<rpm>` — Set motor n speed in RPM
  - Default: assumes 200 steps/revolution (1.8° motor, full step)
  - If using microstepping, scale RPM accordingly
  - Example: `STEP:SPEED (@1),60` — 60 RPM

- `STEP:SPEED? (@n)` — Query motor n speed
  - Returns: Current speed in RPM
  - Example response: `60.00`

**Speed calculation:**

For a 1.8° motor (200 steps/rev at full step):
- Full step: 200 steps/rev → `STEP:SPEED (@1),60` = 60 RPM
- 1/8 step: 1600 steps/rev → `STEP:SPEED (@1),60` = 60 RPM (code assumes 200, so actual RPM is 60/8 = 7.5 RPM)

**To compensate for microstepping:**
- 1/8 step mode → multiply desired RPM by 8 in command
- Example: Want 30 RPM at 1/8 step → `STEP:SPEED (@1),240`

**Max speed:** Limited by `MIN_STEP_DELAY_US = 100µs` → max 10,000 steps/sec = 3000 RPM at full step (unrealistically high; motors typically limited to 300-1000 RPM).

#### Enable Commands

- `STEP:EN (@n),<0|1>` — Enable (1) or disable (0) motor n
  - Disabled motor is de-energized (no holding torque)
  - Enabled motor is energized (holding torque applied)
  - Example: `STEP:EN (@1),1` — enable motor 1

- `STEP:EN? (@n)` — Query motor n enable state
  - Returns: `0` (disabled) or `1` (enabled)

**Power saving:** Disable motors when not in use to reduce heat and power consumption. Motors can be manually positioned when disabled.

#### Direction Commands

- `STEP:DIR (@n),<CW|CCW>` — Set motor direction (informational only)
  - Direction is determined by sign of steps in `STEP:POS` command
  - This command exists for API compatibility but doesn't affect behavior

- `STEP:DIR? (@n)` — Query motor direction
  - Returns: `CW` or `CCW` (based on current target position)

#### Control Commands

- `STEP:STOP (@n)` — Emergency stop motor n
  - Stops motion immediately
  - Current position becomes target position
  - Motor remains enabled

- `STEP:STAT? (@n)` — Query motor n status
  - Returns: `MOVING` or `STOPPED`

### Channel Numbering

Motors are numbered 1 and 2 (SCPI convention). Commands use `(@1)` or `(@2)` syntax.

Example: `STEP:POS (@2),1600` — move motor 2 forward 1600 steps

### Error Responses

All errors return: `ERROR: <description>\n`

Common errors:
- `ERROR: Motor disabled` — attempted move while motor is disabled
- `ERROR: Invalid motor number` — motor number not 1 or 2
- `ERROR: Invalid syntax` — command format incorrect
- `ERROR: Unknown command` — command not recognized

## Usage Examples

### Python Control Script

```python
import socket
import time

class StepperController:
    def __init__(self, ip, port=5025):
        self.ip = ip
        self.port = port

    def send(self, cmd):
        s = socket.socket()
        s.connect((self.ip, self.port))
        s.sendall((cmd + '\n').encode())
        if '?' in cmd:
            resp = s.recv(1024).decode().strip()
            s.close()
            return resp
        s.close()

    def enable(self, motor):
        self.send(f'STEP:EN (@{motor}),1')

    def disable(self, motor):
        self.send(f'STEP:EN (@{motor}),0')

    def set_speed(self, motor, rpm):
        self.send(f'STEP:SPEED (@{motor}),{rpm}')

    def move(self, motor, steps):
        self.send(f'STEP:POS (@{motor}),{steps}')

    def position(self, motor):
        return int(self.send(f'STEP:POS? (@{motor})'))

    def is_moving(self, motor):
        return self.send(f'STEP:STAT? (@{motor})') == 'MOVING'

    def wait_for_stop(self, motor, poll_interval=0.1):
        while self.is_moving(motor):
            time.sleep(poll_interval)

    def home(self, motor):
        self.send(f'STEP:HOME (@{motor})')

    def stop(self, motor):
        self.send(f'STEP:STOP (@{motor})')

# Example usage
stepper = StepperController('192.168.1.42')

# Initialize
stepper.enable(1)
stepper.set_speed(1, 60)  # 60 RPM

# Move 800 steps forward
stepper.move(1, 800)
stepper.wait_for_stop(1)

# Move 400 steps backward
stepper.move(1, -400)
stepper.wait_for_stop(1)

# Check position
print(f"Position: {stepper.position(1)} steps")

# Home position
stepper.home(1)

# Disable motor
stepper.disable(1)
```

### Telnet Interactive Control

```bash
$ telnet 192.168.1.42 5025
*IDN?
N0GQ,ESP32-SCPI-Stepper,1.0,2026

STEP:EN (@1),1
OK

STEP:SPEED (@1),30
OK

STEP:POS (@1),200
OK

STEP:POS? (@1)
200

STEP:STOP (@1)
OK

STEP:HOME (@1)
OK

STEP:POS? (@1)
0
```

### PyVISA Instrument Control

```python
import pyvisa

rm = pyvisa.ResourceManager('@py')
stepper = rm.open_resource('TCPIP::192.168.1.42::5025::SOCKET')

stepper.write('STEP:EN (@1),1')
stepper.write('STEP:SPEED (@1),60')
stepper.write('STEP:POS (@1),1600')

position = int(stepper.query('STEP:POS? (@1)'))
print(f"Motor 1 position: {position} steps")
```

## Use Cases

### Antenna Positioning

Rotate antenna on azimuth/elevation axes for pattern measurements:

```python
# Azimuth: 360° in 10° increments (using 1/8 microstepping, 200 steps/rev motor)
steps_per_degree = (200 * 8) / 360  # ~4.44 steps/degree

for azimuth in range(0, 360, 10):
    stepper.move(1, int(steps_per_degree * 10))  # 10° step
    stepper.wait_for_stop(1)
    measure_signal_strength()
```

### Linear Stage Control

Precise positioning for material testing, optics alignment, etc:

```python
# Linear stage with 8mm lead screw, 1/16 microstepping
steps_per_mm = (200 * 16) / 8  # 400 steps/mm

def move_to_position_mm(motor, position_mm):
    current_steps = stepper.position(motor)
    target_steps = int(position_mm * steps_per_mm)
    stepper.move(motor, target_steps - current_steps)
```

### Rotary Table

Index parts for drilling, photography, inspection:

```python
# 8-position indexing table
positions = 8
steps_per_position = (200 * 8) // positions  # 200 steps at 1/8 microstepping

for i in range(positions):
    stepper.move(1, steps_per_position)
    stepper.wait_for_stop(1)
    perform_operation()
```

### Sample Changer

Automated sample loading for RF measurements:

```python
# 6-sample carousel
samples = 6
stepper.enable(1)
stepper.set_speed(1, 30)  # Slow speed for smooth motion

for sample in range(samples):
    print(f"Loading sample {sample + 1}...")
    stepper.move(1, (200 * 8) // samples)  # 1/6 revolution
    stepper.wait_for_stop(1)
    time.sleep(1)  # Settling time
    measure_sample()
```

## Troubleshooting

### Motor doesn't move

1. **Check enable state:** `STEP:EN? (@1)` should return `1`
   - If `0`, send `STEP:EN (@1),1`

2. **Check power supply:**
   - Verify voltage at driver VMOT pin (should be 12V or 24V)
   - Check GND connection between ESP32 and power supply

3. **Check wiring:**
   - STEP, DIR, EN pins connected to correct ESP32 GPIOs
   - Motor coils connected to driver 1A/1B/2A/2B pins

4. **Check driver current:**
   - Measure VREF with multimeter
   - Too low → no torque; too high → overheating

5. **Check motor coil continuity:**
   - Use multimeter to verify coils are not open-circuit

### Motor vibrates or makes noise but doesn't rotate

- **Coil wiring incorrect:** Try swapping one coil pair (1A ↔ 1B or 2A ↔ 2B)
- **Current too low:** Increase VREF (turn potentiometer clockwise on driver)
- **Speed too high:** Reduce RPM via `STEP:SPEED` command
- **Microstepping mode mismatch:** Verify MS/M pins match expected microstepping

### Motor moves in wrong direction

- **Swap direction:** Send negative steps instead of positive (or vice versa)
- **OR swap one motor coil:** Exchange 1A with 1B (or 2A with 2B) in wiring

### Motor overheats

- **Current too high:** Reduce VREF
- **Motor disabled while energized:** Check enable state with `STEP:EN?`
- **Continuous operation:** Add heatsink to driver chip, improve airflow

### Motor loses steps

- **Speed too high:** Reduce RPM
- **Acceleration too fast:** This code has no acceleration control (instant speed change); for high-inertia loads, ramp speed manually in Python script
- **Insufficient torque:** Increase current (VREF), reduce load, use larger motor
- **Mechanical binding:** Check for obstructions, friction, misalignment

### ESP32 reboots during motor operation

- **Power supply noise:** Add 100µF capacitor across motor supply terminals near drivers
- **Insufficient motor PSU:** Check voltage doesn't drop below minimum when motors move
- **Ground loop:** Verify common ground between ESP32 GND and PSU GND

### "ERROR: Motor disabled" when sending STEP:POS command

- Motor is disabled (power-saving mode)
- Enable first: `STEP:EN (@1),1`

### Position drifts over time

- **Lost steps:** See "Motor loses steps" section
- **No absolute feedback:** This system is open-loop (no encoders). Position is relative to startup or last `STEP:HOME` command. For absolute positioning, add limit switches or encoders.

## Limitations

- **No acceleration/deceleration control:** Motor jumps to target speed instantly. For smooth motion with high-inertia loads, implement speed ramping in Python client code.

- **No endstops or limit switches:** Position is relative only. Add external limit switches and read via ESP32 GPIOs for absolute homing.

- **No encoder feedback:** Open-loop control. If motor stalls or loses steps, firmware doesn't know. Consider adding rotary encoder for closed-loop position verification.

- **Blocking during high-frequency commands:** Motors move asynchronously, but processing SCPI commands can interfere with step timing if commands are sent faster than motors move. For coordinated motion, use `STEP:STAT?` to poll for completion.

- **Single TCP client:** Only one client connection at a time. Additional clients are rejected until the first disconnects.

- **No authentication:** Any device on network can control motors. Add IP whitelist or token auth if deploying on untrusted networks.

## Performance Specifications

- **Step pulse width:** 2µs (exceeds A4988/DRV8825 minimum)
- **Max step rate:** ~10 kHz (10,000 steps/sec) at `MIN_STEP_DELAY_US = 100µs`
- **Speed range:** 1-3000 RPM at full step (practical limit: 300-1000 RPM)
- **Position resolution:** ±1 step (depends on microstepping: 0.056° at 1/16 step)
- **TCP command latency:** <10ms typical on local network

## Safety Considerations

- **Pinch hazard:** Stepper motors have high torque. Keep hands clear of moving parts.
- **Electrical shock:** Use insulated connectors for motor supply voltage. Don't touch exposed terminals while powered.
- **Thermal:** Drivers and motors can reach 60-80°C under load. Don't touch heatsinks or motor case during/after operation.
- **Mechanical stops:** If motor drives into hard stop, it will stall and draw high current. Implement limit switches or software position limits.
- **Runaway:** Test motion with low speed and short distances before deploying. Emergency stop: `STEP:STOP (@n)` or power off motor supply.

## Version History

- **1.0** (2026-06-12): Initial release
  - 2-motor control via SCPI
  - Speed, position, enable commands
  - Non-blocking motion
  - A4988 and DRV8825 driver support

## License

Public domain. No warranty. Use at your own risk.

## References

- [A4988 Datasheet](https://www.pololu.com/file/0J450/a4988_DMOS_microstepping_driver_with_translator.pdf)
- [DRV8825 Datasheet](https://www.ti.com/lit/ds/symlink/drv8825.pdf)
- [SCPI-1999 Specification](https://www.ivifoundation.org/downloads/SCPI/)
- [Stepper Motor Basics](https://www.pololu.com/category/120/stepper-motors)
