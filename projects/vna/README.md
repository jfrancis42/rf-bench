# VNA Projects

Vector-network-analyzer measurement projects. Scripts here target the
**swappable VNA API** shared by:

- `rf_bench.nanovna.NanoVNA` — NanoVNA-F (Deepelec) / -H / -H4 via USB CDC; **working today**
- `rf_bench.hp.HP8712B` — HP 8712B via KISS-488 Ethernet-GPIB; hardware pending

Pick the backend at runtime with the script's `--vna {nanovna,hp}` flag.

## Project status

| Project | Status | Notes |
|---------|--------|-------|
| [`swr-pdf/`](swr-pdf/) | ✅ | S11 → VSWR-vs-frequency single-page PDF. Tested 2026-06-30 against NanoVNA-F on 2 m, 70 cm, 3–30 MHz. |
| [`smith-pdf/`](smith-pdf/) | ✅ | S11 → Smith-chart single-page PDF. Tested 2026-06-30 against NanoVNA-F on 70 cm, 23 cm, and HF. |
| [`return-loss-pdf/`](return-loss-pdf/) | 🧪 | S11 → return-loss-dB PDF with equivalent-VSWR axis. |
| [`cable-loss-pdf/`](cable-loss-pdf/) | 🧪 | S21 THRU → cable insertion-loss PDF; optional dB/100ft panel with manufacturer overlay. |
| [`filter-pdf/`](filter-pdf/) | 🧪 | S21 → filter response with auto-detected -3/-6/-20/-40/-60 dB bandwidths, ripple, shape factor, stopband floor. **Optional `--phase` and `--group-delay` panels.** |
| [`group-delay-pdf/`](group-delay-pdf/) | 🧪 | Standalone S21 group-delay tool for amplifiers / cables / matching networks (\|S21\| + ∠S21 + τ_g panels). |
| [`impedance-pdf/`](impedance-pdf/) | 🧪 | Full one-port diagnostic: R + jX, \|Z\| + phase, VSWR, Smith locus, optional X=0 resonance hunter. **Supersedes** legacy `antenna/` and `impedance/`. |
| [`tline-pdf/`](tline-pdf/) | 🧪 | Transmission-line characterisation: VF, loss/m, and (with `--method osl-s11`) Z₀(f). Supersedes legacy `tline/`. |
| [`sparams-pdf/`](sparams-pdf/) | 🧪 | Full 2-port S-parameters PDF + Touchstone .s2p export. NanoVNA via DUT-reversal; HP 8712B native. Supersedes legacy `sparams/`. |
| [`choke-pdf/`](choke-pdf/) | 🧪 | CM-choke series-through |Z| / R / X PDF (DX-Engineering / K6JCA method). |
| [`resonance-finder/`](resonance-finder/) | 🧪 | Auto-find S11 dips, fit -3 dB BW, report loaded Q. PDF + CSV. |
| [`balun-pdf/`](balun-pdf/) | 🧪 | Two-pass balun characterisation: RL + insertion loss + amplitude/phase balance. |
| [`connector-check/`](connector-check/) | 🧪 | Per-amateur-band PASS/FAIL return-loss check; PDF + JSON; non-zero exit on FAIL. |
| [`toroid-sniff/`](toroid-sniff/) | 🧪 | Wound-toroid L, Al, Q vs frequency + mix-consistency hint. |
| [`tdr-pdf/`](tdr-pdf/) | 🧪 | Host-side IFFT TDR (step + impulse) with cable-VF presets and fault auto-classification. **Time gating via `--gate-start-m` / `--gate-end-m`**: isolate one reflection in time, FFT back to get its frequency response. |
| [`de-embed-pdf/`](de-embed-pdf/) | 🧪 | Pure post-processor: `measurement.s2p` + `fixture.s2p` → DUT-alone `.s2p` + before/after PDF. S↔T matrix algebra; symmetric or asymmetric fixture topology. |
| [`mixed-mode-pdf/`](mixed-mode-pdf/) | 🧪 | 4-port single-ended `.s4p` → mixed-mode S-params (Sdd, Scc, Sdc, Scd) PDF + .s4p output. Standard Bockelman / Eisenstadt mode transform. |
| [`crystal-bvd-pdf/`](crystal-bvd-pdf/) | 🧪 | Live VNA capture (or `.s2p` input) → Butterworth-Van Dyke parameter extraction (Lm, Cm, Rm, C0, Qm) with iterative C0 refinement; PDF + SPICE `.sub` subcircuit. |
| [`vector-fit-spice/`](vector-fit-spice/) | 🧪 | Gustavsen Vector Fitting → SPICE-paste-ready behavioural Laplace subcircuit. LTspice or ngspice flavor. Drops measured S-params into any simulator. |
| [`tdt-pdf/`](tdt-pdf/) | 🧪 | S21 IFFT → time-domain transmission. Finds lumped reflections INSIDE a 2-port DUT (bond-wire mismatches, internal element parasitics). |
| [`bandpass-tdr-pdf/`](bandpass-tdr-pdf/) | 🧪 | Bandpass-mode TDR via analytic-signal IFFT — for sweeps that don't include DC (UHF-only, HPF-limited DUTs). |
| [`renormalize-pdf/`](renormalize-pdf/) | 🧪 | Re-reference a .s2p from one Z₀ to another (50→75 Ω for CATV, 50→100 Ω for differential, 50→600 Ω for ladder line). |
| [`rlgc-pul-pdf/`](rlgc-pul-pdf/) | 🧪 | Distributed-line per-unit-length R, L, G, C from S-params of two cable lengths + open/short. Companion to `tline-pdf` for full SPICE models. |
| [`kramers-kronig-pdf/`](kramers-kronig-pdf/) | 🧪 | Causality check: Re/Im of a causal response are Hilbert transforms. Quantifies residual; useful for SOLT cal quality validation. |
| [`q-cross-check/`](q-cross-check/) | 🧪 | Three independent Q methods (3 dB BW, Lorentzian fit, Smith circle) compared side-by-side; quantifies measurement uncertainty. |
| [`cepstral-pdf/`](cepstral-pdf/) | 🧪 | Cepstral analysis of S11: separates discrete cable reflections (sharp cepstral peaks) from distributed losses (smooth baseline). |
| [`multi-segment-sweep/`](multi-segment-sweep/) | 🧪 | Stitch many narrow NanoVNA sweeps into one wide-band Touchstone .s2p + PDF. Past the 401-point limit. |
| [`stability-logger/`](stability-logger/) | 🧪 | Cron-friendly: appends one S11 capture's headline metrics to a CSV; tracks calibration / antenna drift over days–months. Optional `--alert-mag` for exit-code threshold. |
| [`filter-tuning/`](filter-tuning/) | 🧪 | Live matplotlib window: continuously sweeps S21 against an optional target mask. For hand-tuning crystal / cavity / LC filters. |
| [`wheeler-cap-pdf/`](wheeler-cap-pdf/) | 🧪 | Antenna radiation efficiency η = 1 − Q_free/Q_cap from two S11 captures (free-space and inside a Wheeler cap). |
| [`field-antenna/`](field-antenna/) | 🧪 | Minimal at-the-antenna capture: one CLI flag → .s1p + PDF with UTC-timestamped filenames. |
| [`de-embed-fixture/`](de-embed-fixture/) | 🧪 | Wrapper around `sparams-pdf` that captures a fixture-alone .s2p (DUT replaced by THRU) ready for `de-embed-pdf`. |
| [`quartz-q/`](quartz-q/) | 🧪 | S21-only crystal Q (3 dB BW method); faster than the full BVD fit for batch sorting. |
| [`screen-export/`](screen-export/) | 🧪 | NanoVNA LCD framebuffer (`capture` shell command) → PNG. **Untested: firmware-dependent.** |
| [`ook-power-detector/`](ook-power-detector/) | 🧪 | Fix the VNA to one frequency and sample S21 repeatedly; CSV log + optional envelope-vs-time PDF. |
| [`portable-rf-survey/`](portable-rf-survey/) | 🧪 | Batch-survey many DUTs from a JSON config; one PDF per DUT + HTML index. |
| [`wideband-rl-browser/`](wideband-rl-browser/) | 🧪 | Multi-segment full-range S11 → interactive Plotly HTML (static SVG fallback). |
| [`antenna-pattern/`](antenna-pattern/) | 🧪 | Polar pattern via VNA + SCPI-rotator; CSV + polar PDF. **Untested.** |
| [`vs-ssa-cross-check/`](vs-ssa-cross-check/) | 🧪 | Build NanoVNA S21 → absolute-dBm offset table using SSA as reference. **Untested.** |
| [`flipper-subghz-match/`](flipper-subghz-match/) | 🧪 | S11 of the Flipper Zero's external Sub-GHz antenna across all 3 ISM bands. |
| [`amplifier-curve/`](amplifier-curve/) | 🧪 | S-params vs DC bias contour using SPD3303X-E. **Untested.** |
| [`antenna-factor-pdf/`](antenna-factor-pdf/) | 🧪 | Antenna factor AF (dB/m) derivation from S11 + datasheet gain. **Untested.** |
| [`atten-cal/`](atten-cal/) | 🧪 | Per-code, per-frequency calibration of a digital step attenuator → JSON table. |
| [`coupler-power-meter/`](coupler-power-meter/) | 🧪 | Absolute-dBm offset via directional coupler + SSA xref. **Untested.** |
| [`nec-verify/`](nec-verify/) | 🧪 | Overlay measured S11 vs 4nec2 simulation; diagnose model error. **Untested.** |
| [`mode-decomp-pdf/`](mode-decomp-pdf/) | 🧪 | Spatial-FFT mode decomposition of S-params (overmoded waveguide). **Niche.** |
| [`freq-comb-sweep/`](freq-comb-sweep/) | 🧪 | S21 capture at a discrete frequency list (WSPR/FT8 spots, harmonic-mixer tones). |
| [`sparams-4port-from-2port/`](sparams-4port-from-2port/) | 🧪 | Stitch six 2-port captures into a single 4-port .s4p (with diagonal averaging). |
| [`antenna/`](antenna/) | 🧪 *(legacy, superseded)* | Full feed-point impedance: VSWR + R+X + Smith. Superseded by [`impedance-pdf/`](impedance-pdf/). Kept only for historical reference. |
| `filter/` | ❌ *(legacy, superseded)* | Older HP-only filter-sweep stub. Use [`filter-pdf/`](filter-pdf/) (with optional `--phase` / `--group-delay`). |
| `group-delay/` | ❌ *(legacy, superseded)* | Use [`group-delay-pdf/`](group-delay-pdf/) (standalone) or [`filter-pdf/ --group-delay`](filter-pdf/). |
| `impedance/` | ❌ *(legacy, superseded)* | Use [`impedance-pdf/`](impedance-pdf/). |
| `sparams/` | ❌ *(legacy, superseded)* | Use [`sparams-pdf/`](sparams-pdf/) (handles the NanoVNA DUT-reversal trick automatically). |
| `tline/` | ❌ *(legacy, superseded)* | Use [`tline-pdf/`](tline-pdf/). |
| `transistor/` | ❌ | RF transistor S-parameter extraction. Still HP-only — the DUT-reversal trick is impractical for bias-swept measurements. |

Status legend: ✅ tested · 🧪 limited testing · ❌ not yet run against hardware.

## Quick start (NanoVNA-F)

```bash
# 2m HT antenna VSWR sweep
python projects/vna/swr-pdf/swr_pdf.py \
    --start 144 --stop 148 --label "2m HT antenna" --output 2m.pdf

# HF antenna VSWR sweep (3–30 MHz)
python projects/vna/swr-pdf/swr_pdf.py \
    --start 3 --stop 30 --label "HF antenna" --output hf.pdf
```

See [`drivers/nanovna/README.md`](../../drivers/nanovna/README.md) for the
SOLT calibration walkthrough — antenna VSWR results are only as good as
the calibration that's loaded.
