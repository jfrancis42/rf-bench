# siglent-calibration

Cross-instrument amplitude calibration tool for the Siglent bench. Uses the
SDG1062X function generator as a reference signal source to measure each
instrument's amplitude reading vs frequency.

## What it measures

- **Oscilloscope (SDS2000X):** RMS computed from captured waveform array
- **Spectrum analyzer (SSA3000X):** peak marker in a narrow span
- **Multimeter (SDM3000X):** AC Vrms (reliable to ~100 kHz)

Produces a correction table (offset = instrument − SDG nominal) and a
flatness plot showing amplitude error vs frequency for each instrument.

## IMPORTANT — relative calibration only

The SDG is the reference. This tool tells you how instruments read *relative
to the SDG*. It does not tell you whether the SDG is accurate in absolute terms.
For traceable absolute calibration, use an external NIST-traceable power sensor.

## Hardware setup

```
SDG CH1 ─── T-splitter ─┬─── coax ─── scope CH1
                          ├─── coax ─── SSA RF In
                          └─── coax ─── DMM Hi (BNC-banana)
```

## Quick start

```sh
# Default 10-point log sweep, 100 Hz to 10 MHz
python calibration.py

# Custom frequency list
python calibration.py --freq-list "100,1000,10000,100000,1000000,10000000"

# Skip DMM for RF frequencies
python calibration.py --skip-dmm

# Quieter level with more averages
python calibration.py --level -20 --averages 5
```

## Dependencies

See `requirements.txt`. All Siglent drivers are from `../rf-bench/` (no install needed).

## Output files

- `<prefix>_cal_table.csv`    — per-frequency readings and offsets
- `<prefix>_cal_flatness.png` — three-panel flatness plot
- `<prefix>_cal.txt`          — summary statistics
