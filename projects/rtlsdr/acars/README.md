# rf-bench-rtlsdr-acars

**GitHub:** https://github.com/jfrancis42/rf-bench-rtlsdr-acars

ACARS (Aircraft Communications Addressing and Reporting System) decoder. Monitors
multiple VHF frequencies simultaneously using an RTL-SDR and acarsdec. Logs
flight ID, tail number, label type, and message text to SQLite. Serves live JSON
over HTTP.

## Hardware

| Component | Notes |
|-----------|-------|
| RTL-SDR Blog v4 | Any RTL2832U dongle works |
| VHF antenna | Discone or whip covering 129–132 MHz |

## System dependencies

```bash
yay -S acarsdec-git
```

## Usage

```bash
# Monitor 5 common North American ACARS frequencies
python acars.py

# Custom frequency list
python acars.py --freqs 131.550 131.525 131.725 130.025

# Dump to console only (no DB)
python acars.py --dump-only

# Filter to position/fuel message labels only
python acars.py --filter H1,S1,S2,30

# Skip empty/ACK messages
python acars.py --no-empty

# If your dongle has a frequency offset
python acars.py --ppm -5
```

## HTTP API

| Endpoint | Description |
|----------|-------------|
| `GET /messages` | Last 500 decoded messages (newest last) |
| `GET /flight/{id}` | Messages for a specific flight |
| `GET /tail/{reg}` | Messages for a tail number |
| `GET /status` | Message count and health |

## Default frequencies (North America)

| Frequency | Usage |
|-----------|-------|
| 131.550 MHz | Primary US/Canada ACARS |
| 131.525 MHz | Secondary |
| 131.725 MHz | North America backup |
| 130.025 MHz | Additional |
| 129.125 MHz | Additional |

## Common ACARS labels

| Label | Meaning |
|-------|---------|
| H1 | Position report / ADS-C |
| S1/S2 | Fuel and weights |
| Q0/QD | Acknowledgement |
| _d | Empty (keep-alive) |
| 10/12 | Weather / ATIS |
| 20/21 | D-ATIS (digital ATIS) |
| B1/B6 | ATC datalink uplink/downlink |
| F3 | Engine data |

## Reception tips

- Near a major airport: JFK, LGA, EWR, ORD, LAX, ATL all have dense ACARS traffic
- Antenna at 130 MHz: ~56 cm quarter-wave vertical
- A discone or wideband whip works well; co-linear gives more range
- acarsdec decodes up to 8 channels simultaneously within its tuning bandwidth
