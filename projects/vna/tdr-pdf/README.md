# tdr-pdf — Time-Domain Reflectometry from S11

Frequency-domain VNAs do TDR by inverse-FFT'ing S11 into the time
domain. The NanoVNA's on-device TDR display is doing exactly this in
firmware; this script runs the math in Python so:

- it works on **any VNA** that returns complex S11 (NanoVNA-F, HP 8712B,
  any future driver that conforms to the swappable API);
- the output is an annotated single-page PDF with both step and
  impulse responses;
- you can choose your window, interpolation factor, velocity factor,
  and units in feet or metres;
- the largest fault past a dead zone is auto-identified, sized, and
  classified as open-like / short-like / small-mismatch.

Works with either of the swappable VNA drivers:

- `rf_bench.nanovna.NanoVNA` — **default**, USB CDC at `/dev/ttyACM1`
- `rf_bench.hp.HP8712B` — KISS-488 Ethernet-GPIB at `10.1.1.70`

## Setup

```
VNA Port 1 ──BNC / SMA──→ cable / DUT under test
```

The far end of the cable can be:

- **open** — most informative for fault-finding on a feedline. Any
  intermediate mismatch shows up as a separate reflection.
- **shorted** — equally informative; flips the polarity of every
  reflection.
- **a real antenna** — useful when you want to confirm "the antenna is
  where I think it is" by counting cable length.

OSL-calibrate at port 1 across the same sweep range first. Without
calibration the port-1 connector reflection swamps the front of the
trace; the dead-zone defaults work but you'll have less head-room.

## Usage

```bash
# 1.5 GHz NanoVNA-F sweep on RG-58, find any fault out to ~40 m
python tdr_pdf.py --start 0.05 --stop 900 --cable RG-58 \
    --label "50 ft RG-58 attic run" --output rg58_attic_tdr.pdf

# Same in feet:
python tdr_pdf.py --start 0.05 --stop 900 --cable RG-58 --feet \
    --label "50 ft RG-58 attic run" --output rg58_attic_tdr.pdf

# Hunt for a fault on a long LMR-400 run, only look out to 60 m
python tdr_pdf.py --start 0.05 --stop 1500 --cable LMR-400 \
    --max-dist 60 --label "Tower run, 50 m LMR-400" --output tower.pdf

# Manual VF, no cable preset
python tdr_pdf.py --start 0.05 --stop 1500 --vf 0.66 \
    --label "Mystery cable" --output mystery.pdf

# Use the HP 8712B (cannot start below 0.3 MHz on the HP)
python tdr_pdf.py --vna hp --start 0.3 --stop 1300 --cable LMR-400 \
    --label "Bench LMR-400 patch" --output patch.pdf
```

Optional flags:

- `--vna {nanovna,hp}` — driver selection (default nanovna)
- `--port /dev/ttyACM1` — NanoVNA serial path
- `--host 10.1.1.70` — HP KISS-488 host
- `--start MHZ` / `--stop MHZ` — sweep range (default 0.05 – 900 MHz).
  Wider sweep → finer distance resolution.
- `--points N` — sweep points (NanoVNA max 401, HP max 801; default 401)
- `--average N` — software-average N sweeps (default 2)
- `--power DBM` — HP source power; ignored on NanoVNA
- `--vf VF` — velocity factor (default 0.66)
- `--cable TYPE` — pick velocity factor by cable name. Overrides `--vf`.
  Known: RG-58, RG-58A, RG-8X, RG-213, RG-214, LMR-240, LMR-400, LMR-600,
  9913, Heliax-1/2, Heliax-7/8, Belden-9258, PTFE-jumper, twinlead-300,
  ladder-line.
- `--feet` — plot distance axis in feet (default metres)
- `--max-dist VALUE` — cap the distance axis. Units match `--feet`.
- `--dead-zone M` — distance to ignore when picking the dominant fault
  (default 2 m). Suppresses the port-1 connector echo.
- `--window {rect,hann,hamming,blackman,kaiser}` — frequency-domain
  window (default `hann`). Heavier windows reduce sidelobe ringing at
  the cost of slightly poorer spatial resolution.
- `--interp N` — frequency-domain zero-pad factor for finer time
  sampling (default 8). Doesn't add real resolution; only smooths the
  trace.
- `--gate-start-m M` / `--gate-end-m M` — **time gating.** Defines a
  window in the impulse response, zeros the response outside it, and
  FFT's that back to the frequency domain. The result is what S11
  would look like if ONLY the reflections in that distance band were
  present. Use this to isolate "which connector is bad" when several
  reflections are in series on one cable. (Or `--gate-start-ft` /
  `--gate-end-ft` for feet.)
- `--gate-taper-m M` — cosine-taper width on each gate edge (default
  0.05 m = 5 cm). Avoids spectral leakage from a hard window. Set to 0
  for a hard gate.

## Time gating in detail

A normal TDR shows you EVERY reflection in a cable. When you have a
50-ft run with 4 PL-259s in series, ALL of them contribute to S11,
and you can't tell which one is the bad one just by looking at the
frequency-domain S11 trace.

Time gating fixes that. You see the TDR impulse-response peak at,
say, 18 m one-way. You pass `--gate-start-m 17 --gate-end-m 19`.
The script zeros the impulse response everywhere except 17–19 m,
FFT's back to the frequency domain, and shows you the return-loss
trace of just the reflection at that connector — disambiguated from
the other three.

Two important caveats:

1. **Spatial resolution = vf · c / (2 · sweep span).** With a 0.05 –
   900 MHz sweep on RG-58 (vf 0.66), that's about 11 cm. Two reflections
   closer than 11 cm cannot be separated; gate them as one and live
   with the ambiguity.
2. **Gate taper matters.** A hard rectangular gate causes spectral
   leakage that puts a fake ripple on the gated frequency response.
   The default 5 cm cosine taper softens the edges enough to
   suppress most of this. For an HF-only sweep where 5 cm is tiny
   compared to a wavelength, you can leave it. For UHF / SHF work
   where 5 cm is a significant fraction of a wavelength, **reduce
   the taper or you'll smear adjacent reflections together**.

Example workflow — find the bad PL-259 in a 4-connector feedline:

```bash
# Step 1: capture a full TDR to see all the reflections
python tdr_pdf.py --start 0.05 --stop 900 --cable RG-58 \
    --label "Full feedline" --output full.pdf

# (PDF shows reflection peaks at 0.2 m, 6.4 m, 18.1 m, 30.0 m)

# Step 2: gate around each peak in turn
python tdr_pdf.py --start 0.05 --stop 900 --cable RG-58 \
    --gate-start-m 17.5 --gate-end-m 18.5 \
    --label "PL-259 #3 at 18 m" --output pl259_3.pdf

# (PDF "gated frequency response" panel shows return loss vs frequency
# for just that one connector. -25 dB across HF = healthy. -10 dB =
# damaged or filthy connector. Compare against the same gate on the
# other 3 connectors.)
```

## Output

Two-panel single-page PDF:

1. **Step response Γ(d)** — what a classic step-pulse TDR scope shows.
   A flat trace at 0 means matched line. A jump upward at distance *d*
   is an open-like fault; downward is short-like. The asymptotic value
   reaches ±1 for a true open / short and partial values for partial
   mismatches.

2. **|Impulse response| |h(d)|** — sharper peaks at every reflection.
   Best for locating *multiple* faults in one cable.

Console output also prints:

- **Spatial resolution** — `vf · c / (2 · span)`. With a 0.05–900 MHz
  sweep on RG-58 (vf 0.66) you get about 11 cm of resolution.
- **Unambiguous range** — `vf · c / (2 · df)`. Past this distance the
  IFFT wraps around. With 401 points across 0.05–900 MHz on RG-58 this
  is ~44 m. Use fewer points but wider span if you need range; use a
  narrower span with the same point count if you need resolution.
- **Distance to the dominant fault** past the dead zone, with the
  step-response Γ value and a verbal classification.

## Math, in two lines

We treat S11(f) as the positive half of a Hermitian spectrum, mirror
into the negative-frequency band, window, zero-pad for interpolation,
and IFFT. The result is the *impulse* response *h(t)*. Cumulative
integral of *h(t)* is the *step* response. One-way distance from time
is `d = vf · c · t / 2`.

The DC bin (f = 0) is not measured by the VNA, so the script uses
S11 at the lowest swept frequency as a stand-in. With a NanoVNA-F
starting at 50 kHz, this approximation is essentially perfect for any
cable longer than a few centimetres. With an HP 8712B starting at
300 kHz, the step response has a small DC ambiguity at very long
distances — use the impulse panel for fault location in that case.

## When TDR helps and when it doesn't

- **Helps:** locating cable faults (kinks, water ingress, bad
  connectors), measuring cable length, verifying VF for a mystery
  cable (cut a known length, find the open at the far end, back-solve
  for vf), separating "the antenna is broken" from "the cable to the
  antenna is broken."
- **Doesn't help:** characterising any single point along a *matched*
  cable. A perfectly-matched feedline shows a flat trace; you need a
  deliberate impedance discontinuity to see anything.

## Notes vs the NanoVNA's built-in TDR

The NanoVNA's TDR screen does the same IFFT + cumsum that this script
does. Advantages of running it here:

- PDF output for archiving / sharing
- Auto-finds the largest fault with a verbal classification
- Choice of window and interpolation factor
- Cable presets — type `--cable LMR-400`, not `vf=0.85`
- Works identically on the HP 8712B when it's online

Disadvantages: you have to plug the NanoVNA into the laptop. For
field work (chasing down a bad connector on the tower), the on-device
TDR display is unbeatable.
