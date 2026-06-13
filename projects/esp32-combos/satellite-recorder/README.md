# ESP32 Satellite Recorder

Automated satellite pass recorder combining scpi-rotator + scpi-gps + IC-9700.

Predicts satellite passes, tracks antenna position in real-time, applies Doppler correction to the radio frequency, and records audio for the duration of the pass.

## Status

🔨 **Implementation in progress** — hardware pending

## Hardware

- **scpi-rotator** — ESP32-based az/el antenna rotator (SCPI over TCP port 5025)
- **scpi-gps** — ESP32-based GPS receiver (SCPI over TCP port 5025)
- **IC-9700** — Icom VHF/UHF/1.2GHz transceiver via Hamlib rigctld
- **Audio interface** — IC-9700 USB audio or external sound card for recording

## Dependencies

```bash
pip install rf-bench-drivers-icom rf-bench-drivers-gpsd skyfield sounddevice soundfile requests numpy
```

System packages (for audio):
```bash
sudo apt-get install libportaudio2 libsndfile1
```

## Setup

### 1. Start rigctld for IC-9700

```bash
# IC-9700 on /dev/ttyUSB0
rigctld -m 3081 -r /dev/ttyUSB0 -s 115200 -T localhost -t 4532
```

### 2. Deploy scpi-rotator and scpi-gps firmware

See:
- `~/Dropbox/build/rf-bench/projects/esp32-combos/scpi-rotator/`
- `~/Dropbox/build/rf-bench/projects/esp32-combos/scpi-gps/`

Note the ESP32 IP addresses after deployment.

### 3. Connect IC-9700 audio

Options:
- **USB audio:** IC-9700 appears as ALSA device, use `aplay -l` to identify
- **External sound card:** Line out from IC-9700 accessory jack
- **Script default:** uses system default input device via sounddevice

## Usage

### Record ISS SSTV pass (145.800 MHz FM)

```bash
./satellite_record.py \
  --esp-rotator 10.1.0.100 \
  --esp-gps 10.1.0.101 \
  --rigctld-host localhost \
  --sat-name "ISS" \
  --tx-freq 145800000 \
  --mode FM \
  --bandwidth 15000 \
  --min-elevation 15 \
  --output-dir recordings/
```

### Record NOAA 19 APT weather satellite (137.1 MHz FM)

```bash
./satellite_record.py \
  --esp-rotator 10.1.0.100 \
  --esp-gps 10.1.0.101 \
  --sat-name "NOAA 19" \
  --tx-freq 137100000 \
  --mode FM \
  --bandwidth 40000 \
  --min-elevation 10 \
  --output-dir recordings/
```

### Record AO-91 FM repeater (145.960 MHz)

```bash
./satellite_record.py \
  --esp-rotator 10.1.0.100 \
  --esp-gps 10.1.0.101 \
  --sat-name "AO-91" \
  --tx-freq 145960000 \
  --mode FM \
  --bandwidth 12500 \
  --min-elevation 20 \
  --tle-source SatNOGS \
  --output-dir recordings/
```

### Use remote rigctld

```bash
./satellite_record.py \
  --esp-rotator 10.1.0.100 \
  --esp-gps 10.1.0.101 \
  --rigctld-host 10.1.0.34 \
  --rigctld-port 4532 \
  --sat-name "ISS" \
  --tx-freq 145800000 \
  --output-dir recordings/
```

## Output

For each pass, the script creates:

1. **Audio file:** `<satellite>_<timestamp>.wav` (mono, 48 kHz default)
2. **Metadata file:** `<satellite>_<timestamp>.json` with:
   - Satellite name
   - TX frequency
   - AOS/TCA/LOS times (ISO 8601 UTC)
   - Max elevation and azimuth at AOS/LOS
   - Sample rate

Example metadata:
```json
{
  "satellite": "ISS",
  "tx_frequency_hz": 145800000,
  "aos_time": "2026-06-12T14:32:15+00:00",
  "los_time": "2026-06-12T14:42:08+00:00",
  "tca_time": "2026-06-12T14:37:12+00:00",
  "max_elevation_deg": 68.4,
  "aos_azimuth_deg": 12.3,
  "los_azimuth_deg": 243.7,
  "sample_rate_hz": 48000
}
```

## TLE Sources

- **AMSAT:** https://www.amsat.org/tle/current/nasabare.txt (NASA two-line elements for amateur satellites)
- **SatNOGS:** https://db.satnogs.org/api/tle/ (crowdsourced satellite database with broader coverage)

The script automatically fetches fresh TLEs before each pass prediction.

## Use Cases

- **ISS SSTV events:** Record Slow-Scan TV images on 145.800 MHz FM
- **Weather satellites:** NOAA 15/18/19 APT at 137.x MHz, decode with WXtoImg or noaa-apt
- **FM repeaters in LEO:** AO-91, AO-92, SO-50
- **Linear transponder sats:** FO-29, AO-7 (requires USB/LSB mode)
- **Meteor M2 LRPT:** 137.1 MHz QPSK, decode with SatDump
- **Packet radio:** ISS APRS digipeater on 145.825 MHz

## Doppler Correction Algorithm

The script uses SGP4 propagation (via skyfield) to compute satellite position and velocity at each time step. Doppler shift is calculated as:

```
doppler_shift = -f * (range_rate / c)
```

where:
- `f` = transmitted frequency (Hz)
- `range_rate` = radial velocity component (m/s, positive when receding)
- `c` = speed of light (299792458 m/s)

The receiver is tuned to `f - doppler_shift` to compensate.

For a typical LEO pass at 145 MHz:
- Approaching: +3 kHz Doppler shift (tune receiver 3 kHz lower)
- Overhead: ~0 Hz Doppler shift
- Receding: -3 kHz Doppler shift (tune receiver 3 kHz higher)

The script updates antenna position and radio frequency **every 1 second** during the pass.

## Pass Prediction

Pass prediction uses the skyfield library to compute satellite position at 30-second intervals over the next 7 days. A pass is defined as:

- **AOS (Acquisition of Signal):** Satellite rises above `--min-elevation` threshold
- **TCA (Time of Closest Approach):** Peak elevation during the pass
- **LOS (Loss of Signal):** Satellite falls below `--min-elevation` threshold

The script automatically waits until AOS, then begins tracking and recording.

## Antenna Aiming

The scpi-rotator ESP32 firmware provides SCPI commands for az/el control:

- `ROT:AZ <degrees>` — Set azimuth (0-360°)
- `ROT:EL <degrees>` — Set elevation (0-90°)
- `ROT:AZ?` — Query current azimuth
- `ROT:EL?` — Query current elevation

The script sends position updates every 1 second. Ensure your rotator has sufficient slew rate to track fast passes (ISS moves ~1°/second at peak).

## Audio Recording

Three options:

1. **sounddevice (default):** Uses system default audio input, no configuration needed
2. **IC-9700 USB audio:** Select IC-9700 as ALSA default device in `/etc/asound.conf`
3. **arecord:** Modify script to use `subprocess.Popen(['arecord', '-f', 'S16_LE', '-r', '48000', ...])`

The default sounddevice implementation is simplest and works with any audio interface.

## Known Satellites

### Amateur FM Repeaters (VHF/UHF)
- AO-91: 145.960 MHz downlink
- AO-92: 145.880 MHz downlink
- SO-50: 436.795 MHz downlink
- ISS: 145.800 MHz (SSTV events), 145.825 MHz (APRS digipeater)

### Weather Satellites (NOAA APT)
- NOAA 15: 137.620 MHz
- NOAA 18: 137.9125 MHz
- NOAA 19: 137.100 MHz

### Weather Satellites (Meteor LRPT)
- Meteor M2: 137.100 MHz (QPSK, 72 kbps)
- Meteor M2-2: 137.900 MHz (QPSK, 72 kbps)

### Linear Transponder (SSB/CW)
- FO-29: 435.850 MHz downlink (USB)
- AO-7: 145.950 MHz or 435.150 MHz (mode dependent)

## Future Enhancements

- **Multi-satellite scheduler:** Track passes for multiple satellites, automatically switch between them
- **Waterfall logging:** Save IQ samples for post-pass analysis
- **Automatic APRS decode:** Parse ISS APRS digipeater packets during recording
- **TX support:** Uplink Doppler correction for two-way contacts
- **Web UI:** Real-time pass visualization with WebSocket updates
- **Cloud integration:** Upload recordings to S3/Dropbox for remote access
- **Satellite tracking display:** Live map showing satellite ground track and antenna beam

## Troubleshooting

### No audio captured

- Check `aplay -l` or `arecord -l` to verify sound card is detected
- Test with `arecord -d 5 -f S16_LE -r 48000 test.wav` before running script
- For IC-9700 USB audio, ensure "SEND/WIDTH" control is set to USB in radio menu

### Rotator not moving

- Verify scpi-rotator is reachable: `nc -zv <ESP_IP> 5025`
- Test manually: `echo "ROT:AZ 180" | nc <ESP_IP> 5025`
- Check antenna cables and motor power supply

### Radio frequency not updating

- Verify rigctld is running: `rigctl -m 2 -r localhost:4532 f`
- Check CAT cable connection to IC-9700
- Ensure IC-9700 "CI-V Address" matches rigctld `-m` parameter

### Pass prediction fails

- Check internet connectivity (TLE fetch requires HTTPS)
- Verify satellite name matches AMSAT or SatNOGS database (case-insensitive)
- Try alternate TLE source: `--tle-source SatNOGS` if AMSAT is down

### Doppler correction seems wrong

- Verify GPS position is accurate: `echo "GPS:LAT?" | nc <ESP_IP> 5025`
- Check system time is synchronized (NTP): `timedatectl status`
- Ensure TLE is fresh (older than 1-2 weeks may have significant error)

## References

- Skyfield library: https://rhodesmill.org/skyfield/
- AMSAT TLE: https://www.amsat.org/tle/
- SatNOGS DB: https://db.satnogs.org/
- Hamlib: https://github.com/Hamlib/Hamlib
- IC-9700 manual: https://www.icomamerica.com/en/products/amateur/hf/7300/default.aspx
