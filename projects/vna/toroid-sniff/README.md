# toroid-sniff — Wound-toroid characterisation: L, Q, mix suggestion

Wind N turns through a toroid, drop it into the same series-through
fixture used by [`../choke-pdf/`](../choke-pdf/), and the script returns:

- **L** at the lowest sweep frequency (a usable "DC" inductance)
- **Al** = L / N² in nH/N² — handy for re-using the core later
- **Q vs frequency** with peak f₀ and Q-peak annotated
- A short list of ferrite / iron mixes whose published optimum Q
  range contains the measured Q-peak — a sanity check that you wound
  the *right* core, not the spare from the wrong drawer.

Works with either of the swappable VNA drivers:

- `rf_bench.nanovna.NanoVNA` — **default**, USB CDC at `/dev/ttyACM1`
- `rf_bench.hp.HP8712B` — KISS-488 Ethernet-GPIB at `10.1.1.70`

## Setup

```
VNA Port 1 ── [SMA centre pin → toroid winding → SMA centre pin] ── VNA Port 2
                            (shield continuous; toroid in series)
```

Calibrate THRU (or full SOLT) on the bare fixture first. The whole
point is to subtract the fixture so the trace shows only the wound
core.

## Usage

```bash
# 10 turns on an unknown core, 1–50 MHz
python toroid_sniff.py --start 1 --stop 50 --turns 10 \
    --label "Unknown FT-50, 10t" --output ft50_unk.pdf

# 12 turns FT240-43, hunt for HF Q-peak
python toroid_sniff.py --start 1 --stop 30 --turns 12 \
    --label "FT240-43, 12t #20 enam" --output ft240_43_12t.pdf

# 24 turns on a T50-2 (red iron powder), 5–60 MHz
python toroid_sniff.py --start 5 --stop 60 --turns 24 \
    --label "T50-2, 24t" --output t50_2.pdf
```

Optional flags:

- `--vna {nanovna,hp}` — driver selection (default nanovna)
- `--port /dev/ttyACM1` — NanoVNA serial path
- `--host 10.1.1.70` — HP KISS-488 host
- `--turns N` — **required**; number of turns wound on the core
- `--points N` — sweep points (NanoVNA max 401, HP max 801; default 401)
- `--average N` — software-average N sweeps (default 4)
- `--power DBM` — HP source power; ignored on NanoVNA

## Output

Single-page PDF with three stacked panels and a summary block:

1. **|Z|, R, X** in ohms — broad-strokes "what's this core doing"
2. **L_eff = X / 2πf** in µH (log frequency axis) — flat region at low
   freq = the "good" inductive range; rising/falling = self-resonance
   or core loss territory.
3. **Q = X / R** with the peak annotated.
4. **Summary block** in the lower-left of panel 3:
   - Turns wound
   - L at the start of the sweep
   - Al in nH/N² (so you can re-use the same core for a different
     turn count later)
   - Q peak and frequency
   - Mix(es) consistent with that Q peak

## Mix library (consistency, not authority)

| Name      | Optimum Q range  | Family                     |
|-----------|------------------|----------------------------|
| Mix 77    | 10 kHz – 1 MHz   | MnZn ferrite               |
| Mix 31    | 0.5 – 10 MHz     | NiZn ferrite (LF chokes)   |
| Mix 43    | 1 – 30 MHz       | NiZn ferrite (HF baluns)   |
| Mix 61    | 10 – 50 MHz      | NiZn ferrite (VHF chokes)  |
| Mix 2     | 1 – 30 MHz       | Powdered iron, red         |
| Mix 6     | 10 – 90 MHz      | Powdered iron, yellow      |

A "consistent" hit is just an overlap between the measured Q peak and
the manufacturer's published optimum. Multiple mixes can be
consistent with the same Q peak (e.g. Mix 43 and Mix 2 both peak in
the same HF range — they're distinguished by Al and saturation
behaviour, neither of which this small-signal sweep exercises).

## Notes

- This is a small-signal, near-zero-power measurement. Real RF
  transformer cores get hot in service; their hysteresis losses scale
  with B-field, which this measurement does not exercise. Mix
  suggestion is "did you wind the expected mix?" — not "will it
  handle 1.5 kW key-down."
- The L estimate at the lowest sweep frequency is most accurate when
  X > 0 (inductive) and R ≪ X (low loss). Start your sweep well
  below the core's Q-peak frequency for the best L₀.
- For very low-inductance windings (1–2 turns on a small core), the
  fixture's parasitic inductance becomes comparable to the DUT. Run
  the SOLT calibration *thoroughly* and validate with a
  known-inductance reference (a precision air-core inductor) before
  trusting absolute Al numbers.
