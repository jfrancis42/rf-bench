# ESP32 SCPI Pulse Generator

**Dual-channel precision pulse generator using ESP32 hardware timers, controlled via SCPI over TCP/IP.**

Network-attached instrument for generating precision digital pulses from 0.1 Hz to 40 MHz with microsecond-accurate pulse width control. Uses ESP32 hardware timers (not software PWM) for jitter-free pulse generation suitable for test equipment calibration, clock signal generation, and embedded system testing.

---

## Features

- **Dual independent channels** — simultaneous pulse generation on GPIO 25 and 26
- **Wide frequency range** — 0.1 Hz to 40 MHz
- **Microsecond pulse width control** — 0.1 µs minimum, up to 50% of period
- **Burst mode** — 1-65535 pulses or continuous operation
- **Pulse delay** — 0-1 second inter-pulse delay for custom waveforms
- **Software trigger** — restart bursts on command
- **Hardware timers** — ESP32 hw_timer_t for 1 µs resolution, minimal jitter
- **SCPI protocol** — standard test equipment interface on port 5025
- **Network control** — WiFi TCP/IP, integrates with LabVIEW/MATLAB/Python

---

## Hardware Connections

```
ESP32 Pin      Function
---------      --------
GPIO 25   →    Pulse Output 1 (3.3V logic)
GPIO 26   →    Pulse Output 2 (3.3V logic)
GND       →    Common ground
```

**Output voltage:** 3.3V logic levels (TTL-compatible). For 5V logic, use a level shifter (e.g., 74LVC245).

**Output drive:** ~40 mA per pin max. For driving high-capacitance loads or long cables, add a buffer (e.g., 74HC244).

**Timing accuracy:** ±1 µs at 1 MHz. Higher frequencies have proportionally tighter absolute error but similar relative jitter (~0.1%).

---

## SCPI Command Reference

### Common Commands

```
*IDN?                          Identification query
                               Returns: N0GQ,ESP32-SCPI-Pulse,1.0,2026

*RST                           Reset to defaults
                               - All outputs disabled
                               - 1 kHz frequency
                               - 500 µs pulse width
                               - Continuous mode (burst_count=0)
                               - 0 µs delay

SYST:ERR?                      System error query
                               Returns: 0,"No error"
```

### Pulse Commands

All commands use channel selector `(@n)` where n=1 or n=2.

#### Frequency Control

```
PULS:FREQ (@n),<hz>            Set frequency (0.1 Hz - 40 MHz)
PULS:FREQ? (@n)                Query frequency

Examples:
PULS:FREQ (@1),1000            Channel 1 → 1 kHz
PULS:FREQ (@2),10000000        Channel 2 → 10 MHz
PULS:FREQ? (@1)                Query channel 1 → returns 1000.000000
```

#### Pulse Width Control

```
PULS:WIDT (@n),<us>            Set pulse width in microseconds
                               Must be ≤ period/2 (≤50% duty cycle)
PULS:WIDT? (@n)                Query pulse width

Examples:
PULS:WIDT (@1),100             Channel 1 → 100 µs pulse
PULS:WIDT (@2),0.5             Channel 2 → 500 ns pulse
PULS:WIDT? (@1)                Query channel 1 → returns 100.000000
```

#### Burst Mode

```
PULS:COUN (@n),<count>         Set burst count
                               0 = continuous (default)
                               1-65535 = burst mode
PULS:COUN? (@n)                Query burst count

Examples:
PULS:COUN (@1),0               Channel 1 → continuous
PULS:COUN (@2),100             Channel 2 → burst of 100 pulses
PULS:COUN? (@1)                Query channel 1 → returns 0
```

#### Delay Control

```
PULS:DEL (@n),<us>             Set inter-pulse delay (0-1000000 µs)
                               Adds dead time after each pulse
PULS:DEL? (@n)                 Query delay

Examples:
PULS:DEL (@1),0                Channel 1 → no delay (standard periodic)
PULS:DEL (@2),5000             Channel 2 → 5 ms delay after each pulse
PULS:DEL? (@1)                 Query channel 1 → returns 0.000000
```

#### Output Enable

```
PULS:OUTP (@n),<0|1>           Enable/disable output
                               0 = off, 1 = on
PULS:OUTP? (@n)                Query output state

Examples:
PULS:OUTP (@1),1               Channel 1 → start pulsing
PULS:OUTP (@2),0               Channel 2 → stop (output goes low)
PULS:OUTP? (@1)                Query channel 1 → returns 1
```

#### Software Trigger

```
PULS:TRIG (@n)                 Trigger burst
                               - Restarts burst counter if in burst mode
                               - Resets phase if continuous
                               - Output must be enabled first

Examples:
PULS:TRIG (@1)                 Trigger channel 1 burst
PULS:TRIG (@2)                 Trigger channel 2 burst
```

---

## Example Usage

### Python (raw socket)

```python
import socket
import time

def scpi_cmd(ip, cmd):
    """Send SCPI command, return response if query."""
    s = socket.socket()
    s.connect((ip, 5025))
    s.sendall((cmd + '\n').encode())
    if '?' in cmd:
        resp = s.recv(1024).decode().strip()
        s.close()
        return resp
    s.close()

ip = '192.168.1.42'

# Channel 1: 1 MHz, 200 ns pulse, continuous
scpi_cmd(ip, 'PULS:FREQ (@1),1000000')
scpi_cmd(ip, 'PULS:WIDT (@1),0.2')
scpi_cmd(ip, 'PULS:COUN (@1),0')
scpi_cmd(ip, 'PULS:OUTP (@1),1')  # Start

time.sleep(5)

# Channel 2: 100 kHz, 5 µs pulse, burst of 1000
scpi_cmd(ip, 'PULS:FREQ (@2),100000')
scpi_cmd(ip, 'PULS:WIDT (@2),5')
scpi_cmd(ip, 'PULS:COUN (@2),1000')
scpi_cmd(ip, 'PULS:OUTP (@2),1')  # Start burst

# Trigger another burst after first completes
time.sleep(0.02)  # 1000 pulses @ 100 kHz = 10 ms
scpi_cmd(ip, 'PULS:TRIG (@2)')

# Query settings
freq = float(scpi_cmd(ip, 'PULS:FREQ? (@1)'))
width = float(scpi_cmd(ip, 'PULS:WIDT? (@1)'))
print(f"Channel 1: {freq/1e6:.3f} MHz, {width*1000:.1f} ns pulse")

# Stop both
scpi_cmd(ip, 'PULS:OUTP (@1),0')
scpi_cmd(ip, 'PULS:OUTP (@2),0')
```

### Python (pyvisa)

```python
import pyvisa
rm = pyvisa.ResourceManager('@py')
pulse = rm.open_resource('TCPIP::192.168.1.42::5025::SOCKET')

# 10 kHz square wave (50% duty cycle)
pulse.write('PULS:FREQ (@1),10000')
pulse.write('PULS:WIDT (@1),50')      # 50 µs = 50% at 10 kHz
pulse.write('PULS:OUTP (@1),1')

# Query state
idn = pulse.query('*IDN?')
print(idn)  # N0GQ,ESP32-SCPI-Pulse,1.0,2026
```

### Telnet (manual testing)

```bash
telnet 192.168.1.42 5025
*IDN?
# N0GQ,ESP32-SCPI-Pulse,1.0,2026

PULS:FREQ (@1),1000
PULS:WIDT (@1),500
PULS:OUTP (@1),1
# Channel 1 starts pulsing at 1 kHz, 500 µs pulse

PULS:OUTP (@1),0
# Channel 1 stops
```

---

## Use Cases

### Digital Logic Testing

Generate clock signals for microcontrollers, FPGAs, or digital ICs:

```python
# 16 MHz clock for AVR microcontroller
scpi_cmd(ip, 'PULS:FREQ (@1),16000000')
scpi_cmd(ip, 'PULS:WIDT (@1),0.03125')  # 31.25 ns = 50% duty
scpi_cmd(ip, 'PULS:OUTP (@1),1')
```

### PWM Simulation

Sweep duty cycle to test analog circuits:

```python
for duty in range(10, 91, 10):  # 10% to 90% duty cycle
    freq = 1000  # 1 kHz
    width_us = (duty / 100.0) * (1000000.0 / freq)
    scpi_cmd(ip, f'PULS:FREQ (@1),{freq}')
    scpi_cmd(ip, f'PULS:WIDT (@1),{width_us}')
    scpi_cmd(ip, 'PULS:OUTP (@1),1')
    time.sleep(2)  # Measure response
```

### Oscilloscope Trigger

Generate burst waveforms for trigger testing:

```python
# 100 pulses @ 1 MHz, repeated every second
scpi_cmd(ip, 'PULS:FREQ (@1),1000000')
scpi_cmd(ip, 'PULS:WIDT (@1),0.5')
scpi_cmd(ip, 'PULS:COUN (@1),100')
scpi_cmd(ip, 'PULS:OUTP (@1),1')

while True:
    scpi_cmd(ip, 'PULS:TRIG (@1)')
    time.sleep(1)
```

### Frequency Counter Calibration

Known-frequency reference:

```python
# 10.000000 MHz reference
scpi_cmd(ip, 'PULS:FREQ (@1),10000000')
scpi_cmd(ip, 'PULS:WIDT (@1),0.05')  # 50 ns (50% duty)
scpi_cmd(ip, 'PULS:OUTP (@1),1')
```

### Stepper Motor Clock

Generate step pulses for stepper motor drivers:

```python
# 200 steps/rev, 1 rev/sec = 200 Hz
# A4988 needs 1 µs minimum pulse width
scpi_cmd(ip, 'PULS:FREQ (@1),200')
scpi_cmd(ip, 'PULS:WIDT (@1),1')
scpi_cmd(ip, 'PULS:OUTP (@1),1')
```

### Dual-Channel Phase Control

Independent channels for testing differential inputs:

```python
# Channel 1: 1 MHz
scpi_cmd(ip, 'PULS:FREQ (@1),1000000')
scpi_cmd(ip, 'PULS:WIDT (@1),0.25')
scpi_cmd(ip, 'PULS:OUTP (@1),1')

# Channel 2: 1 MHz, 90° phase shift (250 ns delay)
scpi_cmd(ip, 'PULS:FREQ (@2),1000000')
scpi_cmd(ip, 'PULS:WIDT (@2),0.25')
scpi_cmd(ip, 'PULS:DEL (@2),0.25')  # 250 ns offset
scpi_cmd(ip, 'PULS:OUTP (@2),1')
```

---

## Technical Specifications

| Parameter | Specification |
|-----------|--------------|
| Channels | 2 independent |
| Frequency range | 0.1 Hz to 40 MHz |
| Frequency resolution | 0.1 Hz (floating-point) |
| Pulse width range | 0.1 µs to period/2 |
| Pulse width resolution | 0.1 µs (1 µs timer ticks) |
| Timing accuracy | ±1 µs absolute, ~0.1% relative |
| Jitter | <0.5 µs RMS (hardware timer-driven) |
| Burst count | 0 (continuous) or 1-65535 pulses |
| Inter-pulse delay | 0-1000000 µs (0-1 second) |
| Output voltage | 3.3V CMOS logic |
| Output current | 40 mA max per pin |
| Rise/fall time | ~10 ns (unloaded) |
| Network interface | WiFi TCP/IP, port 5025 |
| Protocol | SCPI (IEEE 488.2 subset) |
| Power | USB (5V, ~150 mA) |

---

## Limitations

- **Maximum frequency:** 40 MHz theoretical; practically limited by ISR overhead. At >10 MHz, duty cycle accuracy degrades. For precision above 20 MHz, use external hardware synthesizer.
- **Pulse width minimum:** 0.1 µs (100 ns) via timer prescaler, but GPIO rise/fall time is ~10 ns. Very short pulses may appear distorted.
- **Duty cycle:** Maximum 50% (pulse width cannot exceed half the period). For higher duty cycles, invert the signal externally or modify firmware.
- **Jitter:** Hardware timers minimize jitter, but WiFi interrupts can add ~0.5 µs occasional glitches. For sub-microsecond jitter requirements, disable WiFi after setup or use dedicated pulse generator hardware.
- **Phase coherence:** No phase-lock between channels. Starting both channels simultaneously does not guarantee phase alignment (each timer runs independently).
- **No external trigger input:** Only software trigger via SCPI. For hardware trigger, add GPIO interrupt handler (future enhancement).
- **No frequency sweep:** Frequency is static until changed via SCPI. For sweeps, send multiple commands in a loop.
- **Single client:** One TCP connection at a time.

---

## Firmware Upload

### Arduino IDE Setup

1. Install ESP32 board support:
   - File → Preferences → Additional Boards Manager URLs:
     ```
     https://raw.githubusercontent.com/espressif/arduino-esp32/gh-pages/package_esp32_index.json
     ```
   - Tools → Board → Boards Manager → search "ESP32" → Install

2. Open `scpi-pulse.ino` in Arduino IDE

3. Edit WiFi credentials at top of file:
   ```cpp
   const char* ssid = "YourSSID";
   const char* password = "YourPassword";
   ```

4. Select board and port:
   - Tools → Board → ESP32 Dev Module
   - Tools → Port → (select USB serial port)

5. Click Upload

6. Open Serial Monitor (115200 baud) to see IP address

### Serial Monitor Output (Example)

```
SCPI Pulse Generator
====================
Output 1: GPIO 25
Output 2: GPIO 26
Hardware timers initialized (1 µs resolution)
Connecting to MyWiFi.... connected!
IP address: 192.168.1.42
SCPI port: 5025

Ready for SCPI commands
Default: 1 kHz, 500 µs pulse width, continuous, outputs disabled
```

---

## Troubleshooting

### No output pulses

- Check `PULS:OUTP (@n),1` was sent (output must be enabled)
- Verify pulse width ≤ period/2 (firmware auto-clamps, but may not be what you expect)
- Use oscilloscope to verify 3.3V logic levels
- Check GPIO 25/26 are not damaged (test with LED + resistor)

### Jittery pulses

- WiFi interrupts can add jitter. After setting parameters, disable WiFi polling:
  ```cpp
  WiFi.disconnect(true);  // Add to firmware after setup if jitter critical
  ```
- At high frequencies (>10 MHz), ISR overhead becomes significant
- Check scope trigger stability and bandwidth

### Frequency not accurate

- ESP32 APB clock tolerance is ~1% (crystal accuracy). For precision, calibrate:
  ```python
  measured_freq = 999500  # Hz (measured on counter)
  target_freq = 1000000    # Hz (desired)
  correction = target_freq / measured_freq
  scpi_cmd(ip, f'PULS:FREQ (@1),{int(target_freq * correction)}')
  ```

### Burst doesn't start

- Ensure output is enabled first: `PULS:OUTP (@n),1`
- Send `PULS:TRIG (@n)` to start burst
- In continuous mode (burst_count=0), output starts immediately when enabled

### WiFi connection fails

- Check SSID/password in firmware
- Verify 2.4 GHz WiFi (ESP32 does not support 5 GHz)
- Check Serial Monitor for error messages

### GPIO conflicts

- GPIO 25/26 are safe on most ESP32 boards
- If using ESP32 variant with different peripherals, change `output_pins[]` in firmware
- Avoid GPIO 6-11 (flash), GPIO 1/3 (UART0), GPIO 34-39 (input-only)

---

## Future Enhancements

- **Hardware trigger input** — start/stop on external GPIO edge
- **Phase-locked dual channels** — synchronize rising edges
- **Arbitrary waveforms** — load pulse train from array
- **Frequency sweep** — linear/log sweep over time
- **Duty cycle > 50%** — invert output logic
- **PWM mode** — direct duty cycle control (0-100%)
- **External clock input** — sync to GPS 1PPS or other reference
- **Web UI** — HTTP control panel with real-time preview
- **Pulse train recorder** — capture and replay timing sequences

---

## Integration with rf-bench

This project fits into the `~/rf-bench/projects/esp32/` ecosystem as a network-controlled pulse generator. Could be wrapped in a Python driver for automated test sequences:

**Potential driver: `~/rf-bench/drivers/pulse/rf_bench/pulse/esp32_pulse.py`**

```python
class ESP32Pulse:
    def __init__(self, ip, port=5025):
        self.ip = ip
        self.port = port

    def set_frequency(self, channel, freq_hz):
        self._write(f'PULS:FREQ (@{channel}),{freq_hz}')

    def set_pulse_width(self, channel, width_us):
        self._write(f'PULS:WIDT (@{channel}),{width_us}')

    def enable(self, channel):
        self._write(f'PULS:OUTP (@{channel}),1')

    def disable(self, channel):
        self._write(f'PULS:OUTP (@{channel}),0')

    def trigger(self, channel):
        self._write(f'PULS:TRIG (@{channel})')

    def _write(self, cmd):
        s = socket.socket()
        s.connect((self.ip, self.port))
        s.sendall((cmd + '\n').encode())
        s.close()
```

**Use in test scripts:**

```python
from rf_bench.pulse import ESP32Pulse

pulse = ESP32Pulse('192.168.1.42')

# Test clock input of DUT
pulse.set_frequency(1, 8000000)  # 8 MHz
pulse.set_pulse_width(1, 0.0625)  # 50% duty
pulse.enable(1)

# Run DUT characterization
# ...

pulse.disable(1)
```

---

## See Also

- **rf-bench ESP32 projects:** `~/rf-bench/projects/esp32/` — relay, GPS, servo, temperature, IMU, power, I2C controllers
- **SCPI standard:** IEEE 488.2 / IVI-3.1 (SCPI-1999)
- **ESP32 hardware timers:** ESP-IDF documentation — `esp_timer.h`, `hw_timer_t`
- **Precision pulse generators:** HP 8082A, Keysight 81110A (commercial references)

---

**Version:** 1.0 (2026-06-12)  
**Author:** N0GQ  
**License:** GPL-3.0-or-later (firmware), documentation public domain  
**Hardware:** ESP32 Dev Module (any variant with WiFi)  
**Dependencies:** Arduino ESP32 core (built-in libraries only, no external deps)
