# filter-tuning — Live S21 with target overlay

Continuously sweeps S21 on the VNA and shows the live trace in a
matplotlib window with an optional **target shape** overlaid. Useful
for tuning crystal / cavity / LC filters by hand: glance at the
chart, twist the screw, repeat.

This is the only "long-running interactive" tool in the VNA project
tree — every other one writes a single PDF and exits.

## Target options

### `--target FILE.s2p`

Overlays a previously-measured filter response (e.g. a golden
reference filter) as a dashed green line. Use for batch-tuning
identical units against the same spec.

### `--target FILE.json`

Loads a spec mask:

```json
{
  "passband_mhz": [9.998, 10.002],
  "max_passband_loss_db": -3.0,
  "stopband_mhz": [[9.990, 9.995], [10.005, 10.010]],
  "min_stopband_atten_db": -40.0
}
```

The passband is shaded green; the stopband is shaded red. Reference
loss lines are drawn at the passband/stopband levels.

## Usage

```bash
# Tune a 10 MHz crystal filter against a 5 MHz centred passband mask
python filter_tuning.py --start 9.99 --stop 10.01 \
    --target tune_mask.json
```

Press Ctrl-C (or close the window) to exit.

## Flags

- `--vna {nanovna,hp}`, `--port`, `--host`
- `--start MHZ` / `--stop MHZ`
- `--points N` (default 401)
- `--target FILE` (`.s2p` or `.json`; optional — without target, just
  shows live trace)
- `--refresh SEC` (default 0.5)

## Notes

- **Requires an interactive matplotlib backend.** Runs fine in a
  desktop session; fails in a headless / cron environment.
- One sweep per `--refresh` interval. At 0.5 s on a NanoVNA-F, the
  full 401-point sweep latency may dominate the refresh rate.
- The target spec file format isn't strictly defined — the script
  treats unrecognised keys as a no-op, so you can extend it.
