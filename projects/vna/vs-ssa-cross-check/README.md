# vs-ssa-cross-check — VNA dBFS → SSA dBm offset table

Drive an SDG into a directional coupler; route the through arm to
the NanoVNA, the coupled arm to an SSA3032X. The SSA gives absolute
dBm; the NanoVNA gives relative S21 dB. The difference, per
frequency, is the calibration offset that converts NanoVNA readings
to absolute dBm.

**⚠ Untested against hardware.** SCPI commands target Siglent SSA
syntax; verify against your specific firmware version.

## Setup

```
SDG  ── coupler ─┬─ SSA3032X (absolute)
                 └─ NanoVNA port 2 (relative)
```

## Usage

```bash
python vs_ssa_cross_check.py --start 1 --stop 1500 --n 31 \
    --ssa-host 10.1.1.60 --output offset.csv --plot offset.pdf
```

## Output

CSV: `freq_hz, vna_s21_db, ssa_dbm, offset_db` per cal frequency.
Optional PDF of offset vs frequency.

## Notes

- The script does NOT drive the SDG — set it externally (or wrap in
  a shell script that does).
- For absolute power downstream, load this CSV and interpolate
  `offset(f)` then add to NanoVNA S21 readings.
- Re-run periodically; the offset drifts with NanoVNA cal cycle.
