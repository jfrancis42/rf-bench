# Flipper Protocol Tester

Automated Sub-GHz TX/RX protocol testing combining scpi-relay + scpi-ptt + Flipper Zero.

## Hardware Setup

### Required Components

- **scpi-relay** — XL9535 I2C relay board with SCPI-over-TCP interface
  - Connects up to 4 DUT receivers (channels 1-4)
  - Each DUT's antenna/RF input connects via relay to common test point
- **scpi-ptt** — PTT controller for keying DUT transmitters
  - Controls DUT TX sequencing in reverse mode
- **Flipper Zero** — Sub-GHz transceiver
  - Transmits test vectors in forward mode
  - Receives DUT transmissions in reverse mode
  - Supports OOK, 2FSK, 4FSK modulations

### Wiring

```
Forward mode (Flipper TX → DUT RX):
  Flipper Sub-GHz → scpi-relay common → DUT1/DUT2/DUT3/DUT4 RX inputs

Reverse mode (DUT TX → Flipper RX):
  DUT1/DUT2/DUT3/DUT4 TX outputs → scpi-relay common → Flipper Sub-GHz
  scpi-ptt PTT outputs → DUT1/DUT2/DUT3/DUT4 PTT inputs
```

## Installation

```bash
pip install rf-bench-drivers-flipper
```

Also requires:
- `rf-bench-drivers-scpi-relay`
- `rf-bench-drivers-scpi-ptt`

## Use Cases

- **433 MHz remote testing** — Garage door openers, wireless doorbells, remote switches
- **315 MHz key fobs** — Car remotes, alarm systems
- **868/915 MHz ISM** — LoRa, FSK telemetry devices
- **TPMS sensors** — Tire pressure monitoring system protocols
- **Compliance testing** — Multi-DUT protocol conformance validation

## Test Vector CSV Format

```csv
protocol,frequency_mhz,data_rate,payload,expected_decode,description
OOK,433.92,4800,AABBCCDD,AABBCCDD,Simple OOK test
OOK,433.92,4800,11223344,11223344,Garage door code
2FSK,315.0,9600,DEADBEEF,DEADBEEF,Key fob test
4FSK,868.3,19200,CAFEBABE,CAFEBABE,ISM telemetry
```

### Fields

- **protocol** — `OOK`, `2FSK`, `4FSK`
- **frequency_mhz** — Carrier frequency in MHz
- **data_rate** — Data rate in baud
- **payload** — Hex string to transmit
- **expected_decode** — Expected hex string after decode
- **description** — Human-readable test name (optional)

## Examples

### Forward Test: 433 MHz OOK, 4 Receivers

Test vectors file `ook_433.csv`:

```csv
protocol,frequency_mhz,data_rate,payload,expected_decode,description
OOK,433.92,4800,AABBCCDD,AABBCCDD,Test pattern 1
OOK,433.92,4800,11223344,11223344,Test pattern 2
OOK,433.92,4800,DEADBEEF,DEADBEEF,Test pattern 3
OOK,433.92,4800,CAFEBABE,CAFEBABE,Test pattern 4
OOK,433.92,4800,12345678,12345678,Test pattern 5
OOK,433.92,9600,AABBCCDD,AABBCCDD,Higher data rate
OOK,433.92,2400,AABBCCDD,AABBCCDD,Lower data rate
OOK,433.92,4800,00000000,00000000,All zeros
OOK,433.92,4800,FFFFFFFF,FFFFFFFF,All ones
OOK,433.92,4800,55AA55AA,55AA55AA,Alternating pattern
```

Run test:

```bash
./protocol_test.py \
  --esp-relay 10.1.0.40 \
  --esp-ptt 10.1.0.41 \
  --flipper-port /dev/ttyACM0 \
  --test-vectors ook_433.csv
```

Expected output:

```
================================================================================
FORWARD TEST: Flipper TX → DUT RX (10 vectors, 4 DUTs)
================================================================================

Vector 1/10: Test pattern 1
  Protocol: OOK, Freq: 433.92 MHz, Rate: 4800 baud
  Payload: AABBCCDD, Expected: AABBCCDD
  Testing DUT 1... PASS
  Testing DUT 2... PASS
  Testing DUT 3... FAIL (got AABBCCDE)
  Testing DUT 4... TIMEOUT

Vector 2/10: Test pattern 2
  ...

================================================================================
COMPLIANCE MATRIX
================================================================================

Vector  DUT1   DUT2   DUT3   DUT4   
------------------------------------
1       ✓      ✓      ✗      T      
2       ✓      ✓      ✓      T      
3       ✓      ✓      ✓      ✓      
...

Legend: ✓=pass, ✗=fail, T=timeout, N=no signal, E=error, R=received
```

### Reverse Test: DUT TX → Flipper RX

```bash
./protocol_test.py \
  --esp-relay 10.1.0.40 \
  --esp-ptt 10.1.0.41 \
  --flipper-port /dev/ttyACM0 \
  --test-vectors ook_433.csv \
  --reverse
```

In reverse mode, scpi-ptt keys each DUT transmitter in sequence, and Flipper receives the transmission. Useful for verifying DUT transmitter output.

### Filter by Protocol or Frequency

```bash
# Test only 2FSK vectors
./protocol_test.py ... --protocol 2FSK

# Test only 315 MHz vectors
./protocol_test.py ... --freq-mhz 315.0

# Test 868 MHz 4FSK only
./protocol_test.py ... --protocol 4FSK --freq-mhz 868.3
```

## DUT Decoder Interface

**IMPORTANT:** Forward mode requires you to provide DUT-specific decoder implementations. The script defines a `DUTDecoder` protocol interface:

```python
class DUTDecoder(Protocol):
    def decode(self, timeout: float = 5.0) -> str:
        """
        Wait for and decode a transmission from the DUT.
        
        Returns:
            Decoded data as hex string, or empty string on timeout/error
        """
        ...
```

You must implement this interface for your specific DUT hardware. Examples:

### Serial DUT Decoder

```python
import serial

class SerialDUTDecoder:
    def __init__(self, port: str, baudrate: int = 115200):
        self.ser = serial.Serial(port, baudrate, timeout=1)
    
    def decode(self, timeout: float = 5.0) -> str:
        """Read decoded data from DUT's serial output."""
        start = time.time()
        while time.time() - start < timeout:
            line = self.ser.readline().decode('ascii').strip()
            if line.startswith("RX:"):
                return line[3:]  # Extract hex payload
        return ""  # Timeout
```

### GPIO/Logic Analyzer DUT Decoder

```python
class GPIODUTDecoder:
    def __init__(self, data_pin: int):
        import RPi.GPIO as GPIO
        GPIO.setmode(GPIO.BCM)
        GPIO.setup(data_pin, GPIO.IN)
        self.data_pin = data_pin
    
    def decode(self, timeout: float = 5.0) -> str:
        """Decode OOK data from GPIO pin."""
        # Implement bit-banging decoder here
        # Return decoded hex string
        ...
```

Once implemented, pass decoder instances to `run_test_forward()`:

```python
decoders = [
    SerialDUTDecoder('/dev/ttyUSB0'),  # DUT 1
    SerialDUTDecoder('/dev/ttyUSB1'),  # DUT 2
    SerialDUTDecoder('/dev/ttyUSB2'),  # DUT 3
    SerialDUTDecoder('/dev/ttyUSB3'),  # DUT 4
]

results = run_test_forward(relay, ptt, flipper, decoders, vectors, num_duts=4)
```

## Status

🔨 **Under Development**

Forward mode framework complete; requires user-provided DUT decoder implementations.
Reverse mode fully functional.

## Future Enhancements

- **SSA spectrum compliance** — Add SSA measurement for occupied bandwidth, harmonics, spurious emissions
- **Power level sweep** — Test receiver sensitivity at different TX power levels
- **Interference testing** — Inject interfering signals via second TX path
- **BER/PER measurement** — Statistical error rate analysis over multiple runs
- **Automated report generation** — HTML/PDF compliance reports with pass/fail criteria

## Related Projects

- `~/rf-bench/projects/esp32-combos/relay-and-relay/` — Dual relay control
- `~/rf-bench/projects/esp32-combos/scope-ssa-vna/` — Multi-instrument automation
- `~/rf-bench/projects/flipper/subghz/` — Flipper Sub-GHz tools
- `~/rf-bench/drivers/flipper/` — rf_bench.flipper driver package
