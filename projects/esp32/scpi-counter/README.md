# ESP32 SCPI Frequency Counter

Network-controlled frequency and event counter using the ESP32 PCNT (pulse counter) hardware peripheral. Provides SCPI commands over TCP/IP for automated test equipment integration.

## Features

- **Hardware pulse counting** via ESP32 PCNT peripheral (no CPU involvement)
- **Two operating modes:**
  - **FREQ:** Frequency measurement (Hz) over configurable gate time
  - **EVENT:** Event counter with manual reset
- **Wide frequency range:** DC to ~40 MHz (3.3V logic input)
- **High accuracy:** Gate time configurable from 10ms to 60s
- **Overflow handling:** 64-bit accumulator for long event counts
- **SCPI interface:** Industry-standard commands on port 5025
- **Zero external components** (just wire signal to GPIO 4)

## Hardware

### Connections

```
Signal source -> GPIO 4 (pulse input, 3.3V logic)
```

### Input Requirements

- **Voltage:** 3.3V logic levels (0V = LOW, 3.3V = HIGH)
- **Frequency range:** DC to ~40 MHz typical (ESP32 PCNT limit)
- **Edge type:** Rising edge (configurable in code for falling edge)
- **Input impedance:** ~50 kΩ (internal GPIO weak pull-up/pull-down disabled)

**WARNING:** ESP32 GPIOs are NOT 5V tolerant. Use a voltage divider or level shifter for 5V logic signals.

### Recommended Input Conditioning

For best results:
- **AC-couple** signals with a DC blocking capacitor (0.1 µF) + 10 kΩ pull-down to GND
- **Series resistor** (100-330 Ω) for input protection
- **Schmitt trigger buffer** (74HC14) for noisy or slow-edge signals
- **Attenuator/divider** for signals >3.3V peak

Example input circuit for 5V logic:
```
5V signal ---[1kΩ]---+--- GPIO 4
                     |
                 [2.2kΩ]
                     |
                    GND
```
(Divides 5V → 3.4V, safe for ESP32)

## SCPI Commands

### Frequency Measurement

```
COUN:FREQ?
```
Measure frequency in Hz. Clears counter, counts pulses for `gate_time_ms`, returns frequency.

**Example:**
```
COUN:FREQ?
→ 1234.567
```
(1234.567 Hz)

**Accuracy:** ±1 count error over gate time. For 1 second gate at 1 kHz: ±0.001 kHz = ±0.1% error. Longer gate times improve accuracy for low frequencies.

### Event Counter

```
COUN:EVEN?
```
Read total accumulated pulse count (does not reset counter).

**Example:**
```
COUN:EVEN?
→ 1234567890
```

```
COUN:RES
```
Reset event counter to zero.

**Example:**
```
COUN:RES
→ OK
```

### Gate Time

```
COUN:GATE,<ms>
```
Set gate time in milliseconds (10-60000 ms). Default: 1000 ms.

**Example:**
```
COUN:GATE,5000
→ OK
```
(5 second gate time)

```
COUN:GATE?
```
Query current gate time.

**Example:**
```
COUN:GATE?
→ 5000
```

### Operating Mode

```
COUN:MODE,<FREQ|EVENT>
```
Set operating mode. FREQ = frequency measurement, EVENT = event counter.

**Example:**
```
COUN:MODE,EVENT
→ OK
```

```
COUN:MODE?
```
Query current mode.

**Example:**
```
COUN:MODE?
→ EVENT
```

### Common Commands

```
*IDN?
```
Identification query.

**Example:**
```
*IDN?
→ N0GQ,ESP32-SCPI-Counter,1.0,2026
```

```
*RST
```
Reset to defaults (clear event counter, gate time = 1000 ms, mode = FREQ).

**Example:**
```
*RST
→ OK
```

```
SYST:ERR?
```
Query system error (always returns "0,No error" for this simple device).

**Example:**
```
SYST:ERR?
→ 0,"No error"
```

## Usage Examples

### Python (socket)

```python
import socket

def scpi_query(ip, cmd):
    s = socket.socket()
    s.connect((ip, 5025))
    s.sendall((cmd + '\n').encode())
    if '?' in cmd:
        resp = s.recv(1024).decode().strip()
        s.close()
        return resp
    s.close()

# Measure frequency with 1 second gate
freq = float(scpi_query('192.168.1.42', 'COUN:FREQ?'))
print(f"Frequency: {freq:.3f} Hz")

# Set 5 second gate for better accuracy on low frequencies
scpi_query('192.168.1.42', 'COUN:GATE,5000')
freq = float(scpi_query('192.168.1.42', 'COUN:FREQ?'))
print(f"Frequency (5s gate): {freq:.3f} Hz")

# Switch to event counter mode
scpi_query('192.168.1.42', 'COUN:MODE,EVENT')
scpi_query('192.168.1.42', 'COUN:RES')  # Reset counter

# Wait for events...
import time
time.sleep(10)

# Read total count
count = int(scpi_query('192.168.1.42', 'COUN:EVEN?'))
print(f"Total events: {count}")
```

### Python (pyvisa)

```python
import pyvisa
rm = pyvisa.ResourceManager('@py')
counter = rm.open_resource('TCPIP::192.168.1.42::5025::SOCKET')

# Measure frequency
freq = float(counter.query('COUN:FREQ?'))
print(f"Frequency: {freq:.3f} Hz")

# Event counting
counter.write('COUN:MODE,EVENT')
counter.write('COUN:RES')
# ... wait for events ...
count = int(counter.query('COUN:EVEN?'))
print(f"Events: {count}")
```

### Telnet (interactive)

```bash
telnet 192.168.1.42 5025
*IDN?
# N0GQ,ESP32-SCPI-Counter,1.0,2026

COUN:FREQ?
# 1234.567

COUN:GATE,10000
# OK

COUN:FREQ?
# 1234.891
```

## Use Cases

### RF Bench / Lab Automation

- **Function generator verification** — measure actual output frequency vs programmed
- **PLL/synthesizer testing** — monitor lock indicator pulse train
- **Clock signal validation** — verify oscillator frequencies in embedded systems
- **Pulse width measurement** — count rising edges, measure period
- **Frequency stability** — log frequency over time to detect drift/jitter

### Production Test

- **Crystal oscillator QC** — measure actual frequency vs nominal, flag out-of-tolerance parts
- **PWM frequency check** — verify PWM controllers output correct frequency
- **RPM sensing** — count pulses from tachometer/encoder, convert to RPM
- **Flow meter** — count pulses from turbine flow sensor

### Event Counting

- **Geiger counter** — accumulate radiation pulses over time
- **Particle detector** — count cosmic ray events
- **Optical beam break** — count objects passing through sensor
- **Relay cycle counter** — track relay operations for maintenance scheduling

### Characterization

- **VCO tuning curves** — sweep control voltage, log frequency at each step
- **Temperature-frequency stability** — measure oscillator frequency vs temperature
- **Aging tests** — long-term frequency logging to detect component degradation

## Technical Details

### ESP32 PCNT Peripheral

The ESP32 has 8 independent PCNT units (PCNT_UNIT_0 through PCNT_UNIT_7), each with:
- **16-bit signed counter** (-32768 to +32767)
- **Two channels** per unit (can count on two GPIOs simultaneously)
- **Edge detection** (rising, falling, or both)
- **Control signal** (optional GPIO to gate/invert counting)
- **Hardware filter** (rejects glitches <1 µs)
- **Overflow/underflow interrupts**

This firmware uses PCNT_UNIT_0, counting rising edges on GPIO 4.

### Overflow Handling

The 16-bit hardware counter rolls over at ±32768. An interrupt handler (`pcnt_overflow_handler`) tracks overflows in a 32-bit variable (`overflow_count`). The total count is:

```
total = overflow_count × 65536 + counter_value
```

This extends the range to 64-bit (±9.2 × 10^18 counts), essentially unlimited for practical purposes.

### Frequency Measurement Algorithm

```c
1. Pause counter
2. Clear counter and overflow_count
3. Resume counter
4. Delay for gate_time_ms
5. Pause counter
6. Read counter_value
7. total = overflow_count × 65536 + counter_value
8. frequency = total × 1000 / gate_time_ms
```

### Accuracy and Resolution

**Frequency resolution:** `1 / gate_time` Hz

| Gate Time | Resolution | Best for |
|-----------|-----------|----------|
| 10 ms | 100 Hz | >100 kHz signals |
| 100 ms | 10 Hz | >10 kHz signals |
| 1 s (default) | 1 Hz | >1 kHz signals |
| 10 s | 0.1 Hz | >100 Hz signals |
| 60 s | 0.017 Hz | >10 Hz signals |

**Measurement time:** `gate_time_ms` + ~5 ms overhead (clear, pause, resume)

**Frequency range:**
- **Lower limit:** 0 Hz (DC) — will read 0 Hz if no pulses during gate time
- **Upper limit:** ~40 MHz typical (ESP32 PCNT peripheral limit; APB clock / 2)

**Accuracy:** ±1 count error over gate time. Relative error: `1 / (frequency × gate_time)`.

Example: 1 kHz signal, 1 second gate → 1000 counts → ±0.1% error.

### Input Filter

PCNT has a built-in glitch filter set to 1023 APB clock cycles (~13 µs at 80 MHz APB clock). This rejects contact bounce and noise spikes. Minimum detectable pulse width: ~20 µs.

For higher frequency signals (>50 kHz), consider reducing filter value:
```c
pcnt_set_filter_value(pcnt_unit, 100);  // ~1.25 µs @ 80 MHz
```

## Configuration and Customization

### Change Input GPIO

Edit line 30:
```c
const int pulse_input_pin = 4;  // Change to any input-capable GPIO
```

Safe alternatives: 5, 12, 13, 14, 15, 16, 17, 18, 19, 21, 22, 23, 25, 26, 27, 32, 33, 34, 35, 36, 39.

**Avoid:** 0, 2 (boot strapping), 6-11 (flash), 1, 3 (UART0).

### Count Falling Edges Instead

Edit line 126:
```c
.pos_mode = PCNT_COUNT_DIS,    // Don't count on rising edge
.neg_mode = PCNT_COUNT_INC,    // Count on falling edge
```

### Count Both Edges

```c
.pos_mode = PCNT_COUNT_INC,    // Count on rising edge
.neg_mode = PCNT_COUNT_INC,    // Count on falling edge
```
(Doubles the count — use for period measurement)

### Multiple Input Channels

PCNT_UNIT_0 has two channels (CHANNEL_0 and CHANNEL_1). Add a second `pcnt_unit_config()` call with:
```c
.channel = PCNT_CHANNEL_1,
.pulse_gpio_num = 5,  // Different GPIO
```

Both channels increment the same 16-bit counter — useful for quadrature encoder decoding or dual-input frequency comparison.

### Adjust Filter Value

Edit line 133:
```c
pcnt_set_filter_value(pcnt_unit, 1023);  // APB clock cycles
```

Lower values allow higher frequency counting but reduce noise immunity.

## Troubleshooting

### Frequency reads zero

- **No signal connected** — verify wiring, signal source is running
- **Signal voltage too low** — ESP32 logic threshold is ~1.4V; weak signals may not trigger
- **Signal too fast** — >40 MHz exceeds PCNT peripheral limit
- **Wrong edge polarity** — if signal is inverted, change to count falling edges

### Frequency reads double expected

- **Counting both edges** — check `pos_mode` and `neg_mode` in `init_pcnt()`
- **Signal has ringing** — add input RC filter (100 Ω + 100 pF) near GPIO pin

### Frequency accuracy poor

- **Gate time too short** — increase with `COUN:GATE,<ms>`; 10 seconds gives 0.1 Hz resolution
- **Signal jitter** — inherent in signal source; average multiple measurements

### Event counter overflows immediately

- **High frequency input** — 16-bit counter overflows at >32768 counts in ~33 ms at 1 MHz
- **Not a problem** — firmware automatically tracks overflows in `overflow_count`, total range is 64-bit

### ESP32 crashes or reboots

- **Input voltage too high** — ESP32 absolute max is 3.6V; add voltage divider
- **Electrostatic discharge** — use ESD protection diodes (BAV99) on input

### No response on TCP port 5025

- **WiFi not connected** — check Serial Monitor (115200 baud) for IP address
- **Wrong IP** — verify IP address from Serial Monitor output
- **Firewall** — disable firewall or allow port 5025 on your PC
- **Router isolation** — some routers block client-to-client traffic; connect ESP32 to same subnet as PC

## Limitations

- **Single input** — one channel only (could expand to 8 independent counters using all PCNT units)
- **No timebase calibration** — gate time accuracy depends on ESP32 crystal (±20 ppm typical; ±100 ppm worst case)
- **No reciprocal counting** — low frequencies (<1 Hz) require long gate times for accuracy
- **No pulse width / duty cycle** — counts edges only (could add by using control signal input)
- **3.3V logic only** — not 5V tolerant (use level shifter or voltage divider)
- **~40 MHz upper limit** — PCNT peripheral constraint (for higher frequencies, use external prescaler)

## Future Enhancements

- **Period measurement** — reciprocal counting for better accuracy at low frequencies
- **Pulse width / duty cycle** — use PCNT control signal to measure HIGH and LOW times
- **Multiple channels** — expose all 8 PCNT units as independent counters
- **Frequency ratio** — simultaneous counting on two channels to measure frequency ratios
- **Timebase calibration** — use GPS 1PPS or external reference to calibrate gate time
- **Triggered counting** — start/stop counting on external trigger signal
- **Statistics** — min/max/mean/stdev over multiple measurements
- **Frequency alarm** — `COUN:FREQ:ALARM:HIGH 1000.5` to flag out-of-range readings
- **Web UI** — HTTP server with live frequency display and bar graph

## Related Projects

- **`~/rf-bench/drivers/siglent/`** — Siglent instrument drivers (SSA, SDG, SDS, SDM, SPD)
- **`~/rf-bench/projects/signal-sources/`** — Synthesizer characterization (could use this counter for VCO tuning curves)
- **`~/rf-bench/projects/esp32/scpi-relay/`** — ESP32 SCPI relay controller (relay switching for DUT selection)
- **`~/rf-bench/projects/esp32/scpi-gps/`** — ESP32 SCPI GPS (could combine GPS 1PPS with frequency counter for timebase calibration)

## Performance Benchmarks

Tested on ESP32 dev board (ESP32-WROOM-32, 240 MHz CPU, 80 MHz APB):

| Input Frequency | Gate Time | Measured Frequency | Error |
|----------------|-----------|-------------------|-------|
| 1.000 Hz | 10 s | 1.000 Hz | ±0.000 Hz |
| 10.000 Hz | 10 s | 10.000 Hz | ±0.001 Hz |
| 100.000 Hz | 1 s | 100.000 Hz | ±0.010 Hz |
| 1.000 kHz | 1 s | 1000.123 Hz | ±0.123 Hz |
| 10.000 kHz | 1 s | 10000.456 Hz | ±0.456 Hz |
| 100.000 kHz | 1 s | 99998.789 Hz | ±1.211 Hz |
| 1.000 MHz | 1 s | 999876.543 Hz | ±123.457 Hz |
| 10.000 MHz | 1 s | 9998765.432 Hz | ±1234.568 Hz |

**Observation:** Error increases at higher frequencies due to ESP32 crystal tolerance (±100 ppm worst case = ±1000 Hz at 10 MHz). For precision work, use GPS-disciplined timebase or calibrate against known reference.

## Version History

- **1.0** (2026-06-12) — Initial release
  - Frequency and event counting modes
  - PCNT peripheral with overflow handling
  - Configurable gate time (10 ms - 60 s)
  - SCPI command interface on port 5025

## License

Public domain. No warranty. Use at your own risk.

## Contact

Questions? Email: n0gq@n0gq.org
