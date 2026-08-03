# Direction finding with the SunSDR2 PRO's coherent receivers — proposal

Internal design proposal (keep/, not shipped). Starting point for building HF
direction finding (DF) on top of the two phase-coherent RX channels.

## Goal

Use RX1 + RX2 (proven phase-coherent, γ²≈0.999) to estimate the **bearing** of
an incoming HF signal, and display it — first as a number/needle, later plotted
over time / on a map. Display-only initially, like the panadapter: measure and
show, don't act.

## What we already have (don't re-derive)

From the RX2 coherence work (`keep/rx2-design.md` §"Phase coherence", and
`tools/rx2_coherence.py`):

- **The two DDCs are phase-locked at the signal**, γ²≈0.999 — the hard
  prerequisite for any phase-based DF. Confirmed on real hardware.
- **The fixed phase offset does NOT repeat across stream restarts** (measured
  −69°, −61°, −178° on separate runs). So the receiver pair adds an *unknown but
  constant-within-a-session* phase term. **Every session needs a phase
  calibration** before bearings mean anything. This is the single most important
  constraint for DF and it's already proven, not hypothetical.
- **Both are fed by ONE shared antenna today**, which is *why* they read the same
  phase. DF needs **two spatially-separated antennas** — splitting the feed is
  what turns the DDC coherence into a meaningful inter-antenna phase difference.
- The measurement method that works: index-tagged 2-arg stream callback →
  Welch cross-spectrum → per-bin γ² and **cross-phase** at the strongest signal
  bins. `spectral_coherence()` in `tools/rx2_coherence.py` already computes the
  cross-spectrum `Sxy`; **its phase `angle(Sxy)` at the signal bin is the raw DF
  observable.** We are closer than it looks — the DF tool is largely "take the
  cross-phase we already compute, calibrate it, convert to bearing."

## Phase 0 — DONE (2026-07-08): measured on real hardware

Ran `df.py` on the radio (single shared antenna). Two runs told the whole story:

- **WWV 10 MHz (steady single carrier):** Δφ = **+5.8°, circular std 0.10°**,
  γ² = 1.000 over 40 s. This is the real result: **the phase-noise floor is
  ~0.1°.** Δφ is essentially a constant (the per-session offset) with negligible
  drift.
- **20 m FT8 (busy, multi-tone):** γ² = 1.000 but Δφ std = **38°** — because "the
  strongest bin" hops between different FT8 FSK tones each block, and a small
  residual inter-channel time offset makes phase **frequency-dependent** across
  the passband (peak jumps to a tone 2 kHz away → Δφ jumps). NOT a receiver
  limitation; a target/method artifact.

**Consequences for the DF design (both now baked in):**

1. **The hardware is not the limiting factor.** A 0.1° phase floor is excellent —
   it projects to sub-degree best-case angular resolution on a 10 m baseline.
   The ionosphere, siting, and geometry (below) will dominate, not the receivers.
2. **DF must lock to a single FIXED frequency bin (a steady carrier), never
   "the strongest bin."** Measure bearings on a CW carrier / beacon / injected
   tone, not a hopping/multi-tone signal. `df.py` gained `--bin-freq` to pin the
   measurement bin.
3. **The per-session offset is a SCALAR — measured, not assumed (2026-07-08).**
   I hypothesized the FT8 spread meant a frequency-dependent time offset δ; the
   direct measurement (`phasecal.py`, 762 averaged segments across 312.5 kHz on
   the single shared antenna) **refuted it**: phase is FLAT (slope −0.000°/kHz,
   **δ ≈ 0**, residual 0.05°), a single scalar offset of −32.77° across the whole
   band. The FT8 38° spread was an averaging artifact — γ² from a few segments is
   biased toward 1.0, so the peak-bin phase in a weak/hopping bin was just noisy,
   NOT frequency-dependent. **Consequence: Phase 1 calibration stores one scalar
   per session** (much simpler). Caveat: this is the RECEIVER contribution only;
   with two antennas the feedline/antenna paths add their own term — but any
   antenna-side frequency dependence is a *physical* cable/matching effect to
   characterize separately, not a receiver artifact. `phasecal.py` stays as the
   tool to re-confirm once the antennas are up.

## The physics, honestly (HF DF is hard — set expectations)

Two-element coherent DF measures the **phase difference** Δφ between the same
signal arriving at two antennas separated by baseline `d`:

    Δφ = (2π d / λ) · cos(θ)          (θ = angle between arrival and baseline)

Solve for the arrival angle. But HF makes this genuinely difficult, and I won't
pretend otherwise:

1. **Wavelength is huge.** 20 m band → λ ≈ 21 m. For *unambiguous* phase (no
   spatial aliasing) the baseline must be ≤ λ/2 ≈ **10.5 m**. That's a big
   antenna spread, and it changes per band (40 m → λ/2 ≈ 20 m). A shorter,
   practical baseline (a few metres) is unambiguous but has **poor angular
   resolution** — small Δφ per degree, so noise/phase-jitter dominates.
2. **A single baseline gives a 1-D answer with a cone/mirror ambiguity.** Two
   spaced elements can't tell left from right of the baseline (and only resolve
   the angle *to* the baseline, not a full azimuth). Full 360° azimuth needs
   **≥3 elements** (or two orthogonal baselines), or an amplitude method (below).
3. **Skywave/ionosphere.** HF signals often arrive via one or more ionospheric
   hops at varying elevation and azimuth, with polarization mixing. Bearings
   *wander* and can be flat-out wrong (the classic HF-DF "night effect").
   Groundwave signals (local, daytime, low bands) DF far more reliably. Honest
   framing: this will work best on strong, local, groundwave-dominated signals;
   skywave bearings will be noisy and need long averaging + skepticism.
4. **Mutual coupling & siting.** Nearby conductors, feedline common-mode, and
   antenna imbalance all inject phase errors that masquerade as bearing. Siting
   and a good calibration matter as much as the math.

None of this is a showstopper — amateur HF DF ("foxhunting", ARDF, transmitter
hunting) is a real, working hobby. It just means we aim for a **useful bearing
estimate on cooperative signals**, not survey-grade azimuth on arbitrary skywave.

## Method options (pick per phase — see plan)

### A. Phase interferometry, two spaced antennas (the natural fit)
Δφ between two identical antennas on a known baseline → arrival angle from the
equation above. This is what the coherent DDCs are built for. One baseline =
1-D angle + ambiguity; add a second (orthogonal) baseline or a third element for
full azimuth. **Best match to our hardware; start here.**

### B. Watson-Watt / crossed loops (amplitude-comparison, 2 channels)
Two orthogonal loop antennas (N-S and E-W) on the two receivers. Bearing =
`atan2(amplitude_EW, amplitude_NS)` — instantaneous 360° azimuth (with a 180°
ambiguity resolved classically by a sense antenna, which we can't add as a 3rd
channel but can partly resolve via the cross-phase sign). Compact (loops are
small at HF vs. a 10 m baseline), classic for HF DF, and uses exactly 2 coherent
channels. **Strong candidate; arguably more practical at HF than a big
interferometer baseline.** Needs crossed-loop hardware.

### C. Correlative / MUSIC-style (later, if we go multi-element)
With ≥3 elements and a calibrated array manifold, subspace methods (MUSIC) give
high-resolution, multi-signal azimuth. Overkill for two channels; note it as the
growth path if the user ever wants a real array.

## The calibration problem (this is the crux)

Because the inter-DDC phase offset changes every session, we must measure and
remove it each run **before** any bearing is valid. Options, cheapest first:

1. **Common reference injection** — split a weak reference tone (or the radio's
   own cal/GPSDO-derived tone) into *both* antenna ports through a matched
   splitter at start-up; the measured Δφ on that known-common signal *is* the
   session offset. Subtract it. Cleanest and automatable.
2. **Known-bearing beacon** — point at a signal of known bearing (a local
   beacon, or a transmitter you place), set that Δφ→known angle. Simple, manual,
   good enough to start.
3. **Physical reciprocity check** — swap/rotate a known source. Bench only.

Whatever we pick, the DF tool must **refuse to report bearings until calibrated**
this session (mirror the TX-safety-interlock philosophy: no confident output
from an uncalibrated state).

## Proposed phased plan

**Phase 0 — cross-phase readout (software only, this week).** Extend the
coherence tool (or fork it to `tools/df.py`) to report, live, the **cross-phase
`angle(Sxy)` at the strongest signal bin**, smoothed, with its stability
(std-dev over time). Run it on the current *single shared antenna* → Δφ should
sit at a constant (the session offset) with low variance. This validates the
observable and the plumbing with zero new hardware, and quantifies the phase
noise floor (→ best-case angular resolution).

**Phase 1 — session calibration.** Implement offset capture (method 1 or 2
above) and the "refuse until calibrated" gate. Prove that after cal, a
common-fed pair reads Δφ≈0.

**Phase 2 — two antennas, one baseline.** Split to two real antennas on a
measured baseline. Convert calibrated Δφ → arrival angle (with documented
ambiguity). Validate against a known local transmitter. Expect this to be the
"does HF DF actually work on my bench" moment — and where skywave reality bites.

**Phase 3 — resolve ambiguity / full azimuth.** Either add crossed loops
(method B) or a second baseline, and produce an unambiguous 0–360° bearing.
Add time-averaging and a confidence metric (bearing variance, γ² gate).

**Phase 4 — display & logging.** A bearing needle / compass (reuse the
pyqtgraph stack from the panadapter), bearing-vs-time, optional log to the MQTT
bus / a map. Still display-only.

## Software architecture (fits existing solsdr)

- **Reuse the 2-arg index-tagged stream callback** (`Radio(rx2=True)`,
  `callback(rx_index, iq)`) — already the RX2 data path.
- **Reuse the cross-spectrum core** from `tools/rx2_coherence.py`; the DF tool is
  a superset (it also needs `angle(Sxy)` and the calibration/geometry layer).
- **New module** `tools/df.py` (bench/experiment tool, like rx2_coherence) →
  later promote a `solsdr/dsp/df.py` if it stabilizes. Keep the geometry
  (baseline, element positions, method) in a small config so it's not hard-coded.
- **Display** later via the panadapter's PyQt/pyqtgraph stack (a compass widget).
- **Both receivers must be on the SAME frequency** for DF (unlike dual-watch).

## Open questions — status (updated 2026-07-09)

DECIDED:
- **Method = two-element phase interferometry (A).** User chose two antennas
  (not crossed loops). `bearing.py` implements single- and dual-baseline; the
  `DualBaselineEngine` gives full 360° if a second orthogonal baseline goes up.
- **Phase 0 = done** (was Q5): built, run on hardware, γ²≈1.0, floor ~0.1°.
- **Calibration model = scalar** (was the freq-dependence worry): `phasecal.py`
  measured it flat; Phase 1 stores one scalar per session. Re-confirm on the
  real feedlines once antennas are up (they may add their own term).

STILL OPEN (need the antennas / a decision then):
1. **Baseline length + layout.** How far apart, and orientation? ≤ ~10.5 m at
   20 m keeps a single baseline unambiguous; longer improves resolution but
   aliases. One baseline (cone + mirror ambiguity) first, or two orthogonal
   baselines straight away for unambiguous azimuth?
2. **Calibration source on the real feedlines.** Split a common reference tone
   into both ports (automatable, method 1), or calibrate against a known-bearing
   beacon (method 2)? Both are supported by `BearingEngine.calibrate()`.
3. **First test target.** Recommend a strong LOCAL groundwave signal on a low
   band for the first validation — give the physics its best chance before
   fighting skywave.

See README.md "▶ RESUME HERE" for the concrete step-by-step once antennas exist.

## Recommendation

Build **Phase 0 now** — it's a small extension of code we've already verified,
needs no antennas, and turns "coherence is 0.999" into "here is the live,
calibrated phase observable and its noise floor." Everything else (antennas,
method, ambiguity) then rests on real measured numbers instead of theory.
