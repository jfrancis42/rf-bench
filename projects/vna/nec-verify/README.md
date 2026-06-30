# nec-verify — Compare measured S11 to NEC-2 simulation

Overlay measurement vs NEC-2 (4nec2 / cocoaNEC / xnecview)
prediction. Disagreement diagnoses model error: wrong height, wrong
wire size, missing ground, missing nearby objects.

**⚠ Untested.** Expects the NEC output as a plain text file with
columns `f_MHz, R, X, ...`. Most NEC tools can dump this; check
your version.

## Usage

```bash
python nec_verify.py --measured antenna.s1p --nec antenna_sim.txt \
    --label "40 m loop" --output verify.pdf
```

## Output

Stacked |S11| (dB) and phase (°) panels showing measured (blue) vs
simulated (red dashed).

## Flags

- `--measured FILE.s1p` — measured Touchstone
- `--nec FILE.txt` — NEC-2 frequency table
- `--z0` — system impedance (default 50)
- `--label`, `--output`

## Notes

- A 1–2 % frequency offset between measured and simulated is common
  and usually due to feedline reactance not included in the NEC
  model. De-embed your feedline first (`../de-embed-pdf/`) for a
  clean comparison.
