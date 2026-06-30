## Future project ideas (not yet started)

The pure-idea section. Numbering matches the original `ideas.md` where it
existed (some old numbers in the 1–95 range are now built and live in the
[built projects](#built-projects--by-domain) tables above).

### Future-power

#### Multi-Chemistry Battery Charger

`projects/power/charger/` — not started.

The SPD3303X-E is a programmable CC/CV bench supply with automatic crossover
— which is what every commercial charger actually is, dressed up. SDM3045X
gives precise terminal-voltage readback; ET5406A+ closes the loop with
capacity / discharge testing. Most of the work is software: a per-chemistry
state machine that drives the supply and logs V/I/Ah vs time.

**Easy (a weekend project):**

- **Lead-acid (flooded / AGM / gel):** classic 3-stage — bulk CC at C/10,
  absorption CV at 14.4–14.7 V (chemistry-dependent) until current tapers to
  ~C/50, float at 13.5 V.
- **LiFePO4:** CC to 3.65 V/cell, hold CV until current drops below ~C/20,
  terminate.
- **Li-ion (single cell, or pack with external BMS):** CC to 4.20 V/cell,
  CV taper, terminate at ~C/20.

**Harder:**

- **NiCd / NiMH:** want **−ΔV detection** (cell voltage droops slightly
  when fully charged) plus a dT/dt backstop. SDM3045X has the resolution
  but the −ΔV is small; needs solid noise rejection. Timer + temperature
  cutoff is the safer fallback.
- **Multi-cell lithium packs:** a bench PSU charges the pack, not
  individual cells. **Without a BMS in the pack, do not charge it from a
  bare PSU — that's how fires start.** Not solvable from rf-bench.
- **Temperature monitoring:** none of the bench DMMs are wired for cell
  temp. Cheapest add: 10 kΩ NTC + Bus Pirate ADC, DS18B20 on Flipper
  GPIO, or a USB thermocouple. Mandatory before NiCd/NiMH or fast-charge.

**SPD3303X-E hardware limits:**

- 32 V / 3.2 A per channel → up to ~7s lead-acid, ~8s LiFePO4, ~7s Li-ion
  at modest rates. Big 12 V AGM banks at 10 A are out.
- Two channels in series → 64 V if needed, but loses independent CC/CV
  per channel.

**Non-obvious safety risk that must be designed in:**

Bench PSUs have **no reverse-polarity protection** and **no battery-
disconnect detection**. If leads are clipped backwards, or the battery
falls off mid-charge and the PSU re-energizes onto a sparking lead, either
the supply or the battery (or both) can be damaged. Mitigations:

- Inline fuse + reverse-blocking diode in the charge harness.
- Use the XL9535 board to gate the PSU output through a relay that the
  state machine commands open before any state change and closed only
  after V_set has stabilised. The relay, not the PSU's analog control
  loop, is the gatekeeper.
- Pre-charge sanity check: before commanding the PSU on, momentarily
  energize the relay through a high-value series resistor and confirm the
  measured terminal voltage is in the expected polarity / range for the
  selected chemistry.

**Phasing:**
- v1: lead-acid + LiFePO4. No temp sensor needed; both terminate cleanly
  on current taper.
- v2: Li-ion (single cell + pack via BMS).
- v3: NiCd / NiMH once a temp sensor is on the bench.

### Future-rf

#### 4-Tone IMD Source for OFDM-style amplifier linearity

`projects/rf/4tone-imd/` — not started.

SDG (2 ch) + MHS-5225A (2 ch) + 4-port resistive combiner gives four
arbitrary independent tones. Standard test for broadband linear amps
handling OFDM; the SDG and MHS are deliberately **not phase-locked**, which
matches real OFDM signals (spectrally complex, not phase-coherent). This
isn't possible with the SDG alone (only 2 channels) and isn't worth doing
on the SDG plus a single-channel third source (only 3 tones).

#### Bench-internal traceability chain (Bootstrap calibration)

See [traceability chain](#traceability-chain) below.

### Future-koolertron

These all live under `projects/signal-sources/` and exploit the MHS-5225A's
unique-on-this-bench combination of dual-channel DDS + counter + low cost.

#### MHS-5225A two-tone IMD source
Drive CH1 + CH2 at f1 and f2 (~100 kHz apart) into a hybrid combiner, feed
the composite into a DUT, and measure IM3 on the SSA. Pure software. The
MHS has independent phase per channel — required for repeatable two-tone.

#### MHS-5225A as backup frequency reference counter
Patch the MHS counter onto any source via a power splitter and read out
independently of the SSA marker. ~7 ppm uncalibrated TCXO accuracy; better
than that against the GPS-disciplined Si5351 reference.

#### Long-term Allan-deviation frequency stability logger
Counter at 10 s gate watching SDG1062X output at 10 MHz for 24–48 h, log
per-minute, compute σ_y(τ). Characterises the SDG's TCXO short- and
long-term stability — neither of which Siglent publishes quantitatively.

#### MHS as sacrificial source for stress / destruction testing
RF input over-voltage testing, antenna survivability under simulated-
lightning pulse, MOSFET gate-driver torture, reverse-bias zener tests,
under-spec thermal testing of TVS arrays. The MHS is cheap enough to be
sacrificial; replacing the SDG output stage is far more painful.

#### MHS sweep + scope Bode plotter
Internal sweep mode runs autonomously; scope captures envelope vs time;
post-process maps time → frequency from sweep parameters. Less precise
than SDG-driven software-stepped sweep but ~10× faster for one-shot scalar
plots.

### Future-nanovna

Projects exploiting the NanoVNA-F's specific characteristics — cheap,
battery-powered, USB-portable, screen-equipped — that the rack-bound
HP 8712B cannot match. All target the swappable VNA API
(`rf_bench.nanovna.NanoVNA` ↔ `rf_bench.hp.HP8712B`), so the same script
runs on either VNA — falling back to the HP for full S22/S12 work where
applicable. Driver verified against the user's NanoVNA-F on 2026-06-30
(17 API smoke tests pass).

#### Field antenna sweep (battery-powered)
`projects/vna/field-antenna/` — 🧪 **built 2026-06-30**.

The script is a minimal-fuss USB-tethered version: one CLI flag,
.s1p + PDF with UTC-timestamped filenames. The on-device standalone
workflow (capture into NanoVNA internal flash, pull off later) is
still a separate idea.

#### Coax TDR via S11 IFFT
`projects/vna/tdr-pdf/` — 🧪 **built 2026-06-30** (not yet run against hardware).

Wideband S11 sweep → IFFT → step + impulse response. Identifies
discontinuities (open, short, kink, water ingress, connector quality)
at known velocity factor. Cable-VF presets (RG-58, RG-213, LMR-400,
9913, Heliax-1/2, etc.), fault auto-classification, choice of window
(Hann / Hamming / Blackman / Kaiser / rect), zero-pad interpolation.
Works on both VNAs (host-side math). The original future-list note
about "tower-base portability" still matches — NanoVNA-F runs on
batteries; the HP can't.

#### Balun / common-mode-choke characterizer
**Two projects built 2026-06-30** (neither run against hardware yet):

- `projects/vna/balun-pdf/` — 🧪 two-pass S11+S21 capture of a balun
  with each leg measured against the other terminated in 50 Ω.
  Outputs RL, insertion loss, amplitude balance, phase balance vs
  frequency. 0° / 180° nominal-phase flag for current vs voltage
  balun topologies.
- `projects/vna/choke-pdf/` — 🧪 series-through fixture method
  (Z = 2·Z0·(1−S21)/S21). Outputs |Z|, R, X with target line
  configurable (2 kΩ / 5 kΩ thresholds standard for HF / VHF).

Together these cover the original "balun-test" idea.

#### Cable loss + electrical-length library
`projects/vna/cable-loss-pdf/` — 🧪 **partially built 2026-06-30** (per-cable
PDF; the persistent YAML library is still future work).

The PDF generator captures S21 of a cable as a THRU and outputs total
loss plus per-100-ft (or per-100-m) with a manufacturer overlay (RG-58,
LMR-400, Heliax-1/2, etc.) and optional pass/fail target. The "save to
`~/.rf-bench/cables.yaml` so downstream projects auto-de-embed" idea
is still TODO — currently each cable check is a one-shot PDF.

#### Real-time filter tuning aid
`projects/vna/filter-tuning/` — 🧪 **built 2026-06-30** (live matplotlib
window with target-mask overlay; audible-beep feature still pending).

NanoVNA-F runs continuously on the bench; the host overlays target
filter response on the live S21 trace. Useful when tuning crystal /
cavity / LC filters by hand — eyes on the filter knobs.

#### Multi-segment wideband sweep
`projects/vna/multi-segment-sweep/` — 🧪 **built 2026-06-30**.

The NanoVNA caps at 401 points per sweep. For span / point combinations
that exceed that, stitch contiguous segments. Trade-off: SOLT
calibration discontinuity at segment edges (drawn as faint vertical
lines on the output PDF so you can see them).

#### NanoVNA-vs-SSA amplitude cross-check
`projects/vna/vs-ssa-cross-check/` — 🧪 **built 2026-06-30** (see project README for hardware caveats where applicable).

SDG1062X drives a coupler; SSA3032X reads through-arm absolute power
in dBm; NanoVNA reads coupler-tap S21. With known coupler coupling
factor, both readings should agree. Deviation reveals NanoVNA amplitude
calibration drift between SOLT runs. Output: per-frequency dBFS→dBm
trim table that subsequent NanoVNA-based amplitude projects can apply.

#### Portable RF survey of installed cable plant
`projects/vna/portable-rf-survey/` — 🧪 **built 2026-06-30** (see project README for hardware caveats where applicable).

Walk an installation site, sweep S11 of every visible cable / antenna /
patch-panel feed. Aggregate into a single HTML report: VSWR plots,
problem-cable highlights, recommended fixes. NanoVNA-F's built-in
display provides on-site go/no-go; the host report adds analytics.

#### Day-zero baseline & drift monitor
`projects/vna/stability-logger/` — 🧪 **built 2026-06-30** as a
general drift logger. Originally proposed as a verification-standard
monitor (`doe-iso-baseline/`); the built version is more general — it
appends one S11 capture's headline metrics to a CSV each invocation,
optionally writes a trend-line PDF, and returns exit-code 2 when a
configurable alert threshold is crossed. Use it on a precision LOAD
for SOLT-drift monitoring; use it on the antenna feedpoint for
seasonal drift tracking.

#### Small-signal amplifier S-parameter vs bias contour
`projects/vna/amplifier-curve/` — 🧪 **built 2026-06-30** (see project README for hardware caveats where applicable).

NanoVNA + SPD3303X-E to set bias. Sweep over Vds / Id grid; capture
S21, S11 at each point. Output: gain contour vs bias, |S21/S12|
estimate (NanoVNA-only proxy for MAG — true MAG needs HP for S12),
unconditional-stability heatmap. RF amplifier characterization for the
homebrew bench.

#### Two-port fixture de-embedding
`projects/vna/de-embed-fixture/` — 🧪 **built 2026-06-30** (see project README for hardware caveats where applicable).

SOLT-calibrate at the SMA plane. Measure the PCB fixture's S-parameters
via open / short / thru standards on the PCB. Use those to mathematically
remove the fixture from subsequent DUT measurements. Lets the NanoVNA
characterize SMT components above its raw port reference plane.

#### Crystal Q via S21 transmission test
`projects/vna/quartz-q/` — 🧪 **built 2026-06-30** (see project README for hardware caveats where applicable).

Note: `projects/vna/resonance-finder/` (🧪 built 2026-06-30) already
covers the loaded-Q part for any S11 dip — point it at the crystal in
a one-port fixture and it returns f₀, -3 dB BW, Q. The `quartz-q/`
idea is still distinct because it wants an *S21* shunt fixture for
unloaded-Q extraction with known fixture impedance.

Low-impedance shunt fixture across the crystal under test; NanoVNA
S21 sweep through the series-resonance minimum. 3 dB bandwidth gives
loaded Q; with known fixture impedance, unloaded Q follows. Pair with
Si5351 reference for sub-Hz frequency accuracy.

#### Connector / jumper audit
`projects/vna/connector-check/` — 🧪 **built 2026-06-30** (not yet run
against hardware).

S11 sweep with 50 Ω load on the back; PASS/FAIL per amateur band vs
a configurable RL threshold; PDF + JSON; non-zero exit on FAIL so it
runs from shell scripts. Catches the one bad PL-259 before it
pollutes an MDS measurement. The "walk-the-lab" aggregator (collect
every connector audit into one HTML report) is still TODO.

#### NanoVNA-as-power-detector for OOK link tests
`projects/vna/ook-power-detector/` — 🧪 **built 2026-06-30** (see project README for hardware caveats where applicable).

Single-frequency S21 capture in continuous mode while the OOK link
project's transmitter modulates. The NanoVNA acts as a calibrated
power detector at a known frequency, dB-magnitude vs time. Cheaper
substitute for `projects/rtlsdr/ook-link/`'s power-detector channel.

#### NanoVNA + Flipper Sub-GHz match validation
`projects/vna/flipper-subghz-match/` — 🧪 **built 2026-06-30** (see project README for hardware caveats where applicable).

Plug the Flipper Zero's external antenna SMA into the NanoVNA. Sweep
S11 over the Flipper's three Sub-GHz windows (300–348, 387–464,
779–928 MHz). Identifies which CC1101 channels actually have a matched
antenna vs which see mismatch. Useful for picking the optimal channel
for a given external antenna.

#### Antenna pattern via NanoVNA + rotator
`projects/vna/antenna-pattern/` — 🧪 **built 2026-06-30** (see project README for hardware caveats where applicable).

The `scpi-rotator` ESP32 project rotates a test antenna in az/el while
the NanoVNA captures S11. For each angle, log return loss; convert to
estimated radiation pattern (relative dB) over the swept azimuth /
elevation. Cheap polar pattern without an anechoic chamber. Pairs with
`projects/rf/antenna-range/`.

#### Wideband return-loss browser
`projects/vna/wideband-rl-browser/` — 🧪 **built 2026-06-30** (see project README for hardware caveats where applicable).

NanoVNA continuously sweeps 1 MHz – 1.5 GHz in segments. Web UI on
host displays the current wideband return-loss heat map; user clicks
to drill in. Useful as a permanently-running rough survey scope —
new resonances, new RF leakage paths, broken jumpers all show up here
first.

#### NanoVNA-F screen-grab + live-trace web export
`projects/vna/screen-export/` — 🧪 **built 2026-06-30** (see project README for hardware caveats where applicable).

The NanoVNA-F has a `capture` shell command that returns the screen
framebuffer. The project converts the captured image to PNG and
serves it on a local HTTP endpoint, optionally annotated with the
current sweep parameters. For documentation and remote viewing.

### Future-vna-math

Pure-host-side processing on top of S-parameter captures, all of
which work identically on the NanoVNA and the HP 8712B since the
math is post-capture. Roughly ordered "would actually be useful
day-to-day" → "cool but niche". Anything marked ✅ here has since
been built — see the "BUILT" parenthetical at the end.

#### Time-domain transformations (extend `tdr-pdf/`)

**Time gating.** TDR a cable, define a time window around one
specific reflection, IFFT back to the frequency domain. The result
is the frequency response of just *that one connector*, isolated
from everything else in the run. Hugely useful when you have a
multi-connector feedline and need to know "which of these 8 PL-259s
is bad?" ~200 lines on top of `tdr-pdf/`. **(✅ BUILT 2026-06-30 as
the `--gate-start-m` / `--gate-end-m` flags on `tdr-pdf/`.)**

**TDT (time-domain transmission).** Same math on S21 instead of
S11. Finds lumped reflections **inside** a 2-port DUT — bonding-wire
mismatches in an amplifier, board-trace discontinuities, internal
filter element parasitics. The HP 8712B has it natively as
`:CALC:TRAN:STATE ON`; NanoVNA needs host-side compute. **(✅ BUILT
2026-06-30 as `projects/vna/tdt-pdf/`.)**

**Bandpass-mode TDR.** For sweeps that don't start at DC (most
non-NanoVNA-F gear). The current `tdr-pdf` script uses low-pass
mode; bandpass mode uses the analytic signal (Hilbert transform of
the band-shifted spectrum) instead. **(✅ BUILT 2026-06-30 as
`projects/vna/bandpass-tdr-pdf/`.)**

#### Calibration and reference-plane tricks

**De-embedding.** Measure a fixture's S-parameters once, save as
Touchstone, then *mathematically subtract* it from every subsequent
measurement. Moves the reference plane from "at the SMA jack" to
"at the chip pad." Industry-standard technique; one of the highest-
value VNA tricks. Pure host-side matrix algebra; works identically
on both VNAs. **(✅ BUILT 2026-06-30 as `projects/vna/de-embed-pdf/`.)**

**TRL (Thru-Reflect-Line) calibration.** Better than SOLT on PCB
fixtures because no fragile precision OPEN standard is required.
Works at frequencies where you can build precise transmission-line
standards. Pure host-side once raw uncorrected S-params are
captured. — 💭 not started.

**Renormalization.** Convert measured 50 Ω S-params to S-params *at
any reference impedance* — 75 Ω (CATV / SDI), 100 Ω (differential
pairs), 600 Ω (open-wire ladder line). One-line numpy. Lets a 50-Ω
VNA characterize a 75-Ω device honestly. **(✅ BUILT 2026-06-30 as
`projects/vna/renormalize-pdf/`.)**

#### Multi-port emulation with a 2-port VNA

**Mixed-mode / differential S-parameters.** Capture all four
single-ended S-params (the trick already used by `sparams-pdf`),
then apply a fixed 4×4 transform to get differential-mode S_dd,
common-mode S_cc, and conversion-mode S_dc / S_cd. Lets you score
"is this CAT5 line common-mode-rejecting properly?" or "is this
LVDS pair really differential?" — **(✅ BUILT 2026-06-30 as
`projects/vna/mixed-mode-pdf/`.)**

**Full 4-port DUT characterization with a 2-port VNA.** Six pair-
wise captures with the other two ports terminated; reconstruct the
full 4×4 S-matrix. Classical "poor man's 4-port VNA" recipe. Quite
painful operator-wise (6 swaps + reterminations); listed for
completeness. — 💭 not started.

#### Component model extraction (S-params → schematic)

**BVD (Butterworth-Van Dyke) crystal extraction.** Sweep S21 across
a crystal's series resonance, fit to the 4-parameter motional
model: motional inductance Lm, motional capacitance Cm, motional
resistance Rm, and shunt capacitance C₀. Used by every crystal
manufacturer; pure curve-fit on top of `resonance-finder/`. Output
includes a schematic-symbol overlay and a SPICE-paste-ready BVD
netlist. **(✅ BUILT 2026-06-30 as `projects/vna/crystal-bvd-pdf/`.)**

**Vector Fitting** (Gustavsen's classic algorithm, 1999). Fit
measured S-params with a rational function (sum of poles +
residues), getting an *analytic* model that can be exported to
**SPICE subcircuit format**. Take any measured 2-port and drop it
straight into LTspice as a `.subckt`. Most engineering value of
anything on this list. **(✅ BUILT 2026-06-30 as
`projects/vna/vector-fit-spice/`.)**

**Per-unit-length transmission-line RLGC extraction.** Measure
S-params of two known lengths of the same line, solve for
distributed R, L, G, C(f). Yields skin-effect coefficient,
dielectric loss tangent, propagation constant. Extension of
`tline-pdf/` math. **(✅ BUILT 2026-06-30 as
`projects/vna/rlgc-pul-pdf/`.)**

#### Statistical / quality work

**Stability logging.** Sweep a known reference standard every N
minutes via cron; track |S11| variance over hours / days.
Quantifies calibration drift; alerts when it exceeds spec.
**(✅ BUILT 2026-06-30 as `projects/vna/stability-logger/`.)**

**Causality check via Kramers-Kronig.** Re(S(ω)) and Im(S(ω)) of
any causal system are Hilbert transforms of each other. Compute one
from the other and compare to the measurement. Non-zero residual →
either non-causal measurement (= calibration error) or a non-linear
DUT. **(✅ BUILT 2026-06-30 as `projects/vna/kramers-kronig-pdf/`.)**

**Q-extraction triple cross-check.** Three independent Q methods —
3 dB bandwidth, Lorentzian fit, and Q-circle on the Smith chart —
should all agree to within a percent or two. Where they disagree,
the measurement is suspect. Useful for tuning high-Q crystals where
1 % matters. **(✅ BUILT 2026-06-30 as `projects/vna/q-cross-check/`.)**

#### Antenna and propagation science

**Wheeler-cap antenna efficiency.** Measure antenna Q in free
space, then re-measure inside a conducting cap (which suppresses
radiation). Comparison gives radiation efficiency vs ohmic
efficiency. NanoVNA-portable; finally tells you whether that tiny
mobile whip is actually radiating. **(✅ BUILT 2026-06-30 as
`projects/vna/wheeler-cap-pdf/`.)**

**Antenna factor calibration.** Pair the VNA with a calibrated
noise source to derive antenna factor in dB(m⁻¹). Lets you use a
homebrew antenna for absolute field-strength measurement. — 💭 not
started.

**NEC model verification.** Measure real antenna S11, compare to
NEC-2-simulated S11 of the modelled geometry. Disagreement
diagnoses the model — wrong height, wrong wire size, missing
ground, etc. — 💭 not started.

#### Cross-instrument combinations

**Antenna pattern via VNA + rotator.** Point a known antenna at the
DUT, rotate the DUT (via the ESP32 `scpi-rotator` project), measure
S21 magnitude at each angle. Cheap polar pattern without an
anechoic chamber. — 💭 not started.

**VNA + Bus Pirate-controlled digital attenuator.** Sweep across
the attenuator's full code space, characterise per-code attenuation
and phase shift vs frequency. Build a correction table; downstream
projects get true-dB-accurate attenuation. — 💭 not started.

**VNA-driven coupler power-meter.** DDS or SDG feeds a directional
coupler, VNA reads through-arm and coupled-arm S21, SSA reads
absolute power. Cross-calibrate the NanoVNA's relative-only S21
into absolute dBm using the SSA as transfer reference. — 💭 not
started.

#### Advanced math / curiosity

**Cepstral analysis of S11.** log-magnitude FFT separates discrete
cable reflections (sharp cepstral peaks) from distributed losses
(smooth cepstral background). Useful when TDR can't separate
closely-spaced reflections. **(✅ BUILT 2026-06-30 as
`projects/vna/cepstral-pdf/`.)**

**Mode decomposition in oversize waveguide.** When frequency goes
above a cable's TE₁₁ cutoff, S-params describe multi-mode
propagation. Modal analysis breaks it apart. Niche but
mathematically beautiful. — 💭 not started.

**Frequency-comb analysis.** Apply a known comb (e.g., a PLL with
many spurs) to a DUT, capture S21 at every comb tooth
simultaneously; faster than a full sweep over discrete bands. — 💭
not started.

#### Why these belong on `projects/vna/`

Every entry above is pure post-processing of a complex S-parameter
capture — no new hardware, no firmware mods. The capture happens
through the existing swappable VNA API; the math runs in Python
afterward. The HP 8712B and NanoVNA-F give identical results on any
of these (within their respective dynamic-range floors), so each
project's `--vna {nanovna,hp}` flag continues to work without
modification.

### Future-solartron

These are blocked on the KISS-488 adapter; code mostly does not exist yet.
All would live under existing project domains (`projects/dmm/`,
`projects/power/`, etc.).

#### 6.5-digit voltage-reference drift logger
LM399 / LTZ1000 / MAX6126 long-term drift on the 7151's 2 V range at I4
(~8 s integration, ~1 ppm absolute) — tracks the 1–10 ppm/yr drift of a
TC-zener over weeks. SQLite + matplotlib drift plot; XL9535 if comparing
multiple references.

#### TCR bridge — two-DMM temperature coefficient
7151 measures DUT resistance at 6.5 digits; SDM3045X reads chamber
thermocouple. Existing `projects/dmm/tcr/` would gain `--use-7151`.

#### 6.5-digit contact resistance tester
Submilliohm contact R is below SDM3045X noise floor. 7151 on 20 kΩ range
+ 6.5-digit averaging gets ~10 µΩ resolution after averaging.
Existing `projects/dmm/contact/` would gain `--use-7151`.

#### Solartron-vs-SDM3045X continuous cross-cal service
Both DMMs measuring the same voltage reference (LM399 / LTZ1000) daily,
indefinitely. The 7151's higher resolution exposes drift in either DMM at
~10 ppm scale long before either annual cal interval would. Catches
calibration drift without an external reference. systemd timer on greybox.

#### 6.5-digit micro-ohm battery internal resistance
Existing battery-tester rig + 7151 on 200 mV range gives ~1 µV / ~10 µΩ
sensitivity at 1 A test current. Matched-pair lithium cell selection,
EV-grade screening, aging studies. `projects/power/battery-tester/` gains
`--use-7151`.

#### 6.5-digit log-detector linearity
SDM3045X resolution is the floor on log-detector accuracy (~0.2 dB at
typical AD8307 slopes). 7151 sees down to ~0.01 dB. Decide whether a
cheap log detector can replace a real RF power meter.

#### Calibration-verification of the 7151 itself
Maintenance procedure rather than a project: drives `calibrate_on()` /
`cal_hi(count)` / `cal_lo(count)` / `cal_write()` against external
references. Needs a Fluke 5500A or equivalent (not in the lab) for full
range coverage; SPD3303X-E + precision shunt covers low-current/low-voltage.

### Future-cross-cutting

Generally cross-domain ideas that don't fit one bucket cleanly.

#### Antenna range characterization
`projects/rf/antenna-range/` — not started.

SDG (transmitter) at a GPS-surveyed point; walk receive antenna to GPS-
waypointed positions; log signal strength vs distance / azimuth.

#### Coherent multi-site recording (TDoA transmitter location)
`projects/rtlsdr/tdoa/` — research-grade.

Two RTL-SDRs at known GPS positions recording simultaneously. Requires
sub-millisecond time accuracy.

#### Vestigare own-ship overlay
Extend `~/vestigare/` to read own-aircraft GPS position from local gpsd
and overlay on the map.

#### GPS-to-APRS bridge
Extend `~/aprs-server/` to read from local gpsd as a position source
(in addition to phone GPS).

#### Calibrated mobile spectrum survey (deferred)
Same concept as `projects/rtlsdr/survey/` but with SSA3032X instead of
RTL-SDR for calibrated dBm. Deferred because the SSA isn't easily portable.

#### APRS position transmitter
`projects/radio/aprs-tx/` — deferred.

GPS + IC-7300 + software TNC. Requires a TNC driver that doesn't exist yet.

### Future-logic-analyzer

Projects using the FX2LAFW "24MHz 8CH" Saleae-compatible logic analyzers. User has three units. Driver: `rf_bench.fx2lafw`.

#### Protocol Decoder Integration

`projects/logic-analyzer/protocol-decode/` — 💭 not started.

**What it does:** Integrate sigrok-cli protocol decoders into Python. Capture I2C/SPI/UART/1-Wire/CAN traffic, decode via sigrok, present results as structured Python dicts. Useful for automated protocol compliance testing.

**Hardware:** FX2LAFW logic analyzer + DUT (sensor, EEPROM, display, etc.)

**Implementation:**
- Capture with `rf_bench.fx2lafw.FX2LAFWLogicAnalyzer.capture()`
- Export to temporary file
- Call `sigrok-cli -P <protocol>` with appropriate channel mappings
- Parse sigrok text output into Python data structures
- Present as list of decoded frames

**Example use:** Capture I2C traffic from temperature sensor, decode to `[{'type': 'START'}, {'type': 'ADDRESS', 'addr': 0x48, 'rw': 'write'}, ...]`

**Why useful:** Automated testing without manual PulseView analysis. Can assert that DUT sends expected I2C sequences.

#### UART Baud Rate Auto-Detector

`projects/logic-analyzer/uart-baud-detect/` — 💭 not started.

**What it does:** Capture unknown UART traffic, measure bit widths, identify baud rate. Reports detected baud (closest standard: 9600, 19200, 38400, 57600, 115200, etc.) plus parity/stop bits.

**Hardware:** FX2LAFW + unknown UART source

**Algorithm:**
1. Capture 100ms at 24 MHz
2. Find transitions (edges)
3. Measure shortest stable pulse width → bit time
4. Calculate baud = 1 / bit_time
5. Round to nearest standard baud rate
6. Decode with detected parameters to verify

**Use case:** Reverse engineering serial devices, identifying bootloader baud rates, debugging embedded systems.

#### SPI Flash Dumper

`projects/logic-analyzer/spi-flash-dump/` — 💭 not started.

**What it does:** Non-intrusive SPI flash memory dump via logic analyzer. Captures SPI bus traffic during boot or operation, decodes READ commands, reconstructs binary image.

**Hardware:** FX2LAFW probed onto SPI flash (CLK, MOSI, MISO, CS)

**Use case:** Firmware extraction from embedded systems, router/IoT device reverse engineering, PCB-level debug without desoldering chips.

**Limitations:** Only captures data actively read by the system. For full dump, need to stimulate reads (power cycle, trigger firmware updates, etc.)

**Output:** Binary file + annotated log showing address ranges read.

#### I2C Bus Scanner

`projects/logic-analyzer/i2c-scan/` — 💭 not started.

**What it does:** Passive I2C bus monitor. Listens to existing I2C traffic, identifies all active addresses, decodes register access patterns, infers device types from access patterns.

**Hardware:** FX2LAFW + I2C bus (SCL, SDA)

**Features:**
- List all I2C addresses seen
- Identify common devices (OLED displays, EEPROMs, sensors) by register patterns
- Traffic histogram (which addresses are busiest)
- Register map extraction (which registers are read vs written)

**Use case:** Reverse engineering I2C-based systems, identifying unknown sensors on dev boards, debugging I2C conflicts.

#### Timing Analyzer / Glitch Detector

`projects/logic-analyzer/timing-glitch/` — 💭 not started.

**What it does:** Long-running capture looking for timing violations or glitches. Monitors setup/hold times, pulse width violations, clock jitter, unexpected transitions.

**Hardware:** FX2LAFW + digital bus

**Detection:**
- Pulse widths < minimum spec
- Setup/hold violations (data changes too close to clock edge)
- Missing clock pulses
- Unexpected state transitions
- Metastability (rapid toggling)

**Output:** Timestamped glitch events + VCD file showing context around each glitch.

**Use case:** Debug intermittent failures, validate signal integrity, identify marginal timing.

#### PWM Analyzer

`projects/logic-analyzer/pwm-analyzer/` — 💭 not started.

**What it does:** Capture and analyze PWM signals. Measures frequency, duty cycle, jitter. Supports multi-channel (e.g., RGB LED driver, motor controller).

**Hardware:** FX2LAFW + PWM source

**Measurements per channel:**
- Frequency (Hz)
- Duty cycle (%)
- Jitter (σ, min, max)
- Phase relationship between channels

**Output:** CSV with per-channel stats, matplotlib plots showing duty cycle over time.

**Use case:** Validate motor controller output, characterize LED dimming, debug servo control signals.

#### Frequency Counter

`projects/logic-analyzer/frequency-counter/` — 💭 not started.

**What it does:** Measure signal frequency by counting edges over time. More accurate than oscilloscope counter for signals > 1 MHz.

**Hardware:** FX2LAFW (captures up to 24 MHz)

**Method:**
- Capture 1 second at max sample rate
- Count rising edges
- Report frequency with confidence interval

**Range:** 1 Hz to 12 MHz (Nyquist limit at 24 MS/s)

**Use case:** Validate oscillator output, measure PLL VCO frequency, check microcontroller clock.

#### Bus Pirate + Logic Analyzer Cross-Validation

`projects/logic-analyzer/buspirate-validation/` — 💭 not started.

**What it does:** Use Bus Pirate to generate known I2C/SPI/UART traffic, capture with logic analyzer, verify correctness. Validates both instruments against each other.

**Hardware:** Bus Pirate + FX2LAFW (loopback or through DUT)

**Test cases:**
- I2C: Write known data to EEPROM, verify logic analyzer captures correct address/data/ACK
- SPI: Transfer test pattern, verify bit timing and CPOL/CPHA
- UART: Send known string, verify baud rate detection and data decode

**Why useful:** Golden reference test — Bus Pirate is known-good, logic analyzer must match.

#### Embedded System Boot Trace

`projects/logic-analyzer/boot-trace/` — 💭 not started.

**What it does:** Capture all I2C/SPI/UART traffic during embedded system boot. Generates timeline showing when each device initializes, register writes, timing bottlenecks.

**Hardware:** FX2LAFW + embedded system (probe all buses)

**Output:**
- Timeline chart (Gantt-style) showing device init sequence
- Protocol annotated with register meanings (if known)
- Bottleneck identification (long pauses between transactions)

**Use case:** Optimize boot time, debug init failures, reverse engineer boot sequence.

#### CAN Bus Decoder

`projects/logic-analyzer/can-decode/` — 💭 not started.

**What it does:** Decode CAN bus traffic via logic analyzer. Captures CAN High/Low differential pair or CAN TX signal, decodes frames to show ID, data, CRC.

**Hardware:** FX2LAFW + CAN bus (1 or 2 channels depending on capture point)

**Supported:**
- Standard 11-bit IDs
- Extended 29-bit IDs
- Error frames
- Overload frames

**Use case:** Automotive diagnostics (OBD-II), industrial control systems (CANopen), robotics.

**Note:** Requires sigrok CAN decoder or manual Python decode implementation.

#### 1-Wire Bus Analyzer

`projects/logic-analyzer/onewire-analyzer/` — 💭 not started.

**What it does:** Decode 1-Wire bus (Dallas/Maxim protocol). Identifies device ROMs, decodes temperature readings, captures timing for standard vs overdrive speed.

**Hardware:** FX2LAFW + 1-Wire bus (DS18B20, iButton, etc.)

**Features:**
- ROM search sequence decode
- Temperature conversion timing
- CRC validation
- Multi-drop bus topology mapping

**Use case:** Debug DS18B20 sensor arrays, reverse engineer iButton locks, validate 1-Wire timing.

### Future-logic-analyzer-integrated

Multi-instrument projects that combine logic analyzer with other bench equipment.

#### SDG + Logic Analyzer: Signal Integrity Test

`projects/logic-analyzer/signal-integrity/` — 💭 not started.

**What it does:** SDG generates test pattern (square wave, PWM, clock), logic analyzer captures at various distances/loads/cable lengths. Measures rise/fall time degradation, overshoot, ringing, crosstalk.

**Hardware:** SDG1062X + FX2LAFW + test cables/loads

**Tests:**
- Rise/fall time vs cable length
- Overshoot vs load capacitance
- Crosstalk between channels
- Impedance mismatch effects

**Output:** Plots showing signal quality vs test condition, annotated VCD files.

**Use case:** Validate PCB layout, select appropriate termination, debug signal integrity issues.

#### Bus Pirate + Logic Analyzer: I2C/SPI Protocol Fuzzer

`projects/logic-analyzer/protocol-fuzzer/` — 💭 not started.

**What it does:** Bus Pirate generates semi-random I2C/SPI traffic (valid and invalid), logic analyzer monitors DUT responses, Python script logs crashes/hangs/error responses.

**Hardware:** Bus Pirate + FX2LAFW + DUT

**Fuzzing strategies:**
- Invalid addresses
- Malformed frames (bad CRC, incorrect length)
- Timing violations (clock glitches, stretched clocks)
- Unexpected NACK/ACK patterns

**Output:** List of inputs that cause DUT to crash/hang/misbehave.

**Use case:** Security testing, robustness validation, protocol compliance.

#### ESP32 + Logic Analyzer: Automated Protocol Compliance Suite

`projects/logic-analyzer/esp32-compliance/` — 💭 not started.

**What it does:** ESP32 generates I2C/SPI/UART traffic (via scpi-i2c/scpi-spi/scpi-uart), logic analyzer captures, Python validates compliance against protocol specs.

**Hardware:** ESP32 + FX2LAFW + optional DUT

**Test suite:**
- I2C: Clock stretching, repeated START, 10-bit addressing
- SPI: All CPOL/CPHA combinations, variable CS timing
- UART: Parity error injection, break conditions, framing errors

**Output:** Pass/fail report per test case, VCD files for failures.

**Use case:** Validate protocol stack implementations, regression testing.

#### SSA + Logic Analyzer: RF + Digital Correlation

`projects/logic-analyzer/rf-digital-correlation/` — 💭 not started.

**What it does:** Logic analyzer captures digital control signals (TX enable, frequency select, etc.), SSA captures RF output, Python correlates timing. Measures TX key-up time, frequency switching speed, spurious emissions during transitions.

**Hardware:** SSA3032X + FX2LAFW + radio or transmitter

**Measurements:**
- TX key-up time (digital assert to RF carrier detected)
- Frequency switching latency
- Phase noise during PLL lock
- Spurious emissions during mode changes

**Output:** Timeline showing digital events overlaid on RF spectrum, annotated plots.

**Use case:** Optimize transmitter control loops, debug spurious emissions, validate FCC compliance during transitions.

#### Scope + Logic Analyzer: Mixed-Signal Debug

`projects/logic-analyzer/scope-mixed-signal/` — 💭 not started.

**What it does:** SDS2504X Plus analog channels + FX2LAFW digital channels on shared trigger. Correlates analog waveforms with digital bus traffic.

**Hardware:** SDS2504X Plus + FX2LAFW + DUT

**Use case:** Debug ADC/DAC systems (capture analog input + SPI config), power supply droops during I2C transactions, clock jitter effects on analog signals.

**Trigger:** Logic analyzer detects digital event (I2C START, SPI CS falling), triggers scope analog capture.

**Output:** Synchronized VCD (digital) + scope CSV (analog), matplotlib plots overlaying both.

**Note:** SDS2504X Plus has built-in MSO option, but external logic analyzer provides more channels (8 vs 16 digital).

#### DMM + Logic Analyzer: Sensor Calibration Validator

`projects/logic-analyzer/sensor-calibration/` — 💭 not started.

**What it does:** DMM reads sensor analog output, logic analyzer captures digital I2C/SPI config, Python verifies that sensor reports match DMM measurements.

**Hardware:** SDM3045X + FX2LAFW + sensor DUT

**Test flow:**
1. Logic analyzer captures sensor config (range, gain, offset)
2. DMM measures sensor analog output
3. Logic analyzer captures sensor digital readout
4. Python compares: does sensor digital value match DMM analog reading?

**Output:** Calibration error plot (sensor reported vs DMM measured), list of out-of-spec sensors.

**Use case:** Production test ADCs, validate sensor calibration, identify defective units.

### Future-tci-router

#### TCI Audio Router — Linux sound device bridge

Discussed, not started. The problem: Linux ham software (WSJT-X, Fldigi,
Direwolf, JS8Call, etc.) expects audio I/O via a standard sound card.
ExpertSDR3 exposes audio via TCI (WebSocket binary stream), not as a sound
device. There is currently no bridge.

**The solution that covers ~99% of use cases:**

A single Python CLI that:
1. Connects to ExpertSDR3 TCI and subscribes to `RX_AUDIO_STREAM`
   (StreamType=1).
2. Writes the decoded PCM audio to a named audio device via `sounddevice`
   (PortAudio).
3. Ham software reads from the other side of an ALSA loopback
   (`snd-aloop`).

```bash
tci-audio --host 192.168.1.x --device "Loopback: PCM (hw:Loopback,0)"
# ham software then uses hw:Loopback,1 as its soundcard input
```

One `modprobe snd-aloop` creates the virtual loopback. `sounddevice`
abstracts ALSA / PulseAudio / PipeWire — the same code works on all three.

**Minimal CLI:**
```
tci-audio --host HOST
          [--port 50001]
          [--trx 0]
          [--rate 8000]       # 8/12/24/48 kHz; sent as AUDIO_SAMPLERATE
          [--device DEVICE]   # default: system default output
          [--list-devices]    # print available audio devices
```

**Implementation note — ring buffer is mandatory.** TCI pushes audio in
~32 ms chunks (256 samples @ 8 kHz). PortAudio's callback fires in chunks
on its own timer. Without a ring buffer between them, the timers drift
and cause dropouts. A `collections.deque` or `queue.Queue` is ~20 extra
lines but the difference between glitchy and clean.

**TCI audio setup sequence (sent before AUDIO_START):**
```
AUDIO_SAMPLERATE:8000;
AUDIO_STREAM_SAMPLE_TYPE:int16;
AUDIO_STREAM_CHANNELS:1;
AUDIO_START:0;
```
The binary frame header carries `sample_rate`, `format`, `length`,
`channels` per frame — read from the frame, don't hardcode.

**Why not stdout?** Stdout to `aplay` works for manual listening but
requires the user to manage the pipe and know ALSA syntax. Writing to a
named device is one command with no user plumbing.

**TX (sending audio to TCI for transmission) — deferred.** TX is harder
not because of the audio path (TCI `TX_CHRONO` is a clean request/response
model — server asks for N samples, client responds) but because of **PTT
coordination**. Something must assert `TRX:0,true,tci;` and that requires
integrating with how the ham software does PTT (Hamlib CAT, RTS/DTR, VOX,
etc.). System-integration problem, not TCI protocol.

PTT options when TX is eventually added:
- **VOX** — detect audio level above threshold in TX buffer, assert PTT.
  Simple, ~50–100 ms latency, no external deps.
- **Hamlib** — watch PTT state via rigctld polling. Correct but adds a
  dependency.
- **Named pipe / socket** — external PTT signal. Clean but needs per-app
  config.

For now, RX-only covers monitoring, decoding (WSJT-X / Fldigi / Direwolf),
recording, and spectrum — the majority of ham software use cases.

**Implemented (RX path):** `projects/sunsdr/tci-audiopipe/tci-audiopipe.py`
(archived working version: `archive/2026-06-06-working-proxy-solution/`).

**Dependencies:** `websocket-client` (already in sunsdr driver), `numpy`,
`pacat` / `parec` (PulseAudio / PipeWire CLI tools).

---

### Future-esp32-combos

ESP32 SCPI controllers paired with existing bench instruments for automated measurement, closed-loop control, and remote operation. Each combines an ESP32 project from `projects/esp32/` with one or more instruments from the hardware inventory.

**Pattern:** ESP32 acts as the orchestration layer — it reads sensors, commands instruments via their Python drivers, makes control decisions, and exposes high-level SCPI commands that abstract the complete measurement system.

#### ESP32 + SSA3032X: Automated antenna tuner with SWR feedback

`projects/esp32-combos/auto-tuner-ssa/` — 🔨 built to documentation.

**Hardware:** scpi-tuner (stepper L/C network) + scpi-ptt (TX sequencing) + SSA3032X tracking generator + power sensor.

**What it does:** Close-loop antenna tuner that keys the radio, measures forward/reflected power on the SSA, adjusts L/C via stepper motors, iterates until SWR < 1.5:1, then unkeys. Exposes `TUNE:AUTO,<freq_mhz>` SCPI command that abstracts the entire sequence.

**Why ESP32:** SSA has no power-sensor SCPI commands (only spectrum trace). ESP32 scpi-swr reads forward/reflected directly from AD8307 detectors, computes SWR, and drives the tuner. Python script on the host orchestrates SSA tracking generator enable/disable and reads SWR from the ESP32.

**Alternative:** scpi-tuner alone can auto-tune with built-in SWR sensor, but SSA tracking generator gives calibrated RF source and spectrum verification of harmonics.

#### ESP32 + SPD3303X: Closed-loop battery charger with temperature monitoring

`projects/esp32-combos/battery-charger/` — 🔨 built to documentation.

**Hardware:** scpi-temp (DS18B20 on battery case) + scpi-relay (output enable/disable) + SPD3303X (CC/CV source) + SDM3045X or scpi-adc (terminal voltage readback).

**What it does:** Multi-chemistry battery charger with per-chemistry state machines (lead-acid 3-stage, LiFePO4 CC/CV, Li-ion CC/CV taper, NiMH −ΔV detection). ESP32 monitors temperature via DS18B20, reads terminal voltage, commands PSU setpoints, and gates the relay for safety. Python script implements the state machine and logs V/I/T/Ah vs time.

**Why ESP32:** Adds temperature sensing and hardware interlock (relay gating) that the PSU alone lacks. scpi-temp provides 0.5°C resolution for −ΔV/dT detection on NiMH. scpi-relay acts as emergency cutoff if temperature or voltage anomalies occur.

#### ESP32 + IC-7300: Remote HF rig with rotator, PTT, and SWR monitoring

`projects/esp32-combos/remote-hf-station/` — 🔨 built to documentation.

**Hardware:** scpi-rotator (antenna az/el) + scpi-ptt (TX sequencing + VOX) + scpi-swr (forward/reflected power) + IC-7300 (via Hamlib rigctld).

**What it does:** Complete remote HF station control. Web UI sets frequency/mode on the IC-7300, aims the antenna, monitors SWR during TX, and provides visual feedback. ESP32 handles all near-radio hardware; Python backend bridges Hamlib and ESP32 SCPI.

**Why ESP32:** Puts antenna control, PTT sequencing, and SWR monitoring at the antenna/radio, eliminating long control cables. Web UI on the LAN or internet (via VPN) for remote operation.

#### ESP32 + SDG1062X: Arbitrary waveform recorder/playback with external trigger

`projects/esp32-combos/waveform-capture/` — 🔨 built to documentation.

**Hardware:** scpi-adc (ADS1115 16-bit 4-ch) + scpi-relay (trigger input) + SDG1062X (arb waveform playback).

**What it does:** scpi-adc samples an analog waveform at up to 860 SPS, stores it in CSV, uploads to SDG1062X as arbitrary waveform, replays on trigger. Use case: capture a transient (motor startup, audio glitch, RF burst), then replay it repeatedly for debugging.

**Why ESP32:** ADS1115 gives 16-bit resolution vs SDG's 14-bit internal arbitrary waveform depth. scpi-relay provides hardware trigger input. Python script handles CSV → SDG arb waveform upload via `rf_bench.siglent.SDG1000X`.

#### ESP32 + ET5406A+: Automated battery discharge tester with capacity logging

`projects/esp32-combos/battery-discharge/` — 🔨 built to documentation.

**Hardware:** scpi-load (or scpi-relay controlling the ET5406A+ via Yertai driver) + scpi-temp (battery temperature) + scpi-adc (terminal voltage).

**What it does:** Automated battery discharge test. Sets constant current load via ET5406A+, monitors terminal voltage via scpi-adc, logs V/I/T vs time, integrates for mAh/Wh capacity, terminates at cutoff voltage. Multi-cell parallel testing via scpi-mux.

**Why ESP32:** scpi-temp provides per-cell temperature monitoring (critical for lithium cells). scpi-adc gives isolated voltage sensing if testing multiple cells in parallel. Python script logs to SQLite and generates capacity curves.

**Alternative:** Use scpi-load (ESP32 MOSFET electronic load) directly instead of ET5406A+ for lower-power testing (<50W).

#### ESP32 + SDS2504X: Automated Bode plot with relay-switched filter bank

`projects/esp32-combos/bode-plotter/` — 🔨 built to documentation.

**Hardware:** scpi-relay (input switching for multi-DUT) + scpi-mux (analog mux for single DUT with multiple test points) + SDS2504X (scope CH1=input, CH2=output) + SDG1062X (swept sine).

**What it does:** Automated Bode plot measurement. SDG sweeps frequency, scope captures CH1/CH2 amplitude ratio and phase, scpi-relay switches between DUTs, Python script generates magnitude/phase plots. Extends existing `projects/scope/bode/` with multi-DUT capability.

**Why ESP32:** scpi-relay allows testing 4 filters back-to-back without manual cable swaps. scpi-mux allows probing multiple nodes on a single DUT (e.g., input, inter-stage, output of a 3-stage amplifier).

#### ESP32 + RTL-SDR: Wideband RF scanner with relay-switched antenna array

`projects/esp32-combos/antenna-array-scanner/` — 🔨 built to documentation.

**Hardware:** scpi-relay (4× antennas to single RTL-SDR input) + RTL-SDR + scpi-gps (position logging).

**What it does:** Scans 4 antennas sequentially across a frequency band, logs power spectrum per antenna, generates antenna pattern plots. Use case: compare dipole/vertical/loop/Yagi gain patterns across HF/VHF.

**Why ESP32:** scpi-relay switches antennas under software control. scpi-gps timestamps each scan for correlation with mobile surveys. Python script uses `rf_bench.rtlsdr` for power spectrum capture.

#### ESP32 + Flipper Zero: Automated Sub-GHz TX/RX protocol tester

`projects/esp32-combos/flipper-protocol-tester/` — 🔨 built to documentation.

**Hardware:** scpi-relay (DUT switching) + scpi-ptt (TX enable) + Flipper Zero (Sub-GHz TX/RX via `rf_bench.flipper`).

**What it does:** Automated protocol compliance testing. Flipper transmits OOK/FSK signals at various frequencies/data rates/modulation indices, scpi-relay switches between DUTs (receivers), Python script logs which DUTs decode correctly. Use case: test 433 MHz remote control receivers, garage door openers, tire pressure sensors.

**Why ESP32:** scpi-relay switches between up to 4 DUTs automatically. scpi-ptt provides TX sequencing if testing transmitters (Flipper in RX mode).

#### ESP32 + SDM3045X: Multi-point temperature profiling for thermal chambers

`projects/esp32-combos/thermal-profiler/` — 🔨 built to documentation.

**Hardware:** scpi-temp (8-16× DS18B20 sensors placed throughout chamber) + SDM3045X (reference thermometer) + scpi-heater (chamber heater PID control).

**What it does:** Measures temperature uniformity in a DIY thermal chamber. scpi-temp reads 8-16 sensors simultaneously, scpi-heater controls chamber temperature via PID, SDM3045X provides calibrated reference. Python script logs spatial temperature distribution and computes max deviation.

**Why ESP32:** DS18B20 1-Wire bus supports 8-16 sensors on a single GPIO, providing spatial profiling impossible with a single DMM. scpi-heater closes the loop for setpoint tracking.

#### ESP32 + Bus Pirate: I2C/SPI device characterization with automated sweeps

`projects/esp32-combos/peripheral-tester/` — 🔨 built to documentation.

**Hardware:** scpi-i2c (or scpi-spi) + Bus Pirate (for comparison/golden reference) + scpi-relay (power cycling DUT).

**What it does:** Automated I2C/SPI device testing. Sweep register addresses, write test patterns, read back, verify. Compare ESP32 I2C master vs Bus Pirate for signal integrity. scpi-relay power-cycles DUT between tests. Use case: characterize ADCs, DACs, EEPROMs, sensors.

**Why ESP32:** scpi-i2c and scpi-spi provide network-accessible I2C/SPI masters. Bus Pirate serves as golden reference for signal-level verification. Python script orchestrates both via `rf_bench.buspirate` and ESP32 SCPI.

#### ESP32 + Koolertron MHS-5225A: Dual-channel IQ modulator with ESP32 DAC correction

`projects/esp32-combos/iq-modulator/` — 🔨 built to documentation.

**Hardware:** scpi-dac (MCP4728 4-ch DAC for I/Q offset/gain trim) + MHS-5225A (dual-channel DDS for I/Q carriers) + SSA3032X (IQ quality measurement).

**What it does:** Generates IQ-modulated RF via MHS-5225A dual channels, uses scpi-dac to trim I/Q DC offsets and amplitude imbalance, measures carrier suppression and sideband symmetry on SSA. Iterates for optimal IQ balance. Use case: SDR TX calibration, IQ modulator testing.

**Why ESP32:** scpi-dac provides 12-bit I/Q trim adjust. MHS-5225A has independent phase per channel (required for IQ). Python script optimizes DAC settings by reading SSA carrier/sideband levels via `rf_bench.siglent.SSA3000X` and `rf_bench.koolertron.MHS5200A`.

#### ESP32 + IC-9700: Automated satellite pass recorder with Doppler correction

`projects/esp32-combos/satellite-recorder/` — 🔨 built to documentation.

**Hardware:** scpi-rotator (antenna az/el tracking) + scpi-gps (position + time) + IC-9700 (VHF/UHF RX with Doppler correction via Hamlib).

**What it does:** Fully automated satellite pass recording. Predicts passes via TLE (AMSAT/SatNOGS), aims antenna, tunes IC-9700 with real-time Doppler correction, records audio, stores metadata (pass time, max elevation, Doppler curve). Use case: unattended capture of ISS SSTV, weather satellite APT, amateur FM repeaters in LEO.

**Why ESP32:** scpi-rotator provides precise antenna aiming. scpi-gps supplies position (for pass prediction) and time (for TLE propagation). Python script uses `rf_bench.icom.IC9700` for Doppler updates and `rf_bench.gpsd` for observer state vector.

#### ESP32 + SPD3303X + SDM3045X: Precision op-amp offset voltage measurement

`projects/esp32-combos/opamp-offset/` — 🔨 built to documentation.

**Hardware:** scpi-mux (CD4067 16-ch analog mux for multi-DUT) + scpi-relay (power supply switching) + SPD3303X (±15V rails) + SDM3045X (µV-resolution DC voltage).

**What it does:** Automated op-amp input offset voltage measurement. scpi-mux switches between 16 DUT op-amps, scpi-relay powers them sequentially, SPD3303X supplies ±15V rails, SDM3045X measures output voltage in unity-gain configuration (Vout = Vos). Python script logs Vos vs temperature if combined with scpi-temp.

**Why ESP32:** scpi-mux allows testing 16 op-amps automatically. scpi-relay gates power to prevent heating adjacent DUTs. Python script uses `rf_bench.siglent.SPD3303X` and `rf_bench.siglent.SDM3000X`.

#### ESP32 + XL9535 relay: Multi-instrument RF routing matrix

`projects/esp32-combos/rf-matrix/` — 🔨 built to documentation (blocked on XL9535 hardware).

**Hardware:** scpi-relay (or scpi-matrix) + XL9535 relay board (16 relays) + RF coaxial relays (external, driven by XL9535 via `rf_bench.relay.XL9535`).

**What it does:** 4×4 or 8×2 RF signal routing matrix. Routes SSA TG, SDG output, IC-7300 TX, or RTL-SDR input to any of 4-8 DUTs or test fixtures. Controlled via SCPI `ROUT:CLOS (@in!out)` commands. Use case: automated multi-DUT RF testing without manual cable swaps.

**Why ESP32:** scpi-matrix provides SCPI interface. XL9535 provides 16 relay outputs for complex routing topologies. Python script abstracts routing as "connect source X to DUT Y" rather than low-level relay bit patterns.

**Note:** XL9535 hardware not yet available (ordered 2026-06-03). Project blocked until board arrives and `rf_bench.relay.XL9535` driver is tested.

#### ESP32 + SSA3032X + scpi-atten: Automated receiver sensitivity (MDS) measurement

`projects/esp32-combos/mds-sweep/` — 🔨 built to documentation.

**Hardware:** scpi-atten (PE4302/HMC472 0-31 dB) + SSA3032X tracking generator + IC-7300 or IC-9700 (RX under test via Hamlib).

**What it does:** Automated minimum detectable signal (MDS) measurement across HF/VHF bands. SSA TG outputs calibrated signal, scpi-atten steps from 0 to −140 dBm (TG + attenuation), radio reports S-meter reading via Hamlib, Python script finds the attenuation where S-meter drops below noise floor. Generates MDS vs frequency plot.

**Why ESP32:** scpi-atten provides programmable attenuation in 0.5 dB steps. Python script uses `rf_bench.siglent.SSA3000X` (TG control), SCPI to scpi-atten, and `rf_bench.icom.IC7300` (S-meter readback).

**Enhancement:** Add scpi-ptt to measure TX power vs frequency for complete TX/RX characterization in one script.

#### ESP32 + SDG1062X: Precision function generator with DAC-corrected offset/amplitude

`projects/esp32-combos/precision-funcgen/` — 🔨 built to documentation.

**Hardware:** scpi-dac (MCP4728 4-ch 12-bit DAC) + SDG1062X + SDM3045X (voltage verification) + summing amplifier circuit (external).

**What it does:** Extends SDG1062X with external DAC-generated DC offset and amplitude scaling. scpi-dac outputs 0-3.3V control voltages, external analog circuit sums SDG AC with DAC DC offset and scales amplitude. Python script commands SDG waveform, adjusts scpi-dac for precise Vpp and Voffset, verifies on SDM3045X. Use case: generate signals with <0.1% amplitude accuracy or µV-level offsets beyond SDG specs.

**Why ESP32:** scpi-dac provides network-controlled analog outputs. SDG alone has 1% amplitude accuracy; adding external DAC + verification loop tightens to SDM resolution (~0.01%). Python script uses `rf_bench.siglent.SDG1000X`, SCPI to scpi-dac, and `rf_bench.siglent.SDM3000X`.

#### ESP32 + SDS2504X: Multi-channel logic analyzer with I2C/SPI/UART decode

`projects/esp32-combos/logic-analyzer/` — 🔨 built to documentation.

**Hardware:** scpi-i2c or scpi-spi or scpi-uart (DUT traffic generation) + SDS2504X digital channels (protocol decode).

**What it does:** Generates I2C/SPI/UART traffic via ESP32, captures on scope digital channels, verifies protocol decode matches transmitted data. Use case: validate I2C sensor datasheets, debug SPI timing violations, test UART parity/framing error handling.

**Why ESP32:** scpi-i2c/spi/uart provide known-good reference traffic. SDS2504X decodes I2C/SPI/UART in hardware. Python script uses `rf_bench.siglent.SDS2000X` to read decoded frames and compares to ESP32 transmitted data via SCPI.

**Note:** Requires SDS2504X MSO option (digital probes). If not installed, use scope analog channels + manual decode.

---
### Future-multi-instrument

Multi-instrument coordination via Python for measurements impossible with single instruments. No ESP32 required — pure `rf_bench.*` driver integration.

#### SSA + SDG phase-locked two-tone IMD

`projects/rf/two-tone-imd/` — 💭 not started.

SSA3032X + SDG1062X generate phase-coherent two tones (f1, f2) for true IP3 measurement. Existing MHS-5225A two-tone idea uses non-phase-locked sources (realistic for OFDM but not for IMD spec). This project synchronizes SDG CH1/CH2 via internal phase lock (if available) or external 10 MHz reference. SSA measures IM3 products at 2f1-f2 and 2f2-f1. Extends `projects/radio/receiver-test/` with proper two-tone IMD measurement.

**Why this combination:** SDG phase-locks CH1/CH2 internally. SSA measures IM3 with calibrated dBm. MHS-5225A alternative (separate project) uses independent phases for OFDM-style testing.

**Blocked on:** Verify SDG1062X internal phase-lock capability via SCPI or 10 MHz reference.

#### IC-7300 + IC-9700 diversity reception

`projects/radio/diversity/` — 💭 not started.

Two radios tuned to same frequency, Python combines audio via equal-gain combining (EGC) or maximal-ratio combining (MRC) based on SNR estimates. Logs SNR improvement vs single receiver. Use case: weak signal DX, EME, meteor scatter.

**Hardware:** 2× radios (IC-7300 + IC-9700 or 2× IC-7300), 2× antennas with independent fading, USB audio capture, sounddevice Python library.

**Why this combination:** Existing hardware. IC-9700 VHF/UHF ideal for space communications. IC-7300 HF for ionospheric fading. Python synchronizes samples, estimates SNR per channel, weights/combines.

#### Dual SSA coherent measurements

`projects/rf/coherent-ssa/` — ❌ blocked on second SSA.

Two SSA3032X units with 10 MHz reference lock for phase noise correlation, EMI source location via TDoA, or coherent gain measurement. Use cases: identify correlated vs uncorrelated noise sources, locate interference via antenna array + time delay.

**Why this combination:** Phase-locked SSAs enable coherent measurements impossible with single unit.

**Blocked on:** Acquiring second SSA3032X Plus.

#### SDG + scope fast transfer function analyzer

`projects/scope/fast-bode/` — 💭 not started.

Extends `projects/scope/bode/` with real-time swept frequency response. SDG sweeps via hardware sweep mode (autonomous, no SCPI per-point), scope captures envelope via fast acquisition mode. Orders of magnitude faster than software-stepped sweep for scalar (magnitude-only) Bode plots.

**Why this combination:** SDG hardware sweep (~100 Hz sweep rate) + scope fast acquisition (~1000 wfm/s) eliminates SCPI round-trip latency. Tradeoff: magnitude only (no phase) unless scope supports FFT phase extraction.

### Future-ml-signal-analysis

Machine learning applied to SDR streams (RTL-SDR, KiwiSDR, SunSDR) for automated signal analysis. All projects require pre-recorded training datasets or live labeling.

#### Modulation classifier

`projects/rtlsdr/ml-modulation/` — 💭 not started.

Train CNN or ResNet on IQ samples from AM/FM/SSB/CW/PSK/FSK/OFDM/QAM. Classify unknown signals in real-time from RTL-SDR or KiwiSDR stream. Use case: spectrum monitoring, interference identification, SIGINT.

**Dataset:** GNU Radio synthetic signals, public datasets (RML2016.10a), or locally generated via SDG + RTL-SDR recording.

**Model:** 1D CNN on IQ time series or 2D CNN on spectrogram. TensorFlow/PyTorch inference in Python, feeds `rf_bench.rtlsdr` or `rf_bench.kiwisdr` stream.

#### Interference detector

`projects/spectrum/ml-interference/` — 💭 not started.

Learn "normal" spectrum from weeks of RTL-SDR captures. Flag anomalies: harmonics, EMI, new transmitters, spurious. Use case: EMC compliance monitoring, RFI hunting, regulatory enforcement.

**Method:** Autoencoder or isolation forest on power spectrum features. Trains on clean baseline, flags deviations. Alerts via email/SMS when anomaly detected.

#### Propagation predictor

`projects/kiwisdr/ml-propagation/` — 💭 not started.

Logs KiwiSDR beacon S-meters + solar/geomagnetic indices (K/A from NOAA API) for months. Predicts HF band openings 1-24 hours ahead via LSTM or gradient boosted trees. Use case: contest prep, DXpedition planning.

**Dataset:** `projects/kiwisdr/beacon-logger/` output + space weather API. Features: time-of-day, season, sunspot number, K-index, recent S-meter trend.

**Output:** Probability of opening per band, recommended QSY times.

#### Automatic QRM notch

`projects/rtlsdr/ml-notch/` — 💭 not started.

Real-time interferer characterization (bandwidth, center freq, modulation) from RTL-SDR IQ stream. Generates notch filter coefficients, applies via GNU Radio or SciPy. Use case: adaptive filtering for weak signal work.

**Method:** Detect interferer via energy detection, characterize via FFT, compute notch (IIR or FIR), apply to IQ stream. Optional: ML-based interferer type classification to optimize notch shape.

### Future-remote-lab

Meta-system coordinating all instruments and projects. Provides unified interface, automation, and data management across the entire bench.

#### Test sequence engine

`lab-automation/sequence-engine/` — 💭 not started.

YAML-defined workflows that chain projects. Example: "tune antenna → measure MDS → measure TX power → log to database → email report if SWR > 2.0". Handles parameter passing, error recovery, parallel execution where safe.

**Format:**
```yaml
sequence:
  - name: Tune antenna
    script: projects/esp32-combos/auto-tuner-ssa/auto_tuner.py
    args: {freq: 14.2, target_swr: 1.5}
  - name: Measure MDS
    script: projects/radio/receiver-test/receiver_test.py
    args: {freq: 14.2, mode: usb}
    requires: [Tune antenna]
  - name: Log results
    script: lab-automation/logger.py
    args: {table: daily_checks}
```

**Engine:** Python (or Prefect/Airflow if complexity grows). Runs via cron or manual trigger. Stores results in SQLite or PostgreSQL.

#### Web dashboard

`lab-automation/dashboard/` — 💭 not started.

Single-pane-of-glass for all instruments. Flask or FastAPI backend, Vue.js or React frontend. Real-time updates via WebSocket. Panels: spectrum waterfall (RTL-SDR/KiwiSDR/SSA), S-meter, rotator position, SWR, chamber temperature, PSU voltage/current, scope traces.

**Why:** Remote monitoring without SSH/VNC into individual instrument UIs. Mobile-friendly for field operations.

**Integration:** REST APIs to all `rf_bench.*` drivers + ESP32 SCPI controllers. WebSocket pushes for <1s update rates.

#### Measurement database

`lab-automation/timeseries-db/` — 💭 not started.

Centralized time-series storage for all logged data. InfluxDB (time-series optimized) or PostgreSQL with TimescaleDB extension. Grafana dashboards for visualization. Projects write to DB via REST API instead of local CSV.

**Schema:** Measurement name, timestamp, value, unit, tags (instrument, project, frequency, etc.). Retention policy: 1s resolution for 7 days, 1min avg for 1 year, 1hr avg forever.

**Use cases:** Long-term drift tracking, anomaly detection, performance regression testing, scientific data publication.

#### Calibration tracker

`lab-automation/cal-tracker/` — 💭 not started.

Knows when instruments were last calibrated (via manual entry or automatic logging from `projects/rf/calibration/`). Flags drift if cross-checks fail. Schedules re-cal. Generates cal certificates (PDF) per instrument.

**Database:** SQLite or PostgreSQL. Tables: instruments, cal_events, drift_checks.

**Alerts:** Email or Slack when cal due, drift detected, or cross-check fails. Integrates with traceability chain (see [Bench-internal traceability chain](#traceability-chain)).

### Future-contest-field-day

Ham radio contest automation and integration with contest logging software.

#### N1MM+ bridge

`projects/radio/n1mm-bridge/` — 💭 not started.

Reads frequency from N1MM+ (via UDP broadcast or database polling), auto-tunes antenna via `esp32-combos/auto-tuner-ssa/`, logs SWR to N1MM+ contact notes. Use case: seamless QSY without manual tuner adjustment, SWR monitoring during contest.

**Integration:** N1MM+ broadcasts frequency on UDP port 12060. Python listener triggers scpi-tuner when frequency changes. SWR from scpi-swr written back to N1MM+ via TCP port 12060.

**Extension:** Add TX power measurement via `esp32-combos/mds-sweep/` (reverse mode: scpi-atten + SSA measure TX output).

#### Propagation-aware band changes

`projects/kiwisdr/auto-band-change/` — 💭 not started.

KiwiSDR monitors all HF contest bands simultaneously (8-12 channels if multiple KiwiSDRs). Measures band noise + beacon S-meters. Tells N1MM+ or other logger when to QSY via UDP command. Use case: maximize QSO rate by following propagation.

**Algorithm:** Compute "band goodness" = (beacon S-meter - noise floor) × activity level (CQ count from CW Skimmer). Recommend QSY if current band drops below threshold and another band improves.

**Caveat:** Requires multiple KiwiSDRs or time-shared single KiwiSDR (monitor each band for 10s, rotate).

#### Automatic SO2R switching

`projects/radio/so2r/` — 💭 not started.

Coordinates IC-7300 + SunSDR (or 2× IC-7300) for Single Operator Two Radio contesting. Handles antenna routing via `esp32-combos/rf-matrix/`, audio switching, PTT interlocks (no simultaneous TX), and frequency coordination (no same-band operation). Integrates with N1MM+ SO2R mode.

**Why this combination:** IC-7300 (HF run radio) + SunSDR (HF mult radio). rf-matrix routes antennas. Python enforces interlock rules.

**Complex because:** SO2R requires sub-100ms switching, interlock logic, and tight integration with logger. May need dedicated SO2R controller hardware (e.g., Microham or manual footswitch) rather than pure software.

#### Field Day scorer

`projects/radio/field-day-scorer/` — 💭 not started.

Integrates GPS (distance to contacts), antenna patterns (gain toward contact azimuth from `esp32-combos/antenna-array-scanner/`), and QSO log to generate tactical reports. Use case: "best antenna for EU right now", "propagation forecast for next 2 hours", "which bands are dead".

**Why:** Combines spatial (GPS + antenna) and temporal (propagation model) data for informed operating decisions. More sophisticated than simple N1MM+ statistics.

### Future-dut-characterization

Automated production test and hardware-in-the-loop characterization. High-throughput testing via relay/mux switching.

#### RF amplifier production test

`projects/rf/amp-production-test/` — 💭 not started.

`esp32-combos/rf-matrix/` routes 4-8 DUT amplifiers sequentially. SSA3032X measures gain, P1dB, IP3 (with SDG two-tone source). `scpi-relay` bins pass/fail into physical trays. Use case: QC line for homebrew or small-run amplifiers.

**Throughput:** ~30s per DUT (tune + gain sweep + P1dB + IP3) = 120 DUTs/hour.

**Test sequence:** Connect DUT → measure S21 gain vs freq → measure P1dB → measure IP3 → write results to DB → actuate pass/fail relay.

#### Filter QC line

`projects/rf/filter-qc/` — 💭 not started.

16-DUT fixture via `scpi-mux`. Automated S21 sweep per DUT via SSA + SDG. Export Touchstone .s2p files. Statistical binning (pass/fail based on insertion loss, passband ripple, stopband rejection). Use case: crystal filter QC, cavity filter tuning validation.

**Why scpi-mux:** 16 filters measured without manual cable swaps. Mux on-resistance (<5Ω) acceptable for filters with Z0=50Ω and >1dB insertion loss.

**Output:** CSV with per-DUT metrics + Touchstone files + bin assignments (A/B/C grade or pass/fail).

#### Crystal aging chamber

`projects/components/crystal-aging/` — 💭 not started.

`esp32-combos/scpi-heater/` cycles temperature (-40°C to +85°C). `scpi-counter` logs crystal oscillator frequency vs temp/time (weeks or months). Use case: TCXO aging characterization, OCXO warm-up time, crystal pulling range vs temp.

**Why this combination:** PID temp control + frequency counter + long-term logging (SQLite). Detects aging (ppm/year), tempco (ppm/°C), and hysteresis.

**Chamber:** DIY insulated box with heater/fan, DS18B20 sensors, crystal oscillator under test powered inside chamber.

#### Battery formation/QC

`projects/power/battery-formation/` — 💭 not started.

Multi-cell formation and QC via `esp32-combos/battery-discharge/` + `esp32-combos/battery-charger/` + `scpi-mux` (16 cells in parallel). Automated charge/discharge cycles, capacity binning, IR matching. Use case: lithium cell QC for pack building, lead-acid desulfation, NiMH break-in.

**Why scpi-mux:** Test 16 cells in parallel with per-cell voltage sensing and per-cell temp monitoring (scpi-temp). `scpi-relay` power-gates cells to prevent thermal runaway propagation.

**Safety:** Requires per-cell fusing, over-temp cutoff, and fireproof enclosure. Not a beginner project.

### Future-propagation-science

Serious ionospheric/tropospheric monitoring for scientific publication or advanced ham radio use.

#### Multipath fading logger

`projects/kiwisdr/multipath-fading/` — 💭 not started.

KiwiSDR monitors known HF beacons (e.g., NCDXF/IARU). Logs selective fading (frequency-dependent S-meter variation). Generates delay-Doppler plots (delay vs Doppler shift). Use case: ionospheric research, propagation mode identification (F2, Es, TEP).

**Method:** Receive beacon CW signal, FFT to extract Doppler shifts, correlate delays. Requires GPS-disciplined KiwiSDR for frequency/time accuracy.

**Output:** 2D plot (delay vs Doppler), identifies single-hop vs multi-hop, auroral vs TEP propagation.

#### Ionospheric sounder

`projects/rf/ionosonde/` — 💭 not started.

SDG1062X generates chirp (1-30 MHz over 100ms). RTL-SDR RX captures reflections. Plot ionogram (frequency vs time-of-flight → virtual height). Use case: real-time MUF estimation, ionospheric layer identification (E, F1, F2).

**Why this combination:** SDG chirp source (arbitrary waveform), RTL-SDR captures echo, Python correlates TX/RX for time-of-flight.

**License requirement:** Experimental or Part 5 operation (very low power, <100mW). High-power ionosondes require coordination.

**Limitation:** Backscatter ionosonde (monostatic) limited to ~500km range. Oblique sounding (bistatic with remote RX) extends range but needs second station.

#### Tropospheric ducting detector

`projects/rf/tropo-ducting/` — 💭 not started.

`scpi-relay` switches between 4 antennas at different heights (e.g., 1m, 3m, 10m, 30m). RTL-SDR measures VHF/UHF beacon signal strength at each height. Computes refractive index gradient (dn/dh). Use case: predict ducting conditions for 2m/70cm DX.

**Method:** Refractivity depends on temperature, pressure, humidity (all measurable via `scpi-temp` + barometer + hygrometer). Height-dependent signal strength maps to refractive index profile. Negative gradient → ducting.

**Beacon:** Distant VHF FM broadcast, NOAA weather radio, or coordinated amateur beacon.

#### Meteor scatter event counter

`projects/rtlsdr/meteor-scatter/` — 💭 not started.

RTL-SDR monitors 6m beacon (50 MHz). Detects meteor reflections (sudden signal bursts 0.1-10s duration). Logs event time, duration, peak strength. Use case: meteor shower analysis, meteor scatter scheduling for QSOs.

**Method:** Energy detection on beacon frequency. Threshold crossing → event. Correlate with known meteor showers (Perseids, Geminids) to validate detection.

**Beacon:** NCDXF 50 MHz or coordinated 6m beacon. Requires quiet 6m band (no local QRM).

---

<a name="future-virtual-instruments"></a>
### Future-virtual-instruments

Virtual SCPI instruments with web and Android interfaces. Built using a universal instrument panel builder framework where users assemble custom control panels from reusable widgets.

**Architecture:** Python backend exposes SCPI TCP server (port 5025) + HTTP/WebSocket server (port 8000/8001) + MQTT bridge. Web UI (React/Vue) and Android app (Kotlin/Jetpack Compose) render panels dynamically from JSON/YAML config files. Widgets subscribe to MQTT topics or poll SCPI commands for real-time updates.

**Development phases:**
1. **Phase 1:** Read-only monitoring widgets (analog meter, bar graph, LED, numeric display, line chart, XY plot, text LCD, waterfall, compass, gauge cluster). Web-only, SCPI polling only. Hand-edited JSON configs.
2. **Phase 2:** Bidirectional controls (toggle, button, knob, slider, text input). MQTT pub/sub integration.
3. **Phase 3:** SCPI→MQTT bridge (existing bench instruments publish to MQTT topics, widgets subscribe).
4. **Phase 4:** Drag-and-drop web-based config builder (like Grafana editor).
5. **Phase 5:** Android app with same widget library and config format.

**Widget library (Phase 1 — 10 display-only widgets):**

#### Analog Meter (virtual-analog-meter)

`virtual/analog-meter/` — 🔨 built to documentation, untested.

**Visual:** Round gauge with needle, configurable colored zones (green/yellow/red).

**Config:** `min`, `max`, `units`, `zones` (thresholds), `needle_color`.

**Binding:** SCPI command (backend polls) or MQTT topic (subscribe).

**Use cases:** S-meter, SWR, voltage, current, temperature, azimuth/elevation.

**Example config:**
```yaml
type: analog_meter
label: "S-Meter"
binding:
  scpi: {host: "10.1.1.60", port: 5025, command: ":CALC:MARK1:Y?"}
  interval: 200ms
config:
  min: -120
  max: -30
  units: "dBm"
  zones:
    - {max: -90, color: red}
    - {max: -60, color: yellow}
    - {max: -30, color: green}
```

---

#### Bar Graph (virtual-bar-graph)

`virtual/bar-graph/` — 💭 not started.

**Visual:** Horizontal or vertical filled bar with optional gradient, threshold lines.

**Config:** `min`, `max`, `orientation` (horizontal/vertical), `color`, `thresholds`.

**Binding:** SCPI or MQTT.

**Use cases:** Signal strength, battery charge, power output, memory usage.

**Example:** Battery voltage 0–15V, green <12V, yellow 12–14V, red >14V.

---

#### LED Indicator (virtual-led)

`virtual/led/` — 🔨 built to documentation, untested.

**Visual:** Single circular LED, configurable on/off colors, optional blink.

**Config:** `on_color`, `off_color`, `blink_rate` (optional).

**Binding:** SCPI boolean (parse as 0/1) or MQTT boolean topic.

**Use cases:** PTT active, relay state, alarm condition, instrument ready, GPS lock.

**Example:** `bench/esp32/ptt/state` → red when transmitting, gray when idle.

---

#### Numeric Display (virtual-numeric-display)

`virtual/numeric-display/` — 🔨 built to documentation, untested.

**Visual:** 7-segment LCD style or plain text digits, large font.

**Config:** `precision` (decimal places), `units`, `font_size`, `color`.

**Binding:** SCPI or MQTT.

**Use cases:** Frequency readout, voltage, distance, GPS altitude, counter.

**Example:** IC-7300 frequency in MHz with 3 decimal places (14.257 MHz).

---

#### Line Chart (virtual-line-chart)

`virtual/line-chart/` — 💭 not started.

**Visual:** Scrolling time-series graph, multiple traces supported, auto-scaling Y axis.

**Config:** `history_seconds`, `y_min`, `y_max`, `traces` (list of bindings with colors).

**Binding:** Multiple SCPI commands or MQTT topics (one per trace).

**Use cases:** Voltage vs time, S-meter trends, temperature logging, power consumption.

**Example:** 60-second S-meter history with green trace, auto-scroll.

---

#### XY Plot (virtual-xy-plot)

`virtual/xy-plot/` — 💭 not started.

**Visual:** Scatter or line plot, X and Y from separate sources, real-time updating.

**Config:** `x_min`, `x_max`, `y_min`, `y_max`, `x_binding`, `y_binding`.

**Binding:** Two SCPI commands or MQTT topics (X and Y independent).

**Use cases:** I-V curves, constellation diagrams, antenna patterns, Lissajous figures.

**Example:** Diode I-V curve: X = voltage (SDM), Y = current (SDM), sweep via SPD.

---

#### Text LCD (virtual-text-lcd)

`virtual/text-lcd/` — 💭 not started.

**Visual:** Monospace text display (16×2 character LCD emulation or larger).

**Config:** `rows`, `cols`, `font`, `scroll_mode` (wrap, scroll, truncate).

**Binding:** SCPI query (string) or MQTT topic (string payload).

**Use cases:** GPS NMEA sentences, instrument status messages, log tail, terminal output.

**Example:** 4-line LCD showing GPS fix status, lat/lon, altitude, speed.

---

#### Waterfall Display (virtual-waterfall)

`virtual/waterfall/` — 💭 not started.

**Visual:** Time vs frequency/parameter heatmap, vertical scrolling, configurable colormap.

**Config:** `width_bins`, `history_rows`, `color_map` (viridis, plasma, jet), `z_min`, `z_max`.

**Binding:** SCPI trace query (array) or MQTT topic (array payload).

**Use cases:** Spectrum analyzer waterfall, RTL-SDR, temperature profile over time, audio spectrogram.

**Example:** SSA spectrum trace (801 points) scrolling down at 10 FPS.

---

#### Compass (virtual-compass)

`virtual/compass/` — 💭 not started.

**Visual:** Circular compass rose with needle and cardinal labels (N/S/E/W).

**Config:** `cardinal_labels` (bool), `needle_color`.

**Binding:** SCPI or MQTT (degrees, 0–360).

**Use cases:** Antenna rotator azimuth, GPS heading, wind direction, satellite azimuth.

**Example:** Rotator azimuth from `bench/esp32/rotator/azimuth`, red needle.

---

#### Gauge Cluster (virtual-gauge-cluster)

`virtual/gauge-cluster/` — 💭 not started.

**Visual:** Multiple small gauges in a grid (car dashboard style).

**Config:** Array of sub-gauges, each with own binding, range, label, color.

**Binding:** Multiple SCPI commands or MQTT topics (one per gauge).

**Use cases:** PSU voltage+current+power in one widget, GPS speed+alt+heading, multi-channel monitor.

**Example:** SPD3303X CH1 showing 13.8V / 2.1A / 29W in three small gauges.

---

#### Multi-instrument panels (Phase 1 compound ideas)

Once the 10 base widgets are built, users can compose them into full instrument clusters via JSON/YAML config. Examples:

##### HF Station Monitor

`virtual/panels/hf-station/` — 💭 not started.

**Widgets:** Analog meter (S-meter), numeric display (frequency), LED (PTT), line chart (S-meter history 60s), bar graph (SWR).

**Bindings:** IC-7300 via Hamlib rigctld SCPI bridge, ESP32 scpi-swr, ESP32 scpi-ptt.

**Layout:** 3×3 grid, S-meter top-left, frequency top-center, PTT LED top-right, line chart middle (full width), SWR bottom-left.

---

##### VHF/UHF Satellite Tracker

`virtual/panels/satellite-tracker/` — 💭 not started.

**Widgets:** Compass (azimuth), analog meter (elevation 0–90°), numeric display (Doppler shift Hz), line chart (signal strength), text LCD (pass info: AOS/LOS/max el).

**Bindings:** ESP32 scpi-rotator (az/el), IC-9700 Doppler offset via rigctld, IC-9700 S-meter, Python pass predictor publishing to MQTT.

**Layout:** 2×3 grid, compass left, elevation meter center, Doppler right, S-meter chart bottom-left span 2, text LCD bottom-right.

---

##### Battery Characterization Lab

`virtual/panels/battery-lab/` — 💭 not started.

**Widgets:** Gauge cluster (voltage, current, power), line chart (V/I/T vs time), numeric display (capacity mAh), bar graph (state of charge %), LED (charge complete).

**Bindings:** ESP32 scpi-adc (voltage), ESP32 scpi-power (INA219 current), ESP32 scpi-temp (battery temp), Python script integrating capacity.

**Layout:** Gauge cluster top-left, line chart top-right span 2 rows, numeric display (capacity) middle-left, bar graph (SOC) bottom, LED bottom-right.

---

##### Spectrum Monitor Wall

`virtual/panels/spectrum-wall/` — 💭 not started.

**Widgets:** 4× waterfall displays (one per band: 20m, 15m, 10m, 6m).

**Bindings:** 4× KiwiSDR channels via WebSocket → MQTT bridge, or RTL-SDR time-shared scanning.

**Layout:** 2×2 grid, each waterfall full-size, labels top of each (20m / 15m / 10m / 6m).

---

##### RF Test Bench Dashboard

`virtual/panels/rf-test-bench/` — 💭 not started.

**Widgets:** Numeric display (frequency), analog meter (output power dBm), bar graph (harmonic distortion dBc), line chart (sweep trace), XY plot (AM/PM distortion).

**Bindings:** SSA marker freq/level, SDG output freq, harmonic measurement script, sweep data logger.

**Layout:** Numeric display top-left, power meter top-center, harmonic bar top-right, line chart middle full-width, XY plot bottom full-width.

---

#### Phase 2 widgets (bidirectional controls — future)

##### Toggle Switch (virtual-toggle)

`virtual/toggle/` — 💭 not started.

**Visual:** SPDT-style toggle, on/off states with color change.

**Config:** `on_label`, `off_label`, `on_color`, `off_color`.

**Binding:** SCPI write command or MQTT publish. Read-after-write confirmation.

**Use cases:** PSU output enable, relay control, PTT override, heater on/off.

---

##### Push Button (virtual-button)

`virtual/button/` — 💭 not started.

**Visual:** Momentary button, press animation.

**Config:** `label`, `color`, `hold_duration` (optional for long-press actions).

**Binding:** SCPI command or MQTT publish on press. Optional hold command.

**Use cases:** SSA sweep trigger, SDG burst trigger, antenna tuner auto-tune, reset counter.

---

##### Rotary Knob (virtual-knob)

`virtual/knob/` — 💭 not started.

**Visual:** Continuous or stepped rotary knob with numeric readout.

**Config:** `min`, `max`, `step`, `units`, `log_scale` (bool).

**Binding:** SCPI write + read-back, or MQTT publish + subscribe for confirmation.

**Use cases:** Frequency tuning, volume control, attenuation setting, gain adjust.

---

##### Slider (virtual-slider)

`virtual/slider/` — 💭 not started.

**Visual:** Horizontal or vertical slider with live value display.

**Config:** `min`, `max`, `step`, `orientation`, `log_scale` (bool).

**Binding:** SCPI write + read-back, or MQTT publish + subscribe.

**Use cases:** PSU voltage setpoint, SDG amplitude, scope timebase, filter bandwidth.

---

##### Text Input (virtual-text-input)

`virtual/text-input/` — 💭 not started.

**Visual:** Single-line text box with submit button.

**Config:** `placeholder`, `validation_regex` (optional).

**Binding:** SCPI arbitrary command or MQTT publish on submit.

**Use cases:** Send raw SCPI commands for debugging, set arbitrary frequency, input callsign.

---

#### Supporting infrastructure (drivers, backend, configs)

##### Virtual instrument driver

`drivers/virtual/` — 💭 not started.

**Package:** `rf_bench.virtual` (if needed as a library).

**Purpose:** Common Python backend code for all virtual instruments. SCPI server base class, MQTT client wrapper, WebSocket handler, config parser (JSON/YAML), widget state manager.

**Alternatively:** Each virtual instrument is self-contained (FastAPI app + React frontend) in `virtual/<name>/`, no shared driver package. Decide based on code duplication after building 2-3 examples.

---

##### SCPI→MQTT bridge

`virtual/scpi-bridge/` — 💭 not started (Phase 3).

**Purpose:** Polls SCPI commands from existing bench instruments (SSA, SDG, IC-7300 via rigctld, etc.) at configured intervals, publishes results to MQTT topics. Widgets subscribe to MQTT, don't care if data came from SCPI or native MQTT instrument.

**Config format:** YAML mapping SCPI commands to MQTT topics with interval, parse type, scaling.

**Example:**
```yaml
instruments:
  ssa3032x:
    host: 10.1.1.60
    port: 5025
    mappings:
      - scpi: ":CALC:MARK1:X?"
        mqtt: "bench/ssa/marker1_freq"
        interval: 500ms
        parse: float
        scale: 1e-6  # Hz → MHz
```

**Deliverable:** Python daemon, systemd service, example configs for SSA/SDG/SDM/SPD/IC-7300.

---

##### Panel config examples

`virtual/configs/` — 💭 not started.

**Purpose:** Example panel YAML files for common use cases. Users copy, edit, load into workbench UI.

**Examples:**
- `hf-station.yaml` — IC-7300 S-meter, frequency, SWR, PTT
- `vhf-monitor.yaml` — IC-9700 satellite tracking with az/el compass
- `battery-lab.yaml` — Multi-cell discharge test with V/I/T/capacity
- `spectrum-wall.yaml` — 4× KiwiSDR waterfall displays
- `rf-test-bench.yaml` — SSA/SDG/scope for amplifier characterization

**Schema:** JSON Schema or YAML schema for validation (optional but recommended for Phase 4 GUI builder).

---

##### Web UI framework

`virtual/workbench-ui/` — 💭 not started.

**Tech stack:** React or Vue 3, TailwindCSS, Plotly.js or Chart.js, mqtt.js (WebSocket MQTT client).

**Features:**
- Load panel config (JSON/YAML) from URL parameter or file upload
- Render widgets dynamically based on config
- Subscribe to MQTT topics or poll backend WebSocket
- Responsive layout (desktop, tablet, mobile)

**Deliverable:** Single-page app, `npm run build` → static files served by Python backend.

---

##### Android app

`virtual/workbench-android/` — 💭 not started (Phase 5).

**Tech stack:** Kotlin, Jetpack Compose, Eclipse Paho MQTT client, MPAndroidChart or Vico.

**Features:**
- Load panel config from JSON/YAML (file picker or URL)
- Native widget rendering (same visual style as web)
- Direct MQTT connection (efficient, low latency)
- Offline mode (last known values cached)
- Notifications (threshold alerts, instrument errors)

**Deliverable:** APK for sideloading, eventual Google Play release.

---

**Development priority (Phase 1, starting now):**
1. Build 2-3 simple display widgets (analog meter, numeric display, LED) as standalone web apps
2. Prove SCPI polling backend + React frontend architecture
3. Add JSON config loading (single-widget panels first)
4. Expand to 10-widget library
5. Build first compound panel (HF Station Monitor with 5 widgets in grid layout)

**Directory structure:**
```
virtual/
├── analog-meter/          # Phase 1 — first widget
│   ├── backend.py         # FastAPI SCPI server + HTTP/WebSocket
│   ├── frontend/          # React app
│   │   ├── src/
│   │   │   └── AnalogMeter.tsx
│   │   └── package.json
│   ├── config.example.yaml
│   └── README.md
├── numeric-display/       # Phase 1
├── led/                   # Phase 1
├── bar-graph/             # Phase 1
├── line-chart/            # Phase 1
├── ...                    # Remaining 5 Phase 1 widgets
├── workbench-ui/          # Phase 1 — unified multi-widget panel renderer
│   ├── backend.py
│   ├── frontend/
│   └── configs/           # Example panel YAML files
├── scpi-bridge/           # Phase 3
└── workbench-android/     # Phase 5
```

**See also:** `~/Dropbox/build/rf-bench/workbench.md` for full architecture documentation, widget API specs, MQTT vs SCPI tradeoffs, and phased development plan.

---

