# balun-pdf — Balun amplitude / phase balance + insertion loss PDF

A balun has three measurements that matter:

1. **Input return loss** — how well it presents Z₀ on the unbalanced
   side.
2. **Insertion loss** — how much signal it eats per leg.
3. **Amplitude / phase balance** — how matched the two output legs
   are. The whole point of a balun is the balance.

This script captures all three using a single 2-port VNA in a two-pass
swap-and-repeat workflow. It prompts you between passes; the only
adapters you need are a 50-Ω termination and whatever fixturing maps
your balun's screw terminals to SMA / BNC.

Works with either of the swappable VNA drivers:

- `rf_bench.nanovna.NanoVNA` — **default**, USB CDC at `/dev/ttyACM1`
- `rf_bench.hp.HP8712B` — KISS-488 Ethernet-GPIB at `10.1.1.70`

## Setup

The balun is treated as a 3-port device: input (unbalanced), leg A,
leg B.

**Pass A:**
```
VNA Port 1 ────── IN  (unbalanced side)
VNA Port 2 ────── A   (one leg of the balanced side)
50-Ω load  ────── B   (the other leg)
```

**Pass B (after the prompt):**
```
VNA Port 1 ────── IN
VNA Port 2 ────── B   ← swap to leg B
50-Ω load  ────── A   ← swap to leg A
```

Calibrate THRU on the VNA over the same sweep range before pass A.
Use a known-good resistive 50-Ω termination; a sloppy load
contaminates both passes.

## Usage

```bash
# 1:1 current (Guanella) balun, HF
python balun_pdf.py --start 1 --stop 30 \
    --label "1:1 current balun, FT240-43" --output balun_1to1.pdf

# Centre-tap voltage balun — legs are nominally 180° out of phase
python balun_pdf.py --start 3 --stop 30 --phase-180 \
    --label "Centre-tap 1:1 voltage balun" --output ctv_balun.pdf

# Capture pass A on the bench, then pass B at a later session
python balun_pdf.py --start 1 --stop 30 --save-A passA.npz \
    --label "..." --output unused.pdf
# ... swap to leg B, then ...
python balun_pdf.py --start 1 --stop 30 --load-A passA.npz \
    --label "..." --output balun_1to1.pdf
```

Optional flags:

- `--vna {nanovna,hp}` — driver selection (default nanovna)
- `--port /dev/ttyACM1` — NanoVNA serial path
- `--host 10.1.1.70` — HP KISS-488 host
- `--points N` — sweep points (NanoVNA max 401, HP max 801; default 401)
- `--average N` — software-average N sweeps (default 2)
- `--power DBM` — HP source power; ignored on NanoVNA
- `--phase-180` — centre-tap voltage balun. Default is 0° (current
  balun), where both legs are nominally in-phase.
- `--save-A FILE.npz` / `--load-A FILE.npz` — capture pass A and
  combine later. Useful for a deliberate fixture swap.
- `--no-prompt` — skip the "press Enter" pauses (use only when the
  swap is automated via relays).

## Output

Single-page PDF with four stacked panels sharing a frequency axis:

1. **Return loss** (dB) — average of the two passes' S11. Reference
   lines at 14 dB and 20 dB.
2. **Insertion loss** (dB, inverted axis) — leg-A and leg-B raw S21,
   plus the combined effective insertion loss `(IL_per_leg − 3 dB)`.
   Reference line at 0.5 dB.
3. **Amplitude balance** (dB) — `20·log10(|S21_A|/|S21_B|)`.
   Reference lines at ±0.5 dB.
4. **Phase balance** (degrees) — `∠S21_A − ∠S21_B − nominal`,
   wrapped to ±180°. Reference lines at ±5°.

## Targets

For a good wideband HF balun:

| Metric            | Target           |
|-------------------|------------------|
| Return loss       | ≥ 14 dB           |
| Insertion loss    | ≤ 0.5 dB          |
| Amplitude balance | ≤ ±0.5 dB         |
| Phase balance     | ≤ ±5° (around nominal) |

## Notes

- This measurement is the "S21 per leg" method described in K9YC's
  excellent ARRL guide. It's the right approach for ham-grade work.
  For lab-grade balun characterization (matched 4-port S-parameters,
  mode-conversion S-parameters), you need a true 4-port VNA.
- A balun with poor balance is often diagnostic of a bad connection
  on one leg, a partly-shorted choke turn, or core saturation at high
  drive. None of those show up clearly in a return-loss-only sweep.
- The Y-axis of the insertion-loss panel is inverted so the trace
  "rises" toward better performance, matching engineer intuition that
  more loss is worse.
- The phase axis subtracts a *nominal* of either 0° or 180° before
  plotting; the trace shows the *deviation* from ideal, not the
  absolute phase difference.
