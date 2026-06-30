# antenna-pattern — Polar radiation pattern via VNA + rotator

For each commanded azimuth angle, capture S21 of (reference antenna →
DUT antenna). The angle-vs-magnitude curve is the polar pattern.

**⚠ Untested against hardware.** Requires:

- A rotator with SCPI control (uses the rf-bench `scpi-rotator` ESP32
  project's `:SERV:POS <deg>` command by default; adapt to your gear).
- A 1+ λ separation between reference and DUT antennas.
- Ideally an anechoic chamber; in open-field test setups, multipath
  distorts the result especially away from boresight.

## Usage

```bash
python antenna_pattern.py --freq 144.5 \
    --rotator-host 10.1.1.45 --rotator-port 5025 \
    --az-start 0 --az-stop 360 --az-step 5 \
    --label "5/8 wave whip" --output whip_pattern.pdf
```

## Flags

- `--vna`, `--port`, `--host`
- `--rotator-host`, `--rotator-port` (default 5025)
- `--freq MHZ` — test frequency
- `--az-start`, `--az-stop`, `--az-step`
- `--settle SEC` (default 2)
- `--average N` (default 4)
- `--label`, `--csv`, `--output`

## Output

- Polar PDF (normalised to peak)
- Optional CSV with raw `az_deg, s21_db`

## Notes

- The reference antenna's pattern is *not* de-embedded. Use an
  approximately-isotropic reference (a thin dipole) for honest
  patterns.
- For 3D / elevation patterns, you need a 2-axis rotator and to
  outer-loop over elevation, capturing one azimuth sweep per
  elevation step.
