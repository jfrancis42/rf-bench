# antenna-factor-pdf — Derive AF (dB/m) for a calibrated field probe

Antenna factor: how many dB/m to add to a receiver reading to get
the actual electric field strength. Required when using an antenna
as an absolute field-strength probe (EMC measurements, propagation
campaigns, etc.).

**⚠ Untested against hardware.** Uses the standard formula
`AF = 20·log10(9.73 / (λ · √G_lin))` plus a measured mismatch-loss
term from S11.

## Usage

```bash
python antenna_factor_pdf.py --start 30 --stop 1000 --gain-db 2.15 \
    --label "λ/2 dipole" --output dipole_AF.pdf
```

## Output

PDF: AF dB/m vs frequency, with both the theoretical (perfect-match)
and the as-measured (match-corrected) curves.

## Flags

- `--vna`, `--port`, `--host`
- `--start MHZ` / `--stop MHZ`
- `--gain-db` — antenna gain in dBi (from datasheet or NEC sim)
- `--label`, `--output`

## Notes

- Assumes a 50-Ω-feed antenna. For non-50-Ω antennas, use
  `../renormalize-pdf/` first.
- The mismatch correction assumes the antenna is the only mismatch
  in the chain.
