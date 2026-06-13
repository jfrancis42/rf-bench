# ESP32 SCPI Analog Multiplexer

Network-controlled analog multiplexer using CD4051/CD4052/CD4067 CMOS ICs with Standard Commands for Programmable Instruments (SCPI) over TCP/IP.

## Features

- **SCPI over TCP/IP** on port 5025 (industry standard)
- **Multiple mux IC support**: CD4051 (8-ch), CD4052 (dual 4-ch), CD4067 (16-ch)
- **Software-configurable mux type** via SCPI command
- **Channel selection** via 4-bit digital address
- **Enable/disable control** for signal isolation
- **ADC readback** on common I/O pin (0-3.3V, 12-bit)
- **WiFi connectivity** with configurable credentials
- **Standard SCPI commands** compatible with test equipment automation

## Hardware Requirements

- ESP32 development board (any variant with WiFi)
- CD4067 16-channel analog multiplexer (or CD4051/CD4052)
- Jumper wires
- (Optional) Breadboard or PCB for connections

### Supported Multiplexer ICs

| IC | Channels | Address Bits | On-Resistance | Supply Voltage |
|----|----------|--------------|---------------|----------------|
| CD4051 | 8 single-ended | 3 (S0-S2) | 80-120 Ω | 3-15V |
| CD4052 | Dual 4-channel | 2 (S0-S1) | 80-120 Ω | 3-15V |
| CD4067 | 16 single-ended | 4 (S0-S3) | 70 Ω | 3-15V |

### Wiring for CD4067 (16-channel, default)

#### Multiplexer Control

| ESP32 GPIO | CD4067 Pin | Function |
|------------|------------|----------|
| GPIO 25 | S0 | Address bit 0 (LSB) |
| GPIO 26 | S1 | Address bit 1 |
| GPIO 27 | S2 | Address bit 2 |
| GPIO 14 | S3 | Address bit 3 (MSB) |
| GPIO 32 | EN | Enable (active LOW) |
| GPIO 36 (ADC1_CH0) | COM | Common I/O (analog in/out) |
| 3.3V or 5V | VCC | Power supply |
| GND | GND | Ground |
| GND | VEE | Negative supply (or GND for unipolar signals) |

**Signal connections:** Connect CH0-CH15 on the CD4067 to the analog signals you want to switch.

#### Wiring for CD4051 (8-channel)

Same as CD4067 above, but:
- Leave GPIO 14 (S3) unconnected (only use S0-S2)
- Channels: CH0-CH7
- Send `MUX:TYPE,CD4051` to configure 8-channel mode

#### Wiring for CD4052 (Dual 4-channel)

Same as CD4067 above, but:
- Leave GPIO 27 (S2) and GPIO 14 (S3) unconnected (only use S0-S1)
- CD4052 has two independent muxes (A and B) sharing address and enable
- Only one COM monitored on GPIO 36 (connect to COMA)
- Send `MUX:TYPE,CD4052` to configure 4-channel mode

### Analog Signal Considerations

**Voltage range:**
- **Digital supply (VCC/GND):** 3-15V (3.3V or 5V typical)
- **Analog signals:** Must stay between VCC and VEE (or GND if VEE=GND)
- **ESP32 ADC readback:** 0-3.3V maximum on GPIO 36 (damage above 3.3V)

**Signal conditioning:** If analog signals exceed 3.3V, use voltage divider before ESP32 ADC readback. Multiplexer itself can handle higher voltages (up to VCC) on CH0-CH15.

**On-resistance:** CD4067 is 70 Ω typical. For high-impedance sources (>10 kΩ), on-resistance causes negligible error. For low-impedance (<100 Ω), voltage divider effect may be significant.

**Example:** 1V source with 50 Ω source impedance through 70 Ω mux into 10 kΩ load:
- Total series resistance: 50 + 70 = 120 Ω
- Voltage divider: 1V × (10000 / (10000 + 120)) = 0.988V (1.2% error)

**Bandwidth:** CD4067 has ~40 MHz analog bandwidth (-3dB). Suitable for audio, sensor signals, DC voltages, and low-frequency RF (AM radio, etc.). Not suitable for high-frequency RF (VHF/UHF).

**Crosstalk:** -60 dB at 1 MHz. Adjacent channels may couple weakly at RF frequencies. Add shielding or increase channel spacing for critical measurements.

## Software Setup

1. **Install Arduino IDE** with ESP32 board support
   - File → Preferences → Additional Board Manager URLs: `https://dl.espressif.com/dl/package_esp32_index.json`
   - Tools → Board → Boards Manager → Search "ESP32" → Install

2. **Configure WiFi credentials**
   - Edit `scpi-mux.ino`
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
Returns device identification string: `N0GQ,ESP32-SCPI-MUX,1.0,2026`

### Reset

```
*RST
```
Resets to channel 0, mux disabled (safe state).

### Channel Selection

```
MUX:CHAN,<n>        # Select channel n (0-based)
MUX:CHAN?           # Query selected channel
```

**Channel numbering:**
- CD4067: 0-15 (16 channels)
- CD4051: 0-7 (8 channels)
- CD4052: 0-3 (single mux, 4 channels)

**Examples:**
```
MUX:CHAN,0          # Select channel 0
MUX:CHAN,5          # Select channel 5
MUX:CHAN,15         # Select channel 15 (CD4067 only)
MUX:CHAN?           # Returns current channel (e.g., "5")
```

### Enable/Disable

```
MUX:EN,<0|1>        # 0 = disable, 1 = enable
MUX:EN?             # Query enabled state
```

**Enable pin is active LOW:** When enabled (EN=1), the CD4067 EN pin is driven LOW. When disabled (EN=0), EN pin is driven HIGH, disconnecting all channels.

**Use case:** Disable mux when not in use to reduce leakage current and improve isolation. Enable only when actively switching/reading signals.

**Examples:**
```
MUX:EN,1            # Enable mux (connect selected channel)
MUX:EN,0            # Disable mux (disconnect all channels)
MUX:EN?             # Returns "1" if enabled, "0" if disabled
```

### Read ADC on Common I/O

```
MUX:READ?           # Read voltage in volts (e.g., "1.234567")
MUX:READ:RAW?       # Read raw ADC counts 0-4095 (e.g., "1520")
```

**Voltage formula:** `voltage = (raw_counts / 4095) × 3.3V`

**ADC settling time:** ESP32 ADC takes ~1ms per reading. For best accuracy, wait 10-100ms after changing channels before reading (allows signal settling through mux on-resistance and input capacitance).

**Examples:**
```
MUX:CHAN,5          # Select channel 5
MUX:EN,1            # Enable mux
MUX:READ?           # Returns voltage (e.g., "2.456789")
MUX:READ:RAW?       # Returns raw ADC (e.g., "3021")
```

### Mux Type Configuration

```
MUX:TYPE,<CD4051|CD4052|CD4067>    # Set mux IC type
MUX:TYPE?                           # Query mux type
```

**Default:** CD4067 (16-channel)

**Why configure mux type?** Prevents selecting invalid channels (e.g., channel 15 doesn't exist on CD4051). Firmware enforces channel limits based on mux type.

**Examples:**
```
MUX:TYPE,CD4051     # Configure for 8-channel CD4051
MUX:CHAN,7          # OK (valid for CD4051)
MUX:CHAN,8          # ERROR (invalid for CD4051)

MUX:TYPE,CD4067     # Configure for 16-channel CD4067
MUX:CHAN,15         # OK (valid for CD4067)

MUX:TYPE?           # Returns "CD4067"
```

**Note:** Changing mux type resets selected channel to 0 if the current channel exceeds the new mux's maximum.

### System Error Query

```
SYST:ERR?
```
Returns `0,"No error"` (always, for this simple device).

### Command Format Notes

- Commands can be uppercase or lowercase (case-insensitive)
- Short form allowed: `MUX:CHAN` has no ambiguous short form
- Commands can be terminated with newline (`\n`), carriage return (`\r`), or semicolon (`;`)
- Multiple commands can be sent in one line separated by semicolons: `MUX:CHAN,5;MUX:EN,1;MUX:READ?`

## Usage Examples

### Telnet (interactive)

```bash
telnet 192.168.1.42 5025
*IDN?
MUX:TYPE,CD4067
MUX:CHAN,0
MUX:EN,1
MUX:READ?
MUX:CHAN,15
MUX:READ?
MUX:EN,0
```

### Netcat (command-line)

```bash
echo "MUX:CHAN,5" | nc 192.168.1.42 5025
echo "MUX:EN,1" | nc 192.168.1.42 5025
echo "MUX:READ?" | nc 192.168.1.42 5025
```

### Python (Socket)

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

# Configure for CD4067 (16-channel)
scpi_command('192.168.1.42', 5025, 'MUX:TYPE,CD4067')

# Scan all 16 channels
for ch in range(16):
    scpi_command('192.168.1.42', 5025, f'MUX:CHAN,{ch}')
    scpi_command('192.168.1.42', 5025, 'MUX:EN,1')
    time.sleep(0.01)  # Allow signal settling
    voltage = scpi_command('192.168.1.42', 5025, 'MUX:READ?')
    print(f"Channel {ch}: {voltage}V")

# Disable mux when done
scpi_command('192.168.1.42', 5025, 'MUX:EN,0')
```

### Python with pyvisa (instrument automation)

```python
import pyvisa
import time

rm = pyvisa.ResourceManager('@py')
mux = rm.open_resource('TCPIP::192.168.1.42::5025::SOCKET', 
                       read_termination='\n',
                       write_termination='\n')

print(mux.query('*IDN?'))

# Set mux type
mux.write('MUX:TYPE,CD4067')
print(f"Mux type: {mux.query('MUX:TYPE?')}")

# Read channel 10
mux.write('MUX:CHAN,10')
mux.write('MUX:EN,1')
time.sleep(0.01)  # Signal settling
voltage = float(mux.query('MUX:READ?'))
print(f"Channel 10: {voltage:.6f}V")

mux.close()
```

### Complete Multi-Channel Scan Script

```python
import socket
import time

def scpi_query(ip, port, cmd):
    s = socket.socket()
    s.connect((ip, port))
    s.sendall((cmd + '\n').encode())
    if '?' in cmd:
        resp = s.recv(1024).decode().strip()
        s.close()
        return resp
    s.close()

ip = '192.168.1.42'
port = 5025

# Configure for CD4051 (8-channel)
scpi_query(ip, port, 'MUX:TYPE,CD4051')
print(f"Mux type: {scpi_query(ip, port, 'MUX:TYPE?')}")

# Enable mux
scpi_query(ip, port, 'MUX:EN,1')

# Scan all channels with 100ms settling time
print("\nScanning channels:")
for ch in range(8):
    scpi_query(ip, port, f'MUX:CHAN,{ch}')
    time.sleep(0.1)  # 100ms settling
    voltage = float(scpi_query(ip, port, 'MUX:READ?'))
    raw = int(scpi_query(ip, port, 'MUX:READ:RAW?'))
    print(f"  CH{ch}: {voltage:.6f}V ({raw} counts)")

# Disable when done
scpi_query(ip, port, 'MUX:EN,0')
print("\nScan complete")
```

## Use Cases

### 1. Multi-Sensor Monitoring

Monitor 16 temperature sensors (DS18B20 analog outputs) or other slow-changing analog signals.

**Advantages over separate ADC channels:**
- Single ADC with multiplexer costs less than 16-channel ADC IC
- Expandable to 32+ channels with two CD4067s and GPIO address bit 4

**Limitations:**
- Sequential acquisition only (no simultaneous sampling)
- ~10-100ms per channel (mux switching + ADC settling)

### 2. DUT Switching for Automated Test

Switch between 16 different DUTs (Device Under Test) in ATE rack, measuring output voltage on each.

**Example:** Battery characterization rig testing 16 cells. Mux switches voltmeter input to each cell sequentially.

### 3. Antenna Selection

Switch between 8 antennas (CD4051) feeding one receiver. Use with IC-7300/IC-9700 for remote antenna switching.

**Wiring:** Each antenna feedline → CH0-CH7 inputs. COM → radio antenna connector.

**Warning:** CD4051/CD4067 on-resistance (70-120 Ω) is too high for transmit (causes loss and heating). Use external RF relay for TX switching. This mux is **RX only**.

### 4. Signal Source Selection

Switch between 16 different signal sources (function generators, oscillators, etc.) feeding one measurement instrument.

**Example:** Frequency standard comparison. Mux switches frequency counter input between 8 GPS-disciplined oscillators and 8 Rb standards.

### 5. Sensor Calibration Rig

Calibrate 16 sensors against one reference sensor by switching a single precision ADC (ADS1115) input across all 16.

**Why not just use 16 ADC channels?** Cost. One ADS1115 ($5) + one CD4067 ($1) is cheaper than four ADS1115s.

### 6. RF Detector Readout

Switch between 16 RF detector diodes measuring power at different points in an RF chain (e.g., multi-stage amplifier, each stage has detector).

**Example:** Measure gain compression in 16-stage distributed amplifier by monitoring detector voltage at each stage.

## Debugging

- **Serial Monitor (115200 baud)** shows WiFi connection status, IP address, and received SCPI commands
- **Connection refused:** Check IP address, port number (5025), and firewall settings
- **Readings always 0V or 3.3V:** Check signal connection to mux CHx pins and mux power supply
- **Wrong channel selected:** Verify address pin wiring (S0-S3) and mux type setting
- **Mux doesn't switch:** Check EN pin wiring (active LOW - should be LOW when enabled)
- **ADC reads incorrect voltage:** ESP32 ADC has known non-linearity; consider external ADC (ADS1115) for precision
- **Crosstalk between channels:** Add shielding, increase physical spacing, or reduce signal frequency
- **Signal attenuation:** Check on-resistance (70-120 Ω) against source/load impedance

## Performance Characteristics

### Switching Speed

**Address settling time:** ~100ns (CD4067 datasheet)  
**Enable/disable time:** ~100ns (CD4067 datasheet)  
**ESP32 GPIO write:** ~1µs (digitalWrite overhead)  
**Total switching time:** ~10µs (conservative, includes firmware overhead)

**Practical throughput:** For 16-channel scan with 1ms ADC read per channel: ~62 scans/sec (16ms per scan).

### ADC Accuracy (ESP32 Built-In)

**Resolution:** 12-bit (4096 counts)  
**Voltage range:** 0-3.3V (with 11dB attenuation)  
**LSB size:** 3.3V / 4096 = 0.806 mV  
**INL (integral nonlinearity):** ~2% FSR (poor, known ESP32 issue)  
**Noise:** ~10 mV RMS (unfiltered)

**For better accuracy:** Use external ADC (ADS1115 16-bit) connected to mux COM. See `~/rf-bench/projects/esp32/scpi-adc/` for ADS1115 SCPI controller.

### Signal Degradation Through Mux

**On-resistance:** 70-120 Ω (adds in series with source impedance)  
**Off isolation:** -50 dB at 1 MHz (unselected channels weakly couple)  
**Crosstalk:** -60 dB at 1 MHz (adjacent channels)  
**Bandwidth:** 40 MHz analog (-3dB)

**Voltage divider error calculation:**
```
V_out = V_in × (R_load / (R_load + R_on))
```

Example: 10 kΩ load, 100 Ω on-resistance → 1% error.

## Limitations and Caveats

- **Sequential acquisition only** — no simultaneous multi-channel sampling. For true simultaneous sampling, use multi-channel ADC IC (ADS1115 has only 4 channels; consider ADS1256 for 8-channel 24-bit simultaneous).
- **ESP32 ADC non-linearity** — ~2% INL. Calibrate or use external ADC for precision.
- **3.3V ADC limit** — ESP32 GPIO 36 damaged above 3.3V. Use voltage divider or external ADC if analog signals exceed 3.3V.
- **Not suitable for high-speed signals** — 40 MHz bandwidth is fine for audio/DC, but not VHF/UHF RF. Use RF relay or coaxial switch for >100 MHz.
- **No isolation between channels** — all channels share common substrate in CMOS die. Add external analog switches (ADG5412F) if true isolation is required.
- **No protection** — ESD or overvoltage can damage IC. Add series resistors (100-1kΩ) and clamping diodes if connecting to harsh environments.
- **Single common I/O** — CD4052 has two COM pins (one per mux), but this firmware only monitors one. To read both CD4052 muxes, add second ADC channel or use external ADC.

## Integration with Test Systems

This SCPI multiplexer integrates with:

- **LabVIEW** via VISA driver (use TCPIP SOCKET resource)
- **MATLAB** via `tcpip` or Instrument Control Toolbox
- **Python** via `pyvisa`, `socket`
- **Keysight VEE, TestStand, etc.** via standard SCPI/VISA interface

The standard SCPI command set and MUX subsystem make this compatible with automated test equipment (ATE) frameworks.

## Related Projects

- **`~/rf-bench/projects/esp32/scpi-relay/`** — 4-channel relay switching (higher current, slower, mechanical)
- **`~/rf-bench/projects/esp32/scpi-adc/`** — 16-bit ADS1115 ADC (precision alternative to ESP32 built-in ADC)
- **`~/rf-bench/projects/relay/`** — XL9535 I²C relay matrix (for RF signal routing, TX/RX isolation)

## License

Public domain. Use freely.

## Author

N0GQ — 2026-06-12
