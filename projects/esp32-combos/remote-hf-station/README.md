# ESP32+IC-7300 Remote HF Station

Complete remote HF station control combining ESP32 SCPI controllers with IC-7300 radio control via Hamlib.

**Status:** 🔨 (In development)

## Features

- **Radio Control**: IC-7300 frequency/mode via Hamlib rigctld
- **Antenna Rotator**: ESP32 SCPI controller (azimuth/elevation)
- **PTT Control**: ESP32 SCPI PTT controller
- **SWR Monitoring**: Real-time SWR via ESP32 SCPI meter + WebSocket
- **QSO Logging**: SQLite database with freq, mode, SWR, notes
- **Web UI**: Browser-based control panel
- **CLI Interface**: Scriptable command-line tools for automation

## Hardware Requirements

1. **IC-7300 HF Transceiver** — USB to Linux host running rigctld
2. **ESP32 Rotator Controller** — Controls antenna azimuth/elevation
3. **ESP32 PTT Controller** — Handles transmit keying
4. **ESP32 SWR Meter** — Monitors forward/reflected power, computes SWR
5. **Antenna Rotator** — DC motor rotator with position sensors
6. **SWR Bridge** — Directional coupler at antenna feedpoint

### ESP32 Firmware

Each ESP32 runs the SCPI server firmware:
- **scpi-rotator**: `~/Dropbox/build/rf-bench/projects/esp32-combos/scpi-rotator/`
- **scpi-ptt**: `~/Dropbox/build/rf-bench/projects/esp32-combos/scpi-ptt/`
- **scpi-swr**: `~/Dropbox/build/rf-bench/projects/esp32-combos/scpi-swr/`

Flash each ESP32 with the appropriate firmware before connecting.

## Software Installation

### Python Dependencies

```bash
pip install rf-bench-drivers-icom flask flask-sock pyvisa pyvisa-py
```

### Start rigctld

IC-7300 must be controlled via Hamlib rigctld:

```bash
# USB connection
rigctld -m 3073 -r /dev/ttyUSB0 -s 115200

# Or network connection to rigctld on another host
rigctld -m 3073 -r /dev/ttyUSB0 -s 115200 -T 0.0.0.0 -t 4532
```

## Usage

### Web UI

Start the Flask server:

```bash
python3 remote_station.py \
    --rotator-ip 192.168.1.100 \
    --ptt-ip 192.168.1.101 \
    --swr-ip 192.168.1.102
```

Open browser to `http://localhost:5000`:

```
┌────────────────────────────────────────────────┐
│   🛰️  Remote HF Station Control               │
├────────────────────────────────────────────────┤
│                                                │
│  📻 Radio Control (IC-7300)                    │
│  ┌──────────────────────────────────────────┐ │
│  │ Frequency (kHz): [14074    ] [Set]      │ │
│  │ Mode: [USB ▼]                [Set]      │ │
│  │                                          │ │
│  │ Status: Freq: 14074 kHz | Mode: USB     │ │
│  └──────────────────────────────────────────┘ │
│                                                │
│  🎯 Antenna Rotator                            │
│  ┌──────────────────────────────────────────┐ │
│  │ Azimuth:  [━━━━━━━━━━━━━━━━━] 90°  [Set]│ │
│  │ Elevation:[━━━━━━━━━━━━━━━━━] 15°  [Set]│ │
│  │                          [Aim Antenna]   │ │
│  │ Status: Az: 90° | El: 15°                │ │
│  └──────────────────────────────────────────┘ │
│                                                │
│  🔴 PTT Control                                │
│  ┌──────────────────────────────────────────┐ │
│  │        [    TRANSMIT    ]                │ │
│  │                                          │ │
│  │ PTT: OFF                                 │ │
│  └──────────────────────────────────────────┘ │
│                                                │
│  📊 SWR Meter                                  │
│  ┌──────────────────────────────────────────┐ │
│  │                                          │ │
│  │              1.23                        │ │
│  │                                          │ │
│  │ WebSocket: Connected                     │ │
│  └──────────────────────────────────────────┘ │
│                                                │
│  📝 Quick QSO Log                              │
│  ┌──────────────────────────────────────────┐ │
│  │ Notes: [W1ABC 599 CO     ] [Log QSO]    │ │
│  │ Ready to log                             │ │
│  └──────────────────────────────────────────┘ │
└────────────────────────────────────────────────┘
```

**SWR Display Colors:**
- **Green** (< 2.0): Good match
- **Orange** (2.0-3.0): Acceptable
- **Red** (> 3.0): Poor match, reduce power

### CLI Interface

For scripting and automation:

```bash
# Set frequency and mode
./station_cli.py set-freq 14074
./station_cli.py set-mode USB

# Aim antenna at Europe (from Colorado)
./station_cli.py aim-antenna --azimuth 45 --elevation 10

# Check SWR before transmitting
./station_cli.py read-swr

# Key PTT for 5 seconds
./station_cli.py key-ptt --duration 5

# Get complete station status
./station_cli.py status
```

**Custom IP addresses:**

```bash
./station_cli.py \
    --rotator-ip 10.1.0.50 \
    --ptt-ip 10.1.0.51 \
    --swr-ip 10.1.0.52 \
    status
```

### Example: Automated Contest Script

```bash
#!/bin/bash
# contest_cq.sh — Automated CQ beacon on multiple bands

BANDS=(14074 7074 3573)

while true; do
    for freq in "${BANDS[@]}"; do
        echo "CQ on $freq kHz..."
        ./station_cli.py set-freq $freq
        sleep 2

        # Check SWR
        swr=$(./station_cli.py read-swr)
        if (( $(echo "$swr > 3.0" | bc -l) )); then
            echo "⚠️  High SWR ($swr), skipping transmit"
            continue
        fi

        # Transmit CQ
        ./station_cli.py key-ptt --duration 10
        sleep 30  # Listen
    done
done
```

### Example: Satellite Tracking

```bash
#!/bin/bash
# track_satellite.sh — Point antenna at ISS

# Get ISS position from tracking API
response=$(curl -s "https://api.open-notify.org/iss-now.json")
lat=$(echo $response | jq -r '.iss_position.latitude')
lon=$(echo $response | jq -r '.iss_position.longitude')

# Convert to azimuth/elevation (requires external tool)
# This is a placeholder — real implementation needs PyEphem or similar
azimuth=$(calculate_azimuth $lat $lon)
elevation=$(calculate_elevation $lat $lon)

# Aim antenna
./station_cli.py aim-antenna --azimuth $azimuth --elevation $elevation
echo "Tracking ISS: Az=$azimuth° El=$elevation°"
```

## QSO Log Database

QSOs are logged to `qso_log.db` (SQLite):

```sql
sqlite3 qso_log.db "SELECT * FROM qsos ORDER BY timestamp DESC LIMIT 5"
```

**Schema:**

```sql
CREATE TABLE qsos (
    id INTEGER PRIMARY KEY,
    timestamp TEXT NOT NULL,     -- ISO 8601 UTC
    frequency_khz INTEGER NOT NULL,
    mode TEXT NOT NULL,
    swr REAL,                    -- SWR at time of QSO
    notes TEXT                   -- Callsign, report, etc.
);
```

## Remote Access

### SSH Tunnel

For secure remote access over the internet:

```bash
# From remote location, tunnel to home server
ssh -L 5000:localhost:5000 -L 4532:localhost:4532 home.example.com

# Open browser to http://localhost:5000
```

### VPN Access

If both locations are on the same VPN (e.g., WireGuard via `~/skynet/`):

```bash
# Run server on home network
python3 remote_station.py --host 0.0.0.0

# Access from anywhere on VPN
# Browser: http://10.1.0.20:5000
```

## API Reference

### REST Endpoints

**Radio Control:**
- `POST /api/radio/frequency` — `{"frequency_khz": 14074}`
- `POST /api/radio/mode` — `{"mode": "USB"}`
- `GET /api/radio/status` — Returns current freq/mode

**Rotator Control:**
- `POST /api/rotator/azimuth` — `{"azimuth": 90}`
- `POST /api/rotator/elevation` — `{"elevation": 15}`
- `POST /api/rotator/aim` — `{"azimuth": 90, "elevation": 15}`
- `GET /api/rotator/position` — Returns current az/el

**PTT Control:**
- `POST /api/ptt` — `{"state": true}` or `{"state": false}`

**Logging:**
- `POST /api/log/qso` — `{"frequency_khz": 14074, "mode": "USB", "swr": 1.5, "notes": "W1ABC 599"}`

### WebSocket

**SWR Monitoring:**
- `ws://localhost:5000/ws/swr` — Receives JSON: `{"swr": 1.23}` every 0.5 seconds

## Security Considerations

**WARNING:** v1 has **no authentication** — anyone on the network can control your station!

**For production use:**
1. Run behind SSH tunnel or VPN only
2. Add HTTP Basic Auth to Flask app
3. Use HTTPS with Let's Encrypt certificate
4. Implement rate limiting to prevent abuse
5. Add emergency stop button in web UI

**Never expose directly to the internet without authentication.**

## Troubleshooting

### "Connection refused" to rigctld

```bash
# Check rigctld is running
ps aux | grep rigctld

# Test connection
telnet localhost 4532
# Type: \get_freq
```

### ESP32 not responding

```bash
# Ping the ESP32
ping 192.168.1.100

# Test SCPI command
echo "*IDN?" | nc 192.168.1.100 5025
```

### High SWR readings

1. Check antenna connections
2. Verify SWR meter calibration
3. Test with dummy load (should read 1.0:1)
4. Check for water in coax connectors

### Web UI not updating SWR

1. Check browser console for WebSocket errors
2. Verify ESP32 SWR meter is responding: `./station_cli.py read-swr`
3. Restart Flask server

## Integration with Contest Logging

The CLI can be called from contest logging software:

**N1MM+ (Windows/Wine):**
```bash
# External program hook
./station_cli.py set-freq %FREQ%
./station_cli.py set-mode %MODE%
```

**CQRLOG (Linux):**
```bash
# QSO after-log command
./station_cli.py log-qso --freq $FREQ --mode $MODE --notes "$CALL $RST"
```

## Future Enhancements

- [ ] Audio streaming from IC-7300 via WebRTC
- [ ] Waterfall display in web UI
- [ ] Automatic band changes based on propagation
- [ ] Integration with PSKReporter for live spot map
- [ ] Voice keyer with audio file upload
- [ ] Multi-user support with permission levels
- [ ] Mobile app (Android/iOS)
- [ ] Integration with WSJT-X/FT8/JS8Call
- [ ] Antenna pattern overlay on rotator control
- [ ] Weather station integration (wind affects antennas)

## Related Projects

- **scpi-rotator**: ESP32 antenna rotator controller
- **scpi-ptt**: ESP32 PTT controller
- **scpi-swr**: ESP32 SWR meter
- **rf-bench drivers**: IC-7300 Python driver

## License

MIT
