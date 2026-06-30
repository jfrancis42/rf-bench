# multi-segment-sweep — Wideband sweep stitching

The NanoVNA caps at 401 points per sweep. For HF-to-UHF coverage at
fine resolution (~10 kHz / point or finer), you need many narrow
sweeps. This tool runs them sequentially and stitches the results
into one wide-band Touchstone .s2p + PDF.

The HP 8712B has its own internal sweep up to ~1601 points; with
`--vna hp` this just runs one big sweep.

## Usage

```bash
# 1–1500 MHz at ~3.7 MHz resolution (15 segments of 401 points each)
python multi_segment_sweep.py --start 1 --stop 1500 \
    --label "Full NanoVNA span" --output wideband.pdf

# Custom segment count
python multi_segment_sweep.py --start 1 --stop 30 --n-segments 10 \
    --label "HF antenna fine sweep" --output hf.pdf
```

## Output

PDF: stacked |S11| and |S21| panels with thin vertical lines at the
segment boundaries (so you can see whether your calibration
discontinuity is visible there).

`.s2p`: standard Touchstone, S12/S22 = 0 (this is a single-pass tool;
for full 4-S-param wideband captures, run this through
[`../sparams-pdf/`](../sparams-pdf/) with the DUT-reversal trick).

## Flags

- `--vna {nanovna,hp}`, `--port`, `--host`
- `--start MHZ` / `--stop MHZ`
- `--seg-points N` (default 401)
- `--n-segments N` (auto if omitted)
- `--average N` (default 2)
- `--label`, `--output`, `--touchstone`

## Notes

- **Edge discontinuities** between segments are NOT smoothed. If
  your calibration is identical across segments, edges will be
  invisible. If you can see them, the cal is segment-dependent —
  calibrate over the same span you're going to sweep.
- For at-the-feedpoint antenna tests, run this once per visit and
  archive the `.s2p`. Year-over-year comparisons immediately show
  cable degradation.
