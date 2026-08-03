# Waterfall — part of `rf-bench-drivers-virtual`
Python driver for **Virtual Waterfall Display** SCPI instrument. Displays frequency-domain spectrum data as a scrolling color-coded waterfall via SCPI-over-TCP (port 5007).

## Installation

```bash
pip install rf-bench-drivers-virtual
```

Or install from source:

```bash
cd drivers/virtual-waterfall
pip install -e .
```

## Quick Start

```python
from rf_bench.virtual import VirtualWaterfall

# Configure waterfall display
with VirtualWaterfall("10.1.1.52") as waterfall:
    waterfall.configure(
        freq_start=144.0,    # MHz
        freq_stop=148.0,     # MHz
        power_min=-100,      # dBm
        power_max=-50,       # dBm
        title="2m Band Monitor"
    )
    
    # Add spectrum traces (list of power values)
    spectrum = [-80, -75, -70, -65, -60, -65, -70, -75, -80]
    waterfall.add_spectrum(spectrum)
```

## Backend Server

The driver connects to a virtual waterfall backend server:

```bash
cd ~/Dropbox/build/rf-bench/virtual/waterfall/backend
python3 server.py
```

Default ports:
- **SCPI TCP**: 5007
- **HTTP/WebSocket**: 8007

Open browser at `http://localhost:8007` to see the waterfall display.

## API Reference

### Connection

```python
VirtualWaterfall(host, port=5007, timeout=2.0)
```

- **host**: IP address or hostname of backend server
- **port**: SCPI TCP port (default 5007)
- **timeout**: Socket timeout in seconds

### IEEE 488.2 Commands

```python
waterfall.idn()           # → "N0GQ,Virtual-Waterfall,1.0,2026"
waterfall.reset()         # Reset to default state, clear waterfall
waterfall.get_error()     # → "0,No error"
```

### Spectrum Measurement

```python
# Add a spectrum trace (list of power values in dBm)
spectrum = [-80, -75, -70, -65, -60, -65, -70, -75, -80]
waterfall.add_spectrum(spectrum)

# Query number of traces in history
count = waterfall.get_trace_count()  # → 1

# Clear all traces
waterfall.clear()
```

### Frequency Configuration

```python
# Set frequency range (MHz)
waterfall.set_freq_start(144.0)
waterfall.set_freq_stop(148.0)
waterfall.set_freq_range(144.0, 148.0)  # Set both at once

# Query frequency range
start = waterfall.get_freq_start()      # → 144.0
stop = waterfall.get_freq_stop()        # → 148.0
start, stop = waterfall.get_freq_range()  # → (144.0, 148.0)
```

### Power Configuration

```python
# Set power range for color scale (dBm)
waterfall.set_power_min(-100)
waterfall.set_power_max(-50)
waterfall.set_power_range(-100, -50)  # Set both at once

# Query power range
min_pwr = waterfall.get_power_min()      # → -100.0
max_pwr = waterfall.get_power_max()      # → -50.0
min_pwr, max_pwr = waterfall.get_power_range()  # → (-100.0, -50.0)
```

### Display Configuration

```python
# Set display title
waterfall.set_title("2m Band Monitor")
waterfall.get_title()  # → "2m Band Monitor"

# Set history depth (number of traces to display)
waterfall.set_history_depth(200)  # 10-500, default 100
waterfall.get_history_depth()     # → 200
```

### MQTT Integration

```python
# Configure MQTT broker and topic
# Backend subscribes and updates waterfall automatically
waterfall.configure_mqtt("mqtt.local", "spectrum/rtlsdr")

# Query MQTT configuration
config = waterfall.get_mqtt_config()  # → "mqtt.local,spectrum/rtlsdr"
```

### Convenience Methods

```python
# Configure all parameters at once
waterfall.configure(
    freq_start=144.0,
    freq_stop=148.0,
    power_min=-100,
    power_max=-50,
    title="2m Band Monitor",
    history_depth=150
)

# Stream from a generator
def spectrum_generator():
    while True:
        spectrum = get_spectrum_from_sdr()  # Your code
        yield spectrum

waterfall.stream(spectrum_generator(), interval=0.1)
```

## Common Use Cases

### SSA3032X Spectrum Analyzer Monitor

```python
from rf_bench.siglent import SSA3000X
from rf_bench.virtual import VirtualWaterfall
import time

ssa = SSA3000X("10.1.1.60")
waterfall = VirtualWaterfall("10.1.1.52")

# Configure spectrum analyzer
ssa.set_center_span(14.2e6, 100e3)  # 14.2 MHz ± 50 kHz
ssa.set_rbw(1e3)  # 1 kHz RBW

# Configure waterfall
waterfall.configure(
    freq_start=14.15,
    freq_stop=14.25,
    power_min=-100,
    power_max=-40,
    title="20m Band - 14.2 MHz"
)

# Stream spectrum data
while True:
    trace = ssa.get_trace()
    freqs = ssa.get_frequencies()
    powers = trace  # Already in dBm
    
    waterfall.add_spectrum(powers)
    time.sleep(0.1)  # 10 Hz update rate
```

### RTL-SDR Wideband Monitor

```python
from rf_bench.rtlsdr import RTLSDR
from rf_bench.virtual import VirtualWaterfall
import numpy as np

sdr = RTLSDR()
waterfall = VirtualWaterfall("10.1.1.52")

# Configure RTL-SDR
center_freq = 144.5e6  # 144.5 MHz
sample_rate = 2.4e6    # 2.4 MSps
sdr.set_center_freq(center_freq)
sdr.set_sample_rate(sample_rate)
sdr.set_gain(30)

# Configure waterfall
waterfall.configure(
    freq_start=143.3,  # MHz
    freq_stop=145.7,   # MHz
    power_min=-80,
    power_max=-30,
    title="2m Band - RTL-SDR",
    history_depth=200
)

# Stream power spectrum
fft_size = 1024
for samples in sdr.stream(chunk_size=fft_size):
    # Compute power spectrum
    fft = np.fft.fftshift(np.fft.fft(samples))
    power_db = 20 * np.log10(np.abs(fft) + 1e-10)
    
    waterfall.add_spectrum(power_db.tolist())
```

### KiwiSDR HF Monitor

```python
from rf_bench.kiwisdr import KiwiSDR
from rf_bench.virtual import VirtualWaterfall
import numpy as np

kiwi = KiwiSDR("kiwisdr.local")
waterfall = VirtualWaterfall("10.1.1.52")

# Configure KiwiSDR for 20m band
center_freq = 14.1e6  # 14.1 MHz
bandwidth = 12e3      # 12 kHz
kiwi.set_frequency(center_freq)
kiwi.set_bandwidth(bandwidth)

# Configure waterfall
waterfall.configure(
    freq_start=14.094,  # FT8 calling frequency area
    freq_stop=14.106,
    power_min=-110,
    power_max=-60,
    title="20m FT8 - KiwiSDR",
    history_depth=300  # Longer history for slow HF activity
)

# Stream IQ data and display spectrum
for iq_samples in kiwi.stream():
    fft = np.fft.fftshift(np.fft.fft(iq_samples, n=512))
    power_db = 20 * np.log10(np.abs(fft) + 1e-10)
    waterfall.add_spectrum(power_db.tolist())
```

### SunSDR2 Pro VHF Monitor

```python
from rf_bench.sunsdr import SunSDR
from rf_bench.virtual import VirtualWaterfall
import numpy as np

sunsdr = SunSDR("sunsdr.local")
waterfall = VirtualWaterfall("10.1.1.52")

# Configure SunSDR for 2m FM calling frequency
center_freq = 146.52e6  # 146.52 MHz
sample_rate = 192000    # 192 kHz
sunsdr.set_frequency(center_freq)
sunsdr.set_sample_rate(sample_rate)

# Configure waterfall
waterfall.configure(
    freq_start=146.42,
    freq_stop=146.62,
    power_min=-90,
    power_max=-40,
    title="2m FM Calling - SunSDR2",
    history_depth=150
)

# Stream IQ and display
for iq_samples in sunsdr.stream_iq():
    fft = np.fft.fftshift(np.fft.fft(iq_samples, n=1024))
    power_db = 20 * np.log10(np.abs(fft) + 1e-10)
    waterfall.add_spectrum(power_db.tolist())
```

### IC-9700 Panadapter (via rigctld + audio)

```python
from rf_bench.icom import IC9700
from rf_bench.virtual import VirtualWaterfall
import numpy as np
import pyaudio

radio = IC9700()
waterfall = VirtualWaterfall("10.1.1.52")

# Set radio to 2m
radio.set_frequency(146_000_000)
radio.set_mode("FM")

# Configure waterfall around current frequency
waterfall.configure(
    freq_start=145.9,
    freq_stop=146.1,
    power_min=-80,
    power_max=-30,
    title="IC-9700 Panadapter - 2m"
)

# Capture audio from IC-9700 USB audio (requires pyaudio)
p = pyaudio.PyAudio()
stream = p.open(format=pyaudio.paFloat32, channels=2, rate=48000,
                input=True, frames_per_buffer=2048)

# Display spectrum from audio
try:
    while True:
        audio = np.frombuffer(stream.read(2048), dtype=np.float32)
        audio_mono = audio[::2]  # Left channel
        
        fft = np.fft.fftshift(np.fft.fft(audio_mono))
        power_db = 20 * np.log10(np.abs(fft) + 1e-10)
        
        waterfall.add_spectrum(power_db.tolist())
finally:
    stream.close()
    p.terminate()
```

### Automated Band Scanner

```python
from rf_bench.siglent import SSA3000X
from rf_bench.virtual import VirtualWaterfall
import time

ssa = SSA3000X("10.1.1.60")
waterfall = VirtualWaterfall("10.1.1.52")

# Scan parameters
bands = [
    (3.5e6, 4.0e6, "80m"),
    (7.0e6, 7.3e6, "40m"),
    (14.0e6, 14.35e6, "20m"),
    (21.0e6, 21.45e6, "15m"),
    (28.0e6, 29.7e6, "10m"),
]

for start_hz, stop_hz, band_name in bands:
    print(f"Scanning {band_name}...")
    
    # Configure SSA
    center = (start_hz + stop_hz) / 2
    span = stop_hz - start_hz
    ssa.set_center_span(center, span)
    ssa.set_rbw(3e3)  # 3 kHz RBW
    
    # Configure waterfall
    waterfall.configure(
        freq_start=start_hz / 1e6,
        freq_stop=stop_hz / 1e6,
        power_min=-110,
        power_max=-50,
        title=f"HF Band Scan - {band_name}"
    )
    waterfall.clear()
    
    # Capture 30 seconds of data per band
    for _ in range(300):
        trace = ssa.get_trace()
        waterfall.add_spectrum(trace)
        time.sleep(0.1)
```

### MQTT-Driven Remote Display

```python
from rf_bench.virtual import VirtualWaterfall

# Configure waterfall to receive spectrum from MQTT
waterfall = VirtualWaterfall("10.1.1.52")

waterfall.configure(
    freq_start=144.0,
    freq_stop=148.0,
    power_min=-100,
    power_max=-40,
    title="Remote 2m Monitor"
)

# Backend subscribes to MQTT topic and updates automatically
waterfall.configure_mqtt("mqtt.local", "spectrum/remote-sdr")

print("Waterfall configured. Publishing to MQTT topic 'spectrum/remote-sdr'")
print("will update the display automatically.")

# On the remote SDR side (separate script):
# import paho.mqtt.client as mqtt
# client = mqtt.Client()
# client.connect("mqtt.local", 1883)
# 
# while True:
#     spectrum = get_spectrum()  # Your SDR code
#     csv_data = ','.join(str(x) for x in spectrum)
#     client.publish("spectrum/remote-sdr", csv_data)
#     time.sleep(0.1)
```

### Multi-Receiver Comparison

```python
from rf_bench.rtlsdr import RTLSDR
from rf_bench.virtual import VirtualWaterfall
import numpy as np

# Two RTL-SDR dongles on same antenna
sdr1 = RTLSDR(device_index=0)
sdr2 = RTLSDR(device_index=1)

waterfall1 = VirtualWaterfall("10.1.1.52", port=5007)
waterfall2 = VirtualWaterfall("10.1.1.52", port=5008)  # Second backend

# Configure both
for sdr, waterfall, name in [(sdr1, waterfall1, "RTL-SDR #1"),
                               (sdr2, waterfall2, "RTL-SDR #2")]:
    sdr.set_center_freq(146.5e6)
    sdr.set_sample_rate(2.4e6)
    sdr.set_gain(30)
    
    waterfall.configure(
        freq_start=145.3,
        freq_stop=147.7,
        power_min=-80,
        power_max=-30,
        title=name
    )

# Stream both in parallel (would normally use threading)
# Simplified single-threaded example:
while True:
    samples1 = sdr1.read_samples(1024)
    fft1 = np.fft.fftshift(np.fft.fft(samples1))
    waterfall1.add_spectrum((20 * np.log10(np.abs(fft1) + 1e-10)).tolist())
    
    samples2 = sdr2.read_samples(1024)
    fft2 = np.fft.fftshift(np.fft.fft(samples2))
    waterfall2.add_spectrum((20 * np.log10(np.abs(fft2) + 1e-10)).tolist())
```

## SCPI Command Reference

### IEEE 488.2 Common Commands
- `*IDN?` — Identification query
- `*RST` — Reset to defaults and clear waterfall
- `SYST:ERR?` — Query error queue

### Measurement Commands
- `MEAS:SPEC <csv>` — Add spectrum trace (comma-separated power values)
- `MEAS:SPEC?` — Query number of traces in history
- `MEAS:CLEAR` — Clear all traces

### Configuration Commands
- `CONF:HIST <int>` — Set history depth (10-500, default 100)
- `CONF:HIST?` — Query history depth
- `CONF:FSTART <float>` — Set start frequency in MHz
- `CONF:FSTART?` — Query start frequency
- `CONF:FSTOP <float>` — Set stop frequency in MHz
- `CONF:FSTOP?` — Query stop frequency
- `CONF:PMIN <float>` — Set power minimum in dBm (default -100)
- `CONF:PMIN?` — Query power minimum
- `CONF:PMAX <float>` — Set power maximum in dBm (default -20)
- `CONF:PMAX?` — Query power maximum
- `CONF:TITLE <string>` — Set display title
- `CONF:TITLE?` — Query title

### MQTT Commands
- `MQTT:CONF <host>,<topic>` — Configure MQTT broker and subscription topic
- `MQTT:CONF?` — Query MQTT configuration

### Direct SCPI Examples

```bash
# Using netcat
echo "*IDN?" | nc localhost 5007
# N0GQ,Virtual-Waterfall,1.0,2026

echo "CONF:FSTART 144.0" | nc localhost 5007
echo "CONF:FSTOP 148.0" | nc localhost 5007
echo "CONF:PMIN -100" | nc localhost 5007
echo "CONF:PMAX -50" | nc localhost 5007
echo "CONF:TITLE 2m Band" | nc localhost 5007

# Add a 10-point spectrum
echo "MEAS:SPEC -80,-75,-70,-65,-60,-65,-70,-75,-80,-85" | nc localhost 5007

# Configure MQTT (backend subscribes automatically)
echo "MQTT:CONF mqtt.local,spectrum/rtlsdr" | nc localhost 5007
```

## Waterfall Display

The virtual waterfall shows:
- **Color-coded traces**: Blue (weak) → Green → Yellow → Red (strong)
- **Scrolling history**: New traces appear at top, scroll downward
- **Frequency axis**: X-axis labeled with frequency in MHz
- **Time axis**: Y-axis represents time (newest at top)
- **Power scale**: Color intensity maps to dBm (min to max range)
- **Title bar**: Display title above waterfall

## Error Handling

```python
from rf_bench.virtual import VirtualWaterfall, VirtualWaterfallError

try:
    waterfall = VirtualWaterfall("10.1.1.99")  # Wrong IP
except VirtualWaterfallError as e:
    print(f"Connection failed: {e}")

try:
    waterfall.set_history_depth(1000)  # Out of range
except ValueError as e:
    print(f"Invalid parameter: {e}")
```

## Requirements

- Python 3.7+
- No external dependencies (uses stdlib `socket`)

## Backend Server Requirements

The backend server requires:
- Python 3.7+
- FastAPI (`pip install fastapi`)
- uvicorn (`pip install uvicorn`)
- websockets (`pip install websockets`)
- paho-mqtt (`pip install paho-mqtt`)

## License

GPL-3.0-or-later — see LICENSE file in package root.

## See Also

- Backend server: `~/Dropbox/build/rf-bench/virtual/waterfall/`
- Other virtual instruments: `~/Dropbox/build/rf-bench/virtual/`
- RF Bench drivers: `~/Dropbox/build/rf-bench/drivers/`
- RTL-SDR driver: `rf-bench-drivers-rtlsdr`
- KiwiSDR driver: `rf-bench-drivers-kiwisdr`
- SunSDR driver: `rf-bench-drivers-sunsdr`
- Siglent SSA driver: `rf-bench-drivers-siglent`
