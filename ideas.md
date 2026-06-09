# Siglent Instrument Automation — Project Ideas

## Inventory

| Model | Type | Key specs |
|-------|------|-----------|
| SDS2504X Plus | Oscilloscope | 4-ch, **500 MHz BW**, AWG output (licensed), LAN SCPI; firmware 5.4.0.1.6.2R5 |
| SSA3032X Plus | Spectrum analyzer | 9 kHz – 3.2 GHz, tracking generator (0 dBm max), LAN SCPI; firmware 3.2.x |
| RB3X25 | Reflection bridge | DUT port for antenna/impedance measurement |
| SDM3045X | Bench DMM | 4.5-digit, V/A/R/C/freq/temp, 4-wire Kelvin, LAN SCPI |
| SPD3303X-E | DC power supply | CH1+CH2: 0–32 V / 0–3.2 A independent; CH3: fixed 5 V; LAN SCPI |
| SDG1062X | Function generator | 2 independent channels, 60 MHz, −50 to ~+24 dBm, LAN SCPI |
| Yertai ET5406A+ | Programmable DC load | 200W, 0–120V, 0–20A; CC/CV/CR/CP/battery/transient/list/LED modes; USB (CH340 → /dev/ttyUSBx); SCPI-like over serial |
| Icom IC-7300 (×2) | HF transceiver | 160m–10m + 6m; CAT via USB CI-V; Hamlib support; AGC disableable via CAT; SDR-based DSP with calibrated S-meter |
| Icom IC-9700 | VHF/UHF/SHF transceiver | 2 m + 70 cm + 23 cm; CAT via USB CI-V or LAN; Hamlib support; satellite mode (split VFOs with cross-band Doppler tracking); `rf_bench.icom.IC9700` adds split / PTT / TX freq / Doppler / band-of helpers on top of the core radio API |
| Yaesu FT-891 | HF + 6 m transceiver | 160 m–6 m, 100 W; CAT via USB at 38400 baud (factory default; menu 031 CAT RATE); preamp (off / IPO / AMP1) and 12 dB attenuator are CAT-controlled; AGC "off" maps to slowest setting only — not a true AGC bypass; `rf_bench.yaesu.FT891` |
| Bus Pirate | USB protocol bridge | SPI/I2C/UART/1-Wire/raw-wire master; 3.3V/5V selectable I/O; USB CDC serial → `/dev/ttyUSBx`; scriptable via pyserial. Version v3/v4 assumed; v5 uses different protocol — verify at connect time. |
| Flipper Zero | Multi-tool sub-GHz radio | 300–928 MHz Sub-GHz (CC1101) OOK/2-FSK/4-FSK/GFSK; 125 kHz LF RFID; 13.56 MHz NFC; IR; GPIO; USB protobuf RPC → `/dev/ttyACM0` |
| RTL-SDR Blog v4 | Software-defined radio receiver | 500 kHz–1766 MHz; 2.4 MHz instantaneous IQ bandwidth; R828D tuner; 1 PPM TCXO; bias tee (5V/180 mA); USB → librtlsdr/pyrtlsdr |
| gpsd | GPS daemon client | lat/lon/alt/speed/heading/DOP; TCP → localhost:2947; auto-reconnect; metric + imperial; `rf_bench.gpsd` |
| HP 8712B | Vector network analyzer | 300 kHz–1.3 GHz; HPIB/GPIB; full 2-port SOLT calibration; S11/S21/S12/S22 + phase; *pending Ethernet-GPIB adapter* |
| Solartron 7151 | 6.5-digit Computing Multimeter (1985) | DCV (200 mV–2 kV), ACV, kΩ (20k–20M), DC/AC current; 6.5-digit (~8 s int), 5.5-digit (400 ms), 3.5-digit (6.7 ms); IEEE-488; calibration via internal HI/LO/WRITE routine + 2.5 mm CAL plug; `rf_bench.solartron`; *pending Ethernet-GPIB adapter* |
| Koolertron / MHinstek MHS-5225A | Dual-channel DDS signal generator + frequency counter (rebranded KKmoon) | 0–25 MHz sine (CH1 limit per model suffix), 200 MSa/s, 12-bit; sine/square/triangle/up-saw/down-saw + 16 user-arb slots; per-channel ampl/duty/offset/phase/atten; built-in counter (frequency / count / period / +pulse / -pulse / duty modes); sweep (linear/log); 10 memory slots; CH340 USB at 57600 baud; `rf_bench.koolertron`; **tested 2026-06-08** against the unit on 10.1.1.52 |
| SunSDR2 Pro | HF/VHF SDR transceiver | 0.1–55 MHz (TX+RX) + 100–150 MHz (RX only); 192 kHz IQ bandwidth (±96 kHz); dual simultaneous TRX; TX IQ injection; Ethernet → ExpertSDR3 TCI port 50001; `rf_bench.sunsdr` |
| KiwiSDR | HF software-defined receiver | 0–30 MHz; 14-bit ADC at 66 MS/s; GPS-disciplined TCXO; 4–8 simultaneous channels; 12 kS/s per channel; ±5 kHz BW per channel; WebSocket SND API; `rf_bench.kiwisdr` |
| XL9535 relay board | I2C relay controller | 16-bit I/O (XL9535/PCA9535/TCA9535); 8 or 16 relays; I2C master via Bus Pirate; `rf_bench.relay`; ⚠ on-board HK19F relays are DC/audio only — use external RF-rated relays for RF signal routing |

**Software options:** All factory software upgrades installed on all Siglent instruments. Notable:
- SDS2504X Plus: full 500 MHz BW; AWG built-in (confirmed working via driver)
- SSA3032X Plus: includes REFL (reflection/VSWR firmware) — the antenna analyzer project deliberately
  avoids using it (manual calibration is more flexible), but it's available if simpler operation is needed
- SDG1062X: all waveform/modulation options

**Firmware quirks confirmed by testing:**
- SDS2504X Plus firmware 5.4.x: `:WAVeform:DATA?` occasionally returns display buffer (1000 pts);
  0.1 V/div and 0.5 V/div trigger a different firmware bug (excluded from driver); TDIV change while
  stopped silently corrupts VDIV register (driver re-applies VDIV after every TDIV change). See rf-bench/README.md.
- SSA3032X Plus firmware 3.2.x: `:SENS:SWE:POIN` is silently ignored — always returns 751 points.
  The `--points` and `--quick` flags in antenna_analyzer.py have no effect on this firmware.
- SDS2504X Plus amplitude at 1 MΩ input: scope reads ~3× higher than the 50Ω-equivalent voltage
  that the SDG reports. Open-circuit theory predicts 2× (voltage doubling); the excess is
  unresolved but consistent and reproducible. **Relative amplitude measurements are accurate;
  absolute amplitude comparisons between scope and SDG readings are not.**

Pattern established in `siglent-antenna-analyzer/`: raw TCP socket to port 5025, no pyvisa.
DC load: Yertai ET5406A+ (OEM'd from East Tester / Hangzhou Zhongchuang). Confirmed specs:
200W, 0–120V, 0–20A. Modes: CC, CV, CR, CP, CCCV, CRCV, battery test, transient, list, scan,
LED simulation, short circuit.

**Interface:** CH340 USB-to-serial chip → appears as `/dev/ttyUSBx` on Linux (even when load is
off). Uses SCPI-like commands over serial. **Timing quirk:** must wait ≥200ms between commands;
occasionally takes much longer to respond, causing random test failures if not handled.

**Integration differs from Siglent instruments:** Siglent uses raw TCP socket to port 5025; the
ET5406A+ uses serial/VISA. Use `pyvisa` with resource name `"ASRL/dev/ttyUSB0::INSTR"` (Linux)
or `"ASRL2::INSTR"` (Windows), or plain `pyserial` if avoiding pyvisa.

**Existing Python library:** [ET54.py by philpagel](https://github.com/philpagel/ET54.py) —
explicitly lists ET5406A+ as supported. Tested on ET5410A+ and ET5407A+. Wraps all modes and
measurements. Use this rather than writing raw SCPI from scratch.

**RTL-SDR:** Uses `pyrtlsdr` Python library wrapping `librtlsdr`. Interface differs from all
Siglent instruments and the radios: no TCP/SCPI, no serial — `librtlsdr` opens the USB device
directly. **Single-process constraint:** only one process may open the RTL-SDR at a time; the
driver should check and raise a clear error rather than letting librtlsdr abort.
**PPM calibration:** the v4 TCXO is nominally 1 PPM but should be verified against a known
reference (SDG + SSA on a carrier) before use; store the measured correction and apply it
in the driver to every `set_center_freq()` call. **Bias tee:** enable via
`rtlsdr_set_bias_tee()` to power an inline LNA; disable when not needed to protect
the LNA if RF input is removed.

---

## Completed Projects

All 19 projects are implemented and published to GitHub and PyPI where applicable.

| Project | Repo | PyPI |
|---------|------|------|
| Receiver Test Suite | rf-bench-receiver-test | — |
| Antenna / Signal Analyzer | rf-bench-signal-analyzer | — |
| Balun / Choke Analyzer | rf-bench-balun-analyzer | — |
| Battery Tester | rf-bench-battery-tester | — |
| Bode Plotter | rf-bench-bode-plotter | — |
| Calibration | rf-bench-calibration | — |
| Clock Jitter | rf-bench-clock-jitter | — |
| Crystal Extractor | rf-bench-crystal-extractor | — |
| EMI Finder | rf-bench-emi-finder | — |
| I-V Tracer | rf-bench-iv-tracer | — |
| Mixer Characterizer | rf-bench-mixer-characterizer | — |
| Power Integrity | rf-bench-power-integrity | — |
| Protocol Analyzer | rf-bench-protocol-analyzer | — |
| PSRR | rf-bench-psrr | — |
| PSU Characterizer | rf-bench-psu-characterizer | — |
| RF Amplifier | rf-bench-rf-amplifier | — |
| RF Impedance | rf-bench-rf-impedance | — |
| Scalar VNA | rf-bench-scalar-vna | — |
| TDR | rf-bench-tdr | — |
| Driver: Siglent | rf-bench-drivers-siglent | ✓ 0.1.0 |
| Driver: Icom | rf-bench-drivers-icom | ✓ 0.1.0 |
| Driver: Yaesu | rf-bench-drivers-yaesu | ✓ 0.1.0 |
| Driver: Utils | rf-bench-drivers-utils | ✓ 0.1.0 |
| Meta-package | rf-bench | ✓ 0.3.0 |

### Virtual Instrument Panels

All driver packages now include Tkinter virtual instrument panels with working controls:

| Panel | File | Instrument | Key Features |
|-------|------|-----------|--------------|
| ET5406A+ DC Load | `rf-bench-drivers-yertai/et5406a_panel.py` | Yertai ET5406A+ | Live V/I/P/R readouts; mode/input/protection status badges; working controls for mode selection (CC/CV/CP/CR/CC-CV), input on/off, set points; demo mode |
| SDG1062X Function Gen | `rf-bench-drivers-siglent/sdg1062x_panel.py` | Siglent SDG1062X | 2-channel frequency/amplitude display; CH1/CH2 ON/OFF; waveform selection (SINE/SQUARE/RAMP); frequency/level setting; demo mode |
| SPD3303X Power Supply | `rf-bench-drivers-siglent/spd3303x_panel.py` | Siglent SPD3303X-E | 3-channel V/I readouts; tracking mode (INDEP/SERIES/PARA); CH1/CH2/CH3 ON/OFF; voltage/current setting; demo mode |
| SDM3045X Multimeter | `rf-bench-drivers-siglent/sdm3045x_panel.py` | Siglent SDM3045X | Large measurement display; function badge; working controls for measurement mode (VDC/VAC/IDC/IAC/2W Ω/4W Ω/FREQ/DIODE/CONT); demo mode |
| IC-7300 Radio | `rf-bench-drivers-icom/ic7300_panel.py` | Icom IC-7300 | Large frequency display; mode/passband/S-meter/AGC tiles; working controls for mode (USB/LSB/CW/AM/FM/RTTY), AGC (OFF/FAST/MID/SLOW), frequency entry (Hz/kHz/MHz), quick band buttons (160m–10m); blue/amber Icom theme; demo mode |
| FT-891 Radio | `rf-bench-drivers-yaesu/ft891_panel.py` | Yaesu FT-891 | Large frequency display; mode/passband/S-meter/AGC/preamp/ATT tiles; working controls for mode (USB/LSB/CW/AM/FM/RTTY/PKT-U), AGC (OFF/FAST/MID/SLOW), preamp (IPO/AMP1), attenuator (OFF/6 dB/12 dB), frequency entry, quick band buttons; green Yaesu theme; demo mode |
| SSA3032X Spectrum Analyzer | `rf-bench-drivers-siglent/ssa3032x_panel.py` | Siglent SSA3032X Plus | Live spectrum trace (matplotlib embedded); center freq/span/RBW/ref level/attenuation tiles; peak search (freq + dBm); tracking generator on/off + level; marker readouts; demo mode (sweeping carrier + harmonics + noise) |
| SDS2504X Oscilloscope | `rf-bench-drivers-siglent/sds2504x_panel.py` | Siglent SDS2504X Plus | Four-channel waveform plot (matplotlib embedded); timebase/trigger/coupling/CH on-off tiles; V/div per channel; Vpp/freq/RMS readouts; demo mode (sine/square/pulse/noise per channel) |

**Common features across all panels:**
- Thread-safe command queue pattern: UI controls queue commands that execute in the background poll thread, avoiding race conditions
- Status bar with automatic timeout for operation feedback
- Demo mode for UI testing without hardware (`--demo` flag)
- Configurable refresh interval (`--interval MS` flag)
- Safety shutdown: all panels that control outputs (load, PSU, function gen, radios) safely disable outputs on window close
- Input validation: all entry fields validate ranges before queueing commands
- Color-coded status badges for instrument state

---

## High Value / Natural Extensions

### ✓ 1. ✓ Bode Plotter — *rf-bench-bode-plotter*

Use the function generator to sweep a frequency range, capture amplitude and phase from the scope
at each point, and plot gain/phase vs. frequency. Essential for characterizing filters, feedback
networks, amplifier response, and matching networks.

**Frequency range:** DC to 60 MHz (SDG1062X limit). The SDS2504X Plus is 500 MHz so it's not the
bottleneck. Fine for all HF filter and feedback-loop work; won't cover VHF.

**Phase measurement:** Use two scope channels — CH1 on input, CH2 on output. Zero-crossing
detection or FFT-based phase extraction gives phase difference at each frequency. Lock both
channels to the same trigger on CH1. Note: `capture_audio()` is optimized for audio bands;
for RF bode plots use a dedicated capture at appropriate TDIV per frequency point.

**Scope AWG variant:** The SDS2504X Plus has a built-in AWG (now driver-supported via
`set_awg_sine()`). For audio-frequency Bode plots of opamp circuits, filter boards, or speaker
crossovers, the scope can be entirely self-contained — AWG output drives the DUT, CH1 monitors
input, CH2 monitors output, all over one SCPI connection. No SDG required for this use case.

**Effort:** Medium.

---

### ✓ 2. ✓ RF Amplifier Characterizer — *rf-bench-rf-amplifier*

Inject a known signal level from the SDG into a DUT, measure output on the SSA. Produces:

- Gain vs. frequency
- Harmonic content / spurious (read SSA markers)
- 1 dB compression point (sweep input power at fixed frequency)
- **Two-tone IMD / IP3** — the SDG1062X is dual-channel with independent outputs; set two
  nearby frequencies (e.g. 14.000 and 14.010 MHz), combine through a simple resistive combiner
  (two 50Ω resistors in a T), inject into DUT, read IMD products on SSA. IP3 is then trivial to
  compute.

**Frequency range:** SDG covers DC to 60 MHz, so this works for all HF and 6m. For VHF/UHF
amplifiers, fall back to the SSA's own tracking generator as source (already proven in the
antenna analyzer) — just gives you gain and harmonics, not two-tone IMD above 60 MHz.

This is the logical sibling of the antenna analyzer — same SCPI pattern, same SSA, different
measurement. Reuses ~80% of `antenna_analyzer.py` infrastructure. Directly useful for verifying
homebrew PA stages, preamps, and transverter boards.

**Effort:** Low–medium. **Best first project.**

---

### ✓ 3. ✓ Two-Port Scalar Network Analyzer — *rf-bench-scalar-vna*

The antenna analyzer already measures S11 (reflection). Adding S21 (insertion gain/loss) in the
same sweep gives you a complete scalar two-port characterization — essentially a budget VNA.

**Measurement setup:**

```
         ┌─────────────────────────────────────────┐
         │        SSA3032X Plus                    │
         │  TG Out ──── RB3X25 ──── DUT ──── RF In │
         │                 │                       │
         │             (open cal)                  │
         └─────────────────────────────────────────┘
```

- **S11 sweep:** standard reflection bridge measurement (same as antenna analyzer). Calibrate
  open-circuit baseline; measure DUT reflection → return loss → VSWR.
- **S21 sweep:** remove bridge, connect TG Out → DUT → SSA RF In. Normalize against a
  through reference (TG Out → SSA In directly). Result is insertion gain/loss vs. frequency.
- Run both sweeps sequentially (two cable reconfigurations); overlay on same plot.

**What this enables:**
- Crystal/LC/bandpass filter characterization: insertion loss, passband width, stopband rejection,
  shape factor — all in one script with two cable setups
- Preamp/LNA gain + input match in one session
- Diplexer/triplexer design verification
- Coaxial stub/trap measurements

**Frequency range:** 9 kHz – 3.2 GHz (SSA tracking generator limit). This covers HF through
Wi-Fi/2.4 GHz. The SDG's 60 MHz ceiling is irrelevant here — the SSA is both the source and the
detector.

**Why this is different from a "real" VNA:** no vector (phase) data, no SOLT calibration, no S12
or S22. But for most RF amateur applications — filter sweeps, amplifier gain, matching networks —
scalar S11 and S21 are what you actually need, and this costs nothing beyond what's already in
the shack.

**Effort:** Low — builds directly on antenna_analyzer.py infrastructure.

---

### ✓ 4. ✓ Balun / Common-Mode Choke Impedance Analyzer — *rf-bench-balun-analyzer*

The reflection bridge already measures antenna impedance. Extend it to characterize baluns and
common-mode chokes:

- Measure choking impedance vs. frequency (connect the choke to the bridge's DUT port)
- Compare core materials, turns counts, wire gauges, geometries
- Verify that a choke actually blocks common mode at target frequencies

Methodology documented by W1HIS and G3TXQ. Zero new hardware required.

**Effort:** Very low — new analysis and display code on top of existing infrastructure.

---

### ✓ 5. ✓ Crystal Parameter Extractor — *rf-bench-crystal-extractor*

Crystals have four electrical parameters that govern filter design: motional inductance Ls,
motional capacitance Cs, series resistance Rs (Q factor), and parallel plate capacitance Cp.
These are extractable by sweeping through the crystal's resonance region and measuring the
impedance.

**Technique:** Insert the crystal in series with a 50Ω reference resistor between SDG and scope.
CH1 monitors the SDG output (reference); CH2 monitors voltage across the crystal. Sweep SDG
from a few kHz below to above the parallel resonance. At each frequency, compute:

```
Z_crystal = 50 × (V_crystal / V_ref)    (complex: magnitude and phase from scope)
```

Series resonance fs: impedance minimum (Z → Rs). Parallel resonance fp: impedance maximum.
From fs, fp, and Q: derive Ls, Cs, Cp, Rs analytically.

**Why it matters:** Crystal filter design requires sorted crystals matched within a few Hz. This
script lets you measure every crystal in a bag and bin them by frequency and Q. The SDG1062X's
0.001 Hz frequency resolution is more than adequate.

**The scope's role:** Two-channel amplitude and phase at each frequency point. Phase requires
careful synchronization — trigger CH1, measure CH2 phase offset via FFT on the captured
waveform. With the scope driver now working correctly (10 M sample captures at 20 MHz), the
FFT-based phase extraction is solid.

**Scope AWG variant:** For ham HF crystals (160m–10m: 1.8–30 MHz), the scope AWG covers the
entire range — no SDG required. The AWG also has a synchronization advantage: its output is
phase-coherent with the scope's internal timebase, eliminating any inter-instrument timing jitter
in the phase measurement. The SDG's better frequency resolution (0.001 Hz) is only relevant if
you need sub-Hz sorting precision.

**Effort:** Medium (the math is straightforward; robust phase extraction at RF is the hard part).

---

### ✓ 6. ✓ TDR — Time-Domain Reflectometer — *rf-bench-tdr*

The SDG generates a fast rising edge; the scope monitors the source end of a coax cable. Any
impedance discontinuity — bad connector, kink, moisture ingress, open, short — reflects a partial
echo back up the line. The round-trip delay gives the fault distance.

**Resolution:** SDG1062X rise time at 60 MHz square wave ≈ 3.5 ns. Velocity factor of RG-58/LMR
≈ 0.66c. Round-trip distance per nanosecond ≈ 10 cm. Practical fault location resolution:
**~17–20 cm** — fine for verifying a 50-foot feedline or finding a bad connector.

**Limit:** The SDS2504X Plus has a rise time of ~0.7 ns (500 MHz / 0.35), so the scope is not
the bottleneck; the SDG's edge speed is. For sub-10 cm resolution you'd need a dedicated TDR
pulse source. For typical amateur station coax (10–50m runs), this is more than adequate.

**Hardware:** SDG → SMA T-splitter → scope CH1 (as reference/monitor) → coax under test.
The other port of the T is the coax input. No additional hardware needed beyond an SMA T.

**Effort:** Low to medium. The hard part is the display — a TDR trace needs distance markers
calibrated to the cable's velocity factor (user input).

---

### ✓ 7. ✓ I-V Curve Tracer — *rf-bench-iv-tracer*

Sweep the power supply voltage in small steps, read current from the bench meter at each step,
plot I-V curves. The SPD3303X-E has two fully independent variable channels, enabling full
family-of-curves characterization:

- **Diodes / Zeners / LEDs:** CH1 sweeps forward voltage; read current via SDM
- **BJTs:** CH1 sweeps V_CE, CH2 steps I_B (via base resistor); family of I_C vs V_CE curves
- **FETs:** CH1 sweeps V_DS, CH2 steps V_GS; family of I_D vs V_DS curves
- Low-resistance measurements benefit from SDM3045X 4-wire Kelvin mode

Note: the SDM3045X already has built-in capacitance measurement (~1 kHz test frequency) — basic
cap sorting doesn't need a separate tool. The I-V tracer complements this for active devices.

**Effort:** Low–medium (diodes are easy; transistor families need careful current limiting to
avoid destroying devices during the sweep).

---

## More Speculative / Higher Effort

### ✓ 8. ✓ RF Impedance Measurement at RF Frequencies — *rf-bench-rf-impedance*

The SDM3045X already measures capacitance (at ~1 kHz), so basic component sorting is covered.
Where this is still useful: measuring component impedance at RF frequencies (100 kHz – 60 MHz)
where parasitic inductance of capacitors and self-resonance of inductors matter.

Technique: inject a sine from the SDG, use a 50Ω series reference resistor, measure V_ref and
V_dut with two scope channels, compute Z = 50 × (V_dut / V_ref) and extract L/C/ESR from
magnitude and phase.

**Useful for:** Finding self-resonant frequency of inductors; measuring capacitor ESR at RF;
characterizing ferrite beads at operating frequency; SMD component characterization.

**Now more feasible** than when first noted: the scope driver is solid (10 M deep-memory
captures, reliable phase via FFT), making RF impedance extraction from two-channel capture
practical without additional hardware.

**Effort:** Medium. Calibration and phase accuracy are the hard parts.

---

### ✓ 9. ✓ Mixer / Frequency Converter Characterization — *rf-bench-mixer-characterizer*

Connect SDG CH1 as LO, CH2 as RF input to a mixer under test. SSA reads the output spectrum.
Characterize:

- Conversion loss (desired IF product amplitude vs. RF input level)
- LO and RF port isolation (LO leakage to IF output, RF leakage to IF output)
- Spurious products (all IM products visible on SSA span)
- 1 dB compression of the IF output
- Two-tone IMD (both CH1 and CH2 as two RF inputs; measure IF products)

**Why interesting:** Mixer performance directly limits receiver and transmitter IMD. Characterizing
homebrew or surplus mixers (SBL-1, ADE-1, Schottky double-balanced types) before installing
them validates the design without needing a separate spectrum analyzer and signal source.

**Effort:** Low — nearly identical setup to the amplifier characterizer; different DUT topology.

---

### ✓ 10. ✓ Battery Capacity / Internal Resistance Tester — *rf-bench-battery-tester*

The programmable DC load is the right tool for this — it can sink constant current, constant
resistance, or constant power, none of which the SPD power supply can do as a load.

- **Capacity:** Set load to constant current discharge, log SDM terminal voltage vs. time,
  integrate to get mAh. Compare against rated capacity.
- **Internal resistance:** Pulse the load between two current levels, measure the instantaneous
  voltage step with the SDM (or scope for fast response), compute R_int = ΔV/ΔI.
- **Charge/discharge cycle:** SPD charges at constant current → constant voltage; load discharges
  at constant current. Automated cycling characterizes capacity fade.

Useful for evaluating NiMH/Li packs for portable radio use (IC-705, HTs, etc.).

**Effort:** Low.

---

### ✓ 11. ✓ Power Supply / Regulator Characterization — *rf-bench-psu-characterizer*

With a programmable source (SPD) and programmable sink (DC load), you can fully automate
power supply testing:

- **Load regulation:** Step load current from 0 to max, measure output voltage at each point.
  Plot V_out vs. I_load; a perfect supply is flat.
- **Line regulation:** Fix load current, sweep input voltage (requires an adjustable bench supply
  on the input side, or use the SPD on a converter under test).
- **Transient response:** Command a fast load step from the DC load, capture the output voltage
  transient on the scope. Reveals output capacitor sizing and feedback loop stability. The 500 MHz
  scope bandwidth is adequate even for fast switching regulators.
- **Efficiency:** Measure V_in × I_in (source side) and V_out × I_out (load side) simultaneously
  with the SDM; compute η = P_out / P_in vs. load current.
- **Ripple:** Scope on the output with DC-block coupling; measure peak-to-peak ripple at each
  load current.

**Effort:** Low–medium depending on how many measurements you want automated.

---

### ✓ 12. ✓ Cross-Instrument Calibration Verification — *rf-bench-calibration*

During driver testing, a 3× amplitude discrepancy appeared between the SDG's reported output
level (−10 dBm / 200 mVpp at LOAD=50) and the scope's measured amplitude (~600 mVpeak at 1 MΩ).
Open-circuit voltage doubling explains 2×; the extra factor is unresolved and consistent.

A structured calibration cross-check would:
- SDG generates a known level at known frequency
- All three measurement instruments read it: scope (via coax), SSA (via coax), DMM (RF probe)
- Build a correction table mapping each instrument's reading to the known SDG reference
- Optionally sweep frequency to map the flatness of each instrument's response

**Why this is valuable:** Every measurement project that follows inherits any systematic offset
from this one. A one-time calibration run establishes traceable baselines for all instruments.
The SDG itself should be verified against a known reference (e.g., a calibrated step attenuator
with known insertion loss) first.

**Effort:** Low (scripting) but requires a calibrated reference attenuator as a ground truth
for the SDG's output level.

---

---

## MSO / Digital Channel Ideas

These require the SDS2504X Plus MSO hardware option (digital probe pod). The driver is
implemented and ready; the hardware has not been tested. All five ideas below are new
capabilities — none were possible before MSO and AWG support were added to the driver.

---

### ✓ 13. ✓ Protocol Bus Analyzer — *rf-bench-protocol-analyzer*

Use the 16 MSO digital channels to capture SPI, I2C, UART, or other serial protocol traffic
directly from hardware, then decode it in Python from the returned numpy bool arrays. No
dedicated logic analyzer hardware needed — the scope does double duty.

**Direct value in radio work:**
- Verify SPI register writes to a DDS (AD9951, AD9835) or synthesizer (ADF4351, Si5351):
  capture D0=CLK, D1=MOSI, D2=CSB → decode register address and data being sent
- Monitor I2C traffic to a GPS module, band decoder, or antenna switch controller
- Capture UART output from embedded firmware under test
- Verify that an SDR frontend is receiving its register configuration correctly over SPI
- Check MCU PWM frequency and duty cycle without manually measuring on a scope screen

**Multiple channels at once:** `capture_all_digital([0, 1, 2, 3])` captures a complete SPI bus
(CLK, MOSI, MISO, CS) in a single acquisition on a shared timebase — all bit times are aligned.
Decode: find CS falling edges, then sample MOSI at each CLK rising edge.

**Sample rate tradeoff:** At 10 MSa/s (100 ns/sample), UART at 115200 baud has ~86 samples per
bit — easily decoded. SPI at 10 MHz has 1 sample per bit at that rate; bump to 100 MSa/s for
comfortable decoding margin. The scope's memory depth determines how many bytes fit in one shot.

**Effort:** Medium. `capture_all_digital()` is complete; the real work is writing robust SPI/I2C/
UART decoders in Python. SPI is the easiest (synchronous — sample MOSI on CLK edges). I2C needs
clock-stretching awareness. UART needs a known baud rate or auto-baud detection.

**Bus Pirate as MSO substitute:** If the MSO digital pod is not available, the Bus Pirate in
UART/I2C monitor / SPI sniffer mode can passively capture slow protocol traffic and decode it.
Bandwidth is limited (a few MHz at most) and there is no analog channel correlation, but for
configuration bus traffic (register writes at < 1 MHz SPI, I2C at 100 kHz, UART at ≤ 115200
baud) it is a practical alternative. The script should detect which backend is available and
use whichever is present.

---

### ✓ 14. ✓ Mixed-Signal Power Integrity — *rf-bench-power-integrity*

Capture digital switching activity on D0–D15 simultaneously with analog power supply voltage on
CH1–CH4. The shared timebase means you can see exactly which digital transition caused a supply
glitch — a capability impossible without MSO (a standalone logic analyzer and a scope are never
synchronized to the same moment).

**Use cases:**
- Find which GPIO or bus activity causes VCC dips in a battery-powered portable transceiver
- Measure ground bounce under simultaneous-switching outputs (SSO): capture 8 GPIO lines
  toggling together on D0–D7, measure resulting supply noise on CH1 at the IC's decoupling cap
- Verify decoupling effectiveness: ripple before and after adding a bypass cap, with the same
  digital stimulus — same code path, same capture, directly comparable
- PA keying sequence: D0=TXEN, D1=PA_ENABLE on digital; CH1=supply voltage, CH2=RF envelope
  on analog. Verify the enable sequence is correct and measure supply sag during TX

**What makes this different from two separate instruments:** causality. You can overlay the
digital state transitions directly on the analog voltage trace, identify which transition
causes which glitch, and measure the delay between cause and effect.

**Effort:** Very low for the capture — one `capture_audio()` and one `capture_all_digital()`
call, both post-processed on a shared time axis. The hard part is the visualization (overlay
bool lanes under the analog trace), but that's one matplotlib figure layout.

---

### ✓ 15. ✓ Clock Jitter and PLL Lock-Time Measurement — *rf-bench-clock-jitter*

**Clock jitter:**

Capture a digital clock on D0 at the maximum sample rate. Find all rising edges in the bool
array (`np.where(np.diff(samples.astype(int)) == 1)`). Compute cycle-to-cycle intervals:
`np.diff(edge_indices) / sample_rate_hz`. Plot a histogram — the spread is cycle-to-cycle jitter.

At 500 MSa/s, each sample is 2 ns. With sub-sample edge interpolation, timing resolution is
better than 1 sample. This is adequate for the 100 ps–10 ns jitter range that matters for
amateur synthesizer work (oscillator module comparison, TCXO qualification, crystal oscillator
startup characterization). Jitter directly maps to synthesizer phase noise.

**PLL lock time:**

- CH1 (analog): VCO tuning voltage
- D0 (digital): lock-detect output from the PLL IC (ADF435x, Si5351, etc.)
- D1 (digital): write-strobe or LE pulse to the PLL chip (trigger source)

Trigger on the D1 write strobe, capture the lock-detect assertion on D0 and the VCO tuning
transient on CH1. Result: lock time in microseconds and the full VCO tuning waveform. Directly
useful when designing frequency-agile synthesizers where lock time limits channel-change speed.

**Effort:** Low. The capture infrastructure is complete; edge-finding and jitter histogram is
~20 lines of numpy. The PLL lock-time measurement is a straightforward trigger + dual capture.

---

### ✓ 16. ✓ EMI Source Identification — *rf-bench-emi-finder*

When the SSA reveals an unexpected emission peak, identifying its source by probing wires one at
a time is tedious. The MSO systematizes it:

1. SSA sweep finds a peak at, say, 48 MHz.
2. Enumerate possible sources: 48/2=24 MHz, 48/3=16 MHz, 48/4=12 MHz, 48/6=8 MHz candidates.
3. MSO captures all candidate clock lines simultaneously on D0–D7.
4. Compute edge spacing for each channel → frequencies. If D3 is a 16 MHz TCXO, its 3rd
   harmonic lands at 48 MHz — likely culprit.
5. Confirm: suppress that clock (if possible) and re-run the SSA sweep. Peak drops → confirmed.

**Shielding and filtering verification:** capture an emission before and after adding a filter.
Keep the MSO capturing the digital source across both measurements. If the digital activity is
unchanged but the emission drops, the fix worked at the radiation path. If the digital activity
changes, the filter is distorting the signal — a different problem.

**Pre-compliance screening:** Run the SSA across 9 kHz–3.2 GHz while the MSO captures the
DUT's digital activity. Build a frequency → source mapping. Fix emissions at the source (add
ferrite on the clock line, reduce edge rate, add local bypassing) rather than applying broad
shielding to cover up root causes.

**Effort:** Medium. The SSA sweep and MSO capture scripts both exist. The correlation step
requires matching harmonic series to measured clock frequencies, which is non-trivial automation
but straightforward manual analysis.

---

### ✓ 17. ✓ PSRR / Voltage Regulator Noise Rejection — *rf-bench-psrr*

The scope AWG enables a measurement the SDG does not: PSRR with the scope as a fully
self-contained instrument (AWG output drives the DUT; CH1 and CH2 read the result).

**Setup:** Inject an AC test signal from the AWG onto a regulator's input rail via a small
coupling capacitor. CH1 monitors input ripple; CH2 monitors output ripple. Compute:

```
PSRR_dB(f) = 20 × log10(V_CH1_rms / V_CH2_rms)
```

Sweep the AWG from 100 Hz to 10 MHz (within the 25 MHz AWG limit). Most LDOs have poor PSRR
above 1 MHz, so the AWG's 25 MHz ceiling is not the limiting factor.

**Useful for:** verifying that an LDO meets its datasheet PSRR spec at the frequencies present
in a switching supply before committing it to a noise-sensitive application (VCO supply, ADC
reference rail, LNA bias). Comparing regulators — e.g., LP5907 vs. ADP150 vs. LT3045 — before
choosing one for a low-noise design.

**AWG synchronization advantage:** because the AWG is internal to the scope, the sweep
frequency is exactly the scope's reference frequency at each step, with no inter-instrument
sync overhead.

**Limitation:** The AWG output is not isolated from scope ground. Injecting onto the DUT's
supply rail requires an AC injection circuit (coupling cap + series inductance, or injection
transformer) to avoid ground loops and avoid back-driving the AWG's output stage with DC. This
is a standard test setup described in TI and Analog Devices application notes for PSRR testing;
it requires only passive components.

**Effort:** Low for the code. Moderate for the coupling fixture.

---

---

## New Project Ideas

---

### ✓ 18. Transmitter Test Suite (SSA + IC-7300 or FT-891 via rigctld)

The receiver test suite measures what the radio can hear; this measures what it transmits.
Uses rigctld to key the radio into transmit (CW carrier, single tone, or two-tone), then
measures the output with the SSA.

**Measurements:**

- **Power output vs. frequency:** Key the radio at each HF band segment, measure carrier power
  at the antenna port through a known attenuator. Plot watts/dBm vs. frequency. Reveals PA
  rolloff at band edges and inter-band variation.
- **ALC curve:** Sweep the microphone gain (or drive level for data modes) while measuring
  output power. Plot output power vs. drive level. Find the ALC knee — where the PA starts
  compressing — and confirm headroom.
- **Harmonic content:** At a fixed carrier frequency, set a wideband SSA span (e.g., 3–150 MHz)
  and measure the 2nd, 3rd, and 4th harmonic levels relative to the fundamental. Plot against
  the FCC Part 97 spurious emission limit: −43 dBc for radiated power ≤ 5 W, or −43 dBc /
  −60 dBW (whichever is stricter) above 5 W. Automated pass/fail against the mask.
- **Carrier suppression in SSB mode:** Set the radio to USB, apply no audio. Measure residual
  carrier at the suppressed carrier frequency. Values worse than −40 dBc warrant inspection.
- **IMD in SSB mode:** Inject a two-tone audio signal from the SDG into the radio's audio
  input. Measure the output on the SSA; compute TX IIP3 from the two tones and their IMD
  products. Directly comparable to the receiver's IIP3.

**Hardware:** The radio's antenna port is connected to the SSA RF input through a fixed
attenuator (at least 30 dB to protect the SSA; the same 30+20 dB chain from the receiver
test works). A directional coupler or calibrated T-attenuator is needed to route power to
both a dummy load and the SSA simultaneously.

**Why it matters:** Most amateurs transmit without ever measuring their output. A radio that
passes all receiver tests may still have excessive harmonic output, a sagging PA at band
edges, or poor ALC behavior. This closes the loop on transceiver testing.

**Effort:** Low–medium. Rigctld already drives both radios. SSA measurements are established
from the amplifier and scalar-vna projects.

---

### ✓ 19. Phase Noise Measurement (SDG + SSA zero-span)

Measures the close-in phase noise of any oscillator — crystal oscillator, TCXO, VCO,
Si5351, ADF4351, or any continuous-wave signal source. Produces a phase noise plot:
dBc/Hz vs. offset frequency from the carrier, typically from 10 Hz to 1 MHz offset.

**Technique:** The SSA's zero-span mode locks on a carrier and measures noise power spectral
density in a calibrated RBW at each frequency offset. Procedure:

1. Set the carrier to the center frequency.
2. For each offset point (e.g., 10 Hz, 30 Hz, 100 Hz, 300 Hz, 1 kHz, 3 kHz…1 MHz):
   - Set SSA to zero-span, center = carrier + offset, RBW = narrow
   - Measure average noise power in dBm
   - Convert to dBc/Hz: `L(f) = P_noise_dBm - P_carrier_dBm - 10·log10(RBW_hz)`
3. Plot L(f) vs. offset on a log-frequency axis.

**Noise floor limit:** The SSA's own noise figure sets the measurement floor. At 0 dBm
carrier and 1 kHz RBW, the SSA3032X Plus can measure phase noise down to approximately
−130 to −140 dBc/Hz at 10 kHz offset — adequate for most amateur oscillator work.

**Useful for:**
- Comparing bare crystal oscillators vs. TCXO modules before choosing one for a VFO
- Verifying that a PLL synthesizer (Si5351, ADF4351) meets phase noise expectations
- Characterizing the IC-7300's built-in oscillator
- Validating a homebrew OCXO or GPS-disciplined oscillator
- Finding oscillators that are "wobbly" under vibration or temperature before installing them

**Caveat:** Phase noise measurement requires a very stable carrier. Feeding the SDG1062X's
output directly into the SSA measures the SDG's own phase noise, which is a useful
self-characterization. For measuring other sources (VFOs, synthesizer boards), connect them
to the SSA RF input through the appropriate attenuator.

**Effort:** Low–medium. Zero-span SSA measurements are straightforward; the calibration math
is well-established. The main work is handling the SSA noise floor subtraction correctly.

---

### ✓ 20. Noise Figure Meter — Y-factor Method (noise source + SSA)

A proper noise figure measurement using the Y-factor technique. Noise figure (NF) is the
single most important parameter for LNA/preamp evaluation and receiver sensitivity prediction,
but NF analyzers cost $10K–$20K. This technique achieves useful results with the SSA and a
cheap noise source.

**What you need:** A noise source with a calibrated excess noise ratio (ENR). Options:
- Commercial: Noisecom NC346 series, HP 346B — $50–200 surplus
- DIY: avalanche noise diode (BFR93A or similar in breakdown) + a 15 dB attenuator gives a
  repeatable ~5–6 dB ENR — adequate for NF measurements to ±0.5–1 dB accuracy

**Technique (Y-factor):**

1. Connect noise source output → DUT (amplifier under test) → SSA RF input.
2. Measure SSA power with noise source **on** (hot): P_hot
3. Measure SSA power with noise source **off** (cold): P_cold
4. Y = P_hot / P_cold (linear ratio)
5. NF_DUT+SSA = ENR / (Y − 1) [linear] → convert to dB
6. Subtract SSA's own NF (measure with noise source directly → SSA, no DUT) to get DUT NF alone

**Sweep across frequency:** Step the noise source center frequency (if tunable) or measure
broadband noise vs. SSA center frequency at fixed RBW. The SSA's preamplifier option, if
enabled, reduces the cascaded noise floor and extends measurement range.

**Why it enables something new:** Without this, NF must be inferred from MDS measurements
(which are bandwidth- and filter-dependent) or from Friis calculations on individual stages.
Direct Y-factor measurement of a complete preamp board or LNA module gives absolute NF in
minutes. Indispensable for evaluating surplus LNAs, comparing home-wound inductors in
input matching networks, or verifying a receive antenna preamplifier before installation.

**Effort:** Medium. The math is simple; the hard part is accurately characterizing the noise
source ENR and accounting for the SSA's own NF in the de-embedding step.

---

### ✓ 21. Band Occupancy Monitor / Spectrum Waterfall (SSA, long-running)

Runs the SSA in a continuous sweep loop over a chosen band and logs peak power vs. frequency
vs. time. Produces a waterfall plot (time on Y-axis, frequency on X-axis, color = signal
level in dBm) that reveals band activity patterns impossible to see from any manual measurement.

**What it reveals:**
- Which frequencies within a band are consistently occupied vs. clear
- Propagation openings: a dead band that suddenly fills with signals
- Interference: a carrier that appears at the same frequency at the same time each day
- Self-interference: harmonics from switching supplies appearing at specific times
- Beacon monitoring: track whether a frequency standard beacon is audible

**Operation:** Sweep period is adjustable. For a 200 kHz HF band segment at 751 points,
one SSA sweep takes ~1–2 seconds; a 24-hour run produces ~40,000–80,000 sweeps. Log to
a compressed numpy .npz file or HDF5. Render waterfalls at any time from logged data.

**Multi-band mode:** Cycle through a list of bands (e.g., 40m → 20m → 17m → 15m) with a
configurable dwell time at each. Useful for propagation monitoring across multiple bands
overnight.

**Triggered capture:** If a threshold is exceeded at any frequency, capture a deep-memory
sweep with narrower span and save it. Combines passive monitoring with event-triggered
detail capture — the SSA becomes a spectrum recorder.

**Effort:** Low for basic waterfall logging; medium for triggered capture and multi-band
cycling.

---

### ✓ 22. Oscillator Stability / Allan Deviation (SSA zero-span or scope freq counter)

Measures the frequency stability of an oscillator over time and computes the Allan deviation
(ADEV) — the standard metric for characterizing oscillator noise types (white noise, flicker
noise, random walk, drift). A single ADEV curve tells you everything about an oscillator's
stability class.

**Technique:** At each measurement interval τ:
1. Measure carrier frequency (either SSA in zero-span centroid mode, or scope frequency
   counter on the analog channel)
2. Compute normalized frequency deviation: y_k = (f_k − f_nominal) / f_nominal
3. Allan deviation: σ_y(τ) = sqrt(½ · mean((y_{k+1} − y_k)²))
4. Plot σ_y vs. τ on log-log axes

Different slopes on the ADEV plot indicate different noise types:
- Slope −½: white phase noise (dominates at short τ)
- Slope 0: flicker phase noise
- Slope +½: white frequency noise (dominates at medium τ)
- Slope +1: flicker frequency (dominates at long τ — crystal aging)
- Slope +3/2: random walk (temperature drift, mechanical)

**Practical use:** Run overnight for a complete ADEV curve from τ = 1 s to τ = 10,000 s.
Compare a bare crystal oscillator (σ_y ~ 10⁻⁸ at τ=1s), a TCXO (~ 10⁻⁹), an OCXO (~ 10⁻¹⁰),
and a GPS-disciplined oscillator (~ 10⁻¹¹ at τ=1000s) — directly on the same plot.

**Application to ham radio:** Most ham equipment uses uncompensated crystals or PLLs with
poor close-in phase noise. Measuring ADEV lets you quantify "how stable is this VFO really"
before using it as a timing reference or frequency standard.

**Effort:** Low. The measurement loop is simple; ADEV computation is ~15 lines of numpy.
Long run-times (overnight) require careful file I/O to avoid losing data.

---

### ✓ 23. Matching Network Designer + Verifier (rf-impedance → Smith chart → verification)

Takes a measured complex impedance at a target frequency (from the rf-impedance tool) and
automatically computes the component values for optimal impedance matching networks. Then
optionally verifies the result by re-measuring after the network is built.

**Workflow:**

1. **Measure:** Run the rf-impedance tool at the target frequency (e.g., 14.2 MHz) to get
   Z_source and Z_load as complex numbers.
2. **Design:** For the desired transformation (e.g., 50 Ω source → 12 − j8 Ω load):
   - L-network (2 components): series-shunt or shunt-series topology; both solutions shown
   - π-network (3 components): adjustable Q; show solutions for Q = 2, 5, 10
   - T-network (3 components): same
   - Tapped-C / Colpitts (for oscillator coupling): compute capacitor ratio
3. **Display:** Smith chart plot showing the matching path; component values from each
   topology; nearest standard E24 values; predicted insertion loss and bandwidth.
4. **Verify:** After building the network, re-run rf-impedance at the same frequency and
   overlay the measured input impedance on the Smith chart. Shows how close the build
   came to the design target.

**Why this is new:** The engineer currently computes matching networks with a separate tool
(RFSim99, Qucs, Smith chart paper) and then builds and tests blind. This closes the loop:
measure → design → compute → build → verify, all from one script. The measurement step
removes guesswork about source/load impedance that often causes matching designs to fail
in practice.

**Useful for:** Antenna tuners, PA output networks, interstage matching in transverters,
low-noise amplifier input matches, loop antenna coupling.

**Effort:** Medium. The measurement part is done. The Smith chart geometry is well-defined.
The new work is the network synthesis equations and the matplotlib Smith chart visualization.

---

### ✓ 24. Varactor / Varicap Characterizer (SPD + SDG + scope)

Measures a varactor diode's capacitance vs. reverse bias voltage at operating RF frequencies —
not at the 1 kHz test frequency used by benchtop DMMs, where parasitic inductance is invisible.

**Why RF-frequency measurement matters:** A varactor's datasheet capacitance is specified at
low frequency. In a VFO at 14 MHz, the same varactor may look 20–30% different due to its
package inductance resonating with the junction capacitance. Measuring C vs. V_bias at the
actual operating frequency gives the correct design value.

**Technique:** Uses the rf-impedance series-injection circuit with SPD CH1 providing the
DC bias and a large-value RF choke (≥1 mH) isolating the bias supply from the RF path.

```
SDG ──→ 50 Ω ref resistor ──→ [RF bypass cap] ──→ Varactor anode
                                                       │
                                         [RF choke] ──→ SPD CH1 (bias)
Varactor cathode ──→ GND
```

At each bias voltage (stepped from 0.5 V to 15 V):
1. Set SPD CH1 to V_bias
2. Run rf-impedance measurement at the target frequency
3. Extract capacitance: C = −1 / (2π·f·Im(Z))
4. Record C and the series resistance R (dissipation factor D = ωRC)

**Output:** C vs. V_bias curve at the operating frequency. Tuning ratio. Series resistance
and Q factor vs. bias. Directly plugs into VFO design calculations.

**Also useful for:** Characterizing varactor-tuned filter banks, voltage-controlled
attenuators using PIN diodes (swap PIN for varactor in same fixture), and verifying that
a varactor matches its datasheet before committing it to a board.

**Effort:** Low. The rf-impedance measurement infrastructure is complete; this is a voltage
sweep wrapper around it.

---

### ✓ 25. SDG Self-Characterization (SDG + SSA)

Uses the SSA to measure the SDG1062X's own output — characterizing the signal source that
all other measurements depend on. Produces a set of correction tables and accuracy reports.

**Measurements:**

- **Level accuracy vs. frequency:** Set SDG to a fixed level (e.g., −10 dBm), sweep
  frequency from 100 kHz to 60 MHz in steps. Measure actual output with SSA at each point.
  Plot "set level − measured level" to reveal flatness error. Correct all future measurements
  using this table.
- **Level accuracy vs. set level:** At a fixed frequency (e.g., 10 MHz), sweep set level
  from −50 dBm to +10 dBm. Measure with SSA. Find where the SDG's output becomes nonlinear
  or deviates from the ideal. There is a known discrepancy between the SDG's reported output
  and what instruments measure; this quantifies it.
- **Harmonic content:** At each test frequency and level, measure the 2nd and 3rd harmonic
  relative to the fundamental. High harmonics at high output levels limit how the SDG can
  be used (e.g., for IP3 testing where spectral purity of the source matters).
- **Output impedance verification:** The SDG is specified at 50 Ω. A real mismatch shifts
  the level seen by a 50 Ω load. Verify using the scalar-vna reflection measurement.
- **Two-channel level tracking:** When both channels are used simultaneously (two-tone IMD),
  verify that CH1 and CH2 levels track within ±0.5 dB across the frequency range. Level
  imbalance between tones introduces a systematic error in IP3 calculations.

**Why this matters:** Every measurement project in this suite uses the SDG as its calibrated
signal source. Level errors in the SDG propagate into every downstream measurement: MDS,
IP3, gain, NF. Running this characterization once and storing the correction table improves
the accuracy of all other projects by 1–3 dB.

**Effort:** Very low. The SSA sweep infrastructure is established. This is primarily an
automation of measurements an engineer would already do manually when setting up a test bench.

---

---

## Bus Pirate Ideas

The Bus Pirate's unique value in this suite is **active protocol master**: the MSO (rf-bench-protocol-analyzer) can passively decode SPI/I2C/UART traffic, but cannot initiate transactions. The Bus Pirate can drive a bus — write registers, step through configurations, read back responses — which enables a whole class of "program it, then measure it" tests with the SSA or scope.

The other genuinely new capability the Bus Pirate brings is **I2C temperature sensing**: none of the Siglent instruments can read a digital thermometer IC. A $3 MCP9808 on the Bus Pirate I2C bus enables oscillator temperature-coefficient measurements that were previously impossible without external MCU hardware.

**Bus Pirate ↔ MSO substitution note:** For basic protocol decode of slow or static buses (I2C register dumps, UART debug output, SPI configuration writes), the Bus Pirate in sniffer/monitor mode is a viable alternative to the MSO digital pod. The tradeoff:
- **MSO pod:** synchronized with analog channels, high sample rate, hardware-correlated timestamps, full 16-channel parallel capture. Requires the MSO probe pod (~$200+).
- **Bus Pirate:** free, no extra hardware. No analog correlation, bandwidth limited to a few MHz, no shared timebase with the scope. Adequate for slow or configuration-only buses.

Where both are available, the ideal combination is **Bus Pirate as active driver + MSO as passive verifier** — the Bus Pirate generates known SPI transactions while the MSO captures them with analog context (clock edge quality, supply noise during writes, MISO response timing).

---

### ✓ 34. Bus Pirate Driver — *rf-bench-drivers-buspirate*

Prerequisite for all other Bus Pirate projects. A new `rf_bench.buspirate.BusPirate` driver
following the same pattern as the Siglent and radio drivers: serial port (pyserial), connection
pooling, context manager support.

**Interface:** The Bus Pirate communicates over USB CDC as a serial port (`/dev/ttyUSBx`).
Versions v3/v4 use a text-based interactive mode plus a binary mode (mode `0x00` = binary SPI,
`0x01` = binary I2C, etc.). v5 uses a different protocol entirely. The driver should detect
version at connect time and raise a clear error if v5 is connected.

**API to expose:**

```python
from rf_bench.buspirate import BusPirate

bp = BusPirate("/dev/ttyUSB1")
bp.identify()                                   # → version string (e.g. "Bus Pirate v3.6")

# SPI master
bp.spi_configure(speed_hz=1_000_000, cpol=0, cpha=0, cs_active_low=True)
bp.spi_transfer([0x40, 0x00, 0x00])            # → list of rx bytes (same length)
bp.spi_write([0x40, 0x00, 0x00])               # transfer + discard rx

# I2C master
bp.i2c_configure(speed_hz=100_000)
bp.i2c_write(addr=0x48, data=[0x01, 0x60, 0x00])  # write register
bp.i2c_read(addr=0x48, reg=0x00, length=2)         # → bytes

# UART passthrough
bp.uart_configure(baud=9600, data_bits=8, parity='N', stop_bits=1)
bp.uart_write(b"AT\r\n")
bp.uart_read(length=16, timeout_s=1.0)

# GPIO and power
bp.set_power(True)    # enable on-board 3.3V/5V supply pins
bp.set_pullups(True)  # enable on-board I2C pull-ups
bp.close()
```

**pyserial dependency:** already in requirements on this machine. No new system packages
needed.

**Effort:** Medium. Binary mode protocol is documented in the Bus Pirate wiki; the edge cases
are around version detection, escape sequences, and the binary mode entry/exit handshake.

---

### ✓ 35. Synthesizer Characterizer — *rf-bench-synthesizer-characterizer*

Programs a PLL synthesizer chip via Bus Pirate, measures the actual RF output with the SSA.
Produces a complete performance map for the chip — what it actually does vs. what the datasheet
claims. Directly useful for every ham radio project that uses a synthesizer module.

**Target chips:**
- **Si5351A** (I2C, 8 kHz–200 MHz, 3 outputs): used in BPF filter boards, uSDX, WSPR beacons,
  Arduino synthesizer shields. Programmed via `CLK0_CTRL`, `PLL_A_*`, `MS0_*` registers.
- **ADF4351** (SPI, 35 MHz–4.4 GHz, integer/fractional-N): used in SDR LO modules, frequency
  counter input converters, signal generators.
- **Si5153 / Si5156** (I2C): similar to Si5351, different register map.

**Measurements at each programmed frequency:**

1. **Frequency accuracy:** SSA measures actual carrier; compare to programmed value.
   Plot error in ppm vs. frequency. Reveals systematic offsets from crystal reference error
   and fractional-N spurs at certain frequency ratios.
2. **Output power:** Track generator output or SSA marker amplitude. Reveals power droop at
   band edges (Si5351 rolls off above ~150 MHz; ADF4351 has bands with different output levels).
3. **Harmonic content:** SSA wideband sweep after each frequency set. `2nd_harmonic_dBc` and
   `3rd_harmonic_dBc` at each frequency. Si5351 harmonics are often −10 to −30 dBc; mapping
   which frequencies are worst guides filter placement decisions.
4. **Fractional-N spurs (ADF4351):** Narrow-span sweep around the carrier. Spurious products
   at `±f_ref/MOD` offsets reveal the worst fractional denominator values to avoid.

**Bus Pirate role:** Programs the chip register sequence for each test frequency. This is
the step that previously required an Arduino or Raspberry Pi — now it's one Python call to
`bp.i2c_write()` or `bp.spi_transfer()`.

**MSO integration (optional):** If the MSO pod is available, capture the SPI/I2C configuration
write on the digital channels while the SSA measures the output. Confirms the chip actually
received the correct register values when a result looks anomalous.

**Output:** JSON calibration table (frequency → actual Hz, power dBm, harmonics dBc) for
use by other bench scripts. Matplotlib multi-panel plot.

**Effort:** Medium. Si5351 register math (PLL multiplier, multisynth divider) is well-documented
in the AN619 application note and multiple open-source libraries. ADF4351 is simpler (single
integer + fractional word).

---

### ✓ 36. DDS Characterizer — *rf-bench-dds-characterizer*

Similar in structure to the synthesizer characterizer but for direct digital synthesis (DDS)
chips. DDS performance is fundamentally different from PLL: instead of phase-locked spurs,
the dominant artifact is **DAC spurious free dynamic range (SFDR)** — quantization aliases
that land at predictable offsets determined by the tuning word / 2^N ratio.

**Target chips:**
- **AD9833** (SPI, 0–12.5 MHz sine/triangle/square): the most common simple DDS module; used
  in signal generators, audio synthesizers, function generator add-ons.
- **AD9851** (SPI, 0–~70 MHz): same DDS core with 6× multiplier and comparator output; used
  in CW keyers and VFO boards.
- **AD9850** (parallel or SPI, 0–~40 MHz): predecessor to AD9851; widely available on eBay.

**Measurements at each tuning word:**

1. **Frequency accuracy:** SSA carrier frequency vs. computed output frequency. DDS frequency
   error tracks the reference oscillator exactly (no PLL divider artifacts) — measuring accuracy
   across the full range verifies the reference crystal's actual frequency.
2. **Spurious products (SFDR):** SSA wide span around the carrier. Spurious products appear
   at `|k·f_clock − m·f_out|` for small integer k, m. SFDR is worst when `f_out / f_clock`
   is a simple rational fraction (e.g., 1/2, 1/3). Map SFDR vs. tuning word — find the
   "clean" regions and the "dirty" ones.
3. **Harmonic content:** DDS chips produce harmonics because the output DAC is not a perfect
   sine; measure 2nd and 3rd harmonic relative to carrier.
4. **Output amplitude vs. frequency:** DDS DAC output rolls off above ~40% of the clock rate
   (sinc rolloff). Measure actual amplitude at each frequency; correction factor for other
   test measurements.
5. **Clock multiplier verification (AD9851):** Program the 6× multiplier on/off; verify
   that the output frequency shifts correctly and spurs change character.

**Bus Pirate role:** Writes the 40-bit (AD9851) or 28-bit (AD9833) frequency tuning word
via SPI at each frequency step.

**Why this complements the synthesizer characterizer:** DDS and PLL have fundamentally
different spur characters. A radio design might use a DDS for fine tuning and a PLL for the
VFO LO; knowing which frequency combinations put a spur in-band requires characterizing both
chip types independently.

**Effort:** Low. The SPI register write sequence for these chips is well-established; the
SSA sweep infrastructure exists.

---

### ✓ 37. Oscillator Temperature Coefficient — *rf-bench-osc-tc*

Measures the frequency vs. temperature characteristic of any free-running oscillator —
crystal, TCXO, VCTCXO, OCXO, or ceramic resonator. Produces a TC curve in ppm/°C and
optionally fits a polynomial model for temperature compensation.

**This project requires the Bus Pirate.** None of the Siglent instruments can read a
digital thermometer IC. A Bus Pirate + $3 I2C temperature sensor (MCP9808, LM75, or BMP280)
is the only combination in this inventory that can log temperature simultaneously with
frequency.

**Temperature sensor options:**
- **MCP9808** (Microchip, I2C 0x18–0x1F): ±0.0625°C resolution, ±0.5°C accuracy, 400 kHz
  I2C, 3.3V. Best all-around choice.
- **LM75** (TI, I2C 0x48–0x4F): ±0.5°C accuracy, 0.5°C resolution. Simpler; widely cloned.
- **BMP280** (Bosch, I2C or SPI): ±0.5°C accuracy; also gives barometric pressure if useful.

**Measurement loop:**

```
while running:
    temp_c = bp.i2c_read(mcp9808_addr, ...)       # read temperature
    freq_hz = ssa.measure_carrier_centroid()        # zero-span centroid measurement
    log(timestamp, temp_c, freq_hz)
    sleep(interval_s)
```

**Thermal stimulus options:**
- **Passive overnight soak:** Lab temperature swings naturally 5–10°C; adequate for gross TC
  characterization of bare crystals.
- **Heat gun / cold spray:** Apply thermal stimulus while the loop runs. Fast temperature
  sweeps reveal hysteresis — if the frequency curve on heat-up differs from cool-down, the
  oscillator has memory effects.
- **Oven (advanced):** Place DUT in a temperature-controlled enclosure. Enables precise TC
  vs. T characterization from −20°C to +70°C.

**Output:**
- Plot: frequency deviation (ppm) vs. temperature (°C)
- Linear regression → TC in ppm/°C
- Optional polynomial fit (3rd-order for AT-cut crystals, which have the classic "S-curve")
- Hysteresis: overlay heat and cool curves; quantify the area between them

**Typical results:**
- Bare HC-49 crystal: TC ≈ ±2–5 ppm/°C; S-curve turning point typically at 25–50°C
- TCXO module: TC < ±0.5 ppm/°C (that's the whole point)
- OCXO: TC < ±0.01 ppm/°C above warmup (measures oven setpoint drift instead)

**Application:** Before using a crystal as a frequency reference or beacon source, characterize
its TC. If a 14.0 MHz VFO drifts 100 Hz over a 10°C temperature swing in a warm shack,
measuring the TC identifies whether a TCXO upgrade is warranted.

**Effort:** Low. The measurement loop is simple; temperature sensor I2C reads are standard.
The interesting work is the polynomial fit and hysteresis quantification.

---

### ✓ 38. Digital Step Attenuator Calibration — *rf-bench-dig-atten-cal*

Maps every attenuation code of a digitally-controlled step attenuator to its actual attenuation
at multiple frequencies, producing a correction table for use in all other bench projects.

**Why this matters:** Every test in this suite that cares about absolute power levels (MDS,
IP3, NF, gain) either needs a calibrated attenuator in the signal path or must account for
attenuator error. A nominally "6 dB" step on a PE43602 may be 5.8 dB at 7 MHz and 6.4 dB
at 30 MHz. Without a calibration table, every downstream measurement inherits that error.

**Target chips (all SPI-controlled):**
- **PE43602** (64-state, 0–31.5 dB in 0.5 dB steps, DC–4 GHz): common in SDR front-ends
  and attenuator modules.
- **HMC307** (8-state, 0–31 dB in 1 dB steps): older part, still widely found on eBay boards.
- **RFSA3013** (64-state, 0–31.5 dB): similar to PE43602.
- **F1958 / F1960** family: used in commercial attenuator modules.

**Measurement:**

```
for code in range(64):          # all 64 states
    bp.spi_write(atten_word(code))              # set attenuator
    for freq in test_frequencies:
        ssa.set_center(freq)
        ssa.single_sweep()
        actual_atten_db[code][freq] = reference_level - ssa.peak_marker_dbm()
```

Reference level is set with attenuator at code 0 (minimum attenuation). The difference
between code 0 and each subsequent code is the actual incremental attenuation.

**Frequency sweep:** 1 MHz, 3 MHz, 7 MHz, 14 MHz, 21 MHz, 28 MHz, 50 MHz, 100 MHz, 500 MHz,
1 GHz, 2 GHz (as appropriate to the attenuator's specified frequency range).

**Output:**
- JSON calibration table: `atten_cal[code][freq_hz] = actual_atten_db` — loaded by other
  bench scripts to compute corrected signal levels.
- Deviation plot: nominal vs. actual for each code, overlaid across all frequencies. Reveals
  code errors (missing bits), temperature hysteresis, and frequency-dependent insertion loss.
- Pass/fail: flag any code where actual ≠ nominal by more than a set tolerance (e.g., ±0.5 dB).

**Bus Pirate role:** Sets the SPI attenuation word at each step. The attenuator's 3.3V SPI
interface is compatible with Bus Pirate v3 default I/O levels.

**Alternative without a digital attenuator:** If no programmable attenuator is available,
a fixed precision attenuator (e.g., a calibrated SMA barrel attenuator with verified ±0.1 dB
accuracy) can anchor the absolute level in the existing calibration project instead. But once
a programmable attenuator is in the signal chain (which all serious bench setups eventually
acquire), this calibration run is mandatory.

**Effort:** Very low. SPI write sequences for these chips are simple; the SSA sweep loop
is already established.

---

---

## Flipper Zero Ideas

The Flipper Zero's unique contribution to this bench is **Sub-GHz coverage**: it houses a Texas Instruments CC1101 chip covering 300–928 MHz in three bands (300–348, 387–464, 779–928 MHz) with OOK, 2-FSK, 4-FSK, GFSK, and MSK modulation. This fills the critical gap between the SDG's 60 MHz ceiling and the SSA's 3.2 GHz measurement range — the bench currently has no independent signal source in the ISM bands (315, 433, 868, 915 MHz). The Flipper also adds 125 kHz LF RFID and 13.56 MHz NFC, neither of which appear anywhere else in the inventory.

USB control uses the Flipper's protobuf RPC interface over a CDC ACM serial port (`/dev/ttyACM0`). The `flipperzero-protobuf` package on PyPI provides generated Python protobuf bindings. The key RPC calls for bench work are `SubGhzStartTransmitCarrier` (continuous unmodulated carrier — directly measurable by SSA), `SubGhzGetRSSI` (receiver signal strength), and `SubGhzStartTx`/`SubGhzStartRx` for modulated operation.

The same driver/application pattern used by the Bus Pirate projects applies here: driver (#39) is the prerequisite; applications (#40–49) cover bench-integrated measurements; applications (#50–56) are standalone tools that require nothing beyond the Flipper and a computer.

---

### ✓ 39. Flipper Zero Driver — *rf-bench-drivers-flipper*

Prerequisite for all other Flipper projects. A `rf_bench.flipper.FlipperZero` driver following the same pattern as `rf_bench.buspirate.BusPirate`: serial port (pyserial to `/dev/ttyACM0`), context manager support, clean Python API.

**API to expose:**

```python
from rf_bench.flipper import FlipperZero

fz = FlipperZero("/dev/ttyACM0")
fz.identify()                                           # → firmware version string

# Sub-GHz (CC1101)
fz.subghz_tx_carrier(freq_hz=433_920_000, power_idx=4)  # CW carrier for SSA measurement (power_idx 0–7)
fz.subghz_stop()
fz.subghz_rx(freq_hz=433_920_000, modulation="OOK_650") # start RX
rssi_dbm = fz.subghz_get_rssi()                         # read RSSI register → dBm (uncalibrated)

# LF RFID (125 kHz)
fz.lfrfid_read(timeout_s=5.0)                           # → decoded card dict or None
fz.lfrfid_emulate(card_type, card_data)

# NFC (13.56 MHz)
fz.nfc_read(timeout_s=5.0)                              # → ISO 14443A card data dict

# GPIO
fz.gpio_set_mode(pin, "output")
fz.gpio_write(pin, value)
fz.gpio_read(pin)

fz.close()
```

**Protobuf RPC:** The Flipper Zero exposes binary protobuf framing over the USB CDC ACM port. The driver handles the 4-byte length-prefixed framing and wraps it into the clean Python API above. v1 scope: Sub-GHz CW carrier TX, Sub-GHz RX + RSSI, LF RFID read, NFC read. GPIO and raw Sub-GHz file replay can be added later.

**`pyserial` dependency:** already installed. `flipperzero-protobuf` pip package needed for the generated protobuf classes.

**Effort:** Medium. The protobuf framing and RPC call/response pairing are the bulk of the work. The Flipper Zero community has well-documented examples.

---

### ✓ 40. CC1101 Synthesizer and Transmitter Characterizer — *rf-bench-flipper-cc1101*

Programs the Flipper's CC1101 to transmit a CW carrier at programmed Sub-GHz frequencies and measures actual RF output on the SSA. This is the Sub-GHz counterpart to the Si5351/ADF4351 synthesizer characterizer (#35) and fills the most important gap in the current bench: **there is no independent signal source between 60 MHz (SDG ceiling) and 3.2 GHz (SSA input range)**. The Flipper in carrier-transmit mode becomes that source.

**Measurements at each programmed frequency across 315, 433, 868, and 915 MHz:**

1. **Frequency accuracy (ppm):** Command `subghz_tx_carrier(freq_hz)`, read SSA peak frequency. The CC1101's synthesizer references a 26 MHz crystal; uncompensated accuracy is typically ±10–50 ppm. Plot error vs. frequency.

2. **Output power vs. PATABLE setting:** The CC1101 has 8 programmable TX power levels (indices 0–7, ≈ −30 to +10 dBm, band-dependent). At each power index and each test frequency, read SSA peak level in dBm. Produce a `power_idx → actual_dBm` calibration table per band. This table is the prerequisite for using the Flipper as a calibrated Sub-GHz signal source in any downstream project.

3. **Harmonic content:** After each carrier set, SSA wideband sweep to 2 GHz. Measure 2nd and 3rd harmonics relative to fundamental. CC1101 harmonics are typically −20 to −35 dBc without an output low-pass filter; mapping the worst-case frequencies guides filter placement decisions.

4. **Frequency coverage and dead-band verification:** The CC1101 has three tuning bands with gaps at 348–387 MHz and 464–779 MHz. Sweep the programmed range across all three bands; confirm the SSA sees no output in the dead zones.

5. **Adjacent-channel power (ACPR, extension):** For modulated TX, measure power in ±100 kHz adjacent channels relative to the intended channel bandwidth.

**Output:** JSON calibration table `flipper_cal[freq_hz][power_idx] = actual_dbm`; harmonic content table; matplotlib multi-panel plots of frequency error (ppm), power accuracy, and harmonic content vs. frequency.

**Effort:** Low once the driver is working. SSA sweep infrastructure is established; the measurement loop follows the same pattern as the Bus Pirate synthesizer characterizer.

---

### ✓ 41. Sub-GHz Receiver Sensitivity Test — *rf-bench-flipper-subghz-sensitivity*

Maps the Flipper Zero's CC1101 receiver: minimum detectable signal (MDS), RSSI calibration, and sensitivity vs. frequency across the ISM bands. Directly analogous to the IC-7300/FT-891 receiver sensitivity test in the completed suite, but for Sub-GHz receivers.

**Signal source:** The SSA's tracking generator (TG Out), stepped across Sub-GHz frequencies via SCPI, through a calibrated attenuator chain (30 dB + 20 dB from the existing receiver test bench). The TG covers 9 kHz–3.2 GHz and cleanly covers all CC1101 bands. Output level is set via `SSA.set_tracking_gen_level(dbm)`.

**Test loop:**

```python
for freq_hz in [315e6, 433.92e6, 868e6, 915e6]:
    fz.subghz_rx(freq_hz, modulation="OOK_650")
    ssa.set_center(freq_hz)
    ssa.set_tracking_gen(on=True)
    for level_dbm in range(-20, -125, -5):
        ssa.set_tracking_gen_level(level_dbm)
        time.sleep(0.1)
        rssi_dbm = fz.subghz_get_rssi()
        log(freq_hz, level_dbm, rssi_dbm)
```

**What this measures:**

- **RSSI calibration:** Plot `rssi_register_dbm` vs. `actual_input_dbm` at each frequency. The CC1101 RSSI is notoriously inaccurate out of the box (up to ±6 dB at some frequencies). The resulting correction table enables accurate received power estimation in other Flipper projects.
- **Minimum detectable signal (MDS):** The input level at which RSSI bottoms out and no longer tracks the source — effectively the receiver noise floor. Compare against CC1101 datasheet: ≈ −116 dBm at 2.4 kBaud OOK, ≈ −110 dBm at 2.4 kBaud FSK.
- **Sensitivity vs. frequency:** CC1101 LNA gain and noise figure vary across its three bands. Map how sensitivity changes across 315 vs. 433 vs. 868 vs. 915 MHz.
- **Blocking dynamic range (extension):** With a strong off-channel interferer from the SSA TG, monitor whether RSSI for the desired channel degrades. Characterizes the CC1101's blocking performance.

**Output:** RSSI correction table per frequency (loaded by other Flipper projects); sensitivity vs. frequency plot; comparison against CC1101 datasheet values.

**Effort:** Low. SSA tracking generator and SCPI level control are established. The test loop is the same structure as the HF receiver sensitivity test.

---

### ✓ 42. ISM Signal Decoder + Spectral Annotation — *rf-bench-flipper-subghz-decode*

Captures real-world ISM-band transmissions — garage door openers, weather stations, tire pressure sensors, car key fobs, 433 MHz sensor nodes — with the Flipper Zero's protocol decoder while the SSA simultaneously characterizes the RF properties of each captured burst. Produces a paired report linking protocol identity to measured RF quality.

**The gap this fills:** The Flipper Zero is excellent at protocol decode but tells you nothing about RF quality. The SSA is excellent at RF measurement but is protocol-agnostic. Combining them answers: "This signal is a CAME protocol remote at 433.92 MHz — and it is 18 kHz off-frequency, with 46 kHz OOK bandwidth and a −28 dBc 2nd harmonic."

**Workflow:**

1. Flipper listens on the target ISM frequency in Sub-GHz RX mode.
2. SSA monitors the same frequency in zero-span peak-hold mode, watching for energy bursts above a threshold.
3. When the Flipper decodes a packet, it reports: protocol name, decoded data payload, RSSI.
4. SSA is then commanded to execute a fast narrow-span sweep (±200 kHz) to measure peak frequency (→ frequency error in ppm), −6 dB and −20 dB occupied bandwidth, and peak power. A subsequent wideband sweep measures harmonics.
5. Both datasets are logged together: `{protocol, data, rssi_dbm, actual_freq_hz, freq_error_ppm, bw_6dB_hz, harmonics_dbm}`.

**Practical applications:**
- Identify ISM transmitters in the local RF environment causing interference, and characterize their RF quality
- Pre-compliance screening of homebrew ISM devices (APRS trackers, sensor nodes) — verify frequency tolerance and bandwidth before regulatory submission
- Map the ISM environment before deploying a new Sub-GHz link (which frequencies are busy, what power levels are present)
- Identify poorly-built commercial ISM products with excessive harmonics or out-of-tolerance frequencies

**Timing note:** ISM transmissions are typically 10–100 ms bursts. The SSA must be pre-armed in max-hold mode rather than triggered post-burst; the Flipper decode event provides the confirmation that a capture is valid.

**Effort:** Medium. The coordination between Flipper decode events and SSA capture requires careful event sequencing, but both instruments are already well-characterized. The trickiest part is the timing architecture.

---

### ✓ 43. RFID / NFC Field Characterizer — *rf-bench-flipper-rfid-field*

When the Flipper Zero emits its LF RFID reader field (125 kHz) or NFC field (13.56 MHz), the SSA can measure the field via a small coupling loop at the bench. This characterizes the Flipper's own RFID output and enables comparison of third-party RFID readers.

**Required hardware:** A small coupling loop (10–15 turns of wire on a 3 cm form, SMA connector). Cost: ~$2 in parts.

**125 kHz LF RFID:**

- **Frequency accuracy:** Flipper in RFID read mode (continuous 125 kHz carrier), SSA zero-span centroid at 1 Hz RBW. Is it actually 125.000 kHz? The LF oscillator is ±0.1% tolerance; direct measurement confirms it. Resolution far exceeds any frequency counter in the bench.
- **Harmonic content:** SSA sweep 100 kHz–2 MHz. The 3rd harmonic at 375 kHz and 5th at 625 kHz are typical from a square-wave-driven RFID coil. Plot the harmonic ladder; note that FCC Part 15.231 limits harmonics outside the 125 kHz band.
- **Load modulation sidebands:** When the Flipper reads an EM4100 card, the card load-modulates the 125 kHz carrier at its data rate (typically 4 kBaud biphase, producing sidebands at 125 kHz ± 4 kHz). SSA narrow-span around 125 kHz in AM demod mode reveals the sidebands and modulation depth.
- **Field strength vs. distance:** Log SSA peak level as the coupling loop is moved away from the Flipper antenna in 1 cm steps. Maps the near-field gradient and estimates reliable read range.

**13.56 MHz NFC:**

Same measurements at 13.56 MHz. ISO 14443A load modulation uses an 847.5 kHz subcarrier; SSA narrow-span around 13.56 MHz shows sidebands at 13.56 MHz ± 847.5 kHz when a card is present, confirming correct NFC modulation.

**Useful for:**
- Verifying the Flipper's RFID hardware is functioning correctly after firmware updates
- Characterizing third-party RFID reader modules (e.g., RDM6300 125 kHz readers driven via Bus Pirate UART) against a known reference
- Measuring antenna coupling between two RFID coils: place one on the Flipper, one on a DUT, measure power transfer vs. distance and orientation — useful for designing RFID reader antennas
- Pre-compliance screening of a custom RFID or NFC reader design for harmonic content at 13.56 MHz

**Effort:** Very low. All SSA measurements are straightforward; no new SCPI patterns needed. The entire project is ~100 lines of Python plus the coupling loop fixture.

---

### ✓ 44. IR Remote Code Library Builder — *rf-bench-flipper-ir-library*

Interactive Python CLI that systematically captures IR codes from all your remotes and builds a searchable, exportable database. The Flipper's interactive UI is tedious for bulk capture — you name each file manually, navigate menus, one remote at a time. This replaces that with a structured capture session driven from the terminal.

**Workflow:**

```
$ ir-library capture --device "Samsung TV" --remote "Samsung BN59-01315A"
  → Waiting for IR signal... [point remote at Flipper and press a button]
  → Decoded: NEC protocol, address 0x07, command 0x02 → label this button: power
  → Waiting... → label: vol_up
  → Waiting... → label: vol_down
  ...
  → Saved 32 buttons to library.json
```

For each captured code the script records: decoded protocol + address + command (if standard) or raw timings (if non-standard), button label, device, remote model, and timestamp.

**Exports:**
- **Flipper `.ir` format:** drop directly onto the Flipper SD card for interactive use
- **LIRC format:** `lircd.conf` for use with LIRC on Linux, Home Assistant, etc.
- **Pronto hex:** vendor-neutral hex encoding accepted by Logitech Harmony, Broadlink, and most professional remotes
- **JSON:** for home automation scripts, Node-RED, etc.
- **Home Assistant `scripts.yaml`:** ready to paste into HA with a `remote.send_command` action per button

**Additional features:**
- `ir-library search --protocol NEC --address 0x07`: find all stored codes matching a filter
- `ir-library replay --device "Samsung TV" --button power`: replay a stored code from the library
- `ir-library import /path/to/Flipper/SD/infrared/`: bulk-import existing Flipper IR files into the database

**Why this is useful over just using the Flipper directly:** The Flipper stores IR as flat `.ir` files with no cross-device search, no export to other formats, and no integration with home automation systems. This turns your Flipper into a proper IR code repository.

**Effort:** Low. Flipper IR RPC calls are `InfraredReadOnce` and `InfraredTransmitMessage`. The protocol conversion (NEC/SIRC/RC5 → LIRC/Pronto) is well-documented and has reference implementations.

---

### ✓ 45. IR Device Code Discovery — *rf-bench-flipper-ir-discover*

Systematically transmits all possible command codes for a given protocol and device address, watching for a response. Useful for finding undocumented codes: factory service menus, test modes, reset functions, and hidden features that manufacturers don't publish. For use on your own devices.

**How it works:**

Most IR protocols encode a device address (selects which device type responds) and a command byte (0–255). For a given protocol and known device address, brute-forcing all 256 command codes takes under 30 seconds. Many devices respond visibly to undocumented codes — LEDs flash, displays show test patterns, hidden menus appear.

```python
for command in range(256):
    fz.ir_transmit(protocol="NEC", address=device_address, command=command)
    time.sleep(0.08)          # inter-code gap
    print(f"  sent command 0x{command:02X}")
    # user watches device and presses Enter to flag interesting responses
```

**Interactive flagging mode:** Script pauses on user input. When a device does something unexpected, the user presses a key; the script logs that command as interesting and continues. At the end, prints a summary of all flagged codes with their hex values.

**Supported protocols:** NEC (most common: LG, Pioneer, some Samsung), SIRC (Sony — 12/15/20 bit variants), RC5/RC6 (Philips, Marantz, older devices), Samsung32. The script selects the protocol and steps through address ranges too if the device address is unknown.

**Example use cases:**
- Find your TV's factory service/alignment menu (almost every TV has one, not in the manual)
- Find a projector's test pattern mode or lamp reset code
- Find an amplifier's direct input select codes (many receivers have codes for "input 7" that aren't on the shipped remote)
- Find a universal remote's learning mode or factory reset

**Effort:** Very low. `InfraredTransmitMessage` in a loop with a configurable inter-code delay.

---

### ✓ 46. IR Universal Remote HTTP Daemon — *rf-bench-flipper-ir-daemon*

A small HTTP server that exposes IR transmission as a REST API. Any script, cron job, or home automation system that can make an HTTP call can now trigger IR commands via the Flipper.

```
POST /ir/send
{
  "protocol": "NEC",
  "address": "0x07",
  "command": "0x02"
}

POST /ir/replay
{
  "device": "Samsung TV",
  "button": "power"
}

POST /ir/raw
{
  "frequency": 38000,
  "duty_cycle": 33,
  "timings": [9000, 4500, 560, 560, 560, 1690, ...]
}

GET /ir/receive?timeout=5
→ {"protocol": "NEC", "address": "0x04", "command": "0x08", "raw": [...]}
```

**Integration points:**
- Home Assistant: call as a `rest_command` service — no plugin, no special integration, works with any HA version
- Cron job: `curl -s -X POST localhost:8099/ir/replay -d '{"device":"TV","button":"power"}'` to turn off the TV at midnight
- CLI alias: `alias tv-off='curl -s -X POST localhost:8099/ir/replay ...'`
- Shell scripts in other rf-bench projects that need to control IR-equipped equipment (signal generators, test fixtures with remote control)

**Implementation:** ~80 lines of Python using `http.server` (stdlib, no dependencies) + the Flipper driver from project #39. Runs as a systemd user service or just in a terminal.

**Effort:** Very low. Thin HTTP wrapper around two driver calls. The library from project #44 provides the replay-by-name lookup.

---

### ✓ 48. IR Transmitter Waveform Characterizer — *rf-bench-flipper-ir-waveform*

Captures the Flipper Zero's IR LED output on the scope via a cheap Si photodiode and characterizes the transmitter: carrier frequency accuracy, duty cycle, modulation timing. **Hardware required:** one Si photodiode (BPW34 or TEPT4400, ~$2) and a 1 kΩ load resistor — the scope's 1 MΩ input sees the resulting voltage directly.

**Why bother:** Nearly every IR remote protocol spec has tight timing tolerances. NEC protocol bit periods are 562.5 µs nominal; timing errors beyond ±10% cause missed decodes on strict receivers. The Flipper's IR transmitter is driven by a microcontroller PWM peripheral — it may be accurate, or it may have systematic timing offsets that cause compatibility problems with some TVs. This measures it precisely.

**Measurements:**

1. **Carrier frequency accuracy:** Flipper transmits a continuous IR carrier (settable in raw IR mode). Scope captures via photodiode; FFT of the captured waveform gives the actual carrier frequency. Standard is 38 kHz for most protocols, but Sony SIRC uses 40 kHz, Philips RC5/RC6 use 36 kHz. Is the Flipper's carrier where it claims to be? `scope.fft_peak()` at microsecond time resolution resolves this to well under 10 Hz.

2. **Duty cycle:** At the same capture, measure the on-time vs. period. Standard IR carrier duty cycle is 1/3 (33%) for battery life — an LED driven at 50% wastes power; at 25% it's weaker than necessary. The actual duty cycle reveals firmware PWM configuration choices.

3. **Modulation envelope timing:** Flipper transmits a known protocol (e.g., NEC). Scope captures the full message (~67 ms for NEC). Python decodes the envelope: measure each burst duration and inter-burst gap with sub-microsecond precision. Compare against protocol spec:
   - NEC: leader burst 9 ms, gap 4.5 ms, bit burst 562.5 µs, 0-bit gap 562.5 µs, 1-bit gap 1.6875 ms
   - Plot measured vs. nominal; quantify absolute error and jitter per bit

4. **Rise/fall times of IR bursts:** Scope at 500 MHz bandwidth resolves the carrier envelope edges. The Flipper's LED driver rise time affects whether a fast TSOP receiver sees a clean carrier envelope or a blurred one.

**Cross-validation:** Independently decode the protocol from the scope's raw capture (Python edge detection on the captured photodiode waveform) and compare the resulting bit stream to what the Flipper reports. Any discrepancy indicates a Flipper firmware decode bug or marginal timing.

**Also useful for:** Characterizing third-party IR LEDs and drivers. Point any IR remote at the photodiode, capture with the scope, and get a precise timing report for that remote. Identifies marginal remotes that barely decode on some TVs.

**Effort:** Low. Scope waveform capture and FFT are established. The main new work is photodiode setup (trivial) and protocol-decode Python (NEC is ~30 lines; sufficient for the cross-validation step).

---

### ✓ 49. IR Receiver Carrier Frequency Response — *rf-bench-flipper-ir-rx-response*

Maps the Flipper Zero's IR receiver sensitivity vs. carrier frequency. The Flipper uses a TSOP-type demodulator IC that is tuned to a center frequency (nominally 38 kHz) and has a bandpass response — signals too far off-frequency are rejected. This project characterizes that bandpass.

**Signal source:** The scope AWG generates a square wave at the test carrier frequency; a series resistor drives an IR LED (850–950 nm, common in indicator LEDs or purposefully chosen). The SDG1062X could also drive the LED for greater power and better frequency accuracy. Place the LED directly in front of the Flipper's IR window.

**Test loop:**

```python
for carrier_hz in range(30_000, 60_000, 500):   # 30–60 kHz in 500 Hz steps
    scope.set_awg_square(freq_hz=carrier_hz, vpp=3.3, duty=33.0)
    # modulate the carrier with a known NEC burst pattern via digital gating
    time.sleep(0.1)
    decoded = fz.ir_receive(timeout_s=0.5)
    log(carrier_hz, decoded is not None, decoded)
```

**What this produces:**
- **Decode success vs. carrier frequency:** At what frequencies does the Flipper successfully decode the NEC burst? The TSOP bandpass is roughly ±3–5 kHz around the center frequency, but actual rolloff varies. Knowing this determines whether the Flipper can reliably receive 36 kHz (RC5), 38 kHz (NEC), or 40 kHz (Sony SIRC) signals from real remotes.
- **Center frequency of the actual TSOP IC installed in the Flipper:** The Flipper Zero uses a TL4838 or equivalent; measuring the actual passband center confirms which part is installed and whether it matches the firmware's default assumption.

**Practical value:** If you're building a device the Flipper needs to control, and its IR receiver uses a non-standard carrier (36 or 40 kHz instead of 38 kHz), you need to know whether the Flipper can decode it. This measurement answers that question directly rather than by trial and error.

**Hardware required:** IR LED (any 850–940 nm LED, ~$0.50) + 100 Ω series resistor. The scope AWG has sufficient current drive for a single LED.

**Effort:** Very low. The scope AWG is fully characterized; the test loop is 20 lines. The only new element is the IR LED wiring, which is simpler than the coupling loop for project #43.

---

### ✓ 50. 433 MHz ISM Sensor Hub — *rf-bench-flipper-sensor-hub*

Passively receives and decodes the broadcast packets from cheap 433 MHz wireless sensors — temperature/humidity sensors, weather stations, door/window contacts, PIR motion sensors, rain gauges, soil moisture probes, and power monitors — that flood the 433.92 MHz band. Logs readings to SQLite and serves live data over HTTP.

**Why this exists:** Dozens of consumer sensor products (Oregon Scientific, Fine Offset, AcuRite, LaCrosse, Nexus/Technoline, Bresser, Govee, Ambient Weather, and many unbranded AliExpress sensors) broadcast their data continuously in plaintext OOK or FSK on 433.92 MHz. Any CC1101 receiver can pick them up. The `rtl_433` project has decoded hundreds of these protocols; the Flipper is a CC1101 with a USB interface — the same raw capture approach applies.

**Architecture:**

```
Flipper Sub-GHz RX (433.92 MHz, OOK raw capture)
    → USB → Python: raw pulse/gap timings
    → Protocol matcher: identify brand/model from preamble + structure
    → Decoder: extract sensor_id, temperature, humidity, battery, sequence
    → SQLite: log readings with timestamp
    → HTTP server: /sensors → live JSON, /sensors/{id}/history → time-series
```

**Protocol coverage:** The rtl_433 project is open source; its protocol decoders are well-documented and can be reimplemented in Python for the subset you care about. Initial target: Oregon Scientific v2/v3 (the most common), Fine Offset (Ambient Weather / Froggit), and AcuRite 6002 — these three cover the majority of cheap sensors sold in the US and EU. Add protocols incrementally as needed.

**Sensor auto-discovery:** On first receipt from an unknown sensor ID, log it as "unknown device, ID 0xABCD, protocol fingerprint [pulse/gap histogram]" and save the raw capture for later analysis. Known sensors are identified by their preamble bit pattern.

**HTTP output:**
```json
GET /sensors
[
  {"id": "0x3F42", "brand": "Oregon Scientific", "model": "THGR122NX",
   "temp_c": 21.4, "humidity_pct": 58, "battery": "ok",
   "last_seen": "2026-05-27T14:23:01Z", "rssi_dbm": -71},
  ...
]
```

**Persistent daemon mode:** Run as a systemd user service. The HTTP endpoint can feed Home Assistant, Grafana, or any tool that polls JSON.

**Effort:** Medium. Raw OOK capture via Flipper RPC is established. The protocol decoders are the bulk of the work but are well-documented in the rtl_433 source. Start with one or two protocols and expand.

---

### ✓ 51. TPMS Decoder — *rf-bench-flipper-tpms*

Receives and decodes Tire Pressure Monitoring System (TPMS) broadcasts from cars on 315 MHz (US) and 433.92 MHz (EU). Every car sold in the US after 2007 has four TPMS sensors that continuously broadcast their sensor ID, tire pressure, temperature, and battery status. The Flipper's CC1101 can receive these.

**What this captures:** While driving or parked near traffic, the Flipper receives TPMS packets from nearby vehicles. Each sensor has a unique 28-32 bit ID burned in at the factory; the vehicle's ECU knows which four IDs belong to it. Different manufacturers use different encoding but most are OOK or FSK with Manchester or NRZ encoding. Well-documented protocols include Schrader (Ford, GM), Continental (VW/Audi, BMW), Huf (Chrysler), Pacific Industries (Toyota/Lexus).

**Two use modes:**

1. **Monitor your own vehicles:** Pre-learn your car's four sensor IDs (drive slowly past the Flipper, capture the first few packets). Thereafter the script filters for those IDs, logs pressure/temp over time, and alerts if any tire drops below threshold. Continuous low-cost TPMS logging that persists between drives.

2. **Survey mode:** Capture all TPMS traffic, identify manufacturer from preamble, report pressure/temperature for everything in range. Useful in a parking lot or driveway — gives a sense of which nearby vehicles have low tires (if you want to be a good neighbor).

**Output:** SQLite log of `(timestamp, sensor_id, manufacturer, pressure_psi, temp_c, battery)`. HTTP endpoint for live monitoring. Alert hook (calls the voip.ms SMS API via `~/money/sms.py`) when a known sensor reports pressure below threshold.

**Effort:** Medium. TPMS protocols are well-documented in the rtl_433 source and academic papers (they've been studied for privacy reasons). The CC1101 packet timing and AGC settling requires tuning, but TPMS packets are long enough to be captured reliably.

---

### ✓ 52. Wireless Alarm Sensor Monitor — *rf-bench-flipper-alarm-monitor*

Decodes the broadcast packets from cheap 315/433 MHz wireless alarm sensors — the kind sold at Harbor Freight, Home Depot, and AliExpress for $5–15 each. These sensors (door/window contacts, PIR motion detectors, glass break sensors, smoke detectors) all broadcast a fixed unique ID when triggered. This project turns the Flipper into a receiver for those sensors, independent of the proprietary base station.

**Why the base station is often the weak link:** Cheap wireless alarm systems have terrible base stations — no network integration, no logging, no remote access. The sensors themselves are fine (decent range, battery life measured in years). This project decodes the RF side so the sensor data can be used with any software.

**Protocol:** Most cheap 433 MHz alarm sensors use one of a handful of OOK protocols: EV1527 (the most common — a simple 24-bit fixed code with no rolling or encryption), PT2262, HX2262, SC5262. These are all trivially decodable: fixed preamble, then 24 bits NRZ/PWM, then a fixed trailer. The sensor ID is encoded in the upper bits; the lower bits indicate event type (trigger, tamper, low battery).

**Decoder output:**
```
2026-05-27 14:31:02  TRIGGERED  sensor_id=0xA4C312  [Front Door]  rssi=-68 dBm
2026-05-27 14:31:02  TRIGGERED  sensor_id=0xA4C312  [Front Door]  rssi=-68 dBm  (repeat)
2026-05-27 14:31:45  LOW_BATT   sensor_id=0x8F1A00  [Garage Motion]  rssi=-82 dBm
```

**Named sensor registry:** A JSON config file maps sensor IDs to human names. First time an unknown sensor ID is seen, it is logged as "unknown 0xXXXXXX" and an alert is generated so you can label it.

**Integration:** The same HTTP + SQLite + SMS alert pattern from the sensor hub (#50). A `POST /alert` webhook fires on any sensor trigger, feeding Home Assistant automations or a simple cron-polled status page.

**Effort:** Low. EV1527 decode is under 30 lines of Python (find preamble, sample 24 bits at the known bit period). The harder part is the sensor registry and alert dispatch, which reuses patterns from other projects.

---

### ✓ 53. 433 MHz Smart Outlet Controller — *rf-bench-flipper-outlet*

Captures the on/off codes from cheap 433 MHz wireless outlet switches (the kind sold in multipacks for $20–30 on Amazon: Etekcity, Dewenwils, BN-LINK, and dozens of generic equivalents) and exposes them via a REST API. Turns the Flipper into a home automation RF bridge for controlling these outlets from any script.

**Context:** These outlets use fixed OOK codes — typically one or two PT2262/EV1527-encoded 24-bit words for "on" and "off" per outlet. The remote that ships with them transmits these codes; the Flipper captures them once and replays them on demand. No cloud account, no app, no hub required.

**Setup workflow:**
```
$ outlet-learn --name "Desk Lamp"
  Point the outlet remote at the Flipper and press ON... captured: 0x1A2B3C (on)
  Press OFF... captured: 0xD4E5F6 (off)
  Saved to outlets.json
```

**REST API (same daemon pattern as #46):**
```
POST /outlets/desk-lamp/on
POST /outlets/desk-lamp/off
GET  /outlets             → list all outlets and current commanded state
```

**Integration:** Drop-in `rest_command` for Home Assistant. Cron job for timed switching. CLI alias. Works with any language that can POST to localhost.

**Transmit timing:** These outlets require the code transmitted 3–5 times with ~10 ms gap between repeats for reliable switching. The Flipper's raw TX mode handles this.

**Effort:** Very low. EV1527/PT2262 capture and replay is already established from #52. The new work is the named outlet registry and the daemon HTTP wrapper.

---

### ✓ 54. Sub-GHz Remote Code Library Builder — *rf-bench-flipper-subghz-library*

The Sub-GHz counterpart to the IR library builder (#44). Systematic capture, labeling, organization, and export of Sub-GHz remote codes — garage door openers, gate controllers, barrier openers, RF outlet remotes, car remotes (fixed code only), wireless doorbells, and any other fixed-code Sub-GHz device.

**Capture session:**
```
$ subghz-library capture --device "Garage Door" --remote "LiftMaster 371LM"
  Waiting for Sub-GHz signal... (point remote at Flipper, press button)
  Decoded: CAME 12-bit, code 0x1A3F → label: open_close
  Waiting... → label: light
  Saved to subghz-library.json
```

**What it records per code:** frequency, modulation, protocol name (if identified), raw timing, decoded value, button label, device, remote model, timestamp of capture.

**Exports:**
- **Flipper `.sub` format:** drop onto SD card for interactive replay
- **JSON database:** machine-readable, searchable by frequency/protocol/device
- **openMQTTGateway format:** compatible with the popular ESP32-based RF bridge firmware, enabling migration from Flipper to a permanent embedded gateway

**Search and replay:**
```
$ subghz-library list --freq 433.92
$ subghz-library send --device "Garage Door" --button open_close
```

**Why this matters over just using the Flipper's built-in capture:** The Flipper's UI stores captures as flat files named by frequency and timestamp. Finding a specific code later, exporting it, or integrating it into automation requires this kind of organized database.

**Effort:** Low. Same structure as the IR library builder; Sub-GHz RPC calls substitute for IR RPC calls.

---

### ✓ 55. Sub-GHz RF Environment Scanner — *rf-bench-flipper-rf-scan*

Uses the CC1101's RSSI measurement capability to sweep ISM frequencies and report signal activity — a simple Sub-GHz spectrum survey tool that requires only the Flipper and a laptop. No SSA, no bench equipment.

**How it works:** The CC1101 can be commanded to a specific frequency, wait for AGC settle, and report the current RSSI register value. By stepping through a list of frequencies and collecting RSSI readings, Python assembles a signal-presence map of the Sub-GHz spectrum.

**Coverage:** 300–928 MHz in the three CC1101 bands. Practical step size: 200 kHz (coarser than the SSA's 751-point sweeps, but sufficient for identifying occupied channels in the ISM bands). Full sweep of all ISM channels in each band in under 10 seconds.

**Display:**
```
433.00 MHz  ▏                          -101 dBm
433.20 MHz  ▏                          -103 dBm
433.40 MHz  ▏                          -104 dBm
433.60 MHz  ▏                           -99 dBm
433.80 MHz  ████▏                       -72 dBm  ← activity
433.92 MHz  ██████████▏                 -58 dBm  ← strong signal
434.00 MHz  ████▏                       -71 dBm
434.20 MHz  ▏                          -100 dBm
```

**Use cases:**
- Site survey before deploying a new 433 MHz link: which channels are clear?
- Find the frequency of an unknown remote or sensor (sweep while pressing the button)
- Identify interference sources in an ISM band before debugging a range problem
- Verify a new 433 MHz link is transmitting on the correct frequency without needing the SSA

**Limitations vs. the SSA:** RSSI accuracy ±6 dB uncalibrated (improved by the calibration table from #41 if that project has been run). Sweep speed is much slower than the SSA. No demodulation or signal display. But it requires zero bench equipment and works anywhere.

**Logging mode:** Record RSSI at each channel continuously to CSV. Run overnight to map ISM occupancy patterns over time. Complement to the SSA band occupancy monitor (#21) for Sub-GHz frequencies.

**Effort:** Very low. CC1101 RSSI reads per frequency are the core of #41; this is the same loop without the signal source, wrapped in a display.

---

### ✓ 57. Si5351 Interactive Multi-Channel Frequency Generator — *rf-bench-si5351-gen*

A curses-based interactive generator that programs all three outputs of a Si5351 breakout
board via Bus Pirate I2C. The Si5351 is a $5 I2C clock generator covering ~3 kHz to 200 MHz
with three independent output clocks — useful as a signal source substitute when a real bench
generator is not available, or as a permanent clock source for homebrew radio projects.

**Equipment required:**
- Bus Pirate v3/v4 (I2C master)
- Si5351 breakout module (~$5 Adafruit, SparkFun, or AliExpress)
- Optional: SSA3032X Plus (to display actual output power per channel)

**What it is not:** The Si5351 has mediocre phase noise (~−100 dBc/Hz at 10 kHz offset) and
modest harmonic content (−10 to −30 dBc typical). It is not a substitute for the SDG1062X
in sensitive IMD or noise figure measurements. It is a cheap, accessible source good enough
for frequency injection, LO generation, clock injection, and rough signal injection testing.

**Known limitation:** The Si5351 has only 2 internal PLLs for 3 outputs. CLK0 is assigned
PLL-A exclusively; CLK1 and CLK2 share PLL-B. Setting either CLK1 or CLK2 reprograms PLL-B
and may slightly change the other's actual output frequency. The TUI displays an asterisk on
outputs sharing a PLL-B and shows computed actual frequency for all channels.

**Curses TUI features:**
- Three-channel display: CLK0/1/2, on/off state, frequency, drive strength (2/4/6/8 mA), PLL source
- Arrow keys to select channel; SPACE to toggle on/off
- F: enter new frequency (parses '10MHz', '7.074e6', '14318kHz', etc.)
- D: cycle drive strength (2→4→6→8→2 mA)
- A/Z: all outputs on / all outputs off
- S: sweep mode — start/stop/steps/dwell prompt for selected channel
- M: measure selected channel on SSA (requires --ssa)
- P/L: save/load named presets to ~/.si5351_presets.json
- Q: quit and disable all outputs

**CLI mode:** `--cli --clk0 10e6 --clk1 7.074e6 --clk2 14.318180e6 [--stay]`

**Hardware note:** Si5351 I2C address is 0x60 (ADDR pin low) or 0x61 (ADDR pin high).
Crystal frequency is 25 MHz on most breakouts; 26 MHz on some. Use `--xtal 26e6` for the
26 MHz variants.

**Effort:** Medium (curses TUI + Si5351 register math). Si5351 register encoding follows
AN619 (P1/P2/P3 multisynth parameters); integer PLL multiplier + fractional MS divider
gives best phase noise while covering full frequency range.

---

### ✓ 56. Sub-GHz Packet Link Tester — *rf-bench-flipper-link-test*

Two-ended packet ping/pong test for evaluating a Sub-GHz RF link. One end is the Flipper; the other end can be a second Flipper, a CC1101 module wired to the Bus Pirate, or any CC1101-based device running cooperative firmware. Measures packet delivery rate, round-trip RSSI, and maximum reliable range at each ISM frequency.

**Test protocol:** The initiating end (Flipper A via USB) transmits a numbered packet. The far end (Flipper B or Bus Pirate CC1101) receives it and retransmits an ACK containing its received RSSI. Flipper A logs: was the ACK received, what was the far-end RSSI, what was the local RSSI on the ACK.

```
Freq       TX power   Distance   PDR     Local RSSI  Far RSSI
433.92 MHz  0 dBm     5 m       100%     -61 dBm     -63 dBm
433.92 MHz  0 dBm     20 m      100%     -74 dBm     -77 dBm
433.92 MHz  0 dBm     50 m       94%     -89 dBm     -91 dBm
433.92 MHz  0 dBm     80 m       61%     -97 dBm     -99 dBm
```

**Useful for:**
- Validating a Sub-GHz link for a hardware design before committing to PCB fabrication
- Comparing antenna designs: whip vs. PCB trace vs. helical — run the same range test with each antenna and compare PDR curves
- Characterizing path loss in a specific environment (through walls, across a field)
- Confirming that your garage door or alarm sensor will reliably reach the base station through your house construction

**Single-Flipper mode (no far end needed):** Place a second CC1101 module (Bus Pirate + CC1101 breakout) at a fixed distance, running simple ACK firmware. The Flipper script drives both ends via USB to the Bus Pirate (#34 Bus Pirate driver + direct CC1101 SPI writes) and the Flipper (#39 driver).

**Effort:** Medium. The packet protocol design is simple; the main work is synchronizing two independent USB-connected devices from the same Python process, and handling the CC1101 packet mode configuration on both ends.

---

---

## RTL-SDR Ideas

The RTL-SDR Blog v4 is the only instrument in this bench that provides **raw I/Q baseband
samples**. The SSA is scalar and swept — amplitude only, no demodulation. The IC-7300
demodulates HF signals but nothing above 60 MHz. The Flipper CC1101 receives at ISM bands
but only at CC1101 bandwidth with modulation-specific sensitivity. The RTL-SDR covers
500 kHz–1766 MHz with 2.4 MHz instantaneous IQ bandwidth and fully software-defined
demodulation.

**What RTL-SDR does that nothing else here can:**
- Demodulate any signal in software (AM, FM, SSB, FSK, OOK, digital modes, satellite)
- Capture a 2.4 MHz IQ slice simultaneously for post-processing or offline replay
- Decode protocols entirely outside the other instruments' capabilities: ADS-B Mode S,
  APRS direct-RF, weather satellite APT/LRPT

**Where it is not a substitute for existing instruments:**
- Dynamic range: SSA wins by ~60 dB — use SSA for amplitude measurement, not RTL-SDR
- HF: IC-7300 has far lower noise figure and better dynamic range below 60 MHz
- Sub-GHz ISM protocols: Flipper CC1101 + SSA is more accurate for power measurements
- TX: RTL-SDR is receive-only; the Flipper is the Sub-GHz TX device

**Driver note:** Unlike the Bus Pirate (binary BBIO1 protocol) and Flipper (USB protobuf
RPC), the RTL-SDR already has a mature Python API — `pyrtlsdr` wraps librtlsdr cleanly.
No custom protocol implementation is needed. A thin `rf_bench.rtlsdr` wrapper is still
worth writing for PPM calibration correction, consistent import pattern, and device
enumeration, but it is ~80 lines rather than the hundreds of lines required by the other
drivers.

---

### ✓ 71. ✓ RTL-SDR Driver — *rf-bench-drivers-rtlsdr*

Prerequisite for all other RTL-SDR projects. A thin `rf_bench.rtlsdr.RTLSDR` wrapper
following the same import pattern as `rf_bench.siglent`, `rf_bench.buspirate`, etc.
Unlike those drivers, **no custom protocol implementation is required** — pyrtlsdr
handles all hardware communication. The wrapper adds:

1. **Frequency calibration:** measured PPM correction applied to every `set_center_freq()`
   call. Calibrate once against a known carrier from the SDG + SSA; store in
   `~/.rtlsdr_cal.json`.
2. **Consistent import pattern:** `from rf_bench.rtlsdr import RTLSDR` rather than
   importing pyrtlsdr directly in each project.
3. **Workflow helpers:** `capture_iq()`, `power_spectrum()`, `scan_activity()` as
   one-liners shared across all RTL-SDR projects.
4. **Device enumeration:** `RTLSDR.find_devices()` lists attached dongles by serial
   number; `RTLSDR(serial="00000001")` connects to a specific unit for reproducibility.

**API to expose:**

```python
from rf_bench.rtlsdr import RTLSDR

sdr = RTLSDR(serial=None, ppm_correction=0)  # serial=None → first device
sdr.identify()                               # → device string + tuner type + firmware

sdr.set_center_freq(144_390_000)
sdr.set_sample_rate(2_400_000)
sdr.set_gain(30)                             # dB, or "auto"
sdr.set_bias_tee(True)                       # power inline LNA

iq = sdr.capture_iq(num_samples=262_144)     # → complex64 numpy array
psd = sdr.power_spectrum(iq, rbw_hz=1000)    # → (freq_hz, power_dbm) arrays

# Streaming (generator — yields complex64 blocks)
for block in sdr.stream_iq(block_size=65_536):
    process(block)
sdr.stop_stream()

sdr.close()
```

**Dependencies:** `pyrtlsdr` (pip — already installed). `rtl-sdr` system package
(already installed: `rtl-sdr 2.0.2`).

**Effort:** Very low. The wrapper is ~80 lines. No protocol implementation; pyrtlsdr
handles everything at the hardware level.

---

### ✓ 72. ✓ ADS-B Local Receiver — *rf-bench-rtlsdr-adsb*

Decodes Mode S ADS-B transmissions at 1090 MHz from aircraft overhead. Produces
real-time aircraft position, altitude, squawk, and velocity data from local RF,
independent of internet feeds. Cross-references each ICAO hex address with the
govt-data `/aircraft/hex/{icao_hex}` API to enrich raw data with N-number, aircraft
type, registered owner, and base airport.

**What this adds beyond Vestigare:** Vestigare (`~/vestigare/`) aggregates data from
airplanes.live, adsb.lol, and OpenSky. This project receives directly from RF —
measuring which aircraft are actually audible at the antenna, characterizing receive
range and signal strength, and comparing against what the internet feeds show. Aircraft
that are overhead but absent from internet feeds (startup flights, military, lost-comms)
show up in local RF decode but not in Vestigare's sources.

**Architecture:**

```
RTL-SDR (1090 MHz, 2 MHz BW) → IQ samples → pyModeS decode → aircraft state
    → govt-data /aircraft API → enriched: N-number, type, owner
    → SQLite: (timestamp, icao_hex, callsign, lat, lon, alt_ft, speed_kt, rssi_dbm)
    → HTTP: /aircraft → live JSON; /aircraft/{hex}/trail → position history
```

**Protocol decode:** `pyModeS` decodes raw Mode S (DF17 ADS-B + DF20/21 Mode S EHS)
directly from I/Q samples. Alternative: pipe raw bytes to `dump1090` via subprocess —
more reliable at weak signals because dump1090 uses phase-corrected demodulation, but
adds a subprocess dependency.

**Bench use cases:**
- **Antenna comparison:** run two RTL-SDRs on different antennas simultaneously, log
  both aircraft decode rates and per-aircraft RSSI, compare antenna gain and pattern.
- **Receive range characterization:** log the RSSI at which each aircraft is first
  decoded; map range vs. elevation angle to characterize antenna pattern and local
  obstructions.
- **Vestigare ground-truth:** cross-check what Vestigare shows from internet feeds
  against what is actually audible at your antenna.

**Dependencies:** `pyModeS` (pip). `dump1090` (optional, AUR or compile from source).

**Effort:** Low. IQ capture is the driver's core operation. pyModeS handles all Mode S
decoding. API lookup and SQLite logging follow the same pattern as the APRS server.

---

### ✓ 73. ✓ APRS Direct Receive — *rf-bench-rtlsdr-aprs*

Receives APRS transmissions directly from RF on 144.390 MHz (US), decodes AX.25
packets, and cross-references with the aprs-server's PostgreSQL database and the
govt-data `/callsigns` API. Offline — no APRS-IS connection required.

**The gap this fills:** The existing aprs-server (`~/aprs-server/`) connects to
APRS-IS — internet-sourced data that is gated, filtered, and potentially delayed.
This project hears only stations within direct RF range. Comparing the two answers:
- Which local stations are being gated to the internet? (present in both)
- Which are heard locally but never gated? (missing igate coverage)
- Which APRS-IS packets have no local source? (relayed from far away via internet)

**Decode path:**

```
RTL-SDR (144.390 MHz, 24 kSa/s, FM demod) → direwolf → decoded AX.25 packets
    → govt-data /callsigns → FCC license info per callsign
    → aprs-server PostgreSQL → compare with APRS-IS-sourced records
    → log: (timestamp, callsign, heard_locally=True, rssi_dbm, packet_data)
```

**Decode options:**
- **direwolf:** the standard Linux AX.25 soft-TNC. `rtl_fm -f 144.39M -s 24000 |
  direwolf -r 24000 -` — reliable, widely tested. Recommended.
- **multimon-ng:** lighter weight, handles AFSK 1200 baud. Easier to embed in a Python
  subprocess.
- **Pure Python (pyax25):** no subprocess dependency, but less sensitive at weak signals.

**Effort:** Low. The RF → direwolf → packet pipeline is well-established. The new
Python work is the APRS-IS database comparison and callsign enrichment.

**Dependencies:** `direwolf` (pacman). No additional pip packages.

---

### ✓ 74. ✓ Weather Satellite APT/LRPT Decoder — *rf-bench-rtlsdr-wxsat*

Receives weather satellite transmissions and decodes them to images. Completely new
capability — no other instrument in this bench approaches this.

**Satellite targets:**

| Satellite | Frequency | Mode | Resolution |
|---|---|---|---|
| NOAA 15 | 137.620 MHz | APT (analog FM) | 4 km/px, VIS + IR |
| NOAA 18 | 137.9125 MHz | APT (analog FM) | 4 km/px, VIS + IR |
| NOAA 19 | 137.100 MHz | APT (analog FM) | 4 km/px, VIS + IR |
| Meteor-M N2-4 | 137.100 MHz | LRPT (digital QPSK) | 1 km/px, RGB composite |

**Workflow:**

1. **Pass prediction:** `pyorbital` computes next satellite pass from your location.
   Returns AOS time, maximum elevation, LOS time.
2. **Automated capture:** schedule the RTL-SDR capture to start 60 s before AOS and
   stop at LOS. Save FM-demodulated audio as WAV (APT) or raw IQ (LRPT).
3. **APT decode:** `noaa-apt` (Rust binary) or `aptdec` (C) converts WAV → PNG with
   visible and IR channels separated and geo-referenced.
4. **LRPT decode:** `SatDump` handles the full pipeline from IQ to RGB image.
5. **Output:** PNG images named `{satellite}_{timestamp}_{elevation}deg.png`. Optional
   web gallery served from the same host.

**Hardware:** A V-dipole antenna (~$5 in wire and a BNC connector) is sufficient —
two 54 cm elements at 120° angle, omnidirectional in elevation, no tracking required
for LEO satellites. Enable the bias tee to power an inline LNA; the extra ~20 dB of
gain makes a large difference for weak-signal APT quality.

**Pass schedule integration:** The pass predictor outputs the same data as existing
satellite-tracking projects. An evening cron job schedules captures for all passes
above 20° elevation overnight; check the web gallery in the morning.

**Dependencies:** `pyorbital` (pip). `noaa-apt` (AUR) for APT decode.
`SatDump` (compile from source) for LRPT.

**Effort:** Medium. Pass prediction and scheduled capture are straightforward Python.
Decode tools are external binaries called via subprocess. Main work: scheduling logic
and image pipeline.

---

### ✓ 75. ✓ Wideband IQ Recorder — *rf-bench-rtlsdr-recorder*

Records any 2.4 MHz slice of spectrum as a raw I/Q file in SigMF format — a
timestamped, annotated capture that can be replayed, demodulated, and analyzed
offline indefinitely.

**What offline I/Q enables that the SSA cannot:**
- Demodulate a signal captured months ago using a decoder that did not exist at
  capture time
- Replay a capture repeatedly while tuning decoder parameters
- Share a capture for independent analysis without repeating the test
- Post-hoc investigation of an intermittent signal (record continuously; examine
  the window around the event after the fact)

**SigMF format:** JSON metadata file + binary `.sigmf-data` file. Metadata records
center frequency, sample rate, timestamp, hardware description, and annotations.
`sigmf` Python library handles read/write. Compatible with GNU Radio, SDR++, inspectrum,
and most SDR software.

**Recording modes:**
- **Immediate:** `record.py --freq 433.92e6 --bw 2.4e6 --duration 60 --out ism.sigmf`
- **Scheduled:** `record.py --freq 137.62e6 --start "2026-05-28T21:14:00Z" --duration 600`
  (timed for a NOAA pass from the wxsat pass predictor)
- **Threshold-triggered:** start recording when power at center frequency exceeds a
  threshold; stop N seconds after the last burst. Useful for intermittent ISM signals.
- **Rotating buffer:** maintain a rolling window of the last N minutes; write to disk
  on request. Nothing is missed; storage is bounded.

**Storage:** 2.4 MSa/s × 8 bytes (complex64) = 19.2 MB/s. Reduce to complex int8
(2 bytes/sample) for long recordings — adequate for most signals, 4× storage saving.

**Dependencies:** `sigmf` (pip).

**Effort:** Low. IQ capture is the driver's core call. SigMF metadata is a JSON
wrapper. Threshold and rotating-buffer modes are small state machines.

---

### ✓ 76. ✓ Protocol Hunter / Signal Classifier — *rf-bench-rtlsdr-classify*

Scans a frequency range, detects signal bursts above the noise floor, and
characterizes each: bandwidth, modulation class, symbol rate estimate, center
frequency offset. Feeds the SSA for precise characterization of anything interesting.

**The gap this fills:** The SSA band occupancy monitor (#21) detects power levels
and produces a waterfall. The Flipper RF scanner (#55) reads CC1101 RSSI. Neither
can classify modulation or estimate symbol rate. This project provides a first-pass
answer to "what kind of signal is this?" anywhere from 500 kHz to 1766 MHz.

**Detection and classification loop:**

```python
for block in sdr.stream_iq(block_size=65_536):
    psd = np.abs(np.fft.fftshift(np.fft.fft(block)))**2
    for peak in find_peaks_above_noise(psd, threshold_db=10):
        burst = extract_burst_iq(block, peak)
        result = classify(burst)  # → {bw_hz, modulation, symbol_rate_hz, freq_offset_hz}
```

**Classification heuristics (amplitude/frequency/phase variance):**

| Test | Classification |
|---|---|
| Low AM index, high FM index, constant envelope | FM carrier (voice, narrowband FM) |
| High AM index, low FM/PM index | AM or OOK (ISM sensors, garage doors) |
| Constant envelope, discrete frequency steps | FSK (APRS, ISM FSK, DMR) |
| Constant envelope, discrete phase steps | PSK/QPSK (ACARS, L-band data links) |
| Impulsive, short duty cycle | radar altimeter, transponder, DME |

Symbol rate estimate: −20 dB bandwidth gives a good first approximation for FSK/OOK.
Autocorrelation peak spacing in instantaneous frequency gives a more precise estimate.

**SSA handoff:** when a signal of interest is detected, optionally command the SSA
via SCPI to lock onto that frequency for a precision measurement. The RTL-SDR scans
fast across a wide range; the SSA measures amplitude accurately. Directly extends the
EMI finder (#16) workflow: RTL-SDR identifies candidate clock harmonics by modulation
signature (pure carrier vs. modulated vs. pulsed), then SSA confirms the level.

**Effort:** Medium. Individual heuristics are simple; tuning them against real signals
requires iteration. SSA handoff is straightforward SCPI.

---

### ✓ 77. ✓ FM Band Monitor with RDS Decode — *rf-bench-rtlsdr-fm-rds*

Extends the SSA FM propagation monitor (#64) with actual demodulation and RDS station
identification. The SSA logs power levels and produces a waterfall. This project adds:
what station is at each frequency, what it is currently broadcasting, and whether a
newly-appeared carrier is a local or distant transmitter.

**RDS fields decoded per station:**

| Field | Content | Use |
|---|---|---|
| PS (Program Service) | 8-char station name | Uniquely identifies the transmitter |
| PI code | 16-bit country + region + ref | Determines transmitter origin |
| PTY | Program type (news, rock, talk…) | Identifies station format |
| RT (RadioText) | Now-playing song/artist | Confirms decode quality |
| AF (Alt Frequencies) | Other freqs for same network | Reveals transmitter network |

**Tropospheric ducting detection:** A distant station appears with a PI code from a
different geographic region. Logging `pi_code → region` over time produces a ducting
event log: "on 2026-05-28 at 14:23 UTC, PI codes from the Pacific Northwest appeared
on normally-clear frequencies." The PI code is far more reliable than trying to
recognize a station by its frequency alone.

**Architecture:**

```
RTL-SDR → FM demodulate (scipy) at each channel → RDS decode (redsea subprocess)
    → DB: (timestamp, freq_mhz, power_dbm, pi_code, ps_name, pty, radiotext)
    → Alert: new PI code region detected → SMS via sms.py
```

**Integration with SSA #64:** Run both concurrently — the SSA sweeps the full band
for a power overview every 2–3 seconds; the RTL-SDR demodulates individual stations
of interest. A new peak on the SSA waterfall triggers the RTL-SDR to demodulate that
frequency and capture its PI code. Between them: one instrument detects presence,
the other confirms identity.

**Dependencies:** `redsea` (C++ binary, compile from source — better weak-signal
RDS than pure-Python alternatives).

**Effort:** Low. FM demodulation is one scipy call. RDS decode via redsea subprocess.
DB schema and SMS alert reuse patterns from other projects.

---

### ✓ 95. Bubba Detector — Multi-Band Handheld Radio Activity Scanner — *rf-bench-rtlsdr-bubba*

Scans all common handheld radio frequencies (FRS, GMRS, Marine VHF, MURS, NOAA weather,
and business band itinerant frequencies) using the RTL-SDR, detects signal energy above
a squelch threshold, and logs each detection with timestamp, frequency, channel name, and
relative signal strength. Displays a rolling terminal log of recent activity.

**The "Bubba Detector" concept:** A scanner pre-loaded with consumer/commercial handheld
radio frequencies to detect nearby radio traffic — useful for situational awareness in
field or survival scenarios where nearby groups may be using cheap bubble-pack radios,
marine handhelds, or business-band radios.

**Detection technique:** Group nearby channels into clusters that fit within the RTL-SDR's
2.4 MHz instantaneous bandwidth. For each group: tune to the cluster center, capture IQ,
FFT, extract power at each channel offset, compare against the estimated noise floor
(median of FFT bins). A channel is flagged "active" if its power exceeds the noise floor
by the squelch threshold (default: 10 dB). This approach gives ~1 second full-sweep cycle
time across 9 scan groups and 74 channels.

**Frequency coverage:**

| Band | Channels | Frequency range |
|------|---------|-----------------|
| FRS channels 1–7 / GMRS CH 1–7 | 7 simplex | 462.5625–462.7125 MHz |
| FRS channels 8–14 | 7 simplex | 467.5625–467.7125 MHz |
| FRS channels 15–22 / GMRS CH 15–22 | 8 simplex | 462.5500–462.7250 MHz |
| GMRS repeater outputs | 8 duplex | 467.5500–467.7250 MHz |
| MURS | 5 simplex | 151.820–154.600 MHz |
| Marine VHF (key channels: 16, 06, 09, 22A, 68–72, 78–80) | ~18 | 156.050–157.400 MHz |
| NOAA weather | 7 | 162.400–162.550 MHz |
| Business band VHF itinerant | ~10 | 151.505–154.600 MHz |
| Business band UHF itinerant | ~4 | 451.800–467.937 MHz |

**Signal strength note:** RTL-SDR power output is uncalibrated dBFS (decibels relative
to full scale). Values are useful for comparing relative signal strength within a session
but do not correspond to dBm without running `rx-crosscheck`. The display shows a bar
graph and raw dBFS value; if `~/.rtlsdr_vhf_cal.json` exists (from rx-crosscheck at the
relevant frequency), calibrated dBm is shown instead.

**Scan groups (11 total, ~1 second per full cycle):**

Each group is one RTL-SDR capture at a fixed center frequency. Within that capture, all
channels within ±1.1 MHz of the center are evaluated simultaneously.

**Output:**
- Rolling terminal log: `[HH:MM:SS] FRS CH 1 / GMRS CH 1  462.5625 MHz  -74 dBFS  ████████░░`
- SQLite database: `bubba_<timestamp>.db` — (ts, freq_hz, channel_name, band, signal_dbfs)
- Scan statistics: detections per channel since startup
- Optional SMS alert when any activity detected (via `~/money/sms.py`)

**Configurable:**
- `--squelch DB` — detection threshold above noise floor (default 10 dB)
- `--gain DB` — RTL-SDR gain (default 40 dB; reduce if overload)
- `--no-gmrs`, `--no-marine`, `--no-murs` — disable individual band groups
- `--alert` — send SMS on first detection in each scan cycle
- `--log FILE` — SQLite output path

**Effort:** Low. RTL-SDR capture and FFT are established. The channel database and
scan group geometry are the main new work. No demodulation required — energy detection
only. The rolling display is simpler than a waterfall.

---

---

## Priority Order

| Priority | Project | Instruments | Hardware needed | GitHub |
|----------|---------|-------------|-----------------|--------|
| ✓ Done | Receiver Test Suite | SDG + attenuators + scope + IC-7300/FT-891 | SMA pads, combiner | ✓ pushed |
| ✓ Done | Signal Analyzer (antenna VSWR) | SSA + RB3X25 | None | ✓ pushed |
| ✓ Done | RF Amplifier Characterizer | SDG + SSA | Resistive combiner | ✓ pushed |
| ✓ Done | Scalar VNA | SSA + RB3X25 | None | ✓ pushed |
| ✓ Done | Balun / Choke Analyzer | SSA + RB3X25 | None | ✓ pushed |
| ✓ Done | Bode Plotter | SDS2000X (AWG) or SDG | None | ✓ pushed |
| ✓ Done | Crystal Extractor | SDG + scope | None | ✓ pushed |
| ✓ Done | TDR | SDG + scope | SMA T-splitter | ✓ pushed |
| ✓ Done | PSU Characterizer | SPD + ET54 + SDM + scope | None | ✓ pushed |
| ✓ Done | I-V Tracer | SPD + SDM | None | ✓ pushed |
| ✓ Done | Battery Tester | ET54 + SDM + SPD | None | ✓ pushed |
| ✓ Done | Mixer Characterizer | SDG + SSA | None | ✓ pushed |
| ✓ Done | RF Impedance | SDG + scope | None | ✓ pushed |
| ✓ Done | Calibration | SDG + scope + SSA + DMM | Reference attenuator | ✓ pushed |
| ✓ Done | Protocol Analyzer | SDS2000X MSO | MSO pod | ✓ pushed |
| ✓ Done | Power Integrity | SDS2000X MSO | MSO pod | ✓ pushed |
| ✓ Done | Clock Jitter | SDS2000X MSO | MSO pod | ✓ pushed |
| ✓ Done | EMI Finder | SSA + SDS2000X MSO | MSO pod | ✓ pushed |
| ✓ Done | PSRR | SDS2000X AWG + scope | Injection circuit (passives) | ✓ pushed |
| ✓ Done | Transmitter Test Suite (#18) | SSA + IC-7300/FT-891 | None | ✓ pushed |
| ✓ Done | Phase Noise Measurement (#19) | SDG + SSA | None | ✓ pushed |
| ✓ Done | Noise Figure Meter / Y-factor (#20) | SSA + noise source | Noise source (~$50–200) | ✓ pushed |
| ✓ Done | Band Occupancy / Spectrum Waterfall (#21) | SSA | None | ✓ pushed |
| ✓ Done | Oscillator Stability / Allan Deviation (#22) | SSA or scope | None | ✓ pushed |
| ✓ Done | Matching Network Designer + Verifier (#23) | SDG + scope + scalar-vna | None | ✓ pushed |
| ✓ Done | Varactor / Varicap Characterizer (#24) | SPD + SDG + scope | None | ✓ pushed |
| ✓ Done | SDG Self-Characterization (#25) | SDG + SSA | None | ✓ pushed |
| ✓ Done | Bus Pirate Driver (#34) | Bus Pirate | Bus Pirate hardware | ✓ pushed |
| ✓ Done | Synthesizer Characterizer Si5351/ADF4351 (#35) | Bus Pirate + SSA; MSO optional | Bus Pirate + synth module | ✓ pushed |
| ✓ Done | DDS Characterizer AD9833/AD9851 (#36) | Bus Pirate + SSA | Bus Pirate + DDS module | ✓ pushed |
| ✓ Done | Oscillator Temperature Coefficient (#37) | Bus Pirate + SSA | Bus Pirate + I2C temp sensor ($3) | ✓ pushed |
| ✓ Done | Digital Step Attenuator Calibration (#38) | Bus Pirate + SSA | Bus Pirate + SPI attenuator | ✓ pushed |
| ✓ Done | Si5351 Multi-Channel Generator (#57) | Bus Pirate | Si5351 breakout (~$5) | ✓ pushed |
| ✓ Done | Flipper Zero Driver (#39) | Flipper Zero | Flipper Zero hardware | ✓ pushed |
| ✓ Done | CC1101 Synthesizer + TX Characterizer (#40) | Flipper Zero + SSA | Flipper Zero | ✓ pushed |
| ✓ Done | Sub-GHz Receiver Sensitivity Test (#41) | Flipper Zero + SSA (TG) + attenuators | Flipper Zero | ✓ pushed |
| ✓ Done | ISM Signal Decoder + Spectral Annotation (#42) | Flipper Zero + SSA | Flipper Zero | ✓ pushed |
| ✓ Done | RFID / NFC Field Characterizer (#43) | Flipper Zero + SSA | Flipper Zero + coupling loop (~$2) | ✓ pushed |
| ✓ Done | IR Remote Code Library Builder (#44) | Flipper Zero only | None | ✓ pushed |
| ✓ Done | IR Device Code Discovery (#45) | Flipper Zero only | None | ✓ pushed |
| ✓ Done | IR Universal Remote HTTP Daemon (#46) | Flipper Zero only | None | ✓ pushed |
| ✓ Done | IR Transmitter Waveform Characterizer (#48) | Flipper Zero + scope (photodiode) | Flipper Zero + Si photodiode (~$2) | ✓ pushed |
| ✓ Done | IR Receiver Carrier Frequency Response (#49) | Flipper Zero + scope AWG + IR LED | Flipper Zero + IR LED + 100 Ω resistor (~$0.50) | ✓ pushed |
| ✓ Done | 433 MHz ISM Sensor Hub (#50) | Flipper Zero only | None | ✓ pushed |
| ✓ Done | TPMS Decoder (#51) | Flipper Zero only | None | ✓ pushed |
| ✓ Done | Wireless Alarm Sensor Monitor (#52) | Flipper Zero only | None | ✓ pushed |
| ✓ Done | 433 MHz Smart Outlet Controller (#53) | Flipper Zero only | None | ✓ pushed |
| ✓ Done | Sub-GHz Remote Code Library Builder (#54) | Flipper Zero only | None | ✓ pushed |
| ✓ Done | Sub-GHz RF Environment Scanner (#55) | Flipper Zero only | None | ✓ pushed |
| ✓ Done | Sub-GHz Packet Link Tester (#56) | Flipper Zero × 2 or Flipper + Bus Pirate CC1101 | CC1101 breakout module (~$3) optional | ✓ pushed |
| ✓ Done | RTL-SDR Driver (#71) | RTL-SDR | RTL-SDR Blog v4 dongle (~$40) | ✓ pushed |
| ✓ Done | ADS-B Local Receiver (#72) | RTL-SDR | RTL-SDR + LNA + 1090 MHz antenna | ✓ pushed |
| ✓ Done | APRS Direct Receive (#73) | RTL-SDR | RTL-SDR + LNA + 144 MHz antenna | ✓ pushed |
| ✓ Done | Weather Satellite Decoder (#74) | RTL-SDR | RTL-SDR + LNA + V-dipole antenna (~$5) | ✓ pushed |
| ✓ Done | Wideband IQ Recorder (#75) | RTL-SDR | RTL-SDR | ✓ pushed |
| ✓ Done | Protocol Hunter / Classifier (#76) | RTL-SDR (+ SSA optional) | None | ✓ pushed |
| ✓ Done | FM Monitor with RDS (#77) | RTL-SDR (+ SSA for waterfall) | None | ✓ pushed |
| ✓ Done | Component Sorting Station (#58) | SDM3045X only | None | ✓ pushed |
| ✓ Done | Temperature Coefficient of Resistance (#59) | SDM3045X only | Type K thermocouple probe | ✓ pushed |
| ✓ Done | Kelvin Contact Resistance Survey (#60) | SDM3045X only | None | ✓ pushed |
| ✓ Done | Eye Diagram Builder (#61) | SDS2504X Plus only | None | ✓ pushed |
| ✓ Done | Glitch / Anomaly Trap (#62) | SDS2504X Plus only | None | ✓ pushed |
| ✓ Done | Power Rail Sequencer (#63) | SPD3303X-E only | None | ✓ pushed |
| ✓ Done | FM Broadcast Propagation Monitor (#64) | SSA3032X Plus only | None | ✓ pushed |
| ✓ Done | Thermal Resistance Characterizer (#65) | SPD + SDM | Type K thermocouple probe | ✓ pushed |
| ✓ Done | Component Stress / Aging Monitor (#66) | SPD + SDM | None | ✓ pushed |
| ✓ Done | Inrush Current Profiler (#67) | SPD + scope | 0.1 Ω current-sense resistor | ✓ pushed |
| ✓ Done | Radio Audio Chain Tester (#68) | SDG + IC-7300 (USB audio) | BNC-to-3.5 mm adapter | ✓ pushed |
| ✓ Done | RF Switch Characterizer (#69) | Bus Pirate + SSA | RF switch module | ✓ pushed |
| ✓ Done | Dual-Radio Antenna Isolation (#70) | IC-7300 × 2 | 30 dB SMA attenuator | ✓ pushed |
| ✓ Done | HP GPIB Driver (#26) | HP 8712B | Ethernet-GPIB adapter | ✓ pushed |
| ✓ Done | Full S-Parameter Suite (#27) | HP 8712B | Ethernet-GPIB adapter | ✓ pushed |
| ✓ Done | Group Delay Measurement (#28) | HP 8712B | Ethernet-GPIB adapter | ✓ pushed |
| ✓ Done | True RF Impedance + Smith Chart (#29) | HP 8712B | Ethernet-GPIB adapter | ✓ pushed |
| ✓ Done | Transistor S-Parameter Characterization (#30) | HP 8712B + bias fixture | Ethernet-GPIB adapter + fixture PCB | ✓ pushed |
| ✓ Done | Transmission Line Characterizer (#31) | HP 8712B | Ethernet-GPIB adapter | ✓ pushed |
| ✓ Done | Filter Characterization + Group Delay (#32) | HP 8712B | Ethernet-GPIB adapter | ✓ pushed |
| ✓ Done | Antenna Feed-Point Impedance R+jX (#33) | HP 8712B | Ethernet-GPIB adapter | ✓ pushed |
| ✓ Done | Bubba Detector (#95) — multi-band handheld radio scanner | RTL-SDR | RTL-SDR + wideband antenna | local only |

---

## Future Projects — HP 8712B Vector Network Analyzer

These projects require the HP 8712B VNA (300 kHz–1.3 GHz, HPIB/GPIB interface) and an
Ethernet-GPIB adapter (e.g., Prologix GPIB-ETHERNET or Agilent 82357B + USB bridge). The
HP 8712B performs full two-port SOLT calibration and returns complex (magnitude + phase)
S-parameters — capabilities fundamentally beyond what the Siglent instruments offer.

The key distinction from the existing scalar-vna and rf-impedance projects is phase. The
Siglent tools measure amplitude only. The HP 8712B returns full complex S-parameters, enabling
Smith charts, group delay, true Z = R + jX vs. frequency, and stability circle calculations
that all require phase information.

---

### ✓ 26. HP GPIB Driver — *rf-bench-drivers-hp*

A new `rf_bench.hp` driver subpackage for the HP 8712B over Ethernet-GPIB. This is the
enabler for all other HP 8712B projects.

**Interface:** The HP 8712B speaks HP-IB (IEEE-488.1/GPIB). Ethernet-GPIB adapters
(Prologix, Agilent/Keysight GPIB-ETHERNET) present a TCP socket that accepts GPIB commands
and returns responses. The driver wraps this socket exactly like the Siglent drivers — raw
TCP, no pyvisa — and follows the same patterns established in `rf_bench.siglent`.

**Core operations the driver must expose:**

- `identify()` — `*IDN?`, return model string
- `set_start(freq_hz)` / `set_stop(freq_hz)` / `set_center(freq_hz)` / `set_span(freq_hz)`
- `set_points(n)` — sweep point count (3–1601)
- `solt_cal_sequence()` — interactive SOLT: prompt operator for each standard, commit cal
- `save_cal(path)` / `load_cal(path)` — persist calibration to JSON for repeat use
- `get_frequencies()` → numpy array of frequency points
- `get_s_param(param)` → complex numpy array for `'S11'`, `'S21'`, `'S12'`, or `'S22'`

**Calibration note:** SOLT calibration is stored in the 8712B's firmware. The driver
initiates a cal sequence that prompts the operator ("connect OPEN at port 1, press Enter"),
then sends the corresponding GPIB command for each standard. After all four standards
(OPEN, SHORT, LOAD, THRU), the 8712B applies the error model automatically to all
subsequent S-parameter reads.

**GPIB adapter quirks to handle:** Prologix adapters require explicit EOI and EOS settings;
some responses need a delay before reading. The driver must handle variable-length IEEE 488.2
binary block responses and ASCII CSV responses from older 8712B firmware revisions.

**Effort:** Medium. The GPIB protocol and 8712B command set are well-documented. Initial
bring-up should be done with a simple `*IDN?` + single-frequency S11 spot measurement before
attempting a full sweep or calibration sequence.

---

### ✓ 27. Full S-Parameter Suite (HP 8712B)

Complete two-port vector S-parameter characterization for any two-port device: filters,
amplifiers, attenuators, splitters, balun cores, matching networks, or PCB traces.

**Measurements:**

- **S11 (input reflection):** Complex reflection at port 1, port 2 matched. Magnitude =
  return loss (same as scalar VNA, but now with phase). Plotted on Smith chart.
- **S21 (forward transmission):** Complex gain/loss from port 1 to port 2. Magnitude =
  insertion loss or gain; phase = transmission phase vs. frequency.
- **S12 (reverse transmission):** Transmission in reverse direction. For passive symmetric
  devices S12 = S21; for amplifiers, S12 = reverse isolation.
- **S22 (output reflection):** Reflection at port 2 with port 1 matched.

**What the HP 8712B adds over the scalar VNA project:**

- Phase information on all four parameters — directly enables group delay, Smith chart
  display, and true complex impedance
- Full two-port SOLT calibration removes cable, connector, and fixture errors simultaneously
  from all four S-parameters
- No separate injection circuit needed for impedance — calibrated S11 gives Z directly
- Touchstone (.s2p) file export for import into QUCS, Keysight ADS, or other simulators

**Output:** Four S-parameter magnitude subplots + Smith chart for S11 and S22 + S21 phase
vs. frequency. Touchstone .s2p file saved alongside the plots.

**Effort:** Low once the driver is working. matplotlib complex S-parameter plotting and
Touchstone file writing are straightforward.

---

### ✓ 28. Group Delay Measurement (HP 8712B)

Computes group delay from the S21 phase response:
`τ_g(f) = −d(φ)/d(ω) = −(1 / 2π) · d(φ)/df`

**Why group delay matters:**

A filter with flat gain but non-constant group delay distorts wideband signals — the classic
ringing after a square wave through a Chebyshev filter. SSB transmitters with non-linear
group delay in the audio chain produce sideband distortion correctable only by measuring the
phase response directly. SAW filters, helical filters, and coupled-cavity filters have highly
non-linear group delay near band edges; quantifying this determines the usable bandwidth.
Transmission lines have constant group delay for ideal coax but exhibit variations near
resonances — this identifies stubs, bad connectors, and cable damage.

**Technique:** Direct from S21 phase data. The HP 8712B returns unwrapped phase vs.
frequency as a complex array. Differentiate numerically with `numpy.gradient` and apply
mild smoothing.

The 8712B also has a built-in group delay display mode (`GDELAY`); the driver can request
this directly rather than computing from raw S21 phase, and the results can be compared as
a self-check.

**Display:** Three-panel: S21 magnitude (dB), S21 phase (degrees, unwrapped), group delay
(ns). Optional passband group delay ripple marker: click two frequencies, report peak-to-peak
delay variation in the passband.

**Effort:** Very low once S-parameter data is available from project 27. Group delay is a
direct numerical derivative of the phase data already in hand.

---

### ✓ 29. True RF Impedance Analyzer + Smith Chart (HP 8712B calibrated S11)

Derives complex impedance Z = R + jX at every frequency point from calibrated S11.
Plots on both a Cartesian (R, X vs. frequency) axes and a Smith chart.

**Conversion formula:**
`Z(f) = Z0 · (1 + S11(f)) / (1 − S11(f))`   where Z0 = 50 Ω.

**Advantage over the existing rf-impedance project:**

The current rf-impedance tool uses a two-channel scope and series injection circuit. It works
from 100 kHz to ~10 MHz but is limited by:
- Phase accuracy of the scope's two channels (ADC skew, channel-to-channel drift)
- Injection circuit parasitics at higher frequencies
- Need for a separate fixture and careful calibration at each frequency

The HP 8712B with SOLT calibration removes all these limitations: the calibration reference
plane is at the DUT connector, and the 8712B's internal DSP handles the complex arithmetic
to 1.3 GHz with no external fixture needed.

**Applications:** Antenna feed-point characterization, inductor/capacitor equivalent circuit
modeling at operating frequency, ferrite core impedance vs. frequency, balun winding
impedance, matching network design and verification.

**Display:** Three panels: |Z| vs. frequency, R and X on Cartesian axes (with ±50 Ω
reference lines), and Smith chart showing the full Z locus from start to stop frequency.
Phase angle θ and quality factor Q(f) derived and annotated at each point.

**Effort:** Very low once the driver and S-parameter data path are established. Z from S11
is one formula; Smith chart is a standard matplotlib projection available in the `scikit-rf`
library or implementable in ~50 lines.

---

### ✓ 30. Transistor S-Parameter Characterization (HP 8712B + bias fixture)

Measures S-parameters of a discrete transistor (BJT, JFET, MOSFET, GaAsFET) at its intended
operating bias, then computes stable gain, stability, and maximum available gain.

**Required fixture:** A small PCB that biases the device at the test Q-point while blocking
DC from the HP 8712B ports. Typical construction: bypass caps on the supply rail, RF chokes
on the DC bias lines, SMA connectors at the base/gate and collector/drain. A stripboard
build-up works for evaluation; fixture parasitics are de-embedded by SOLT calibration with
the fixture in-circuit.

**Computed parameters:**

- **Maximum available gain (MAG):** `|S21|² / ((1 − |S11|²)(1 − |S22|²))` — upper bound
  on transducer gain achievable with conjugate matching at both ports.
- **Stability factor K (Rollett):** `K > 1` and `|Δ| < 1` → unconditionally stable at
  that frequency. `K < 1` → potentially unstable; oscillation is possible without careful
  source/load termination.
- **Stability circles on Smith chart:** Show the boundary of source and load impedances that
  cause oscillation. Plot the stability boundary so the PA or LNA designer can see the safe
  operating region and avoid it in the matching network design.
- **Unilateral figure of merit U:** Quantifies how much reverse transmission (S12) perturbs
  the unilateral gain approximation. U < 0.1 → unilateral approximation is valid to within
  ±1 dB.

**Output:** MAG vs. frequency, K vs. frequency (with K = 1 reference line), stability
circles on Smith chart at the frequency of interest.

**Useful for:** Evaluating surplus RF transistors before designing around them, characterizing
Chinese-surplus parts (BFR93, BFR505, 2N5109, MRF171) against datasheet values, pre-screening
transistors for low-noise amplifier designs, confirming a PA transistor is unconditionally
stable at the intended operating frequency.

**Effort:** Medium. S-parameter measurement is project 27. The gain and stability
calculations are standard RF design textbook math (Pozar Chapter 12). Stability circle
geometry on the Smith chart is slightly more involved but well-documented.

---

### ✓ 31. Transmission Line Characterizer (HP 8712B)

Complete electrical characterization of a coaxial cable or transmission line: velocity
factor, characteristic impedance Zo, attenuation vs. frequency α(f), and propagation
constant γ = α + jβ, from 300 kHz to 1.3 GHz.

**Why this is better than TDR for this purpose:**

The existing TDR project identifies impedance discontinuities and approximate electrical
length. It does not give Zo in ohms, does not resolve α(f) vs. frequency, and is limited
by the SDG's ~5 ns rise time (~100 MHz bandwidth). The HP 8712B gives all four parameters
continuously across the full frequency range.

**Technique:**

Measure S11 twice at port 1: once with port 2 open, once with port 2 shorted.

```
Z_oc = Z0 · (1 + S11_open)  / (1 − S11_open)
Z_sc = Z0 · (1 + S11_short) / (1 − S11_short)
Zo   = sqrt(Z_oc · Z_sc)                          # characteristic impedance
γ    = (1/L) · arccosh((Z_oc + Z_sc) / (2·Zo))   # propagation constant; L = physical length
α    = Re(γ)                                       # attenuation per metre
β    = Im(γ)                                       # phase constant per metre
VF   = c / (β / (2π·f))                           # velocity factor
```

**Output:**

- Velocity factor VF(f) — typically 0.65–0.84 for coax; slight frequency dependence expected
- Zo(f) — flat at nominal impedance for good cable; deviations indicate dielectric
  non-uniformity or manufacturing variance
- α(f) in dB/100m — skin-effect slope (α ∝ √f) vs. dielectric loss slope (α ∝ f) are both
  visible; their ratio reveals whether loss is conductor-dominated or dielectric-dominated
- Total insertion loss for the specific cable at any frequency (useful table to keep)

**Practical use:** Evaluating surplus coax (RG-8X, LMR-400 clones, mystery bulk spool)
before using it for a VHF/UHF antenna feedline. Comparing known-good vs. water-damaged coax.
Characterizing home-wound transmission line transformers (baluns wound with coax).

**Effort:** Medium. The two-port measurements are straightforward; extracting ABCD
parameters from S-parameters and solving for Z0 and γ requires careful attention to sign
conventions and branch cuts in the arccosh.

---

### ✓ 32. Filter Characterization + Group Delay (HP 8712B)

Complete characterization of any 2-port filter: passband ripple, stopband rejection, shape
factor, insertion loss, return loss, and passband group delay — from 300 kHz to 1.3 GHz.

**What this adds beyond the scalar VNA project:**

The scalar VNA (SSA + RB3X25) measures S21 and S11 amplitude only. The HP 8712B adds phase
response → group delay, which the scalar VNA fundamentally cannot produce. For filter
evaluation, group delay in the passband is as important as amplitude: a Chebyshev filter
with excellent rejection may have severe group delay peaking near its band edges that makes
it unusable for wideband digital signals, while a Bessel filter with poorer rejection has
constant group delay and may be the better choice.

**Key measurements:**

- Passband: S21 flatness, ripple (dB peak-to-peak), insertion loss, S11/S22 return loss
- Stopband: rejection at specified offset frequencies, ultimate stopband level
- Shape factor: ratio of 60 dB bandwidth to 3 dB bandwidth (indicates filter order/topology)
- Group delay: peak-to-peak variation in passband, slope and symmetry
- Multi-level bandwidth markers: −1 dB, −3 dB, −6 dB, −10 dB, −40 dB, −60 dB

**Automated pass/fail:** Input a filter specification (passband loss ≤ X dB, stopband ≥ Y dB
from F1 to F2, group delay variation ≤ Z ns) and the script produces a pass/fail report with
markers at failing points.

**Useful for:** Evaluating surplus bandpass filters before installing them in receive paths,
characterizing homebrew LC or helical filters, validating crystal ladder filter designs
against SPICE simulation, comparing PIN diode vs. relay switched filter banks in terms of
both amplitude and phase response.

**Effort:** Very low once the S-parameter suite (project 27) and group delay (project 28)
are implemented. Filter parameter extraction is marker placement on existing data.

---

### ✓ 33. Antenna Feed-Point Impedance (HP 8712B calibrated S11 → R + jX)

Measures the complex impedance seen at an antenna's feed connector vs. frequency. The
primary use case: characterize a homebrew antenna before connecting it to the transmitter,
understand what the matching network must transform, and verify the match after tuning.

**What it measures:**

- Z(f) = R(f) + jX(f) — resistance and reactance vs. frequency
- VSWR vs. frequency (derived from S11 magnitude)
- Return loss vs. frequency (S11 magnitude in dB)
- Resonant frequency (where X = 0)
- Feed-point impedance at resonance (R + j0 at the self-resonant dip)

**How it improves on the existing signal-analyzer project:**

The scalar signal analyzer (SSA + RB3X25) measures VSWR and return loss. It can find the
resonant frequency and plot VSWR, but it cannot say whether the antenna is inductive or
capacitive at a given frequency, or what the radiation resistance is at resonance. The HP
8712B gives full R + jX, so the engineer can say "at 14.1 MHz, Z = 42 + j28 Ω — I need
−j28 Ω of reactance from the matching network" rather than just "VSWR is 2.1:1."

**Calibration:** SOLT calibration at the end of the measurement cable, not at the
instrument. This de-embeds the cable and places the reference plane at the antenna connector.
For a portable antenna measurement kit, a small SOLT standard set (SMA OPEN/SHORT/LOAD
caps) at the end of a known good jumper gives a portable field measurement capability.

**Output:** Smith chart (Z locus vs. frequency), R and X on Cartesian axes, VSWR curve
(backwards-compatible with signal-analyzer output format), resonant frequency markers with
exact Z at each resonance.

**Effort:** Very low once projects 26 and 29 are implemented. This is project 29 applied to
an antenna as the DUT, with VSWR output added for backwards compatibility with signal-analyzer
workflows.

---

---

## Future Projects — Solartron 7151 6.5-Digit DMM (1985, IEEE-488)

These projects require the Solartron 7151 (or its 7150 / 7150-plus siblings) and the
same KISS-488 Rev 2 Ethernet-GPIB adapter used by the HP 8712B VNA. The 7151 is a
6.5-digit bench DMM with full DC voltage (200 mV–2 kV), AC voltage, kΩ (20 k–20 M),
and DC/AC current ranges. Resolution scales with integration time:

| Integration | Resolution | Use case |
|------------|-----------|----------|
| 6.7 ms (I0) | 3.5 digits | Free-running, high speed |
| 40 ms (I1) | 4.5 digits | 50 Hz line-cycle averaging |
| 50 ms (I2) | 4.5 digits | 60 Hz line-cycle averaging |
| 400 ms (I3) | 5.5 digits | General bench measurement |
| 1.6 s (I5) | 5.5 digits | Filter-on, low-noise |
| ~8 s (I4) | 6.5 digits | "Walking window" — best resolution |

The complementary case to the 4.5-digit Siglent SDM3045X: when the project genuinely
needs 6.5-digit precision (TCR measurements, voltage-reference characterization, low-
level offset hunting), this is the bench DMM that delivers it. The driver
(`rf_bench.solartron.Solartron7151`) is implemented from documentation; hardware
verification and the projects below are blocked on the KISS-488 adapter being installed.

---

### Solartron GPIB Driver — *rf-bench-drivers-solartron* — code complete, untested

A `rf_bench.solartron` driver subpackage for the Solartron 7151 over Ethernet-GPIB.
Implements the full 1985-vintage shortform command set (single ASCII letters with
integer arguments) extracted directly from the User Manual ND/7151/2 Issue 2 (1985)
and the GPL-2.0 open-source `s7150` C reference driver by Joerg Hau (which works
against 7150, 7150-plus, and 7151 with the same code). Includes calibration commands
(HI/LO/WRITE/REFRESH) gated behind a 2.5 mm CAL shorting plug.

**Interface:** Same KISS-488 Rev 2 adapter as the HP 8712B, port 1234. Important
caveat: the 7151's default GPIB primary address (set by rear-panel DIP switches) and
the HP 8712B's are both 16. They cannot share the same bus on the same address.
Either move the 7151 (or the HP) to a different address, or only have one of them
powered on at a time during early bring-up.

**First-power-on bring-up plan:**

1. Set GPIB DIP switches on the 7151 to a non-conflicting address (e.g., 5).
2. `++mode 1` / `++addr 5` / `A` (DCL) / wait 2 s for the RESTART message.
3. Switch to `U7N0T1` (CR delimiter, literals on, tracking on).
4. `M0R0I3` (DCV, autorange, 5.5 digits) → first reading.
5. Verify reading parser handles both `LITERALS ON` (`"+ 2.798450 V DC ..."`) and
   `LITERALS OFF` (`"+ 2.798450"`) forms, and that the `!` overload flag is detected.

---

### Solartron 6.5-Digit Voltage-Reference Logger

Long-term drift logger for precision voltage references (LM399, LTZ1000, MAX6126, etc.).
The Solartron 7151 at 6.5 digits (~8 s integration) provides ~1 ppm absolute resolution
on its 2 V range, enough to track the 1–10 ppm/yr drift of a temperature-compensated
zener over weeks of logging. SQLite log + matplotlib drift plot. Compares multiple
references on the same DUT board if a relay multiplexer (XL9535) is added.

**Hardware:** Solartron 7151 (DCV mode, 2 V range, I4 = 8 s integration), XL9535 relay
board (optional, for N-up reference comparison), SPD3303X-E PSU to power the references.
GPS-disciplined timestamping via `rf_bench.gpsd` for metrologically traceable timing.

**Why the 7151 specifically:** the 4.5-digit SDM3045X tops out at ~10 ppm resolution on
the 10 V range, which is coarser than the drift you're trying to measure. This is the
canonical case where 6.5 digits matters.

---

### TCR Bridge — Temperature Coefficient of Resistance via Two DMMs

The 7151's 6.5-digit kΩ measurement combined with the 4-wire Kelvin capability of the
SDM3045X enables a high-resolution TCR measurement: place the DUT in a temperature-
controlled chamber (or simply on a Peltier element with a thermocouple), sweep
temperature, log `R(T)`. Compute `(1/R0) · dR/dT` in ppm/°C across the range.

The 7151 measures the DUT (high resolution); the SDM3045X measures the chamber
thermocouple (good enough for ±0.1 °C). Existing `projects/dmm/tcr/` would gain a
`--use-7151` flag selecting the 6.5-digit DMM as the resistance instrument.

---

### 6.5-Digit Contact Resistance Tester

The existing `projects/dmm/contact/` measures contact / connector resistance with the
4.5-digit SDM3045X. Sub-milliohm contact resistance (gold-on-gold connectors, RF coax
center-pin contact) is below the SDM3045X's noise floor on the 200 Ω range. Switching
the same project to the Solartron 7151 on its 20 kΩ range with 6.5-digit averaging
gets you ~10 µΩ resolution after averaging — adequate for matched-pair connector
selection or aging studies.

---

### Calibration Verification of the 7151 Itself

The 7151's own internal calibration is performed via CALIBRATE ON / HI / LO / WRITE
commands against external calibrator references. The driver exposes these as
`calibrate_on()` / `cal_hi(count)` / `cal_lo(count)` / `cal_write()`. A future
project could automate the full annual calibration sequence using the SPD3303X-E
plus a precision shunt as the calibration source for low-current and low-voltage
ranges, and a dedicated calibrator (Fluke 5500A or equivalent — not in the lab) for
the rest. This is more of a maintenance procedure than a project.

---

## Future Projects — Koolertron / MHinstek MHS-5225A DDS Generator + Counter

The Koolertron / MHinstek MHS-5200A series is a low-cost dual-channel DDS
function generator with a built-in frequency counter and sweep generator.
It's wildly rebranded (KKmoon, AliExpress "200MSa/s 12Bit DDS", various eBay
listings); the unit on the bench identifies as **MHS-5225A** (25 MHz CH1 sine
limit, raw model code `5225A5040000`). The driver is fully implemented and
tested as of 2026-06-08.

What it adds to the bench that wasn't there before:

- **A second function generator** complementing the SDG1062X. The SDG is
  cleaner (better phase noise, more sample memory, true AWG with 14-bit DAC at
  300 MSa/s) but only has 2 channels total; pairing the SDG and the MHS-5225A
  gives **4 simultaneous independent signal channels** for things like
  intermodulation testing and vector-source approximations.
- **A built-in frequency counter** — useful as a sanity check on any other
  generator's commanded vs actual output, or as a standalone counter for
  external signals on its EXT IN.
- **Internal sweep mode** that runs autonomously without a controller — useful
  for one-shot scalar transfer-function plots when paired with a scope or SSA.

---

### MHS-5225A Two-Tone IMD Source

Drive CH1 + CH2 at f1 and f2 (≈100 kHz apart, both in some target band) into
a hybrid combiner, feed the resulting two-tone composite into a DUT, and
measure the IM3 products on the SSA3032X. Pure software project — uses
`rf_bench.koolertron` for the source side and `rf_bench.siglent` for the
analyzer. The MHS-5225A has independent phase per channel, which is required
for repeatable two-tone work.

**Hardware:** MHS-5225A, hybrid combiner (Mini-Circuits ZFSC-2-1+ or
equivalent at ~1 MHz–1 GHz; or wound bifilar at HF), DUT, SSA3032X.

---

### MHS-5225A as Backup Frequency Reference Counter

When the Siglent SSA's frequency-marker readout is suspect (or just for
cross-checking), the MHS-5225A's counter can be patched onto the same source
via a power splitter and read out independently. ~7 ppm uncalibrated TCXO
accuracy from the MHS-5225A; better than that if compared against the
GPS-disciplined Si5351 reference (already in the project map under
`projects/gps/freq-cal/`).

---

### Bring-up Test Project — MHS-5225A Validation Sweep

A simple `projects/signal-sources/koolertron-validation/` script that drives
each waveform / each frequency decade / each amplitude setting on each
channel, captures the result on the SDS2504X scope (FFT for spectral
purity), and produces a one-shot validation report. Useful both for verifying
new units coming off AliExpress and for periodic calibration drift checks.

---

### MHS-5225A Sweep + Scope Bode Plotter

The unit can sweep linearly or logarithmically without controller intervention.
Combined with the SDS2504X scope's measured-amplitude readback, this enables
a Bode plot capture without driver-level sweep timing — let the MHS-5225A
sweep autonomously while the scope captures envelope versus time, then map
time → frequency from the sweep parameters. Less precise than an SDG-driven
software-stepped sweep, but ~10× faster.

---

## Single-Instrument Automation Ideas

These projects exploit one instrument's automation potential: leaving it running unattended for hours, measuring many components in rapid sequence without fatigue, or computing statistics across hundreds of acquisitions. The core insight is that SCPI gives you the instrument's full internal state without manual interaction — enabling capabilities that are impractical at the bench but trivial in software. Most require no cable reconfiguration beyond the initial setup.

---

### ✓ 58. Component Sorting Station — *rf-bench-dmm-sorter*

**Instrument: SDM3045X only.**

Reads resistance, capacitance, or diode Vf from the DMM continuously while you probe components one at a time. After each stable measurement, the script announces the bin assignment — nearest E12 or E24 value, actual deviation from nominal — and logs the result to CSV. Eliminates the read-interpret-write cycle of manual sorting.

**Trigger mechanism:** DMM is polled continuously. A new reading is registered when it differs from the previous by more than a dead-band threshold (e.g., > 5%), then declared stable when three consecutive readings agree within 0.1%. This debounces probe lift/touch without requiring a button press.

**Modes:**
- **Resistance (2-wire):** 100 Ω–10 MΩ, matches nearest E12/E24 value, reports deviation %.
- **Resistance (4-wire Kelvin):** 0.1 mΩ–100 Ω, eliminates probe lead resistance for precision resistors and current-sense shunts.
- **Capacitance:** matches nearest E12 capacitor series. Useful for sorting C0G/NP0 caps for filter builds.
- **Diode Vf:** records forward voltage at the DMM's test current — useful for matching Schottky diodes for ring mixers and balanced detectors.

**Audio output:** System bell pattern encodes the bin (1 beep = bin 1, 2 beeps = bin 2, …). Eyes stay on the component being probed, not the screen. Out-of-tolerance parts get a distinct long tone.

**Output:** CSV: timestamp, measured value, nearest E-series value, deviation_pct, pass_fail. End-of-session summary: N components, distribution across bins, outlier count.

**Why automation matters:** Sorting 100 SMD resistors into 1% bins at one component per 5 seconds manually takes 8 minutes with hand-written logs. With this script, logs are automatic, errors are impossible, and the distribution report is instant. The Kelvin mode gives sub-milliohm resolution unavailable in any other single-instrument workflow in this bench.

**Effort:** Very low. DMM SCPI read loop is trivial; E-series matching and bin audio are ~50 lines of Python.

---

### ✓ 59. Temperature Coefficient of Resistance — *rf-bench-dmm-tcr*

**Instrument: SDM3045X only.**

Measures a passive component's resistance vs. temperature using only the bench DMM. The SDM3045X can measure resistance on its main terminals and temperature via its thermocouple input. By rapidly alternating between modes via SCPI (mode switch takes ~100 ms, fast relative to typical thermal time constants of several seconds), the script builds a synchronized R vs. T log without any additional hardware.

**Setup:** Clip leads or 4-wire Kelvin probes to the component under test. Type K thermocouple probe pressed against or clipped to the same component. Apply thermal stimulus: heat gun, lab oven, or natural room temperature variation overnight.

**Measurement loop:**
```python
while running:
    dmm.set_function("RESISTANCE_4W")
    r_ohm = dmm.measure()
    dmm.set_function("TEMP_TC_K")
    temp_c = dmm.measure()
    log(time.time(), temp_c, r_ohm)
    time.sleep(interval_s)
```

**Output:**
- Plot: resistance deviation (ppm from R at 25 °C) vs. temperature (°C)
- Linear regression → TCR in ppm/°C
- Thermistor: β-coefficient fit (R = R₀ · e^(β(1/T − 1/T₀)))
- RTD: Callendar-Van Dusen fit for Pt100/Pt1000 calibration

**Comparison to osc-tc (#37):** The Bus Pirate + MCP9808 approach measures oscillator frequency vs. temperature and requires the SSA, Bus Pirate, and an external sensor. This project requires only the DMM — no additional hardware — and targets passive components rather than oscillators. Applications: characterizing precision resistors in a bridge or feedback network, verifying matched resistor pairs for low-TCR dividers, qualifying thermistors before embedding them in a sensor circuit.

**Effort:** Very low. Mode switching via SCPI is a single command; polynomial fits are one numpy call.

---

### ✓ 60. Kelvin Contact Resistance Survey — *rf-bench-dmm-contact*

**Instrument: SDM3045X only.**

Uses the DMM's 4-wire Kelvin mode to systematically log contact resistance across connector pins, relay contacts, RF switch contacts, PCB vias, and solder joints. The 4-wire mode eliminates probe lead resistance, giving reliable readings below 1 mΩ — impossible with 2-wire measurement.

**Applications:**
- **Multi-pin connector audit:** Probe every pin of a D-sub, RJ45, or SMA connector. Script increments the pin counter automatically and prompts for the next contact. Report flags any pin exceeding a threshold (> 100 mΩ indicates a marginal crimp or oxidation).
- **Relay contact wear:** Log contact resistance at the start and end of an endurance test. Upward drift → oxidation or arc damage.
- **RF relay characterization:** A good-quality RF relay has < 50 mΩ contact resistance; a marginal one may be 200–500 mΩ. At HF power levels, P = I²R — a 500 mΩ contact in a 100 W signal path is a thermal problem.
- **PCB via resistance:** Kelvin clip across a via; a cracked via shows elevated or erratic readings. Good vias are typically < 5 mΩ.
- **Solder joint audit:** QC for current-sense shunt pads or critical RF connector solder joints.

**Output:** CSV: user-supplied label per probe point, timestamp, measured resistance in mΩ, pass/fail for a configurable threshold. Summary: min, max, mean, σ, fail count.

**Effort:** Very low. Identical loop to the component sorter; the 4-wire mode is a single SCPI command difference (`CONF:FRES` vs. `CONF:RES`).

---

### ✓ 61. Eye Diagram Builder — *rf-bench-scope-eye*

**Instrument: SDS2504X Plus only.**

Captures many triggered waveform frames of a serial data signal and overlays them in Python to produce an eye diagram — the standard tool for digital signal integrity. Works for any serial data stream: UART, SPI, CAN bus, LVDS differential pairs, or any custom logic.

**Technique:**
1. Configure scope trigger on the rising edge of the data signal at the appropriate threshold voltage.
2. Set timebase to show 1.5–2 bit periods (e.g., 10 µs/div for UART at 115200 baud).
3. Capture N waveforms (100–500) via the established `capture_waveform()` call in the scope driver.
4. Time-align each numpy array to the center of the first detected transition using linear interpolation for sub-sample precision.
5. Overlay all arrays in matplotlib. The overlapping traces form the eye.

**What the eye reveals:**
- **Eye height:** worst-case vertical margin between logic high and low at the sampling instant. Thin eye → noise or reflections.
- **Eye width:** horizontal opening at the decision threshold. Narrow eye → timing jitter is closing the sampling window.
- **Crossing symmetry:** where transitions cross the decision level. Off-center → asymmetric rise/fall (impedance mismatch or parasitic capacitance).
- **Jitter histogram:** extract crossing times across all frames, build a distribution. A bimodal histogram indicates deterministic jitter (EMI or crosstalk) vs. Gaussian random jitter.

**Scope setup automation:** The script auto-selects timebase and voltage scale from user-supplied baud rate and signal swing. No manual scope adjustment needed.

**Effort:** Low. Scope capture and waveform download are established. Time-alignment via edge detection is ~15 lines of numpy. Eye overlay is standard matplotlib.

---

### ✓ 62. Glitch / Anomaly Trap — *rf-bench-scope-glitch*

**Instrument: SDS2504X Plus only.**

Configures the scope to watch for rare trigger events — supply voltage spikes, runt pulses, clock dropouts — and saves every captured waveform to disk with a timestamp. Runs unattended for hours or overnight. In the morning, you have a complete timestamped record of every anomalous event.

**Trigger modes:**
- **Voltage threshold:** trigger when a channel exceeds or drops below a level (supply spike, brownout).
- **Pulse width:** trigger on pulses narrower or wider than a specified window (runt pulses on a clock line, glitched data frames).
- **Edge dropout:** trigger when expected edges stop appearing for longer than a timeout (oscillator stall, bus lockup).

**Operation:**
```python
scope.set_trigger_mode("normal")   # hold until event, no auto-sweep
scope.set_trigger_level(threshold)
scope.arm_trigger()
while True:
    if scope.trigger_has_fired():
        waveform = scope.capture_waveform(channel=1)
        save_npz(f"glitch_{time.time():.3f}.npz", waveform)
        log_event(timestamp, peak_v, pulse_width)
        scope.arm_trigger()        # re-arm for next event
```

**Output per capture:** numpy .npz waveform + event log with timestamp, peak voltage, pulse width, and inter-event time. Optional SMS alert when N events have accumulated (via `~/money/sms.py`).

**Why automation over the scope's built-in single-trigger:** The scope's internal record memory holds a fixed number of captures. Python removes that limit — captures go to disk indefinitely. The event log enables analysis across all captures: do events cluster in time? Is the inter-event interval periodic (suggesting a systematic source) or random?

**Practical use:** Leave running on a prototype that crashes intermittently. In the morning, review exactly what happened on the supply rail or clock line at each crash event. Without the trap, you'd stare at the scope indefinitely hoping to catch the glitch manually.

**Effort:** Low. Trigger status polling and waveform download are established in the scope driver. Glitch/runt trigger SCPI commands need verification against SDS2504X Plus firmware (`TRIGger:GLITch` or `TRIGger:RUNT` modes).

---

### ✓ 63. Power Rail Sequencer — *rf-bench-psu-sequencer*

**Instrument: SPD3303X-E only.**

Executes precise power-on and power-off sequences across the SPD's channels with user-defined timing. Essential for multi-rail IC bring-up — FPGAs, DDR memory controllers, complex SoCs — where supply rails must appear in a specific order within specific timing windows.

**Why sequencing matters:** Many ICs latch up or fail to initialize if rails appear out of order. An FPGA typically requires core voltage (VCCINT) before I/O voltage (VCCO). A DDR controller needs VDD before VDDQ. Done manually, this requires coordinating two separate button presses — unrepeatable and error-prone.

**Sequence definition (JSON):**
```json
{
  "name": "FPGA board bring-up",
  "steps": [
    {"t_ms":   0, "ch": 1, "action": "on",  "volts": 1.0, "ilim_a": 0.5},
    {"t_ms":  10, "ch": 2, "action": "on",  "volts": 3.3, "ilim_a": 1.0},
    {"t_ms":  50, "ch": 1, "action": "set", "volts": 1.2},
    {"t_ms": 500, "ch": 2, "action": "off"},
    {"t_ms": 510, "ch": 1, "action": "off"}
  ]
}
```

**Extensions:**
- **Repeat mode:** cycle power N times with configurable dwell time (power-cycling endurance test).
- **Abort on overcurrent:** if any channel draws more than expected at a given step, halt the sequence immediately before proceeding — catches partial bring-up failures before damaging further circuitry.
- **Log actual timestamps:** record the actual measured time of each step vs. the programmed delay; reveals SPD SCPI response latency.

**Effort:** Very low. SPD3303X-E SCPI channel control is established from the PSU characterizer. The sequence engine is a sorted event loop — under 40 lines of Python.

---

### ✓ 64. FM Broadcast Propagation Monitor — *rf-bench-ssa-fm-monitor*

**Instrument: SSA3032X Plus only.**

Sweeps the FM broadcast band (87.5–108 MHz) on a timed loop and logs all station signal levels vs. time. Produces a propagation waterfall revealing which stations are present, at what levels, and when distant stations appear due to tropospheric ducting. Entirely passive — no tracking generator or external signal source required.

**Operation:**
1. SSA sweeps 87.5–108 MHz at RBW = 30 kHz (resolves adjacent FM channels separated by 200 kHz).
2. Python reads the spectrum, peak-detects all carriers above a configurable threshold.
3. Identifies each peak by frequency ± 100 kHz, records peak level in dBm.
4. Logs: timestamp × frequency → power matrix (same .npz format as band_occupancy #21).
5. Waterfall display: x=frequency (MHz), y=time (newest at top), color=level (dBm).

**What it reveals:**
- **Local RF environment baseline:** which FM stations are permanently present and at what levels, before deploying any VHF equipment in this frequency range.
- **Tropospheric ducting:** when a distant FM station appears at a normally-empty frequency — a classic indicator of a tropo propagation event. Summer mornings, coastal paths, high-pressure systems.
- **Multipath signatures:** a station whose level oscillates by > 10 dB in minutes → multipath between the direct path and a reflection (aircraft, vehicle, or troposcatter).
- **Interference sources:** unknown carriers at non-standard FM channel spacings or appearing only at specific times of day.

**Alert mode:** When any frequency that was below threshold in the baseline scan exceeds a threshold (new station appeared), send SMS via `~/money/sms.py`. Passive overnight monitoring with notification.

**Effort:** Very low. The SSA sweep loop and peak-finding exist in band_occupancy (#21). New code: FM band span, station-labeling, and alert logic — approximately 40 lines.

---

---

## New Multi-Instrument Combinations

---

### ✓ 65. Thermal Resistance Characterizer — *rf-bench-thermal-rth*

**Instruments: SPD3303X-E + SDM3045X.**

Measures the thermal resistance (θ_JA, θ_JC, θ_SA) of a transistor package, linear regulator, heatsink, or thermal interface material. The SPD provides precisely controlled DC power to the device under test; the DMM's thermocouple input reads the case or heatsink surface temperature. Result: θ = ΔT / P in °C/W — the number that determines whether a part will survive at its operating dissipation.

**Setup:**
```
SPD CH1 → DUT (transistor in resistive dissipation, or LDO with resistive load)
SPD reads back V and I via SCPI → P = V × I (measured, not programmed)
SDM3045X thermocouple probe → DUT case surface (or heatsink face)
```

**Measurement loop:**
1. Set SPD to a dissipation level.
2. Wait for thermal equilibrium: temperature rate of change < 0.1 °C/min (detected by logging temperature over a rolling 60 s window).
3. Record: P_dissipated from SPD V × I, T_case from SDM thermocouple, T_ambient from a stationary reference thermocouple.
4. θ = (T_case − T_ambient) / P_dissipated.
5. Step to the next dissipation level and repeat.

**What this measures:**
- **θ_JA (junction to ambient):** for TO-220/TO-247 without heatsink, in still air.
- **θ_CS (case to heatsink):** compare thermal interface materials — white grease vs. Shin-Etsu X23 vs. graphite pad. A good TIM is 0.2–0.5 °C/W; a poor one is 2–5 °C/W. The difference is directly measurable.
- **θ_SA (heatsink to ambient):** actual thermal resistance in your enclosure vs. the heatsink's datasheet value (which assumes specific fin orientation and airflow conditions you may not have).

**No scope or SSA needed:** this is a DC thermal measurement. The DMM and SPD are entirely adequate.

**Practical value:** Verify that a TO-220 regulator will stay below T_j = 125 °C at your operating dissipation before committing to a layout. Confirm that a surplus heatsink from the parts bin actually meets the datasheet spec under your actual airflow conditions.

**Effort:** Very low. Both instruments are already driven. New code: equilibrium detection (rate of temperature change over a rolling window).

---

### ✓ 66. Component Stress / Aging Monitor — *rf-bench-stress-monitor*

**Instruments: SPD3303X-E + SDM3045X.**

Applies a continuous stress voltage to a component while the DMM periodically measures a key parameter — capacitance, resistance, or voltage — and logs it over hours or days. Reveals how a component's value drifts under electrical stress, with a specificity that datasheets rarely provide for individual batches.

**Primary application — MLCC capacitance vs. DC bias:**

MLCC capacitors (X5R, X7R, Y5V dielectrics) lose significant capacitance under DC bias — an X5R 10 µF part may measure 4–6 µF at rated voltage. The SPD provides the DC bias; the DMM measures capacitance with bias applied (the DMM's 1 kHz AC test signal rides on the SPD's DC, which is the actual operating condition).

```
SPD CH1 → 1 kΩ isolation resistor → capacitor under test → GND
SDM3045X Cx terminals → across the capacitor
```

```python
spd.set_voltage(1, v_bias)
while True:
    c_uf = dmm.measure_capacitance()
    log(time.time(), v_bias, c_uf)
    time.sleep(interval_s)
```

**Other applications:**
- **Electrolytic cap ESR aging:** run at rated ripple current for 100–500 hours; DMM logs ESR at defined intervals → detect end-of-life before circuit failure.
- **Resistor drift under power:** apply rated dissipation via SPD, log resistance every hour. Wirewound and thick-film types drift differently; this quantifies it for a specific batch.
- **Zener voltage stability:** bias at rated current (SPD CH1 + series resistor), log V_z via DMM → stabilization time after power-on and long-term drift for precision reference applications.

**Output:** CSV + matplotlib plot of parameter vs. time, with stress voltage annotated. SMS alert if drift exceeds a threshold (e.g., > 20% of initial value).

**Effort:** Low. Simpler than the battery tester. Alert logic identical to band_occupancy.

---

### ✓ 67. Inrush Current Profiler — *rf-bench-inrush*

**Instruments: SPD3303X-E + SDS2504X Plus.**

Captures the inrush current transient when a DUT powers on — the surge that flows while input capacitors charge. Essential for fuse sizing, NTC thermistor selection, and hot-plug compliance. Fundamentally different from the PSU characterizer (steady-state regulation) and the battery tester (DC current over minutes).

**Setup:**
```
SPD CH1 (voltage source, current-limited above expected inrush peak) → 0.1 Ω sense resistor → DUT
Scope CH1: voltage across 0.1 Ω sense resistor → I = V / 0.1 Ω
Scope CH2: DUT supply voltage
Trigger: CH2 rising edge (power-on event)
```

**What this measures:**
- **Peak inrush current:** instantaneous peak at power-on. For a capacitive DUT, I_peak = C × dV/dt — can be 10–50× steady-state current.
- **Inrush duration:** how long the peak lasts before settling to steady-state.
- **I²t integral:** `numpy.trapz(i_squared_vs_time)` — energy deposited in a fuse or NTC during inrush. If I²t_inrush > I²t_fuse, the fuse blows on every power-up at normal load.
- **NTC effectiveness:** compare inrush with and without an NTC thermistor in series. Reduced peak and extended settling → direct comparison against the NTC datasheet I²t limit.

**Repeat mode:** Power-cycle N times, overlay all inrush captures. A consistent trace → healthy circuit. Diverging traces → marginal soft-start or intermittent component.

**Hardware:** 0.1 Ω current-sense resistor (wirewound, non-inductive, 1–5 W) in series with the DUT supply. Already in most parts bins.

**Effort:** Low. SPD voltage enable and scope triggered capture are both established. The I²t integral is one numpy call. The sense resistor is a passive fixture.

---

### ✓ 68. Radio Audio Chain Tester — *rf-bench-audio-chain*

**Instruments: SDG1062X + IC-7300 (via USB audio — no scope or SSA required).**

Injects a calibrated audio tone from the SDG into the IC-7300's microphone input and captures the processed audio from the radio's USB audio interface. The IC-7300 presents as a USB audio device on Linux at 48 kSa/s; Python reads PCM data directly via `sounddevice`, eliminating the need for a scope or any RF measurement equipment. Measures audio frequency response, DSP filter shape, ALC compression curve, and transmit audio THD.

**Setup:**
```
SDG CH1 (100 Hz–5 kHz sine, −40 to −20 dBm, BNC) → BNC-to-3.5 mm adapter → IC-7300 MIC input
IC-7300 USB → Linux laptop: sounddevice reads PCM audio in real time
```

**Measurements:**

1. **TX audio frequency response:** Sweep SDG from 100 Hz to 5 kHz in 10 Hz steps. At each step, capture 0.5 s of USB audio, FFT it, extract amplitude at the test frequency. Plot gain vs. frequency. Reveals the radio's transmit audio passband (typically 300 Hz–2.7 kHz for SSB) and any DSP equalization applied.

2. **ALC compression curve:** Fix SDG at 1 kHz, sweep amplitude from −60 dBm to 0 dBm. Measure USB audio output amplitude at each level. Plot output vs. input. Identifies the ALC knee (where compression begins) and headroom before clipping.

3. **TX audio THD:** Set SDG to 1 kHz at a level just below the ALC threshold. FFT the USB audio → measure 2nd harmonic (2 kHz) and 3rd harmonic (3 kHz) relative to the fundamental. A clean SSB transmitter should have < −40 dBc at the audio output. Higher THD indicates microphone preamp saturation or over-driven DSP compression.

4. **DSP/IF filter shape:** Set the radio to CW mode (IF filter = 500 Hz). Sweep SDG from 400 Hz to 1200 Hz in 10 Hz steps. USB audio amplitude vs. frequency reveals the actual IF filter passband: center frequency, −3 dB and −60 dB bandwidths, rolloff slope — directly compared against the claimed specification.

**Why this combination is new:** The existing receiver test suite measures RF sensitivity. This project measures the audio chain from the microphone input to the USB audio output — a completely separate, previously unmeasured signal path. USB audio capture eliminates the need for a scope.

**Dependency:** `sounddevice` Python library. `pip install sounddevice`. No additional hardware beyond a BNC-to-3.5 mm adapter.

**Effort:** Low. SDG frequency sweep is established. USB audio capture via sounddevice is straightforward. FFT processing is identical to the scope-based Bode plotter.

---

### ✓ 69. RF Switch Characterizer — *rf-bench-rf-switch*

**Instruments: Bus Pirate + SSA3032X Plus.**

Programs a digitally-controlled RF switch (SPDT or SP4T) via the Bus Pirate's SPI interface, then measures insertion loss and isolation at each switch position using the SSA's tracking generator. Produces a complete performance map vs. frequency for every switch state — without a VNA.

**Target devices:**
- **PE42020** (pSemi, SPDT, DC–13 GHz): extremely common in SDR receive paths and antenna switch controllers
- **ADRF5020** (Analog Devices, SPDT, DC–20 GHz): found in wideband SDR front-ends
- **F2333** (Qorvo, SP4T): used in LNA + filter bank switch combiners for HF/VHF receivers
- **Generic SMA relay modules** (5V GPIO-controlled via Bus Pirate digital output): characterizable at HF

**Measurement:**
1. SSA TG Out → RF switch input; switch output A → SSA RF In. Normalize against a through reference (TG Out → SSA In directly).
2. Bus Pirate programs the switch to state A via SPI.
3. SSA sweeps the frequency range; records insertion loss at each frequency.
4. Bus Pirate programs the switch to state B (or C, D).
5. SSA measures signal at port B → isolation (leakage from the "on" path into the "off" path).
6. Repeat for all switch positions and isolation pairs.

**Output:** Insertion loss vs. frequency for each switch position (dB), port-to-port isolation vs. frequency for each pair. All positions overlaid. Pass/fail against user-specified limits (e.g., "insertion loss < 1 dB, isolation > 40 dB from 1–100 MHz").

**Why this combination is new:** The Bus Pirate controls the switch state electronically; the SSA measures the RF consequence. Neither instrument alone can do this. A surplus RF switch module claiming 60 dB isolation may only achieve 30 dB at 30 MHz due to PCB coupling — this characterization reveals actual performance before the module is committed to a design.

**Effort:** Low. Bus Pirate SPI writes for each chip are simple 1–3 byte sequences. SSA sweep infrastructure is established. New work: SPI register tables for each supported switch IC.

---

### ✓ 70. Dual-Radio Antenna Isolation Measurement — *rf-bench-antenna-isolation*

**Instruments: IC-7300 × 2 (each connected to a different antenna).**

Measures the isolation between two antenna systems at a station — how much of the signal transmitted on antenna A is received on antenna B. Uses the radios' own calibrated transmit power and S-meter readings, with no external signal source or spectrum analyzer. The result determines what receive protection filtering is required for simultaneous TX/RX operation.

**Setup:**
```
IC-7300 #1: TX → 30 dB fixed attenuator → antenna A feedline
IC-7300 #2: RX → antenna B feedline, AGC off, preamp off, RF gain = max
```

The 30 dB attenuator is mandatory — it reduces the transmitted signal to safe levels at the receive antenna and must be declared in the script's configuration before it will run.

**Measurement per frequency:**
1. IC-7300 #1 transmits a CW carrier at minimum power (typically 100 mW = +20 dBm into antenna A; −10 dBm with the 30 dB pad).
2. IC-7300 #2 reads the S-meter on the same frequency; convert to dBm via the calibrated S-meter table from the receiver test suite.
3. Isolation = (TX power into antenna A, dBm) − (RX power at antenna B, dBm).
4. Script steps IC-7300 #1 to the next frequency via CAT; IC-7300 #2 follows.

**What this reveals:**
- Antenna-to-antenna isolation vs. frequency across the HF spectrum.
- Which bands have sufficient isolation (typically > 60–80 dB needed for full-power TX with simultaneous RX) for concurrent operation without receive protection filters.
- How isolation changes with antenna geometry — useful when evaluating different antenna placements.
- At which frequencies additional filtering (stub traps, bandpass filters) is required before the receive front end.

**Automation adds:** Automatic frequency stepping across all HF bands, S-meter reading at each step, producing a complete isolation-vs.-frequency chart in one unattended run. Without automation, this measurement requires two operators or careful solo coordination.

**Safety note:** Even at 100 mW into a 30 dB pad, signals at very close antenna spacings could exceed safe IC-7300 input levels. The script warns when computed received power at any frequency exceeds −20 dBm and aborts the run if a second attenuator is not declared in the configuration.

**Effort:** Low. Both IC-7300 drivers are implemented. The measurement is two CAT calls per frequency point (set TX frequency, read RX S-meter). Safety enforcement is the main engineering concern.

---

---

## XL9535 I2C Relay Board Ideas

The XL9535 is a 16-bit I/O port expander (I2C, address 0x20–0x27) that drives relay coils via an on-board transistor array (typically ULN2803). The Bus Pirate is the natural host: one `bp.i2c_write(0x20, [0x06, 0x00, 0x00])` configures all 16 pins as outputs; thereafter `bp.i2c_write(0x20, [0x02, state_lo, state_hi])` sets any relay combination in a single transaction.

**Critical relay-type distinction:** The cheap HK19F-style signal relays found on most XL9535 relay boards are rated for audio/DC but have very poor RF performance above ~5 MHz — typically 20–40 dB insertion loss and poor isolation above HF. For RF signal routing applications (antennas, instrument ports, filter bank inputs), the XL9535 board should be used as a *controller* for external RF-rated relays (reed relays: 100 MHz; Omron G6Y: 3 GHz; coaxial relays: as needed), not to route RF directly through its own relay contacts. For non-RF applications — power switching, calibration standard selection, DUT port selection for low-frequency impedance/capacitance measurements — the on-board relays are entirely adequate.

---

### ✓ 78. XL9535 I2C Relay Driver — *rf-bench-drivers-relay*

Prerequisite for all other XL9535 relay projects. A thin `rf_bench.relay.XL9535` wrapper following the same pattern as the Bus Pirate and Flipper drivers. The XL9535 register map is simple: configuration registers (0x06/0x07) set each pin as input or output; output registers (0x02/0x03) set output states; input registers (0x00/0x01) read pin states. The driver hides the port-split (Port 0 = relays 0–7, Port 1 = relays 8–15).

**API to expose:**

```python
from rf_bench.relay import XL9535

rl = XL9535(bp, i2c_addr=0x20)   # bp is a BusPirate instance
rl.configure_outputs(pins=range(16))  # set all 16 pins as outputs

rl.set(0, True)          # energize relay 0
rl.set(3, False)         # de-energize relay 3
rl.set_all(0b0000_0101_0000_0011)  # set 16 relays in one I2C write (bitmask)
rl.close_only(5)         # de-energize all, then energize relay 5 (exclusive switching)

states = rl.get_all()    # → int bitmask of current output states
rl.all_off()             # safe state: all relays off

# Context manager for safe teardown
with XL9535(bp) as rl:
    rl.set(2, True)
    # ... rl.all_off() called automatically on exit
```

**I2C timing:** XL9535 supports 400 kHz Fast-mode I2C. Bus Pirate I2C is limited to ~100 kHz in hardware — adequate; relay coil inductance means actual closure time is 5–10 ms anyway, so I2C speed is never the bottleneck.

**Power note:** Most XL9535 relay boards require a 5V supply for the relay coils (via the ULN2803) even if the I2C logic is 3.3V. Bus Pirate can provide 5V on its power pin for a small board; larger boards with their own power connector need an external 5V supply (SPD3303X-E CH3, which is fixed 5V, is ideal for this).

**Multi-board support:** Two XL9535 boards at I2C addresses 0x20 and 0x21 give 32 relays; three boards give 48. The `XL9535` class takes `i2c_addr` as a parameter for this purpose.

**Effort:** Very low. XL9535 register writes are three-byte I2C transactions — under 60 lines total including error handling and the context manager.

---

### ✓ 79. Multi-DUT Sequential Component Tester — *rf-bench-relay-multidut*

Connects up to 8 (4-relay board), 8 (8-relay board), or 16 (16-relay board) DUT sockets to a single instrument input via relay switching. Steps through all populated sockets automatically, measuring each one in turn. Eliminates the physically most tedious part of batch component characterization: touching and swapping leads for each new part.

**Instruments supported:** SDM3045X (resistance, capacitance, diode Vf) or SDG + scope / rf-impedance measurement chain.

**Primary use cases:**

- **Crystal sorting for ladder filters (extends #5):** Wire 8 crystals into relay sockets. The script closes one relay at a time and runs the rf-impedance or crystal-extractor measurement on each crystal. After all 8, prints a frequency-sorted table: `[14.074001 MHz, 14.074003 MHz, 14.074008 MHz, …]`. Bin crystals by frequency offset for matched filter construction. Reduces 8-crystal sorting from 30 minutes of probing to 3 minutes of unattended measurement.

- **Capacitor binning for crystal filters:** Relay-switch the test capacitor into the DMM Cx terminals. Script steps through all sockets, reads capacitance, bins against E12 series. Most useful for low-value NP0 caps (10–100 pF) where the component sorter (#58) already works but requires manual probe repositioning.

- **Resistor characterization under bias (#66 variant):** Wire 8 resistors into relay sockets in series with a fixed bias resistor. Script applies SPD voltage, switches each DUT relay, measures resistance via DMM, computes power dissipation per DUT. Useful for qualifying batches of matched resistors for a bridge or attenuator pad.

- **Diode Vf matching for balanced mixers:** 8 Schottky diodes in sockets. Script measures each at the DMM's forward-bias test current and sorts by Vf. Matching Vf within 1 mV in a double-balanced mixer directly improves carrier suppression by 10–15 dB.

**Relay type:** On-board HK19F relays are adequate here — signals are DC or audio-frequency only. No RF performance concern.

**Socket fixture:** A small piece of perfboard with 8 SIP headers (one per relay) and a shared common rail. Components plug into standard header pins; no soldering for test.

**Effort:** Low. Relay switching is one I2c write per step. All measurement loops already exist in the component sorter (#58), crystal extractor (#5), and rf-impedance (#8) projects.

---

### ✓ 80. Automated VNA Calibration Fixture — *rf-bench-relay-solt*

Automates SOLT calibration for the HP 8712B (#26) by wiring OPEN, SHORT, LOAD, and THRU standards to relay positions. The calibration sequence — which currently requires interactive manual steps ("connect OPEN at port 1, press Enter") — becomes a single `cal.auto_solt()` call.

**Why this matters:** The HP 8712B projects (#26–33) are all listed as "hardware pending" because the GPIB adapter has not been installed yet. When it is installed, the first thing needed is a reliable, repeatable SOLT calibration workflow. Manual SOLT requires careful attention to standard sequencing and connector handling, and must be repeated every time a cable or setup changes. An automated fixture eliminates this friction.

**Fixture design:**

```
                     HP 8712B Port 1
                          │
              ┌───────────┴──────────────────────┐
              │          SPDT switch tree         │
         RL1 (OPEN)   RL2 (SHORT)   RL3 (50Ω LOAD)   RL4 (DUT port)
```

A 4-relay SPDT arrangement (or 4 SPNO relays switched against a common port 1 node) selects which standard is presented to the VNA port. Port 2 is handled by a second 4-relay group. The 4-relay board handles Port 1 standards; the second 4-relay group handles Port 2. A 16-relay board handles both ports with relays to spare.

**Standards wiring:** Solder SMA OPEN (cap removed from termination — physically an open SMA connector), SHORT (SMA termination with center pin shorted to shell), and LOAD (50 Ω precision SMA termination, ±0.5 Ω, Amphenol or equivalent) onto the board. The THRU position connects Port 1 and Port 2 relay commons together directly.

**Calibration sequence:**

```python
from rf_bench.relay import XL9535
from rf_bench.hp import HP8712B

vna = HP8712B("10.1.1.70")
rl  = XL9535(bp, i2c_addr=0x20)

cal = AutoSOLT(vna, rl, port1_relays=(0,1,2,3), port2_relays=(4,5,6,7))
cal.auto_solt()   # steps through all 12 standard/port combinations, no prompts
cal.save("~/.8712b_cal.json")
```

**Limitation:** Relay contact resistance (50–100 mΩ) adds a small perturbation to the SHORT and LOAD standards. This is measurable with the Kelvin contact resistance survey (#60) and can be characterized once and subtracted from the cal. For HF/VHF work up to 500 MHz the perturbation is negligible; above 500 MHz the relay parasitics become significant and a different (coaxial relay) approach is warranted.

**Relay type note:** For this application, use reed relays (Coto 9011 or similar, rated to 100–200 MHz) rather than the HK19F relays on standard boards, to keep relay contact parasitics below the standard's own reflection error. The XL9535 driver works identically regardless of which relay type is used.

**Effort:** Medium. Fixture construction is the main work. The Python sequence is straightforward once the relay driver (#78) and HP 8712B driver (#26) exist.

---

### ✓ 81. Band-Switched Filter Bank Controller — *rf-bench-relay-filterbank*

Controls a relay-switched bandpass/lowpass filter bank in the instrument signal path. The XL9535 selects the appropriate filter for the current operating frequency, eliminating manual cable changes between test bands and enabling the transmitter test suite (#18) to sweep all HF bands automatically without pausing for filter swaps.

**Two use cases:**

**A. Transmit LPF bank (for transmitter test suite #18):**
The transmitter test requires a low-pass filter between the radio's antenna port and the SSA to suppress harmonics to safe SSA input levels AND to prevent out-of-band harmonics from confusing the measurement. Different bands need different LPF cutoffs: a 3.5 MHz test needs a 4 MHz LPF; a 28 MHz test needs a 30 MHz LPF. With a relay bank:

```
IC-7300 antenna port → relay bank (selects LPF by band) → 30 dB fixed atten → SSA RF In
```

8 relays cover 8 LPF stages (160m, 80m, 40m, 30m, 20m, 17m, 15m, 10m/6m). The transmitter test script sets the radio frequency, looks up the correct relay position, switches the bank, and proceeds — no pause for manual filter changes.

**B. Receive BPF bank (for receiver test suite, dual-radio antenna isolation #70, and general sensitivity):**
Bandpass filters before the IC-7300 or RTL-SDR suppress out-of-band interferers that cause IMD in the receiver front end. A relay-switched BPF bank makes it practical to measure receiver performance with and without band filtering in rapid succession:

```
Antenna → relay bank (selects BPF by band) → IC-7300 or RTL-SDR
```

**Integration with existing projects:**

- **Transmitter test (#18):** Add `switch_lpf(freq_hz)` call before each frequency step. The transmitter test becomes fully automated across all bands without manual intervention.
- **Receiver test (#1/receiver-test):** Add `switch_bpf(freq_hz)` call before each band sweep. Enables a single unattended run across all HF bands.
- **Dual-radio isolation (#70):** Automatically select the correct BPF on the receive radio as the transmit radio steps through bands, improving isolation and reducing IMD in the S-meter reading.

**Relay type for RF path:** For LPF and BPF switching in the signal path, use RF-rated relays — Omron G6Y-1 (SPDT, 3 GHz rated, $5–8 each) or equivalent. Wire these with short coax jumpers to the filter input/output SMA connectors. The XL9535 driver controls the relay coil; the signal flows through the coaxial relay contacts, not through the XL9535 board's own traces.

The XL9535 board is used *only* as a coil driver: XL9535 output → transistor → relay coil. This is the key architectural point — the relay board drives the coil, but the RF path runs through separate coaxial relays wired next to the filter components.

**Effort:** Medium (relay wiring and filter construction); Low (Python integration).

---

### ✓ 82. Instrument Port and Antenna Router — *rf-bench-relay-router*

An N×M signal routing matrix that connects any of N antennas/signal sources to any of M instrument inputs, under full software control. Eliminates the #1 source of manual intervention in bench automation: physically moving coax between the SSA, IC-7300, RTL-SDR, and different antennas between measurements.

**Example configuration (8-relay board = 4-input × 2-output matrix, or 2-input × 4-output):**

```
Sources / Antennas:          Instruments:
  A: HF antenna              X: SSA RF In
  B: VHF/UHF antenna         Y: IC-7300 Antenna
  C: SSA Tracking Generator  Z: RTL-SDR
  D: SDG CH1 output          W: HP 8712B Port 1
```

Each source-to-instrument pair uses one relay (or a relay tree for mutual exclusion). Software commands like `router.connect(SOURCE_B, INSTRUMENT_Z)` make any configuration in one I2C write.

**High-value automation flows this enables:**

- **Antenna comparison (receiver test #1):** `router.connect(ANTENNA_A, IC7300)` → run MDS measurement → `router.connect(ANTENNA_B, IC7300)` → run MDS again → compare. No cable change; results differ only by antenna performance.

- **Reference/DUT bypass for scalar measurements:** In the scalar VNA (#3) and RF amplifier characterizer (#2), a "through" reference measurement is required before each DUT measurement. Relays RFL1 and RFL2 implement a SPDT bypass: position 1 connects source directly to detector (reference); position 2 inserts the DUT. The script automatically switches to reference, captures a baseline, switches to DUT, captures measurement, computes normalized result — one press of Enter, no cable touches.

- **FM propagation monitor + dual-instrument verification (#64 + #77):** SSA sweeps the FM band for power overview; when a new peak is detected, the router switches the RTL-SDR to the same antenna for RDS decode to confirm identity. Between them, one instrument detects presence, the other confirms identity — no manual re-plugging required.

- **ADS-B multi-antenna comparison (#72):** Connect two antennas (HF vertical vs. discone) to different router inputs; the router alternates connections to the RTL-SDR, building decode statistics per antenna.

**Relay type:** Same caveat as the filter bank — use coaxial RF relays in the RF signal path, controlled by the XL9535 board via transistor drivers. For HF (up to 30 MHz), surplus coaxial relays (Dow-Key, Transco, or similar) work well; for VHF/UHF up to 1 GHz, Omron G6Y-1 in a proper SMA fixture is adequate.

**16-relay board configuration:** 16 relays give up to a 4×4 full crosspoint (16 single-throw relays in a grid) or an 8×2 matrix with mutual exclusion enforced by software. The full crosspoint requires more careful RF layout (each crossing has mutual coupling potential); the 8×2 with shared columns is simpler and sufficient for most bench use.

**Effort:** Medium (RF relay fixture and coax wiring); Low (Python routing API — it is just a bitmask table).

---

### ✓ 83. Reference/DUT Path Switcher for Normalization — *rf-bench-relay-normalize*

A focused 2-relay application that automates the most common manual step in scalar RF measurements: switching between a "reference" (through) path and the "DUT" path for normalization. Applies to the Bode plotter (#1), scalar VNA (#3), RF amplifier (#2), balun analyzer (#4), and any other measurement that requires a baseline before measuring the DUT.

**Current workflow (manual):**
1. Connect source → detector directly (bypass DUT). Press Enter. Script captures reference.
2. Disconnect source, insert DUT, reconnect. Press Enter. Script captures DUT response.
3. Normalize: DUT / reference → corrected gain/loss curve.

Step 2 takes 20–60 seconds of physical cable manipulation per measurement. For frequency-swept measurements, you must hold the bench configuration constant between reference and DUT sweeps — any accidental cable shift introduces a systematic error. Over dozens of components, this becomes the dominant time sink.

**With the 2-relay switcher:**
Two SPDT relays (or two SPNO + common) implement the reference/DUT selection:

```
Source output ─── Relay R1 ─── [THROUGH] ─────────── Relay R2 ─── Detector input
                   │                                      │
                   └───── DUT input ──── DUT ─── DUT output ─┘
```

`rl.close_only(0)` → reference path. `rl.close_only(1)` → DUT path. Zero cable changes. Reference and DUT sweeps can be interleaved at every frequency step if desired (doubling accuracy by tracking any drift in the source level between reference and measurement).

**Specific integration points:**

- **Bode plotter (#1):** `bode_plotter.py --auto-reference` flag: on each run, automatically captures a reference sweep before inserting the DUT via relay command.
- **Scalar VNA (#3):** Automates the S21 normalization step that currently requires manual cable reconfiguration.
- **RF amplifier (#2):** Automates the SSA reference-level calibration pass that establishes the input power baseline before sweeping the amplifier.
- **Balun analyzer (#4):** Switches between the reflection bridge (S11 measurement) and a through connection for SSA baseline normalization.

**Relay type:** Reed relays or Omron G6Y-1 for RF signal path above 10 MHz. For the scope/SDG Bode plotter (up to 60 MHz), G6Y-1 is adequate. For the SSA-based measurements (up to 3.2 GHz), use coaxial relays in the RF path.

**Effort:** Very low — this is 2 relays and a 3-line Python addition to each existing measurement script.

---

---

## Virtual Instrument Panel Ideas

These Tkinter-based graphical panels provide live visual monitoring of instrument state, modeled after the Yertai ET5406A+ virtual panel pattern. Each panel polls the instrument in a background thread and updates the display in real time. All panels support `--demo` mode for UI testing without hardware and include disabled control button stubs for future interactive operation.

---

### ✓ 84. SDM3045X Virtual Panel — *rf-bench-drivers-siglent/sdm3045x_panel.py*

**Instrument: SDM3045X bench multimeter.**

Displays live measurement value, function mode badge (VDC/VAC/IDC/IAC/RES/FREQ/etc.), range setting (AUTO or numeric), and connection status. The function badge is color-coded by measurement type: VDC blue, VAC orange, IDC amber, RES green, etc.

```bash
python sdm3045x_panel.py                    # default 10.1.1.63:5025
python sdm3045x_panel.py --host 10.1.1.63   # explicit IP
python sdm3045x_panel.py --interval 500     # refresh every 500 ms (default)
python sdm3045x_panel.py --demo             # simulated data, cycles all functions every ~6 s
```

**Demo mode cycles through:** VDC, VAC, IDC, IAC, 2W Ω, 4W Ω, FREQ, PERIOD, CONT, DIODE — all with plausible simulated readings and noise.

**Control stubs (future):** VDC, VAC, IDC, IAC, 2W Ω, 4W Ω, FREQ, DIODE, CONT, AUTO RANGE buttons. Entry field for manual range selection.

**Effort:** Done. Published in rf-bench-drivers-siglent/.

---

### ✓ 85. SDG1062X Virtual Panel — *rf-bench-drivers-siglent/sdg1062x_panel.py*

**Instrument: SDG1062X dual-channel function generator.**

Two-column layout (CH1 orange | CH2 blue) showing frequency (with `format_freq_short()` — e.g., "14.001 MHz"), amplitude (both dBm and Vpp), phase (degrees), waveform type (SINE/SQUARE/RAMP/ARB), and output ON/OFF state per channel.

```bash
python sdg1062x_panel.py                    # default 10.1.1.55:5025
python sdg1062x_panel.py --host 10.1.1.55   # explicit IP
python sdg1062x_panel.py --interval 1000    # refresh every 1000 ms (default)
python sdg1062x_panel.py --demo             # simulated data, CH1 toggles on/off every ~8 s
```

**Demo mode:** CH1 toggles output on/off every ~8 s while both channels display live frequency with gentle drift + noise, simulating a real dual-channel signal generator under operation.

**Control stubs (future):** CH1 ON/OFF, CH2 ON/OFF, SINE, SQUARE, RAMP, SET FREQ, SET LEVEL buttons. Entry fields for frequency and amplitude.

**Effort:** Done. Published in rf-bench-drivers-siglent/.

---

### ✓ 86. SPD3303X Virtual Panel — *rf-bench-drivers-siglent/spd3303x_panel.py*

**Instrument: SPD3303X-E triple-output programmable power supply.**

Three-column layout (CH1 red | CH2 green | CH3 blue). Each channel displays voltage, current, power measurements, output ON/OFF state, and CV/CC mode badge. CH1 and CH2 show set points (V SET, I SET); CH3 (fixed-voltage) shows measurements only. Tracking mode indicator at the bottom: INDEPENDENT / SERIES / PARALLEL.

```bash
python spd3303x_panel.py                    # default 10.1.1.56:5025
python spd3303x_panel.py --host 10.1.1.56   # explicit IP
python spd3303x_panel.py --interval 1000    # refresh every 1000 ms (default)
python spd3303x_panel.py --demo             # simulated data, cycles tracking modes every ~10 s
```

**Demo mode cycles:** INDEPENDENT → SERIES → PARALLEL → … with plausible V/I/P readouts and gentle variation to simulate real loading conditions.

**Control stubs (future):** CH1/CH2/CH3 ON/OFF, INDEP/SERIES/PARA tracking mode selection, SET V, SET I buttons, entry fields for voltage and current.

**Effort:** Done. Published in rf-bench-drivers-siglent/.

---

### ✓ 87. SSA3032X Virtual Panel — *rf-bench-drivers-siglent/ssa3032x_panel.py*

**Instrument: SSA3032X Plus spectrum analyzer (9 kHz–3.2 GHz).**

Proposed panel displays:
- Live spectrum trace (matplotlib embedded in Tkinter, static or waterfall)
- Center frequency, span, RBW, reference level, attenuation
- Markers 1–6 with frequency and power readouts
- Peak search results (frequency + power at highest peak)
- Tracking generator on/off + level
- Measurement statistics (peak hold, average, min hold modes)

```bash
python ssa3032x_panel.py                    # default 10.1.1.60:5025
python ssa3032x_panel.py --host 10.1.1.60   # explicit IP
python ssa3032x_panel.py --interval 2000    # refresh every 2000 ms (spectrum sweep rate)
python ssa3032x_panel.py --demo             # simulated spectrum with carrier + noise
```

**Demo mode:** Generates a synthetic spectrum with a strong carrier at a programmable frequency (sweeps across the display), harmonic peaks, and Gaussian noise floor — simulating a signal generator or transmitter under test.

**Control stubs (future):** CENTER FREQ, SPAN, RBW, REF LEVEL entry fields; AUTO SCALE, PEAK SEARCH, MARKER ON/OFF buttons; tracking generator controls; screenshot capture.

**Unique feature:** matplotlib integration for live spectrum plotting. This is the first virtual panel in the suite that requires real-time graphing beyond simple numeric readouts. The Yertai panel displays only V/I/P/R text values; the SSA panel must display a frequency-domain trace with correct axis scaling, peak markers, and color mapping.

**Effort:** Medium. SSA driver exists. matplotlib embed in Tkinter is well-documented but requires careful attention to refresh rate vs. plot complexity. Demo mode spectrum generation is straightforward — carrier at center ± offset, harmonics, white noise via `np.random`.

---

### ✓ 88. SDS2504X Virtual Panel — *rf-bench-drivers-siglent/sds2504x_panel.py*

**Instrument: SDS2504X Plus oscilloscope (500 MHz, 4-ch).**

Proposed panel displays:
- Four-channel waveform plot (matplotlib embedded in Tkinter, time-domain traces)
- Timebase, trigger settings (level, slope, source)
- Channel on/off state, V/div per channel
- Built-in measurement readouts (Vpp, freq, rise time, etc.) per active channel
- Cursor measurements (if enabled)
- Acquisition status: running / stopped / triggered

```bash
python sds2504x_panel.py                    # default 10.1.1.58:5025
python sds2504x_panel.py --host 10.1.1.58   # explicit IP
python sds2504x_panel.py --interval 500     # refresh every 500 ms (continuous acquisition)
python sds2504x_panel.py --demo             # simulated 4-channel waveforms (sine/square/pulse/noise)
```

**Demo mode:** Generates four synthetic time-domain waveforms: CH1 = sine wave with gentle amplitude/frequency variation, CH2 = square wave, CH3 = pulse train, CH4 = noise. All with plausible voltage scales and timebase settings.

**Control stubs (future):** CH1/CH2/CH3/CH4 ON/OFF, V/div, timebase (s/div), trigger level/slope/source, RUN/STOP/SINGLE, AUTO SCALE, cursor enable/position.

**Unique feature:** Real-time waveform plotting with trigger synchronization. The most complex virtual panel in this list — four simultaneous traces, shared time axis, trigger indicator line, and auto-scaling. Unlike the SSA (frequency domain, slow sweep), the scope is time-domain at potentially high refresh rates.

**Effort:** High. Scope driver waveform download exists. matplotlib 4-trace plot is straightforward. The hard part is managing refresh rate: full deep-memory waveform downloads (10 M points) are slow (~2 s); reduced-point downloads (14k points) are fast but lower resolution. The panel should default to reduced points for live display and offer a "capture high-res" button for single-shot deep memory.

---

### ✓ 89. IC-7300 Virtual Panel — *rf-bench-drivers-icom/ic7300_panel.py*

**Instrument: Icom IC-7300 HF transceiver (via rigctld on port 4532).**

Proposed panel displays:
- VFO frequency (large digits, tunable with mouse wheel or arrow keys)
- Operating mode (USB/LSB/CW/AM/FM/RTTY)
- S-meter (analog meter graphic or bar graph) — live signal strength
- RF gain, AGC setting (OFF/SLOW/MID/FAST)
- Preamp/attenuator state (IC-7300: preamp 1/2/off, attenuator 10/20 dB)
- Power output (when transmitting) — red badge when PTT active
- Filter bandwidth (SSB: WIDE/MID/NAR; CW: 50 Hz – 3.6 kHz)

```bash
python ic7300_panel.py                      # default localhost:4532 (rigctld)
python ic7300_panel.py --host 10.1.1.70     # remote rigctld instance
python ic7300_panel.py --port 4533          # non-default rigctld port
python ic7300_panel.py --demo               # simulated VFO + S-meter with drift and signal bursts
```

**Demo mode:** VFO slowly drifts across 14 MHz band (±5 kHz over ~60 s). S-meter shows baseline noise (~S1) with occasional signal bursts (S5–S9) lasting 2–10 s, simulating real band activity. Operating mode cycles USB → CW → LSB → … every ~15 s.

**Control stubs (future):** Frequency entry field, UP/DOWN buttons, MODE buttons, RF GAIN slider, AGC selector, PREAMP/ATT buttons, PTT button (software TX enable — dangerous; requires confirmation dialog).

**Unique feature:** S-meter graphical display. The IC-7300 has a calibrated S-meter; the panel can display it as either an analog meter (styled like a classic radio panel meter with needle and scale) or a modern bar graph. The analog meter gives a more intuitive "ham radio" feel and matches the radio's own display aesthetic.

**Effort:** Low–medium. IC-7300 driver exists. S-meter read is `get_strength()` or `get_strength_settled()`. Analog meter drawing in Tkinter requires a custom canvas widget or matplotlib polar subplot — under 100 lines. All other fields are simple text/label updates.

---

### ✓ 90. FT-891 Virtual Panel — *rf-bench-drivers-yaesu/ft891_panel.py*

**Instrument: Yaesu FT-891 HF transceiver (via rigctld on port 4532).**

Nearly identical to the IC-7300 panel (#89), but reflects FT-891-specific differences:
- Preamp: AMP1 on/off only (no preamp 2)
- Attenuator: 6/12 dB steps (not 10/20 dB like IC-7300)
- S-meter: less linear than IC-7300; calibration table from receiver-test applies

```bash
python ft891_panel.py                       # default localhost:4532 (rigctld)
python ft891_panel.py --demo                # simulated VFO + S-meter
```

**Control stubs (future):** Same as IC-7300 panel, adapted for FT-891 CAT command set (handled by rigctld abstraction; panel code is nearly identical).

**Effort:** Very low once IC-7300 panel exists — copy, rename, adjust preamp/att labels.

---

### ✓ 91. RTL-SDR Virtual Panel — *rf-bench-drivers-rtlsdr/rtlsdr_panel.py*

**Instrument: RTL-SDR Blog v4 (500 kHz–1766 MHz receiver).**

Proposed panel displays:
- Waterfall display (matplotlib, time × frequency, color = power dBm)
- Instantaneous spectrum (live FFT of most recent IQ block)
- Center frequency, sample rate, gain (dB or AUTO)
- PPM calibration offset applied
- Bias tee on/off (5V to power inline LNA)
- Signal detection indicator (threshold crossing, e.g., "Signal detected at 433.92 MHz")

```bash
python rtlsdr_panel.py                      # default: first RTL-SDR found
python rtlsdr_panel.py --serial 00000001    # explicit RTL-SDR by serial number
python rtlsdr_panel.py --freq 144.39e6      # start at APRS frequency
python rtlsdr_panel.py --demo               # simulated waterfall with sweeping carrier + noise
```

**Demo mode:** Generates a synthetic waterfall with a slow-moving carrier (simulates a drifting transmitter or frequency-hopping burst) across the displayed bandwidth. Noise floor at −110 dBm; carrier at −70 dBm moves ±200 kHz over ~30 s. Simulates the visual experience of monitoring an ISM band or APRS frequency.

**Control stubs (future):** CENTER FREQ entry, SAMPLE RATE selector (0.9/1.2/1.8/2.4 MHz), GAIN slider, BIAS TEE toggle, RECORD button (starts IQ capture to SigMF file), DEMOD selector (AM/FM/USB/LSB — pipes demodulated audio to speakers via sounddevice).

**Unique feature:** The waterfall display is the RTL-SDR's defining visual output. Unlike the SSA (swept spectrum at each time slice), the RTL-SDR provides a continuous 2.4 MHz slice with time history stacked vertically. The panel should maintain a rolling buffer of the last N seconds (configurable, default 60 s) and display the waterfall in near-real-time. This is the most graphically intensive panel — balancing FFT rate (10–50 Hz) vs. display refresh (20–30 fps) requires careful threading.

**Effort:** High. RTL-SDR driver IQ capture exists. matplotlib waterfall rendering is well-documented but refresh-rate optimization is non-trivial. Demo mode waterfall generation is straightforward (`np.random` noise + moving carrier).

---

### ✓ 92. Si5351 Virtual Panel — *rf-bench-si5351-gen/si5351_panel_gtk.py* (alternative to curses TUI)

**Instrument: Si5351A clock generator (I2C via Bus Pirate, 3 kHz–200 MHz, 3 outputs).**

The existing `si5351_gen` project (#57) uses a curses TUI. A Tkinter alternative would provide:
- Three-output display: CLK0, CLK1, CLK2 with large frequency readouts
- Drive strength selector per output (2/4/6/8 mA)
- Output enable/disable toggle per channel
- PLL assignment indicator (CLK0 → PLL-A; CLK1/CLK2 → shared PLL-B with asterisk when both active)
- Preset selector dropdown (load/save named presets to `~/.si5351_presets.json`)
- SSA MEASURE button (if `--ssa` flag given, opens SSA and measures actual output power on selected channel)

```bash
python si5351_panel_gtk.py                  # default Bus Pirate auto-detect
python si5351_panel_gtk.py --buspirate /dev/ttyUSB1
python si5351_panel_gtk.py --ssa 10.1.1.60  # enable SSA measurement button
python si5351_panel_gtk.py --demo           # simulated 3-channel output (no Bus Pirate needed)
```

**Demo mode:** Displays three simulated clock outputs with user-adjustable frequencies via entry fields, but does not write to hardware. Useful for UI testing and learning the tool's layout without a Si5351 module present.

**Effort:** Medium. Si5351 driver exists in the Bus Pirate project. The curses TUI logic is already implemented; this is a GUI rewrite using Tkinter instead. The preset save/load and SSA measurement integration are new.

---

### ✓ 93. Flipper Zero Virtual Panel — *rf-bench-drivers-flipper/flipper_panel.py*

**Instrument: Flipper Zero (Sub-GHz, IR, RFID, NFC multi-tool).**

Proposed panel displays:
- Sub-GHz: current frequency, TX/RX state, RSSI (dBm) when receiving, power index when transmitting
- IR: last captured protocol + command, transmit button per saved code
- RFID/NFC: card detected indicator, UID, card type
- GPIO state visualization (8 pins, on/off indicators)

```bash
python flipper_panel.py                     # default /dev/ttyACM0
python flipper_panel.py --port /dev/ttyACM1 # explicit USB CDC port
python flipper_panel.py --demo              # simulated Sub-GHz RX with RSSI variation
```

**Demo mode:** Sub-GHz tab shows a simulated RSSI reading that varies ±10 dB around −75 dBm (simulates a weak ISM signal fading in and out). IR tab displays a fake captured code. RFID tab shows no card detected. GPIO pins all off.

**Control stubs (future):** Sub-GHz TX CARRIER button (starts CW transmission at set frequency + power), RX START/STOP buttons, IR TRANSMIT button (sends a stored code), RFID READ button (arms reader for next card).

**Unique feature:** Multi-tab UI — Sub-GHz, IR, RFID/NFC, GPIO as separate tabs. This is the first virtual panel with fundamentally different operating modes in the same tool. Each tab polls different Flipper RPC calls and displays mode-specific state.

**Effort:** Medium. Flipper driver (#39) exists. Protobuf RPC calls for each subsystem are already wrapped. New work: multi-tab Tkinter layout and per-tab update logic.

---

## Panel Architecture Summary

All virtual panels share this structure:

1. **State dataclass:** defines all displayable instrument state (measurements, settings, connection status)
2. **Demo source class:** generates plausible simulated data for `--demo` mode; cycles through operating modes/ranges/functions
3. **Poll worker thread:** connects to instrument, reads state in a loop, stores latest snapshot in a lock-protected shared `state_ref` list
4. **UI refresh loop:** reads latest state (from poll thread or demo source), updates all Tkinter widgets via `.config()` and `StringVar.set()`
5. **Control section:** disabled button stubs with placeholder layout for future interactive controls

**Adding interactive controls (future):**
- Change `tk.Button(..., state=tk.DISABLED)` to `state=tk.NORMAL`
- Add `command=lambda: self._on_<action>()` callback
- Implement callback that calls driver method (e.g., `psu.set_voltage(1, 5.0)`)
- For user input (frequency, voltage, etc.): replace stub `tk.Entry` with live entry + validation

**Why virtual panels are valuable:**
- **Unattended monitoring:** Leave running during overnight tests; check state in the morning without SSH/SCPI.
- **Parallel operation:** Monitor multiple instruments simultaneously in separate windows.
- **Learning tool:** `--demo` mode lets new users explore instrument UI layout and controls without hardware.
- **Remote access:** SSH with X forwarding (`ssh -X host`) displays the panel remotely — useful when the instrument is physically in a different room or building.
- **Integration with automation:** Automation scripts run in the background; the panel provides a human-friendly live view of what the script is commanding.

**Priority order for implementation:**
1. ✓ SDM3045X, SDG1062X, SPD3303X-E (Done)
2. SSA3032X — high value for live spectrum monitoring during transmitter/amplifier/antenna tests
3. IC-7300 / FT-891 — immediate value for receiver/transmitter test automation (human-readable state during automated test runs)
4. SDS2354X — high complexity but high value; complements the scope-based measurement projects
5. RTL-SDR — useful for ISM/APRS/ADS-B monitoring projects
6. Si5351, Flipper — lower priority; niche applications

---

## GPS / gpsd-enabled projects

These become possible with the `rf_bench.gpsd` driver (`drivers/gpsd/`).

---

### Standalone GPS projects

**✓ GPS position precision surveyor** (`projects/gps/survey/survey.py`)
Log a static fix for an extended period, compute mean lat/lon and N/E/2D scatter in metres.
Reports HDOP/VDOP and saves samples to CSV. Built.

**✓ Grid square calculator / locator display** (`projects/gps/gridsquare/gridsquare.py`)
Live Maidenhead locator display (4/6/8 characters), optional waypoints with distance and bearing.
Uses pure-Python Maidenhead implementation. Built.

**✓ GPS fix quality monitor** (`projects/gps/monitor/monitor.py`)
Fullscreen terminal: fix mode, HDOP/VDOP/PDOP bars, position, speed, heading, error estimates,
ASCII scatter plot of recent fix scatter. Built.

---

### RTL-SDR + GPS integrations

**✓ Mobile spectrum survey** (`projects/rtlsdr/survey/survey.py`)
Captures power spectra with RTL-SDR at regular intervals; geo-tags with GPS when `--gps` is set.
Single frequency or swept; CSV output with lat/lon/power. GPS optional. Built.

**✓ GPS-tagged SigMF IQ recorder** (extended `projects/rtlsdr/recorder/recorder.py`)
Added `--gps` flag: embeds `core:geolocation` GeoJSON Point in SigMF global metadata.
Zero overhead when `--gps` is not passed. Built.

**✓ RF coverage drive test** (`projects/rtlsdr/drivetest/drivetest.py`)
Continuous single-frequency power logging with RTL-SDR; CSV + GPX output with signal-strength
extension when `--gps` is set. GPS optional. Built.

---

### Radio (IC-7300 / IC-9700 / FT-891) + GPS integrations

**✓ Signal strength coverage mapper** (`projects/radio/coverage/coverage.py`)
S-meter (dBm) vs GPS position; IC-7300, IC-9700, or FT-891; CSV + GPX output.
GPS optional via `--gps`. Built.

**APRS position transmitter** (`projects/radio/aprs-tx/`) — *not yet built*
Use GPS + IC-7300 + software TNC to transmit APRS position packets.
Requires a TNC driver (not yet implemented). Deferred.

**✓ Doppler VFO corrector** (`projects/radio/doppler/doppler.py`)
Computes radial velocity toward a fixed target from GPS speed + heading, applies VFO offset
in real-time via Hamlib. Works with IC-7300, IC-9700, or FT-891. `--dry-run` for display only.
IC-9700 is the primary intended radio for this project (satellite cross-band Doppler). Built.

---

### Siglent SSA3000X + GPS integrations

**✓ GPS-disciplined frequency drift monitor** (`projects/gps/freq-cal/freq_cal.py`)
Measures SDG or external carrier with SSA; uses GPS `time_utc` as absolute timestamp.
Logs frequency + offset + ppm to CSV; `--report` mode computes drift rate from saved data. Built.

**Calibrated mobile spectrum survey** — *not yet built*
Same concept as the RTL-SDR mobile survey but with SSA3000X for calibrated dBm readings.
Deferred: SSA is not easily portable.

---

### Multi-instrument integrations

**Antenna range characterization** (`projects/rf/antenna-range/`) — *not yet built*
Place SDG1062X (transmitter) at a GPS-surveyed point; walk receive antenna to GPS-waypointed
positions; log signal strength vs distance/azimuth.

**GPS + IQ: coherent multi-site recording** — *future / aspirational*
Two RTL-SDRs at known GPS positions recording simultaneously for TDOA transmitter location.
Requires sub-millisecond time accuracy; research-grade.

---

### Vestigare / ADS-B integration

**Own-ship overlay for ADS-B** (extend `vestigare/`) — *not yet built*
Feed GPS position into Vestigare as an own-aircraft marker on the map.

---

### APRS server integration

**GPS-to-APRS bridge** (extend `aprs-server/`) — *not yet built*
Let `aprs-server` read from a local gpsd instance instead of (or in addition to) a phone GPS.
Useful for fixed-station position reporting and portable ops.

---

## IC-9700 projects

The IC-9700 covers 144 MHz (2m), 430/440 MHz (70cm), and 1296 MHz (23cm).
It supports USB/LSB/CW/FM/DV (D-STAR) and cross-band split for satellite operation.
Hamlib model 3081. USB or LAN connection.

---

### Standalone IC-9700 projects

**✓ Satellite pass planner + Doppler tracker** (`projects/radio/satellite/satellite.py`)
TLE from AMSAT (group) / SatNOGS (per-NORAD). SGP4 via skyfield. Pass prediction + live
Doppler correction via IC-9700 `set_satellite_mode()` / `update_doppler()`. GPS optional
via `--gps`. `--dry-run` for display without radio. Built-in transponder database: AO-91,
AO-92, SO-50, ISS, FO-29, AO-7. Note: Celestrak /pub/TLE/ returns 403; AMSAT + SatNOGS
are the working sources. Built.

**D-STAR digital voice monitor** (`projects/radio/dstar-monitor/`)
Set the IC-9700 to DV mode, decode incoming frames via the IC-9700's USB audio output,
log callsigns, message text, and signal strength. No dedicated D-STAR decoder library needed
if the IC-9700 handles the digital decode internally and outputs the decoded audio/data via
its USB sound card. Monitor repeater activity and log to SQLite.

**VHF/UHF receiver sensitivity measurement** (`projects/radio/vhf-receiver-test/`)
VHF/UHF equivalent of the HF `receiver-test` project. The SSA3032X's tracking generator
covers up to 3.2 GHz, so it can drive the IC-9700's 2m and 70cm inputs directly
(vs. the SDG1062X which only reaches 60 MHz). Tests: MDS (minimum discernible signal),
noise figure from MDS, S-meter calibration, FM quieting sensitivity.
Much more useful than HF receiver testing for VHF weak-signal and satellite work.

**VHF/UHF beacon logger** (`projects/radio/beacon-logger/`)
Tune the IC-9700 to a known beacon frequency (2m propagation beacons, APRS, ISS),
log S-meter reading and GPS timestamp continuously to SQLite. Useful for tracking
tropospheric ducting events, Es openings, or satellite visibility windows.
GPS gives absolute time for cross-correlating with ionospheric data.

---

### IC-9700 + GPS integrations

**Full satellite cross-band pass** (`projects/radio/satellite/`) — see above.
The IC-9700 is the only radio in this inventory that supports simultaneous TX and RX
on different bands, which is required for satellite duplex. The `set_satellite_mode()`,
`update_doppler()`, and `set_ptt()` methods in the driver are built specifically for this.

**VHF/UHF antenna pattern mapper** (`projects/radio/coverage/` — extend existing)
Use the existing `coverage.py` with `--radio ic9700` and `--gps` to map 2m or 70cm antenna
radiation patterns. Drive a circle around the transmitter; post-process the GPX + S-meter
CSV into a polar plot. The IC-9700's S-meter calibration via SSA TG makes this quantitative.

**APRS igate via IC-9700** (`projects/radio/aprs-igate/`)
Use the IC-9700 on 144.390 MHz FM, feed audio to direwolf running on the same machine,
pipe decoded packets to the existing `aprs-server` on 10.1.0.20. The IC-9700's USB audio
output (it presents as a USB sound card) eliminates the need for an external TNC or audio
interface. Add GPS position reporting from `rf_bench.gpsd` for own-station beaconing.

---

### IC-9700 + SSA integrations

**VHF/UHF transmitter test** (`projects/radio/transmitter-test/` — `--radio ic9700`)
Already added: `transmitter_test.py --radio ic9700`. The SSA3032X (9 kHz–3.2 GHz) can
measure IC-9700 output power, harmonics, and ALC on all three bands. Note: 23cm
(1296 MHz) is within the SSA's range. Use appropriate attenuator (50 dB min) on the
TX output before the SSA input.

**FM deviation measurement** (`projects/radio/fm-deviation/`)
Connect IC-9700 TX output → attenuator → SSA3032X. Measure FM deviation by reading
the SSA's FM demodulation output while keying the IC-9700 with a known audio tone.
Verify the IC-9700's deviation is within spec (±5 kHz for narrow FM on 2m/70cm).
Uses SSA SCPI `CALC:DMOD:FM` commands.

**Intermodulation distortion — VHF** (`projects/radio/imd-vhf/`)
Two-tone IMD test at 2m or 70cm. Requires a VHF combiner and two signal sources at
2m/70cm — potentially using the RTL-SDR's bias tee to power an upconverter, or
a second IC-9700. The SSA TG at VHF can serve as one tone; a second source needed
for the second tone. More complex than HF IMD but more relevant for satellite LNA work.

---

### IC-9700 + RTL-SDR integrations

**IC-9700 + RTL-SDR cross-check** (`projects/radio/rx-crosscheck/`)
Tune both IC-9700 and RTL-SDR to the same VHF/UHF frequency, measure the same signal
simultaneously, and compare S-meter readings. Builds a calibration table mapping
RTL-SDR relative power (dB) to IC-9700 calibrated S-meter (dBm). Enables using the
RTL-SDR as a fast spectrum scanner calibrated against the IC-9700's known S-meter.

**✓ Satellite signal monitor** (`projects/rtlsdr/satellite/`)
While the IC-9700 handles the satellite duplex uplink, use the RTL-SDR as a wideband
receiver to monitor the 70cm downlink passband. Capture the full transponder bandwidth
as IQ (the RTL-SDR can do this at 2.4 MHz wide), letting you see your own signal plus
other stations in the passband simultaneously — useful for linear transponders.
**Status:** Implemented in `satellite_monitor.py`. Real-time waterfall display with
optional Doppler tracking and SigMF recording. Built-in database for AO-91, AO-92,
SO-50, ISS, FO-29, AO-7. Complementary to `projects/radio/satellite/satellite.py`.

---

## KiwiSDR — HF Receiver Projects

**Hardware:** KiwiSDR (BeagleBone Black cape). 0–30 MHz, 14-bit ADC at 66 MS/s,
GPS-disciplined TCXO. Delivers IQ or audio via WebSocket SND API. Up to 4–8 simultaneous
independent channels on one device. Driver: `rf_bench.kiwisdr` (WebSocket, 12 kS/s fixed).

### KiwiSDR standalone

**HF band activity monitor** (`projects/kiwisdr/hf-monitor/`)
Use `scan_band()` to sweep one or more HF amateur or shortwave bands and log detected
signals to SQLite.  Track frequency, power, timestamp, and optionally the classified
modulation (AM/SSB/CW/digital via `_classify_iq()`).  Build a daily/weekly activity
heatmap (frequency vs. time-of-day) to understand propagation patterns on each band.
Natural companion to bubba-detector's VHF/UHF scanning.

**HF propagation / noise floor logger** (`projects/kiwisdr/propagation/`)
Continuously log noise floor at specific HF frequencies (20m, 40m, 80m, 160m, WWV at
5/10/15 MHz, NCDXF beacons at 14.100 MHz etc.) to SQLite every N minutes.  Correlate
noise floor variations with solar flux data (K-index, A-index) or with known propagation
events.  The KiwiSDR's GPS-disciplined clock gives precise timestamps for cross-correlation.

**Shortwave broadcast band scanner** (`projects/kiwisdr/swbc/`)
Scan AM broadcast bands (LW 150–285 kHz, MW 520–1710 kHz, SW 2.3–26.1 MHz) in steps,
detect carriers, and log frequency + signal strength.  During band openings (especially
on 49m, 41m, 31m), distant stations become audible — the log reveals which bands are open
and to which parts of the world (by correlating station ID with broadcast schedules).

**WWV/WWVH time signal monitor** (`projects/kiwisdr/wwv/`)
Monitor WWV (5, 10, 15, 20, 25 MHz) and WWVH (2.5, 5, 10, 15 MHz) signal strength
continuously.  The S/N ratio at each frequency follows the ionosphere's daily and
seasonal variation.  Plot all WWV frequencies simultaneously using the multi-channel
capability (one channel per WWV frequency) for a real-time ionogram proxy.  Requires
4–5 simultaneous KiwiSDR channels.

**CW skimmer / spotting** (`projects/kiwisdr/cw-skimmer/`)
Monitor a CW subband (e.g. 20m CW: 14.000–14.060 MHz) continuously via `stream_iq()`.
Run `_classify_iq()` blocks to detect CW; pass detected segments to the CW modem
library (`~/Dropbox/build/cw-modem/`) for decoding.  Output callsign spots to SQLite
or a local RBN-style web page.  Complements the CodeMonkey transceiver for contest use.

**Digital mode activity logger** (`projects/kiwisdr/digital-monitor/`)
Monitor FT8/FT4/JS8 calling frequencies (e.g. 14.074, 14.078, 7.074 MHz) and log raw
IQ to SigMF files or pipe to WSJT-X's UDP input.  The 12 kHz bandwidth covers a full
FT8 passband (0–3 kHz used).  Useful for long-term activity recording without tying up
a transceiver.

**HF direction finding (multi-KiwiSDR TDoA)** (`projects/kiwisdr/tdoa/`)
If access to multiple KiwiSDR receivers is available (via the public KiwiSDR network at
http://kiwisdr.com/public/), use Time Difference of Arrival between geographically
separated receivers to estimate bearing to an HF transmitter.  The KiwiSDR GPS timestamp
provides the precise timing required.  The KiwiSDR project's own TDoA tool is the reference
implementation; this project would wrap it for automated measurement logging.

### KiwiSDR + RTL-SDR integrations

**HF + VHF band opening detector** (`projects/kiwisdr/band-opening/`)
Run KiwiSDR monitoring 6m (up to 30 MHz for the low end of 50 MHz — actually limited to
30 MHz, so this would cover propagation indicators like 10m beacons at 28.200 MHz) and
RTL-SDR monitoring 6m/2m SSB calling frequencies simultaneously.  When the KiwiSDR sees
unusual 10m activity, flag the RTL-SDR's 50.125 MHz channel as high-priority in the
bubba-detector analyzer queue.  Propagation indicators on one band predict openings on
the next.

**Full-spectrum HF + VHF/UHF scanner** (`projects/kiwisdr/full-spectrum/`)
Combine KiwiSDR (0–30 MHz) with one or more RTL-SDRs (24 MHz–1766 MHz) for continuous
HF-through-microwave coverage.  The KiwiSDR handles HF with its multi-channel capability;
the RTL-SDR(s) handle VHF/UHF as in bubba-detector.  A unified SQLite database records
all activity with consistent timestamp and modulation fields.  This is effectively
bubba-detector extended to include HF.

**HF groundwave / NVIS coverage mapping** (extends `projects/radio/coverage/`)
Use the KiwiSDR as the receive endpoint while driving a low-power HF transmitter (IC-7300)
from a mobile setup.  Record the KiwiSDR's received signal strength vs. GPS position
(from `rf_bench.gpsd`) to map groundwave or NVIS coverage at various HF frequencies.
The KiwiSDR's calibrated GPS clock provides precise signal strength timestamps; the
IC-7300 provides the known transmit power reference.

### KiwiSDR + IC-7300 integrations

**HF transceiver + KiwiSDR panadapter** (`projects/kiwisdr/panadapter/`)
Tap the IC-7300's IF output (or a T-connector on the antenna) into the KiwiSDR while
the IC-7300 is operating.  The KiwiSDR provides a wide panadapter display (up to ±6 kHz
around the operating frequency, or scan a wider range) while the IC-7300 handles the
actual transceive.  Capture IQ of the full band around the operating frequency to a
SigMF file for post-contest analysis.

**Noise figure measurement via Y-factor** (`projects/kiwisdr/noise-figure/`)
The KiwiSDR's 14-bit ADC and GPS-calibrated clock make it suitable as the measurement
receiver in a Y-factor noise figure test.  Use a calibrated noise source (or the
IC-7300's internal noise source if available) and measure Y-factor across HF frequencies.
The KiwiSDR's multi-channel capability allows simultaneous NF measurement at multiple
frequencies.


---

## SunSDR2 Pro — Projects

**Hardware:** SunSDR2 Pro by Expert Electronics. 0.1–55 MHz + 100–150 MHz.
14-bit ADC, GPS-disciplined TCXO. Connects via Ethernet to ExpertSDR3 (TCI WebSocket,
port 50001). Two simultaneous independent receivers (TRX 0 + TRX 1). IQ output up to
192 kHz (±96 kHz instantaneous bandwidth). Full TX on HF/6m. Driver: `rf_bench.sunsdr`.
IP address TBD. ExpertSDR3 version TBD.

### SunSDR standalone

**✓ Wideband HF band scanner** (`projects/sunsdr/hf-scanner/`)
The 192 kHz IQ rate means a single capture covers ±96 kHz — the entire 30m band in one
shot, 40m in 3 captures, 20m in 4.  Sweep 0–55 MHz ~19× faster than the KiwiSDR.
Similar to hf-monitor but exploiting the wide bandwidth: at each step, run the full PSD
and extract all signals above threshold simultaneously.  SQLite log + rolling display.

**✓ VHF band monitor** (`projects/sunsdr/vhf-monitor/`)
Use TRX 1 on the SunSDR's VHF port (144 MHz) while TRX 0 handles HF.
Monitor 2m with the dual-receiver capability.
The SunSDR's VHF sensitivity is better than the RTL-SDR's; this replaces
bubba-detector's `--ham-vhf` mode with higher dynamic range.
Combines naturally with bubba-detector's VHF SSB opening detection.

**✓ Dual-band simultaneous scanner** (`projects/sunsdr/dual-scan/`)
TRX 0 sweeps HF (e.g. 40m/20m), TRX 1 holds on the 2m calling frequency.
Two SunSDR instances in two threads, unified SQLite log.  First rf-bench project
to exploit true dual-receiver operation on one device.

**✓ TX waveform injection / arbitrary signal generator** (`projects/sunsdr/tx-arb/`)
Use `transmit_iq()` to inject Python-generated waveforms: WSPR, FT8, CW, test tones,
swept signals for antenna impedance analysis.  The SunSDR becomes a calibrated HF signal
source.  Combine with the KiwiSDR or IC-7300 as the monitoring receiver.
⚠ Requires valid amateur licence and appropriate power level.

**HF noise figure measurement** (`projects/sunsdr/noise-figure/`)
Improved version of the KiwiSDR NF project: the SunSDR's wide IQ bandwidth means you
can characterize an entire 100 kHz band in one capture (rather than stepping through
10 kHz windows).  Use a calibrated noise source, Y-factor method, log NF vs frequency
across HF.  More accurate than the KiwiSDR version due to simultaneous multi-frequency
measurement within one capture window.

### SunSDR + IC-7300 integrations

**✓ HF transmitter characterization** (`projects/sunsdr/tx-characterize/`)
Use the IC-7300 as the HF transmitter and the SunSDR as the measurement receiver.
At 192 kHz IQ bandwidth, simultaneously measure: harmonic levels, IMD products,
spectral purity, carrier suppression, ALC response — all in a single capture.
The SunSDR has better dynamic range and calibrated amplitude tracking than the RTL-SDR.
Compare with `projects/radio/transmitter-test/` which uses the SSA.

**✓ Phase noise measurement** (`projects/sunsdr/phase-noise/`)
Tune IC-7300 to a stable carrier; SunSDR receives it.  At 192 kHz IQ rate, the full
close-in phase noise profile (±96 kHz offsets) is visible in one capture.  Compare
to the SSA-based `projects/radio/phase-noise/` — the SunSDR approach is faster
(one capture vs. SSA sweep) but less dynamic range at large offsets.

**✓ SO2R two-radio integration** (`projects/sunsdr/so2r/`)
Single-operator two-radio (SO2R) contest automation: IC-7300 on one band,
SunSDR on another.  Coordinate VFO changes, band switches, and PTT inhibit between
the two radios via rf_bench.icom and rf_bench.sunsdr.  Log all activity with
unified timestamps.

**✓ Cross-receiver S-meter calibration** (`projects/sunsdr/cal-smeter/`)
Same signal, both receivers simultaneously.  Map SunSDR dBFS → IC-7300 dBm using
the IC-7300's calibrated S-meter as the reference.  Extends the existing
`projects/radio/rx-crosscheck/` (RTL-SDR vs IC-9700) to the HF SunSDR path.

### SunSDR + KiwiSDR integrations

**✓ Diversity reception** (`projects/sunsdr/diversity/`)
Two antennas → KiwiSDR + SunSDR, both tuned to the same frequency simultaneously.
Combine the IQ streams in software (equal-gain combining, maximal-ratio combining,
or switched diversity) to improve SNR on weak HF signals.  The KiwiSDR's GPS-
disciplined clock makes coherent combining feasible if the phase offset is calibrated.

**✓ Full HF spectrum comparison** (`projects/sunsdr/hf-compare/`)
Both devices sweep the same HF band simultaneously; compare detected signals,
signal strengths, and noise floors.  Useful for antenna comparison (different antenna
on each device) or for verifying the SunSDR driver's amplitude accuracy against the
KiwiSDR's known-good GPS-referenced signal path.

### SunSDR + RTL-SDR integrations

**✓ Wideband station monitor** (`projects/sunsdr/station-monitor/`)
SunSDR handles 0–55 MHz + 100–150 MHz via TCI; RTL-SDR fills in 55–1766 MHz.
Together: near-complete coverage from 100 kHz to 1.7 GHz with a combined unified
SQLite detection log.  The SunSDR's 192 kHz IQ and the RTL-SDR's 2.4 MHz IQ complement
each other — no single device does both well.

**✓ VHF band-opening relay** (`projects/sunsdr/band-opening-relay/`)
SunSDR TRX 1 monitors 6m (50 MHz) with its HF receiver port — not possible on KiwiSDR.
When 50.125 MHz USB activity is detected, write a JSON alert file for bubba-detector
to boost VHF/UHF SSB priority.  More direct than the KiwiSDR's 10m-beacon proxy
because the SunSDR can actually receive 6m directly.

### SunSDR + SSA integrations

**✓ VHF transmitter measurement** (`projects/sunsdr/vhf-tx-test/`)
Use an IC-9700 as the 2m transmitter, SunSDR TRX 1 as the wideband IQ receiver,
and the SSA3032X as the calibrated reference for harmonic content and spectral
purity.  The SunSDR's 192 kHz IQ captures the full ±96 kHz around the carrier
simultaneously for IMD product analysis.

---

## TCI Audio Router — Linux sound device bridge

**Status:** Discussed, not yet started.

**The problem:** Linux ham software (WSJT-X, Fldigi, Direwolf, JS8Call, etc.) expects
audio I/O via a standard sound card — an ALSA/PulseAudio/PipeWire device it can open
like hardware.  ExpertSDR3 exposes audio via TCI (WebSocket binary stream), not as a
sound device.  There is currently no bridge.

**The solution that covers ~99% of use cases:**

A single Python CLI tool that:
1. Connects to ExpertSDR3 TCI and subscribes to `RX_AUDIO_STREAM` (StreamType=1)
2. Writes the decoded PCM audio to a named audio device via `sounddevice` (PortAudio)
3. Ham software reads from the other side of an ALSA loopback (`snd-aloop`)

```bash
tci-audio --host 192.168.1.x --device "Loopback: PCM (hw:Loopback,0)"
# ham software then uses hw:Loopback,1 as its soundcard input
```

One `modprobe snd-aloop` creates the virtual loopback.  `sounddevice` (PortAudio)
abstracts ALSA/PulseAudio/PipeWire — the same code works on all three.

**Minimal CLI:**
```
tci-audio --host HOST
          [--port 50001]
          [--trx 0]
          [--rate 8000]       # 8/12/24/48 kHz; sent as AUDIO_SAMPLERATE to TCI
          [--device DEVICE]   # default: system default output
          [--list-devices]    # print available audio devices and exit
```

**Key implementation note — ring buffer is mandatory:**
TCI pushes audio in ~32 ms chunks (256 samples @ 8 kHz).  PortAudio's callback
also fires in chunks, on its own timer.  Without a ring buffer between them, the
two timers drift and cause dropouts.  A `collections.deque` or `queue.Queue`
circular buffer is ~20 extra lines but the difference between glitchy and clean.

**TCI audio setup sequence (sent before AUDIO_START):**
```
AUDIO_SAMPLERATE:8000;
AUDIO_STREAM_SAMPLE_TYPE:int16;
AUDIO_STREAM_CHANNELS:1;
AUDIO_START:0;
```
The binary frame header carries `sample_rate`, `format`, `length`, and `channels`
fields — read from each frame rather than hardcoded, so mismatches are self-correcting.

**Why not stdout?**
Stdout piped into `aplay` works for manual listening but requires the user to manage
the pipe and know ALSA syntax.  Writing directly to a named device is one command
with no user plumbing, and it's what ham software actually needs.

**TX (sending audio to TCI for transmission) — deferred:**
TX is harder, not because of the audio path (TCI `TX_CHRONO` is a clean
request/response model — server sends a timestamp asking for N samples, client
responds with N samples from its buffer), but because of **PTT coordination**.
Something must assert `TRX:0,true,tci;` to tell ExpertSDR3 to use TCI audio for TX,
and that requires integrating with how the ham software does PTT (Hamlib CAT, RTS/DTR,
VOX, etc.).  That's a system-integration problem, not a TCI protocol problem.

Options for PTT when TX is eventually added:
- **VOX:** detect audio level above threshold in the TX buffer → assert PTT.
  Simple, adds ~50–100 ms latency, no external dependencies.
- **Hamlib integration:** watch for PTT state changes via rigctld polling.
  Correct, but adds a dependency and requires the user to configure Hamlib.
- **Named pipe / socket:** external PTT signal from ham software.
  Clean but requires per-app configuration.

For now, the RX-only tool covers monitoring, decoding (WSJT-X, Fldigi, Direwolf),
recording, and spectrum display — the majority of ham software use cases.

**Implemented:** `projects/sunsdr/tci-audiopipe/tci-audiopipe.py`
**Dependencies:** `websocket-client` (already in sunsdr driver), `numpy`, `pacat`/`parec` (PulseAudio/PipeWire CLI tools)

