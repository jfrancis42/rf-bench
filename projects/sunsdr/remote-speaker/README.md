# TCI Remote Speaker

Browser-based audio receiver for ExpertSDR3 / SunSDR2 Pro.

Connects directly to ExpertSDR3's TCI WebSocket interface, subscribes to the
demodulated audio stream, and plays it in real time through the browser's Web
Audio API.  No server required — open `remote_speaker.html` straight from disk.

## Features

- Single self-contained HTML file — no build step, no dependencies
- Displays current frequency (kHz) and mode from live TCI state events
- Volume control with immediate effect
- Start/Stop button; inputs lock while connected
- Auto-reconnects on disconnect with exponential back-off (3 s → 30 s)
- Python WebSocket proxy included for cases where a direct browser connection
  is blocked

## Quick start

### Direct (no server needed)

Open `remote_speaker.html` in Chrome or Firefox.

1. Set **Host** to the IP of the machine running ExpertSDR3
2. Set **Port** (default 50001) and **TRX** (0 or 1)
3. Click **Connect & Play**

WebSocket connections from `file://` pages are not subject to same-origin
restrictions, so this works without a server in most browsers.

### Via proxy

Use the proxy when direct connection is blocked, or to serve the page to other
machines on the LAN.

```
pip install -r requirements.txt
python proxy.py --tci-host 192.168.1.x
```

Open `http://localhost:8080/` and set **Host=localhost**, **Port=8080**.

```
python proxy.py --help

optional arguments:
  --tci-host  ExpertSDR3 host IP or hostname  (required)
  --tci-port  TCI WebSocket port              (default: 50001)
  --port      Local proxy port                (default: 8080)
  --host      Local bind address              (default: 127.0.0.1)
              use 0.0.0.0 to expose on the LAN
```

## Requirements

**HTML page:** none — pure JavaScript, Web Audio API, standard WebSocket.

**Proxy:** Python 3.9+, `aiohttp >= 3.9`

```
pip install -r requirements.txt
```

## TCI prerequisites

ExpertSDR3 must be running with TCI enabled:
**Settings → TCI → Enable** (port 50001 by default).

The SunSDR2 Pro hardware is accessed through ExpertSDR3, not directly.

## Protocol

Implements **TCI v2.0** (Expert Electronics, January 2024).

Before starting audio the page sends:
```
AUDIO_SAMPLERATE:8000;
AUDIO_STREAM_SAMPLE_TYPE:int16;
AUDIO_STREAM_CHANNELS:1;
AUDIO_START:0;
```

Binary audio frames have a 40-byte header (Stream struct, all uint32_t LE).
`sample_rate`, `format`, `length`, and `channels` are read from each frame
header, so the decoder adapts automatically to whatever the server actually
sends. Stereo frames are mixed down to mono.

## Troubleshooting

### Connected but no audio

1. Open browser developer tools (F12 → Console) and check for errors.
2. Confirm ExpertSDR3's TCI is enabled and the port matches.
3. The log shows the exact commands sent — verify `AUDIO_START` was issued.
4. If the server sends INT24 format (unusual), change `REQ_FORMAT = 'int32'`
   or `'float32'` at the top of the script block.

### Browser console

Open the browser developer tools (F12 → Console) to see connection events and
any JavaScript errors.

### file:// blocked by browser

Some browsers or OS-level security policies block `ws://` connections to
non-localhost addresses from `file://` pages.  Use the proxy in that case.

## Hardware

[SunSDR2 Pro](https://eesdr.com/) by Expert Electronics, connected via
Ethernet to a PC running ExpertSDR3 (v3.x).

| Range | Coverage |
|-------|----------|
| 0.1 – 55 MHz | HF + 6 m (RX + TX) |
| 100 – 150 MHz | VHF, covers 2 m (RX only) |

## Part of rf-bench

This project is part of the
[rf-bench](https://github.com/jfrancis42/rf-bench) monorepo — a collection
of Python drivers and measurement projects for bench instrument automation and
RF testing.

The SunSDR2 Pro driver (`rf_bench.sunsdr`) lives in `drivers/sunsdr/` and
provides Python access to the same TCI interface used here.

## License

GPL-3.0-or-later
