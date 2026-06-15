# ESP32 SCPI ADC (ADS1115)

Network-controlled 16-bit 4-channel analog-to-digital converter using ADS1115 and SCPI over TCP/IP.

## Hardware

**MCU:** ESP32 dev board (any variant with WiFi)

**ADC:** ADS1115 16-bit 4-channel I2C ADC module with programmable gain amplifier

**Connections:**
```
ADS1115          ESP32
-------          -----
VDD      -->     3.3V (or 5V - ADS1115 is 2.0-5.5V tolerant)
GND      -->     GND
SCL      -->     GPIO 22 (I2C clock)
SDA      -->     GPIO 21 (I2C data)
ADDR     -->     GND (sets I2C address to 0x48, default)
ALERT    -->     (not connected - optional interrupt pin)

AIN0     -->     Analog input channel 0 (0 to VDD max)
AIN1     -->     Analog input channel 1
AIN2     -->     Analog input channel 2
AIN3     -->     Analog input channel 3
```

**I2C Address:** 0x48 (default, ADDR pin to GND)
- ADDR to GND → 0x48
- ADDR to VDD → 0x49
- ADDR to SDA → 0x4A
- ADDR to SCL → 0x4B

**Resolution:** 16-bit signed (-32768 to +32767)

**Input voltage ranges (programmable via PGA gain):**
- Gain 2/3 (0): ±6.144V
- Gain 1 (1): ±4.096V (default)
- Gain 2 (2): ±2.048V
- Gain 4 (4): ±1.024V
- Gain 8 (8): ±0.512V
- Gain 16 (16): ±0.256V

**Sample rates:** 8, 16, 32, 64, 128 (default), 250, 475, 860 samples/sec

**Input impedance:** 10 MΩ typical

**WARNING:** Do not exceed VDD + 0.3V on any analog input. For 3.3V supply, max input is ~3.6V. For 5V supply, max input is ~5.3V. The ±6.144V range is for differential inputs or when VDD = 5V.

## Features

- **4 independent channels** with per-channel programmable gain
- **16-bit resolution** (65536 steps) for high-precision voltage measurement
- **SCPI over TCP/IP** for LabVIEW/MATLAB/Python integration
- **Configurable sample rate** (8-860 SPS) to trade speed vs noise rejection
- **Network accessible** via WiFi (no USB required after programming)

## Software Setup

### Arduino IDE

1. Install ESP32 board support (Boards Manager → "esp32" by Espressif)
2. Install Adafruit ADS1X15 library:
   - Tools → Manage Libraries → "Adafruit ADS1X15" by Adafruit
   - This also installs dependency: Adafruit BusIO
3. Edit `scpi-adc.ino` and change WiFi credentials at top:
   ```cpp
   const char* ssid = "YourSSID";
   const char* password = "YourPassword";
   ```
4. Tools → Board → ESP32 Dev Module
5. Tools → Port → (select USB serial port)
6. Click Upload
7. Open Serial Monitor (115200 baud) to see IP address

### Serial Monitor Output

```
SCPI ADC (ADS1115)
==================
ADS1115 found at address 0x48

Connecting to YourNetwork.... connected!
IP address: 192.168.1.42
SCPI port: 5025

Ready for SCPI commands
```

## SCPI Commands

### Common Commands

- `*IDN?` — identification (returns "N0GQ,ESP32-SCPI-ADC,1.0,2026")
- `*RST` — reset (all channels to gain 1, 128 SPS)
- `SYST:ERR?` — system error query (returns "0,No error")

### Measurement Commands

- `MEAS:VOLT? (@n)` — read channel n voltage in volts (n = 0-3)
- `MEAS:VOLT:RAW? (@n)` — read channel n raw 16-bit ADC value (-32768 to +32767)
- `MEAS:ALL?` — read all 4 channels as CSV (returns "v0,v1,v2,v3")

### Configuration Commands

- `ADC:GAIN (@n),<gain>` — set PGA gain for channel n (gain = 0, 1, 2, 4, 8, or 16)
- `ADC:GAIN? (@n)` — query gain for channel n
- `ADC:RATE,<rate>` — set sample rate in SPS (rate = 8, 16, 32, 64, 128, 250, 475, 860)
- `ADC:RATE?` — query sample rate

**Channel numbering:** 0-3 (not 1-4 like most SCPI instruments). This matches ADS1115 datasheet convention.

**Gain values:**
- 0 → ±6.144V (gain 2/3)
- 1 → ±4.096V (gain 1, default)
- 2 → ±2.048V (gain 2)
- 4 → ±1.024V (gain 4)
- 8 → ±0.512V (gain 8)
- 16 → ±0.256V (gain 16)

**Sample rate:** Lower rates (8 SPS) have better noise rejection but slower acquisition. Higher rates (860 SPS) are faster but noisier. 128 SPS is a good balance.

## Usage Examples

### Telnet (manual testing)

```bash
telnet 192.168.1.42 5025

*IDN?
# N0GQ,ESP32-SCPI-ADC,1.0,2026

MEAS:VOLT? (@0)
# 1.234567

ADC:GAIN (@0),2
# OK

MEAS:VOLT? (@0)
# 1.234568  (now using ±2.048V range for better resolution)

MEAS:ALL?
# 1.234567,0.000123,-0.000456,3.298765

ADC:RATE,8
# OK

ADC:RATE?
# 8
```

### Python (socket)

```python
import socket

class SCPI_ADC:
    def __init__(self, ip, port=5025):
        self.ip = ip
        self.port = port
        self.sock = None

    def connect(self):
        self.sock = socket.socket()
        self.sock.settimeout(2.0)
        self.sock.connect((self.ip, self.port))

    def query(self, cmd):
        self.sock.sendall((cmd + '\n').encode())
        return self.sock.recv(1024).decode().strip()

    def write(self, cmd):
        self.sock.sendall((cmd + '\n').encode())

    def close(self):
        if self.sock:
            self.sock.close()

# Example usage
adc = SCPI_ADC('192.168.1.42')
adc.connect()

print(adc.query('*IDN?'))

# Read channel 0
voltage = float(adc.query('MEAS:VOLT? (@0)'))
print(f"Channel 0: {voltage:.6f} V")

# Set channel 1 to ±2.048V range for better resolution
adc.write('ADC:GAIN (@1),2')
voltage = float(adc.query('MEAS:VOLT? (@1)'))
print(f"Channel 1: {voltage:.6f} V")

# Read all channels
all_voltages = adc.query('MEAS:ALL?')
v0, v1, v2, v3 = [float(v) for v in all_voltages.split(',')]
print(f"All: {v0:.3f} V, {v1:.3f} V, {v2:.3f} V, {v3:.3f} V")

adc.close()
```

### Python (pyvisa)

```python
import pyvisa

rm = pyvisa.ResourceManager('@py')
adc = rm.open_resource('TCPIP::192.168.1.42::5025::SOCKET',
                       read_termination='\n',
                       write_termination='\n',
                       timeout=2000)

print(adc.query('*IDN?'))

# Set channel 0 to ±1.024V range (best for 0-1V signals)
adc.write('ADC:GAIN (@0),4')
voltage = float(adc.query('MEAS:VOLT? (@0)'))
print(f"Voltage: {voltage:.6f} V")

# Fast scan mode (860 SPS)
adc.write('ADC:RATE,860')
for i in range(10):
    v = float(adc.query('MEAS:VOLT? (@0)'))
    print(f"{i}: {v:.6f} V")

adc.close()
```

## Use Cases

### Automated Test Equipment

- **Sensor calibration:** Read sensor output voltage vs reference stimulus
- **Power supply testing:** Monitor voltage rails under load
- **Battery characterization:** Log discharge voltage vs time
- **Signal quality monitoring:** Measure DC bias on RF/audio circuits
- **Multi-point voltage logging:** 4 channels for simultaneous measurements

### RF Bench Integration

- **Detector diode readout:** Measure RF power via Schottky detector (0-1V → dBm)
- **VSWR bridge voltage:** Read forward/reflected power detector outputs
- **Temperature compensation:** Log voltage vs temperature for tempco measurement
- **Bias monitoring:** Check amplifier Vcc/Vee rails during RF sweep
- **Modulation envelope:** Slow envelope detection of AM/SSB signals (up to 860 Hz bandwidth)

### Data Logging

- **Environmental monitoring:** 4-channel temperature (via analog temp sensors like LM35, TMP36)
- **Battery management:** Monitor multi-cell pack voltage
- **Solar panel I-V curves:** Log voltage and current (via shunt resistor)
- **Slow-changing signals:** Thermocouple (via cold-junction compensated amplifier)

### Calibration and Characterization

- **ADC linearity test:** Compare ESP32 built-in ADC (12-bit, 0-3.3V) vs ADS1115 (16-bit, ±6.144V)
- **Voltage reference stability:** Monitor 1.25V / 2.5V / 5V references over time/temperature
- **DAC accuracy:** Measure DAC output voltage at each code
- **Resistor divider verification:** Check ratio accuracy

## Performance

### Resolution vs Range

| Gain | Full-Scale Range | LSB (Voltage per Bit) | Effective Bits (0.1% FS) |
|------|------------------|-----------------------|--------------------------|
| 0    | ±6.144V          | 187.5 µV              | ~13-14 bits              |
| 1    | ±4.096V          | 125 µV                | ~14 bits                 |
| 2    | ±2.048V          | 62.5 µV               | ~14-15 bits              |
| 4    | ±1.024V          | 31.25 µV              | ~15 bits                 |
| 8    | ±0.512V          | 15.625 µV             | ~15-16 bits              |
| 16   | ±0.256V          | 7.8125 µV             | ~16 bits                 |

**Note:** ADS1115 is specified at 16-bit resolution, but effective noise-free resolution is ~15 bits at 128 SPS. Lower sample rates (8-64 SPS) improve ENOB due to better noise rejection.

### Acquisition Speed

| Sample Rate | Time per Channel | Time for All 4 Channels |
|-------------|------------------|-------------------------|
| 8 SPS       | 125 ms           | 500 ms                  |
| 16 SPS      | 62.5 ms          | 250 ms                  |
| 32 SPS      | 31.25 ms         | 125 ms                  |
| 64 SPS      | 15.6 ms          | 62.5 ms                 |
| 128 SPS     | 7.8 ms           | 31.2 ms (default)       |
| 250 SPS     | 4 ms             | 16 ms                   |
| 475 SPS     | 2.1 ms           | 8.4 ms                  |
| 860 SPS     | 1.16 ms          | 4.64 ms                 |

**MEAS:ALL?** command reads all 4 channels sequentially, so total time = 4 × (1/sample_rate).

### Accuracy

- **Gain error:** ±0.15% FSR typical (±0.3% max)
- **Offset error:** ±3 LSB typical
- **INL:** ±0.01% FSR typical
- **Temperature coefficient:** ±10 ppm/°C typical

**Example:** At ±4.096V range (125 µV/bit), offset error of ±3 LSB = ±375 µV. For 1.000V input, gain error of 0.15% = ±1.5 mV. Combined error ~±2 mV, or 0.2%.

## Troubleshooting

### ADS1115 Not Found

Serial monitor shows:
```
ERROR: ADS1115 not found!
  - Check wiring (SDA -> GPIO 21, SCL -> GPIO 22)
  - Verify I2C address (default 0x48, ADDR pin to GND)
  - Check power (VDD to 3.3V or 5V)
```

**Solutions:**
1. Verify I2C wiring (SDA/SCL swapped is common mistake)
2. Check I2C address with `i2cdetect`:
   - Install `i2c-tools` on a Raspberry Pi or Linux PC
   - Connect ADS1115 to I2C bus
   - Run `i2cdetect -y 1` (or `-y 0` on older Pi)
   - Should show `48` at row 40, column 8
3. Verify power: measure VDD pin with multimeter (should be 3.3V or 5V)
4. Try different I2C address by changing ADDR pin connection

### Readings Always Zero

**Likely causes:**
1. No signal connected to analog input (0V is a valid reading)
2. Input voltage below noise floor (use higher gain for millivolt signals)
3. Input voltage exceeds full-scale range (saturated at +32767 or -32768)
4. Floating input (high impedance source may need pull-down resistor)

**Solutions:**
- Connect known voltage source (e.g., 1.5V battery between AIN0 and GND)
- Check raw ADC value with `MEAS:VOLT:RAW? (@0)` (should be non-zero if signal present)
- Reduce gain if input voltage > full-scale range (e.g., 5V signal with gain 1 = saturated)

### Noisy Readings

**Likely causes:**
1. Sample rate too high (860 SPS has less filtering than 8 SPS)
2. Poor grounding (ground loops, long ground wires)
3. EMI from WiFi (ADS1115 measures during WiFi transmission)
4. High-impedance source (10 MΩ input impedance may pick up noise)

**Solutions:**
- Lower sample rate: `ADC:RATE,8` (8 SPS has ~16× better noise rejection than 128 SPS)
- Shorten wires between signal source and ADS1115
- Add 0.1 µF capacitor between AIN and GND at source (low-pass filter)
- Use shielded cable for analog inputs (shield to GND)
- Use twisted pair for AIN+ and GND
- Add series resistor (1-10 kΩ) and capacitor at input (RC low-pass filter)

### Readings Incorrect (Consistent Offset)

**Likely causes:**
1. Input voltage exceeds VDD (clamps at VDD, reads high)
2. Wrong gain setting (e.g., gain 2/3 when expecting gain 1)
3. Differential input wired as single-ended (AINx should be to GND, not floating)
4. Calibration error (ADS1115 has ±0.15% gain error, ±3 LSB offset error)

**Solutions:**
- Verify input voltage with multimeter
- Check gain setting: `ADC:GAIN? (@0)`
- Ensure ADS1115 GND is connected to signal source GND
- For critical applications, perform 2-point calibration (0V and known reference voltage)

## ADS1115 vs ESP32 Built-In ADC

| Feature             | ADS1115         | ESP32 ADC1     |
|---------------------|-----------------|----------------|
| Resolution          | 16-bit          | 12-bit         |
| Voltage range       | ±6.144V to ±0.256V (programmable) | 0-3.3V (fixed, with attenuation) |
| INL                 | ±0.01% FSR      | ~2% FSR (poor linearity) |
| Channels            | 4 single-ended  | 8 channels (ADC1) |
| Sample rate         | 8-860 SPS       | Up to 200 kSPS |
| Input impedance     | 10 MΩ           | ~1 MΩ (varies with attenuation) |
| Noise               | ~15-16 ENOB     | ~9-10 ENOB     |
| Interface           | I2C             | Direct GPIO    |
| Best for            | Precision DC voltage | Fast, lower-precision sampling |

**Use ADS1115 when:** Accuracy matters (sensor calibration, voltage references, test equipment)

**Use ESP32 ADC when:** Speed matters, 12-bit resolution is sufficient, signals are 0-3.3V

## Differential vs Single-Ended Inputs

**This firmware uses single-ended mode** (each AINx input is measured relative to GND).

**ADS1115 also supports differential mode:**
- AIN0 - AIN1 (channel 0 differential)
- AIN2 - AIN3 (channel 1 differential)
- AIN0 - AIN3 (channel 2 differential)
- AIN1 - AIN3 (channel 3 differential)

**To enable differential mode** (future enhancement):
Replace `readADC_SingleEnded(n)` with `readADC_Differential_0_1()`, `readADC_Differential_2_3()`, etc. in firmware.

**Use differential mode for:**
- Wheatstone bridges
- Thermocouples
- Shunt resistor current sensing
- Rejecting common-mode noise

## Future Enhancements

- **Differential inputs:** Add SCPI commands for differential measurements
- **Continuous conversion mode:** Stream samples at sample rate (currently single-shot)
- **Comparator/threshold:** Use ALERT pin for hardware interrupt when voltage exceeds threshold
- **Calibration:** Store per-channel offset/gain correction in EEPROM
- **Multiple ADS1115 devices:** Support 2-4 ADS1115 on same I2C bus (16-64 channels total)
- **Web UI:** HTTP server with live voltage display (Chart.js)
- **Data logging:** Write samples to SD card or SPIFFS filesystem

## Related Projects

- **scpi-relay:** 4-channel relay controller (GPIO outputs)
- **scpi-temp:** DS18B20 temperature monitor (1-Wire sensors)
- **scpi-power:** INA219 voltage/current monitor (higher speed, lower resolution)
- **scpi-i2c:** I2C master bridge (generic I2C device access)

## References

- **ADS1115 datasheet:** [TI ADS111x](https://www.ti.com/lit/ds/symlink/ads1115.pdf)
- **Adafruit ADS1X15 library:** [GitHub](https://github.com/adafruit/Adafruit_ADS1X15)
- **SCPI specification:** IEEE 488.2, SCPI-1999
- **ESP32 datasheet:** [Espressif ESP32](https://www.espressif.com/sites/default/files/documentation/esp32_datasheet_en.pdf)

---

**Author:** N0GQ  
**License:** GPL-3.0-or-later  
**Version:** 1.0 (2026-06-12)
