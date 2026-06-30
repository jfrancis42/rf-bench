# cepstral-pdf — Cepstral analysis of S-params

The cepstrum (inverse FFT of log-magnitude) separates discrete cable
reflections — which become sharp cepstral peaks — from distributed
losses, which appear as a slowly-decaying baseline. Useful when
ordinary TDR can't resolve two closely-spaced reflections.

## Usage

```bash
python cepstral_pdf.py --input cable.s2p --parameter S11 \
    --vf 0.66 --label "RG-58 feedline" --output ceps.pdf
```

## Output

Two-panel PDF (real cepstrum, |complex cepstrum|) vs quefrency,
labelled in metres (or feet with `--feet`) using the supplied VF.
Dominant cepstral peak past 1 m is annotated.

## Flags

- `--input FILE.s2p`
- `--parameter` (default S11)
- `--vf VF` (default 0.66)
- `--feet`
- `--interp N` (default 4)
- `--label`, `--output`

## Notes

- Pure post-processor.
- Cepstral peaks at integer multiples of one base distance often
  indicate a single strong reflection (the higher cepstral peaks
  are harmonics of the base period).
- For straight fault-distance work, prefer `../tdr-pdf/`. Use this
  when you need to disambiguate periodic structure.
