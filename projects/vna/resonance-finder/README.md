# resonance-finder — Auto-detect S11 dips and characterise Q

Sweep S11 across a wide range, automatically find every reflection-dip
(resonance), and report f₀ / -3 dB bandwidth / loaded-Q for each.

Outputs a console table, a single-page PDF chart with each dip
labelled, and an optional CSV with the raw list.

Works with either of the swappable VNA drivers:

- `rf_bench.nanovna.NanoVNA` — **default**, USB CDC at `/dev/ttyACM1`
- `rf_bench.hp.HP8712B` — KISS-488 Ethernet-GPIB at `10.1.1.70`

## Setup

```
VNA Port 1 ──BNC / SMA──→ DUT (trap, helical resonator, crystal jig, ...)
```

Calibrate (at minimum OSL) over the same sweep range first. Without
calibration the dip *depths* will be misreported, though dip *centre
frequencies* and *bandwidths* will still be roughly right.

## Usage

```bash
# Find all resonances in a trap dipole from 1–60 MHz
python resonance_finder.py --start 1 --stop 60 \
    --label "G7FEK trap dipole" --output trap.pdf --csv trap.csv

# Hunt for the resonance of a 2 m helical antenna
python resonance_finder.py --start 100 --stop 200 \
    --label "2 m rubber duck on dummy ground" --output rd.pdf

# Crystal motional resonance, narrow sweep
python resonance_finder.py --start 9.995 --stop 10.005 \
    --points 401 --average 8 --min-depth 3 \
    --label "10 MHz HC-49 xtal" --output xtal.pdf
```

Optional flags:

- `--vna {nanovna,hp}` — driver selection (default nanovna)
- `--port /dev/ttyACM1` — NanoVNA serial path
- `--host 10.1.1.70` — HP KISS-488 host
- `--points N` — sweep points (NanoVNA max 401, HP max 801; default 401)
- `--average N` — software-average N sweeps (default 2)
- `--power DBM` — HP source power; ignored on NanoVNA
- `--min-depth DB` — only count dips deeper than this (default 6 dB)
- `--min-separation MHZ` — minimum spacing between two distinct dips.
  Default is 1 % of the sweep span; raise it if a noisy trace gets
  split into multiple "resonances."
- `--csv FILE.csv` — also write the resonance list as CSV

## Output

Console table:

```
  #     f0 (MHz)  depth (dB)  BW3dB (kHz)        Q
  ---  ----------  ----------  -----------  -------
    1     7.0512       -22.4         85.2      828
    2    14.1023       -18.9        180.4      781
    3    21.1488       -14.1        302.7      699
```

Single-page PDF with:

- **|S11| (dB) vs frequency**, Y-axis flipped so dips point upward
- Every detected resonance marked with a downward triangle and a label
  bubble: `f₀`, depth, -3 dB BW (kHz), Q
- Shaded -3 dB region around each dip

## What's "Q" here?

Loaded Q = f₀ / BW₃dB. This is the *as-measured* Q including all
external loading from the VNA's 50-Ω port. Unloaded Q is higher; the
classical extraction is

    Q_u = Q_l · (1 - 10^(depth_dB / 20))^-1

The script reports Q_l only — a fair go/no-go indicator for trap
tuning. If you need Q_u, the depth and BW are right there to compute
it from.

## Notes

- The detector assumes |S11| (in dB) has clear local minima. Noisy
  traces produce false dips. Cure with `--average`, by raising
  `--min-depth`, or by raising `--min-separation`.
- A "dip" with broad shoulders may have a poorly-defined 3-dB
  bandwidth (the analyser walks outward until S11 rises 3 dB above the
  bottom; if it never does within the sweep, Q is reported as "n/a"
  / NaN).
- For crystal motional measurement (Q values in the thousands), use a
  fine sweep and the highest VNA averaging available. NanoVNA noise
  floor will limit Q resolution above ~5000; the HP 8712B does
  considerably better.
