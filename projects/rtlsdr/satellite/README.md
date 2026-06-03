# satellite_monitor — Satellite Downlink Wideband Monitor

While the IC-9700 handles the satellite duplex uplink, use the RTL-SDR as a
wideband receiver to monitor the 70cm downlink passband. Captures the full
transponder bandwidth as IQ (up to 2.4 MHz wide), letting you see your own
signal plus other stations in the passband simultaneously — useful for linear
transponders.

This is complementary to `projects/radio/satellite/` — that script commands the
IC-9700 for TX/RX Doppler correction; this script provides a real-time wideband
waterfall view of the downlink transponder showing all active stations at once.

## Features

- **Real-time waterfall display** — see all stations in the transponder passband simultaneously
- **Doppler tracking** — optional automatic frequency correction using satellite TLE + GPS
- **IQ recording** — save passes to SigMF format for offline analysis
- **Built-in satellite database** — AO-91, AO-92, SO-50, ISS, FO-29, AO-7
- **Linear transponder support** — monitor 50+ kHz passband for SSB/CW activity
- **FM repeater support** — narrow-band monitoring for FM voice satellites

## Quick start

```bash
# Monitor AO-91 downlink (FM, 30 kHz BW)
python satellite_monitor.py --sat AO-91 --gps

# Monitor FO-29 linear transponder (USB, 200 kHz BW, with Doppler)
python satellite_monitor.py --sat FO-29 --gps --doppler

# Custom frequency with Doppler tracking
python satellite_monitor.py --freq 145.96e6 --bw 200e3 --gps --doppler --norad 43017

# Record pass to SigMF file
python satellite_monitor.py --sat AO-91 --gps --doppler --record ao91_pass

# Waterfall-only (no recording, minimal CPU)
python satellite_monitor.py --sat FO-29 --gps --doppler --waterfall-only
```

All frequencies are in Hz. Use scientific notation: `145.960e6` = 145.960 MHz.

## Options

### Satellite selection
| Flag | Description |
|------|-------------|
| `--sat NAME` | Built-in satellite (AO-91, AO-92, SO-50, ISS, FO-29, AO-7) |
| `--freq HZ` | Custom downlink frequency in Hz |
| `--norad N` | NORAD catalog number (required with `--freq --doppler`) |
| `--bw HZ` | Sample rate / bandwidth in Hz (default: auto from satellite) |
| `--list-sats` | List built-in satellites and exit |

### Location (for Doppler tracking)
| Flag | Description |
|------|-------------|
| `--gps` | Use gpsd for ground station location |
| `--lat DEG` | Latitude in decimal degrees (+N) |
| `--lon DEG` | Longitude in decimal degrees (+E) |
| `--alt M` | Altitude in metres (default: 0) |

### Doppler tracking
| Flag | Description |
|------|-------------|
| `--doppler` | Enable real-time Doppler correction (requires location and `skyfield`) |

Without `--doppler`, the RTL-SDR tunes to the nominal downlink frequency and does
not adjust during the pass. This is fine for short passes or FM satellites where
the receiver's AFC handles Doppler, but linear transponders benefit from tracking.

### Recording and display
| Flag | Default | Description |
|------|---------|-------------|
| `--record STEM` | — | Save IQ to SigMF file (e.g., `pass.sigmf` → `pass.sigmf-data` + `pass.sigmf-meta`) |
| `--waterfall-only` | — | Display waterfall without recording (lower CPU / disk usage) |
| `--fft-size N` | 2048 | FFT size for spectrum / waterfall |
| `--update S` | 0.1 | Display update interval in seconds |

### RTL-SDR settings
| Flag | Default | Description |
|------|---------|-------------|
| `--gain DB` | auto | Gain in dB or `auto` |
| `--bias-tee` | — | Enable bias tee to power an LNA |
| `--serial SN` | — | RTL-SDR serial number (if multiple dongles) |

## Built-in satellites

| Name | NORAD | Downlink | Mode | BW | Notes |
|------|-------|----------|------|-----|-------|
| AO-91 | 43017 | 145.960 MHz | FM | 30 kHz | Fox-1B; uplink needs 67.0 Hz CTCSS |
| AO-92 | 43137 | 145.880 MHz | FM | 30 kHz | Fox-1D |
| SO-50 | 27607 | 436.795 MHz | FM | 30 kHz | Uplink: arm 74.4 Hz, then 67.0 Hz |
| ISS | 25544 | 145.800 MHz | FM | 30 kHz | Crossband repeater; intermittent |
| FO-29 | 24278 | 435.850 MHz | USB | 50 kHz | Linear transponder, inverted |
| AO-7 | 7530 | 145.975 MHz | USB | 50 kHz | Mode B linear; battery-less |

Frequencies from AMSAT-NA documentation. Verify against current AMSAT news before
use — satellite configurations can change.

## Use cases

### 1. Linear transponder monitoring during your own QSO

When working a linear transponder (FO-29, AO-7), you need to hear where your own
signal lands in the passband. The IC-9700 handles your TX/RX, but you only hear
your own downlink if another station is calling you or you have a second receiver.

**With this script:** the RTL-SDR shows the full 50 kHz passband as a waterfall.
You see your own CW or SSB signal as a trace in real-time, along with all other
active stations. Adjust your uplink frequency to move your signal to a clear spot.

### 2. Learning satellite operating before transmitting

Before keying up on a busy satellite, watch the downlink waterfall for a few
passes. You'll learn:
- Which frequencies in the passband are most active
- Typical signal strengths (how loud do stations appear?)
- How Doppler shifts the passband during the pass
- When the satellite is quiet enough to make a call

### 3. Recording passes for later analysis

Record the full transponder bandwidth during a pass, then replay it in GNU Radio,
SDR++, or inspectrum to decode signals you missed live, measure Doppler drift,
or practice finding weak CW signals in the noise.

### 4. Comparing IC-9700 and RTL-SDR reception

Run both receivers simultaneously (IC-9700 on a beam, RTL-SDR on an omni). The
waterfall shows what the RTL-SDR hears; the IC-9700's audio is what you transmit
on. If the RTL-SDR sees a signal the IC-9700 doesn't, your beam pointing may be
off, or the IC-9700's preamp/filter settings need adjustment.

## How Doppler tracking works

When `--doppler` is enabled:
1. The script fetches TLE (orbital parameters) from AMSAT or SatNOGS
2. At 1-second intervals, it computes the satellite's position using `skyfield` (SGP4)
3. It calculates the radial velocity (range rate) between the ground station and satellite
4. It updates the RTL-SDR's center frequency to compensate: `f_rx = f_nominal × (1 − range_rate / c)`

Peak Doppler at 145 MHz: ±3.4 kHz. At 435 MHz: ±10 kHz. Without correction, a
CW or SSB signal on a linear transponder drifts across several kHz during a pass,
making it hard to follow in the waterfall. With Doppler tracking, signals stay
centered in the display.

**Note:** The RTL-SDR's frequency tracking is **receive-only**. It does not
command the IC-9700. If you want the IC-9700 to also track Doppler, run
`projects/radio/satellite/satellite.py --track` in parallel.

## TLE data sources

- **AMSAT** (`amsat.org/tle/current/nasabare.txt`) — authoritative for amateur satellites; updated daily
- **SatNOGS** (`db.satnogs.org/api/tle/`) — per-NORAD fallback
- Cache: `~/.cache/rf-bench/tle/` — refreshed every 6 hours

TLE data is required only if `--doppler` is enabled. Without Doppler, no TLE
fetch occurs.

## Hardware requirements

- RTL-SDR dongle (RTL-SDR Blog v3/v4 recommended)
- Optional: GPS receiver with `gpsd` running (for Doppler tracking)
- Optional: LNA + bias tee for weak satellite signals
- Python 3.9+ with dependencies:
  ```bash
  pip install numpy matplotlib rf-bench-drivers-rtlsdr
  pip install skyfield requests  # for Doppler tracking
  pip install sigmf              # for SigMF metadata
  pip install rf-bench-drivers-gpsd  # for GPS location
  ```

## Typical workflow

1. **Start rigctld for IC-9700:**
   ```bash
   rigctld -m 3081 -r /dev/ttyUSB0 -s 115200 &
   ```

2. **Start Doppler tracker for IC-9700 TX/RX:**
   ```bash
   cd ../../../projects/radio/satellite/
   python satellite.py --sat AO-91 --gps --track &
   ```

3. **Start RTL-SDR waterfall monitor (this script):**
   ```bash
   python satellite_monitor.py --sat AO-91 --gps --doppler --waterfall-only
   ```

4. **Operate:** The IC-9700 handles TX/RX with Doppler. The RTL-SDR waterfall
   shows the full downlink passband. You see your own signal plus all other
   stations in real-time.

5. **Record a pass (optional):**
   ```bash
   python satellite_monitor.py --sat AO-91 --gps --doppler --record ao91_$(date +%Y%m%d_%H%M)
   ```

## Known limitations

- **Waterfall update rate:** At 0.1s default, the display updates 10 times per
  second. Lower `--update` for smoother waterfalls at the cost of higher CPU usage.
- **RTL-SDR bandwidth:** Maximum 2.4 MHz. Linear transponders (50 kHz) fit easily;
  you could monitor multiple FM channels (each 30 kHz) in one 200 kHz span.
- **No automatic pass scheduling:** This script does not predict pass times. Use
  `projects/radio/satellite/satellite.py` (without `--track`) to list upcoming
  passes, then start this script manually before AOS.
- **No transmit integration:** This script is receive-only. It does not control
  the IC-9700's TX frequency or PTT. Use the companion satellite.py for that.

## Complementary tools

- **`projects/radio/satellite/satellite.py`** — IC-9700 Doppler tracker (TX/RX)
- **`projects/rtlsdr/recorder/recorder.py`** — General-purpose IQ recorder (no Doppler, no waterfall)
- **`projects/rtlsdr/classify/classify.py`** — Signal classifier (identifies modulation type)
- **GNU Radio** / **SDR++** / **inspectrum** — Offline analysis of recorded SigMF files

## Example: Monitoring FO-29 linear transponder

FO-29 is a 50 kHz linear transponder (inverted passband) on 435.850 MHz USB.
Stations transmit on 145.950 MHz LSB; the satellite inverts and shifts to the
70cm downlink.

**Setup:**
```bash
# Start IC-9700 Doppler tracker for TX/RX
python ../../../projects/radio/satellite/satellite.py --sat FO-29 --gps --track &

# Start RTL-SDR waterfall monitor
python satellite_monitor.py --sat FO-29 --gps --doppler --bw 200e3 --record fo29_pass
```

**During the pass:**
- IC-9700 LSB on 145.950 MHz (TX), USB on 435.850 MHz (RX)
- RTL-SDR waterfall shows 200 kHz around 435.850 MHz
- Your USB downlink signal appears in the waterfall along with other stations
- Adjust your TX frequency to move your signal to a clear part of the passband
- Recording saves the full pass for later analysis

**After the pass:**
- Open `fo29_pass.sigmf-data` in inspectrum or GNU Radio
- Replay the pass, decode CW/SSB signals you missed live
- Measure actual Doppler drift by tracking a strong carrier across the pass
- Share the recording with other stations who were active during the pass

## Troubleshooting

**"No TLE found for NORAD XXXXX"**  
The satellite may not be in AMSAT's nasabare.txt or SatNOGS database. Verify the
NORAD catalog number at [CelesTrak](https://celestrak.org) or [n2yo.com](https://n2yo.com).

**Waterfall shows only noise**  
- Check antenna connection and LNA power (use `--bias-tee` if needed)
- Verify the satellite is above the horizon: run `../../../projects/radio/satellite/satellite.py --sat XYZ --gps` to list pass times
- Increase RTL-SDR gain: try `--gain 40` instead of `--gain auto`

**Doppler correction is wrong**  
- Verify ground station location is correct: `--gps` or `--lat/--lon/--alt`
- Check TLE age: stale TLE data (weeks old) causes prediction errors
- Use `--refresh-tle` in the radio/satellite script to force a fresh TLE download

**Recording file is huge**  
- A 10-minute pass at 2.4 MS/s complex float32 is ~11 GB
- Use smaller bandwidth: `--bw 200e3` (200 kHz) → 1.4 GB for 10 minutes
- Or record as complex int8 (modify script to use `astype(np.int8)`) → 4× smaller

**Waterfall is choppy / slow**  
- Reduce `--fft-size` (e.g., 1024 instead of 2048)
- Increase `--update` interval (e.g., 0.2 instead of 0.1)
- Close other CPU-heavy applications

## See also

- [AMSAT-NA Satellite Frequency Guide](https://www.amsat.org/status/)
- [SatNOGS Network](https://network.satnogs.org) — live satellite passes and recordings
- [projects/radio/satellite/README.md](../../../projects/radio/satellite/README.md) — IC-9700 Doppler tracker
- [projects/rtlsdr/recorder/README.md](../../recorder/README.md) — General IQ recorder
