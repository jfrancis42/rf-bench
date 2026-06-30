# mixed-mode-pdf — Single-ended .s4p → mixed-mode S-parameters

Take a 4-port single-ended Touchstone .s4p (typical: a differential
pair, an LVDS link, a CAT-5 segment, a transformer, a balun captured
as 4 single-ended ports) and compute the mixed-mode S-parameter
matrix:

```
S_mm = [ S_dd  S_dc ]      S_dd  : differential-to-differential
       [ S_cd  S_cc ]      S_cc  : common-to-common
                           S_dc  : common-to-differential (mode conversion)
                           S_cd  : differential-to-common (mode conversion)
```

For a well-balanced differential line:

| Quantity            | Healthy           | Bad                          |
|---------------------|-------------------|------------------------------|
| `|S_dd21|`          | ≈ 0 dB (passing)  | low → the diff line is lossy |
| `|S_cc21|`          | matches \|S_dd21\| | very different → asymmetric |
| `|S_dc21|, |S_cd21|`| ≪ −40 dB           | rises with f → EMC source / pickup |

Mode conversion is the kicker. Any geometric asymmetry between the
two halves of a "differential" line (one trace longer, different
launch parasitics, asymmetric ground reference) converts a fraction
of the signal between modes — and *that* is the mechanism by which
allegedly-balanced lines radiate, and by which "this is digital so
EMC won't be a problem" turns out to be wrong.

Pure post-processor — no hardware connection.

## Port convention

The script defaults to the most common Touchstone convention for
diff pairs:

- Pair 1 (input): ports 1 and 2
- Pair 2 (output): ports 3 and 4

Pass `--convention 1-3/2-4` to use the alternate (some EDA tools and
some VNA vendors prefer it):

- Pair 1: ports 1 and 3
- Pair 2: ports 2 and 4

If your modes look wrong (e.g., your "diff" mode is much smaller than
your "common" mode for what you know is a balanced line), the
convention is probably mismatched — try the other one.

## How to get an .s4p

The NanoVNA / HP 8712B in this monorepo are both 2-port instruments,
so a "real" 4-port capture takes 6 single-ended captures (12 if you
include the DUT-reversal trick on the NanoVNA) and a 4×4 S-matrix
build script — a future project. For now this tool consumes:

- `.s4p` from a true 4-port VNA (anyone you can borrow time on)
- `.s4p` from EDA simulation (Sonnet, HFSS, AWR, QUCS)
- `.s4p` from scikit-rf if you have one already
- The 4-port construction project (planned) once it exists in
  `projects/vna/`

## Math, in 3 lines

```
M = mode-transform matrix (4×4)
S_mm = M · S_se · M^T          (per frequency)
Split S_mm into 2×2 blocks Sdd, Sdc, Scd, Scc.
```

The transform M for the default 1-2/3-4 convention:

```
        1   [  1  -1   0   0 ]      ← d1 = (V1 - V2) / √2
M  =  ───   [  0   0   1  -1 ]      ← d2 = (V3 - V4) / √2
       √2   [  1   1   0   0 ]      ← c1 = (V1 + V2) / √2
            [  0   0   1   1 ]      ← c2 = (V3 + V4) / √2
```

Reference: Bockelman & Eisenstadt, "Combined Differential and
Common-Mode Scattering Parameters: Theory and Simulation," IEEE
Trans MTT, 1995.

## Usage

```bash
# Convert a 4-port .s4p (typical CAT5 pair sim or measurement)
python mixed_mode_pdf.py --input cat5_pair.s4p \
    --label "CAT-5e pair, 1 m" --output cat5_mm.pdf
# → writes cat5_mm.s4p alongside

# Alternate port convention
python mixed_mode_pdf.py --input my_balun.s4p \
    --convention 1-3/2-4 --label "1:4 balun, 4 SE ports" \
    --output balun_mm.pdf
```

Flags:

- `--input DUT.s4p` — **required**; single-ended 4-port Touchstone
- `--convention {1-2/3-4, 1-3/2-4}` — port-to-pair mapping (default
  `1-2/3-4`)
- `--label TEXT` — chart title text
- `--output OUT.pdf` — **required**; PDF path
- `--touchstone OUT.s4p` — optional explicit Touchstone path
  (defaults to `<output-basename>.s4p`)

## Output

**PDF** — 4 × 2 grid. Each row is one of the four important
mixed-mode S-parameters (Sdd21, Scc21, Sdc21, Scd21); left column is
magnitude in dB, right column is unwrapped phase in degrees.

**Touchstone .s4p** — the full 4×4 mixed-mode matrix written back as
Touchstone, with rows / cols in mode order [d1, d2, c1, c2]. Useful
when you want to chain mixed-mode analysis through other tools.

## NanoVNA vs HP — mixed-mode-specific notes

- Pure post-processing. The math is identical whatever the .s4p
  source.
- Where the **source VNA's** dynamic range matters: mode-conversion
  terms (Sdc21, Scd21) are usually 40–80 dB below the through term
  Sdd21. The NanoVNA's ~50–70 dB dynamic range will hit its floor
  before Sdc21 hits its real value on a well-balanced pair, so the
  reported "conversion" is dominated by VNA noise rather than DUT
  physics. For honest mode-conversion measurements on good
  differential lines, use the HP 8712B (~100 dB) as the .s4p
  source.

## Notes

- This is the canonical Bockelman / Eisenstadt mode transform. Some
  vendor tools normalize by 2 instead of √2 (Agilent ADS at one
  point did, then changed). The √2 convention used here matches
  scikit-rf, modern Keysight tools, and AWR.
- For 8-port DUTs (two coupled pairs), generalisations exist but
  aren't implemented here. Manually decompose into multiple 4-port
  captures.
- Verified against a synthetic ideal-diff-pair .s4p: Sdd21 round-
  trips to 0.00 dB; all other terms sit on the numerical noise floor
  (~−240 dB).
