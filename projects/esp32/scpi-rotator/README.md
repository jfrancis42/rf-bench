# ESP32 SCPI Antenna Rotator Controller

Network-controlled antenna rotator using Standard Commands for Programmable Instruments (SCPI) over TCP/IP. Controls azimuth and elevation servos with limit switch protection for safe antenna positioning.

## Features

- **SCPI over TCP/IP** on port 5025 (industry standard)
- **2-axis control** — Azimuth (0-360°) and Elevation (0-90°)
- **4 limit switches** — Prevents mechanical damage at travel limits
- **Smooth slewing** — Configurable speed (default 30°/sec)
- **Emergency stop** — Immediate halt of all motion
- **WiFi connectivity** with configurable credentials
- **Standard SCPI commands** compatible with test equipment automation
- **Position query** for verification and closed-loop control

## Hardware Requirements

- ESP32 development board (any variant with WiFi and PWM)
- 2× RC hobby servos (SG90, MG996R, or similar — preferably metal gear for durability)
- 4× limit switches (normally open — mechanical switches, microswitches, or magnetic reed switches)
- **External 5V power supply** (2-5A depending on servo load)
- Pull-down resistors (10kΩ) for limit switches (optional if ESP32 internal pull-downs are used)
- Jumper wires

### Recommended Servos

- **Azimuth:** MG996R or DS3218 (metal gear, high torque) — must support antenna weight and wind load
- **Elevation:** MG996R or similar — lighter load than azimuth in most designs

For small antennas (VHF/UHF handheld yagi), SG90 servos may suffice. For larger antennas (HF beam, satellite array), use industrial servo motors or modified continuous rotation servos with feedback.

**IMPORTANT:** Standard RC servos have 0-180° range. For full 360° azimuth rotation, you need:
- **Multi-turn servo** (e.g., 3-turn = 0-1080°), or
- **Continuous rotation servo** with absolute position feedback (encoder/potentiometer), or
- **Mechanical reduction** (gears/pulleys to map 180° servo → 360° antenna)

This firmware assumes 180° servo range maps to 360° azimuth via mechanical reduction.

## Wiring

### Servo Connections

| ESP32 GPIO | Function | Servo Signal Wire |
|------------|----------|-------------------|
| GPIO 25    | Azimuth  | Signal (yellow/white/orange) |
| GPIO 26    | Elevation | Signal (yellow/white/orange) |

### Limit Switch Connections

| ESP32 GPIO | Function | Switch Type |
|------------|----------|-------------|
| GPIO 32    | Azimuth CW limit | Normally open (closes at CW end of travel) |
| GPIO 33    | Azimuth CCW limit | Normally open (closes at CCW end of travel) |
| GPIO 35    | Elevation Up limit | Normally open (closes at maximum elevation) |
| GPIO 34    | Elevation Down limit | Normally open (closes at minimum elevation / horizon) |

**Limit switch wiring:**
```
ESP32 GPIO → One side of switch
Other side of switch → +3.3V
ESP32 internal pull-down resistor pulls GPIO LOW when switch is open
When switch closes, GPIO reads HIGH
```

Alternatively, use external 10kΩ pull-down resistors:
```
Switch between GPIO and +3.3V
10kΩ resistor between GPIO and GND
```

### Power Wiring

**CRITICAL:** Servos draw significant current (each servo can draw 200-800mA under load, up to 1.5A stall). **DO NOT power servos from the ESP32's 5V pin** — this will damage the ESP32 or cause brownouts/reboots.

**Correct wiring:**
```
External 5V PSU (+) ──→ Servo VCC (red wire, both servos)
External 5V PSU (−) ──→ Common GND
ESP32 GND          ──→ Common GND (shared with PSU and servos)
```

All grounds must be connected together (ESP32 GND, power supply GND, servo GND).

**Power supply sizing:**
- Azimuth + Elevation servos (MG996R): 5V 3A minimum, 5V 5A recommended
- Add 1000-2200 µF bulk capacitor across PSU +/− terminals near servos to handle current spikes

## Calibration

The firmware assumes a linear mapping from servo angles to antenna angles:

### Azimuth Calibration
```
Servo 0° → Antenna 0° (North)
Servo 90° → Antenna 180° (South)
Servo 180° → Antenna 360° (North again)
```

**Mechanical reduction required** for full 360° rotation. For example:
- 2:1 gear reduction: 180° servo → 360° antenna
- 4:1 gear reduction: 45° servo → 180° antenna (useful for small antennas)

### Elevation Calibration
```
Servo 0° → Antenna 0° (Horizon)
Servo 90° → Antenna 45° (mid-sky)
Servo 180° → Antenna 90° (Zenith)
```

Most antennas don't need full 0-90° elevation. For satellite tracking, 0-45° may be sufficient (satellites are rarely overhead).

### Adjusting Calibration Constants

Edit the firmware constants if your mechanical installation differs:
```cpp
const float az_servo_min = 0.0;      // Servo angle for 0° azimuth
const float az_servo_max = 180.0;    // Servo angle for 360° azimuth
const float el_servo_min = 0.0;      // Servo angle for 0° elevation
const float el_servo_max = 180.0;    // Servo angle for 90° elevation
```

For example, if your elevation servo only travels 0-90° (due to mechanical limits):
```cpp
const float el_servo_max = 90.0;     // Servo 90° = Antenna 90° (zenith)
```

## Limit Switch Placement

Limit switches prevent the antenna from hitting mechanical stops or obstructions.

### Azimuth Limits
- **CW limit (GPIO 32):** Closes when antenna reaches maximum clockwise rotation
- **CCW limit (GPIO 33):** Closes when antenna reaches maximum counter-clockwise rotation

For a rotator with 360° mechanical rotation but limited by cables/counterweights, place limits at ~350° and ~10° to leave a safe gap.

For a rotator with mechanical stops at 270° CW / 90° CCW, place limits accordingly.

### Elevation Limits
- **Up limit (GPIO 35):** Closes when antenna reaches maximum elevation (typically 80-90°)
- **Down limit (GPIO 34):** Closes when antenna reaches minimum elevation (typically 0-5° above horizon)

**Limit switch logic:**
- When a limit switch activates (reads HIGH), motion in that direction is **blocked**
- Motion in the opposite direction is still allowed
- Firmware polls limit switches during slewing and stops immediately if a limit is hit

**Example:** If azimuth CW limit activates while moving clockwise, the antenna stops. You can still move counter-clockwise to clear the limit.

## Software Setup

1. **Install Arduino IDE** with ESP32 board support
   - File → Preferences → Additional Board Manager URLs: `https://dl.espressif.com/dl/package_esp32_index.json`
   - Tools → Board → Boards Manager → Search "ESP32" → Install

2. **Install ESP32Servo library**
   - Tools → Manage Libraries → Search "ESP32Servo" by Kevin Harrington → Install

3. **Configure WiFi credentials**
   - Edit `scpi-rotator.ino`
   - Change `ssid` and `password` near the top of the file

4. **Upload to ESP32**
   - Tools → Board → ESP32 Dev Module (or your specific board)
   - Tools → Port → (select your ESP32's serial port)
   - Click Upload

5. **Find the IP address**
   - Open Serial Monitor (115200 baud)
   - Reset the ESP32
   - Note the IP address printed (e.g., `192.168.1.42`)

6. **Connect servos, limit switches, and power**
   - Wire servos to GPIOs as shown above
   - Wire limit switches to GPIOs with pull-downs
   - Connect external 5V power supply
   - **Ensure all grounds are connected together**

7. **Verify limit switches**
   - Manually press each limit switch and verify Serial Monitor shows activation
   - Test motion stops when limit is reached

## SCPI Command Reference

Connect to the ESP32 on port 5025 using any TCP client (`telnet`, `nc`, or Python `socket`).

### Identification

```
*IDN?
```
Returns device identification string: `N0GQ,ESP32-SCPI-Rotator,1.0,2026`

### Reset / Home

```
*RST
ROT:HOME
```
Moves antenna to home position (0° azimuth, 0° elevation). Clears emergency stop flag.

### Set Azimuth

```
ROT:AZ,<degrees>
```
Sets azimuth angle (0-360°). Motion respects limit switches.

**Examples:**
```
ROT:AZ,0          # North
ROT:AZ,90         # East
ROT:AZ,180        # South
ROT:AZ,270        # West
ROT:AZ,45.5       # Northeast (fractional degrees supported)
```

### Query Azimuth

```
ROT:AZ?
```
Returns current azimuth angle (0-360°).

### Set Elevation

```
ROT:EL,<degrees>
```
Sets elevation angle (0-90°). Motion respects limit switches.

**Examples:**
```
ROT:EL,0          # Horizon
ROT:EL,45         # 45° above horizon
ROT:EL,90         # Zenith (straight up)
```

### Query Elevation

```
ROT:EL?
```
Returns current elevation angle (0-90°).

### Set Slew Speed

```
ROT:SPEED,<deg_per_sec>
```
Sets slewing speed (0.1-180.0 degrees per second). Default is 30°/sec.

**Examples:**
```
ROT:SPEED,10      # Slow (10°/sec)
ROT:SPEED,30      # Default
ROT:SPEED,90      # Fast (90°/sec) — may skip if servo can't keep up
```

Higher speeds may cause the servo to lag behind or vibrate. Adjust based on servo speed and mechanical load.

### Query Slew Speed

```
ROT:SPEED?
```
Returns current slew speed in degrees per second.

### Emergency Stop

```
ROT:STOP
```
Immediately halts all motion. Sets emergency stop flag. Antenna remains at current position. Clear by sending `ROT:HOME` or `*RST`.

### Query Limit Switches

```
ROT:LIM:AZ?       # Query azimuth limits (bit 0=CW, bit 1=CCW)
ROT:LIM:EL?       # Query elevation limits (bit 0=Up, bit 1=Down)
```

Returns integer where each bit represents a limit switch:
- **ROT:LIM:AZ?** → `0` (no limits), `1` (CW limit), `2` (CCW limit), `3` (both limits — should not happen)
- **ROT:LIM:EL?** → `0` (no limits), `1` (Up limit), `2` (Down limit), `3` (both limits — should not happen)

**Example:**
```
ROT:LIM:AZ?
1                 # Azimuth CW limit is active
```

### System Error Query

```
SYST:ERR?
```
Returns `0,"No error"` (always, for this simple device).

### Command Format Notes

- Commands can be uppercase or lowercase (case-insensitive)
- Short form allowed: `ROT:AZ` = `ROTAT:AZIMUTH`
- Commands can be terminated with newline (`\n`), carriage return (`\r`), or semicolon (`;`)
- Multiple commands can be sent in one line separated by semicolons: `ROT:AZ,180;ROT:EL,45`

## Usage Examples

### Telnet (interactive)

```bash
telnet 192.168.1.42 5025
*IDN?
ROT:HOME
ROT:AZ,90
ROT:EL,45
ROT:AZ?
ROT:EL?
ROT:STOP
```

### Netcat (command-line)

```bash
echo "ROT:AZ,180" | nc 192.168.1.42 5025
echo "ROT:EL,30" | nc 192.168.1.42 5025
echo "ROT:HOME" | nc 192.168.1.42 5025
```

### Python

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

# Home the antenna
scpi_command('192.168.1.42', 5025, 'ROT:HOME')
time.sleep(5)  # Wait for motion to complete

# Point to Northeast at 30° elevation
scpi_command('192.168.1.42', 5025, 'ROT:AZ,45')
scpi_command('192.168.1.42', 5025, 'ROT:EL,30')
time.sleep(3)

# Query current position
az = float(scpi_command('192.168.1.42', 5025, 'ROT:AZ?'))
el = float(scpi_command('192.168.1.42', 5025, 'ROT:EL?'))
print(f"Current position: Az={az}° El={el}°")

# Check limit switches
az_limits = int(scpi_command('192.168.1.42', 5025, 'ROT:LIM:AZ?'))
el_limits = int(scpi_command('192.168.1.42', 5025, 'ROT:LIM:EL?'))
print(f"Limits: Az=0x{az_limits:x} El=0x{el_limits:x}")
```

### Python with pyvisa (instrument automation)

```python
import pyvisa
import time

rm = pyvisa.ResourceManager('@py')
rotator = rm.open_resource('TCPIP::192.168.1.42::5025::SOCKET',
                           read_termination='\n',
                           write_termination='\n')

print(rotator.query('*IDN?'))

# Home
rotator.write('ROT:HOME')
time.sleep(5)

# Set position
rotator.write('ROT:AZ,90')
rotator.write('ROT:EL,30')
time.sleep(3)

# Query position
az = float(rotator.query('ROT:AZ?'))
el = float(rotator.query('ROT:EL?'))
print(f"Position: Az={az}° El={el}°")

rotator.close()
```

### Satellite Tracking Example

```python
import socket
import time
import math

def set_rotator(ip, port, az, el):
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.connect((ip, port))
        s.sendall(f'ROT:AZ,{az:.1f};ROT:EL,{el:.1f}\n'.encode())

# Simulate satellite pass (circular arc from horizon to horizon)
rotator_ip = '192.168.1.42'
rotator_port = 5025

# Home position
set_rotator(rotator_ip, rotator_port, 0, 0)
time.sleep(5)

# Track satellite (simplified — real satellite tracking needs TLE propagation)
for t in range(0, 180, 5):  # 0 to 180 seconds, update every 5 sec
    # Simulate satellite moving from East to West
    az = 90 - (t / 180.0) * 180.0  # 90° (East) to 270° (West)
    if az < 0:
        az += 360
    
    # Simulate satellite rising and falling (parabolic elevation)
    el = 45 * math.sin(math.radians(t))  # Peak at 90 sec, 45° elevation
    if el < 0:
        el = 0
    
    set_rotator(rotator_ip, rotator_port, az, el)
    print(f"t={t}s  Az={az:.1f}°  El={el:.1f}°")
    time.sleep(5)

# Return to home
set_rotator(rotator_ip, rotator_port, 0, 0)
```

For real satellite tracking, integrate with:
- **Skyfield** (Python TLE propagation library)
- **PyEphem** (older but still works)
- **Gpredict** (can export antenna control protocol)

## Use Cases

### Antenna Pattern Measurement

Rotate antenna through azimuth and elevation while measuring gain with spectrum analyzer or power meter. Generates antenna radiation pattern plots.

**Integration with rf-bench:**
```python
# ~/rf-bench/projects/rf/antenna-pattern/pattern_3d.py
from rf_bench.siglent import SSA3000X
import socket

ssa = SSA3000X('10.1.1.60')
rotator = socket.socket()
rotator.connect(('192.168.1.42', 5025))

results = []
for el in range(0, 91, 5):  # 0-90° elevation, 5° steps
    for az in range(0, 360, 10):  # 0-360° azimuth, 10° steps
        rotator.sendall(f'ROT:AZ,{az};ROT:EL,{el}\n'.encode())
        time.sleep(2)  # Wait for motion + settling
        power = ssa.get_marker_amplitude(1)  # Read peak power
        results.append((az, el, power))
        print(f"Az={az}° El={el}° Power={power:.1f} dBm")

# Plot 3D radiation pattern (not shown here)
```

### Satellite Tracking

Point antenna at moving satellites (ISS, weather satellites, ham radio satellites) based on real-time TLE propagation.

### EMI Source Location

Slowly sweep azimuth and elevation while monitoring RFI with spectrum analyzer. Peak signal indicates direction of interference source.

### Antenna Comparison

Test multiple antennas at the same physical orientations to compare gain, beamwidth, and pattern shape.

### Radio Astronomy

Track celestial radio sources (Sun, Jupiter, Cassiopeia A, etc.) as they move across the sky.

## Safety and Mechanical Considerations

- **Servo torque:** MG996R servos exert 11 kg·cm torque — enough to damage antennas, cables, or pinch fingers. Larger servos (DS3218 at 20 kg·cm) can cause serious injury.
- **Limit switches are critical** — without them, the antenna can hit mechanical stops and strip servo gears or bend the mounting hardware.
- **Wind load:** Antennas catch wind. In high winds (>20 mph), retract to home position or use heavier-duty servos with brakes.
- **Cable management:** Azimuth rotation can twist coax cables. Use a slip ring or limit azimuth to <360° with cable service loop.
- **Counterweights:** Large antennas on elevation axis need counterweights to balance the load — otherwise the servo fights gravity constantly and overheats.
- **Weatherproofing:** Servos and limit switches must be weatherproofed for outdoor use (sealed enclosures, conformal coating, grease on mechanical parts).

### Servo Upgrades for Larger Antennas

Standard RC servos (SG90, MG996R) are suitable for:
- VHF/UHF handheld yagi (small, lightweight)
- Small satellite antennas (dual-band eggbeater, turnstile)
- Indoor test setups with foam/cardboard antennas

For larger antennas, consider:
- **Industrial servo motors** with encoders (Dynamixel, Herkulex)
- **Stepper motors** with gearboxes (more torque, absolute positioning)
- **Continuous rotation servos** with external potentiometer feedback
- **DC gear motors** with H-bridge and rotary encoder
- **Commercial antenna rotators** (Yaesu G-5500, Alfa SPID) with SCPI interface adapter

## Debugging

- **Serial Monitor (115200 baud)** shows WiFi connection status, IP address, servo commands, and limit switch activations
- **Connection refused:** Check IP address, port number (5025), and firewall settings
- **Servos don't move:**
  - Check signal wire connections (ESP32 GPIO → servo signal wire)
  - Check power: servo VCC to external 5V, GND to common ground
  - Verify ESP32 GND is connected to power supply GND
  - Check emergency stop flag (send `ROT:HOME` to clear)
- **Servos jitter/twitch:** Insufficient power supply or poor ground connection
- **ESP32 reboots when servos move:** Servos drawing too much current from ESP32 pin — use external 5V power supply
- **Servo moves to wrong angle:**
  - Calibration constants may need adjustment (`az_servo_min/max`, `el_servo_min/max`)
  - Mechanical linkage may have slop or backlash
  - Servo may have non-standard pulse range (adjust `servo_min_us` and `servo_max_us`)
- **Limit switch doesn't stop motion:**
  - Verify switch wiring (normally open, closes to +3.3V)
  - Check pull-down resistor (internal or external 10kΩ)
  - Verify switch activation with Serial Monitor (should print "limit reached")
- **Antenna drifts after commanded position:**
  - Servo holding torque insufficient for load (upgrade to higher-torque servo)
  - Vibration or wind load
  - Servo gear slop or mechanical backlash

## Integration with Test Systems

This SCPI rotator controller integrates with:

- **LabVIEW** via VISA driver (use TCPIP SOCKET resource)
- **MATLAB** via `tcpip` or Instrument Control Toolbox
- **Python** via `pyvisa`, `socket`, or `PySerial`
- **Keysight VEE, TestStand, etc.** via standard SCPI/VISA interface
- **Gpredict** (satellite tracking software) — can be adapted to send SCPI commands instead of Hamlib rotctld

The standard SCPI command set and ROTATOR subsystem make this compatible with automated test equipment (ATE) frameworks.

## Firmware Customization

### Adding Absolute Position Feedback

Standard RC servos don't have position feedback. To add closed-loop control:
- Use **multi-turn potentiometers** on azimuth/elevation axes
- Read analog voltage on ESP32 ADC pins
- Compare commanded position to actual position
- Adjust servo angle to correct errors

### Adding Satellite Tracking

Integrate with TLE propagation libraries:
```python
from skyfield.api import load, wgs84
import time

# Load TLE data
stations_url = 'https://celestrak.org/NORAD/elements/gp.php?GROUP=amateur&FORMAT=tle'
satellites = load.tle_file(stations_url)
by_name = {sat.name: sat for sat in satellites}
satellite = by_name['ISS (ZARYA)']

# Observer location (example: Boulder, CO)
observer = wgs84.latlon(40.0, -105.0, elevation_m=1650)

# Propagate and track
ts = load.timescale()
while True:
    t = ts.now()
    geocentric = satellite.at(t)
    topocentric = (geocentric - observer.at(t)).altaz()
    
    az = topocentric[1].degrees  # Azimuth
    el = topocentric[0].degrees  # Elevation (altitude)
    
    if el > 0:  # Satellite is above horizon
        scpi_command('192.168.1.42', 5025, f'ROT:AZ,{az:.1f};ROT:EL,{el:.1f}')
    
    time.sleep(5)  # Update every 5 seconds
```

### Adding Rotctld Compatibility

Hamlib's `rotctld` uses a different protocol. To make this controller compatible with Hamlib-based software:
- Implement the `rotctld` ASCII protocol alongside SCPI
- Listen on port 4533 (standard `rotctld` port)
- Commands: `p` (get position), `P <az> <el>` (set position), `S` (stop), `_` (get info)

Example rotctld command translation:
```
rotctld: P 90.0 30.0
SCPI:    ROT:AZ,90.0;ROT:EL,30.0
```

## Known Limitations

- **No authentication** — any device on the network can control the rotator. Add IP whitelist or token auth if deploying on untrusted networks.
- **Single client** — one TCP connection at a time. Additional clients are rejected until the first disconnects.
- **No position feedback** — firmware tracks commanded position, not actual position. If the antenna jams, firmware doesn't know. (Standard RC servos don't have encoders; some high-end servos do but require different protocol.)
- **180° servo range limits azimuth** — for full 360° rotation, use mechanical reduction or multi-turn servos.
- **Blocking motion** — servo slewing blocks command processing. Client waits for "OK" response. (Could implement async motion with status query in future.)
- **No wind speed compensation** — strong winds can overpower servos. Add wind sensor and auto-park at high speeds.
- **No EEPROM persistence** — rotator resets to home (0°, 0°) on reboot. (Could add NVS storage for power-on positions.)

## Future Enhancements

- **Rotctld protocol** — compatibility with Hamlib-based satellite tracking software
- **Absolute position feedback** — closed-loop control with potentiometers or encoders
- **Wind sensor integration** — auto-park in high winds
- **Web UI** — HTTP server with sliders and joystick control
- **TLE-based satellite tracking** — onboard propagation without PC
- **Multi-client support** — WebSocket broadcast to multiple monitoring clients
- **Logging** — record all commanded positions and limit switch events to SD card
- **Auto-calibration** — slowly move until limit switches activate, then measure range
- **Coordinated motion** — simultaneous azimuth+elevation slew instead of sequential

## Related Projects

- **`~/ota/`** — SOTA/POTA app with Hamlib — similar multi-interface (GUI/TUI/daemon) design
- **`~/govt-data/`** — REST API reference for structuring networked embedded services
- **`~/rf-bench/projects/relay/`** — XL9535 relay controller — similar GPIO control pattern
- **`~/scpi-servo/`** — Servo controller sibling project (4 independent servos, no limit switches)
- **`~/scpi-gps/`** — GPS receiver sibling project (serial input instead of output)
- **`~/vestigare/`** — Aircraft tracking — similar antenna pointing problem (ADS-B antenna could benefit from rotator for directional gain)

## License

Public domain. Use freely.

## Author

N0GQ — 2026-06-12
