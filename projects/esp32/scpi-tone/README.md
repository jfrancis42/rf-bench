# ESP32 SCPI Tone Generator

Network-controlled audio tone generator using ESP32 PWM output. Generates tones from 20 Hz to 20 kHz with adjustable amplitude. Useful for audio testing, frequency response measurement, signal injection, and speaker/buzzer testing.

## Features

- **Frequency range:** 20 Hz to 20 kHz (full audio spectrum)
- **Amplitude control:** 0-100% via separate PWM output (optional low-pass filtering)
- **SCPI commands:** Standard test equipment command set over TCP/IP
- **Network control:** WiFi connection, port 5025 (SCPI standard)
- **Beep function:** Timed tone bursts for alerts and testing
- **Frequency sweep:** Linear sweep over time for frequency response testing
- **No external DAC required:** Uses ESP32 LED Control (LEDC) PWM peripheral

## Hardware Connections

### Tone Output (GPIO 25)

**For speaker:**
```
ESP32 GPIO 25 ---[100uF cap]---[100-220Ω resistor]--- Speaker (8-32Ω) --- GND
```

The series capacitor blocks DC, and the resistor limits current. Use a speaker rated for 0.5-1W.

**For piezo buzzer:**
```
ESP32 GPIO 25 --- Piezo buzzer (+) --- Piezo buzzer (-) --- GND
```

Direct connection works because piezo buzzers are high impedance.

**For audio equipment input:**
```
ESP32 GPIO 25 ---[voltage divider]--- Audio input (line level ~1Vrms)
```

Use a voltage divider (e.g., 10kΩ + 3.3kΩ) to reduce the 3.3V PWM signal to line level (~1V).

### Amplitude Control (GPIO 26) — Optional

```
ESP32 GPIO 26 ---[1kΩ resistor]---+--- Amplitude control voltage (0-3.3V)
                                   |
                                [10uF cap]
                                   |
                                  GND
```

Low-pass filter converts PWM duty cycle to a DC voltage proportional to amplitude (0-100% → 0-3.3V). This can be used as a volume control input for an external amplifier or as a simple DAC output.

If you don't need amplitude control, leave GPIO 26 unconnected.

## WiFi Configuration

Edit `scpi-tone.ino` before uploading:

```cpp
const char* ssid = "YourSSID";
const char* password = "YourPassword";
```

## SCPI Commands

| Command | Function | Example | Response |
|---------|----------|---------|----------|
| `*IDN?` | Identification | `*IDN?` | `N0GQ,ESP32-SCPI-Tone,1.0,2026` |
| `*RST` | Reset to defaults | `*RST` | `OK` |
| `SYST:ERR?` | Query system error | `SYST:ERR?` | `0,"No error"` |
| `TONE:FREQ,<hz>` | Set frequency (20-20000 Hz) | `TONE:FREQ,1000` | `OK` |
| `TONE:FREQ?` | Query frequency | `TONE:FREQ?` | `1000.00` |
| `TONE:AMPL,<0-100>` | Set amplitude percent | `TONE:AMPL,75` | `OK` |
| `TONE:AMPL?` | Query amplitude | `TONE:AMPL?` | `75` |
| `TONE:OUTP,<0\|1>` | Enable/disable output | `TONE:OUTP,1` | `OK` |
| `TONE:OUTP?` | Query output state | `TONE:OUTP?` | `1` |
| `TONE:BEEP,<freq>,<ms>` | Play tone for duration | `TONE:BEEP,1000,500` | `OK` |
| `TONE:SWEE,<start>,<end>,<ms>` | Frequency sweep | `TONE:SWEE,100,10000,5000` | `OK` |

**Default state:** 440 Hz (A4 note), 50% amplitude, output OFF.

**Beep and sweep are blocking:** The ESP32 will not respond to commands while a beep or sweep is in progress.

## Example Usage

### Python (raw socket)

```python
import socket
import time

def scpi_command(ip, port, cmd):
    """Send SCPI command and return response (if query)."""
    s = socket.socket()
    s.connect((ip, port))
    s.sendall((cmd + '\n').encode())
    if '?' in cmd:
        resp = s.recv(1024).decode().strip()
        s.close()
        return resp
    s.close()

# Connect to tone generator
IP = '192.168.1.42'  # Replace with your ESP32's IP address
PORT = 5025

# Identify device
idn = scpi_command(IP, PORT, '*IDN?')
print(f"Connected to: {idn}")

# Set 1 kHz tone at 75% amplitude
scpi_command(IP, PORT, 'TONE:FREQ,1000')
scpi_command(IP, PORT, 'TONE:AMPL,75')
scpi_command(IP, PORT, 'TONE:OUTP,1')  # Enable output
time.sleep(2)
scpi_command(IP, PORT, 'TONE:OUTP,0')  # Disable output

# Play a 2 kHz beep for 500 ms
scpi_command(IP, PORT, 'TONE:BEEP,2000,500')

# Sweep from 100 Hz to 10 kHz over 5 seconds
scpi_command(IP, PORT, 'TONE:SWEE,100,10000,5000')

# Query current frequency
freq = scpi_command(IP, PORT, 'TONE:FREQ?')
print(f"Current frequency: {freq} Hz")
```

### Telnet (interactive testing)

```bash
telnet 192.168.1.42 5025

*IDN?
TONE:FREQ,440
TONE:AMPL,50
TONE:OUTP,1
# Listen to tone
TONE:OUTP,0
TONE:BEEP,1000,1000
# 1 kHz beep for 1 second
```

### pyvisa (instrument automation)

```python
import pyvisa

rm = pyvisa.ResourceManager('@py')
tone = rm.open_resource('TCPIP::192.168.1.42::5025::SOCKET')

# Identify
print(tone.query('*IDN?'))

# Generate 440 Hz tone
tone.write('TONE:FREQ,440')
tone.write('TONE:AMPL,100')
tone.write('TONE:OUTP,1')

import time
time.sleep(2)

# Stop tone
tone.write('TONE:OUTP,0')

# Sweep test
tone.write('TONE:SWEE,20,20000,10000')  # Full audio range in 10 seconds
```

## Use Cases

1. **Speaker frequency response testing:** Sweep from 20 Hz to 20 kHz while measuring SPL with a microphone
2. **Audio amplifier testing:** Inject test tones to measure THD, gain, and frequency response
3. **Microphone calibration:** Known-frequency reference for microphone characterization
4. **Hearing test:** Generate pure tones at various frequencies for audiometry
5. **Signal tracing:** Inject tone into audio circuits to trace signal path
6. **Passive component testing:** Measure capacitor/inductor frequency response
7. **Alert system testing:** Beep function for annunciators and alarms
8. **Doppler effect demo:** Dynamic frequency changes via SCPI commands
9. **Musical tuning reference:** Generate A440 and other reference pitches
10. **Function generator replacement:** Low-frequency PWM signal source for non-critical applications

## Technical Details

### PWM Tone Generation

The ESP32 LEDC (LED Control) peripheral generates PWM signals with configurable frequency and duty cycle. For audio tone generation:

- **LEDC channel 0:** Tone output, 10-bit resolution, variable frequency (20-20000 Hz), 50% duty cycle
- **LEDC channel 1:** Amplitude control, 8-bit resolution, fixed 5 kHz carrier, variable duty cycle (0-100%)

The 50% duty cycle on the tone output creates a square wave, which contains the fundamental frequency plus odd harmonics. For a pure sine wave, use an external low-pass filter (e.g., 2-pole active filter with cutoff at 20 kHz).

### Amplitude Control Mechanism

GPIO 26 outputs a 5 kHz PWM signal with duty cycle proportional to amplitude. An external RC low-pass filter (cutoff ~16 Hz with 1kΩ and 10µF) converts this to a DC voltage:

- 0% amplitude → 0% duty cycle → 0V DC
- 50% amplitude → 50% duty cycle → 1.65V DC
- 100% amplitude → 100% duty cycle → 3.3V DC

This voltage can control:
- An analog multiplexer or VCA (voltage-controlled amplifier)
- An external DAC's reference voltage
- The gain control pin of an audio amplifier

If you don't need amplitude control, the amplitude PWM output can be ignored.

### Frequency Accuracy

LEDC frequency is derived from the ESP32's 80 MHz APB clock. Frequency resolution decreases at higher frequencies due to the 10-bit PWM counter limit. Typical accuracy:

- 20-100 Hz: ±0.01 Hz
- 100-1000 Hz: ±0.1 Hz
- 1000-10000 Hz: ±1 Hz
- 10000-20000 Hz: ±5 Hz

For reference-grade frequency accuracy, use an external DDS generator (e.g., AD9833) or GPS-disciplined oscillator.

## Limitations

- **Square wave output:** Fundamental + harmonics (not a pure sine wave). Add external low-pass filter for sine wave.
- **3.3V logic level:** Output is 0-3.3V square wave. May need attenuation for line-level audio equipment.
- **No amplitude control on tone output:** Amplitude PWM (GPIO 26) requires external filtering and scaling. The tone output itself (GPIO 25) is always full amplitude square wave.
- **Blocking beep/sweep:** ESP32 cannot process new commands during beep or sweep. Max duration is 60 seconds.
- **No harmonic filtering:** Output contains odd harmonics up to the Nyquist limit. Use external filter for THD-sensitive applications.
- **No frequency modulation:** Only fixed-frequency or linear sweep. For FM or arbitrary modulation, consider using an external DDS chip.
- **Single channel:** Mono output only. For stereo, use two ESP32s or add a second LEDC channel.

## Future Enhancements

- **I2S DAC output:** True 16-bit sine wave generation using ESP32 I2S peripheral and external DAC (e.g., PCM5102)
- **Wavetable synthesis:** Store sine/triangle/sawtooth waveforms in flash, play via I2S
- **Frequency modulation:** SCPI commands for FM sweep, chirp, warble
- **Amplitude modulation:** Dynamic amplitude control via SCPI
- **Dual-tone generation:** Simultaneous output of two frequencies for DTMF, IMD testing
- **DTMF encoding:** Telephone keypad tone generation
- **Morse code:** CW keying with configurable WPM
- **THD measurement:** Analyze output harmonics via FFT
- **Web interface:** Browser-based tone generator control
- **EEPROM presets:** Save/recall favorite frequencies and amplitudes

## Related Projects

- **~/rf-bench/projects/signal-sources/**: Signal generator characterization scripts
- **~/rf-bench/drivers/siglent/**: SDG1062X function generator driver (full-featured arbitrary waveform generator)
- **~/CodeMonkey/**: CW (Morse code) transceiver with audio keying
- **~/jf8call/**: JS8 digital mode modem with audio I/O
- **~/rf-bench/projects/audio/**: Radio audio chain testing tools

## Building and Uploading

### Arduino IDE

1. Install ESP32 board support: File → Preferences → Additional Board Manager URLs:
   ```
   https://dl.espressif.com/dl/package_esp32_index.json
   ```
2. Tools → Board → ESP32 Arduino → ESP32 Dev Module
3. Tools → Port → (select your ESP32's USB serial port)
4. Edit WiFi credentials in `scpi-tone.ino`
5. Click Upload
6. Open Serial Monitor (115200 baud) to see IP address

### PlatformIO

```bash
cd ~/Dropbox/build/rf-bench/projects/esp32/scpi-tone
pio init --board esp32dev
pio run -t upload
pio device monitor -b 115200
```

## Troubleshooting

**No sound from speaker:**
- Check series capacitor polarity (electrolytic capacitors have +/- markings)
- Verify speaker impedance (8-32Ω typical)
- Increase amplitude: `TONE:AMPL,100`
- Enable output: `TONE:OUTP,1`
- Test with beep command: `TONE:BEEP,1000,1000`

**Distorted sound:**
- Reduce amplitude if speaker is overdriven
- Add series resistor (100-220Ω) to limit current
- Use low-pass filter to remove harmonics

**No network connection:**
- Verify WiFi credentials match your network
- Check Serial Monitor for IP address on boot
- Ensure ESP32 and control PC are on same subnet
- Try telnet to port 5025 to test connectivity

**Frequency drift or glitches:**
- ESP32 PWM frequency changes slightly with temperature
- For stable frequency reference, use external oscillator
- Avoid blocking operations (e.g., WiFi scanning) while tone is playing

## Author

Jeff Francis / N0GQ  
Created: 2026-06-12  
Part of rf-bench: https://github.com/jfrancis42/rf-bench
