# renormalize-pdf — Re-reference S-params from one Z₀ to another

Pure post-processor. Takes a Touchstone `.s2p` measured at 50 Ω and
rewrites it as the same DUT in a different system impedance.

Why care:

- 50-Ω VNA, **75-Ω** DUT (CATV, SDI, video) → 50-Ω VSWR overreads
  the mismatch. Renormalise to 75 Ω to see real-world VSWR.
- 50-Ω VNA, **100-Ω** differential pair (LVDS, USB) → measured S11
  / S22 lie because they're referenced to the wrong impedance.
- 50-Ω VNA, **600-Ω** ladder line / antenna → S11 always looks bad
  even when the line is perfectly matched into its own system.

## Usage

```bash
# CATV measurement: re-reference to 75 Ω
python renormalize_pdf.py --input cable_50ohm.s2p \
    --target-z 75 --label "CATV barrel adapter at 75 Ω" \
    --output cable_75.pdf

# Differential pair: re-reference to 100 Ω
python renormalize_pdf.py --input diff_pair_50.s2p \
    --target-z 100 --label "LVDS pair at 100 Ω" \
    --output lvds.pdf

# 600-Ω ladder line
python renormalize_pdf.py --input ladder_50.s2p \
    --target-z 600 --label "OWL antenna at 600 Ω" \
    --output ladder.pdf
```

Flags:

- `--input DUT.s2p` — **required**; input Touchstone at the VNA's
  native impedance.
- `--target-z OHMS` — **required**; new system impedance in Ω.
- `--label TEXT` — chart title text.
- `--output FILE.pdf` — **required**; PDF path.
- `--touchstone FILE.s2p` — optional explicit Touchstone path
  (defaults to `<output>.s2p`).

## Output

PDF: 2 × 2 grid (one per S-parameter). For each, the original (50-Ω)
trace is dashed-grey and the renormalised trace is solid-blue, both
in dB magnitude.

Touchstone: standard `.s2p` MA format with the new Z₀ header.

## Math

Bilinear transform with reflection coefficient Γ:

```
Γ = (Z_new - Z_old) / (Z_new + Z_old)
S_new = (S_old - Γ·I) · (I - Γ·S_old)^-1
```

For real Z₀ values (typical), the simple form above is exact. The
implementation also works with complex reference impedances (rare
in ham bench work, but supported).

## Notes

- This **does not** change anything about the underlying DUT. It
  just tells you what the same DUT would look like to a different-
  impedance system.
- If you build a 75-Ω test fixture with a matching pad, you can
  cross-check: the renormalised result should match the new
  fixture's direct measurement to within calibration noise.
- For one-port DUTs (just S11), the math reduces to a single
  Möbius transform; this script handles it as a 2-port with
  meaningless off-diagonals.
