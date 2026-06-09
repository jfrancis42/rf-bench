# coverage — Signal Strength Coverage Mapper

Logs S-meter readings from an IC-7300, IC-9700, or FT-891 vs time, optionally
geo-tagged with GPS coordinates. Useful for:

- Measuring a repeater's coverage area (drive or walk a route)
- Mapping an antenna's horizontal radiation pattern (drive a circle)
- Finding propagation dead zones
- VHF/UHF path characterization with IC-9700

## Hardware required

- IC-7300, IC-9700, or FT-891 (rigctld running)
- (Optional) gpsd-connected GPS receiver

## Usage

```bash
# 2m beacon coverage map with GPS:
python coverage.py --freq 144283 --radio ic9700 --gps

# HF 20m propagation survey, no GPS:
python coverage.py --freq 14200 --radio ic7300 --duration 3600

# FT-891 on 40m, custom output stem:
python coverage.py --freq 7200 --radio ft891 --gps --out 40m_survey
```

## Output

- `<stem>_<timestamp>.csv` — timestamp, lat, lon, signal dBm, mode
- `<stem>_<timestamp>.gpx` — GPX track with signal-strength extension (GPS only)
