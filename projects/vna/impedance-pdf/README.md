# impedance-pdf — Full one-port impedance / antenna diagnostic PDF

S11 sweep on VNA port 1 → R + jX, |Z| + ∠Z, VSWR, and Smith locus —
all in one multi-panel single-page PDF. Optional **resonance hunting**
finds every X = 0 crossing (series / parallel) inside the sweep.

This project **supersedes** the legacy `../antenna/` and
`../impedance/` directories (both of which were HP-only stubs that
did different subsets of the same job). Use it for:

- Antennas — feed-point Z, VSWR, where it resonates, what to design
  the matching network against
- Filter input / output impedance into a 50 Ω load
- Tank circuits, traps, helical resonators
- Anything one-port where you want one PDF that tells you everything
  the VNA can about it

For simpler one-panel views, the focused tools still exist:

- [`../swr-pdf/`](../swr-pdf/) — VSWR only
- [`../return-loss-pdf/`](../return-loss-pdf/) — RL dB only
- [`../smith-pdf/`](../smith-pdf/) — Smith only
- [`../resonance-finder/`](../resonance-finder/) — auto-detect S11 dips
  and characterise Q (different math: dips in |S11| not X=0 crossings)

Works with either of the swappable VNA drivers:

- `rf_bench.nanovna.NanoVNA` — **default**, USB CDC at `/dev/ttyACM1`
- `rf_bench.hp.HP8712B` — KISS-488 Ethernet-GPIB at `10.1.1.70`

## Setup

```
VNA Port 1 ──BNC / SMA──→ DUT (antenna, network, ...)
```

1-port SOLT calibration over the same sweep range first.

## Usage

```bash
# HF dipole — full sweep with resonance hunting
python impedance_pdf.py --start 1 --stop 30 --resonances \
    --label "40 m dipole at 30 ft" --output 40m_dipole.pdf

# 2 m vertical, with Smith
python impedance_pdf.py --start 140 --stop 150 --resonances \
    --label "2 m vertical, ground-plane" --output 2m_vert.pdf

# Filter input impedance (drop the Smith panel for a portrait-style PDF)
python impedance_pdf.py --start 9.0 --stop 11.0 --no-smith \
    --label "9 MHz crystal filter input Z" --output xtalin.pdf

# Tank circuit, narrow sweep
python impedance_pdf.py --start 7.0 --stop 7.3 --points 401 --average 4 \
    --resonances --label "40 m tank" --output tank.pdf
```

Optional flags:

- `--vna {nanovna,hp}` — driver selection (default nanovna)
- `--port /dev/ttyACM1` — NanoVNA serial path
- `--host 10.1.1.70` — HP KISS-488 host
- `--points N` — sweep points (NanoVNA max 401, HP max 801; default 401)
- `--average N` — software-average N sweeps (default 2)
- `--power DBM` — HP source power; ignored on NanoVNA
- `--resonances` — locate every X = 0 crossing and annotate
- `--no-smith` — drop the Smith-chart panel (portrait-style PDF)

## Output

Three- or four-panel PDF:

1. **R + X vs frequency** — the headline panel for antenna / matching
   work. R = resistive part (what radiates / dissipates), X = reactive
   part (+ind / −cap). 0 Ω line shown. 50 Ω line shown.
2. **|Z| (log) + ∠Z (twin axis)** — magnitude and phase of the
   impedance vector. The log Y on |Z| spans 10×–100× without rescaling.
3. **VSWR** with 1.5 / 2 / 3 reference lines; best-VSWR marker with
   the equivalent RL printed.
4. **Smith chart** with frequency-coloured Γ locus (unless `--no-smith`).

If `--resonances` is given, every X = 0 crossing is drawn as a faint
vertical dashed line on the R+X panel, and listed in the console
(frequency, R at the crossing, and a `series`/`parallel` hint based on
the magnitude of R there).

## NanoVNA vs HP — one-port-impedance specific notes

- **Where they're equivalent:** any DUT where the impedance falls
  within ~5–500 Ω (|Γ| < 0.9). The NanoVNA's S11 is already well-
  calibrated in this region; both VNAs return numbers that agree to
  ~1–2 % after a good SOLT.
- **Where the HP wins:** very high |Z| (small antennas around an
  off-band resonance, parallel-resonant tanks, etc.) where Γ → 1
  amplifies any calibration residual. The HP's tighter directivity
  (~40 dB vs the NanoVNA's ~30 dB) gives noticeably less wobble on
  the impedance trace at the edges of the Smith chart.
- **Where the NanoVNA wins:** anything portable. Antenna at the
  feedpoint, antenna at the top of the tower with a laptop on a
  battery pack — physically impossible with the rack-bound HP.
- **Smith locus colour scale:** identical math on both VNAs — the
  Smith panel here uses the same code as `../smith-pdf/`.

## Notes

- "Series" vs "parallel" classification of X=0 crossings is a heuristic
  based on R at the crossing. R ≤ 250 Ω → series; R > 250 Ω →
  parallel. For RF antennas the heuristic works well; for filters and
  matching networks, just look at the R+X panel directly.
- The first and last sweep samples participate in the X=0 search but
  are most prone to edge effects. Sweep slightly wider than the band
  of interest.
- For very-high-VSWR conditions, the VSWR panel saturates at 10:1 to
  keep the chart readable. The R + jX panel still shows the truth.
