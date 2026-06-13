# SCPI PID Temperature Controller

ESP32-based closed-loop temperature controller with SCPI interface over TCP/IP.

Uses DS18B20 digital temperature sensor and SSR (Solid State Relay) for heater control. PID algorithm maintains target temperature with proportional PWM control.

## Features

- **DS18B20 1-Wire digital temperature sensor** (-55°C to +125°C, ±0.5°C accuracy)
- **PID control algorithm** with tunable Kp, Ki, Kd constants
- **SSR proportional control** via PWM output (0-100% duty cycle)
- **1 Hz update rate** for stable control
- **SCPI commands** over TCP/IP port 5025
- **Network accessible** via WiFi
- **Serial debugging** at 115200 baud

## Hardware Requirements

### Components

- ESP32 development board (any variant with WiFi)
- DS18B20 digital temperature sensor (TO-92 or waterproof probe)
- 4.7kΩ resistor (1/4W) for 1-Wire pull-up
- Solid State Relay (SSR) with 3.3V logic input (e.g., Fotek SSR-25DA, Omron G3MB-202P)
- Heater load (resistive heater, heating element, Peltier TEC, etc.)
- Breadboard or PCB for wiring
- USB cable for programming and power

### Wiring Diagram

```
DS18B20 Temperature Sensor:
  VCC (red)    -> 3.3V or 5V
  GND (black)  -> GND
  DATA (yellow) -> GPIO 4
                   |
               4.7kΩ pull-up resistor to VCC

SSR Heater Control:
  GPIO 25 -> SSR control input (+)
  GND     -> SSR control input (-)
  
  SSR output:
    Load +  -> 120/240VAC hot
    Load -  -> Heater element
    Heater element -> 120/240VAC neutral

WARNING: SSR output side carries mains voltage (120/240VAC).
Use proper insulation, enclosure, and safety practices.
```

### GPIO Pin Assignments

| GPIO | Function | Notes |
|------|----------|-------|
| 4    | DS18B20 DATA (1-Wire) | Requires 4.7kΩ pull-up to VCC |
| 25   | SSR control output (PWM) | 3.3V logic, 0-100% duty cycle |

## Software Setup

### Required Libraries

Install via Arduino IDE → Tools → Manage Libraries:

- **OneWire** by Paul Stoffregen (version 2.3.7+)
- **DallasTemperature** by Miles Burton (version 3.9.0+)

ESP32 board support via Arduino IDE → Tools → Board → Boards Manager → ESP32.

### Configuration

1. Open `scpi-heater.ino` in Arduino IDE
2. Edit WiFi credentials at top of file:
   ```cpp
   const char* ssid = "YourSSID";
   const char* password = "YourPassword";
   ```
3. (Optional) Adjust PID default constants:
   ```cpp
   float kp = 10.0;   // Proportional gain
   float ki = 0.5;    // Integral gain
   float kd = 1.0;    // Derivative gain
   ```
4. Connect ESP32 via USB
5. Select board: Tools → Board → ESP32 Dev Module
6. Select port: Tools → Port → (your USB serial port)
7. Click Upload

### First Boot

Open Serial Monitor (115200 baud) to see:

```
SCPI PID Temperature Controller
================================
SSR control on GPIO 25 (PWM channel 0)
Found 1 DS18B20 sensor(s) on GPIO 4
  Sensor: 28FF123456780190

Connecting to YourSSID.... connected!
IP address: 192.168.1.42
SCPI port: 5025
PID update rate: 1000 ms

Ready for SCPI commands
Initial temperature: 23.45°C
```

If sensor count is 0:
- Check wiring (DATA -> GPIO 4, VCC -> 3.3V/5V, GND -> GND)
- Verify 4.7kΩ pull-up resistor between DATA and VCC
- Test sensor with another device (Arduino, Raspberry Pi, etc.)

## SCPI Command Reference

Connect via telnet or raw TCP socket on port 5025.

### Common Commands

| Command | Description | Example Response |
|---------|-------------|------------------|
| `*IDN?` | Identification query | `N0GQ,ESP32-SCPI-Heater,1.0,2026` |
| `*RST` | Reset (disable control, reset PID) | `OK` |
| `SYST:ERR?` | System error query | `0,"No error"` |

### Temperature Control Commands

| Command | Description | Example | Response |
|---------|-------------|---------|----------|
| `HEAT:TEMP?` | Read current temperature (°C) | `HEAT:TEMP?` | `23.5625` |
| `HEAT:SETP,<degC>` | Set target temperature | `HEAT:SETP,50.0` | `OK` |
| `HEAT:SETP?` | Query setpoint | `HEAT:SETP?` | `50.0000` |
| `HEAT:OUT?` | Query heater output (0-100%) | `HEAT:OUT?` | `35.42` |
| `HEAT:PID,<P>,<I>,<D>` | Set PID constants | `HEAT:PID,10.0,0.5,1.0` | `OK` |
| `HEAT:PID?` | Query PID constants | `HEAT:PID?` | `10.0000,0.5000,1.0000` |
| `HEAT:EN,<0\|1>` | Enable/disable control | `HEAT:EN,1` | `OK` |
| `HEAT:EN?` | Query enabled state | `HEAT:EN?` | `1` (enabled) or `0` (disabled) |

### Command Notes

- Commands are **case-insensitive** (HEAT:TEMP? = heat:temp?)
- Terminate commands with `\n`, `\r`, or `;`
- Setpoint range: -55°C to +125°C (DS18B20 hardware limit)
- Heater output clamped to 0-100%
- PID constants can be any positive float (negative values allowed but not typical)
- Control disabled on boot — must explicitly enable via `HEAT:EN,1`

## Usage Examples

### Telnet Quick Test

```bash
telnet 192.168.1.42 5025

*IDN?
# N0GQ,ESP32-SCPI-Heater,1.0,2026

HEAT:TEMP?
# 23.5625

HEAT:SETP,50.0
# OK

HEAT:EN,1
# OK

HEAT:OUT?
# 45.32

HEAT:EN,0
# OK (disable control)
```

### Python Control Script

```python
import socket
import time

class HeaterController:
    def __init__(self, ip, port=5025):
        self.ip = ip
        self.port = port
        self.sock = None
    
    def connect(self):
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.sock.settimeout(3.0)
        self.sock.connect((self.ip, self.port))
    
    def send_command(self, cmd):
        self.sock.sendall((cmd + '\n').encode())
    
    def query(self, cmd):
        self.send_command(cmd)
        return self.sock.recv(1024).decode().strip()
    
    def close(self):
        if self.sock:
            self.sock.close()
    
    def get_temperature(self):
        return float(self.query('HEAT:TEMP?'))
    
    def set_setpoint(self, temp_c):
        self.send_command(f'HEAT:SETP,{temp_c}')
    
    def get_setpoint(self):
        return float(self.query('HEAT:SETP?'))
    
    def set_pid(self, kp, ki, kd):
        self.send_command(f'HEAT:PID,{kp},{ki},{kd}')
    
    def get_pid(self):
        resp = self.query('HEAT:PID?')
        kp, ki, kd = map(float, resp.split(','))
        return kp, ki, kd
    
    def enable_control(self):
        self.send_command('HEAT:EN,1')
    
    def disable_control(self):
        self.send_command('HEAT:EN,0')
    
    def is_enabled(self):
        return self.query('HEAT:EN?') == '1'
    
    def get_output(self):
        return float(self.query('HEAT:OUT?'))

# Example: Heat to 60°C and hold
heater = HeaterController('192.168.1.42')
heater.connect()

print(f"Initial temp: {heater.get_temperature():.2f}°C")

# Set target temperature
heater.set_setpoint(60.0)
print(f"Setpoint: {heater.get_setpoint():.2f}°C")

# Enable control
heater.enable_control()
print("Control enabled")

# Monitor for 5 minutes
for i in range(300):
    temp = heater.get_temperature()
    output = heater.get_output()
    print(f"T={temp:.2f}°C OUT={output:.1f}%")
    time.sleep(1)

# Disable control
heater.disable_control()
print("Control disabled")

heater.close()
```

### Step Response Test

```python
import socket
import time

def scpi_query(ip, cmd):
    s = socket.socket()
    s.settimeout(3.0)
    s.connect((ip, 5025))
    s.sendall((cmd + '\n').encode())
    if '?' in cmd:
        resp = s.recv(1024).decode().strip()
        s.close()
        return resp
    s.close()

def scpi_command(ip, cmd):
    s = socket.socket()
    s.settimeout(3.0)
    s.connect((ip, 5025))
    s.sendall((cmd + '\n').encode())
    s.close()

ip = '192.168.1.42'

# Configure PID
scpi_command(ip, 'HEAT:PID,10.0,0.5,1.0')

# Set initial setpoint
scpi_command(ip, 'HEAT:SETP,40.0')
scpi_command(ip, 'HEAT:EN,1')

print("Settling at 40°C for 60 seconds...")
time.sleep(60)

# Step to 60°C
print("Step to 60°C")
scpi_command(ip, 'HEAT:SETP,60.0')

# Record step response
print("Time(s),Temp(°C),Output(%)")
for i in range(300):  # 5 minutes
    temp = float(scpi_query(ip, 'HEAT:TEMP?'))
    output = float(scpi_query(ip, 'HEAT:OUT?'))
    print(f"{i},{temp:.4f},{output:.2f}")
    time.sleep(1)

# Disable control
scpi_command(ip, 'HEAT:EN,0')
```

## PID Tuning

Default values: `Kp=10.0`, `Ki=0.5`, `Kd=1.0`. These work for many systems but may need adjustment.

### Quick Tuning Procedure (Ziegler-Nichols)

1. Set `Ki=0` and `Kd=0` (proportional-only control):
   ```
   HEAT:PID,1.0,0.0,0.0
   ```
2. Set setpoint 10-20°C above ambient
3. Enable control: `HEAT:EN,1`
4. Gradually increase `Kp` until system oscillates steadily (constant amplitude)
5. Record ultimate gain `Ku` and oscillation period `Tu` (seconds)
6. Calculate PID constants:
   - `Kp = 0.6 * Ku`
   - `Ki = 2 * Kp / Tu`
   - `Kd = Kp * Tu / 8`
7. Set new constants: `HEAT:PID,<Kp>,<Ki>,<Kd>`
8. Test and fine-tune

### Manual Tuning Tips

- **Kp too high:** Large overshoot, oscillation
- **Kp too low:** Slow response, never reaches setpoint
- **Ki too high:** Overshoot, instability
- **Ki too low:** Steady-state error (doesn't reach setpoint)
- **Kd too high:** Noise amplification, instability
- **Kd too low:** Overshoot, slow settling

### System-Specific Considerations

- **Fast heater (< 10 seconds):** Increase `Kd`, decrease `Ki`
- **Slow heater (> 60 seconds):** Increase `Ki`, decrease `Kd`
- **High thermal mass:** Increase `Ki`, increase `Kd`
- **Low thermal mass:** Decrease `Ki`, decrease `Kd`

## Safety Features

### Built-in Safety

- **Sensor fault detection:** If DS18B20 returns error (-127.0°C), control automatically disables
- **Output clamping:** Heater output limited to 0-100% regardless of PID calculation
- **Integral anti-windup:** Prevents integral term from growing unbounded
- **Power-on safe state:** Control starts disabled, heater OFF

### External Safety (Highly Recommended)

- **Thermal fuse** on heater element (inline with mains power)
- **Independent over-temperature shutdown** (bimetallic thermostat, thermal fuse, or secondary controller)
- **SSR heatsink** if switching > 5A (SSR can overheat and fail shorted)
- **Proper enclosure** for mains voltage wiring (grounded metal box)
- **Fuse on mains input** (10A slow-blow for 1500W heater on 120VAC)

### Failure Modes

| Failure | Behavior | Mitigation |
|---------|----------|------------|
| DS18B20 disconnected | Control disables, heater OFF | Redundant sensor + failsafe relay |
| WiFi disconnect | Control continues with last setpoint | Watchdog timer + failsafe relay |
| ESP32 crash | Last PWM state persists | External watchdog + failsafe relay |
| SSR fails shorted | Heater stuck ON | Thermal fuse, over-temp shutdown |
| SSR fails open | Heater stuck OFF | None needed (safe failure) |

**Recommended failsafe:** Add external over-temperature relay (NC contact) in series with SSR output. If temperature exceeds safe limit, relay opens and cuts power to heater regardless of ESP32 state.

## Use Cases

### Laboratory Applications

- **Thermal chamber** — Maintain constant temperature for component characterization
- **PCB reflow oven** — Follow solder reflow temperature profile (with profile scripting)
- **Water bath** — Precision temperature control for chemistry experiments
- **Incubator** — Biological sample temperature stability

### RF/Electronics Applications

- **Crystal oven** — Stabilize oscillator frequency via temperature control
- **Amplifier tempco test** — Characterize gain vs temperature (with SSA3032X)
- **Thermal resistance measurement** — Heat DUT and measure junction-to-case ΔT
- **Thermal aging** — Accelerated life testing at elevated temperature

### Integration with rf-bench

Could be used in:
- **`~/rf-bench/projects/rf/amplifier-tempco/`** — Sweep temperature, measure gain/NF
- **`~/rf-bench/projects/components/thermal-aging/`** — Long-term drift testing
- **`~/rf-bench/projects/signal-sources/crystal-tempco/`** — Oscillator frequency vs temperature

## Performance Specifications

| Parameter | Value | Notes |
|-----------|-------|-------|
| Temperature sensor | DS18B20 | 1-Wire digital |
| Temperature range | -55°C to +125°C | Hardware limit |
| Temperature accuracy | ±0.5°C | -10°C to +85°C typical |
| Temperature resolution | 0.0625°C | 12-bit mode |
| Temperature conversion time | 750 ms | 12-bit blocking |
| PID update rate | 1 Hz | Once per second |
| Heater control | 0-100% | PWM duty cycle |
| PWM frequency | 1 Hz | Slow PWM for SSR |
| Control response time | System-dependent | Typically 30-300 seconds |
| Network protocol | SCPI over TCP/IP | Port 5025 |
| WiFi | 2.4 GHz 802.11 b/g/n | ESP32 built-in |

## Troubleshooting

### Sensor Issues

**Sensor not found (count = 0):**
- Check wiring: DATA -> GPIO 4, VCC -> 3.3V/5V, GND -> GND
- Verify 4.7kΩ pull-up resistor between DATA and VCC
- Test sensor with multimeter (VCC = 3.3V or 5V, GND = 0V)
- Try known-good DS18B20 (counterfeit sensors common)

**Temperature reads -127.0°C or 85.0°C:**
- -127.0°C = sensor not responding (wiring issue, bad sensor)
- 85.0°C = power-on default (sensor not initialized)
- Add 0.1µF decoupling capacitor across sensor VCC/GND
- Check for loose connections (wiggle wires)

**Temperature reads but control doesn't work:**
- Check if control enabled: `HEAT:EN?` should return `1`
- Verify setpoint > current temperature (for heating)
- Check heater output: `HEAT:OUT?` should be non-zero

### SSR Issues

**Heater doesn't turn on:**
- Measure voltage on GPIO 25 (should vary 0-3.3V with PWM)
- Check SSR control input polarity (+ to GPIO 25, - to GND)
- Verify SSR control voltage spec (should accept 3.3V logic)
- Test SSR with 5V source (some SSRs need > 3.3V)
- Check SSR output side wiring (mains voltage connections)

**Heater stuck on or off:**
- Reboot ESP32 (`*RST` or power cycle)
- Check if control disabled: `HEAT:EN,0` then `HEAT:EN,1`
- Verify SSR not failed (measure output voltage with control OFF)

### Control Issues

**Temperature oscillates around setpoint:**
- PID tuning needed — reduce `Kp`, reduce `Ki`, increase `Kd`
- Thermal lag in system (sensor not at heater location)
- Update rate too slow for system dynamics

**Temperature never reaches setpoint:**
- Heater too weak for thermal load
- Increase `Ki` (integral term)
- Check for heat leaks (insulation)
- Verify SSR actually switching (measure mains voltage at heater)

**Temperature overshoots and settles slowly:**
- Increase `Kd` (derivative term)
- Reduce `Kp` (proportional gain)
- System has high thermal mass

### Network Issues

**Can't connect to SCPI server:**
- Check ESP32 is on WiFi (Serial Monitor shows IP address)
- Ping IP address from client machine
- Check firewall (allow TCP port 5025)
- Verify WiFi credentials in firmware

**Connection drops frequently:**
- WiFi signal strength issue (move closer to AP)
- Check for WiFi channel interference
- Add reconnection logic in client code

## Limitations

- **Single sensor:** Supports one DS18B20 only (firmware can be extended for multiple)
- **Single TCP client:** One connection at a time (second client rejected)
- **Fixed GPIO pins:** DS18B20 on GPIO 4, SSR on GPIO 25 (hard-coded)
- **No temperature profiling:** Manual setpoint changes only (no ramp/soak profiles)
- **No data logging:** Temperatures not stored (client must log)
- **No web UI:** SCPI only (no HTTP dashboard)
- **No authentication:** Open network access (no password)

## Future Enhancements

- **Multiple sensors** — Support DS18B20 array for multi-zone control
- **Temperature profiling** — Upload time/temp profile for automated reflow, curing, etc.
- **Data logging** — Write temperatures to SD card or SPIFFS filesystem
- **Web dashboard** — HTTP server with live temperature graph (Chart.js)
- **MQTT publish** — Push temperatures to MQTT broker (Home Assistant, Node-RED)
- **Email/SMS alerts** — Notify on over-temperature, control failure
- **Relay failsafe output** — Dedicated GPIO for over-temp relay cutoff
- **PID autotuning** — Ziegler-Nichols algorithm run automatically
- **Fan control** — Add cooling output for bidirectional control (heating + cooling)

## Version History

**1.0** (2026-06-12)
- Initial release
- DS18B20 sensor support
- PID control with tunable constants
- SSR PWM output
- SCPI command interface
- 1 Hz update rate

## License

This project is in the public domain. No warranty provided. Use at your own risk, especially with mains voltage wiring.

## Related Projects

- **scpi-temp** — Read-only temperature monitor (no control loop)
- **scpi-relay** — GPIO relay controller (on/off control, no analog)
- **scpi-pwm** — Multi-channel PWM generator (no feedback loop)
- **scpi-servo** — RC servo controller (position control)
- **rf-bench/projects/power/** — PSU and thermal testing projects
