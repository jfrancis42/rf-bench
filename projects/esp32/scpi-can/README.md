# SCPI CAN Bus Controller for ESP32

Network-accessible CAN bus master bridge — send/receive CAN frames via Standard Commands for Programmable Instruments (SCPI) over TCP/IP. Supports standard (11-bit) and extended (29-bit) CAN IDs.

## Hardware

- **ESP32 dev board** (any variant with SPI: ESP32, ESP32-S2, ESP32-S3, ESP32-C3)
- **MCP2515 CAN controller** (SPI interface)
- **MCP2551 CAN transceiver** (or TJA1050, SN65HVD230 for 3.3V)
- **120Ω termination resistor** (between CAN_H and CAN_L at each end of bus)

Most MCP2515 + MCP2551 modules are available as single PCB units with on-board 8 MHz crystal and power regulation. Common sources: Seeed Studio, Adafruit, generic clones on AliExpress/Amazon.

## Pin Connections

```
ESP32      MCP2515
GPIO 23  → MOSI (SI)
GPIO 19  → MISO (SO)
GPIO 18  → SCK
GPIO 5   → CS
GPIO 4   → INT (optional — not used in polling mode)
GND      → GND
5V       → VCC (or 3.3V if module supports it)

MCP2551 (CAN transceiver)
CAN_H    → CAN bus H (yellow/white)
CAN_L    → CAN bus L (green/blue)
```

**SPI bus:** ESP32 has two SPI buses (HSPI and VSPI). This code uses VSPI (default). GPIO assignments match ESP32 VSPI defaults.

**Power:** Most MCP2515 modules require 5V input (they have on-board 3.3V regulator for MCP2515). MCP2551 transceiver is 5V. The SPI interface is 3.3V-tolerant (module handles level shifting).

**Interrupt pin:** GPIO 4 is connected to MCP2515 INT pin but not used in this firmware (polling mode). For high-speed CAN (>500 kbps) or low-latency requirements, interrupt-driven RX is better (future enhancement).

## CAN Bus Basics

### CAN Frame Structure

Standard CAN frame (CAN 2.0A):
- **ID:** 11 bits (0x000 to 0x7FF, 2048 possible IDs)
- **Data:** 0 to 8 bytes
- **Priority:** Lower ID = higher priority (arbitration)

Extended CAN frame (CAN 2.0B):
- **ID:** 29 bits (0x00000000 to 0x1FFFFFFF, ~536 million possible IDs)
- **Data:** 0 to 8 bytes
- **Backward compatible:** Standard nodes ignore extended frames

### CAN Baud Rates

Common CAN baud rates (supported by MCP2515 with 8 MHz crystal):
- **5 kbps** — ultra-low-speed, long cables
- **10 kbps** — industrial automation (DeviceNet, CANopen)
- **20 kbps** — industrial
- **50 kbps** — industrial
- **100 kbps** — industrial
- **125 kbps** — CANopen default
- **250 kbps** — J1939 heavy vehicle
- **500 kbps** — CAN high-speed (automotive body electronics)
- **1000 kbps (1 Mbps)** — CAN high-speed (automotive powertrain, max standard rate)

Higher baud rates require shorter cables. 1 Mbps works up to ~40 meters. 125 kbps works up to ~500 meters.

### Bus Termination

CAN requires **120Ω termination** at each end of the bus (between CAN_H and CAN_L). Without termination, reflections cause communication errors.

**Single node testing:** Add 120Ω across CAN_H/CAN_L on the ESP32 module. For multi-node networks, add 120Ω at physical ends of the cable (not at intermediate nodes).

## SCPI Commands

### IEEE 488.2 Common Commands

- `*IDN?` — identification
- `*RST` — reset CAN controller
- `SYST:ERR?` — system error query

### CAN Subsystem

#### Configuration

- `CAN:RATE,<kbps>` — set baud rate (5, 10, 20, 50, 100, 125, 250, 500, 1000)
- `CAN:RATE?` — query baud rate (returns integer kbps)
- `CAN:FILT,<id>,<mask>` — set filter/mask (mask 0x000 = accept all)
- `CAN:FILT?` — query filter/mask

#### Transmit

- `CAN:SEND,<id>,<byte1>,<byte2>,...` — send standard frame (11-bit ID)
- `CAN:SEND:EXT,<id>,<byte1>,<byte2>,...` — send extended frame (29-bit ID)

**ID format:** Decimal or hex (0x123 or 291). Hex recommended.

**Data bytes:** 0 to 8 bytes, comma-separated, decimal or hex (0xFF or 255).

**Zero-length frames:** Omit data bytes: `CAN:SEND,0x123` sends ID 0x123 with DLC=0.

#### Receive

- `CAN:READ?` — read next frame from RX buffer (returns `id,ext,len,data_csv` or `NONE`)
- `CAN:AVAI?` — query number of frames available in RX buffer

**RX buffer:** 32-frame circular buffer. Frames are polled from MCP2515 every loop iteration (~1 ms). If buffer fills, oldest frames are dropped.

**Response format:** `0x123,0,4,0x11,0x22,0x33,0x44` (standard ID 0x123, 4 data bytes)

**Extended frame response:** `0x12345678,1,2,0xAB,0xCD` (extended ID, 29-bit, 2 data bytes)

**Empty buffer:** `NONE`

## Examples

### Scan CAN bus (passive sniffing)

```bash
telnet 192.168.1.42 5025
CAN:RATE,500
CAN:AVAI?
# Returns: 5 (5 frames received)
CAN:READ?
# Returns: 0x123,0,8,0x01,0x02,0x03,0x04,0x05,0x06,0x07,0x08
CAN:READ?
# Returns: 0x456,0,2,0xAB,0xCD
```

### Send standard CAN frame (ID 0x123, 4 data bytes)

```bash
CAN:SEND,0x123,0x11,0x22,0x33,0x44
# Returns: OK
```

### Send extended CAN frame (ID 0x12345678, 2 data bytes)

```bash
CAN:SEND:EXT,0x12345678,0xAB,0xCD
# Returns: OK
```

### Send zero-length frame (heartbeat / RTR)

```bash
CAN:SEND,0x100
# Returns: OK
```

### Set filter to accept only ID 0x123 (exact match)

```bash
CAN:FILT,0x123,0x7FF
# Returns: OK
```

Mask 0x7FF means all 11 bits must match. Frames with ID 0x123 are accepted; all others are rejected.

### Set filter to accept all frames (default)

```bash
CAN:FILT,0x000,0x000
# Returns: OK
```

Mask 0x000 means no bits are checked — all frames accepted.

### Change baud rate to 125 kbps

```bash
CAN:RATE,125
# Returns: OK
CAN:RATE?
# Returns: 125
```

## Python Integration

### Simple socket client

```python
import socket
import time

def scpi_cmd(ip, cmd):
    s = socket.socket()
    s.connect((ip, 5025))
    s.sendall((cmd + '\n').encode())
    if '?' in cmd:
        resp = s.recv(1024).decode().strip()
        s.close()
        return resp
    s.close()

# Set baud rate
scpi_cmd('192.168.1.42', 'CAN:RATE,500')

# Send frame
scpi_cmd('192.168.1.42', 'CAN:SEND,0x123,0x11,0x22,0x33,0x44')

# Read frames
for _ in range(10):
    frame = scpi_cmd('192.168.1.42', 'CAN:READ?')
    if frame != 'NONE':
        print(f"RX: {frame}")
    time.sleep(0.1)
```

### pyvisa (instrument automation)

```python
import pyvisa

rm = pyvisa.ResourceManager('@py')
can = rm.open_resource('TCPIP::192.168.1.42::5025::SOCKET')

# Send frame
can.write('CAN:SEND,0x123,0x11,0x22,0x33,0x44')

# Read frame
frame = can.query('CAN:READ?')
print(f"RX: {frame}")

# Query buffer depth
count = can.query('CAN:AVAI?')
print(f"Frames available: {count}")
```

## Use Cases

### 1. Automotive Diagnostics

Sniff CAN bus on OBD-II connector (standard 500 kbps or 250 kbps). Decode OBD-II PIDs, manufacturer-specific frames, powertrain data.

**Example:** Read engine RPM, throttle position, coolant temp from ECU broadcast frames.

### 2. Industrial Automation

Control CANopen devices (motors, sensors, I/O modules). Send SDO (Service Data Object) and PDO (Process Data Object) frames to configure and read devices.

### 3. Marine / RV Networks

NMEA 2000 (250 kbps CAN). Monitor GPS, depth sounder, wind sensor, autopilot, AIS data. Integrate with onboard electronics.

### 4. Agricultural Machinery

ISOBUS / ISO 11783 (250 kbps). Control tractors, implements, precision agriculture systems.

### 5. CAN Protocol Development

Prototype CAN-based protocols. Send arbitrary frames, verify device responses, fuzz-test CAN nodes.

### 6. Lab Automation

Integrate CAN devices into SCPI-based ATE (Automated Test Equipment). Control CAN-enabled DUT (Device Under Test) from Python/MATLAB test scripts.

### 7. CAN Bus Reverse Engineering

Capture frames from unknown CAN networks. Log traffic, identify IDs, decode data formats. Useful for automotive aftermarket development (custom dashboards, steering wheel controls, etc.).

### 8. Educational Tool

Teach CAN protocol without embedded C programming. Students interact with live CAN bus via simple SCPI commands.

## Installation

1. Install MCP_CAN library:
   - Arduino IDE → Tools → Manage Libraries
   - Search "MCP_CAN"
   - Install "MCP_CAN" by coryjfowler
   - Or: https://github.com/coryjfowler/MCP_CAN_lib

2. Open `scpi-can.ino` in Arduino IDE

3. Edit WiFi credentials at top of file

4. Tools → Board → ESP32 Dev Module (or your ESP32 variant)

5. Tools → Port → (select your ESP32 USB port)

6. Click Upload

7. Open Serial Monitor (115200 baud) to see IP address

8. Wire MCP2515 to ESP32 (see Pin Connections above)

9. Connect CAN_H/CAN_L to physical CAN bus (with 120Ω termination)

## MCP2515 Library Notes

### Supported Libraries

This firmware uses `MCP_CAN` by coryjfowler (most popular, actively maintained):
- https://github.com/coryjfowler/MCP_CAN_lib
- Arduino Library Manager: "MCP_CAN"

**Alternative:** Seeed Studio fork (older, less maintained):
- https://github.com/Seeed-Studio/CAN_BUS_Shield

Both are API-compatible for basic operations (`begin`, `sendMsgBuf`, `readMsgBuf`).

### Crystal Frequency

MCP2515 modules typically use **8 MHz** or **16 MHz** crystal. This firmware assumes 8 MHz (most common on cheap modules).

**If your module has 16 MHz crystal:**
Change line 87 in `scpi-can.ino`:
```cpp
if (CAN.begin(MCP_ANY, can_baud, MCP_16MHZ) == CAN_OK) {
```

**How to check:** Look for small metal can on MCP2515 PCB. Label says "8.000" (8 MHz) or "16.000" (16 MHz).

### Mode Selection

`MCP_ANY` mode allows initialization without checking for ACK from other CAN nodes. Useful for single-node testing (loopback or sniffing).

For production CAN networks with multiple nodes, use `MCP_NORMAL` in `CAN.begin()` call.

## Troubleshooting

### CAN:SEND returns ERROR: CAN send failed

- **No bus termination** — add 120Ω resistor between CAN_H and CAN_L
- **Wrong baud rate** — CAN nodes must agree on baud rate (no auto-detection)
- **No other nodes on bus** — MCP2515 waits for ACK from another node. Use loopback mode for testing without physical bus: `CAN.setMode(MCP_LOOPBACK)` after `CAN.begin()`
- **Wiring error** — verify SPI connections (MOSI, MISO, SCK, CS)
- **Power issue** — check 5V supply to MCP2515 module

### CAN:READ? returns NONE (no frames received)

- **Wrong baud rate** — must match transmitting nodes
- **No traffic on bus** — verify other nodes are transmitting
- **Filter too restrictive** — set filter to accept all: `CAN:FILT,0x000,0x000`
- **Wiring error** — verify CAN_H and CAN_L connections
- **Bus off state** — MCP2515 entered bus-off after too many errors. Send `*RST` to reset.

### MCP2515 initialization fails (serial monitor shows "FAILED")

- **Wrong crystal frequency** — change `MCP_8MHZ` to `MCP_16MHZ` in code
- **SPI wiring error** — verify MOSI/MISO/SCK/CS connections
- **CS pin conflict** — GPIO 5 may be used by another peripheral. Change to GPIO 15 or 13.
- **Power issue** — check 5V supply and GND
- **Faulty module** — try different MCP2515 board

### RX buffer overflow (frames dropped)

Firmware polls CAN bus every loop iteration (~1 ms). At high baud rates (1 Mbps) with heavy traffic, buffer may fill.

**Solutions:**
1. Read frames faster (call `CAN:READ?` more frequently from Python)
2. Increase RX buffer size (change `RX_BUFFER_SIZE` in code)
3. Use interrupt-driven RX (future enhancement)
4. Apply stricter filter (`CAN:FILT`) to reduce unwanted frames

### Bus-off state (too many errors)

CAN nodes enter "bus-off" state after 255+ consecutive errors (wrong baud rate, no termination, electrical noise).

**Recovery:** Send `*RST` command to reinitialize MCP2515.

## Limitations

- **Single CAN bus** — one MCP2515 per ESP32. Could add second bus by using different CS pin and creating second `MCP_CAN` instance.
- **Polling mode** — RX frames polled every ~1 ms. For high-speed traffic (>500 kbps) or low latency (<10 ms), interrupt-driven RX is better.
- **32-frame RX buffer** — overflows if frames aren't read fast enough. Adjust `RX_BUFFER_SIZE` in code for deeper buffering.
- **No CAN FD** — MCP2515 supports CAN 2.0A/B only (max 1 Mbps, 8-byte payload). For CAN FD (8 Mbps, 64-byte payload), use MCP2518FD (different driver required).
- **No J1939 / CANopen / OBD-II decoding** — firmware sends/receives raw CAN frames. Higher-layer protocol parsing (J1939 PGN, CANopen SDO/PDO, OBD-II PIDs) must be done in Python.
- **No timestamping** — RX frames don't include timestamp. For timing analysis, log timestamps in Python when reading frames.
- **8 MHz crystal assumption** — code assumes 8 MHz crystal (most common). 16 MHz modules require code change (see MCP2515 Library Notes).

## Future Enhancements

- **Interrupt-driven RX** — use GPIO 4 INT pin to trigger frame reads (lower latency)
- **Timestamping** — add millisecond timestamp to RX frames
- **CAN:SEND:RTR** — send Remote Transmission Request frames
- **CAN:STAT?** — query error counters (TEC, REC), bus state (error-active, error-passive, bus-off)
- **CAN:ERR?** — read last error register
- **Dual bus support** — second MCP2515 on different CS pin
- **CAN FD support** — MCP2518FD driver (8 Mbps, 64-byte frames)
- **J1939 helpers** — decode PGN (Parameter Group Number), source address, priority
- **CANopen helpers** — SDO/PDO encode/decode
- **OBD-II helpers** — PID request/response parsing
- **Web UI** — HTML interface for manual CAN transactions
- **MQTT publish** — push CAN frames to MQTT broker (automotive telemetry)
- **SD card logging** — log frames to CSV on SD card (long-term capture)
- **DBC file parsing** — decode frames using Vector DBC format (signal definitions)

## Related Projects

- `~/rf-bench/projects/esp32/scpi-relay/` — ESP32 relay controller (GPIO outputs)
- `~/rf-bench/projects/esp32/scpi-i2c/` — ESP32 I2C master bridge
- `~/rf-bench/projects/esp32/scpi-spi/` — ESP32 SPI master bridge (planned)
- `~/rf-bench/drivers/buspirate/` — Bus Pirate I2C/SPI/UART master (USB-serial Python driver)

## References

- [CAN Bus Specification](https://www.bosch-semiconductors.com/media/ip_modules/pdf_2/can/canpaper.pdf) — Bosch CAN 2.0 spec
- [MCP2515 Datasheet](https://ww1.microchip.com/downloads/en/DeviceDoc/MCP2515-Stand-Alone-CAN-Controller-with-SPI-20001801J.pdf) — Microchip
- [MCP2551 Datasheet](https://ww1.microchip.com/downloads/en/DeviceDoc/20001667G.pdf) — CAN transceiver
- [MCP_CAN Library](https://github.com/coryjfowler/MCP_CAN_lib) — Arduino library
- [J1939 Protocol](https://www.csselectronics.com/pages/j1939-explained-simple-intro-tutorial) — Heavy vehicle CAN
- [CANopen Protocol](https://www.can-cia.org/canopen/) — Industrial automation CAN

## Version

1.0 (2026-06-12)
