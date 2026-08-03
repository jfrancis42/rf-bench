# Clamp Current Logger — Fluke 80i-400 + bench DMM

Measure and log AC current through a **Fluke 80i-400** clamp using any rf-bench
DMM as the readout. The 80i-400 is a passive current transformer that outputs
**1 mA per amp** (1000:1) into the meter's current jacks; this project applies
that conversion plus the datasheet ±(3 % + 0.4 A) accuracy model.

## Connections

```
conductor under test ──► clamp inside the 80i-400 jaws (ONE wire only)
80i-400 banana plugs ──► DMM CURRENT (mA) input   ← NOT the volts input
DMM ──► AC current, true-RMS, mA range reaching 400 mA
```

Clamp only a single conductor — if you clamp both wires of a mains pair the
opposing fields cancel and you read ~zero. At 400 A the probe sources 400 mA;
make sure the meter's mA range and fuse cover it.

## Usage

```bash
# Live read via the inventory DMM named "sdm", 1 Hz:
python clamp_current.py

# 2 Hz, log to CSV:
python clamp_current.py --interval 0.5 --csv run.csv

# Different inventory DMM:
python clamp_current.py --dmm sdm3045

# No instrument — just convert a meter reading you took by hand (240 mA -> A):
python clamp_current.py --ma 240
```

## Notes

- Meter-agnostic: the clamp driver only calls the DMM's `measure_iac()`
  (amperes), so any rf-bench DMM driver works.
- The 80i-400 is AC-only (48–1000 Hz). DC is not datasheet-specified.
- Readings outside the 1–400 A range are flagged `<OUT OF SPEC>` and their
  uncertainty is reported as unavailable.

See `rf_bench.fluke` (`drivers/fluke/`) for the conversion/accuracy layer.
