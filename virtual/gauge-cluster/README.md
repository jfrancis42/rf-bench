# Virtual Gauge Cluster

✅ **Status: Tested 2026-06-14** — SCPI commands, WebSocket updates, 2-gauge and 4-gauge layouts, needle physics verified

SCPI-controlled multi-meter gauge cluster with realistic needle physics. Supports 2-gauge or 4-gauge layouts for dashboard-style instrument panels.

## Features

- **SCPI TCP server** on port 5009 (IEEE 488.2 standard)
- **WebSocket real-time updates** for instant value changes
- **Realistic needle physics** with spring-damper model (overshoot and settling)
- **Flexible layouts:** 2 gauges (side-by-side) or 4 gauges (2×2 grid)
- **Independent configuration** per gauge (range, units, zones, labels)
- **Colored zone arcs** for visual status indication

## Ports

- **SCPI:** `tcp://0.0.0.0:5009`
- **HTTP:** `http://0.0.0.0:8009`
- **WebSocket:** `ws://0.0.0.0:8009/ws`
- **MQTT:** Configurable via `MQTT:CONF` command

## SCPI Commands

### Measurement (per gauge)
- `MEAS:VAL1 <float>` — Set gauge 1 value
- `MEAS:VAL2 <float>` — Set gauge 2 value
- `MEAS:VAL3 <float>` — Set gauge 3 value (4-gauge layout only)
- `MEAS:VAL4 <float>` — Set gauge 4 value (4-gauge layout only)
- `MEAS:VAL[1-4]?` — Query gauge value

### Configuration
- `CONF:LAYOUT <2|4>` — Set 2-gauge or 4-gauge layout
- `CONF:LAYOUT?` — Query current layout
- `CONF:LABEL1 <string>` — Set gauge 1 label
- `CONF:UNIT1 <string>` — Set gauge 1 units
- `CONF:MIN1 <float>` — Set gauge 1 minimum scale value
- `CONF:MAX1 <float>` — Set gauge 1 maximum scale value
- `CONF:ZONE1 <id>,<v0>,<v1>,<color>` — Define colored zone for gauge 1

*(Replace `1` with `2`, `3`, or `4` for other gauges)*

### IEEE 488.2 Standard
- `*IDN?` — Identification query
- `*RST` — Reset to defaults
- `SYST:ERR?` — Query error queue

### MQTT
- `MQTT:CONF <host>,<topic1>,<topic2>[,<topic3>,<topic4>]` — Configure MQTT topics
- `MQTT:CONF?` — Query MQTT configuration

## Quick Start

```bash
# Start the server
cd ~/Dropbox/build/rf-bench/virtual/gauge-cluster/backend
python3 server.py

# Open in browser
xdg-open http://localhost:8009

# Configure 2-gauge layout (voltage and current)
echo "CONF:LAYOUT 2" | nc localhost 5009
echo "CONF:LABEL1 Voltage" | nc localhost 5009
echo "CONF:UNIT1 V" | nc localhost 5009
echo "CONF:MIN1 0" | nc localhost 5009
echo "CONF:MAX1 15" | nc localhost 5009
echo "CONF:LABEL2 Current" | nc localhost 5009
echo "CONF:UNIT2 A" | nc localhost 5009
echo "CONF:MIN2 0" | nc localhost 5009
echo "CONF:MAX2 20" | nc localhost 5009

# Send values
echo "MEAS:VAL1 13.8" | nc localhost 5009
echo "MEAS:VAL2 8.5" | nc localhost 5009
```

## Gauge Physics

Each gauge uses a spring-damper second-order system for realistic needle motion:
- Spring constant: 355
- Damping coefficient: 23
- Creates natural overshoot and settling behavior like real analog meters

## Integration Examples

### Power supply monitor (2-gauge)
```python
from rf_bench.siglent import SPD3303X
import socket, time

psu = SPD3303X('10.1.1.56')
sock = socket.socket()
sock.connect(('localhost', 5009))

# Configure gauges
sock.sendall(b'CONF:LAYOUT 2\n')
sock.sendall(b'CONF:LABEL1 CH1 Voltage\n')
sock.sendall(b'CONF:UNIT1 V\n')
sock.sendall(b'CONF:MIN1 0\n')
sock.sendall(b'CONF:MAX1 32\n')
sock.sendall(b'CONF:LABEL2 CH1 Current\n')
sock.sendall(b'CONF:UNIT2 A\n')
sock.sendall(b'CONF:MIN2 0\n')
sock.sendall(b'CONF:MAX2 3.2\n')

while True:
    voltage = psu.measure_voltage(1)
    current = psu.measure_current(1)
    sock.sendall(f'MEAS:VAL1 {voltage}\n'.encode())
    sock.sendall(f'MEAS:VAL2 {current}\n'.encode())
    time.sleep(0.2)
```

### Radio panel (4-gauge)
```python
from rf_bench.icom import IC7300
import socket, time

radio = IC7300()
sock = socket.socket()
sock.connect(('localhost', 5009))

# Configure 4-gauge cluster
sock.sendall(b'CONF:LAYOUT 4\n')
sock.sendall(b'CONF:LABEL1 S-Meter\n')
sock.sendall(b'CONF:UNIT1 S\n')
sock.sendall(b'CONF:MIN1 0\n')
sock.sendall(b'CONF:MAX1 9\n')
sock.sendall(b'CONF:LABEL2 Power\n')
sock.sendall(b'CONF:UNIT2 W\n')
sock.sendall(b'CONF:MIN2 0\n')
sock.sendall(b'CONF:MAX2 100\n')
sock.sendall(b'CONF:LABEL3 SWR\n')
sock.sendall(b'CONF:UNIT3 :1\n')
sock.sendall(b'CONF:MIN3 1\n')
sock.sendall(b'CONF:MAX3 3\n')
sock.sendall(b'CONF:LABEL4 ALC\n')
sock.sendall(b'CONF:UNIT4 %\n')
sock.sendall(b'CONF:MIN4 0\n')
sock.sendall(b'CONF:MAX4 100\n')

while True:
    # Read radio parameters (example - actual API varies)
    s_meter = radio.get_strength()
    # power = radio.get_tx_power()  # Example
    # swr = radio.get_swr()         # Example
    # alc = radio.get_alc()         # Example
    
    sock.sendall(f'MEAS:VAL1 {s_meter}\n'.encode())
    # sock.sendall(f'MEAS:VAL2 {power}\n'.encode())
    # sock.sendall(f'MEAS:VAL3 {swr}\n'.encode())
    # sock.sendall(f'MEAS:VAL4 {alc}\n'.encode())
    time.sleep(0.1)
```

### MQTT Integration
```bash
# Configure MQTT for 4 gauges
echo "MQTT:CONF localhost,gauge/1,gauge/2,gauge/3,gauge/4" | nc localhost 5009

# Publish values from elsewhere
mosquitto_pub -h localhost -t gauge/1 -m 13.8
mosquitto_pub -h localhost -t gauge/2 -m 5.2
```

## Use Cases

- Power supply monitoring (V/A/W)
- Radio transmitter panels (power/SWR/ALC/temp)
- Test equipment dashboards
- Vehicle instrument clusters
- Environmental monitoring (temp/humidity/pressure/wind)
- Process control displays
- Multi-parameter sensor displays

## Files

```
gauge-cluster/
├── backend/
│   └── server.py          # FastAPI SCPI + WebSocket server
├── frontend/
│   └── index.html         # Canvas gauge cluster with physics
└── README.md              # This file
```

## See Also

- [PORT-ASSIGNMENTS.md](../PORT-ASSIGNMENTS.md) — Port allocations for all instruments
- [BUILDING-STATUS.md](../BUILDING-STATUS.md) — Phase 1 completion status
- [analog-meter](../analog-meter/) — Single analog meter gauge
- [compass](../compass/) — Directional compass display
