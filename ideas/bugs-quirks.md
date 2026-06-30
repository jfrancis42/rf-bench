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

### Arduino + W5100 4-channel relay board (`hardware/arduino-relay-board/`)

- **Relay module on the bench is active-HIGH, not active-LOW.** The
  generic 4-channel module currently wired to the Arduino energizes
  when the control pin is driven HIGH. Initial firmware defaulted
  `RELAY_ACTIVE_HIGH = false` (the cheap-module convention) and on
  first bring-up every relay was in the inverted state. Flipped to
  `true` and the inversion went away with no other changes. Anyone
  swapping to a different module should expect to verify polarity
  again and may need to flip it back.
- **W5100 has only 4 hardware sockets, not 8.** One is consumed by the
  listening server, so the practical max-concurrent-clients is 3
  (`MAX_CLIENTS = 3` in the sketch). On a W5500 swap, bump it up to
  6–7. The Arduino `Ethernet` library auto-detects either chip; no
  other code change is needed.
- **The Vilros Ethernet R3 shield's microSD CS (D4) must be driven
  HIGH in `setup()` even if you're not using the SD.** Both the W5100
  and the SD chip share SPI; a floating SD CS will corrupt every
  Ethernet transfer with garbage. Symptom: DHCP succeeds, then the
  TCP server hangs on the first packet.

---

*Last revised: 2026-06-25. Per-driver and per-project READMEs are the
authoritative source for any specific implementation detail; this
document is the cross-cutting reference.*
