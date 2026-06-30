# mode-decomp-pdf — Mode decomposition of S-params

Spatial FFT of an S-parameter trace to identify mode-pair beat
frequencies in overmoded coax / waveguide. Peaks in the FFT
correspond to discrete propagation-velocity differences.

**⚠ Untested. Niche use.** Most ham coax stays well below TE/TM mode
cutoff. Useful above ~30 GHz where typical cable modes propagate.

## Usage

```bash
python mode_decomp_pdf.py --input waveguide.s2p --vf 0.95 \
    --label "WR-90 waveguide section" --output modes.pdf
```

## Output

PDF: log-scale spatial-FFT magnitude vs equivalent propagation
length (m). Strong peaks indicate distinct propagating modes.

## Notes

- For single-mode cables (most coax up to ~20 GHz) the trace shows
  only one strong peak at the physical electrical length.
- Effective at exposing the existence of moded propagation, not at
  quantifying mode powers.
