# tci-sipphone

A SIP softphone that bridges a **SunSDR2 Pro** (or any ExpertSDR3-based radio) to a
**FreePBX / Asterisk** PBX extension.  Dial the extension from any phone on the PBX
to hear the radio receiver audio in real time.  Caller audio can optionally be
transmitted via the radio using VOX-gated PTT.

## Features

- Registers as a standard SIP extension — no PBX configuration beyond creating an extension
- Streams demodulated radio audio to the caller as G.711 µ-law RTP (8 kHz, PCMU)
- VOX-gated transmit: caller speech above a configurable threshold keys the radio PTT
- Jitter buffer with 60 ms pre-fill absorbs WebSocket delivery irregularities
- AGC normalises audio level for clean µ-law encoding regardless of signal strength
- Clock drift correction keeps the buffer stable over long calls
- Pure Python — no native audio libraries required

## Requirements

- Python 3.8+
- ExpertSDR3 running with TCI enabled (Settings → TCI → Enable)
- FreePBX or Asterisk with a SIP extension and UDP 5060 accessible

```
pip install websocket-client numpy
```

## Usage

```
tci-sipphone.py --tci-host HOST --sip-server HOST --sip-user EXT --sip-password PASS [options]
```

### Required arguments

| Argument | Description |
|----------|-------------|
| `--tci-host HOST` | ExpertSDR3 IP address or hostname |
| `--sip-server HOST` | FreePBX / Asterisk IP address or hostname |
| `--sip-user EXT` | SIP extension number to register as |
| `--sip-password PASS` | SIP extension password |

### Optional arguments

| Argument | Default | Description |
|----------|---------|-------------|
| `--tci-port PORT` | 50001 | TCI WebSocket port |
| `--tci-trx N` | 0 | TCI transceiver index (0 = TRX 0) |
| `--sip-port PORT` | 5060 | FreePBX SIP port |
| `--local-ip IP` | auto-detected | Local IP address for SIP/RTP |
| `--rx-only` | off | Disable caller-to-radio transmit path |
| `--vox-threshold LEVEL` | 0.02 | VOX RMS trigger level (0.0 – 1.0) |

### Example

```bash
python3 tci-sipphone.py \
    --tci-host 192.168.1.50 \
    --sip-server 192.168.1.10 \
    --sip-user 701 \
    --sip-password s3cr3t \
    --tci-trx 0
```

Dial extension 701 from any PBX phone to hear TRX 0.  Speak into the phone to
transmit (VOX-gated); hang up to end the session.

For receive-only monitoring (no transmit):

```bash
python3 tci-sipphone.py --tci-host 192.168.1.50 --sip-server 192.168.1.10 \
    --sip-user 701 --sip-password s3cr3t --rx-only
```

## FreePBX / Asterisk setup

1. **Create an extension** in FreePBX (Admin → Extensions → Add Extension).
   - Technology: Chan SIP or PJSIP
   - Extension number: e.g. `701`
   - Display name: e.g. `Radio`
   - Set a secret/password
2. **Check firewall**: UDP port 5060 (SIP) and the RTP port range (typically
   10000–20000) must be reachable from the machine running tci-sipphone.
3. Run tci-sipphone.  The console will print `Registered: sip:701@<server>` when
   the PBX accepts the registration.
4. Dial `701` from any extension.

No inbound route or trunk configuration is needed — calls to the extension go
directly to tci-sipphone.

## Audio pipeline

```
ExpertSDR3 (TCI WebSocket)
        │
        │  RX_AUDIO frames (int16, 8 kHz)
        ▼
    _rx_buf  ──[jitter buffer + AGC]──►  RTP/PCMU UDP  ──►  SIP phone (caller)

SIP phone (caller)
        │
        │  RTP/PCMU UDP
        ▼
    VOX gate  ──[PTT on/off]──►  TCI TX_AUDIO  ──►  ExpertSDR3
```

The jitter buffer pre-fills to 60 ms before sending the first RTP packet.  This
absorbs the bursty delivery of WebSocket frames, which is the primary cause of
buzz and clicking in a naive implementation.  Genuine underruns (network hiccup,
TCI pause) fall back to -50 dBFS comfort noise rather than hard silence, which
blends much more smoothly.

## PTT / VOX behaviour

- PTT asserts after **5 consecutive** RTP frames above `--vox-threshold` (~100 ms)
- PTT releases after **20 consecutive** frames below threshold (~400 ms)
- The radio is keyed via `TRX:N,true,tci` and unkeyed via `TRX:N,false`
- If another controller (CAT, front panel) keys the radio, tci-sipphone
  re-asserts the TCI audio source so its TX audio is not displaced
- Use `--rx-only` to disable the TX path entirely when transmit is not wanted

## Limitations

- Outbound calls (dialling out from the radio side) are not supported
- Only G.711 µ-law (PCMU, payload type 0) is negotiated — no G.722 or Opus
- No RTCP, no hold/re-INVITE, no DTMF relay
- One active call at a time; a second INVITE receives 486 Busy
- IPv4 only

## Dependencies

- [`websocket-client`](https://pypi.org/project/websocket-client/) — TCI WebSocket connection
- [`numpy`](https://pypi.org/project/numpy/) — audio processing and G.711 codec

No native audio libraries (PortAudio, PulseAudio, ALSA) are required.  The script
runs headless and is suitable for deployment as a systemd service.

## Running as a systemd service

```ini
[Unit]
Description=TCI SIP Phone Bridge
After=network.target

[Service]
ExecStart=/usr/bin/python3 /opt/tci-sipphone/tci-sipphone.py \
    --tci-host 192.168.1.50 \
    --sip-server 192.168.1.10 \
    --sip-user 701 \
    --sip-password s3cr3t
Restart=on-failure
RestartSec=10

[Install]
WantedBy=multi-user.target
```

## License

MIT
