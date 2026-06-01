# rf-bench-rtlsdr-ais

**GitHub:** https://github.com/jfrancis42/rf-bench-rtlsdr-ais

AIS (Automatic Identification System) vessel receiver. Decodes both AIS channels
simultaneously (161.975 MHz and 162.025 MHz) using an RTL-SDR dongle and rtl_ais.
Tracks vessel positions, names, callsigns, ship types, and dimensions. Logs to
SQLite and serves live JSON over HTTP.

## Hardware

| Component | Notes |
|-----------|-------|
| RTL-SDR Blog v4 | Any RTL2832U dongle works |
| VHF antenna | Marine band whip or discone; 162 MHz |

## System dependencies

```bash
# Build rtl_ais from source (not in AUR as of 2026-06)
git clone --depth=1 https://github.com/dgiardini/rtl-ais
cd rtl-ais && make && sudo cp rtl_ais /usr/local/bin/
```

## Python dependencies

```bash
pip install pyais
```

## Usage

```bash
# Run with HTTP API on port 8092 and SQLite log
python ais.py

# Dump decoded messages to stdout only
python ais.py --dump-only

# Custom gain and CSV output
python ais.py --gain 40 --csv positions.csv

# If your dongle has a frequency offset
python ais.py --ppm -5
```

## HTTP API

| Endpoint | Description |
|----------|-------------|
| `GET /vessels` | All tracked vessels (sorted by last seen) |
| `GET /vessel/{mmsi}` | Single vessel by MMSI |
| `GET /status` | Vessel count and health |

## AIS channels

| Channel | Frequency | ITU name |
|---------|-----------|----------|
| AIS 1   | 161.975 MHz | VHF ch 87B |
| AIS 2   | 162.025 MHz | VHF ch 88B |

Both channels are received simultaneously; rtl_ais centers between them and
demodulates each in software.

## Message types decoded

| Type | Description |
|------|-------------|
| 1/2/3 | Class A position report (commercial vessels) |
| 5 | Class A static and voyage data (name, callsign, type, dimensions) |
| 18/19 | Class B position (recreational boats, small vessels) |
| 21 | Aid to navigation (buoys, beacons) |
| 24A/24B | Class B static data |

## SQLite schema

- **vessels**: MMSI, name, callsign, ship_type, IMO, dimensions, first/last seen
- **positions**: timestamp, MMSI, lat, lon, speed, heading, course, nav status, source (A/B)
