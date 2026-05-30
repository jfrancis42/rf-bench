> ⚠️ **UNTESTED** — This implementation has not been verified against physical hardware.
> Code is complete but has not been bench-tested. Verify behavior before relying on output.

# rf-bench-rtlsdr-wxsat

**GitHub:** https://github.com/jfrancis42/rf-bench-rtlsdr-wxsat

Weather satellite receiver and decoder: captures NOAA APT and Meteor-M LRPT
transmissions via RTL-SDR, decodes them to PNG images.  Pass predictions are
computed from current TLE data; captures can be scheduled automatically.

## Satellites

| Satellite | Frequency | Mode | Resolution |
|-----------|-----------|------|-----------|
| NOAA 15 | 137.620 MHz | APT (analog FM) | 4 km/px, VIS + IR |
| NOAA 18 | 137.9125 MHz | APT (analog FM) | 4 km/px, VIS + IR |
| NOAA 19 | 137.100 MHz | APT (analog FM) | 4 km/px, VIS + IR |
| Meteor-M N2-4 | 137.100 MHz | LRPT (digital QPSK) | 1 km/px, RGB |

## Hardware

| Component | Notes |
|-----------|-------|
| RTL-SDR Blog v4 | Any RTL2832U dongle works |
| V-dipole antenna | Two 54 cm elements at 120° — omnidirectional, no tracking needed |
| Inline LNA | Strongly recommended; enable bias tee with `--bias-tee` in the driver |

Observer location is hard-coded in `wxsat.py` at the top of the file.  Change
`OBSERVER_LAT`, `OBSERVER_LON`, `OBSERVER_ALT` to your coordinates.

## System dependencies

```bash
pacman -S rtl-sdr sox
# APT decode
yay -S noaa-apt          # or install from https://noaa-apt.mbernardi.com.ar
# LRPT decode (optional)
# SatDump: https://github.com/SatDump/SatDump
```

## Usage

### List upcoming passes

```bash
python wxsat.py passes
python wxsat.py passes --sat NOAA19 --hours 48
```

### Capture next pass

```bash
python wxsat.py capture --sat NOAA18
python wxsat.py capture --sat NOAA19 --gain 45 --outdir ~/wxsat/
```

Waits until AOS (minus 60 s), records the full pass, then decodes to PNG.

### Decode a saved file

```bash
python wxsat.py decode wxsat_NOAA19_20260528_211400.wav
python wxsat.py decode wxsat_METEOR_20260528_211400.iq
```

### Auto-schedule all passes

```bash
python wxsat.py schedule --outdir ~/wxsat/
```

Runs continuously, capturing every pass above `MIN_ELEVATION` (20° default).

## Output files

| File | Description |
|------|-------------|
| `wxsat_{SAT}_{timestamp}.wav` | Raw FM audio for APT satellites |
| `wxsat_{SAT}_{timestamp}.iq` | Raw IQ for Meteor LRPT |
| `wxsat_{SAT}_{timestamp}.png` | Decoded image (after noaa-apt) |
| `tle_cache.json` | Cached TLE data (refreshed every 24 h) |

## Python dependencies

```
pip install rf-bench-drivers-rtlsdr pyorbital
```
