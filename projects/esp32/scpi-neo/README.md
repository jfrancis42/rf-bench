# SCPI NeoPixel (WS2812B) Controller

ESP32-based network-controlled addressable LED strip controller using SCPI commands over TCP/IP.

Compatible with WS2812B, WS2811, SK6812, and similar addressable RGB LEDs.

## Hardware Requirements

- ESP32 dev board (any variant with WiFi)
- WS2812B LED strip (or compatible)
- External 5V power supply (1A per 60 LEDs at full white brightness)
- Level shifter (recommended) or 330Ω resistor for signal reliability

### Connections

| Component | Pin | Notes |
|-----------|-----|-------|
| LED strip data | GPIO 25 | 3.3V signal; add level shifter or 330Ω resistor |
| LED strip 5V | External PSU | **Never** power from ESP32 |
| LED strip GND | ESP32 GND + PSU GND | Common ground required |

**Power sizing:** Each LED draws ~60mA at full white (R=255, G=255, B=255). Examples:
- 60 LEDs: 3.6A → use 5A PSU minimum
- 150 LEDs: 9A → use 12A PSU minimum
- 300 LEDs: 18A → use 20A PSU minimum

At lower brightness or non-white colors, current is proportionally lower.

### Level Shifting

WS2812B expects 5V logic (HIGH ≥ 3.5V typical). ESP32 GPIO is 3.3V. Many strips work directly, but for reliability:
- Add 74HCT125 buffer (3.3V in → 5V out) between GPIO 25 and strip data line, **or**
- Add 330Ω resistor in series near the strip's data input (reduces reflections)

## Dependencies

Install via Arduino Library Manager:
- **Adafruit NeoPixel** (tested with v1.11.0+)

Built-in ESP32 libraries:
- WiFi (included in ESP32 core)

## SCPI Commands

All commands are case-insensitive and terminated with `\n`, `\r`, or `;`.

### IEEE 488.2 Common Commands

| Command | Response | Description |
|---------|----------|-------------|
| `*IDN?` | `N0GQ,ESP32-SCPI-NeoPixel,1.0,2026` | Identification |
| `*RST` | `OK` | Clear all pixels to off |
| `SYST:ERR?` | `0,"No error"` | System error query |

### NEO Subsystem (LED Control)

| Command | Response | Description |
|---------|----------|-------------|
| `NEO:LEN,<n>` | `OK` | Set strip length (1-300 pixels) |
| `NEO:LEN?` | `<n>` | Query strip length |
| `NEO:PIX (@n),<r>,<g>,<b>` | `OK` | Set pixel n to RGB (0-indexed) |
| `NEO:ALL,<r>,<g>,<b>` | `OK` | Set all pixels to RGB |
| `NEO:FILL,<start>,<count>,<r>,<g>,<b>` | `OK` | Fill range starting at `start` |
| `NEO:BRI,<0-100>` | `OK` | Set global brightness (percent) |
| `NEO:BRI?` | `<0-100>` | Query brightness (percent) |
| `NEO:SHOW` | `OK` | Update strip (latch pixel buffer) |
| `NEO:CLEA` | `OK` | Clear all pixels to off |

**Notes:**
- RGB values: 0-255 for each channel
- Pixel numbers: 0-indexed (first pixel is 0)
- `NEO:SHOW` is **required** to update the strip after setting pixel colors
- Brightness applies globally to all pixels (reduces effective RGB resolution)
- `NEO:LEN` clears the strip when changing length

### Command Flow

Typical sequence to set colors:
1. `NEO:LEN,60` — set strip length (if changed)
2. `NEO:PIX (@0),255,0,0` — set pixel 0 to red
3. `NEO:PIX (@1),0,255,0` — set pixel 1 to green
4. `NEO:SHOW` — latch changes to strip

Batch update all pixels:
1. `NEO:ALL,128,128,255` — set all to light blue
2. `NEO:SHOW` — latch

Brightness control (non-destructive to color data):
1. `NEO:BRI,50` — reduce to 50% brightness
2. `NEO:SHOW` — latch

## Usage Examples

### Telnet (quick test)

```bash
telnet 192.168.1.42 5025
*IDN?
# N0GQ,ESP32-SCPI-NeoPixel,1.0,2026

NEO:LEN,60
NEO:ALL,255,0,0
NEO:SHOW
# All 60 pixels turn red

NEO:BRI,25
NEO:SHOW
# Brightness reduced to 25%

NEO:PIX (@0),0,255,0
NEO:SHOW
# First pixel turns green

NEO:CLEA
NEO:SHOW
# All pixels off
```

### Python (socket)

```python
import socket
import time

class NeoPixelSCPI:
    def __init__(self, ip, port=5025):
        self.ip = ip
        self.port = port
        self.sock = None

    def connect(self):
        self.sock = socket.socket()
        self.sock.connect((self.ip, self.port))

    def send(self, cmd):
        self.sock.sendall((cmd + '\n').encode())

    def query(self, cmd):
        self.send(cmd)
        return self.sock.recv(1024).decode().strip()

    def close(self):
        if self.sock:
            self.sock.close()

# Rainbow animation
neo = NeoPixelSCPI('192.168.1.42')
neo.connect()

neo.send('NEO:LEN,60')
neo.send('NEO:BRI,50')

colors = [
    (255, 0, 0),    # Red
    (255, 127, 0),  # Orange
    (255, 255, 0),  # Yellow
    (0, 255, 0),    # Green
    (0, 0, 255),    # Blue
    (75, 0, 130),   # Indigo
    (148, 0, 211),  # Violet
]

for i in range(60):
    r, g, b = colors[i % len(colors)]
    neo.send(f'NEO:PIX (@{i}),{r},{g},{b}')

neo.send('NEO:SHOW')
time.sleep(5)

neo.send('NEO:CLEA')
neo.send('NEO:SHOW')
neo.close()
```

### Python (pyvisa)

```python
import pyvisa
import time

rm = pyvisa.ResourceManager('@py')
neo = rm.open_resource('TCPIP::192.168.1.42::5025::SOCKET')

# Theater chase pattern
neo.write('NEO:LEN,60')
neo.write('NEO:BRI,30')

for offset in range(3):
    neo.write('NEO:CLEA')
    for i in range(offset, 60, 3):
        neo.write(f'NEO:PIX (@{i}),255,255,255')
    neo.write('NEO:SHOW')
    time.sleep(0.1)

neo.write('NEO:CLEA')
neo.write('NEO:SHOW')
neo.close()
```

### MATLAB

```matlab
% Connect to NeoPixel controller
neo = tcpclient('192.168.1.42', 5025);

% Set strip length
writeline(neo, 'NEO:LEN,60');

% Fill with gradient
for i = 0:59
    r = round(255 * (i / 59));
    g = round(255 * (1 - i / 59));
    b = 128;
    cmd = sprintf('NEO:PIX (@%d),%d,%d,%d', i, r, g, b);
    writeline(neo, cmd);
end

writeline(neo, 'NEO:SHOW');
pause(5);

writeline(neo, 'NEO:CLEA');
writeline(neo, 'NEO:SHOW');
clear neo;
```

## Upload and Configuration

1. Open `scpi-neo.ino` in Arduino IDE
2. Edit WiFi credentials at top of file:
   ```cpp
   const char* ssid = "YourNetworkName";
   const char* password = "YourPassword";
   ```
3. Tools → Board → ESP32 Dev Module (or your specific board)
4. Tools → Port → (select USB serial port)
5. Sketch → Upload
6. Tools → Serial Monitor (115200 baud) to see IP address

Serial output on boot:
```
SCPI NeoPixel Controller
========================
Connecting to YourNetwork.... connected!
IP address: 192.168.1.42
SCPI port: 5025
LED strip: 60 pixels on GPIO 25

Ready for SCPI commands
```

## Safety and Current Limits

**Power supply sizing is critical.** Undersized PSUs will cause:
- Voltage sag → color shifts (especially white → yellow)
- ESP32 brownouts/resets if sharing ground with high strip current
- Fire hazard if PSU overheats

**Best practices:**
- Use PSU rated for 150% of calculated max current
- Add 1000µF capacitor across strip's 5V/GND at power entry point
- Keep data line short (<1m) or use differential signaling (e.g., CAT5)
- Set brightness limit in code if strip length is unknown: `NEO:BRI,30` for safety

**Strip length safety:** Code limits to 300 pixels max. Override `max_leds` constant if larger strips are needed (but verify PSU capacity first).

## Troubleshooting

| Problem | Solution |
|---------|----------|
| First LED glitches | Add 330Ω resistor between GPIO 25 and strip data |
| LEDs flicker or show wrong colors at startup | Add 1000µF capacitor at strip power entry |
| No connection | Check Serial Monitor for IP address; verify WiFi credentials |
| Strip doesn't respond | Check common ground between ESP32 and strip PSU |
| Colors shift to yellow | PSU voltage sag; reduce brightness or upgrade PSU |
| ESP32 resets randomly | Ground loop with high strip current; isolate PSU grounds or use level shifter with separate power domains |

## Integration with rf-bench

Could be added as `~/rf-bench/drivers/neopixel/` driver package wrapping SCPI commands in a Python class.

Possible use cases:
- Visual indicator for test automation (green = pass, red = fail)
- Power level bar graph on spectrum analyzer projects
- Frequency display on KiwiSDR band monitor
- Status indicator for APRS igate or beacon logger

## License

Public domain / MIT-0. Use freely.

## References

- [Adafruit NeoPixel Überguide](https://learn.adafruit.com/adafruit-neopixel-uberguide)
- [WS2812B Datasheet](https://cdn-shop.adafruit.com/datasheets/WS2812B.pdf)
- [SCPI Standard](https://www.ivifoundation.org/docs/scpi-99.pdf)
