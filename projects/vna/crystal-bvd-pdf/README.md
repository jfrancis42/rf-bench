# crystal-bvd-pdf — Crystal BVD parameter extraction

Sweep a quartz crystal's S21 across its series-resonance region (live
on the VNA, or from a saved `.s2p`) and extract the standard four-
parameter Butterworth-Van Dyke (BVD) model:

```
            Lm    Cm    Rm
      o───┬─[LLL]─[CC]─[/\\]─┬───o
          │                  │
         ─┴─  C0            ─┴─
          ─                  ─
          │                  │
      o───┴──────────────────┴───o
```

- **Lm** — motional inductance (mH range for HF crystals)
- **Cm** — motional capacitance (femtofarads; tiny)
- **Rm** — motional resistance (1–50 Ω typically)
- **C0** — shunt / holder capacitance (a few pF)

From these, derived quantities:

- **fs** — series resonance frequency
- **fp** — parallel ("anti") resonance frequency
- **Qm = ωsLm/Rm** — motional Q (10⁴–10⁶ for a good xtal)
- **C0/Cm** — capacitance ratio (200–500 typical)

## Why care

Crystal-ladder filter designers need all four BVD parameters to
design a filter. Crystal-oscillator designers need at least Cm and
C0 (the load-capacitance pulling formula uses these). Quartz-quality
sorters use Qm and Rm directly (high-Qm / low-Rm = good).

Manufacturer datasheets quote nominal BVD values; this tool tells
you what your actual specimens measure as. For ladder-filter design,
**measure every crystal you intend to use** and bin them.

## Fixture

Series-through, low-impedance:

```
Port 1 ──┬─ 12.5 Ω ─[crystal]─ 12.5 Ω ─┬── Port 2
         │                              │
         ↓ ground                        ↓ ground
```

The 12.5 Ω series resistors set the effective port impedance to
approximately match a typical crystal's Rm. The BVD math doesn't
need this matching to be exact — the script computes Z from S21
correctly regardless — but the matching keeps S21 in a measurable
range (not too close to 0 or 1) for better signal-to-noise.

For lab-grade Qm work (Qm > 100k) the fixture's own loss / phase
becomes the limit. Characterise the empty fixture and de-embed it
using [`../de-embed-pdf/`](../de-embed-pdf/) before BVD extraction.

## Sweep span

The script's default sweep span is **±1 %** (`--span-ppm 20000`)
around the user's `--estimate`. This is **wide on purpose**:

- The two BVD resonances (fs, fp) are typically 10–500 ppm apart.
  A narrow sweep would put both inside the noisy resonance region.
- The C0 fit needs samples that are well **off** resonance — the
  motional branch's admittance must be small compared to the C0
  admittance there.

For a 10 MHz crystal the default ±100 kHz span gives both clean
resonance peaks and 90 kHz of off-resonance baseline below fs for
C0 extraction. Narrower spans → noisier C0 → noisier Cm and Lm.

## Usage

### Live capture

```bash
# 10 MHz HC-49 — default ±1 % span
python crystal_bvd_pdf.py --estimate 10.0 \
    --label "HC-49 #3, 10 MHz" --output xtal3.pdf

# 9 MHz Inrad / SDR-Kits crystal, narrower sweep
python crystal_bvd_pdf.py --estimate 9.0 --span-ppm 5000 \
    --label "Inrad 9 MHz #7" --output inrad7.pdf

# 4.000 MHz oscillator can, HP 8712B
python crystal_bvd_pdf.py --vna hp --estimate 4.0 \
    --label "EPSON 4 MHz, ABLS family" --output ablss.pdf
```

### Offline (from .s2p)

```bash
# Re-fit a previously-saved capture
python crystal_bvd_pdf.py --from-s2p xtal3_capture.s2p \
    --label "HC-49 #3 (revisit)" --output xtal3_refit.pdf
```

## Outputs

**PDF** — three stacked panels sharing the frequency axis:

1. **|S21| (dB)** — the headline view: a sharp dip at fs, a peak at fp.
2. **R + X** — the impedance separation; X = 0 crossings mark fs and fp.
3. **|Z| (log)** — wide-dynamic-range view, useful for sanity-checking
   the resonance peak heights.

A floating panel of the extracted BVD parameters sits in the
lower-left of the |S21| chart.

**.sub** — a SPICE-paste-ready BVD subcircuit:

```
.subckt XTAL_BVD a b
Lm a x  2.500000e-02
Cm x y  1.013212e-14
Rm y b  8.000000e+00
C0 a b  5.000000e-12
.ends
```

Drop this into LTspice / ngspice and you have a circuit model of
your actual crystal. Useful for designing oscillator pulling
networks or ladder-filter coupling capacitors against the real part.

## Flags

- `--estimate MHZ` (or `--from-s2p FILE.s2p`) — **one is required**.
  `--estimate` does a live VNA capture; `--from-s2p` skips the VNA.
- `--vna {nanovna,hp}` — VNA driver (default nanovna). Ignored with
  `--from-s2p`.
- `--port`, `--host` — NanoVNA serial path / HP KISS-488 host.
- `--span-ppm PPM` — sweep span in PPM around `--estimate` (default
  20000 = ±1 %). Wider gives better C0 fit at the cost of poorer
  resonance-band resolution.
- `--points N` — sweep points (default 401).
- `--average N` — software-average N sweeps (default 4; this matters
  because the resonance is sharp and the noise floor matters).
- `--power DBM` — HP source power; ignored on NanoVNA.
- `--label TEXT` — chart title text.
- `--output FILE.pdf` — **required**; PDF path.
- `--spice FILE.sub` — optional explicit SPICE-netlist path
  (defaults to `<output>.sub`).

## NanoVNA vs HP — crystal-BVD specific notes

- **Drive-level dependence is a thing.** Crystals are slightly
  non-linear; their Rm and Lm change with drive level. The HP
  8712B has calibrated dBm and can sweep at, say, −20 dBm
  consistently. The NanoVNA's drive level is uncalibrated coarse-
  index, so the absolute number Rm depends on which `power 0..3`
  index you used. For consistent batch sorting on a NanoVNA, fix
  the power index and don't change it between crystals.
- **Phase-noise / averaging.** Qm extraction needs **clean phase**
  in the resonance band, which is small in magnitude (Rm is just a
  few ohms). The HP's hardware averaging plus tighter trace noise
  gives Qm accurate to ~1 % for typical crystals. The NanoVNA
  needs `--average 4` minimum, and Qm should be treated as ±5 %
  for ham-grade work.
- **Frequency stability.** Both VNAs use crystal references that
  themselves drift by a few ppm. fs and fp values are quoted to 4
  decimal kHz here, but a 10 MHz reading good to a few Hz absolute
  needs the VNA cal'd against GPSDO — see `projects/gps/freq-cal/`
  for one approach.

## Self-test

A synthetic 10 MHz crystal with Lm = 25 mH, Cm = 10.13 fF, Rm = 8 Ω,
C0 = 5 pF round-trips through the fit to within **0.3 % on all
parameters** (fs / Lm / Cm / C0 / Rm) at the default ±1 % sweep span.
With a narrower ±0.5 % sweep, errors rise to ~5 %; ±0.1 % is too
narrow and the fit fails because the C0-extraction baseline isn't
clear of resonance.

## Notes

- The script assumes a SINGLE resonance pair inside the sweep. For
  overtone crystals (3rd-overtone / 5th-overtone fundamentals
  outside the swept range), narrow the sweep around the harmonic
  you care about.
- For SC-cut and BT-cut crystals with multiple closely-spaced
  fundamentals, manually inspect the |S21| panel and split into
  multiple narrow sweeps.
- Crystals shipped from the same manufacturing batch typically
  match Cm within ±5 % and Lm within ±5 %. A bigger spread in the
  measured values often means the crystals are different batches,
  not different parts.
- Use `--from-s2p` to refit existing captures without re-pulling
  the crystal off the bench. This is how you bin a stack: capture
  every crystal in one session, then refit later from the saved
  `.s2p` files at leisure.
