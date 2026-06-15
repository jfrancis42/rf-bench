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
| FX2LAFW Logic Analyzer (×3) | 8-ch, 24 MHz max, Saleae-compatible | USB VID=08a9 PID=0014 | `rf_bench.fx2lafw.FX2LAFWLogicAnalyzer` | ✅ Driver complete, hardware untested |
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

### Logic analyzers

#### FX2LAFW "24MHz 8CH" Saleae-compatible logic analyzers

- **Count:** 3 units (tagged primary, backup, spare in registry)
- **Hardware:** Cypress FX2-based, 8 digital channels, 24 MHz max sample rate
- **USB:** VID=08a9 PID=0014 (Saleae Logic compatible)
- **Firmware:** fx2lafw (open source)
- **Driver:** `rf_bench.fx2lafw.FX2LAFWLogicAnalyzer`, version 0.1.0 local (not yet published)
- **Connection:** USB, auto-detected by driver
- **Sample rates:** 1, 2, 3, 4, 6, 8, 12, 16, 24 MHz (discrete steps only)
- **Status:** ✅ Driver complete and installed, hardware not yet tested

**Implementation:** Uses `sigrok-cli` subprocess rather than direct libsigrok Python bindings. More portable, easier installation, proven stable. Trade-off: subprocess overhead (~100ms), acceptable for logic analyzer use cases.

**Supported features:**
- Multi-channel capture (1-8 channels)
- VCD file export (open in GTKWave or PulseView)
- Duration-based or sample-count-based capture
- Software triggering (edge detection, pattern matching in Python)

**Protocol decode:** Planned but not yet implemented in driver. For now:
1. Save capture to VCD with `save_vcd()`
2. Open in PulseView (has built-in I2C/SPI/UART/1-Wire/CAN decoders)
3. Or call `sigrok-cli -P <protocol>` from Python subprocess

**Future:** Direct protocol decode integration via `sigrok-cli -P` subprocess, or direct libsigrok Python bindings if streaming becomes important.

**Use cases:**
- I2C/SPI/UART bus analysis
- Protocol reverse engineering
- Timing violation detection
- PWM duty cycle measurement
- Frequency counter (1 Hz to 12 MHz)
- Digital bus debugging
- Signal integrity analysis (when combined with SDG test patterns)

**Limitations:**
- No hardware triggering (capture starts immediately, use software triggering in Python)
- No streaming mode (fixed-length captures only)
- USB bandwidth limits long captures at 24 MHz × 8 channels
- Protocol decode requires external tools (PulseView or sigrok-cli)

**Three identical units:** Registry handles via tags:
- Unit #1: `tags: [logic, digital, portable, primary]` — main bench, drawer
- Unit #2: `tags: [logic, digital, portable, backup]` — portable kit
- Unit #3: `tags: [logic, digital, portable, spare]` — storage box

Access via registry:
```python
from rf_bench.instruments import Registry
registry = Registry()
la = registry.get('logic-analyzer')  # Returns first available
# or
la = registry.get('logic-analyzer', tag='primary')
```

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

