# rf-bench — Reference and Project Index

The single reference for the bench: what hardware is here, which drivers exist
and what state they're in, which projects are built vs planned, and the bugs
and quirks that matter when using any of it.

This file is intentionally exhaustive. If something contradicts a per-driver
or per-project README, the README wins — those track the code, this tracks
the design intent and the cross-cutting context.

---

## Table of Contents

1. [Status legend](#status-legend)
2. [Hardware inventory](#hardware-inventory)
   - [Siglent bench instruments](#siglent-bench-instruments)
   - [Radios](#radios)
   - [SDRs](#sdrs)
   - [Programmable PSU / load / DMMs](#programmable-psu--load--dmms)
   - [Signal sources (auxiliary)](#signal-sources-auxiliary)
   - [GPIB instruments (pending KISS-488)](#gpib-instruments-pending-kiss-488)
   - [Microcontroller / protocol bridges](#microcontroller--protocol-bridges)
   - [GPS, relays, accessories](#gps-relays-accessories)
3. [Driver status](#driver-status)
4. [Virtual instrument panels](#virtual-instrument-panels)
5. [Built projects — by domain](#built-projects--by-domain)
   - [drivers/* — driver self-tests and bring-up](#driver-self-tests)
   - [projects/rf](#projectsrf)
   - [projects/radio](#projectsradio)
   - [projects/gps](#projectsgps)
   - [projects/signal-sources](#projectssignal-sources)
   - [projects/scope](#projectsscope)
   - [projects/spectrum](#projectsspectrum)
   - [projects/dmm](#projectsdmm)
   - [projects/power](#projectspower)
   - [projects/components](#projectscomponents)
   - [projects/audio](#projectsaudio)
   - [projects/flipper](#projectsflipper)
   - [projects/rtlsdr](#projectsrtlsdr)
   - [projects/kiwisdr](#projectskiwisdr)
   - [projects/sunsdr](#projectssunsdr)
   - [projects/esp32](#projectsesp32)
6. [Hardware-pending projects](#hardware-pending-projects)
   - [HP 8712B VNA (projects/vna/)](#hp-8712b-vna)
   - [Solartron 7151 6.5-digit DMM](#solartron-7151)
   - [XL9535 relay board (projects/relay/)](#xl9535-relay)
   - [KiwiSDR (IP TBD)](#kiwisdr-pending)
   - [SunSDR2 Pro (IP TBD)](#sunsdr-pending)
7. [Future project ideas (not yet started)](#future-project-ideas)
   - [Power & batteries](#future-power)
   - [RF / measurement chain](#future-rf)
   - [Koolertron MHS-5225A applications](#future-koolertron)
   - [Solartron 7151 applications](#future-solartron)
   - [Cross-cutting bench services](#future-cross-cutting)
   - [TCI Audio Router](#future-tci-router)
8. [Bench-internal traceability chain (calibration plan)](#traceability-chain)
9. [Cross-cutting bugs and quirks (one-stop reference)](#cross-cutting-bugs)

---

## Status legend

Used throughout this document and intended to match the markers in per-driver
and per-project READMEs.

| Marker | Meaning |
|--------|---------|
| ✅ | Built, tested against hardware, working well |
| 🔶 | Built, tested, has known limitations or is partially exercised |
| 🧪 | Code complete, limited or no hardware testing |
| ❌ | Hardware not present yet — code may exist, but is unverified |
| 💭 | Idea only — no code in the tree |

For projects, "tested" means a real run against the real instrument, not just
an import or a `--demo` smoke test.

---

## Hardware inventory

Concise table first, then per-instrument detail (specs, connection, known
bugs, calibration notes). For deeper technique notes (e.g. Carson's rule
workaround for the SSA's missing FM-demod SCPI), see
[cross-cutting bugs](#cross-cutting-bugs).

| Instrument | Class | IP / Port | Driver | Status |
|------------|-------|-----------|--------|--------|
| SSA3032X Plus | Spectrum analyzer 9 kHz–3.2 GHz, TG to 0 dBm | 10.1.1.60:5025 | `rf_bench.siglent.SSA3000X` | ✅ |
| SDG1062X | Function generator, 2-ch, 60 MHz | 10.1.1.55:5025 | `rf_bench.siglent.SDG1000X` | ✅ |
| SDS2504X Plus | Oscilloscope, 4-ch, 500 MHz, AWG (licensed), MSO-capable | 10.1.1.58:5025 | `rf_bench.siglent.SDS2000X` | ✅ |
| SDM3045X | Bench DMM, 4.5-digit | 10.1.1.63:5025 | `rf_bench.siglent.SDM3000X` | ✅ |
| SPD3303X-E | Triple-output PSU, 2 × 32 V/3.2 A + fixed | 10.1.1.56:5025 | `rf_bench.siglent.SPD3303X` | ✅ |
| RB3X25 | Reflection bridge (passive, no driver) | — | — | ✅ |
| Icom IC-7300 (×2) | HF + 6 m, 100 W, USB CAT | rigctld 4532 (model 3073) | `rf_bench.icom.IC7300` | ✅ |
| Icom IC-9700 | 2 m + 70 cm + 23 cm, USB or LAN CAT | rigctld 4532 (model 3081) | `rf_bench.icom.IC9700` | ✅ |
| Yaesu FT-891 | HF + 6 m, 100 W, USB CAT | rigctld 4532 (model 1036) | `rf_bench.yaesu.FT891` | ✅ |
| Yertai ET5406A+ | DC load 200 W / 120 V / 20 A | greybox /dev/ttyUSB0 9600 | `rf_bench.yertai.ET5406A` | ✅ |
| Koolertron MHS-5225A | DDS 25 MHz dual-ch + counter | 10.1.1.52 /dev/ttyUSB0 57600 | `rf_bench.koolertron.MHS5200A` | ✅ |
| Bus Pirate v3/v4/v5 | SPI/I2C/UART/GPIO master | /dev/ttyUSB* (v3/v4) or /dev/ttyACM1 (v5) | `rf_bench.buspirate.BusPirate` | ✅ |
| Flipper Zero | Sub-GHz / IR / RFID / NFC multi-tool | /dev/ttyACM0 | `rf_bench.flipper.FlipperZero` | 🔶 OOK + 2-FSK TX/RX verified; IR/RFID/NFC untested |
| RTL-SDR Blog v4 | 500 kHz–1766 MHz, 2.4 MHz IQ | librtlsdr USB | `rf_bench.rtlsdr.RTLSDR` | ✅ IQ + streaming tested |
| gpsd | GPS daemon client | localhost:2947 | `rf_bench.gpsd.GPSD` | ✅ tested |
| HP 8712B | 2-port VNA 300 kHz–1.3 GHz | 10.1.1.70:1234 (KISS-488 GPIB) | `rf_bench.hp.HP8712B` | ❌ pending KISS-488 |
| Solartron 7151 | 6.5-digit DMM, IEEE-488 | 10.1.1.70:1234 (KISS-488 GPIB) | `rf_bench.solartron.Solartron7151` | ❌ pending KISS-488 |
| XL9535 relay board | I2C 16-port expander → relays | via Bus Pirate I2C | `rf_bench.relay.XL9535` | ❌ board ordered 2026-06-03 |
| KiwiSDR | HF receiver 0–30 MHz, GPS-disciplined, 12 kS/s | host:8073 WebSocket | `rf_bench.kiwisdr.KiwiSDR` | 🧪 IP TBD |
| SunSDR2 Pro | HF/6 m + 2 m, 192 kS/s IQ, RX+TX, dual TRX | ExpertSDR3 TCI :50001 | `rf_bench.sunsdr.SunSDR` | 🧪 IP TBD |

**KISS-488 conflict to resolve when GPIB comes online:** the HP 8712B and the
Solartron 7151 both default to GPIB primary address 16. They cannot share the
adapter at the same address. Move one of them at the rear-panel switches
before powering both on.

---

### Siglent bench instruments

All Siglent instruments speak raw SCPI over TCP port 5025. **No pyvisa anywhere
in the stack** — this is a deliberate choice; pyvisa adds 50+ MB of
dependencies and a layer of behaviour to debug. `rf_bench.siglent` opens a
plain `socket` and reads/writes ASCII or 488.2 binary blocks directly.

#### SSA3032X Plus — spectrum analyzer

- **Range:** 9 kHz – 3.2 GHz; tracking generator to ~+0 dBm output (0 dBm max
  per Siglent spec; observed ~−10 dBm without the +10 dBm option).
- **Firmware:** 3.2.2.6.3R2.
- **REFL option installed.** The antenna analyzer project deliberately *does
  not* use it (manual calibration is more flexible), but it's available.
- **Resolution bandwidths:** 1 Hz – 1 MHz; the driver carries the standard
  Siglent RBW set as a constant in `rf_bench.utils`.

**Firmware quirks to remember:**

- `:SENS:SWE:POIN` is **silently ignored** on this firmware. The trace is
  always 751 points regardless of the request. Driver:
  `setup_band()` calls `get_sweep_points()` to read the actual count back
  before computing RBW. Any code that relied on `--points 1001` to make a
  finer sweep is wrong on this firmware — it ran with 751.
- All FM-demod SCPI commands (`:CALC:DMOD:FM?`, `:MEAS:FM?`, every variant)
  return `−113 Undefined header`. The path to FM deviation on this instrument
  is **Carson's rule on the spectrum trace** — measure the −26 dB occupied
  bandwidth at the carrier and back out Δf. `projects/radio/fm-deviation/`
  uses this approach.

**Cross-instrument amplitude oddity:** the SDS2504X Plus reads roughly **3×
higher** voltage than the 50 Ω-equivalent the SDG reports, into a 1 MΩ scope
input. Open-circuit voltage doubling explains 2× of that; the remaining ~1.5×
factor is unresolved but consistent and reproducible. Relative amplitude
measurements are accurate; absolute scope-vs-SDG comparisons are not unless
calibrated. See [calibration project](#projectsrf).

#### SDG1062X — function generator

- **Range:** DC – 60 MHz, 2 channels.
- **Resolution:** 0.001 Hz.
- **Output level:** ≈ −50 dBm to ~+24 dBm into 50 Ω. (For dBm → Vpp the
  driver uses `7.0711×10^(dBm/20)` — i.e. 0 dBm = 0.6325 Vpp into 50 Ω. The
  `7.958` constant in older code is wrong by ~4 dB.)
- **Firmware:** 1.01.01.33R3.

**Firmware quirks:**

- `C1:BSWV?` responses append unit suffixes: `FRQ,1000HZ`, `AMP,0.2V`,
  `AMPDBM,−10.0dBm`. `float()` raises ValueError on these strings. The
  driver's `_strip_unit()` regex strips suffixes before parsing.
- See "Scope AWG uses SDG-style commands" under SDS2504X — the scope's
  built-in AWG is programmed with the same `C1:BSWV` syntax as the SDG, not
  the documented `WGEN`.

**Phase noise:** acceptable for IMD work; not adequate for −140 dBc/Hz close-in
phase noise measurements. Use the koolertron or an external low-noise
synthesizer for those.

#### SDS2504X Plus — oscilloscope

- **Specs:** 4 channels, 500 MHz BW (full upgrade installed), 10 M deep
  memory per channel, AWG built-in, MSO option (probe pod ordered, untested).
- **Firmware:** 5.4.0.1.6.2R5. Has accumulated nine documented bugs over
  driver development; all have implemented workarounds. The full list is in
  the [cross-cutting bugs section](#cross-cutting-bugs); the most
  load-bearing ones to know:

  1. **`:WAVeform:DATA?` intermittently returns the 1000-sample display
     buffer instead of the requested deep memory.** Workaround: every
     waveform call retries once if it gets back ≤1000 samples on a wide
     timebase. Almost always succeeds on the second try.
  2. **TDIV/VDIV must be changed while stopped, or the next acquisition is
     5 corrupt bytes.** Driver always issues `:STOP` before reconfiguring.
  3. **TDIV change while stopped silently corrupts the VDIV register.**
     Driver explicitly re-applies `C{n}:VDIV` after every TDIV change.
  4. **Built-in AWG uses `C1:BSWV`, not `:WGEN:` as the programming guide
     claims.** The driver was rewritten around this.
  5. **PAVA returns NaN immediately after `:STOP`.** Driver runs a
     short-window acquisition with a 0.5 s sleep before reading.
  6. **Trailing `\n` after binary block reads sits in the TCP socket and
     poisons the next PAVA query.** Driver drains all bytes with a 50 ms
     timeout after every binary read.

- **Amplitude offset:** see SSA3032X note above — the scope at 1 MΩ reads
  3× higher than the SDG reports at 50 Ω, ~1.5× of which is unexplained.
  Use scope amplitude readings *relative to a reference capture*, not as
  absolute dBm. Run `projects/rf/calibration/` for a one-shot map.

#### SDM3045X — bench DMM

- **Specs:** 4.5-digit, V/A/R/C/freq/temp, 4-wire Kelvin available, internal
  thermocouple input (Type K).
- **Capacitance test frequency:** ~1 kHz. For RF-frequency capacitance use
  `projects/rf/rf-impedance/`, not the DMM.
- **Resolution floor:** ~5 mV LSB on the 10 V range, ~10 ppm fractional.
  This is the binding constraint for log-detector linearity, voltage-
  reference drift, and matched-pair component selection — when 4.5 digits
  is not enough, the path is the [Solartron 7151 at 6.5 digits](#solartron-7151).

#### SPD3303X-E — programmable PSU

- **Specs:** CH1+CH2: 0–32 V / 0–3.2 A independent; CH3: fixed 2.5/3.3/5 V
  selectable.
- **CH3 is hardware-fixed.** `set_voltage(3, ...)` raises ValueError —
  there is no SCPI command to override the front-panel switch.
- **`OUTP?` is unreliable** on all firmware revisions tested. Sometimes
  returns empty. Driver's `is_enabled()` reads the SYST:STAT? bitmask
  (bits 4–6) instead.

#### RB3X25 — reflection bridge

Passive accessory. Used by the antenna analyzer, scalar VNA, and balun
analyzer projects. No driver, no firmware, no quirks; just remember the
nominal directivity is ~25 dB, which sets the noise floor on any return-loss
measurement using it.

---

### Radios

All three radios speak Hamlib via rigctld on TCP port 4532 (default). The
drivers wrap rigctld; they do not poke CI-V or CAT bytes directly. This
keeps the driver code small but means rigctld must be running before
instantiation.

#### Icom IC-7300 (HF + 6 m)

- **Hamlib model:** 3073.
- **CAT setup:** Menu → Set → Connectors → CI-V Baud Rate = 115200.
  Connection: USB-B to /dev/ttyUSB0 → `rigctld -m 3073 -r /dev/ttyUSB0 -s 115200`.
- **S-meter:** S9 = −93 dBm (HF / ITU standard).
- **AGC off** (`set_agc("off")`) is a true hardware bypass.
- **USB audio:** presents as a USB sound card on Linux at 48 kS/s — the
  basis of `projects/audio/audio-chain/` and several future ideas.
- Two units on hand → enables `projects/radio/antenna-isolation/` (#70 in
  the original numbering).

#### Icom IC-9700 (2 m + 70 cm + 23 cm)

- **Hamlib model:** 3081. Connection over USB or LAN (Hamlib ≥ 4.3 for LAN).
- **S-meter:** S9 = −73 dBm (VHF/UHF / ITU standard) — note the 20 dB
  offset from the IC-7300.
- **Satellite mode:** the only radio in the bench with simultaneous TX on
  one band and RX on another. Driver exposes `set_satellite_mode()`,
  `update_doppler()`, `set_split()`, `set_ptt()`, `set_tx_frequency()`,
  `band_of()` on top of the shared HF API.
- **AGC off** is a true bypass (same as IC-7300).

#### Yaesu FT-891 (HF + 6 m)

- **Hamlib model:** 1036. CAT rate menu 031 = 38400 (factory default);
  `rigctld -m 1036 -r /dev/ttyUSB0 -s 38400`.
- **Preamp/atten extras:** `set_preamp(PREAMP_OFF | PREAMP_AMP1)` and
  `set_att(0|6|12)` (6 dB steps, not the IC-7300's 10/20 dB).
- **AGC "off" is NOT a bypass** — it maps to the slowest AGC setting only.
  Code that asserts true RX bypass on the FT-891 is wrong.

#### Shared radio API (drop-in compatible across all three)

`get_frequency / set_frequency / get_mode / set_mode / get_strength /
get_strength_settled / set_agc / get_agc / set_rf_gain / close`.

`get_strength()` returns Hamlib's raw STRENGTH (dB re S9 in Hamlib 4.x,
range ≈ −54 to +60). To get dBm you need a calibration table — that's
exactly what `projects/radio/receiver-test/` produces.

---

### SDRs

#### RTL-SDR Blog v4

- **Range:** 500 kHz – 1766 MHz; instantaneous IQ BW 2.4 MHz; 1 PPM TCXO;
  bias tee (5 V / 180 mA) for inline LNA power.
- **Driver:** `rf_bench.rtlsdr.RTLSDR`, thin wrapper around pyrtlsdr.
  Version 0.1.2 on PyPI.
- **Single-process constraint:** only one process can hold the dongle at a
  time. The driver checks and raises a clear error rather than letting
  librtlsdr abort.
- **PPM calibration is mandatory before serious work.** Stored in
  `~/.rtlsdr_cal.json` and applied by every `set_center_freq()` call.
  Calibrate against an SDG carrier on a known frequency monitored by the
  SSA.
- **Power readings are uncalibrated dBFS**, not dBm. Some projects ship a
  per-frequency dBFS→dBm table at `~/.rtlsdr_vhf_cal.json` produced by
  `projects/radio/rx-crosscheck/` — when that file is present, displays
  show calibrated dBm.

#### KiwiSDR (pending hardware bring-up)

- **Range:** 0 – 30 MHz HF; **GPS-disciplined TCXO** (no PPM cal needed).
- **Sample rate:** **12 000 S/s fixed** (FPGA, not configurable). Per-channel
  bandwidth ±5–6 kHz.
- **4 standard / 8 extended simultaneous channels** on one device.
- **Driver:** `rf_bench.kiwisdr.KiwiSDR`, WebSocket on host:8073, returns
  IQ as int16 big-endian. Code complete locally; **not yet on PyPI** and
  **IP not yet assigned** — update this document when it is.
- **API is intentionally compatible with the RTL-SDR driver**
  (`capture_iq`, `stream_iq`, `power_spectrum`) — same project code can
  switch between them as the HF backend.

#### SunSDR2 Pro (pending hardware bring-up)

- **Range:** 0.1 – 55 MHz (RX + TX) plus 100 – 150 MHz (RX-only).
- **IQ:** 48 / 96 / **192 kS/s** — at 192 kS/s, ±96 kHz instantaneous BW
  (entire 40 m CW band in one capture).
- **Dual TRX:** TRX 0 + TRX 1 simultaneous, independent frequencies.
- **TX IQ injection** — the only TX-capable SDR in the bench.
- **Driver:** `rf_bench.sunsdr.SunSDR`, WebSocket TCI to ExpertSDR3 on
  port 50001. Code complete; not yet on PyPI; IP TBD.
- **TCI quirks worth knowing before bring-up** (full list under
  [cross-cutting bugs](#cross-cutting-bugs)): only one TCI client at a time
  per ExpertSDR3 instance, audio defaults always come back as
  48 000/float32/2 regardless of what was requested, and the binary frame
  header carries the actual sample rate and format which should be read from
  each frame, not assumed.

---

### Programmable PSU / load / DMMs

#### Yertai ET5406A+ DC load

- **Specs:** 200 W / 120 V / 20 A, single channel.
- **Modes:** CC / CV / CR / CP / CC-CV / CR-CV / TRAN / LIST / SCAN /
  SHOR / BATT / LED.
- **Connection:** CH340 USB-serial → /dev/ttyUSB0 on greybox (10.1.0.16),
  9600 baud. Appears as a serial port even when the load is powered off.
- **Driver:** `rf_bench.yertai.ET5406A`, version 0.1.0 on PyPI. Wraps
  upstream `philpagel/ET54.py` (commit 82be1da, 2026-06-02). Includes the
  `read_all()` field-order fix that was merged upstream as PR #5
  (was returning `(I, V, P, R)` instead of `(V, I, P, R)`).
- **Timing quirk:** must wait ≥200 ms between commands; occasionally takes
  much longer to respond. Random test failures if not handled — driver
  inserts the wait and retries.
- **OCP latch** persists through `off()` calls and can only be cleared by
  power cycle or front-panel reset. There is no SCPI command for it.

#### Koolertron / MHinstek MHS-5225A — DDS gen + counter

The MHS-5200A series is heavily rebranded (KKmoon, AliExpress "200MSa/s
12-bit DDS", various eBay listings). The unit on the bench identifies as
**MHS-5225A** (25 MHz CH1 sine ceiling, raw model code `5225A5040000`).

- **Specs:** Dual-channel DDS, 25 MHz sine, 200 MSa/s 12-bit, sine /
  square / triangle / up-saw / down-saw + 16 user-arb slots, per-channel
  ampl / duty / offset / phase / atten, built-in frequency counter, sweep,
  10 memory slots.
- **Counter modes:** FREQ / COUNT / PERIOD / PULSE+ / PULSE− / DUTY,
  configurable gate.
- **Driver:** `rf_bench.koolertron.MHS5200A`, version 0.1.0 local — ready
  to publish but not yet on PyPI. Tested against the bench unit on
  2026-06-08, all 9 tests pass.
- **Connection:** CH340 USB at 57600 baud → 10.1.1.52 /dev/ttyUSB0.
- **Protocol:** ASCII over 57600 8N1, `:` prefix + CRLF suffix, implemented
  from the public `wd5gnr/MHS5200AProtocol.pdf` (CC-licensed reverse-
  engineering, 2015-08-09).

**Quirks worth designing around:**

- **Master output enable is global.** `:s1b1` enables both channels.
  Workaround: set the unwanted channel's amplitude to 0 to "disable" it
  while keeping CH1 controllable independently.
- **Counter takes 2–3 gate cycles to settle** after `counter_start()`. The
  driver's `measure_frequency_hz()` waits for it.
- **Counter unit scaling (firmware 5040000):**
  - FREQ mode reads in **tenths of Hz** (1.234 MHz → 12345761 → 1 234 576.1 Hz)
  - PERIOD mode reads in **nanoseconds**
  - Other modes return raw integers
- **TCXO accuracy ~7 ppm** uncalibrated. Useful as a reference counter
  against a GPS-disciplined source.

**What the MHS adds to the bench:**

- A second function generator complementing the SDG. Pairing them gives
  4 independent simultaneous channels for IMD testing.
- A built-in counter — sanity check on any other generator's commanded vs
  actual output.
- A standalone sweep generator that runs without controller intervention.

#### SDM3045X — covered above under [Siglent](#siglent-bench-instruments).

---

### Signal sources (auxiliary)

#### Si5351A breakouts (Adafruit / SparkFun / AliExpress)

- **Range:** ~3 kHz – 200 MHz, three independent outputs.
- **Cost:** ~$5/breakout.
- **Limitations:** 2 PLLs for 3 outputs — CLK0 has PLL-A; CLK1 and CLK2
  share PLL-B and reprogramming one perturbs the other. Phase noise
  ~−100 dBc/Hz at 10 kHz offset (mediocre). Harmonics −10 to −30 dBc.
  **Not** a substitute for the SDG in IMD or NF measurements.
- **Use cases:** clock injection, LO generation, rough frequency injection,
  permanent clock source for homebrew radio projects, GPS-disciplined
  reference (`projects/gps/freq-cal/`).
- Programming: I2C via Bus Pirate. Address 0x60 (ADDR pin low) or 0x61.
  Crystal: 25 MHz on most breakouts; 26 MHz on some — use `--xtal 26e6` if so.

#### ADF4351 / Si5153 / Si5156 / AD9833 / AD9851 / AD9850

Synthesizer and DDS modules used by `projects/signal-sources/synthesizer-
characterizer/` and `projects/signal-sources/dds-characterizer/` — described
under those projects. All driven via SPI through the Bus Pirate.

---

### GPIB instruments (pending KISS-488)

The KISS-488 Rev 2 Ethernet-GPIB adapter is the bridge — until it's
installed, both instruments below are inert. They share the same TCP
endpoint (`10.1.1.70:1234`) once it is.

#### HP 8712B VNA

- **Specs:** 300 kHz – 1.3 GHz, 2-port, full SOLT calibration, complex
  S11/S12/S21/S22.
- **Default GPIB primary address:** 16.
- **Driver:** `rf_bench.hp.HP8712B`, status ❌ — code complete from
  documentation, untested. Several SCPI commands flagged "Verify against
  HP 8712B manual" — particularly `:CALC:PAR:MOD`, `:SENS:S11:STAT`,
  `:TRIG:SOUR`, `:SOUR:POW`, `:SENS:CORR:STAT?`. Not yet published.

#### Solartron 7151 6.5-digit DMM (1985)

- **Specs:** 6.5-digit Computing Multimeter, full DC voltage (200 mV–2 kV),
  AC voltage, kΩ (20 k – 20 M), DC/AC current. Resolution scales with
  integration time:

  | Integration | Resolution | Use |
  |-------------|-----------|-----|
  | 6.7 ms (I0) | 3.5 digits | Free-running |
  | 40 ms (I1) | 4.5 digits | 50 Hz line-cycle averaging |
  | 50 ms (I2) | 4.5 digits | 60 Hz line-cycle averaging |
  | 400 ms (I3) | 5.5 digits | General bench |
  | 1.6 s (I5) | 5.5 digits | Filter-on, low-noise |
  | ~8 s (I4) | 6.5 digits | "Walking window", best resolution |

- **Default GPIB primary address:** 16 (rear-panel DIP switches).
- **Driver:** `rf_bench.solartron.Solartron7151`, status ❌ — code
  complete, untested. Predates SCPI; uses single-letter ASCII commands
  (M, R, N, T, …) extracted from User Manual ND/7151/2 Issue 2 (1985)
  and the open-source `s7150.c` reference driver. Several uncertainties
  flagged in the README:
  - DIODE mode (M5) — present in `s7150.c` but not in the OCR'd 7151
    manual; may be 7150/7150+ only.
  - `++spoll` Prologix response format assumed decimal integer.
  - Reading-string whitespace pattern designed against an OCR example.

**Calibration commands** (`HI`/`LO`/`WRITE`/`REFRESH`) are gated behind a
2.5 mm CAL shorting plug; the driver exposes them but they're a maintenance
procedure, not a measurement.

---

### Microcontroller / protocol bridges

#### Bus Pirate (v3 / v4 / v5)

- **Versions:** v3/v4 are USB CDC over FTDI/PIC → /dev/ttyUSB*. v5 is
  RP2040-based and exposes **two** USB CDC ACM ports — connect to
  /dev/ttyACM1 (binary), not /dev/ttyACM0 (terminal).
- **v5 one-time setup:** in the v5 terminal, `binmode` → select **2**
  (BPIO2 FlatBuffers protocol) and save as default. Without this the
  binary mode the driver expects isn't exposed.
- **Capabilities:** SPI master, I2C master, UART passthrough, GPIO,
  3.3 V / 5 V switchable I/O, on-board PSU.
- **Driver:** `rf_bench.buspirate.BusPirate`, version 0.1.0 on PyPI
  (published 2026-06-03). Status 🧪 — code follows the documented binary
  protocol but **not yet exercised against physical hardware** in the
  rf-bench context. Bring-up testing is the prerequisite to all Bus
  Pirate-dependent projects.

#### Flipper Zero

- **Sub-GHz radio:** TI CC1101, 300–928 MHz in three bands (300–348,
  387–464, 779–928 MHz; gaps in between are dead). OOK, 2-FSK, 4-FSK,
  GFSK, MSK.
- **125 kHz LF RFID** read/write/emulate.
- **13.56 MHz NFC** read.
- **IR** transmit and receive (TSOP-style demodulator IC; tuning unknown
  until measured by `projects/flipper/ir-rx-response/`).
- **GPIO** PA4–PA7 read/write.
- **Connection:** USB-C → /dev/ttyACM0; protocol is **protobuf RPC** with
  a 4-byte length prefix.
- **Driver:** `rf_bench.flipper.FlipperZero`, version 0.2.1 on PyPI.
  Status 🔶: Sub-GHz OOK and 2-FSK TX/RX verified; **GFSK and MSK are
  RX-only** because the firmware crashes on GFSK/MSK TX presets. Workaround
  in `projects/rtlsdr/ook-link/`: stick to OOK and 2-FSK on the TX side.
  IR / RFID / NFC subsystems not yet end-to-end tested.

---

### GPS, relays, accessories

#### gpsd

- **Hardware:** any gpsd-supported receiver. Bench unit is a u-blox over
  /dev/ttyACM0 or /dev/ttyACM1 at 9600 baud, gpsd 3.27.5.
- **Driver:** `rf_bench.gpsd.GPSD`, version 0.1.1 on PyPI. Status ✅. Auto-
  reconnects with exponential backoff; default 10 s stale-data timeout.
  Provides lat/lon/alt (prefers MSL → falls back to HAE → falls back to
  raw), speed, heading, DOP, satellite counts; metric + imperial units.
- **Bug fixed in 0.1.1:** startup race where `_last_tpv_monotonic` was
  not initialized before the background thread checked `is_stale`.

#### XL9535 16-bit I2C I/O expander → relay coil driver

- **Variants:** XL9535, PCA9535, TCA9535 — identical register maps.
- **Connection:** Bus Pirate I2C master. I2C address 0x20–0x27 (chip
  pins set this).
- **Driver:** `rf_bench.relay.XL9535`. Status ❌ — code complete,
  hardware ordered 2026-06-03 but not yet tested.
- **Power note:** relay coils need an external 5 V supply (ULN2803 driver
  array on the board). The Bus Pirate's 150 mA isn't enough beyond 1–2
  relays. Use SPD3303X-E CH3 (fixed 5 V).
- **Hard caveat about the on-board relays:** the cheap HK19F-style signal
  relays found on standard XL9535 boards are **DC/audio only** — 20–40 dB
  of insertion loss above ~5 MHz with poor isolation. Use the XL9535 as a
  *coil driver* for external RF-rated relays (reed: 100 MHz; Omron G6Y:
  3 GHz; coaxial relays: as needed) when switching RF. The XL9535 driver
  is identical regardless of which relay type is wired downstream of it.

---

## Driver status

| Driver | PyPI name | Version | Status | Notes |
|--------|-----------|---------|--------|-------|
| `rf_bench.siglent` | `rf-bench-drivers-siglent` | 0.1.0 | ✅ | All 5 instruments tested; 9 documented firmware workarounds |
| `rf_bench.icom` | `rf-bench-drivers-icom` | 0.1.0 (0.2.0 local) | ✅ | IC-7300 + IC-9700; Hamlib-based. Local 0.2.0 adds IC-9700 satellite/PTT extras, unpublished |
| `rf_bench.yaesu` | `rf-bench-drivers-yaesu` | 0.1.0 | ✅ | FT-891 only |
| `rf_bench.utils` | `rf-bench-drivers-utils` | 0.1.0 | ✅ | Pure RF math — no instruments |
| `rf_bench.yertai` | `rf-bench-drivers-yertai` | 0.1.0 | ✅ | ET5406A+ DC load. Wraps philpagel/ET54.py with field-order fix |
| `rf_bench.gpsd` | `rf-bench-drivers-gpsd` | 0.1.1 | ✅ | gpsd JSON/TCP client; tested with u-blox |
| `rf_bench.koolertron` | (not yet on PyPI) | 0.1.0 local | ✅ | MHS-5225A, tested 2026-06-08 — ready to publish |
| `rf_bench.rtlsdr` | `rf-bench-drivers-rtlsdr` | 0.1.2 | ✅ | Thin pyrtlsdr wrapper + PPM cal cache |
| `rf_bench.flipper` | `rf-bench-drivers-flipper` | 0.2.1 | 🔶 | Sub-GHz OOK + 2-FSK only; IR/RFID/NFC untested |
| `rf_bench.buspirate` | `rf-bench-drivers-buspirate` | 0.1.0 | 🧪 | Published, untested in rf-bench context |
| `rf_bench.kiwisdr` | (not yet on PyPI) | 0.1.0 local | 🧪 | Code complete; IP TBD |
| `rf_bench.sunsdr` | (not yet on PyPI) | 0.2.0 local | 🧪 | Code complete; IP TBD |
| `rf_bench.relay` | (not on PyPI) | local | ❌ | Hardware ordered 2026-06-03 |
| `rf_bench.hp` | (not on PyPI) | local | ❌ | Pending KISS-488 adapter |
| `rf_bench.solartron` | (not on PyPI) | local | ❌ | Pending KISS-488 adapter |

`pip install rf-bench` (meta-package, 0.6.0) pulls in the published drivers.

### Radio API compatibility

The IC-7300, IC-9700 and FT-891 share a common interface:

```
get_frequency, set_frequency, get_mode, set_mode,
get_strength, get_strength_settled, set_agc, get_agc,
set_rf_gain, close
```

This means project scripts can take `--radio ic7300|ic9700|ft891` and use the
same code path. **AGC and S-meter behave differently across the three:**

- IC-7300 / IC-9700: `set_agc("off")` is a true bypass; S9 = −93 dBm (HF) /
  −73 dBm (VHF/UHF).
- FT-891: `set_agc("off")` maps to slowest only — *not* a bypass. S-meter is
  less linear than the IC-7300; calibration table from `projects/radio/
  receiver-test/` is necessary.

**IC-9700 extras:** `get_vfo / set_vfo`, `get_split / set_split`, PTT,
TX-frequency split, `set_satellite_mode / clear_satellite_mode`,
`update_doppler`, `band_of`. None of these exist on the HF radios — code
that needs them must guard.

**FT-891 extras:** `set_preamp(PREAMP_OFF | PREAMP_AMP1)`, `set_att(0|6|12)`.
Note the 6 dB increments (vs IC-7300 10/20 dB) — projects that loop over
attenuation values need to know which radio they're talking to.

---

## Virtual instrument panels

All panels are Tkinter-based, share a common architecture (state dataclass +
poll thread + UI refresh loop + thread-safe command queue + `--demo` mode +
safety shutdown on close), and live next to the driver they exercise.

| Panel | Path | Status | Working controls |
|-------|------|--------|------------------|
| SDG1062X | `drivers/siglent/sdg1062x_panel.py` | ✅ | Output on/off per ch, waveform, frequency, level |
| SDM3045X | `drivers/siglent/sdm3045x_panel.py` | ✅ | All measurement functions (VDC/VAC/IDC/IAC/2W/4W Ω/FREQ/DIODE/CONT) |
| SPD3303X | `drivers/siglent/spd3303x_panel.py` | ✅ | Output on/off per ch, tracking mode (INDEP/SERIES/PARA), V and I setpoints |
| SSA3032X | `virtual-instruments/ssa3032x_panel.py` | ✅ | Live spectrum trace; tracking gen on/off + level; markers; peak search |
| SDS2504X | `virtual-instruments/sds2504x_panel.py` | ✅ | 4-channel waveform plot; timebase / V/div / trigger / on-off; Vpp / freq / RMS readouts |
| ET5406A+ | `drivers/yertai/et5406a_panel.py` | ✅ | Mode (CC/CV/CP/CR/CC-CV), input on/off, set points; demo mode |
| IC-7300 | `drivers/icom/ic7300_panel.py` | ✅ | Mode, AGC, frequency entry, band buttons (160m–10m); blue/amber Icom theme |
| FT-891 | `drivers/yaesu/ft891_panel.py` | ✅ | Mode, AGC, preamp, attenuator, frequency, bands; green Yaesu theme |
| RTL-SDR | `drivers/rtlsdr/rtlsdr_panel.py` | ✅ | Live waterfall + FFT |
| Flipper | `drivers/flipper/flipper_panel.py` | ✅ | Multi-tab: Sub-GHz / IR / RFID-NFC / GPIO |
| Si5351 | `projects/signal-sources/si5351-gen/si5351_panel.py` | ✅ | 3-channel freq + drive strength; Tkinter alternative to the curses TUI |

All panels accept `--demo` (no hardware required) for UI testing and `--interval MS` for refresh rate. All panels that command outputs (PSU, load, function gen, radios) safely disable the output on window close.

---

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

### projects/esp32

ESP32-based SCPI-over-WiFi controllers. Each project connects to WiFi, exposes SCPI commands on TCP port 5025 (industry standard), and controls external hardware via GPIO/I2C/SPI/UART. Common pattern across all projects: Arduino IDE sketch (~400-600 lines), WiFi credentials embedded in source, IEEE 488.2 common commands (*IDN?, *RST, SYST:ERR?), domain-specific SCPI subsystem. Each project directory contains: `.ino` sketch, `README.md` (user guide with wiring, commands, examples), `README` (developer notes), `test_*.py` (Python demo).

**Status codes:** ✅ = tested on hardware; 🔨 = built to documentation (not yet tested); 💭 = idea only.

**All 35 ESP32 SCPI projects are now built to documentation (🔨)**. Each includes complete `.ino` firmware, `README.md` user guide, and `README` developer documentation. Hardware testing pending.

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

## Hardware-pending projects

### HP 8712B VNA

(`projects/vna/` — all ❌, blocked on KISS-488 adapter.)

The HP 8712B adds **phase** to every measurement that the SSA scalar VNA
already does, plus full SOLT calibration.

| Project | Notes |
|---------|-------|
| `sparams/` | Full S11/S21/S12/S22 magnitude + phase; Touchstone .s2p export. |
| `group-delay/` | τ_g(f) = −dφ/dω from S21 phase; built-in `GDELAY` mode for cross-check. |
| `impedance/` | Z = R + jX from calibrated S11; Smith chart + Cartesian R/X plots. |
| `transistor/` | S-parameters + MAG / K-factor / stability circles / unilateral figure of merit. |
| `tline/` | Velocity factor, Z₀, attenuation α(f), propagation constant — from open-then-shorted S11 measurements at known length. |
| `filter/` | Filter passband ripple / stopband / shape factor / group delay; pass-fail mask. |
| `antenna/` | Feed-point Z = R + jX vs frequency; replaces the SSA scalar antenna analyzer for everything but its passband range. |

**Bring-up plan** — once KISS-488 is installed:
1. Set HP 8712B GPIB address ≠ 16 (Solartron defaults to 16 too).
2. `*IDN?` smoke test through the KISS-488.
3. Single-frequency S11 spot measurement before attempting a sweep.
4. Run a SOLT cal sequence (manual, no automation yet).
5. Save cal to `~/.8712b_cal.json`.
6. Run `sparams/` against a known good filter as a regression test.

### Solartron 7151

(❌ blocked on KISS-488 adapter; code in `drivers/solartron/`.)

**Bring-up plan:**
1. Set GPIB DIP switches to a non-conflicting address (e.g. 5).
2. `++mode 1` / `++addr 5` / `A` (DCL) / wait 2 s for the RESTART message.
3. Switch to `U7N0T1` (CR delimiter, literals on, tracking on).
4. `M0R0I3` (DCV, autorange, 5.5 digits) → first reading.
5. Verify reader handles both `LITERALS ON` and `LITERALS OFF` reading
   formats and that the `!` overload flag is detected.

Once verified, the projects that benefit live in
[future Solartron applications](#future-solartron) below — voltage-reference
drift logger, TCR bridge, contact-resistance tester, micro-ohm battery IR,
log-detector linearity, and the cross-cal-with-SDM service.

### XL9535 relay

(❌ board ordered 2026-06-03; `projects/relay/` exists with code.)

| Project | Notes |
|---------|-------|
| `multidut/` | Multi-DUT routing for batch component characterization (crystal sort, capacitor bin, diode Vf match). On-board HK19F relays are fine here — DC/audio only. |
| `solt/` | Automated SOLT calibration fixture for the HP 8712B. **Use reed relays** in the RF path, not the on-board HK19F. |
| `filterbank/` | Band-switched LPF / BPF bank for transmitter / receiver test automation. **External RF-rated relays** driven by XL9535 outputs. |
| `router/` | N×M antenna / source / instrument router. **External coaxial relays.** |
| `normalize/` | 2-relay focused tool for source/DUT/through switching in scalar measurements. **External RF relays.** |

### KiwiSDR (pending)

See [projects/kiwisdr](#projectskiwisdr) — all 🧪 until IP is assigned and
the unit is bench-tested.

### SunSDR (pending)

See [projects/sunsdr](#projectssunsdr) — all 🧪 until ExpertSDR3 is online.
The TCI constraints in [cross-cutting bugs](#cross-cutting-bugs) are
mandatory reading before the first connection; in particular: ONE TCI
client at a time, audio defaults always come back as 48 000/float32/2
regardless of what was requested, and ExpertSDR3 has no TCI audio settings
other than on/off and port number.

---

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

## Bench-internal traceability chain (calibration plan)

A cross-cutting idea that ties several future projects together. The goal
is **±0.05 dB internal-bench-traceability** across SDG / SSA / Koolertron /
scope amplitude — turning the published specs (±0.5 to ±2 dB absolute)
into a tighter relative match good enough for two-tone IMD, NF, and
amplitude comparison work.

The chain:

1. **SDM3045X ↔ Solartron 7151 cross-cal** keeps both DMMs honest at
   10 ppm scale (continuous service — see [future-solartron](#future-solartron)).
   Anchors voltage truth.
2. **SPD3303X-E voltage cal** is verified against the SDM/Solartron at
   two reference points.
3. **Solartron 7151 measures the DC drop across each fixed RF attenuator
   (1 / 10 / 30 dB)** with a calibrated SPD3303X current — at low
   frequency, below RF rolloff. Solartron sees ~1 ppm; that's the ground
   truth for the pad.
4. **Use the characterized pad + SDG to calibrate the SSA3032X amplitude
   flatness** across its 9 kHz–3.2 GHz range.
5. **Use the calibrated SSA to calibrate Koolertron amplitude** (already
   done for one channel/level pair — extend to full range).
6. **Use the calibrated SSA to calibrate the scope amplitude** —
   resolves the unexplained ~1.5× scope-vs-SDG factor by characterizing
   it instead of trying to explain it.

The chain bottoms out at SPD voltage calibration, which the SDM/Solartron
cross-cal keeps honest. Hardware needed: Solartron 7151 (pending KISS-488),
~10 fixed RF attenuators of various values to characterize.

This is the umbrella for `projects/rf/calibration/` (already built,
covering the SDG/SSA/scope/DMM relationship), the future Solartron-side
projects, and a future `projects/rf/atten-cal/` (programmable attenuators
already covered by `projects/signal-sources/dig-atten-cal/`; this would
be the fixed-pad version).

---

## Cross-cutting bugs and quirks

The single place to find every known firmware oddity, instrument quirk,
and gotcha across the bench. Cross-references each item to its driver or
project where the workaround lives.

### SDS2504X Plus oscilloscope (Siglent firmware 5.4.x)

Nine documented bugs, each with implemented workaround in the driver. All
are state-dependent — none are "always broken", but each ruins a
measurement when it triggers.

1. **`:WAVeform:DATA?` intermittently returns the 1000-sample display
   buffer instead of deep memory.** Driver: `capture_audio()` retries when
   it gets back ≤1000 samples on a wide timebase.
2. **0.1 V/div and 0.5 V/div trigger a different firmware bug.** Driver
   excludes those V/div settings from autorange.
3. **Trailing `\n` after binary block reads sits in the TCP socket and
   poisons the next PAVA query.** Symptom: `measure_rms()` returns NaN,
   subsequent calls return each other's values. Driver:
   `_read_binary_block()` drains all bytes with a 50 ms timeout; PAVA
   queries call `_drain()` first.
4. **PAVA silently returns near-zero Vpp when signal is at ±1–3 ADC
   counts with too-large V/div.** Symptom: naïve autorange sees zero,
   selects a far-too-fine V/div, ADC clips the signal. Driver:
   `_autorange_vdiv()` captures at 0.1 V/div, computes 99th-percentile
   peak from raw ADC counts, bypasses PAVA.
5. (Deprecated; merged into #1.)
6. **TDIV/VDIV change while running produces 5-byte all-`+127` corrupt
   acquisition.** Driver always issues `:STOP` before reconfiguring.
7. **PAVA returns NaN/wrong values immediately after `:STOP`.** Driver
   sets short TDIV (2 ms/div = 20 ms window), runs with 0.5 s sleep
   before reading.
8. **TDIV change while stopped silently corrupts the VDIV register.**
   Driver explicitly re-applies `C{n}:VDIV` after every TDIV change
   (tracked in `_last_capture_vdiv`).
9. **Built-in AWG uses SDG-style `C1:` commands, NOT documented WGEN.**
   Programming guide documents `:WGEN:OUTP` etc.; actual firmware uses
   `C1:BSWV WVTP,SINE,FRQ,1000HZ`. Driver was rewritten around this.
   Verified on SDS2504X Plus 2026-06-08.

### SSA3032X Plus spectrum analyzer (firmware 3.2.2.6.3R2)

- **`:SENS:SWE:POIN` is silently ignored.** Trace is always 751 points.
  Driver: `setup_band()` reads `get_sweep_points()` to confirm. The
  `--points` and `--quick` flags in `antenna_analyzer.py` have no effect
  on this firmware.
- **All FM-demod SCPI commands return −113 Undefined header.** No
  software path to FM deviation. Workaround:
  `projects/radio/fm-deviation/` measures the −26 dB occupied bandwidth
  and applies Carson's rule.

### SDG1062X function generator (firmware 1.01.01.33R3)

- **`C1:BSWV?` responses include unit suffixes** (`HZ`, `V`, `dBm`).
  Driver `_strip_unit()` regex strips them before float parse.

### SPD3303X-E PSU (all firmware versions)

- **`OUTP?` query unreliable** — sometimes returns empty. Driver
  `is_enabled()` uses `SYST:STAT?` bitmask (bits 4–6) instead.

### Cross-instrument scope-vs-SDG amplitude

- **Scope at 1 MΩ reads ~3× higher** than the 50 Ω-equivalent SDG
  reports. Open-circuit voltage doubling explains 2×; the remaining ~1.5×
  is unresolved but consistent and reproducible. **Relative scope
  measurements are accurate; absolute scope-vs-SDG comparisons are not.**
  Run `projects/rf/calibration/` to map and account for it.

### ET5406A+ DC load timing

- **Must wait ≥200 ms between commands.** Occasionally takes much longer
  to respond — random test failures if not handled. Driver inserts the
  wait and retries.
- **OCP latch persists through `off()` calls.** No SCPI command to
  clear; only power cycle or front-panel reset. Project code that uses
  OCP should warn the user.

### Koolertron MHS-5225A

- **Master output enable is global** (`:s1b1` enables both channels). To
  "disable" one channel while keeping the other live, set its amplitude
  to 0.
- **Counter takes 2–3 gate cycles to settle.** Driver waits.
- **Counter unit scaling depends on mode** (firmware 5040000):
  FREQ → tenths of Hz, PERIOD → nanoseconds, others → raw integer. Driver
  handles the conversions; raw integer access remains for diagnostics.

### Bus Pirate v5

- **Two USB ACM ports — connect to /dev/ttyACM1 (binary), not
  /dev/ttyACM0 (terminal).**
- **One-time setup required:** in the v5 terminal, `binmode` → select **2**
  (BPIO2 FlatBuffers protocol), save as default. Driver assumes this is
  set.

### Flipper Zero CC1101

- **GFSK and MSK TX presets crash the firmware.** RX in those
  modulations works. Workaround: stick to OOK and 2-FSK on the TX side.
- **CC1101 dead bands:** 348–387 MHz and 464–779 MHz are gaps in the
  CC1101 PLL; no transmission possible there. The synthesizer
  characterizer project verifies this.

### IC-9700 / IC-7300 / FT-891 differences

- **AGC "off"** is a true bypass on IC-7300 and IC-9700. **On the FT-891
  it maps to slowest only — not a bypass.**
- **S-meter calibration** S9 = −93 dBm on HF (IC-7300, FT-891) but
  **−73 dBm on VHF/UHF (IC-9700)**. 20 dB offset that breaks code that
  assumes either is universal.

### IC-7300 / IC-9700 satellite caveat

- **Celestrak `/pub/TLE/` returns 403** as of 2026-05. Use AMSAT (group)
  and SatNOGS (per-NORAD) instead. Hardcoded into
  `projects/radio/satellite/`.

### TCI / ExpertSDR3 (SunSDR2 Pro)

The load-bearing constraints:

1. **Only ONE TCI client at a time per ExpertSDR3 instance.** Multiple
   clients prevent audio from flowing.
2. **Audio defaults are always 48 000 / float32 / 2 channels** on
   startup. After the client sets sample-rate / format / channels, ESDR3
   echoes them back; it may also send the original defaults again after
   AUDIO_START. This is normal, not a bug.
3. **Binary frame structure: 64-byte header + audio data.** Stream type
   is at offset 24: 1 = RX_AUDIO_STREAM, 2 = TX_AUDIO_STREAM, 3 =
   TX_CHRONO. Read the frame header for actual sample rate / format /
   channels — don't hardcode.
4. **RX_AUDIO_STREAM frames are 1088 bytes** (64 header + 1024 audio
   data for 512 int16 samples).

### KISS-488 + GPIB primary-address conflict

- **HP 8712B and Solartron 7151 both default to GPIB primary address
  16.** Either move one of them at the rear-panel switches or only have
  one powered on at a time during early bring-up.

### gpsd

- **Stale-data detection.** Default 10 s timeout. If altitude is
  occasionally absent, driver prefers altMSL → altHAE → `alt`.

### RTL-SDR

- **Single-process constraint** — one process holds the dongle at a
  time. Driver checks and raises a clear error.
- **PPM calibration is mandatory.** Stored in `~/.rtlsdr_cal.json` and
  applied automatically; calibrate against an SDG/SSA carrier before
  serious work.
- **Power readings are dBFS, not dBm.** `~/.rtlsdr_vhf_cal.json` from
  `projects/radio/rx-crosscheck/` provides VHF dBm calibration when
  present.

### dBm ↔ Vpp constant

- **0 dBm into 50 Ω = 0.6325 Vpp**, not 0.4 Vpp. P = Vpp²/8R is the
  right relation. The `7.958` constant in older code was wrong by ~4 dB.
  Use `rf_bench.utils` helpers (`dbm_to_vpp`, `vpp_to_dbm`) — they're
  correct.

---

*Last revised: 2026-06-08. Per-driver and per-project READMEs are the
authoritative source for any specific implementation detail; this
document is the cross-cutting reference.*
