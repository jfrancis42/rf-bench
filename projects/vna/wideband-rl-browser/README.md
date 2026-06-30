# wideband-rl-browser — Interactive wideband S11 viewer

Multi-segment full-range S11 sweep + interactive HTML page (Plotly).
Open the result in any browser; zoom, pan, hover for values.

## Usage

```bash
python wideband_rl_browser.py --start 0.05 --stop 1500 \
    --output ~/site.html
```

Then open `~/site.html` in any browser.

## Flags

- `--vna`, `--port`, `--host`
- `--start MHZ` / `--stop MHZ` (default 0.05–900 MHz)
- `--seg-points N` / `--n-segments N`
- `--average N`
- `--output FILE.html`

## Output

Self-contained HTML (Plotly bundled). Fallback to a static SVG-only
page if Plotly isn't installed; install with
`pip install plotly --break-system-packages` for the interactive
version.

## Notes

- Captures S11 only. For combined S11+S21 in HTML form, run
  `../multi-segment-sweep/` and feed the .s2p into an external Plotly
  script.
