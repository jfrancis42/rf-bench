# bubba-detector

RTL-SDR multi-band handheld radio activity scanner with two operating modes.

**Log mode** (default) — fast group-sweep across all active channels every ~1.1 seconds.
Detects signal energy above squelch, logs timestamped detections to SQLite, rolling
terminal display. No audio, no demodulation.

**Scan mode** — traditional sequential channel scanner. Hops through each channel,
stops when squelch opens, demodulates audio (**NFM or AM** depending on channel type)
for real-time playback, records each transmission as a timestamped MP3, and runs
**WebRTC VAD** on every recording to flag transmissions containing human voice — all
in real time with no separate post-processing step.

---

## Hardware required

- RTL-SDR Blog v4 or Nooelec NESDR SMArt v5 (both tested)
- Antenna: discone covers all bands; UHF whip for FRS/GMRS; VHF whip for Marine/MURS

---

## Frequency coverage

### Standard bands (always on unless `--no-X` is passed)

| Band | Count | Frequency range | Modulation |
|------|-------|----------------|------------|
| FRS CH 1–22 / GMRS | 30 | 462.55–467.73 MHz | NFM |
| MURS | 5 | 151.82–154.60 MHz | NFM |
| Business band VHF itinerant | 10 | 151.50–154.57 MHz | NFM |
| Marine VHF key channels | 18 | 156.05–157.40 MHz | NFM |
| NOAA weather | 7 | 162.40–162.55 MHz | NFM (excluded from scan by default) |
| Business band UHF itinerant | 4 | 451.80–467.94 MHz | NFM |

### Optional bands (off by default — add with flags)

| Flag | Band | Count | Frequency range | Modulation |
|------|------|-------|----------------|------------|
| `--airband` | Aviation VHF key channels | 17 | 118–136 MHz | **AM** |
| `--ham-vhf` | Amateur 2m FM simplex + APRS | 11 | 144.39–147.56 MHz | NFM |
| `--ham-uhf` | Amateur 70cm FM simplex | 8 | 445.93–446.50 MHz | NFM |

**Total: 110 channels, 18 scan groups** (with all optional bands enabled).

Aviation channels use **AM (amplitude modulation)**, not FM — the script automatically
selects the correct demodulator per channel.

---

## Aviation channels (`--airband`)

These are the key "universal" aviation channels monitored across the US.
ATC approach/tower/departure frequencies are locale-specific; add them to
`ALL_CHANNELS` in the script with `_air("My Tower 119.3", 119.3)`.

| Channel | Frequency | Notes |
|---------|-----------|-------|
| Guard 121.500 | 121.500 MHz | Emergency / Guard — all aircraft monitor |
| Guard 121.600 | 121.600 MHz | Ground control |
| Guard 121.700 | 121.700 MHz | Ground control |
| FSS 122.200 | 122.200 MHz | Flight service stations |
| UNICOM 122.700 | 122.700 MHz | Uncontrolled airports |
| UNICOM 122.800 | 122.800 MHz | Most common UNICOM |
| CTAF 122.900 | 122.900 MHz | CTAF / Multicom |
| SAR 123.025 | 123.025 MHz | Search and rescue primary |
| Helo 123.050 | 123.050 MHz | Helicopter operations |
| SAR 123.100 | 123.100 MHz | Search and rescue secondary |
| A-A 123.450 | 123.450 MHz | Air-to-air (general aviation) |
| FSS 126.700 | 126.700 MHz | Flight service stations |
| Center 127.500 | 127.500 MHz | En-route center (common) |
| ARINC 128.820 | 128.820 MHz | ARINC |

---

## Amateur radio channels

**2m FM (`--ham-vhf`):** national simplex calling (146.520 MHz), common simplex
frequencies, and APRS (144.390 MHz). Local repeater outputs vary by region — add yours
to `ALL_CHANNELS` with `_ham("W0XYZ RPT 147.180", 147.180, "Ham 2m")`.

**70cm FM (`--ham-uhf`):** national simplex calling (446.000 MHz) and surrounding
simplex channels. Local repeater outputs (typically 440–450 MHz) are not included
by default for the same reason.

---

## Setup

```bash
# Log mode only:
pip install rf-bench-drivers-rtlsdr numpy

# Scan mode (audio + MP3 + VAD):
pip install rf-bench-drivers-rtlsdr numpy sounddevice lameenc scipy webrtcvad
```

---

## Usage

### Log mode (default)

```bash
# All standard bands, squelch +10 dB above noise:
python bubba_detector.py

# With airband and ham added:
python bubba_detector.py --airband --ham-vhf --ham-uhf

# FRS/GMRS only, tighter squelch:
python bubba_detector.py --no-murs --no-marine --no-biz --squelch 15

# Reduce gain if strong local signals cause IMD:
python bubba_detector.py --gain 25 --squelch 20

# SMS alert on any activity:
python bubba_detector.py --alert
```

### Scan mode

```bash
# Full scanner — audio + MP3 + voice detection:
python bubba_detector.py --mode scan

# Aviation only (AM demodulation, voice detection):
python bubba_detector.py --mode scan --airband \
    --no-frs --no-murs --no-marine --no-biz

# Ham 2m + 70cm only:
python bubba_detector.py --mode scan --ham-vhf --ham-uhf \
    --no-frs --no-murs --no-marine --no-biz

# Silent recording only (no audio playback):
python bubba_detector.py --mode scan --no-audio

# Increase dwell time (hold 3s of silence before advancing):
python bubba_detector.py --mode scan --resume-delay 3

# Limit time on any one channel to 8 seconds:
python bubba_detector.py --mode scan --max-dwell 8

# Higher quality MP3:
python bubba_detector.py --mode scan --mp3-bitrate 48
```

### Utilities

```bash
python bubba_detector.py --list-channels      # full channel list with modulation type
python bubba_detector.py --no-color | tee log.txt
```

---

## Signal strength

Signal strength is reported in **dBFS** (decibels relative to full scale) — relative
and uncalibrated. Useful for comparing signals within a session.

If `~/.rtlsdr_vhf_cal.json` exists (from `projects/radio/rx-crosscheck/`), calibrated
dBm values are shown alongside.

Typical values (Nooelec SMArt v5, gain 40 dB):

| Signal | Measured dBFS | Excess above noise |
|--------|--------------|-------------------|
| Strong local NOAA (~70 km) | −17 to −22 | 51–57 dB |
| Adjacent channel bleedthrough | −55 to −62 | 15–23 dB |
| Noise floor | ~−77 | 0 dB |

---

## Voice Activity Detection (VAD)

Scan mode runs **WebRTC VAD** (Google's voice detector, designed for telephony and
radio) on every demodulated audio block in real time. No separate post-processing
step — the `has_voice` flag is set while the transmission is being recorded.

**How it works:**
1. Each audio block (13.6 ms) is downsampled 48 kHz → 16 kHz
2. Buffered into 30 ms frames
3. Each frame is classified as speech or non-speech by `webrtcvad.Vad(2)`
4. If any frame in the dwell period is classified as speech, `has_voice = 1`
5. `has_voice` is written to SQLite when the recording is saved

**Display:** Transmissions with detected voice show `🗣` in the terminal log.
Recordings show `⏺`.

**Query voice-only detections:**
```bash
sqlite3 bubba_*.db \
  "SELECT ts_utc, channel_name, signal_dbfs, recording_path
   FROM detections WHERE has_voice = 1 ORDER BY ts_unix;"
```

**Known limitation:** webrtcvad at aggressiveness 2 can flag strong radio-frequency
noise (squelch-open noise) as voice on weak or marginal signals. This is a general
limitation of energy-based VAD. Raise `--squelch` to ensure only real signals are
captured, which reduces spurious voice flags.

---

## Demodulation

| Channel type | Demodulator | Notes |
|-------------|-------------|-------|
| FRS, GMRS, MURS, Marine, business | **NFM** | Phase discriminator + 4 kHz LPF |
| Aviation (--airband) | **AM** | Envelope detection + DC removal + 4 kHz LPF |
| Ham 2m / 70cm | **NFM** | Same as FRS/GMRS |

The demodulator is selected automatically per channel via the `modulation` field.

**NFM pipeline:**
1. `np.angle(iq[1:] * conj(iq[:-1]))` — instantaneous phase difference
2. Stateful Butterworth LPF at 4 kHz (state maintained across blocks → no clicks)
3. Decimate 50× (2.4 MHz → 48 kHz)

**AM pipeline:**
1. `abs(iq)` — envelope detection
2. Subtract mean (removes carrier DC offset)
3. Same LPF + decimate as NFM

---

## Output

### Terminal — scan mode
```
  ▶ Guard 121.500 [AM]         121.5000 MHz   -58.2 dBFS   (dwelt)

  [14:23:01] Guard 121.500 [AM]      121.5000 MHz  -58.2 dBFS  ████████░░  🗣  ⏺
  [14:23:44] FRS CH 1 / GMRS CH 1   462.5625 MHz  -71.3 dBFS  ████████░░      ⏺
  [14:24:12] 2m Calling 146.520      146.5200 MHz  -63.1 dBFS  ██████████  🗣  ⏺
```

### SQLite schema

| Column | Description |
|--------|-------------|
| `ts_utc` | ISO 8601 UTC timestamp |
| `ts_unix` | Unix epoch |
| `freq_hz` | Exact channel frequency |
| `channel_name` | Channel name |
| `band` | Band name |
| `modulation` | NFM or AM |
| `signal_dbfs` | Peak channel power (dBFS, relative) |
| `signal_dbm` | Calibrated dBm if rx-crosscheck data present |
| `squelch_db` | Squelch threshold used |
| `has_voice` | 1 if WebRTC VAD detected speech; 0 otherwise |
| `recording_path` | Path to MP3 file (scan mode); NULL if no recording |

---

## Options

| Option | Default | Description |
|--------|---------|-------------|
| `--mode log\|scan` | `log` | Operating mode |
| `--squelch DB` | 10 | dB above noise floor |
| `--gain DB` | 40 | RTL-SDR gain; reduce to 25–30 if overloaded |
| `--ppm N` | 0 | RTL-SDR PPM correction |
| `--serial S` | auto | RTL-SDR serial number |
| `--log FILE` | auto | SQLite path |
| `--alert` | off | SMS alert via `~/money/sms.py` |
| `--no-frs` | off | Skip FRS/GMRS |
| `--no-murs` | off | Skip MURS |
| `--no-marine` | off | Skip Marine VHF |
| `--no-noaa` | off | Skip NOAA (scan mode already skips NOAA by default) |
| `--noaa` | off | **[scan]** Include NOAA (not recommended — always-on) |
| `--no-biz` | off | Skip business band |
| `--airband` | off | Add aviation VHF AM channels (118–136 MHz) |
| `--ham-vhf` | off | Add amateur 2m FM simplex + APRS |
| `--ham-uhf` | off | Add amateur 70cm FM simplex |
| `--no-audio` | off | **[scan]** Disable audio playback |
| `--no-record` | off | **[scan]** Disable MP3 recording |
| `--resume-delay S` | 2.0 | **[scan]** Seconds of silence before advancing |
| `--skip-delay S` | 0.15 | **[scan]** Seconds per channel when scanning |
| `--max-dwell S` | 10.0 | **[scan]** Max seconds on one channel before forcing advance |
| `--mp3-bitrate N` | 32 | **[scan]** MP3 bitrate kbps (32 adequate for voice) |
| `--rec-dir DIR` | `recordings/` | **[scan]** Directory for MP3 files |
| `--tail N` | 25 | Recent detections shown |
| `--no-color` | off | Disable ANSI colours |
| `--list-channels` | — | Print full channel database with modulation types |

---

## Squelch tuning

| Environment | Log mode | Scan mode |
|-------------|----------|-----------|
| Quiet rural | 8–10 dB | 20–25 dB |
| Suburban | 10–15 dB | 25–35 dB |
| Urban / near broadcast FM | 15–20 dB | 35–45 dB |

Scan mode needs a higher threshold because the RTL-SDR has no hardware IF filter,
so strong adjacent-channel signals bleed through. Measured: a strong NOAA transmitter
reads 15–23 dB excess on channels 25 kHz away. A squelch of 35 dB cleanly separates
it from genuine signal (50+ dB excess).

---

## Hardware notes

| Hardware | Result |
|----------|--------|
| Nooelec NESDR SMArt v5 (R820T) | ✅ Full test pass — log and scan modes |
| RTL-SDR Blog v4 | Expected compatible (same driver) |

Log mode cycle time: **~1.1 seconds** per sweep.
Scanner hop time: **~0.15 s/channel** when scanning (no signal).
Scanner dwell: until squelch closes + `resume_delay`, or `max_dwell` expires.

The `[R82XX] PLL not locked!` message at startup is a cosmetic librtlsdr quirk —
it does not indicate a problem.

---

## Adding local frequencies

```python
# In bubba_detector.py, add to ALL_CHANNELS:

# Local repeater (2m):
_ham("W0XYZ RPT 147.180", 147.180, "Ham 2m"),

# Local ATC tower:
_air("Denver Approach 119.3", 119.3, "local ATC"),

# Local business:
_biz("Fire Dispatch 155.340", 155.340, "Business VHF"),
```

The channel will be automatically assigned to the nearest scan group.
If no existing group is within 1.1 MHz, add a new `ScanGroup` entry in `_build_groups()`.
