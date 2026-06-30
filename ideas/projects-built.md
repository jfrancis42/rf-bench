## Built projects — by domain

Projects implementations live under `projects/<domain>/<name>/`. Each has its
own README.md. This section is a one-line-each index — see the per-project
README for invocation, options, output formats.

### Driver self-tests

- **drivers/siglent/test_*.py** — bring-up smoke tests for SDG, SDS, SSA,
  SDM, SPD. Run after firmware updates.
- **drivers/koolertron/test_koolertron.py** — 9-test validation sweep,
  passes against MHS-5225A 2026-06-08.

### projects/rf

| Project | Status | Hardware | Notes |
|---------|--------|----------|-------|
| `antenna-analyzer/` | ✅ | SSA + RB3X25 | Sweeps VSWR across HF/VHF/UHF; adaptive RBW; 751-point trace forced (SSA firmware ignores POIN). |
| `balun-analyzer/` | ✅ | SSA + RB3X25 | Choking impedance vs frequency; log-scale \|Z\|. |
| `calibration/` | ✅ | SDG + scope + SSA + DMM | Cross-instrument amplitude calibration. Exposes the unresolved 1.5× scope-vs-SDG amplitude factor. |
| `crystal-extractor/` | ✅ | SDG + scope (or scope AWG) | BVD parameters Rs/Ls/Cs/Cp via series-resonance sweep + curve fit; batch-sort mode. |
| `iv-tracer/` | ✅ | SPD + SDM | Diode / Zener / LED / BJT / FET I-V curves; family-of-curves with both PSU channels. |
| `matching-network/` | ✅ | SDG + scope (or rf-impedance chain) | L / π / T network synthesis from measured Z; Smith chart; optional verification mode. |
| `mixer-characterizer/` | ✅ | SDG (×2 channel) + SSA | Conversion loss, port isolation, IMD, 1 dB compression. |
| `rf-amplifier/` | ✅ | SDG + SSA + resistive combiner | Gain vs frequency, 1 dB compression, two-tone IP3. |
| `rf-impedance/` | ✅ | SDG + scope (series injection) | Complex Z(f) from 100 kHz–60 MHz; phase via two-channel FFT. |
| `rf-switch/` | ✅ | Bus Pirate + SSA | Insertion loss + isolation per state; Bus Pirate programs the switch IC. |
| `scalar-vna/` | ✅ | SSA + RB3X25 | Two-port S11 + S21 scalar network analysis; same RB3X25 fixture as antenna analyzer. |
| `tdr/` | ✅ | SDG + scope + SMA T | Time-domain reflectometer; ~17 cm fault-distance resolution at SDG edge speed. |

### projects/radio

| Project | Status | Hardware | Notes |
|---------|--------|----------|-------|
| `aprs-igate/` | 🧪 | IC-9700 USB audio + direwolf | APRS igate with optional APRS-IS gating; SQLite log. |
| `audio-chain/` (in `projects/audio/`) | ✅ | SDG + IC-7300 USB audio | TX audio frequency response, ALC compression curve, THD, IF filter shape. |
| `beacon-logger/` | 🧪 | IC-9700 + optional GPS | VHF/UHF beacon S-meter logger; SQLite + HTTP. |
| `coverage/` | ✅ | IC-7300 / IC-9700 / FT-891 + GPS | S-meter vs GPS position; CSV + GPX. |
| `doppler/` | ✅ | any radio + GPS | Real-time Doppler VFO correction from GPS speed/heading. |
| `dstar-monitor/` | 🧪 | IC-9700 | D-STAR activity logger via Hamlib CAT. |
| `fm-deviation/` | ✅ | IC-9700 + SSA | FM deviation via Carson's rule on the spectrum trace (since the SSA firmware lacks FM-demod SCPI). |
| `noise-figure/` | ✅ | IC-7300 / FT-891 + SSA + noise source | Y-factor NF measurement. |
| `phase-noise/` | ✅ | SDG / radio + SSA zero-span | L(f) dBc/Hz vs offset. |
| `receiver-test/` | ✅ | radio + SDG + 110 dB attenuator chain + scope | MDS, NF, S-meter calibration, IMD/IP3, blocking, selectivity. |
| `rx-crosscheck/` | 🧪 | IC-9700 + RTL-SDR | Cross-cal RTL-SDR dBFS → IC-9700 dBm; output is `~/.rtlsdr_vhf_cal.json`. |
| `satellite/` | ✅ | IC-9700 + optional GPS | Pass planner + live Doppler tracker; TLE from AMSAT and SatNOGS. Note: Celestrak `/pub/TLE/` returns 403; use AMSAT + SatNOGS. |
| `transmitter-test/` | ✅ | radio + SSA + 30 dB pad | Power vs freq, harmonics (FCC Part 97 mask), ALC, carrier suppression, two-tone IMD. |
| `vhf-receiver-test/` | 🧪 | IC-9700 + SSA TG | VHF/UHF MDS, S-meter cal, NF on 2 m / 70 cm / 23 cm. |
| `vhf-tx-test/` | 🧪 | IC-9700 + SSA | VHF TX power + harmonics. |

### projects/gps

| Project | Status | Notes |
|---------|--------|-------|
| `freq-cal/` | ✅ | GPS-timestamped frequency drift measurement with SSA. |
| `gridsquare/` | ✅ | Live Maidenhead locator + waypoint distance/bearing. |
| `monitor/` | ✅ | Fullscreen GPS status: DOP bars, scatter, speed, heading. |
| `survey/` | ✅ | Static fix precision survey: mean lat/lon, N/E scatter in metres. |

GPS is wired into many other domains via the `--gps` flag — see
[future ideas](#future-cross-cutting) for the open ends.

### projects/signal-sources

| Project | Status | Hardware | Notes |
|---------|--------|----------|-------|
| `dds-characterizer/` | ✅ | Bus Pirate + AD9833/AD9851/AD9850 + SSA | SFDR maps, harmonics, sinc rolloff, tuning-word sweet spots. |
| `dig-atten-cal/` | ✅ | Bus Pirate + PE43602/HMC307/RFSA3013 + SSA | Per-code, per-frequency correction table → JSON for downstream projects. |
| `koolertron-cal/` | ✅ | MHS-5225A + scope | One-shot validation sweep; tested 2026-06-08. |
| `osc-stability/` | ✅ | SSA / scope counter | Allan deviation σ_y(τ); identifies white/flicker/random-walk regimes. |
| `osc-tc/` | ✅ | Bus Pirate + I2C temp sensor + SSA | Frequency vs temperature, polynomial fit, hysteresis quantification. |
| `sdg-cal/` | ✅ | SDG + SSA | SDG self-characterization: flatness, harmonics, P1dB, two-channel tracking. Output is a correction table. |
| `si5351-gen/` | ✅ | Bus Pirate + Si5351 breakout | Curses TUI + CLI; Tkinter panel alternative; preset save/load; SSA measurement integration. |
| `synthesizer-characterizer/` | ✅ | Bus Pirate + Si5351 / ADF4351 + SSA | Frequency accuracy ppm, harmonics, frac-N spurs. |

### projects/scope

| Project | Status | Hardware | Notes |
|---------|--------|----------|-------|
| `bode-plotter/` | ✅ | scope + SDG (or scope AWG) | Audio-band Bode plots fully self-contained on the scope's AWG. |
| `clock-jitter/` | 🧪 | scope MSO | Cycle-to-cycle jitter histogram; PLL lock-time measurement. **MSO probe pod ordered, untested.** |
| `eye/` | ✅ | scope | Eye diagram from N triggered captures; jitter histogram. |
| `glitch/` | ✅ | scope | Long-running glitch / runt-pulse / dropout trap with timestamped capture archive. |
| `power-integrity/` | 🧪 | scope MSO | Mixed-signal: digital bus + analog supply rail on shared timebase. **MSO untested.** |
| `protocol-analyzer/` | 🧪 | scope MSO (or Bus Pirate sniffer fallback) | SPI / I2C / UART decode. **MSO untested.** Bus Pirate substitution path documented. |
| `tdr/` | ✅ | SDG + scope + SMA T | See `projects/rf/tdr/` — alias entry for cross-reference. |
| `txvs/` | ✅ | scope | Transmitter-vs-scope characteristic capture. |

### projects/vna

Uses the swappable VNA API — `rf_bench.nanovna.NanoVNA` (working) or
`rf_bench.hp.HP8712B` (hardware pending). Scripts call only the shared
method set so the same code runs on either backend.

| Project | Status | Hardware | Notes |
|---------|--------|----------|-------|
| `swr-pdf/` | ✅ | NanoVNA-F (`/dev/ttyACM1`) or HP 8712B | S11 → VSWR-vs-frequency single-page PDF. Amateur-band shading 160 m – 70 cm. Tested 2026-06-30 against NanoVNA-F across 2 m / 70 cm / 3–30 MHz. |
| `smith-pdf/` | ✅ | NanoVNA-F or HP 8712B | S11 → Smith-chart single-page PDF, frequency-coloured locus. Tested 2026-06-30 against NanoVNA-F on 70 cm / 23 cm / HF. |
| `return-loss-pdf/` | 🧪 | NanoVNA-F or HP 8712B | S11 → return-loss-dB PDF with equivalent-VSWR secondary axis. Better than swr-pdf for sub-2:1 fine-tuning. Authored 2026-06-30; not yet run against hardware. |
| `cable-loss-pdf/` | 🧪 | NanoVNA-F or HP 8712B (THRU) | S21 THRU → coax insertion-loss PDF; optional dB/100 ft panel with manufacturer-curve overlay (RG-58/-213/LMR-400/etc.) and pass/fail target line. Authored 2026-06-30. |
| `filter-pdf/` | 🧪 | NanoVNA-F or HP 8712B (THRU) | S21 → filter response PDF with auto-detected -3/-6/-20/-40/-60 dB bandwidths, ripple, shape factor, stopband floor. Optional `--phase` and `--group-delay` panels. Authored 2026-06-30. |
| `group-delay-pdf/` | 🧪 | NanoVNA-F or HP 8712B (THRU) | Standalone S21 group-delay tool (\|S21\| / ∠S21 / τ_g panels). For amp / cable / matching-network work where filter-pdf bandwidth detection is irrelevant. Authored 2026-06-30. |
| `impedance-pdf/` | 🧪 | NanoVNA-F or HP 8712B | Full one-port diagnostic: R+jX, \|Z\|+∠Z, VSWR, Smith locus, optional X=0 resonance hunter. Supersedes legacy `antenna/` and `impedance/`. Authored 2026-06-30. |
| `tline-pdf/` | 🧪 | NanoVNA-F or HP 8712B | Transmission-line characterisation: VF, loss/m, optional Z₀(f) via OSL-S11 two-pass method. Two methods: `--method s21` (fast, Z₀ assumed 50) and `--method osl-s11` (derives Z₀ for unknown lines). Supersedes legacy `tline/`. Authored 2026-06-30. |
| `sparams-pdf/` | 🧪 | NanoVNA-F (DUT-reversal, two-pass) or HP 8712B (native 4-S-param) | Full 2-port S-parameters + Touchstone .s2p. NanoVNA captures S11+S21 forward, then prompts to physically reverse the DUT for S22+S12. HP captures all four natively. Supersedes legacy `sparams/`. Authored 2026-06-30. |
| `choke-pdf/` | 🧪 | NanoVNA-F or HP 8712B (series-through fixture) | Common-mode choke |Z| / R / X PDF using the K6JCA / DXE series-through method (Z = 2·Z0·(1−S21)/S21). Authored 2026-06-30. |
| `toroid-sniff/` | 🧪 | NanoVNA-F or HP 8712B (series-through) | Wound-toroid L / Al / Q PDF with a mix-consistency hint (43 / 31 / 61 / 77 / 2 / 6) based on Q-peak frequency. Authored 2026-06-30. |
| `balun-pdf/` | 🧪 | NanoVNA-F or HP 8712B (two-pass) | Balun characterisation: RL + insertion loss + amplitude balance + phase balance, captured as two passes (swap A↔B with the other leg in 50 Ω). 0° / 180° nominal phase per balun topology. Authored 2026-06-30. |
| `resonance-finder/` | 🧪 | NanoVNA-F or HP 8712B | Auto-find S11 dips, fit -3 dB BW, report loaded Q. PDF + CSV. Authored 2026-06-30. |
| `connector-check/` | 🧪 | NanoVNA-F or HP 8712B | Per-amateur-band PASS / FAIL return-loss check vs configurable threshold. PDF + JSON; non-zero exit on FAIL. Authored 2026-06-30. |
| `tdr-pdf/` | 🧪 | NanoVNA-F or HP 8712B | Host-side IFFT time-domain reflectometer (step + impulse), cable-VF presets, fault auto-classification. **Time-gating extension added 2026-06-30:** `--gate-start-m` / `--gate-end-m` window the impulse response and FFT back to show the frequency response of one isolated reflection. Authored 2026-06-30. |
| `de-embed-pdf/` | 🧪 | post-processor (no VNA needed) | Take a `measurement.s2p` and a `fixture.s2p`, return the DUT-alone S-parameters. S↔T cascade math. Symmetric (one half-jig file) or asymmetric (separate input/output) topology. PDF before/after + `.s2p`. Authored 2026-06-30; self-tested to round-trip at machine precision. |
| `mixed-mode-pdf/` | 🧪 | post-processor (no VNA needed) | 4-port single-ended `.s4p` → mixed-mode S-params (Sdd / Scc / Sdc / Scd). Bockelman / Eisenstadt mode transform, selectable port-pair convention (1-2/3-4 or 1-3/2-4). PDF + mixed-mode .s4p. Authored 2026-06-30; self-tested with synthetic ideal diff pair. |
| `crystal-bvd-pdf/` | 🧪 | NanoVNA-F or HP 8712B (or `.s2p` input) | Butterworth-Van Dyke crystal extraction. Live capture sweeps ±1 % around `--estimate`, fits Lm / Cm / Rm / C0 / Qm with iterative C0 refinement. Output: PDF + SPICE-paste-ready `.sub` subcircuit. Authored 2026-06-30; self-tested on synthetic 10 MHz crystal to 0.3 % parameter recovery. |
| `vector-fit-spice/` | 🧪 | post-processor (no VNA needed) | Gustavsen Vector Fitting → behavioural Laplace subcircuit for LTspice or ngspice. Fits S11/S12/S21/S22 with N poles, exports `.sub` with full rational form. Authored 2026-06-30; self-tested on synthetic 2nd-order BPF (6 poles → 0.23 dB RMS fit error). |
| `antenna/` | ❌ *(superseded)* | — | Legacy HP-only feed-point impedance. **Use `impedance-pdf/` instead.** Kept for historical reference. |
| `filter/` | ❌ *(superseded)* | — | Older HP-only filter S21 stub. **Use `filter-pdf/`** (add `--phase`/`--group-delay` for the HP-equivalent capabilities). |
| `group-delay/` | ❌ *(superseded)* | — | **Use `group-delay-pdf/` (standalone) or `filter-pdf/ --group-delay`.** |
| `impedance/` | ❌ *(superseded)* | — | **Use `impedance-pdf/`.** |
| `sparams/` | ❌ *(superseded)* | — | **Use `sparams-pdf/`** — it handles the NanoVNA DUT-reversal trick automatically. |
| `tline/` | ❌ *(superseded)* | — | **Use `tline-pdf/`** (NanoVNA-friendly with two methods). |
| `transistor/` | ❌ | HP 8712B (pending) | **Still HP-only.** Parametric bias-swept S-params require all four S-params at every bias point; the DUT-reversal trick is impractical at that scale. |

### projects/spectrum

| Project | Status | Notes |
|---------|--------|-------|
| `band-occupancy/` | ✅ | Continuous spectrum waterfall logger; threshold-triggered captures; multi-band cycling; `.npz` archives. |
| `emi-finder/` | 🧪 | Correlates SSA peaks with MSO-captured clock harmonics. **MSO untested.** |
| `ssa-fm-monitor/` | ✅ | FM band 87.5–108 MHz monitor; alert mode for new station appearances. |

### projects/dmm

| Project | Status | Notes |
|---------|--------|-------|
| `contact/` | ✅ | 4-wire Kelvin contact resistance survey; sub-mΩ resolution. |
| `sorter/` | ✅ | Continuous-poll component sorter with audio bin announcement; R/4WR/C/diode Vf. |
| `tcr/` | ✅ | TCR via SDM thermocouple + 4-wire R; polynomial fits for thermistors / RTDs. |

### projects/power

| Project | Status | Notes |
|---------|--------|-------|
| `battery-tester/` | ✅ | Capacity (mAh integration), internal R (current pulse method), multi-cycle aging. |
| `inrush/` | ✅ | Power-on inrush capture; I²t integral; NTC effectiveness comparison. |
| `psrr/` | ✅ | PSRR via scope AWG injection on supply rail through coupling cap. |
| `psu-characterizer/` | ✅ | Load reg / line reg / efficiency / ripple / transient response. |
| `psu-sequencer/` | ✅ | Multi-rail JSON-defined power-on/off sequences with overcurrent abort. |
| `thermal-rth/` | ✅ | θ_JA / θ_CS / θ_SA via SPD dissipation + SDM thermocouple. |

### projects/components

| Project | Status | Notes |
|---------|--------|-------|
| `crystal-extractor/` | ✅ | (Cross-listed under `projects/rf/`.) |
| `iv-tracer/` | ✅ | (Cross-listed under `projects/rf/`.) |
| `stress-monitor/` | ✅ | Long-duration component stress (DC bias on MLCC, ESR aging on electrolytics, R drift under power, Zener drift). |
| `varactor/` | ✅ | C(V) and Q(V) sweep with bias-network isolation choke; tuning-ratio plot. |

### projects/audio

| Project | Status | Notes |
|---------|--------|-------|
| `audio-chain/` | ✅ | (See [projects/radio](#projectsradio).) |

### projects/flipper

| Project | Status | Notes |
|---------|--------|-------|
| `alarm-monitor/` | 🧪 | Cheap 315/433 MHz wireless alarm sensor decoder (EV1527 / PT2262). |
| `cc1101/` | ✅ | CC1101 synthesizer + TX characterizer; output power per PATABLE setting per band. |
| `ir-daemon/` | 🧪 | HTTP REST API for IR send/receive. |
| `ir-discover/` | 🧪 | Brute-force NEC/SIRC/RC5/RC6 command codes; interactive flagging. |
| `ir-library/` | 🧪 | IR remote code library builder; LIRC / Pronto / JSON / Home Assistant exports. |
| `ir-rx-response/` | 🧪 | IR receiver carrier-frequency-response sweep with photodiode + scope. |
| `ir-waveform/` | 🧪 | Capture Flipper IR LED output; carrier accuracy, duty cycle, envelope timing vs spec. |
| `link-test/` | 🧪 | Two-end packet ping/pong (Flipper × 2 or Flipper + Bus Pirate CC1101). |
| `outlet/` | ✅ | 433 MHz smart-outlet capture and replay; REST API. |
| `rfid-field/` | 🧪 | 125 kHz / 13.56 MHz field characterization via coupling loop + SSA. |
| `rf-scan/` | ✅ | Sub-GHz RF environment scanner — CC1101 RSSI sweep across ISM bands. |
| `sensor-hub/` | 🧪 | 433 MHz ISM sensor hub (Oregon Scientific / Fine Offset / AcuRite decoders). |
| `subghz-decode/` | ✅ | Pairs Flipper protocol decode with SSA RF measurement on the same burst. |
| `subghz-library/` | 🧪 | Sub-GHz remote-code library builder; Flipper `.sub` / openMQTTGateway export. |
| `subghz-sensitivity/` | ✅ | Sub-GHz RX MDS, RSSI calibration, sensitivity vs band. |
| `tpms/` | 🧪 | TPMS decoder for 315 MHz (US) and 433.92 MHz (EU) cars. |

### projects/rtlsdr

| Project | Status | Notes |
|---------|--------|-------|
| `acars/` | 🧪 | ACARS aircraft-comms decoder. |
| `adsb/` | ✅ | 1090 MHz Mode S decode via pyModeS; govt-data API enrichment; SQLite + HTTP API. |
| `ais/` | 🧪 | Maritime AIS decoder. |
| `aprs/` | ✅ | Direct-RF APRS @ 144.390 MHz via rtl_fm + direwolf; APRS-IS comparison report. |
| `bubba-detector/` | ✅ | Multi-band handheld-radio activity scanner (FRS / GMRS / MURS / Marine VHF / NOAA / business band). |
| `classify/` | ✅ | Signal classifier (AM/OOK/FM/FSK/PSK/CW/pulsed); BW + symbol rate; optional SSA handoff. |
| `drivetest/` | ✅ | Single-frequency drive-test logging; CSV + GPX track. |
| `fm-rds/` | ✅ | FM monitor with RDS decode (PI/PS/PTY/RT); tropospheric ducting alert. |
| `ook-link/` | 🔶 | OOK + 2-FSK link test (Flipper TX + RTL-SDR RX); GFSK/MSK RX-only because Flipper TX crashes on those presets. |
| `recorder/` | ✅ | SigMF IQ recorder: immediate / scheduled / threshold-triggered / rotating buffer; complex64 or int8. |
| `satellite/` | ✅ | Wideband satellite passband monitor — RTL-SDR while IC-9700 does duplex; SigMF recording; built-in DB for AO-91/-92, SO-50, ISS, FO-29, AO-7. |
| `survey/` | ✅ | Wideband mobile spectrum survey at intervals; geo-tagged CSV. |
| `wxsat/` | 🧪 | Weather satellite decoder (NOAA APT 137 MHz; Meteor-M N2-4 LRPT). End-to-end image production untested. |

### projects/kiwisdr

All KiwiSDR projects are 🧪 — code is complete, IP TBD until the KiwiSDR is
powered on and assigned an address. Update this document when it is.

| Project | Notes |
|---------|-------|
| `hf-monitor/` | Continuous HF band activity; SQLite log. |
| `band-opening/` | Detects activity changes signaling propagation openings. |
| `cw-skimmer/` | CW segment monitor with callsign detection. |
| `digital-monitor/` | FT8 / FT4 / JS8 calling-frequency monitor; raw IQ to SigMF. |
| `full-spectrum/` | 0–30 MHz waterfall with multi-channel parallelism. |
| `noise-figure/` | Y-factor NF measurement; multi-channel simultaneous frequencies. |
| `panadapter/` | Panoramic display fed by tap on the IC-7300 IF / antenna. |
| `propagation/` | Multi-frequency noise-floor logger; correlate with K/A index. |
| `swbc/` | Shortwave broadcast band scanner. |
| `wwv/` | WWV/WWVH multi-frequency S/N monitor (real-time ionogram proxy). |

(💭 future: `tdoa/` — multi-receiver TDoA bearings using the public KiwiSDR network — not yet present in the tree.)

### projects/sunsdr

All SunSDR projects are 🧪 (code complete, IP TBD) **except `tci-audiopipe/`**
which has an archived working proxy at
`projects/sunsdr/tci-audiopipe/archive/2026-06-06-working-proxy-solution/`.

| Project | Notes |
|---------|-------|
| `band-opening-relay/` | Relay alert on 50.125 MHz USB activity (TRX 1 monitors 6 m). |
| `cal-smeter/` | Cross-receiver S-meter calibration vs IC-7300 reference. |
| `diversity/` | KiwiSDR + SunSDR diversity reception (equal-gain / maximal-ratio combining). |
| `dual-scan/` | TRX 0 sweeps HF, TRX 1 holds VHF calling freq. |
| `hf-compare/` | KiwiSDR vs SunSDR amplitude / sensitivity comparison. |
| `hf-scanner/` | Wideband HF band scanner exploiting 192 kS/s IQ. |
| `phase-noise/` | SunSDR as coherent receiver for phase-noise of an IC-7300 carrier. |
| `remote-speaker/` | Browser audio player via TCI WebSocket. |
| `so2r/` | SO2R contest automation: IC-7300 + SunSDR. |
| `station-monitor/` | Combined SunSDR + RTL-SDR full-spectrum station monitor. |
| `tci-audiopipe/` | TCI audio bridge — RX-only, archived working proxy from 2026-06-06. |
| `tci-sidecar-linux/` | Linux sidecar (companion to tci-audiopipe / TCI Audio Router). |
| `tci-sipphone/` | SIP phone integration over TCI audio. |
| `tx-arb/` | TX waveform injection (WSPR / FT8 / CW / test tones). |
| `tx-characterize/` | HF TX characterization with 192 kHz IQ. |
| `vhf-monitor/` | 100–150 MHz wideband activity monitor (TRX 1). |
| `vhf-tx-test/` | IC-9700 TX → SunSDR TRX 1 wideband measurement. |

### hardware/

Standalone embedded hardware projects that aren't part of the ESP32 SCPI
fleet (different MCU / different network stack / different protocol).

| Project | Status | Hardware | Protocol | Use Case |
|---------|--------|----------|----------|----------|
| `arduino-relay-board/` | ✅ | Arduino Uno R3 + Vilros Ethernet R3 (W5100 + microSD) + 4-ch active-HIGH relay module | ASCII line protocol on TCP :5025 (DHCP, address 10.1.1.36) | Wired-Ethernet remote relay switching where WiFi (ESP32 `scpi-relay/`) is undesirable or unavailable |

Tested on hardware 2026-06-25 — all four relays exercise correctly via
`hardware/arduino-relay-board/test_relays.py` against the
`rf_bench.arduino_relay_board.ArduinoRelayBoard` driver. Non-blocking
pulse mode (`PULSEH`/`PULSEL`) confirmed; explicit `ON`/`OFF` correctly
cancels an in-flight pulse.

---

### projects/esp32

ESP32-based SCPI-over-WiFi controllers. Each project connects to WiFi, exposes SCPI commands on TCP port 5025 (industry standard), and controls external hardware via GPIO/I2C/SPI/UART. Common pattern across all projects: Arduino IDE sketch (~400-600 lines), WiFi credentials embedded in source, IEEE 488.2 common commands (*IDN?, *RST, SYST:ERR?), domain-specific SCPI subsystem. Each project directory contains: `.ino` sketch, `README.md` (user guide with wiring, commands, examples), `test_*.py` (Python demo).

**Status codes:** ✅ = tested on hardware; 🔨 = built to documentation (not yet tested); 💭 = idea only.

**All 35 ESP32 SCPI projects are now built to documentation (🔨)**. Each includes complete `.ino` firmware and a `README.md` user guide. Hardware testing pending.

| Project | Status | Hardware | SCPI Subsystem | Use Case |
|---------|--------|----------|----------------|----------|
| `scpi-relay/` | ✅ | 4× relay outputs + 4× digital inputs + 1× analog input (0-3.3V ADC) | `ROUTE:`, `MEAS:` | ATE switching, DUT control, sensor monitoring |
| `scpi-gps/` | ✅ | Serial GPS module (NEO-6M/7M/8M), UART @ 9600 baud | `GPS:` | Position logging, RF field testing, time sync |
| `scpi-servo/` | ✅ | 4× RC hobby servos (SG90, MG996R), external 5V PSU required | `SERV:` | Antenna positioning, sample rotation, optical alignment |
| `scpi-temp/` | ✅ | DS18B20 1-Wire (8-16 sensors on single GPIO) | `TEMP:` | Environmental monitoring, thermal testing |
| `scpi-imu/` | ✅ | MPU6050 or LSM9DS1 (accel/gyro/mag via I2C) | `IMU:` | Vibration testing, tilt monitoring, motion detection |
| `scpi-power/` | ✅ | INA219/INA226 I2C voltage/current sensor | `MEAS:` (V/I/P/energy) | Power consumption logging, DUT characterization |
| `scpi-adc/` | 🔨 | ADS1115 16-bit 4-channel I2C ADC with PGA | `MEAS:`, `ADC:` | Precision voltage measurement, sensor interfacing |
| `scpi-counter/` | 🔨 | GPIO interrupt + ESP32 PCNT peripheral | `COUN:` | Frequency/event counting, RPM measurement |
| `scpi-encoder/` | 🔨 | Quadrature decoder (2-4 rotary encoders) | `ENC:` | Position feedback, knob reading, angle measurement |
| `scpi-distance/` | 🔨 | HC-SR04 ultrasonic or VL53L0X ToF laser | `DIST:` | Level sensing, proximity detection, automated positioning |
| `scpi-stepper/` | 🔨 | A4988/DRV8825 drivers (2-4 stepper motors) | `STEP:` | Linear stages, rotary tables, precise positioning |
| `scpi-motor/` | 🔨 | L298N/TB6612 H-bridge (2-4 DC motors) | `MOT:` | Drive test rigs, conveyor control, robotic arms |
| `scpi-pwm/` | 🔨 | 4-16 independent PWM channels (LED PWM peripheral) | `PWM:` | LED dimming, fan control, signal generation |
| `scpi-dac/` | 🔨 | MCP4725 (1-ch) or MCP4728 (4-ch) I2C DAC, 12-bit | `DAC:` | Programmable voltage source, bias control, waveform gen |
| `scpi-neo/` | 🔨 | WS2812B/NeoPixel addressable RGB LED strip | `LED:` | Status indicators, light shows, visual test feedback |
| `scpi-heater/` | 🔨 | Heater element + DS18B20 + PID control via SSR/MOSFET | `HEAT:` | Environmental chambers, PCB reflow, thermal testing |
| `scpi-i2c/` | 🔨 | I2C master interface (scan bus, read/write arbitrary devices) | `I2C:` | I2C device testing, sensor development, debugging |
| `scpi-spi/` | 🔨 | SPI master interface (generic transactions) | `SPI:` | SPI device control, flash memory, ADC/DAC interfacing |
| `scpi-uart/` | 🔨 | Serial UART bridge (transparent or command parser) | `UART:` | Control serial devices over network, GPS forwarding |
| `scpi-can/` | 🔨 | MCP2515 CAN controller (automotive/industrial) | `CAN:` | Vehicle diagnostics (OBD-II), industrial automation |
| `scpi-modbus/` | 🔨 | RS-485 Modbus RTU/TCP gateway | `MODB:` | Industrial sensor/actuator control, building automation |
| `scpi-ir/` | 🔨 | IR LED (TX) + TSOP receiver (RX) | `IR:` | Remote control testing, appliance automation, IR replay |
| `scpi-rotator/` | 🔨 | Antenna rotator: 2 servos (az/el) + limit switches | `ROT:` | Antenna aiming, satellite tracking, antenna pattern measurement |
| `scpi-ptt/` | 🔨 | PTT (push-to-talk) controller: GPIO outputs + VOX sense inputs | `PTT:` | Remote radio keying, automated TX sequences, amplifier sequencing |
| `scpi-atten/` | 🔨 | RF attenuator: PE4302, HMC472, or relay-switched network | `ATTE:` | Signal level control, gain/loss measurement, dynamic range testing |
| `scpi-swr/` | 🔨 | SWR/power meter: AD8707 log detector or directional coupler + ADC | `SWR:`, `POW:` | Antenna tuning automation, transmitter testing, protection monitoring |
| `scpi-keyer/` | 🔨 | CW keyer: iambic with paddle inputs | `KEY:` | Automated CW testing, beacon control, contest logging |
| `scpi-tuner/` | 🔨 | Antenna tuner controller: motorized variable caps or relay L/C network | `TUNE:` | Automated antenna matching, remote tuner control |
| `scpi-funcgen/` | 🔨 | Function generator: DAC + DDS for sine/square/tri/arb waveforms | `FUNC:` | Audio testing, sensor stimulation, filter response |
| `scpi-pulse/` | 🔨 | Pulse/pattern generator: GPIO with precise timing | `PULS:`, `PATT:` | Clock generation, trigger signals, digital pattern injection |
| `scpi-tone/` | 🔨 | Audio tone generator: I2S DAC or PWM audio output | `TONE:` | Audio testing, DTMF generation, calibration tones |
| `scpi-mux/` | 🔨 | Analog multiplexer: CD4051/CD4067 or relay matrix | `MUX:` | Multi-DUT switching, instrumentation multiplexing |
| `scpi-load/` | 🔨 | Electronic load: MOSFET + op-amp constant current sink | `LOAD:` | Battery discharge testing, PSU characterization, LED testing |
| `scpi-decade/` | 🔨 | Programmable decade box: relay-switched resistor/capacitor network | `RES:`, `CAP:` | Resistance substitution, sensor simulation, calibration |
| `scpi-matrix/` | 🔨 | Signal routing matrix: relay crosspoint (N inputs × M outputs) | `MATR:` | Automated signal routing, multi-instrument switching |

**Hardware notes:**
- **Power:** Most projects run on USB power alone. Servos, relays, motors, and LED strips require external 5V power supply (2-5A depending on load).
- **I/O levels:** ESP32 is 3.3V logic. Use level shifters or voltage dividers for 5V interfacing.
- **Libraries:** Most projects use built-in Arduino libraries (Wire for I2C, SPI for SPI, HardwareSerial for UART). Servos need ESP32Servo library. DS18B20 needs OneWire + DallasTemperature. IMU needs sensor-specific library (e.g., Adafruit_MPU6050).
- **GPIO:** Common assignments reused across projects (relays/servos on GPIO 25/26/27/14; I2C on SDA=21/SCL=22; SPI on VSPI MOSI=23/MISO=19/SCK=18/CS=5; UART2 on RX=16/TX=17). Alternatives documented in each project's README.

**Integration:** All projects integrate with LabVIEW, MATLAB, Python (pyvisa or raw socket), Keysight VEE, TestStand via standard SCPI/VISA. Python test scripts included in each project directory.

---

