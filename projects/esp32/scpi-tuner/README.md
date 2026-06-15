# SCPI Antenna Tuner Controller

ESP32-based network-controlled antenna tuner with optional SWR feedback and EEPROM memory slots.

## Hardware

### Required
- ESP32 dev board
- 2× stepper motors (or relay-switched L/C networks)
- 2× A4988 or DRV8825 stepper drivers (if using steppers)
- External 12V/24V power supply for motors

### Optional (for auto-tune)
- Forward power detector → GPIO 36
- Reflected power detector → GPIO 39
- (AD8307 logarithmic detectors or simple diode detectors)

## Wiring

### Inductor Control
```
ESP32 GPIO 25 → Driver STEP
ESP32 GPIO 26 → Driver DIR
Driver VMOT   → External 12V/24V supply +
Driver GND    → ESP32 GND + External supply −
Driver outputs → Inductor stepper motor
```

### Capacitor Control
```
ESP32 GPIO 27 → Driver STEP
ESP32 GPIO 14 → Driver DIR
Driver VMOT   → External 12V/24V supply +
Driver GND    → ESP32 GND + External supply −
Driver outputs → Capacitor stepper motor
```

### SWR Sensor (Optional)
```
Forward power detector output  → GPIO 36 (ADC1_CH0)
Reflected power detector output → GPIO 39 (ADC1_CH3)
Detectors should output 0-3.3V (or use voltage divider)
```

## SCPI Commands

### Common Commands
```
*IDN?              - Identification query
*RST               - Reset (home both to position 0)
SYST:ERR?          - System error query
```

### Tuner Control
```
TUN:IND,<pos>      - Set inductor position (0-255)
TUN:IND?           - Query inductor position
TUN:CAP,<pos>      - Set capacitor position (0-255)
TUN:CAP?           - Query capacitor position
TUN:AUTO           - Auto-tune via grid search (requires SWR sensor)
TUN:SWR?           - Query current SWR (requires SWR sensor)
TUN:STAT?          - Query status (MOVING or STOPPED)
```

### Memory Slots
```
TUN:SAVE,<slot>    - Save current position to EEPROM slot (0-9)
TUN:RECA,<slot>    - Recall position from EEPROM slot (0-9)
```

### Raw ADC Access
```
ADC:FWD?           - Query raw forward power ADC (0-4095)
ADC:REF?           - Query raw reflected power ADC (0-4095)
```

## Usage Examples

### Manual Tuning
```python
import socket

def scpi_cmd(ip, port, cmd):
    s = socket.socket()
    s.connect((ip, port))
    s.sendall((cmd + '\n').encode())
    if '?' in cmd:
        resp = s.recv(1024).decode().strip()
        s.close()
        return resp
    s.close()

# Set inductor to 128, capacitor to 64
scpi_cmd('192.168.1.42', 5025, 'TUN:IND,128')
scpi_cmd('192.168.1.42', 5025, 'TUN:CAP,64')

# Wait for motion to complete
while scpi_cmd('192.168.1.42', 5025, 'TUN:STAT?') == 'MOVING':
    time.sleep(0.1)

# Check SWR
swr = float(scpi_cmd('192.168.1.42', 5025, 'TUN:SWR?'))
print(f"SWR: {swr:.2f}")

# Save to slot 0
scpi_cmd('192.168.1.42', 5025, 'TUN:SAVE,0')
```

### Auto-Tune
```python
# Auto-tune to find best match
scpi_cmd('192.168.1.42', 5025, 'TUN:AUTO')
# This will take 30-60 seconds to complete

# Query final positions
l_pos = int(scpi_cmd('192.168.1.42', 5025, 'TUN:IND?'))
c_pos = int(scpi_cmd('192.168.1.42', 5025, 'TUN:CAP?'))
swr = float(scpi_cmd('192.168.1.42', 5025, 'TUN:SWR?'))
print(f"Tuned: L={l_pos}, C={c_pos}, SWR={swr:.2f}")

# Save to memory slot
scpi_cmd('192.168.1.42', 5025, 'TUN:SAVE,0')
```

### Band Presets
```python
# Save 40m preset to slot 0
scpi_cmd('192.168.1.42', 5025, 'TUN:IND,200')
scpi_cmd('192.168.1.42', 5025, 'TUN:CAP,100')
scpi_cmd('192.168.1.42', 5025, 'TUN:SAVE,0')

# Save 20m preset to slot 1
scpi_cmd('192.168.1.42', 5025, 'TUN:IND,120')
scpi_cmd('192.168.1.42', 5025, 'TUN:CAP,80')
scpi_cmd('192.168.1.42', 5025, 'TUN:SAVE,1')

# Later: recall 40m preset
scpi_cmd('192.168.1.42', 5025, 'TUN:RECA,0')
```

## Auto-Tune Algorithm

The `TUN:AUTO` command performs a two-stage grid search:

1. **Coarse search:** 16×16 grid (256 points) with step size 16
   - Finds approximate best match
   - Early exit if SWR < 1.1

2. **Fine search:** 2-step increments around coarse best
   - Refines to optimal position
   - Covers ±16 positions around coarse best

**Typical timing:**
- Coarse search: 256 points × 50ms settle time = ~13 seconds
- Fine search: ~289 points × 50ms = ~14 seconds
- **Total: 25-30 seconds** for full auto-tune

**Optimization:** If coarse search finds SWR < 1.1, fine search skips directly to that region.

## SWR Sensor Details

The firmware expects **0-3.3V** analog voltages on GPIO 36 (FWD) and GPIO 39 (REF) proportional to RF power.

### Simple Diode Detector
```
RF IN → Schottky diode (1N5711, BAT46) → 10nF → GPIO 36/39
                                          ↓
                                        100kΩ
                                          ↓
                                         GND
```

- **Pros:** Simple, low cost
- **Cons:** Nonlinear (square-law region below ~-10dBm), temperature-sensitive
- **Calibration:** Required at multiple power levels for accuracy

### Logarithmic Detector (AD8307)
```
RF IN → AD8307 → Voltage divider (if needed) → GPIO 36/39
```

- **Pros:** 92dB dynamic range (-75dBm to +17dBm), linear dB output, accurate
- **Cons:** More expensive (~$5), requires 5V supply and level-shift to 3.3V
- **Calibration:** Optional (output is ~25mV/dB)

### No Sensor Mode
If no SWR sensor is connected:
- Manual position control works normally
- `TUN:AUTO` returns `ERROR: No SWR sensor detected`
- `TUN:SWR?` returns `ERROR: No SWR sensor`
- Use external SWR meter and adjust positions manually

## EEPROM Memory

- **10 slots** (0-9) for position presets
- Each slot stores: inductor position + capacitor position
- Survives power cycles (stored in ESP32 NVS flash)
- Last position automatically saved/restored on reboot

## Position Range

- **0-255** for both inductor and capacitor
- Actual component values depend on mechanical design:
  - Stepper rotation angle per step
  - Gear ratios
  - Inductor taps or capacitor rotor travel

**Example:** NEMA 17 stepper at 1/8 microstepping:
- 200 steps/rev × 8 = 1600 steps/rev
- 255 steps = 57° rotation
- May need gearing for full component travel

## Timing Parameters

- **Step delay:** 2ms between steps = 500 steps/sec
- **Settle time:** 50ms after move before SWR reading
- **Non-blocking motion:** Commands accepted while motors moving

## Integration with rf-bench

Could be added as `~/rf-bench/drivers/tuner/` for automated antenna sweeps:

```python
from rf_bench.tuner import ESP32Tuner
from rf_bench.siglent import SSA3000X

tuner = ESP32Tuner('192.168.1.42')
ssa = SSA3000X('10.1.1.60')

# Sweep inductor, measure return loss at each position
results = []
for l_pos in range(0, 256, 8):
    tuner.set_inductor(l_pos)
    tuner.wait_for_stop()
    rl = ssa.read_marker_return_loss()
    results.append((l_pos, rl))
```

## Troubleshooting

### Motors don't move
- Check external 12V/24V supply connected and powered
- Verify ESP32 GND connected to motor supply GND
- Check GPIO wiring (STEP/DIR pins)
- Use Serial Monitor to see position updates

### Auto-tune fails
- Verify SWR sensor connected to GPIO 36/39
- Check sensor output voltage (should be 0-3.3V, not 0V or 5V)
- Test raw ADC with `ADC:FWD?` and `ADC:REF?` commands
- Ensure transmitter is powered and radiating during auto-tune

### SWR readings incorrect
- Calibrate sensors at known power levels
- For diode detectors: requires multi-point calibration
- For AD8307: check voltage divider if output >3.3V

### Position doesn't save
- Check Serial Monitor for NVS errors
- ESP32 flash may be full (unlikely on dev boards)
- Reflash firmware to clear NVS

## Related Projects

- `~/rf-bench/projects/esp32/scpi-stepper/` — Generic 2-motor stepper controller (basis for this project)
- `~/rf-bench/projects/esp32/scpi-swr/` — Standalone SWR meter (basis for SWR code)
- `~/rf-bench/projects/rf/antenna-analyzer/` — Antenna impedance measurement (complements tuner)
- `~/rf-bench/projects/radio/transmitter-test/` — Harmonic measurement (verify tuner output)

## Future Enhancements

- **Multi-band memory:** Store 10 presets per band
- **Frequency input:** Auto-recall preset based on transceiver frequency (via CAT control)
- **Smart presets:** Interpolate between saved frequencies
- **Relay control mode:** Support relay-switched L/C networks instead of steppers
- **Power protection:** Shut down on excessive reflected power
- **Web UI:** HTML interface for manual control
- **Return loss:** Report RL in addition to SWR (needs calibrated sensors)
- **Match quality metric:** Integrate impedance vs frequency from antenna analyzer

## License

Same as rf-bench — GPL-3.0-or-later.

## Author

N0GQ, 2026
