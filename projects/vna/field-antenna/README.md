# field-antenna — Minimal at-the-antenna capture tool

One command, sensible defaults, immediate PDF + .s1p output with
UTC-timestamped filenames so trips don't overwrite each other.

## Usage

```bash
python field_antenna.py --start 1 --stop 30 --label "G5RV at 30 ft"
# → 20260630T173000Z_G5RV_at_30_ft.s1p
# → 20260630T173000Z_G5RV_at_30_ft.pdf
```

## Output

`.s1p` Touchstone (MA format, 50 Ω) and a two-panel PDF (VSWR + R+jX).

## Flags

- `--vna {nanovna,hp}`, `--port`, `--host`
- `--start MHZ` / `--stop MHZ` / `--points` / `--average`
- `--label TEXT` — used in filenames AND as PDF title
- `--out-dir DIR` — output directory (default cwd)

## Notes

When you want full diagnostics, use `../impedance-pdf/`. This is the
"quick capture" tool for tower visits.
