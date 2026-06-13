# ESP32 SCPI PWM Generator

8-channel hardware PWM generator controlled via Standard Commands for Programmable Instruments (SCPI) over TCP/IP.

## Features

- **8 independent PWM channels** with hardware generation (ESP32 LED PWM peripheral)
- **Frequency range:** 1 Hz - 40 kHz per channel
- **Duty cycle:** 0-100% with floating-point precision (8-bit resolution = 256 steps)
- **Independent control:** Each channel has separate frequency, duty cycle, and enable state
- **SCPI over TCP/IP** on port 5025 (industry standard)
- **WiFi connectivity** with configurable credentials
- **3.3V logic output** (compatible with most digital circuits, use level shifter for 5V if needed)
- **No external components required** (PWM generated entirely in ESP32 hardware)

## Hardware Requirements

- ESP32 development board (any variant with WiFi and LED PWM peripheral)
- (Optional) External loads: LEDs, motors, fans, heaters, etc.
- (Optional) Logic level shifter for 5V interfacing

### Pin Assignments

| Channel | GPIO | Use Cases |
|---------|------|-----------|
| PWM 1   | 25   | General purpose |
| PWM 2   | 26   | General purpose |
| PWM 3   | 27   | General purpose |
| PWM 4   | 14   | General purpose |
| PWM 5   | 32   | General purpose |
| PWM 6   | 33   | General purpose |
| PWM 7   | 23   | General purpose |
| PWM 8   | 19   | General purpose |

All outputs are 3.3V logic level. Maximum current per GPIO: 12 mA (do not drive loads directly - use transistor/MOSFET driver).

## Software Setup

1. **Install Arduino IDE** with ESP32 board support
   - File → Preferences → Additional Board Manager URLs: `https://dl.espressif.com/dl/package_esp32_index.json`
   - Tools → Board → Boards Manager → Search "ESP32" → Install

2. **Configure WiFi credentials**
   - Edit `scpi-pwm.ino`
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
Returns device identification: `N0GQ,ESP32-SCPI-PWM,1.0,2026`

### Reset

```
*RST
```
Disables all outputs and resets all channels to default (1 kHz, 50% duty cycle).

### Set Frequency

```
PWM:FREQ (@1),1000        # Set channel 1 to 1000 Hz
PWM:FREQ (@2),5000        # Set channel 2 to 5 kHz
PWM:FREQ (@8),100         # Set channel 8 to 100 Hz
```

Valid range: 1 - 40000 Hz. Values outside range are automatically clamped.

### Query Frequency

```
PWM:FREQ? (@1)            # Query channel 1 frequency
```

Returns frequency in Hz (e.g., `1000.00`).

### Set Duty Cycle

```
PWM:DUTY (@1),50          # Set channel 1 to 50%
PWM:DUTY (@2),25.5        # Set channel 2 to 25.5%
PWM:DUTY (@8),0           # Set channel 8 to 0% (always low)
PWM:DUTY (@4),100         # Set channel 4 to 100% (always high)
```

Valid range: 0.0 - 100.0%. Values outside range are automatically clamped.

### Query Duty Cycle

```
PWM:DUTY? (@1)            # Query channel 1 duty cycle
```

Returns duty cycle percentage (e.g., `50.00`).

### Enable Output

```
PWM:ON (@1)               # Enable channel 1 output
PWM:ON (@8)               # Enable channel 8 output
```

Starts PWM generation at the configured frequency and duty cycle.

### Disable Output

```
PWM:OFF (@1)              # Disable channel 1 output
PWM:OFF (@8)              # Disable channel 8 output
```

Stops PWM generation and sets output to LOW (0V).

### Query Output State

```
PWM:STAT? (@1)            # Query channel 1 enabled state
```

Returns `1` if enabled, `0` if disabled.

### System Error Query

```
SYST:ERR?
```
Returns `0,"No error"` (always, for this simple device).

### Command Format Notes

- Commands can be uppercase or lowercase (case-insensitive)
- Commands can be terminated with newline (`\n`), carriage return (`\r`), or semicolon (`;`)
- Multiple commands can be sent in one line separated by semicolons: `PWM:FREQ (@1),1000;PWM:DUTY (@1),50;PWM:ON (@1)`
- Channel numbers are 1-indexed (1-8)

## Usage Examples

### Telnet (interactive)

```bash
telnet 192.168.1.42 5025
*IDN?
PWM:FREQ (@1),1000
PWM:DUTY (@1),50
PWM:ON (@1)
PWM:STAT? (@1)
PWM:OFF (@1)
```

### Netcat (command-line)

```bash
echo "PWM:FREQ (@1),1000" | nc 192.168.1.42 5025
echo "PWM:DUTY (@1),75" | nc 192.168.1.42 5025
echo "PWM:ON (@1)" | nc 192.168.1.42 5025
echo "PWM:FREQ? (@1)" | nc 192.168.1.42 5025
```

### Python Socket

```python
import socket

def scpi_command(ip, port, command):
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.connect((ip, port))
        s.sendall((command + '\n').encode())
        if '?' in command:
            response = s.recv(1024).decode().strip()
            return response

# Configure channel 1: 1 kHz, 50% duty cycle
scpi_command('192.168.1.42', 5025, 'PWM:FREQ (@1),1000')
scpi_command('192.168.1.42', 5025, 'PWM:DUTY (@1),50')
scpi_command('192.168.1.42', 5025, 'PWM:ON (@1)')

# Query settings
freq = float(scpi_command('192.168.1.42', 5025, 'PWM:FREQ? (@1)'))
duty = float(scpi_command('192.168.1.42', 5025, 'PWM:DUTY? (@1)'))
enabled = int(scpi_command('192.168.1.42', 5025, 'PWM:STAT? (@1)'))

print(f"Channel 1: {freq} Hz, {duty}%, {'ON' if enabled else 'OFF'}")

# Disable output
scpi_command('192.168.1.42', 5025, 'PWM:OFF (@1)')
```

### Python with pyvisa

```python
import pyvisa

rm = pyvisa.ResourceManager('@py')
pwm = rm.open_resource('TCPIP::192.168.1.42::5025::SOCKET',
                       read_termination='\n',
                       write_termination='\n')

print(pwm.query('*IDN?'))

# Configure multiple channels
pwm.write('PWM:FREQ (@1),1000')
pwm.write('PWM:DUTY (@1),50')
pwm.write('PWM:ON (@1)')

pwm.write('PWM:FREQ (@2),5000')
pwm.write('PWM:DUTY (@2),25')
pwm.write('PWM:ON (@2)')

# Query all channels
for ch in range(1, 9):
    freq = float(pwm.query(f'PWM:FREQ? (@{ch})'))
    duty = float(pwm.query(f'PWM:DUTY? (@{ch})'))
    enabled = int(pwm.query(f'PWM:STAT? (@{ch})'))
    if enabled:
        print(f"PWM{ch}: {freq:.2f} Hz, {duty:.2f}%")

pwm.close()
```

### LED Dimming Example

```python
import socket
import time

def scpi_cmd(ip, port, cmd):
    with socket.socket() as s:
        s.connect((ip, port))
        s.sendall((cmd + '\n').encode())

# Configure LED on channel 1: 1 kHz PWM (invisible flicker)
scpi_cmd('192.168.1.42', 5025, 'PWM:FREQ (@1),1000')

# Fade in from 0% to 100%
scpi_cmd('192.168.1.42', 5025, 'PWM:ON (@1)')
for brightness in range(0, 101, 5):
    scpi_cmd('192.168.1.42', 5025, f'PWM:DUTY (@1),{brightness}')
    time.sleep(0.05)

# Fade out
for brightness in range(100, -1, -5):
    scpi_cmd('192.168.1.42', 5025, f'PWM:DUTY (@1),{brightness}')
    time.sleep(0.05)

scpi_cmd('192.168.1.42', 5025, 'PWM:OFF (@1)')
```

### Motor Speed Control Example

```python
# Assumes motor connected via MOSFET driver to GPIO 25 (channel 1)
# WARNING: Do NOT connect motor directly to ESP32 GPIO!

import socket

def scpi_cmd(ip, port, cmd):
    with socket.socket() as s:
        s.connect((ip, port))
        s.sendall((cmd + '\n').encode())

# Configure 25 kHz PWM (ultrasonic, no audible whine)
scpi_cmd('192.168.1.42', 5025, 'PWM:FREQ (@1),25000')

# Run motor at 75% speed
scpi_cmd('192.168.1.42', 5025, 'PWM:DUTY (@1),75')
scpi_cmd('192.168.1.42', 5025, 'PWM:ON (@1)')

# Stop motor
scpi_cmd('192.168.1.42', 5025, 'PWM:OFF (@1)')
```

### Analog Voltage Simulation (with RC low-pass filter)

```python
# External circuit: GPIO → 1kΩ resistor → 10µF capacitor → GND
# This creates a simple DAC with ~159 Hz cutoff frequency
# PWM frequency should be >> cutoff (use 10+ kHz)

import socket

def set_analog_voltage(ip, port, channel, voltage, vref=3.3):
    """Set analog voltage (0-3.3V) using PWM + RC filter."""
    duty = (voltage / vref) * 100.0
    with socket.socket() as s:
        s.connect((ip, port))
        s.sendall(f'PWM:FREQ (@{channel}),10000\n'.encode())
        s.sendall(f'PWM:DUTY (@{channel}),{duty:.2f}\n'.encode())
        s.sendall(f'PWM:ON (@{channel})\n'.encode())

# Generate 1.65V (50% of 3.3V) on channel 1
set_analog_voltage('192.168.1.42', 5025, 1, 1.65)

# Generate 2.0V on channel 2
set_analog_voltage('192.168.1.42', 5025, 2, 2.0)
```

## Application Examples

### LED Dimming / RGB Control

- **PWM frequency:** 500-2000 Hz (invisible flicker)
- **Duty cycle:** 0-100% brightness
- **3 channels** for RGB LED (red, green, blue)
- Add current-limiting resistors or use LED driver IC

### DC Motor Speed Control

- **PWM frequency:** 20-40 kHz (ultrasonic, no motor whine)
- **Interface:** MOSFET or motor driver IC (L293D, L298N, etc.)
- **WARNING:** Never connect motor directly to ESP32 GPIO (max 12 mA, motor draws 100+ mA)

### Servo Control

- **PWM frequency:** 50 Hz (standard RC servo)
- **Duty cycle:** 5-10% (1000-2000 µs pulse width on 20 ms period)
- **Note:** For servo control, use `scpi-servo` project instead (provides angle interface)

### Fan Speed Control (4-pin PWM fans)

- **PWM frequency:** 25 kHz (Intel spec for 4-pin PWM fans)
- **Duty cycle:** 20-100% (most fans have 20% minimum)
- **Wiring:** Fan PWM pin → ESP32 GPIO, fan power → 12V supply, common ground

### Heater Control (via SSR)

- **PWM frequency:** 1-10 Hz (SSR switching speed limit)
- **Interface:** Solid-state relay (SSR) with 3.3V trigger
- **Use case:** Temperature control via time-proportioning (duty cycle = % of full power)

### Clock Signal Generation

- **PWM frequency:** 1 Hz - 40 kHz
- **Duty cycle:** 50% (square wave)
- **Use case:** Test clock input for digital circuits, SPI/I2C emulation, frequency reference

### Audio Tone Generation (low quality)

- **PWM frequency:** 20 Hz - 20 kHz (audio range)
- **Duty cycle:** 50% (square wave)
- **Interface:** RC low-pass filter → audio amplifier
- **Note:** Square wave only (no sine), lots of harmonics

### Stepper Motor Control (with driver)

- **PWM frequency:** 100-2000 Hz (determines step rate)
- **Duty cycle:** 50%
- **Use 2-4 channels** for step/direction or 4-phase control
- **Interface:** A4988, DRV8825, or similar stepper driver

## Technical Details

### ESP32 LED PWM Peripheral

The ESP32 has 16 LED PWM channels (0-15) that generate hardware PWM with no CPU overhead. This project uses channels 0-7 for the 8 outputs.

- **Resolution:** 8-bit (256 duty cycle steps: 0-255)
- **Frequency range:** 1 Hz - 40 MHz (limited to 40 kHz in this implementation for stability)
- **Accuracy:** Clock derived from 80 MHz APB clock with divider
- **Jitter:** Minimal (hardware-generated, not software timing)

### Frequency and Resolution Trade-off

PWM frequency and duty cycle resolution are inversely related:

```
Max Frequency = APB_CLK / (2^resolution)
80 MHz / 256 = 312.5 kHz (for 8-bit resolution)
```

At very high frequencies (>40 kHz), jitter and clock divider granularity become significant. This project limits frequency to 40 kHz for reliable operation.

For higher frequencies or higher resolution, adjust `pwm_resolution` constant in code (but understand the trade-offs).

### Output Characteristics

- **Logic levels:** 0V (LOW), 3.3V (HIGH)
- **Drive strength:** ~12 mA per GPIO (sink or source)
- **Rise/fall time:** ~10 ns (unloaded)
- **Capacitive load limit:** ~50 pF (longer wires add capacitance and slow edges)

### Current Limitations

**Do NOT drive loads directly from ESP32 GPIO.** Maximum current is 12 mA per pin, 40 mA total for all pins combined. Exceeding this will:
- Damage the ESP32
- Cause voltage drops and erratic behavior
- Potentially destroy the GPIO driver transistor

**Always use external driver circuits:**
- **LEDs:** 220-470Ω resistor or LED driver IC
- **Motors:** MOSFET (IRLZ44N, 2N7000) or motor driver IC (L293D, L298N)
- **Relays:** Transistor + flyback diode or relay driver IC (ULN2003)
- **High-power loads:** SSR (solid-state relay) or MOSFET + gate driver

### 3.3V vs 5V Logic

ESP32 outputs are 3.3V. Most 5V logic accepts 3.3V as HIGH (typical threshold: 2.0-2.4V), but some devices require 5V.

**If interfacing with 5V logic:**
- **Logic level shifter:** Bidirectional (TXS0108E) or unidirectional (74HC125)
- **MOSFET buffer:** Low-side N-channel MOSFET (inverts signal)
- **3.3V-compatible devices:** Many modern ICs accept 3.3V inputs even with 5V supply

## Debugging

- **Serial Monitor (115200 baud)** shows WiFi connection status, IP address, and received SCPI commands
- **Connection refused:** Check IP address, port number (5025), and firewall settings
- **No PWM output:** Verify GPIO pin assignment and check that output is enabled (`PWM:ON`)
- **Incorrect frequency:** Use oscilloscope or logic analyzer to verify actual frequency (may be rounded to nearest achievable divider value)
- **Incorrect duty cycle:** 8-bit resolution means 256 steps (0.39% per step). Requested duty cycle is rounded to nearest step.
- **Multiple channels interfere:** If using external power supplies or ground loops, ensure all grounds are connected together

## Integration with Test Systems

This SCPI PWM generator integrates with:

- **LabVIEW** via VISA driver (use TCPIP SOCKET resource)
- **MATLAB** via `tcpip` or Instrument Control Toolbox
- **Python** via `pyvisa`, `socket`, or `PySerial`
- **Keysight VEE, TestStand, etc.** via standard SCPI/VISA interface

Use standard SCPI commands for automated test equipment (ATE) integration, signal generation for DUT testing, or automated characterization.

## Limitations

- **Single client connection** — only one TCP client at a time
- **No authentication** — any device on the network can control outputs (add IP whitelist if needed)
- **No waveform generation** — square wave only (use external function generator for sine/triangle/arbitrary)
- **No phase synchronization** — all channels run independently (no phase-locked outputs)
- **No frequency sweeps** — frequency is static (implement sweep via Python script if needed)
- **Finite frequency steps** — actual frequency is quantized by APB clock divider (not continuous)
- **GPIO drive limits** — 12 mA max per pin (use external driver for loads)

## Future Enhancements

- **Phase control** — `PWM:PHAS (@n),<degrees>` to set relative phase between channels
- **Sweep mode** — `PWM:SWE (@n),<start_hz>,<end_hz>,<step_hz>,<delay_ms>` for frequency sweeps
- **Pulse mode** — `PWM:PULS (@n),<count>` to emit N pulses then stop
- **Burst mode** — `PWM:BURS (@n),<on_ms>,<off_ms>` for time-gated bursts
- **Higher resolution** — 10-bit or 12-bit PWM (reduces max frequency)
- **Frequency/duty ramps** — smooth transitions over time
- **Trigger input** — external GPIO trigger to start/stop outputs synchronously
- **Web UI** — HTTP server with sliders for manual control

## License

Public domain. Use freely.

## Author

N0GQ — 2026-06-12
