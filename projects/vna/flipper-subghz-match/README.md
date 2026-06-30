# flipper-subghz-match — Flipper Sub-GHz antenna match check

Sweeps S11 across the Flipper Zero's three Sub-GHz regulatory bands
(300–348 / 387–464 / 779–928 MHz) and reports best-match frequency
per band.

**⚠ Untested against hardware.** Just unplug the antenna from the
Flipper and connect it to VNA port 1. No software talks to the
Flipper.

## Usage

```bash
python flipper_subghz_match.py --label "Flipper stock 433 MHz whip" \
    --output stock.pdf

# Single band only
python flipper_subghz_match.py --bands mid --label "433-only whip" \
    --output 433.pdf
```

## Flags

- `--vna`, `--port`, `--host`
- `--bands {low,mid,high,all}` — pick subsets (default all)
- `--threshold-db DB` — RL pass threshold (default 10 dB ≈ VSWR 1.92)
- `--label`, `--output`

## Output

One panel per band, RL vs frequency, with the best-match marker.

## Notes

- For pass/fail per channel, post-process with `../connector-check/`.
- 50 Ω-only check — Flipper antennas are 50 Ω.
