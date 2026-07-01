# TRL Calibration — Design Reference

## What TRL is

TRL (Thru-Reflect-Line) is a self-calibrating VNA error-correction
technique that does not require precisely characterised impedance
standards. Instead it uses three simple structures:

- **Thru** — a zero-length (or known-length) connection between
  ports.
- **Reflect** — a high-reflection standard whose exact value is
  *unknown*, only required to be *identical* at both ports.
- **Line** — a transmission line slightly longer than the Thru,
  whose exact impedance and loss *need not be known*.

The math backs out the measurement errors from the three captures
themselves — no manufacturer's certified OPEN/SHORT data required.

## Why TRL exists (what SOLT can't do)

SOLT (Short-Open-Load-Thru) calibration works when the reference
plane sits at a precision coaxial connector — the standards
manufacturer provides traceable SMA/N/BNC kits with known S-params.
SOLT falls apart when:

1. The reference plane is **on a PCB** — you can't build a
   precision 50.000 Ω load on FR-4 with uncontrolled solder-mask
   dielectric and launch discontinuity.
2. The frequency is high enough that **connector repeatability**
   dominates the residual error budget.
3. You need calibration accuracy **inside a test fixture** (e.g.,
   at a chip die-pad or an SoC pin).

TRL sidesteps these by requiring only *simple geometry*, not
*precision impedance values*.

## The three standards

### Thru (T)

A direct connection between the two calibration planes. Ideally
zero-length so that S21 = 1 + j0 and S11 = 0. If the Thru has
non-zero length (common on PCB), its electrical delay must be
measured or estimated — the math uses it.

On PCB: a short microstrip bridge between the two launch pads. A
coax-to-coax setup uses a through connector (barrel adapter).

### Reflect (R)

Any 1-port standard with high |Γ|. Typically a SHORT or an OPEN.
The critical requirement is **symmetry** — the reflect standard
must present the *same* reflection when placed at port 1 as at
port 2. The math solves for *what* the reflection actually is;
you just need it consistent.

On PCB: a shorting bar between signal and ground at the cal
reference pad. Both pads must be geometrically identical.

### Line (L)

A transmission line whose phase length differs from the Thru's by
some amount NOT equal to 0° or 180° (where eigenvalues
degenerate). Practical rule: the electrical length offset should be
between 20° and 160° across the calibrated band.

On PCB: a longer trace connecting the two launch pads — typically
λ/4 at center frequency, giving 90° offset. No impedance precision
needed; the math extracts the line's propagation constant from the
measurement itself.

## Mathematical foundation (Engen-Hoer 1979)

### Error model

The 2-port VNA error model decomposes the measured S-matrix T_meas
into:

```
T_meas = T_A · T_DUT · T_B
```

where T_A (port-1 error adapter) and T_B (port-2 error adapter)
are unknown 2×2 T-matrices capturing directivity, source match,
load match, tracking, and isolation errors. The goal of calibration
is to determine T_A and T_B so they can be de-embedded from every
subsequent measurement.

### Step 1 — Form the eigenvalue problem

Measure the Thru and Line through the error adapters:

```
M_T = T_A · I · T_B          (Thru — identity DUT)
M_L = T_A · D_L · T_B        (Line — diagonal propagation matrix)
```

where D_L = diag(e^{-γl}, e^{+γl}) for a line of length l and
propagation constant γ.

Take the product:

```
M_T^{-1} · M_L = T_B^{-1} · D_L · T_B
```

This is a **similarity transformation** — M_T^{-1} · M_L has the
same eigenvalues as D_L. The eigenvalues are e^{-γl} and e^{+γl}.

### Step 2 — Extract propagation constant

The eigenvalues λ₁, λ₂ of M_T^{-1} · M_L satisfy:

```
λ₁ · λ₂ = e^{-γl} · e^{+γl} = 1   (for lossless; ≈1 for lossy)
λ₁ / λ₂ = e^{-2γl}
```

From the ratio: `γl = -½ ln(λ₁/λ₂)`.

The eigenvectors of M_T^{-1} · M_L give the columns of T_B (up to
a scalar ambiguity resolved in the next step).

### Step 3 — Resolve sign/root ambiguity with Reflect

The eigenvalue decomposition has a sign ambiguity — which
eigenvalue is e^{-γl} vs e^{+γl}? And the eigenvectors have a
multiplicative scalar freedom.

The Reflect measurement resolves both:

```
M_R1 = T_A · [[Γ_R, 0], [0, 0]] · T_A^{-1}   (reflect at port 1)
M_R2 = T_B · [[Γ_R, 0], [0, 0]] · T_B^{-1}   (reflect at port 2)
```

Since Γ_R is the same at both ports (by the symmetry requirement),
cross-referencing the two measurements pins down the sign of Γ_R
and removes the scalar ambiguity from T_A and T_B.

### Step 4 — Apply correction

Once T_A and T_B are known, de-embed any DUT measurement:

```
T_DUT = T_A^{-1} · T_meas · T_B^{-1}
```

Convert T_DUT back to S-parameters for presentation.

## Constraints and failure modes

### Frequency-band limitation

The Line's electrical length must stay between 20° and 160° offset
from the Thru across the entire calibrated band. At exactly 0° or
180°, D_L becomes ±I and the eigenvalue problem degenerates (both
eigenvalues are equal; eigenvectors are undefined).

For wideband calibration, use **multiline TRL** (Marks 1991) —
multiple lines of different lengths, each covering a different
frequency sub-band, stitched together. scikit-rf supports this.

### Bandwidth rule of thumb

A single line covers roughly an 8:1 frequency span (20° at f_low,
160° at f_high → ratio = 160/20 = 8). For a NanoVNA sweeping
50 kHz–1.5 GHz (30000:1 ratio), you'd need 5+ lines.

### Reflect symmetry

The reflect standard MUST be identical at both ports. On PCB this
means identical geometry, identical solder, identical trace launch.
Oxidation, solder-blob asymmetry, or misaligned vias break the
assumption and inject systematic error.

### Thru length

If the Thru isn't truly zero-length, the calibration reference
plane sits at the *electrical midpoint* of the Thru, not at the
physical port face. Correctable (tell the algorithm the Thru's
delay), but worth knowing — a 5 mm Thru at 6 GHz is 36° of
unmodelled phase if you pretend it's zero-length.

### Line Z₀ defines the reference impedance

TRL does NOT reference to 50 Ω — it references to the Line's
characteristic impedance. If your PCB Line trace is 47 Ω because
of dielectric variation, your calibrated S-params are in a 47 Ω
system. Use `renormalize-pdf/` afterward to convert to 50 Ω if
needed.

## Implementation complexity — why it wasn't built

The Engen-Hoer eigenvalue decomposition has several practical
pitfalls that make a naive implementation give plausible-but-wrong
results:

1. **Branch-cut disambiguation.** `γl = -½ ln(λ₁/λ₂)` has a
   complex logarithm with an infinite number of branches. Picking
   the wrong branch gives a propagation constant off by jπ/l.
   Real implementations track phase continuity across frequency.

2. **Degenerate-eigenvalue handling.** Near 0° and 180° offset,
   the two eigenvalues approach each other. The eigenvector
   computation becomes numerically unstable (condition number
   diverges). Robust code needs to detect and exclude these
   frequency points, or switch to a different Line.

3. **Sign of Γ_R.** The Reflect step resolves a ± sign. Getting
   this wrong flips the reference plane by 180° — the error is
   subtle because return-loss magnitude looks correct, only
   Smith-chart phase is wrong. Debugging requires a known DUT.

4. **Multi-line stitching.** For wideband TRL, the overlap region
   between two lines' valid bands needs careful phase-unwrapping
   and weighted averaging. Discontinuities in the stitching produce
   ripple artifacts.

5. **Non-zero Thru correction.** Most real fixtures have a non-
   zero Thru. The algorithm must subtract the Thru's known (or
   estimated) electrical length before forming the eigenvalue
   problem, else the reference plane is displaced.

6. **Sensitivity to measurement noise.** Unlike SOLT where each
   standard independently constrains one error term, TRL's error
   terms are coupled through the eigenvalue decomposition. Noisy
   S11 data (common on NanoVNA at high frequencies) propagates
   into correlated errors across all extracted coefficients.

## What a proper rf-bench implementation would require

- **~400 lines of Python** (eigendecomposition, phase unwrapping,
  reflect disambiguation, Touchstone I/O, PDF output).
- **Synthetic test suite** — construct known T_A, T_B, D_L
  matrices, generate synthetic measurements, verify the algorithm
  recovers T_A and T_B to machine precision.
- **Edge-case tests** — near-degenerate eigenvalues, lossy lines,
  non-zero Thru delay, asymmetric reflect (should detect and warn).
- **Real-hardware validation** — a PCB TRL cal kit measured on the
  NanoVNA, with results cross-checked against scikit-rf's `TRL`
  class on the same raw .s2p files.
- **Multiline support** — for full NanoVNA band (50 kHz–1.5 GHz),
  at least 5 lines with overlap-band stitching logic.

## Practical path today: scikit-rf

Until a bespoke rf-bench implementation is validated, use scikit-rf:

```bash
pip install scikit-rf --break-system-packages
```

```python
import skrf as rf

# Load raw (uncorrected) measurements
thru = rf.Network('thru.s2p')
reflect = rf.Network('reflect.s2p')
line = rf.Network('line.s2p')

# Build and run TRL calibration
cal = rf.calibration.TRL(
    measured=[thru, reflect, line],
    line_lengths=[0, 0, 0.020],   # metres; Thru=0, Reflect=0, Line=20mm
    ideals=None,                  # TRL doesn't need ideal models
)
cal.run()

# Apply to a DUT measurement
dut_raw = rf.Network('dut_measured.s2p')
dut_corrected = cal.apply_cal(dut_raw)
dut_corrected.write_touchstone('dut_true.s2p')
```

Then feed `dut_true.s2p` to any rf-bench post-processor:
`impedance-pdf`, `filter-pdf`, `de-embed-pdf`, `vector-fit-spice`,
etc.

scikit-rf also supports **multiline TRL** via
`rf.calibration.MultilineTRL` — pass a list of line Networks and
their lengths, and it handles the overlap stitching.

## When to build the bespoke version

Build it when:

1. A real PCB TRL cal kit is on the bench (even a simple one: two
   identical SMA launches with a Thru bridge and a 20 mm Line).
2. The scikit-rf dependency is undesirable (e.g., for a standalone
   script that runs on a Raspberry Pi without numpy/scipy bloat —
   though that's unlikely given everything else already requires
   numpy).
3. Integration with `de-embed-pdf/` is desired as a single pipeline
   (capture raw → TRL cal → de-embed fixture → present DUT).

## References

- G. F. Engen and C. A. Hoer, "Thru-Reflect-Line: An Improved
  Technique for Calibrating the Dual Six-Port Automatic Network
  Analyzer," IEEE Trans. MTT, vol. 27, no. 12, Dec 1979.
- D. F. Williams, R. B. Marks, and A. Davidson, "Comparison of
  On-Wafer Calibrations," 38th ARFTG Conference, Dec 1991.
- R. B. Marks, "A Multiline Method of Network Analyzer
  Calibration," IEEE Trans. MTT, vol. 39, no. 7, July 1991.
- D. Rytting, "Network Analyzer Error Models and Calibration
  Methods," Agilent Technologies, 2004.
- scikit-rf documentation: https://scikit-rf.readthedocs.io/
  (specifically `skrf.calibration.TRL` and `MultilineTRL`).
