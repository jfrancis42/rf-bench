# ESP32 SCPI Decade Box Controller

Binary-weighted relay controller for resistance, capacitance, or inductance decade boxes. Provides SCPI control over USB serial.

## Hardware

- ESP32 development board
- 10 relays (5V or 3.3V logic) connected to GPIOs: 25, 26, 27, 14, 32, 33, 23, 19, 18, 5
- Binary-weighted passive components (resistors, capacitors, or inductors)
- Power supply appropriate for relay coils

### Relay Assignments

| GPIO | Relay | Weight | R Decade | C Decade | L Decade |
|------|-------|--------|----------|----------|----------|
| 25   | 0     | 2^0    | 1Ω       | 1pF      | 1µH      |
| 26   | 1     | 2^1    | 10Ω      | 10pF     | 10µH     |
| 27   | 2     | 2^2    | 100Ω     | 100pF    | 100µH    |
| 14   | 3     | 2^3    | 1kΩ      | 1nF      | 1mH      |
| 32   | 4     | 2^4    | 10kΩ     | 10nF     | 10mH     |
| 33   | 5     | 2^5    | 100kΩ    | 100nF    | 100mH    |
| 23   | 6     | 2^6    | 1MΩ      | 1µF      | 1H       |
| 19   | 7     | 2^7    | 10MΩ     | 10µF     | 10H      |
| 18   | 8     | 2^8    | 100MΩ    | 100µF    | 100H     |
| 5    | 9     | 2^9    | 1GΩ      | 1mF      | 1kH      |

## Software

### Installation

1. Install Arduino IDE with ESP32 board support
2. Open `scpi-decade.ino`
3. Select board: ESP32 Dev Module
4. Select port: `/dev/ttyUSB0` (or appropriate)
5. Upload

### SCPI Commands

All commands sent over USB serial at 115200 baud, terminated with `\n`.

#### Identification & Reset

- `*IDN?` — Returns identification string: `N0GQ,ESP32-SCPI-DECADE,001,1.0`
- `*RST` — Reset to default state (all relays off, value = 0)

#### Decade Type

- `DEC:TYPE,<R|C|L>` — Set decade type (R=resistance, C=capacitance, L=inductance)
- `DEC:TYPE?` — Query current type (returns `R`, `C`, or `L`)

#### Value Control

- `DEC:VAL,<value>` — Set value in ohms (R), farads (C), or henries (L)
- `DEC:VAL?` — Query current value (returns scientific notation)

#### Range Queries

- `DEC:MIN?` — Query minimum value (base relay value)
- `DEC:MAX?` — Query maximum value (sum of all relays)
- `DEC:STEP?` — Query step resolution (smallest relay value)

### Usage Example

```bash
# Connect and test
screen /dev/ttyUSB0 115200

# Identify
*IDN?
# Response: N0GQ,ESP32-SCPI-DECADE,001,1.0

# Set resistance mode
DEC:TYPE,R
# Response: OK

# Query range
DEC:MIN?
# Response: 1.000000000000

DEC:MAX?
# Response: 1111111111.000000000000

# Set 4.7kΩ (achieves closest binary sum: 4.7k = 4k + 700 = ...)
DEC:VAL,4700
# Response: OK

# Query actual value
DEC:VAL?
# Response: 4700.000000000000

# Switch to capacitance mode
DEC:TYPE,C
# Response: OK

# Set 100pF
DEC:VAL,100e-12
# Response: OK
```

## Binary-Weighted Algorithm

The controller uses a greedy algorithm to find the best relay combination:

1. Start with the highest-value relay
2. If adding it doesn't exceed target, activate it
3. Move to next lower relay and repeat
4. Continue until all relays checked

This guarantees the closest achievable value given the binary-weighted constraints.

For non-exact values, the controller selects the largest combination that doesn't exceed the target.

## Python Control Library

```python
import serial
import time

class DecadeBox:
    def __init__(self, port='/dev/ttyUSB0', baudrate=115200):
        self.ser = serial.Serial(port, baudrate, timeout=1)
        time.sleep(2)  # Wait for ESP32 reset
        self.ser.flushInput()

    def _send(self, cmd):
        self.ser.write(f"{cmd}\n".encode())
        return self.ser.readline().decode().strip()

    def identify(self):
        return self._send("*IDN?")

    def reset(self):
        return self._send("*RST")

    def set_type(self, dtype):
        """Set decade type: 'R', 'C', or 'L'"""
        return self._send(f"DEC:TYPE,{dtype}")

    def get_type(self):
        return self._send("DEC:TYPE?")

    def set_value(self, value):
        """Set value in ohms, farads, or henries"""
        return self._send(f"DEC:VAL,{value}")

    def get_value(self):
        return float(self._send("DEC:VAL?"))

    def get_min(self):
        return float(self._send("DEC:MIN?"))

    def get_max(self):
        return float(self._send("DEC:MAX?"))

    def get_step(self):
        return float(self._send("DEC:STEP?"))

# Usage
box = DecadeBox()
print(box.identify())

box.set_type('R')
box.set_value(4700)
print(f"Set to {box.get_value()} Ω")
```

## Applications

- Automated resistance/capacitance/inductance substitution testing
- Filter component sweeps
- RC time constant characterization
- Impedance matching experiments
- Calibration standard switching
- Remote programmable test loads

## Accuracy Considerations

- Actual component tolerance affects achievable accuracy (typically 1-5%)
- Relay contact resistance adds ~50-200mΩ per relay
- Parasitic capacitance/inductance in relays and wiring
- For precision work, use 0.1% or better tolerance components
- Consider temperature coefficient effects for high-accuracy applications

## Wiring Notes

- Use short, heavy gauge wire for low-resistance decades
- Star ground topology reduces ground loop errors
- Keep relay control wiring separate from measurement path
- Shield measurement terminals for low-capacitance/inductance decades
- Consider TinyRL or similar compensation for relay parasitic R

## Safety

- Ensure relay voltage/current ratings exceed application requirements
- Add flyback diodes across relay coils to protect ESP32 outputs
- Fuse the decade box output for overcurrent protection
- Do not exceed relay contact ratings (typically 0.5-2A at low voltage)
- High-value resistance decades can store charge — discharge before handling

## License

Public domain. Use as you wish.

## Author

N0GQ — 2026-06-12
