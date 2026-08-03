# HF direction finding on the SunSDR2 PRO's coherent receivers

Experimental HF direction finding (DF) built on the SunSDR2 PRO's two
phase-coherent receivers, driven by the **solsdr** project (ExpertSDR3-free,
`~/Dropbox/build/solsdr/`). Goal: estimate — and display — the bearing of an
incoming HF signal. Display-only for now (measure and show; don't retune/key).

**Status: Phase 0.** See [`df-proposal.md`](df-proposal.md) for the full plan and
an honest account of why HF DF is hard (huge wavelengths, baseline vs.
resolution, cone/mirror ambiguity, skywave). Read that before expecting bearings.

## Why this is a coherent-receiver problem

Two-element phase DF measures the phase difference Δφ of the same signal at two
antennas on a baseline `d`:  `Δφ = (2π d/λ)·cos(θ)` → arrival angle θ. That's
only meaningful if the two receivers hold a fixed phase relationship — which the
PRO's DDCs do: **γ² ≈ 0.999**, measured (solsdr `keep/rx2-design.md`). Two known
constraints from that work drive everything here:

- The inter-DDC phase offset is **stable within a session but changes across
  restarts** → every session needs a **phase calibration** before bearings are
  valid.
- Both receivers share **one antenna** today. Real DF needs **two
  spatially-separated antennas**; the DDC coherence is what makes the
  inter-antenna phase difference meaningful once the feed is split.

## Phase 0 — live cross-phase readout (this directory)

`df.py` tunes both receivers to the **same** frequency and reports, live, the
phase difference Δφ at the strongest signal bin, smoothed, with its **stability
(circular std-dev)**. On the current single shared antenna, Δφ should sit at a
constant with low variance. This:

- validates the DF observable (`angle(Sxy)`) and the data plumbing, with **no new
  hardware**;
- measures the **phase-noise floor** (the Δφ std), which sets the best-case
  angular resolution any later two-antenna DF can achieve;
- surfaces the per-session offset that Phase 1 will calibrate out.

It does **not** yet produce a bearing — that's Phases 2-3 (two antennas +
calibration).

### Run it

`df.py` talks the SunSDR2's raw UDP protocol directly (for sample-aligned
dual-RX IQ — see the maintainer notes in this directory), so **run it on the
radio host** with the solsdr project available:

```bash
# on the machine wired to the radio:
python3 df.py --freq 14074 --radio-ip 10.1.2.3 --local-ip 10.1.2.185
python3 df.py --freq 14074 --seconds 60          # longer stability run
```

Point both receivers at a **strong, steady** signal (a busy 20 m FT8 window, a
broadcast carrier, or an injected tone). Options: `--freq` (kHz), `--seconds`,
`--nfft`, `--min-gamma` (reject weak/incoherent blocks), `--block` (s per
measurement), `--rate`, `--solsdr-path`. `--help` for all.

### Reading the output

```
  t=  5.2s  Δφ=  -63.4°  γ²=0.998  RX1=-96.1dBFS  | mean  -63.1°  std 0.42°  (n=20)
  ...
SUMMARY  (112 measurements, 3 rejected)
  cross-phase Δφ : -63.1°  (circular std 0.42°)
  coherence γ²   : 0.998
  phase-noise floor -> best-case angular resolution ~0.03° ... (λ=21.3 m)
```

- **γ² near 1.0** → the DDCs are phase-locked (expected; the prerequisite).
- **A steady Δφ with small std** → good. The mean is the per-session offset;
  the std is the phase-noise floor. Small std = tight future bearings.
- **Δφ drifting or large std** → investigate before proceeding (weak signal,
  interference in the peak bin, or a real coherence problem).

The "best-case angular resolution" line is a **context-only** projection (what a
two-element interferometer *could* resolve at broadside given this phase noise,
`--baseline` metres) — Phase 0 has one antenna and produces no bearing.

## Built ahead of the antennas (2026-07-08)

The plan is two antennas, ~1-2 weeks out. Almost the entire system is built and
**validated against synthetic data now** — only the final on-air bearing needs
real antennas. What's done and tested (`test_df.py`, 23 checks, no hardware):

- **`phasecal.py`** — measured the inter-channel phase vs. frequency on the
  radio: it's **FLAT** (δ≈0, one scalar offset −32.77° across 312.5 kHz). This
  refuted the earlier "frequency-dependent offset" guess and means **Phase 1
  calibration is a single scalar per session** (simple). See df-proposal.md §0.
- **`geometry.py`** — the Δφ↔bearing math: interferometer equation, cone angle,
  electrical spacing, aliasing (D>0.5) + mirror ambiguity flags, error
  propagation (θ error vs. Δφ std), and two-baseline azimuth. Pure/unit-tested.
- **`simulate.py`** — synthesizes sample-aligned two-channel IQ for a signal
  from a known bearing on a known baseline (+ noise, + the measured offset). The
  ground-truth fixture that lets the whole pipeline be tested without antennas.
- **`bearing.py`** — the engine: calibrated cross-phase → geometry → bearing,
  with a **refuse-until-calibrated** gate (mirrors solsdr's TX-safety interlock),
  single-baseline (cone + ambiguity) and dual-baseline (full 360° azimuth) modes.
- **`df_offline.py`** — runs the full pipeline on simulated data; recovers cone
  angles to ~0.1° and azimuth to ~0.01° at 25 dB SNR. **Try it now:**
  `python3 df_offline.py` / `python3 df_offline.py --dual`.

So when the antennas go up, Phase 2 is mostly: split the feed, run `phasecal.py`
to confirm the offset on the real feedlines, calibrate, and feed live `df.py`
cross-phase into the already-tested engine.

## Roadmap

| Phase | What | Hardware | Status |
|-------|------|----------|--------|
| **0** | live cross-phase readout + noise floor | none | ✅ done (γ²≈1.0, floor ~0.1°) |
| **1** | scalar session calibration + refuse-until-cal gate | ref splitter / beacon | ✅ built + tested (offline) |
| **geometry/engine** | Δφ→bearing, ambiguity, dual-baseline azimuth | none | ✅ built + tested (offline) |
| **2** | two antennas, one baseline → live arrival angle | **2 antennas** (pending) | ⏳ awaiting antennas |
| 3 | second baseline / crossed loops → unambiguous 360° | 2nd baseline or loops | ⏳ |
| 4 | bearing display (compass widget), logging, MQTT/map | — | 💭 |

## ▶ RESUME HERE — the exact next steps (for picking this up later)

Everything up to live two-antenna bearings is built and tested offline. When the
**two antennas are erected**, do this, in order:

1. **Wire it.** Antenna A → RX1 input, antenna B → RX2 input, on a measured
   baseline `d` (metres). For an unambiguous single baseline keep `d ≤ λ/2`
   (≤ ~10.5 m on 20 m; scales with band). Record `d` and the baseline's compass
   orientation — bearings come out relative to the baseline axis.
2. **Re-confirm the calibration model on the real feedlines.** Feed the SAME
   signal to both antenna ports (split a tone/noise source, or use a strong
   common carrier) and run `phasecal.py --freq <kHz> --rate 312500`. Phase 0
   found the *receiver* offset flat (scalar). The **antennas + feedlines may add
   frequency dependence** the receiver-only test couldn't see — if `phasecal`
   now shows a slope/δ, the scalar `Calibration` must become per-frequency
   (store δ; correct per bin). Confirm flat before trusting a scalar.
3. **Establish the session offset φ0** (Phase 1, already coded):
   - Easiest: split a reference into both ports (zero path difference ⇒ known
     geometric phase 0) → `φ0 = measured cross-phase`. Or point at a beacon of
     known bearing and set that.
   - Feed it to `bearing.BearingEngine(baseline_m=d, freq_hz=f).calibrate(...)`.
     Re-do every session — the offset is stable within a run but NOT across
     stream restarts.
4. **Measure a live bearing.** Get the cross-phase from `df.py` (use
   `--bin-freq` to pin the target's exact bin — do NOT use "strongest bin" on a
   multi-tone/hopping signal; Phase 0 showed that fails), pass it to
   `engine.bearing(dphi_meas_deg, dphi_std_deg=...)`. Validate against a
   transmitter of **known** bearing first — a strong local groundwave signal, not
   skywave (skywave bearings wander; see df-proposal.md §physics).
5. **Sanity-check against theory.** A broadside signal (perpendicular to the
   baseline) should read Δφ_geo ≈ 0 after calibration. Swap the two antenna
   feeds → the bearing should mirror. If those hold, the geometry/sign is right.

Then Phase 3 (full 360°): add a second orthogonal baseline and use
`DualBaselineEngine` (built + tested), or crossed loops (Watson-Watt — would need
a small rework of the front end). Phase 4: bearing display + logging.

**The one decision still open:** the physical antenna layout / baseline length
(and whether to go single-baseline-with-mirror-ambiguity first, or straight to
two baselines for unambiguous azimuth). Everything else is coded.

**Integration glue still to write** (small, deferred until antennas exist so it's
tested against real data, not guessed): a `df_live.py` that wires `df.py`'s
live cross-phase stream directly into `BearingEngine` and prints/plots a live
bearing. Today the live monitor (`df.py`) and the engine (`bearing.py`) are
tested separately + end-to-end via the simulator; the thin live bridge is the
last piece and belongs with real antennas so its calibration flow is real.

## Files

- `df.py` — Phase 0 live cross-phase monitor (radio host).
- `phasecal.py` — inter-channel phase-vs-frequency characterization (radio host).
- `geometry.py` — interferometer geometry (Δφ↔bearing), pure math.
- `simulate.py` — two-channel IQ simulator for a known arrival (no hardware).
- `bearing.py` — DF engine (calibration + geometry + ambiguity/confidence).
- `df_offline.py` — full-pipeline demo on simulated data (no hardware).
- `test_df.py` — pipeline test suite (23 checks, no hardware).
- `df-proposal.md` — full proposal, physics, method options, open decisions.
