# Fluke 80i-400 AC Current Clamp — Project Ideas

Driver: `rf_bench.fluke` (`drivers/fluke/`). See also `projects/dmm/clamp-current/`.

## What this clamp is (and isn't)

The 80i-400 is a **passive current transformer** for **mains-frequency** work:

| Spec | Value | Consequence for projects |
|---|---|---|
| Output | 1 mA/A (1000:1) AC current | Read on a DMM's mA jacks, or a scope via a burden resistor |
| Range | 1–400 A AC | **1 A floor** — useless below ~1 A (sub-amp loads lost in noise) |
| Frequency | 48–1000 Hz | **Mains-band only** — not an RF tool |
| Accuracy | ±(3 % + 0.4 A) | ±0.4 A floor kills small-current / leakage work |
| Power | none (passive) | No battery, no interface — it's an accessory, not an instrument |

**Design rule:** good projects are "big AC currents on a wire you can't or don't
want to break into." Anything RF, sub-amp, DC, or milliamp-resolution is the
wrong tool — see the "Poor fit" section.

## The two front-ends

1. **Clamp → DMM current (mA) jacks.** Simplest. DMM reads AC mA = amps
   (1 mA/A). Good for slow logging, RMS current, profiling. This is what
   `rf_bench.fluke.Fluke80i400(dmm=...)` does.
2. **Clamp → burden resistor → scope channel.** The clamp is a current
   source; a scope is high-Z. Put a burden resistor across the clamp leads
   (e.g. **1 Ω → 1 mV/A**, so 400 A → 400 mV). Scope then sees a voltage
   proportional to instantaneous current. Needed for anything time-domain:
   harmonics, inrush, waveform. Same trick the existing `projects/power/inrush/`
   uses for its DC sense resistor.

---

## Worth building — current-only (SAFE, no mains-voltage contact)

These need only the clamp. No contact with the mains voltage conductor, so no
added shock hazard beyond the clamp's own insulation.

### 1. Harmonic / THD-i analyzer  ✅ BUILT → `projects/power/ac-harmonics/`
Clamp → burden → scope. FFT the current waveform, report total harmonic
distortion of the **current** (THD-i) and the per-harmonic breakdown (2nd–~40th).
Very revealing on switching supplies, LED bulbs, VFDs, motors. THD-i is a ratio
of harmonic currents — it does **not** require voltage sensing, so it's fully
valid with the clamp alone.

### 2. AC inrush current capture  ✅ BUILT → `projects/power/ac-inrush/`
Scope single-shot triggered on the clamp/burden signal. Catches transformer,
motor, and PSU turn-on surge. Reports peak inrush (A), time above 10 % of peak,
and I²t (A²·s). Non-invasive AC-mains complement to the DC-side
`projects/power/inrush/`. Characterized purely by current — valid without
voltage.

### 3. Current profiler / MQTT bridge  ✅ BUILT → `drivers/mqtt` bridge + `projects/power/current-profiler/`
Clamp → DMM, log AC **current** over time. On/off (duty-cycle) detection,
peak/avg/RMS current, session stats. Publishes to the MQTT bus so the existing
`timeseries_logger` and `alert_daemon` pick it up. **Labeled current, not
power** — see note below on why power is deferred.

---

## Power measurement — built (safety-gated) or blocked

These need **true power (W)**, which requires sensing mains **voltage**
simultaneously with current. Knowing only current and assuming 120 V × PF = 1
gives **wrong** numbers for reactive/nonlinear loads — so nothing here fakes
watts from current alone.

The **driver gap is now closed**: `SDS2000X.capture_two_channels()` (added
2026-07-10) captures both channels from ONE acquisition, so V and I are
phase-aligned — the prerequisite for a correct power factor.

The **safety blocker is physical, not code**: sensing a mains hot conductor on a
bench scope is a shock / ground-loop hazard needing a **differential probe** or
an **isolation transformer**.

### 4. Scope AC power analyzer  ✅ BUILT (safety-gated) → `projects/power/ac-power/`
v(t)·i(t) → real power, apparent power, reactive power, power factor. Uses
`capture_two_channels()`. **Refuses to run without `--i-have-isolation`** (and
requires `--volt-scale`) so the isolation-hardware decision is explicit. Math
validated on synthetic signals (120 V/10 A/60° → 600 W, PF 0.5). Not yet run
against hardware — needs the burden resistor + differential probe/isolation xfmr
below.

### 5. PSU / transformer efficiency map  ⏸ DEFERRED
Clamp measures AC **input** current; `yertai` DC load measures DC output power.
Efficiency = P_out / P_in needs real P_in (W) from #4's analyzer plus the same
isolation hardware. Now a thin add-on once #4 runs against hardware: sweep the
DC load, read input power via the analyzer, plot η vs load. Deferred only until
#4 is hardware-verified.

---

## Poor fit — wrong instrument, do NOT build

- **Standby / phantom-load hunting** — a 100 W device is <1 A at 120 V, below
  the 1 A floor and buried in the ±0.4 A error. Use a low-range clamp or an
  inline power meter instead.
- **Leakage / ground-fault imbalance** — needs mA resolution; this clamp
  resolves whole amps.
- **Anything RF / >1 kHz** — the 80i-400 rolls off past 1 kHz.
- **DC current** — it's an AC current transformer; DC is not passed and not
  datasheet-specified (`Fluke80i400.read(dc=True)` exists only for off-label
  experimentation).

---

## Hardware shopping list to unblock #4/#5

- One **burden resistor** for the scope front-end: 1 Ω, ≥¼ W, low inductance
  (1 mV/A). Already needed for #1/#2.
- One **differential probe** (e.g. 1400 V CAT III) *or* a **mains isolation
  transformer** for safe voltage sensing.
- Driver: add `SDS2000X.capture_two_channels()` (single-arm, CH1+CH2, shared
  timebase) so V and I are phase-aligned.
