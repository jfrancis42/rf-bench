# doppler — Real-Time Doppler VFO Corrector

Computes the radial velocity component toward a fixed target from the GPS-reported
speed and heading, then applies a VFO offset in real time via Hamlib to compensate
for Doppler shift. Primarily useful for satellite operation with the IC-9700.

## Hardware required

- IC-7300, IC-9700, or FT-891 (rigctld running)
- GPS receiver + gpsd running

## Usage

```bash
# IC-9700 satellite Doppler correction (dry-run):
python doppler.py --radio ic9700 --freq 435100 --target-lat 39.35 --target-lon -104.67 --dry-run

# Live correction:
python doppler.py --radio ic9700 --freq 435100 --target-lat 39.35 --target-lon -104.67
```

## Notes

- IC-9700 is the primary intended radio (cross-band satellite duplex)
- `--dry-run` displays computed offset without sending to radio
- For satellite passes, prefer `radio/satellite/satellite.py` which handles
  the full pass ephemeris and sets both uplink and downlink Doppler
