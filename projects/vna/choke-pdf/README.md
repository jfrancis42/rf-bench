# choke-pdf — Common-mode choke |Z| PDF

S21 sweep with the choke wired in series with the THRU path → |Z| and
R / X across frequency → single-page PDF.

This is the standard "K6JCA / DX Engineering" series-through method:
the choke sits as a SERIES element in a 50-Ω VNA THRU; the derived
impedance is

    Zdut(f) = 2 · Z0 · (1 - S21(f)) / S21(f)

Works with either of the swappable VNA drivers:

- `rf_bench.nanovna.NanoVNA` — **default**, USB CDC at `/dev/ttyACM1`
- `rf_bench.hp.HP8712B` — KISS-488 Ethernet-GPIB at `10.1.1.70`

## Setup

```
VNA Port 1 ── [SMA centre pin → choke → SMA centre pin] ── VNA Port 2
                    (shield is continuous, common to both jacks)
```

You need a series-through fixture: two SMA bulkhead jacks bolted to a
shared brass strip, centre conductors broken into a pair of test
clips. The choke connects between the clips. Calibrate THRU on the
fixture *with the centre conductor solidly bridged* before measuring,
so the trace shows only the choke and not the fixture loss.

## Usage

```bash
# 4-turn FT240-43 ugly balun across HF
python choke_pdf.py --start 1 --stop 30 --target 2000 \
    --label "FT240-43, 4 turns RG-58" --output ft240_43_4t.pdf

# 7-turn FT240-31 for high-band HF emphasis
python choke_pdf.py --start 5 --stop 50 --target 2000 \
    --label "FT240-31, 7 turns RG-58" --output ft240_31_7t.pdf

# Snap-on ferrite choke for 2 m / 70 cm
python choke_pdf.py --start 100 --stop 500 --target 1000 \
    --label "Wuerth snap-on, 6 turns" --output vhf_snap.pdf
```

Optional flags:

- `--vna {nanovna,hp}` — driver selection (default nanovna)
- `--port /dev/ttyACM1` — NanoVNA serial path
- `--host 10.1.1.70` — HP KISS-488 host
- `--points N` — sweep points (NanoVNA max 401, HP max 801; default 401)
- `--average N` — software-average N sweeps (default 4)
- `--power DBM` — HP source power; ignored on NanoVNA
- `--target OHMS` — horizontal target line on the |Z| panel
  (commonly 2000 Ω for HF, 5000 Ω for excellent)

## Output

Single-page PDF with two panels:

- **Top:** |Z| in ohms on a semilog Y axis. Faint reference lines at
  1000, 2000, 5000 Ω. Optional target line. Peak |Z| annotated.
- **Bottom:** R (real, resistive losses — what dissipates heat) and X
  (reactive — what bounces back) on a linear axis, with a zero-line.
  Inductive (positive X) below resonance; capacitive (negative X)
  above.

## Notes

- This is a CM-impedance measurement, not a differential one. It tells
  you whether the choke chokes; it does not characterise the choke as
  a 1:1 voltage balun.
- The series-through method is most accurate when the choke's |Z|
  ranges roughly Z0/10 … Z0·1000 (5 Ω – 50 kΩ). At |Z| ≪ 50 Ω the
  measurement is noise-dominated; at |Z| ≫ 50 kΩ S21 → 0 and again the
  noise floor matters. The choke peak almost always falls in the
  reliable band.
- NanoVNA dynamic range (~50–70 dB) is enough for routine choke work.
  For very-high-Q chokes (|Z| peaks past 20 kΩ) the noise floor will
  flatten the top of the |Z| peak. Try more `--average`, then drop
  back to the HP 8712B once it's online.
- **Fixture matters.** A bad fixture (long leads, missing shield
  bonding) adds parasitic inductance/capacitance that flattens or
  shifts the peak. Cal-out and verify with a known choke before
  trusting absolute numbers.
