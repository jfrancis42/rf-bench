# return-loss-pdf — Return loss (dB) PDF chart

S11 sweep on VNA port 1 → return loss in dB → single-page PDF with an
equivalent-VSWR axis on the right edge.

This is the **logarithmic** view of the same data
[`../swr-pdf/`](../swr-pdf/) plots linearly as VSWR. Hams reading "1.5:1
is good, 2:1 is OK" prefer that view. Engineers tuning a sub-2:1 match
generally want this one — return loss spreads VSWR 1.0–1.5:1 across
∞–14 dB, where you can actually see what tuning a screw does.

Works with either of the swappable VNA drivers:

- `rf_bench.nanovna.NanoVNA` — **default**, USB CDC at `/dev/ttyACM1`
- `rf_bench.hp.HP8712B` — KISS-488 Ethernet-GPIB at `10.1.1.70`

## Setup

```
VNA Port 1 ──BNC / SMA──→ Antenna or DUT
```

Run a 1-port (OSL) calibration over the same sweep range first and
leave correction enabled.

## Usage

```bash
# 70 cm HT antenna
python return_loss_pdf.py --start 430 --stop 450  \
    --label "70cm HT" --output 70cm_rl.pdf

# HF dipole, full HF
python return_loss_pdf.py --start 3 --stop 30 \
    --label "G5RV at 30 ft" --output hf_rl.pdf

# Zoom into a single band with finer Y-axis range (default ymax 40 dB)
python return_loss_pdf.py --start 14 --stop 14.4 --ymax 50 \
    --label "20 m dipole after retune" --output 20m_rl.pdf
```

Optional flags:

- `--vna {nanovna,hp}` — driver selection (default nanovna)
- `--port /dev/ttyACM1` — NanoVNA serial path
- `--host 10.1.1.70` — HP KISS-488 host
- `--points N` — sweep points (NanoVNA max 401, HP max 801; default 401)
- `--average N` — software-average N sweeps
- `--power DBM` — HP source power; ignored on NanoVNA
- `--ymax DB` — Y-axis top in dB (default 40)

## Output

Single-page PDF with:

- **Return loss vs frequency** in dB. Higher up the chart is better.
- **Reference lines** at the four most-quoted VSWR equivalents:
  - 9.5 dB = VSWR 2.0:1 (typical "use it" threshold for SSB)
  - 14 dB = VSWR 1.5:1 (typical "use it without thinking" threshold)
  - 20 dB = VSWR 1.22:1 (good match)
  - 26 dB = VSWR 1.10:1 (excellent match — most amp manufacturers'
    auto-tune target)
- **Best-RL annotation** with the equivalent VSWR for that point
- **Secondary Y-axis** on the right edge labelled in VSWR (1.05:1,
  1.1:1, 1.2:1, 1.5:1, 2:1, 3:1)
- **Amateur band shading** for any of 160 m – 70 cm overlapping the
  sweep
- Title with DUT label, sweep range, point count, driver, IDN,
  timestamp

## When to prefer this over `../swr-pdf/`

- Fine-tuning an antenna or match network — once you're already under
  2:1, the VSWR view goes flat against the X-axis and the dB view
  shows you which way is downhill.
- Specifying an antenna or filter to the manufacturer — "≥ 20 dB
  return loss in band" is the standard wording.
- Anything with a connector or coax — connector quality is best
  measured as "how many dB of return loss," not as "what VSWR."
