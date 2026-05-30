# siglent-mixer-characterizer

CLI tool for characterizing RF mixers using a Siglent SDG1062X function generator
(LO + RF source) and SSA3032X Plus spectrum analyzer (IF measurement).

## Measurements

- **Conversion loss vs frequency** — sweeps RF from `--rf-start` to `--rf-stop` at fixed
  LO, measures IF peak power at each point
- **1 dB compression** (`--p1db`) — sweeps RF input power at a fixed frequency to find
  the IF P1dB compression point
- **Port isolation** (`--isolation`) — measures LO→IF and RF→IF feedthrough
- **Spurious products** — captures a wide-span SSA trace with annotated IM products

## Hardware setup

```
SDG CH1 (LO) ──────────────────────── LO port of mixer
SDG CH2 (RF) ──[external attenuator]── RF port of mixer
                                        IF port of mixer ─── SSA RF In
```

## Quick start

```sh
# Default: sweep RF 1–20 MHz with 10 MHz LO at +7 dBm, RF at −20 dBm
python mixer_characterizer.py

# Custom LO frequency and level
python mixer_characterizer.py --lo-freq 100000 --lo-level 7

# Find 1 dB compression at 5 MHz RF
python mixer_characterizer.py --p1db --p1db-freq 5000

# All measurements
python mixer_characterizer.py --p1db --isolation
```

## Dependencies

See `requirements.txt`. All Siglent drivers are from `../rf-bench/` (no install needed).

## Output files

- `<prefix>_conversion.png` — conversion loss vs RF frequency plot
- `<prefix>_p1db.png`       — compression curve with P1dB marker
- `<prefix>_spurs.png`      — wide-span trace with annotated IM products
- `<prefix>_mixer.txt`      — summary text report
