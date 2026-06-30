# amplifier-curve — Amplifier S-params vs DC bias

For each Vds value, set the PSU, capture all four S-params via
`../sparams-pdf/`, log Id and the Touchstone path to CSV.

**⚠ Untested against hardware.** Requires:

- `rf_bench.siglent.SPD3303X` driver (working today)
- A bias-tee fixture so the PSU can power the amp while the VNA
  measures S-params

## Usage

```bash
python amplifier_curve.py --psu-host 10.1.1.56 \
    --vds 3.0 3.3 3.6 4.0 \
    --start 100 --stop 1500 --f0 432 \
    --label "BFP840 MMIC" --out-dir ~/biasrun/
```

## Output

- One `.s2p` and `.pdf` per Vds point (via sparams-pdf)
- A CSV indexing the run

## Notes

- Add stability circles and K-factor extraction by post-processing
  the .s2p files (future work).
- For full I-V tracing, use `projects/components/iv-tracer/` instead.
