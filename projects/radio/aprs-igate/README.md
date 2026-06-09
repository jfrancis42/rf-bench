# aprs-igate

APRS receive igate using the **Icom IC-9700** USB audio output and
**direwolf** as the AX.25 soft-TNC.

The IC-9700 presents as a USB audio device on Linux (48 kHz sample rate).
direwolf handles AFSK 1200 baud demodulation and AX.25 frame assembly.
This script reads direwolf's decoded packet output, logs to SQLite, optionally
enriches callsigns via the local govt-data API, and optionally gates packets
to APRS-IS.

## Hardware required

- Icom IC-9700 with USB cable connected
- IC-9700 menu: **SET → Connectors → USB AF SQL** = Unlink from SQL,
  **USB AF Output** = AF (or AF/SQL as preferred)
- 144.390 MHz FM receive (set manually or via `--set-freq`)

## System requirements

```bash
# Install direwolf:
sudo pacman -S direwolf          # Arch
sudo apt install direwolf         # Debian/Ubuntu

# Find the IC-9700 audio device:
arecord -l
# Look for something like "IC-9700" or card index number
```

## Setup

```bash
pip install rf-bench-drivers-icom

# Optional: start rigctld for CAT frequency control:
rigctld -m 3081 -r /dev/ttyUSB0 -s 115200 &
```

## Usage

```bash
# Monitor only, auto-detect audio device:
python aprs_igate.py

# Specify IC-9700 audio device explicitly:
python aprs_igate.py --audio-dev "plughw:2,0"

# Set IC-9700 to APRS frequency via CAT, then monitor:
python aprs_igate.py --set-freq

# Monitor + enrich callsigns via govt-data:
python aprs_igate.py --enrich

# Full igate: monitor + enrich + gate to APRS-IS:
python aprs_igate.py --enrich --gate --callsign N0GQ-10 --passcode 12345

# Custom APRS frequency (e.g. 144.390 is default, 144.800 for EU):
python aprs_igate.py --freq 144800
```

## Finding the IC-9700 audio device

```bash
arecord -l
# card 2: IC9700 [IC-9700], device 0: USB Audio [USB Audio]
# → use: --audio-dev plughw:2,0  or  --audio-dev plughw:IC-9700,0
```

## Output

SQLite database `aprs_igate_<timestamp>.db`:

| Column | Description |
|--------|-------------|
| `ts_utc` | UTC timestamp |
| `callsign` | Originating station callsign |
| `path` | Digipeater path |
| `info` | APRS information field |
| `lat` / `lon` | Decoded position (if present) |
| `fcc_name` | Licensee name from FCC database |
| `fcc_class` | License class |
| `gated` | 1 if gated to APRS-IS |

## APRS-IS gating note

To gate to APRS-IS, you need your callsign's APRS-IS passcode.
Generate it at: http://www.aprs-is.net/Connecting.aspx

Only gate packets that were received locally (first-hop, no TCPIP in path).
This script gates all received packets — add path filtering for a production igate.

## Comparison with rf-bench APRS server

The `~/Dropbox/build/aprs-server/` project connects to APRS-IS and bridges
internet-sourced packets to mobile clients.  This project receives directly
from RF via the IC-9700 — it hears only what is locally audible.  Running both
simultaneously shows which local stations are not being gated to the internet.
