# Virtual Waterfall

✅ **Status: Tested 2026-06-14** — SCPI commands, WebSocket updates, spectrum display, time scrolling, color gradients verified

SCPI-controlled waterfall display for spectrum analyzer / time-series visualization. Features color-mapped intensity display with configurable ranges and scrolling.

## Features

- **SCPI TCP server** on port 5007 (IEEE 488.2 standard)
- **WebSocket real-time updates** for instant spectrum data
- **Color-mapped intensity** (blue→green→yellow→red gradient)
- **Scrolling waterfall** display (time flows downward)
- **Configurable frequency range** and intensity scaling
- **Variable bin count** (spectrum resolution)

## Ports

- **SCPI:** `tcp://0.0.0.0:5007`
- **HTTP:** `http://0.0.0.0:8007`
- **WebSocket:** `ws://0.0.0.0:8007/ws`
- **MQTT:** Configurable via `MQTT:CONF` command

## SCPI Commands

### Data Input
- `DATA:SPEC <bin_values>` — Send spectrum data (comma-separated float values)
- `DATA:SPEC?` — Query last spectrum data

### Configuration
- `CONF:FMIN <float>` — Set minimum frequency (Hz)
- `CONF:FMIN?` — Query minimum frequency
- `CONF:FMAX <float>` — Set maximum frequency (Hz)
- `CONF:FMAX?` — Query maximum frequency
- `CONF:IMIN <float>` — Set minimum intensity (dB)
- `CONF:IMIN?` — Query minimum intensity
- `CONF:IMAX <float>` — Set maximum intensity (dB)
- `CONF:IMAX?` — Query maximum intensity
- `CONF:BINS <int>` — Set number of frequency bins
- `CONF:BINS?` — Query bin count

### IEEE 488.2 Standard
- `*IDN?` — Identification query
- `*RST` — Reset to defaults
- `SYST:ERR?` — Query error queue

### MQTT
- `MQTT:CONF <host>,<topic>` — Configure MQTT broker and topic (expects JSON array)
- `MQTT:CONF?` — Query MQTT configuration

## Quick Start

```bash
# Start the server
cd ~/Dropbox/build/rf-bench/virtual/waterfall/backend
python3 server.py

# Open in browser
xdg-open http://localhost:8007

# Configure frequency range (14.0-14.1 MHz)
echo "CONF:FMIN 14000000" | nc localhost 5007
echo "CONF:FMAX 14100000" | nc localhost 5007
echo "CONF:IMIN -120" | nc localhost 5007
echo "CONF:IMAX -40" | nc localhost 5007
echo "CONF:BINS 100" | nc localhost 5007

# Send spectrum data (100 values from -120 to -80 dBm)
python3 -c "
import socket, random
sock = socket.socket()
sock.connect(('localhost', 5007))
while True:
    spectrum = [random.uniform(-120, -80) for _ in range(100)]
    data = ','.join(str(v) for v in spectrum)
    sock.sendall(f'DATA:SPEC {data}\n'.encode())
"
```

## Display Behavior

- Each `DATA:SPEC` command adds one horizontal line to the waterfall
- Lines scroll downward (newest at top)
- Color intensity maps dB values: blue (low) → green → yellow → red (high)
- Frequency axis shown at bottom (FMIN to FMAX)

## Integration Examples

### Spectrum analyzer waterfall
```python
from rf_bench.siglent import SSA3000X
import socket, time
import numpy as np

ssa = SSA3000X('10.1.1.60')
sock = socket.socket()
sock.connect(('localhost', 5007))

# Configure
ssa.set_center_frequency(14.05e6)
ssa.set_span(100e3)
sock.sendall(b'CONF:FMIN 14000000\n')
sock.sendall(b'CONF:FMAX 14100000\n')
sock.sendall(b'CONF:IMIN -120\n')
sock.sendall(b'CONF:IMAX -40\n')
sock.sendall(b'CONF:BINS 751\n')  # SSA trace has 751 points

while True:
    trace = ssa.get_trace()
    data = ','.join(str(v) for v in trace)
    sock.sendall(f'DATA:SPEC {data}\n'.encode())
    time.sleep(0.1)  # 10 Hz update rate
```

### RTL-SDR waterfall
```python
from rf_bench.rtlsdr import RTLSDR
import socket, time
import numpy as np

sdr = RTLSDR()
sdr.set_center_freq(144.39e6)  # APRS frequency
sdr.set_sample_rate(2.4e6)
sdr.set_gain(40)

sock = socket.socket()
sock.connect(('localhost', 5007))
sock.sendall(b'CONF:FMIN 143190000\n')  # Center - 1.2 MHz
sock.sendall(b'CONF:FMAX 145590000\n')  # Center + 1.2 MHz
sock.sendall(b'CONF:IMIN -60\n')
sock.sendall(b'CONF:IMAX -10\n')
sock.sendall(b'CONF:BINS 256\n')

while True:
    samples = sdr.read_samples(256 * 1024)
    psd = 10 * np.log10(np.abs(np.fft.fftshift(np.fft.fft(samples[:256]))) ** 2)
    data = ','.join(str(v) for v in psd)
    sock.sendall(f'DATA:SPEC {data}\n'.encode())
    time.sleep(0.05)  # 20 Hz update
```

### Audio spectrum analyzer
```python
import pyaudio
import numpy as np
import socket

RATE = 48000
CHUNK = 2048

p = pyaudio.PyAudio()
stream = p.open(format=pyaudio.paInt16, channels=1, rate=RATE, input=True, frames_per_buffer=CHUNK)

sock = socket.socket()
sock.connect(('localhost', 5007))
sock.sendall(b'CONF:FMIN 0\n')
sock.sendall(b'CONF:FMAX 24000\n')  # Nyquist
sock.sendall(b'CONF:IMIN -80\n')
sock.sendall(b'CONF:IMAX -20\n')
sock.sendall(b'CONF:BINS 512\n')

while True:
    data = np.frombuffer(stream.read(CHUNK), dtype=np.int16)
    fft = np.fft.rfft(data)
    psd = 20 * np.log10(np.abs(fft[:512]) + 1e-10)
    spectrum = ','.join(str(v) for v in psd)
    sock.sendall(f'DATA:SPEC {spectrum}\n'.encode())
```

### MQTT Integration
```bash
# Configure MQTT (expects JSON array of spectrum values)
echo "MQTT:CONF localhost,waterfall/spectrum" | nc localhost 5007

# Publish spectrum from elsewhere (Python example)
import json, paho.mqtt.publish as pub
spectrum = [-80, -75, -70, -65, -70, -75, -80]  # Example data
pub.single("waterfall/spectrum", json.dumps(spectrum), hostname="localhost")
```

## Use Cases

- RF spectrum analyzer displays
- SDR (software-defined radio) waterfalls
- Audio spectrum analyzers
- APRS/packet radio activity monitoring
- Band occupancy analysis
- Signal detection and tracking
- Propagation monitoring
- EMI/RFI analysis

## Color Mapping

Intensity values are mapped to colors:
- **Blue** — Minimum intensity (noise floor)
- **Green** — Low-mid intensity
- **Yellow** — Mid-high intensity
- **Red** — Maximum intensity (strong signals)

The mapping is linear between `CONF:IMIN` and `CONF:IMAX`.

## Files

```
waterfall/
├── backend/
│   └── server.py          # FastAPI SCPI + WebSocket server
├── frontend/
│   └── index.html         # Canvas waterfall display
└── README.md              # This file
```

## See Also

- [PORT-ASSIGNMENTS.md](../PORT-ASSIGNMENTS.md) — Port allocations for all instruments
- [BUILDING-STATUS.md](../BUILDING-STATUS.md) — Phase 1 completion status
- [line-chart](../line-chart/) — Time-series line chart display
- [xy-plot](../xy-plot/) — Scatter/line plot display
