# vector-fit-spice — Measured S-params → SPICE rational model

Fit a measured S-parameter trace with a rational function (sum of
poles + residues), then export a SPICE subcircuit you can drop
straight into LTspice or ngspice as a behavioural Laplace model.

This is the most engineering-valuable post-processor in the VNA
project tree. Take any 2-port DUT — a filter, an amplifier, a
matching network, a balun, a transformer — measure its S-parameters
with one of the swappable-API VNA tools, run this script, and you
have a SPICE model of the actual physical part. Use that model to
design surrounding circuitry, predict driver loading, simulate
overall system performance.

## Algorithm

Standard Vector Fitting (Gustavsen & Semlyen, IEEE Trans. Power
Delivery 1999):

1. Start with an initial pole set spread across the measurement
   frequency band (complex-conjugate pairs, slightly damped).
2. Solve a linear least-squares problem to find pole-relocation
   coefficients.
3. New poles = eigenvalues of the relocation matrix; reflect any
   right-half-plane poles into the left half for stability.
4. Iterate steps 2–3 until poles stop moving (default 8 iterations).
5. Solve a final residue-fit LS with the converged poles.
6. Convert the partial-fraction sum to a rational `N(s)/D(s)`.
7. Emit a SPICE Laplace source.

The implementation is the original 1999 algorithm, not the modern
relaxed variant from Gustavsen 2006. ~200 lines, no external
dependencies beyond numpy.

## Usage

```bash
# Fit S21 of a captured filter with 6 poles, write LTspice subckt
python vector_fit_spice.py --input measured_filter.s2p \
    --parameter S21 --poles 6 \
    --label "9 MHz Inrad SSB filter" --output fit.pdf

# More poles for a wideband DUT with multiple resonances
python vector_fit_spice.py --input wideband_amp.s2p \
    --parameter S21 --poles 12 \
    --label "MMIC 1–500 MHz" --output mmic_fit.pdf

# Fit S11 instead (for one-port model — antenna, matching net)
python vector_fit_spice.py --input antenna.s2p \
    --parameter S11 --poles 8 \
    --label "Mobile whip @ 7 MHz" --output ant_fit.pdf

# ngspice flavor instead of LTspice
python vector_fit_spice.py --input filter.s2p \
    --spice-flavor ngspice --output filter_fit.pdf
```

Flags:

- `--input FILE.s2p` — **required**; Touchstone v1 (`.s1p` or `.s2p`)
- `--parameter {S11,S12,S21,S22}` — which S-parameter to fit
  (default S21).
- `--poles N` — number of poles. **Rule of thumb: 2 poles per
  resonance / shoulder you can see in the magnitude trace.** Default
  6 covers most simple 2-pole filters with margin. More poles =
  tighter fit, riskier extrapolation outside the measured band.
- `--iters N` — pole-relocation iterations (default 8). Increase to
  20 if the fit-error message at the end is unusually large.
- `--no-d` — drop the constant term `d` from the model. Rarely
  useful; the default model includes it.
- `--with-h` — add a proportional term `h·s`. Use if the response
  visibly rises linearly at the top of the sweep.
- `--spice-flavor {ltspice,ngspice}` — output syntax (default
  ltspice).
- `--label TEXT` — chart title text.
- `--output FILE.pdf` — **required**; PDF path.
- `--spice FILE.sub` — optional explicit SPICE path (defaults to
  `<output>.sub`).

## Output

**PDF** — three stacked panels:

1. `|S_xx|` (dB) — measured (dashed grey) vs fit (solid)
2. `∠S_xx` unwrapped (degrees) — measured vs fit
3. Magnitude error (dB) — fit minus measured; reports RMS and max
   error in the legend

**.sub** — a SPICE subcircuit with a single 2-terminal behavioural
Laplace source. LTspice flavor:

```spice
.subckt FIT_RATIONAL in out
B1 out 0 V=laplace V(in) = (...num poly in s...) / (...den poly in s...)
.ends FIT_RATIONAL
```

ngspice flavor (with the `Erational` LAPLACE controlled source).

## Drop into LTspice

1. Copy `<basename>.sub` to your LTspice project directory.
2. In your schematic, drop a `sub` placeholder, edit its
   `Value` to `FIT_RATIONAL`.
3. Add a SPICE directive: `.include <basename>.sub`.
4. Connect its `in` / `out` pins to your circuit. The block now
   behaves as a black-box `S21(s)` equivalent — driving it with a
   voltage gives you the output that the DUT would have produced
   in your simulation.

## When this is the right tool

- **Filter integration.** You have a measured commercial filter and
  you want to simulate its interaction with your matching network
  and driver. Drop the fit into LTspice between your driver model
  and your downstream stage. Far more accurate than the datasheet's
  ideal-element schematic.

- **Reference comparisons.** Fit a manufactured part, fit a
  prototype, compare the two SPICE models side-by-side in
  simulation across signals the VNA didn't directly test.

- **Stability / loop analysis.** A fit of an amplifier's S21 gives
  you a model that participates honestly in a feedback-loop
  simulation, including bandwidth limitations.

- **Crystal / SAW modeling.** Better than the BVD model from
  [`../crystal-bvd-pdf/`](../crystal-bvd-pdf/) when the part has
  spurs or non-fundamental behavior the BVD topology can't capture.

## When this is NOT the right tool

- DUTs you want lumped-element insight into. The fit hides the
  physics in a polynomial; if you want "what RLC corresponds to
  this measurement," use a physics-based fit
  (`../crystal-bvd-pdf/` for crystals, `../tline-pdf/` for cables).
- Extreme-bandwidth captures (DC to GHz with many resonances) — the
  basic algorithm here can struggle with the conditioning; consider
  the `python-vectfit` package for the modern relaxed variant.

## NanoVNA vs HP — vector-fit-specific notes

Pure post-processing. Identical results from either VNA's `.s2p`
input. Practical caveats:

- **Phase data matters more than magnitude.** The VF cost function
  is on complex H(s), and a noisy phase trace produces a fit that
  oscillates between sweep points. The HP 8712B's tighter phase
  noise (a few tenths of a degree) gives noticeably cleaner fits
  on narrow features than the NanoVNA (~2–5°).
- **At low magnitude levels** (well into the stopband, far past
  series resonance, etc.), the NanoVNA's noise floor produces phase
  that's effectively random. The fit will try to model that noise
  unless you either (a) raise `--average` on the source capture or
  (b) use fewer poles so the model doesn't have the degrees of
  freedom to follow the noise.

## Self-test

A synthetic 2nd-order bandpass at 14 MHz BW 2 MHz, captured with
401 frequency points across 10–18 MHz, round-trips through the fit:

- 2 poles: 5.0 dB RMS error  ← model under-parameterised
- 4 poles: 2.5 dB RMS error
- 6 poles: 0.23 dB RMS error  ← good fit, extra poles parked away
                                  from the band

For a real-world measurement, 0.5–1 dB RMS is excellent; >3 dB
RMS usually means more poles are needed.

## Notes

- The model is **non-passive by construction.** SPICE will happily
  simulate a fitted-S21 that has reverse signal flow inconsistent
  with reciprocity, etc. If you intend to chain multiple fitted
  blocks in series, this can produce non-physical results. For
  passive cascades, fit each block separately and use the rational
  models only at the interfaces you care about.
- The `.sub` file is reproducible: re-running with the same input
  and same `--poles` / `--iters` gives bit-identical output.
- For >12 poles the polynomial coefficients become very large
  (orders of 10⁵⁰); LTspice handles this fine but readability
  suffers. Consider whether you really need that many poles.
