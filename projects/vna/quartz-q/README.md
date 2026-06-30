# quartz-q — Focused crystal Q from S21

Series-resonance Q only, via 3-dB BW method on |S21|. Fast batch-
sorting alternative to the full BVD extraction in
[`../crystal-bvd-pdf/`](../crystal-bvd-pdf/).

## Usage

```bash
# 10 MHz crystal, ±250 ppm sweep
python quartz_q.py --estimate 10.0 --label "HC-49 #4" --output q4.pdf
```

## Output

PDF: |S21| dB vs kHz with f0 marker and Q in the title.

## Flags

- `--vna`, `--port`, `--host`
- `--estimate MHZ` — required; series-resonance estimate
- `--span-ppm` — sweep span (default 500 ppm = ±250 ppm)
- `--points` (default 401), `--average` (default 8)
- `--label`, `--output`

## Notes

- Loaded Q only. For unloaded Q multiply by 1/(1 - 10^(depth/20)),
  using the depth of the dip below the off-resonance baseline.
- For Lm/Cm/Rm/C0 extraction use `../crystal-bvd-pdf/`.
