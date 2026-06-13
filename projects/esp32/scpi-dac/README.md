# ESP32 SCPI DAC Controller

Network-accessible 4-channel 12-bit digital-to-analog converter (DAC) using MCP4728 I2C DAC and Standard Commands for Programmable Instruments (SCPI) over TCP/IP.

## Features

- **SCPI over TCP/IP** on port 5025 (industry standard)
- **4 independent DAC channels** (0-4095 raw, 12-bit resolution)
- **Voltage control** with automatic scaling based on Vref
- **Internal 2.048V reference** or **external Vref (VDD)** — 3.3V or 5V
- **2x gain mode** for internal Vref (0-4.096V output from 2.048V reference)
- **Rail-to-rail output** (0 to VDD)
- **22 mA max drive current** per channel
- **Nonvolatile EEPROM** for power-on defaults (future enhancement)
- **WiFi connectivity** with configurable credentials
- **Standard SCPI commands** compatible with test equipment automation

## Hardware Requirements

- ESP32 development board (any variant with WiFi)
- MCP4728 12-bit 4-channel I2C DAC breakout board
- Jumper wires
- Optional: External precision voltage reference (for high-accuracy applications)

### MCP4728 DAC Module

The MCP4728 is a quad 12-bit DAC with I2C interface and internal voltage reference:

**Key specifications:**
- 4 independent DAC channels (A, B, C, D)
- 12-bit resolution (4096 steps)
- Rail-to-rail buffered output (0 to VDD)
- Internal 2.048V reference with optional 2x gain
- External reference via VDD pin (3.3V or 5V)
- I2C address: 0x60 (default, configurable via LDAC/ADDR pins)
- Output settling time: 6-10 µs
- Integral nonlinearity (INL): ±0.2 LSB typical
- Differential nonlinearity (DNL): ±0.4 LSB typical
- Output impedance: <0.5 Ω (buffer amplifier)
- Load drive: 22 mA max per channel

### Wiring Diagram

```
ESP32                MCP4728 DAC
-----                -----------
3.3V or 5V --------- VCC (power supply, also external Vref)
GPIO 21 (SDA) ------ SDA (I2C data)
GPIO 22 (SCL) ------ SCL (I2C clock)
GND ---------------- GND

Optional:
                     LDAC -------- GND (immediate update mode)
                     ADDR -------- GND (I2C address 0x60)
                     VOUT_A ------ Output channel 1 (analog voltage)
                     VOUT_B ------ Output channel 2
                     VOUT_C ------ Output channel 3
                     VOUT_D ------ Output channel 4
```

**Critical notes:**
- **VCC voltage determines external Vref range:** 3.3V supply → 0-3.3V output, 5V supply → 0-5V output
- **LDAC pin:** Tie to GND for immediate update (DAC outputs change as soon as I2C command received). Leave floating or tie to VCC for latched mode (requires separate LDAC pulse to update outputs).
- **ADDR pin:** Tie to GND for I2C address 0x60 (default). Tie to VCC for 0x61 (allows two MCP4728s on same bus).
- **I2C pull-ups:** Most MCP4728 breakout boards have built-in 10kΩ pull-ups on SDA/SCL. External pull-ups not needed.

### Power Supply Selection

**For 0-3.3V output range:**
- Connect ESP32 3.3V pin to MCP4728 VCC
- Set `vdd_voltage = 3.3` in firmware (line 50)
- Use external Vref mode: `DAC:VREF,EXT`

**For 0-5V output range (recommended for most applications):**
- Connect external 5V supply (NOT ESP32 5V pin — insufficient current for load)
- Or use USB 5V if load current <100mA
- Set `vdd_voltage = 5.0` in firmware (line 50)
- Use external Vref mode: `DAC:VREF,EXT`

**For 0-2.048V or 0-4.096V output (high precision):**
- Use internal 2.048V reference: `DAC:VREF,INT`
- Gain 1x: 0-2.048V output
- Gain 2x: 0-4.096V output (command: `DAC:GAIN (@n),2`)
- VCC still needed for chip power, but output voltage independent of VCC fluctuations

**Current budget:**
- ESP32: ~150 mA (WiFi active)
- MCP4728 quiescent: 0.4 mA
- Output load: depends on application (measure with DMM)
- Total system: ESP32 + MCP4728 + 4× load currents

**If total load current >200 mA:** Use external 5V supply for MCP4728, NOT ESP32 5V pin.

## Software Setup

1. **Install Arduino IDE** with ESP32 board support
   - File → Preferences → Additional Board Manager URLs: `https://dl.espressif.com/dl/package_esp32_index.json`
   - Tools → Board → Boards Manager → Search "ESP32" → Install

2. **Install required library**
   - Tools → Manage Libraries
   - Search "Adafruit MCP4728" → Install
   - This also installs dependencies: Adafruit BusIO, Adafruit Unified Sensor

3. **Configure WiFi credentials**
   - Edit `scpi-dac.ino`
   - Change `ssid` and `password` near the top of the file

4. **Set VDD voltage** (if using 5V supply)
   - Edit line 50: `float vdd_voltage = 5.0;` (change from 3.3 to 5.0)

5. **Upload to ESP32**
   - Tools → Board → ESP32 Dev Module (or your specific board)
   - Tools → Port → (select your ESP32's serial port)
   - Click Upload

6. **Find the IP address**
   - Open Serial Monitor (115200 baud)
   - Reset the ESP32
   - Note the IP address printed (e.g., `192.168.1.42`)

## SCPI Command Reference

Connect to the ESP32 on port 5025 using any TCP client (`telnet`, `nc`, or Python `socket`).

### Identification

```
*IDN?
```
Returns device identification string: `N0GQ,ESP32-SCPI-DAC,1.0,2026`

### Reset

```
*RST
```
Sets all channels to 0V, external Vref mode, 1x gain.

### System Error Query

```
SYST:ERR?
```
Returns `0,"No error"` (always, for this simple device).

### Set Channel Voltage

```
DAC:VOLT (@1),1.5       # Set channel 1 to 1.5V
DAC:VOLT (@2),2.048     # Set channel 2 to 2.048V
DAC:VOLT (@3),0.0       # Set channel 3 to 0V (ground)
DAC:VOLT (@4),3.3       # Set channel 4 to 3.3V (max for 3.3V Vref)
```

**Voltage is automatically scaled** based on current Vref mode:
- External Vref (VDD): 0 to VDD volts (3.3V or 5V)
- Internal Vref, 1x gain: 0 to 2.048V
- Internal Vref, 2x gain: 0 to 4.096V

Returns `OK` on success, `ERROR: ...` on failure (e.g., voltage exceeds Vref).

**Note:** SCPI channel numbers are 1-indexed (1 to 4), not 0-indexed.

### Query Channel Voltage

```
DAC:VOLT? (@1)          # Query channel 1 voltage
DAC:VOLT? (@2)          # Query channel 2 voltage
```

Returns voltage with 4 decimal places (e.g., `1.5000`).

### Set Channel Raw Value (0-4095)

```
DAC:RAW (@1),2048       # Set channel 1 to mid-scale (2048/4095 of Vref)
DAC:RAW (@2),4095       # Set channel 2 to full-scale (maximum voltage)
DAC:RAW (@3),0          # Set channel 3 to 0 (ground)
DAC:RAW (@4),1024       # Set channel 4 to 1/4 scale
```

**Raw value:** 0 = 0V, 4095 = Vref (2.048V, 3.3V, 4.096V, or 5V depending on mode).

Returns `OK` on success, `ERROR: ...` if value out of range (0-4095).

### Query Channel Raw Value

```
DAC:RAW? (@1)           # Query channel 1 raw value
DAC:RAW? (@2)           # Query channel 2 raw value
```

Returns integer 0-4095 (e.g., `2048`).

### Set Vref Mode (All Channels)

```
DAC:VREF,INT            # Use internal 2.048V reference
DAC:VREF,EXT            # Use external reference (VDD = 3.3V or 5V)
```

**Internal mode (INT):**
- Vref = 2.048V (or 4.096V with 2x gain)
- Output independent of VCC supply voltage
- Best for precision applications (±0.2% reference accuracy)

**External mode (EXT):**
- Vref = VDD (3.3V or 5V, depending on power supply)
- Output tracks supply voltage
- Best for maximum output range (0-5V)

**Default:** External mode (EXT).

Returns `OK` on success.

### Query Vref Mode

```
DAC:VREF?
```

Returns `INT` or `EXT`.

### Set Gain (Internal Vref Only)

```
DAC:GAIN (@1),1         # Channel 1: 1x gain (0-2.048V)
DAC:GAIN (@2),2         # Channel 2: 2x gain (0-4.096V)
```

**Gain only applies when using internal Vref** (`DAC:VREF,INT`). In external Vref mode, gain setting is ignored.

- **1x gain:** 0-2.048V output
- **2x gain:** 0-4.096V output (doubles internal 2.048V reference)

**Default:** 1x gain.

Returns `OK` on success.

### Query Gain

```
DAC:GAIN? (@1)          # Query channel 1 gain
DAC:GAIN? (@2)          # Query channel 2 gain
```

Returns `1` or `2`.

### Set All Channels at Once

```
DAC:ALL,1.0,1.5,2.0,2.5  # Set ch1=1.0V, ch2=1.5V, ch3=2.0V, ch4=2.5V
DAC:ALL,0,0,0,0          # Set all channels to 0V
```

**Atomic update:** All four channels update simultaneously (within microseconds). Useful for synchronized multi-channel waveforms or state transitions.

Returns `OK` on success, `ERROR: ...` if any voltage out of range.

### Query All Channels

```
DAC:ALL?
```

Returns CSV of all four channel voltages (e.g., `1.0000,1.5000,2.0000,2.5000`).

### Command Format Notes

- Commands can be uppercase or lowercase (case-insensitive)
- Short form allowed: `DAC:VOLT` instead of `DAC:VOLTAGE`
- Commands can be terminated with newline (`\n`), carriage return (`\r`), or semicolon (`;`)
- Multiple commands can be sent in one line separated by semicolons: `DAC:VOLT (@1),1.5;DAC:VOLT (@2),2.0`

## Usage Examples

### Telnet (interactive)

```bash
telnet 192.168.1.42 5025
*IDN?
DAC:VREF,EXT          # Use 3.3V or 5V VDD as Vref
DAC:VOLT (@1),1.5     # Set channel 1 to 1.5V
DAC:VOLT (@2),2.5     # Set channel 2 to 2.5V
DAC:VOLT? (@1)        # Query channel 1 (returns 1.5000)
DAC:ALL?              # Query all channels
*RST                  # Reset all to 0V
```

### Netcat (command-line)

```bash
echo "DAC:VOLT (@1),2.5" | nc 192.168.1.42 5025
echo "DAC:VOLT? (@1)" | nc 192.168.1.42 5025
echo "DAC:ALL?" | nc 192.168.1.42 5025
```

### Python (socket)

```python
import socket

def scpi_command(ip, port, command):
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.connect((ip, port))
        s.sendall((command + '\n').encode())
        if '?' in command:
            response = s.recv(1024).decode().strip()
            return response

# Set voltages
scpi_command('192.168.1.42', 5025, 'DAC:VOLT (@1),1.65')
scpi_command('192.168.1.42', 5025, 'DAC:VOLT (@2),2.5')
scpi_command('192.168.1.42', 5025, 'DAC:VOLT (@3),0.8')
scpi_command('192.168.1.42', 5025, 'DAC:VOLT (@4),3.3')

# Query voltages
v1 = float(scpi_command('192.168.1.42', 5025, 'DAC:VOLT? (@1)'))
v2 = float(scpi_command('192.168.1.42', 5025, 'DAC:VOLT? (@2)'))
print(f"Channel 1: {v1:.4f}V, Channel 2: {v2:.4f}V")

# Set all at once
scpi_command('192.168.1.42', 5025, 'DAC:ALL,1.0,1.5,2.0,2.5')

# Query all
voltages = scpi_command('192.168.1.42', 5025, 'DAC:ALL?')
print(f"All channels: {voltages}")
```

### Python with pyvisa (instrument automation)

If you have `pyvisa` and `pyvisa-py` installed:

```python
import pyvisa

rm = pyvisa.ResourceManager('@py')
dac = rm.open_resource('TCPIP::192.168.1.42::5025::SOCKET', 
                       read_termination='\n',
                       write_termination='\n')

print(dac.query('*IDN?'))

# Use external Vref (5V VDD)
dac.write('DAC:VREF,EXT')

# Set voltages
dac.write('DAC:VOLT (@1),2.5')
dac.write('DAC:VOLT (@2),3.3')

# Query back
v1 = float(dac.query('DAC:VOLT? (@1)'))
v2 = float(dac.query('DAC:VOLT? (@2)'))
print(f"Ch1: {v1:.3f}V, Ch2: {v2:.3f}V")

dac.close()
```

### Sweep Voltage Example

```python
import socket
import time

def set_voltage(ip, port, channel, volts):
    with socket.socket() as s:
        s.connect((ip, port))
        s.sendall(f'DAC:VOLT (@{channel}),{volts}\n'.encode())
        s.recv(1024)  # Read "OK"

IP = '192.168.1.42'
PORT = 5025
CHANNEL = 1

# Sweep 0 to 3.3V in 0.1V steps
for v in range(0, 34):
    volts = v * 0.1
    set_voltage(IP, PORT, CHANNEL, volts)
    print(f"Set {volts:.1f}V")
    time.sleep(0.5)

# Return to 0V
set_voltage(IP, PORT, CHANNEL, 0.0)
print("Sweep complete")
```

### Multi-Channel Synchronized Output

```python
import socket

def scpi_write(ip, port, cmd):
    with socket.socket() as s:
        s.connect((ip, port))
        s.sendall((cmd + '\n').encode())
        s.recv(1024)

IP = '192.168.1.42'
PORT = 5025

# Set all four channels to specific voltages simultaneously
scpi_write(IP, PORT, 'DAC:ALL,1.2,2.4,3.0,0.5')

# Sequence through multiple states
states = [
    (0.0, 0.0, 0.0, 0.0),  # All off
    (1.0, 0.0, 0.0, 0.0),  # Ch1 on
    (1.0, 2.0, 0.0, 0.0),  # Ch1+Ch2 on
    (1.0, 2.0, 3.0, 0.0),  # Ch1+Ch2+Ch3 on
    (1.0, 2.0, 3.0, 3.3),  # All on
]

for v1, v2, v3, v4 in states:
    scpi_write(IP, PORT, f'DAC:ALL,{v1},{v2},{v3},{v4}')
    time.sleep(1)
```

## Typical Applications

### Amplifier Bias Control

Set precise bias voltages for RF amplifiers, op-amps, or Class A/AB bias circuits:

```python
# Set VGS for MOSFET amplifier
scpi_write(IP, PORT, 'DAC:VOLT (@1),2.8')  # Gate bias
scpi_write(IP, PORT, 'DAC:VOLT (@2),12.0') # Drain supply (via level shifter)
```

### Variable Attenuator Control

Control voltage-controlled attenuators (e.g., HMC346, PE4302):

```python
# Sweep attenuation 0-31 dB (0-5V control voltage)
for atten_db in range(0, 32):
    volts = atten_db * 5.0 / 31.0
    scpi_write(IP, PORT, f'DAC:VOLT (@1),{volts}')
    time.sleep(0.1)
```

### VCO Tuning Voltage

Generate tuning voltage for voltage-controlled oscillators:

```python
# Sweep VCO from 100 MHz to 200 MHz (0-5V tune range)
for freq_mhz in range(100, 201):
    volts = (freq_mhz - 100) / 100.0 * 5.0
    scpi_write(IP, PORT, f'DAC:VOLT (@1),{volts}')
    # Measure frequency with counter, log data
```

### Power Supply Sequencing

Generate precise turn-on/turn-off sequences for multi-rail systems:

```python
# Power-on sequence: 3.3V → 5V → 12V with delays
scpi_write(IP, PORT, 'DAC:VOLT (@1),3.3')  # Rail 1
time.sleep(0.01)
scpi_write(IP, PORT, 'DAC:VOLT (@2),5.0')  # Rail 2
time.sleep(0.01)
scpi_write(IP, PORT, 'DAC:VOLT (@3),3.0')  # Rail 3 control (12V via boost)
```

### Component Characterization

Sweep voltage across varactor, LED, diode, or transistor and measure I-V curve:

```python
import socket

def measure_iv(ip, port, dac_ch, vstart, vend, vstep):
    results = []
    for v in range(int(vstart * 1000), int(vend * 1000), int(vstep * 1000)):
        volts = v / 1000.0
        # Set voltage via DAC
        with socket.socket() as s:
            s.connect((ip, port))
            s.sendall(f'DAC:VOLT (@{dac_ch}),{volts}\n'.encode())
            s.recv(1024)
        
        time.sleep(0.05)  # Settling time
        
        # Measure current with DMM (separate SCPI connection)
        # current = query_dmm(...)
        
        # results.append((volts, current))
    
    return results

# Characterize varactor C-V curve
iv_data = measure_iv('192.168.1.42', 5025, 1, 0.0, 5.0, 0.1)
```

### Sensor Calibration

Generate known reference voltages to calibrate ADCs or analog sensor circuits:

```python
# Generate 0.5V, 1.0V, 1.5V, 2.0V, 2.5V reference points
# User measures with DUT and records actual readings for cal table
ref_voltages = [0.5, 1.0, 1.5, 2.0, 2.5]

for v in ref_voltages:
    scpi_write(IP, PORT, f'DAC:VOLT (@1),{v}')
    input(f"Calibration point: {v}V. Measure and record. Press Enter for next...")
```

### Servo Control (via level shifter)

Generate control voltage for non-PWM servos or motor controllers:

```python
# Control servo position via 0-5V analog input (if servo has analog mode)
scpi_write(IP, PORT, 'DAC:VOLT (@1),2.5')  # Center position
time.sleep(1)
scpi_write(IP, PORT, 'DAC:VOLT (@1),0.5')  # Min position
time.sleep(1)
scpi_write(IP, PORT, 'DAC:VOLT (@1),4.5')  # Max position
```

### Waveform Generation (Low Frequency)

Generate arbitrary low-frequency waveforms (limited by I2C update rate ~1 kHz):

```python
import math

def generate_sine(ip, port, channel, freq_hz, amplitude_v, offset_v, duration_sec):
    sample_rate = 100  # Hz (limited by I2C speed)
    samples = int(sample_rate * duration_sec)
    
    for i in range(samples):
        t = i / sample_rate
        v = offset_v + amplitude_v * math.sin(2 * math.pi * freq_hz * t)
        
        # Clamp to 0-Vref
        v = max(0.0, min(v, 5.0))
        
        with socket.socket() as s:
            s.connect((ip, port))
            s.sendall(f'DAC:VOLT (@{channel}),{v:.4f}\n'.encode())
            s.recv(1024)
        
        time.sleep(1.0 / sample_rate)

# Generate 1 Hz sine wave, 1V amplitude, 2.5V offset, 5 sec duration
generate_sine('192.168.1.42', 5025, 1, 1.0, 1.0, 2.5, 5.0)
```

## Debugging

### Serial Monitor (115200 baud)

The Serial Monitor shows:
- WiFi connection status and IP address
- MCP4728 initialization status
- Real-time SCPI commands received
- Error messages (invalid commands, out-of-range values)

**Expected boot output:**
```
SCPI DAC Controller
===================
I2C: SDA=21, SCL=22
MCP4728 initialized at 0x60
VDD voltage: 3.30V (update vdd_voltage in code if using 5V)
All channels set to 0V

Connecting to YourSSID.... connected!
IP address: 192.168.1.42
SCPI port: 5025

Ready for SCPI commands
Use DAC:VOLT (@n),<volts> to set channel voltage
Use DAC:RAW (@n),<0-4095> to set raw DAC value
```

### MCP4728 Not Found

**Error:** `ERROR: MCP4728 not found!`

1. **Check wiring:**
   - SDA → GPIO 21
   - SCL → GPIO 22
   - VCC → 3.3V or 5V
   - GND → GND
2. **Verify I2C address:**
   - Default: 0x60 (ADDR pin to GND or floating)
   - Alternate: 0x61 (ADDR pin to VCC)
   - If using 0x61, change firmware: `mcp.begin()` → `mcp.begin(0x61)`
3. **Scan I2C bus** (add to `setup()` temporarily):
   ```cpp
   Serial.println("Scanning I2C bus...");
   for (byte addr = 1; addr < 127; addr++) {
     Wire.beginTransmission(addr);
     if (Wire.endTransmission() == 0) {
       Serial.printf("Device found at 0x%02X\n", addr);
     }
   }
   ```
4. **Check power:** Measure VCC pin on MCP4728 — should be 3.3V or 5V.

### Output Voltage Incorrect

**Problem:** `DAC:VOLT (@1),2.5` command sent, but DMM reads 2.48V or 2.52V.

**Expected accuracy:**
- **Resolution:** 12-bit = 0.024% of full-scale (e.g., 0.8 mV steps at 3.3V Vref)
- **INL (integral nonlinearity):** ±0.2 LSB typical = ±0.16 mV at 3.3V Vref
- **Supply voltage variation:** If using external Vref (VDD), output tracks supply voltage

**Solutions:**
1. **Measure actual VDD voltage:**
   - Use DMM to measure ESP32 3.3V or 5V pin
   - Update `vdd_voltage` in firmware (line 50)
2. **Use internal Vref for precision:**
   - `DAC:VREF,INT` → 2.048V reference (±0.2% accuracy, independent of VDD)
3. **Calibrate per channel:**
   - Set known voltage (e.g., 2.000V)
   - Measure with calibrated DMM
   - Calculate offset, apply in software or external trim pot

### Output Voltage Drifts Over Time

**Problem:** Set 2.5V, but voltage drifts to 2.48V after 30 minutes.

**Causes:**
- **Temperature coefficient:** MCP4728 internal Vref is ±50 ppm/°C (0.1 mV/°C at 2.048V)
- **VDD fluctuation:** If using external Vref (VDD), output tracks supply voltage changes
- **Self-heating:** DAC chip warms up during operation (~5°C rise typical)

**Solutions:**
- Use internal Vref (`DAC:VREF,INT`) for better stability
- Add external precision voltage reference (e.g., LM4040, ADR4540) to Vref pin
- Wait 10-15 minutes after power-on for thermal stabilization
- Use voltage regulator with low temperature coefficient for VDD

### Output Voltage Saturates (Clips at Max)

**Problem:** Command `DAC:VOLT (@1),5.0` but output measures 3.28V (using 3.3V VDD).

**Cause:** Requested voltage exceeds current Vref.

**Solution:**
- Check current Vref: `DAC:VREF?` → returns `EXT` or `INT`
- If `EXT` with 3.3V VDD: max output is 3.3V
- If need 5V output: power MCP4728 from 5V supply, set `vdd_voltage = 5.0` in firmware
- If using internal Vref (2.048V): enable 2x gain for 4.096V max: `DAC:GAIN (@1),2`

### Noise on Output

**Problem:** DMM shows ±10 mV fluctuation on DAC output.

**Causes:**
- WiFi RF interference coupling into analog output traces
- Ground loops between ESP32 GND and load GND
- Insufficient power supply decoupling

**Solutions:**
- Add 0.1 µF ceramic capacitor + 10 µF electrolytic across VCC/GND at MCP4728
- Add 100 Ω series resistor + 1-10 µF capacitor at each DAC output (RC filter)
- Use shielded cable for DAC outputs, ground shield at one end only
- Keep WiFi antenna away from analog circuitry
- Use star grounding (all GNDs connect at single point)

### Slow Update Rate

**Problem:** Setting voltage via `DAC:VOLT` command takes 50-100 ms.

**Cause:** TCP/IP handshake, WiFi latency, and I2C transaction overhead.

**Expected update rate:** ~50-100 Hz (10-20 ms per command) over WiFi.

**Optimizations:**
- Use `DAC:ALL,v1,v2,v3,v4` to set all channels at once (4× faster than individual commands)
- Use raw mode `DAC:RAW (@n),<value>` to skip voltage-to-raw conversion math
- Reduce serial debug prints in firmware (comment out `Serial.printf` lines)
- For high-speed waveforms (>1 kHz), use function generator instead — MCP4728 is for slow control voltages

### Multiple Devices on Same I2C Bus

**Problem:** Want to use MCP4728 + OLED display on same I2C bus.

**Common I2C addresses:**
- MCP4728: 0x60 or 0x61
- OLED SSD1306: 0x3C or 0x3D
- No conflict — both can share same bus

**Solution:**
- Initialize both devices in `setup()`:
  ```cpp
  Wire.begin(21, 22);
  mcp.begin();        // 0x60
  display.begin(0x3C); // OLED at 0x3C
  ```

## Performance Notes

### Resolution and Accuracy

**12-bit resolution:**
- 4096 discrete steps (0 to 4095)
- Step size = Vref / 4095

**Resolution vs Vref:**
| Vref Mode | Vref Voltage | Step Size | Example |
|-----------|--------------|-----------|---------|
| Internal 1x | 2.048V | 0.5 mV | Setting 1.000V → raw 1999, actual 1.0005V |
| Internal 2x | 4.096V | 1.0 mV | Setting 2.000V → raw 1999, actual 2.001V |
| External 3.3V | 3.3V | 0.8 mV | Setting 1.650V → raw 2047, actual 1.649V |
| External 5V | 5V | 1.22 mV | Setting 2.500V → raw 2047, actual 2.499V |

**Accuracy (MCP4728 spec):**
- Integral nonlinearity (INL): ±0.2 LSB typical, ±2 LSB max
- Differential nonlinearity (DNL): ±0.4 LSB typical, ±1 LSB max
- Offset error: ±1 LSB typical
- Gain error: ±0.1% typical

**Practical accuracy:** ±5 mV typical at 3.3V Vref (internal reference mode, after warm-up).

### Update Rate

**TCP/IP command latency:** ~10-50 ms per command (WiFi overhead + I2C transaction + SCPI parsing).

**Maximum update rate:** ~50-100 Hz (using `DAC:VOLT` or `DAC:RAW` commands).

**For faster updates:** Use `DAC:ALL` to set all four channels simultaneously — 4× faster than individual commands.

**MCP4728 settling time:** 6-10 µs (hardware limit, not firmware bottleneck).

**For high-speed waveforms (>1 kHz):** Use dedicated function generator (SDG1062X, AD9833 DDS, etc.) — MCP4728 is designed for slow control voltages, not arbitrary waveform generation.

### Output Drive Capability

**MCP4728 output stage:** Rail-to-rail buffer amplifier, 22 mA max per channel.

**Load impedance:**
- **High-Z load (>10 kΩ):** No problem, milliamps of drive current.
- **Low-Z load (<1 kΩ):** May exceed 22 mA limit, causing voltage drop or damage.

**Example:** 3.3V output into 100 Ω load = 33 mA → exceeds 22 mA limit → output will sag.

**Solution for low-Z loads:** Add external buffer op-amp (e.g., TL072, OPA2134) after DAC output:
```
MCP4728 output → op-amp non-inv input
                 op-amp output → load
```

### Nonvolatile Memory (EEPROM)

MCP4728 has internal EEPROM to store power-on default values (DAC output, Vref mode, gain).

**Current firmware does NOT use EEPROM** — all channels reset to 0V on boot.

**Future enhancement:** Add `DAC:SAVE` command to write current values to EEPROM (power-on defaults).

## Integration with Test Systems

This SCPI DAC controller integrates with:

- **LabVIEW** via VISA driver (use TCPIP SOCKET resource)
- **MATLAB** via `tcpip` or Instrument Control Toolbox
- **Python** via `pyvisa`, `socket`, or higher-level automation frameworks
- **Keysight VEE, TestStand, etc.** via standard SCPI/VISA interface

The standard SCPI command set makes this compatible with automated test equipment (ATE) frameworks.

## License

Public domain. Use freely.

## Author

N0GQ — 2026-06-12
