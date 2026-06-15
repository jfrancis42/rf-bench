# Virtual Rotary Knob

🔨 **Status: Built 2026-06-14** — Phase 2 interactive control (rotary knob with drag rotation)

SCPI-controlled rotary knob with **bidirectional** communication. Features continuous or stepped rotation, wrap-around support, and Canvas-based rendering. Perfect for frequency tuning, gain control, and other analog adjustments.

## Features

- **SCPI TCP server** on port 5103
- **Bidirectional WebSocket** for instant updates
- **Interactive Canvas knob** with drag-to-rotate
- **Continuous or stepped** values
- **Wrap-around option** (360° continuous rotation)
- **Configurable range**, step, labels, colors
- **MQTT bidirectional** (subscribe/publish)

## Ports

- **SCPI:** `tcp://0.0.0.0:5103`
- **HTTP:** `http://0.0.0.0:8103`
- **WebSocket:** `ws://0.0.0.0:8103/ws` (bidirectional)

## SCPI Commands

### Value Control
- `MEAS:VAL <float>` — Set knob value
- `MEAS:VAL?` — Query current value

### Configuration
- `CONF:MIN <float>` — Set minimum (default 0)
- `CONF:MAX <float>` — Set maximum (default 100)
- `CONF:STEP <float>` — Set step size (0=continuous, default 1)
- `CONF:WRAP <bool>` — Enable wrap-around (default 0)
- `CONF:LABEL <string>` — Set knob label
- `CONF:UNIT <string>` — Set display units
- `CONF:COL <color>` — Set pointer color (hex)
- `CONF:SIZE <int>` — Set size 100-250px (default 150)

### IEEE 488.2
- `*IDN?`, `*RST`, `SYST:ERR?`

### MQTT
- `MQTT:CONF <host>,<sub_topic>[,<pub_topic>]`

## Quick Start

```bash
cd ~/Dropbox/build/rf-bench/virtual/knob/backend
python3 server.py
xdg-open http://localhost:8103
```

## Use Cases

- **Frequency tuning** (VFO, sweep control)
- **Gain/volume control** (RF gain, audio volume)
- **Filter bandwidth** (RBW, IF bandwidth)
- **Attenuation** (variable attenuator)
- **Phase adjustment** (0-360°)
- **Motor speed** (RPM control)

## Files

```
knob/
├── backend/server.py
├── frontend/index.html
└── README.md
```

## See Also

- [slider](../slider/) — Linear control
- [toggle](../toggle/) — ON/OFF switch
- [button](../button/) — Momentary trigger
