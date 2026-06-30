# connector-check — Pass/fail return-loss test for a connector or patch lead

Quick-take sanity check after every PL-259 crimp, every barrel
adapter you buy off eBay, every patch lead you're not sure about.
Plug the DUT into port 1 with a 50-Ω load on the back, pick which
amateur bands to score it against, and the script tells you PASS or
FAIL per band.

Works with either of the swappable VNA drivers:

- `rf_bench.nanovna.NanoVNA` — **default**, USB CDC at `/dev/ttyACM1`
- `rf_bench.hp.HP8712B` — KISS-488 Ethernet-GPIB at `10.1.1.70`

## Setup

```
VNA Port 1 ── [connector / adapter / patch lead under test] ── 50-Ω LOAD
```

OSL-calibrate the VNA at the SMA / N reference plane *before* the DUT,
across the same sweep range you'll use in the test. The point of the
load on the far end is to terminate the line so the only reflection
you see is the DUT itself.

For a patch lead, both connectors are exercised. For a single barrel
adapter, you'll see a clean reflection from any imperfection in the
adapter.

## Usage

```bash
# Check a PL-259 crimp across HF
python connector_check.py --bands hf --threshold 20 \
    --label "PL-259 on RG-58 #3 (new crimp)" \
    --output crimp3.pdf --json crimp3.json

# VHF/UHF patch lead
python connector_check.py --bands vhf uhf --threshold 18 \
    --label "BNC patch lead, lab #7" --output lab7.pdf

# Custom range with auto band-detection
python connector_check.py --start 1 --stop 30 --threshold 20 \
    --label "PL-259 attic feed" --output attic.pdf
```

Optional flags:

- `--vna {nanovna,hp}` — driver selection (default nanovna)
- `--port /dev/ttyACM1` — NanoVNA serial path
- `--host 10.1.1.70` — HP KISS-488 host
- `--bands SET …` — pick one or more of `hf`, `6m`, `vhf`, `uhf`,
  `23cm`. The sweep range is the union of the chosen ranges, padded
  by 10 %. Overrides `--start`/`--stop`.
- `--start MHZ` / `--stop MHZ` — explicit sweep range. The script
  scores any amateur band that falls within.
- `--threshold DB` — pass/fail return-loss threshold (default 20 dB,
  i.e. VSWR 1.22:1). Useful overrides:
  - **14 dB** — minimum for "we'll let it slide on the high bands"
  - **20 dB** — default; tight but achievable on a good crimp
  - **26 dB** — high-end spec, VSWR 1.10:1
- `--points N` — sweep points (NanoVNA max 401, HP max 801; default 401)
- `--average N` — software-average N sweeps (default 2)
- `--power DBM` — HP source power; ignored on NanoVNA
- `--json FILE.json` — also write a machine-readable result file

## Output

Console table per band:

```
   Band       Range (MHz)     Worst RL      Best RL   Verdict
  ------   -----------------   ----------   ----------   -------
    160m     1.800–2.000        29.4 dB       33.1 dB   PASS
     80m     3.500–4.000        26.7 dB       30.2 dB   PASS
     20m    14.000–14.350       21.1 dB       24.0 dB   PASS
     15m    21.000–21.450       19.4 dB       22.5 dB   FAIL
     10m    28.000–29.700       18.2 dB       20.9 dB   FAIL

  Overall      : FAIL
```

Plus a single-page PDF with the |S11| trace, the threshold line, and
each amateur band shaded green (PASS) or red (FAIL).

JSON file (if `--json` is given) holds the same data plus the IDN,
timestamp, and a top-level `overall_pass` boolean — useful for
scripting incoming-QA on bulk-bought connectors.

## Exit code

The script exits with:

- `0` — all checked bands passed
- `2` — at least one band failed
- `1` — script error (bad arguments, VNA didn't respond, etc.)

Drop it in a shell script to automate batch testing.

## Notes

- Don't trust the result without a calibration cross-check. After
  OSL, sweep a known-good barrel and verify the trace looks like the
  manufacturer's curve before testing your sample.
- For very-high-quality connector work (N-type, SMA, precision lab
  adapters), 20 dB is well below the part's spec. Push the threshold
  up to 26 or 30 dB. PL-259 / UHF connectors at VHF are inherently
  worse — 14 dB is more honest.
- A patch lead's whole length sits between port 1 and the load; long
  cables with appreciable matched loss will show up as *better*
  return loss than a short jumper made of the same connectors (the
  reflection from the far end gets attenuated by the round trip).
  Account for this if you're trying to grade just the connectors.
