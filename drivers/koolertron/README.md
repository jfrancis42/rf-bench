# rf-bench-drivers-koolertron

> **Status:** Tested 2026-06-08 against a real **MHS-5225A** (raw model code
> `5225A5040000`, CH340 USB-serial) and confirmed working: frequency,
> amplitude, waveform, duty-cycle, offset, phase, attenuator, and
> per-channel set/get; master output enable; built-in frequency counter
> (loopback test confirms ±7 ppm against the unit's commanded frequency);
> period-mode counter; snapshot of full state. **Arbitrary waveform upload
> (ARB0-ARB15) added 2026-06-17** — implemented from wd5gnr's public-domain
> reference implementation and **hardware-verified working** (1024-sample
> uploads to all 16 slots, ~200-300 ms per upload). Sweep commands
> implemented from documentation but not yet exercised against hardware.

Python driver for the **Koolertron / MHinstek MHS-5200A series** dual-channel
DDS arbitrary-waveform signal generator with built-in frequency counter and
sweep generator. Sold under many brand names — **Koolertron**, **MHinstek**,
**KKmoon**, and various AliExpress / eBay listings labelled "200MSa/s 12Bit
DDS". The hardware and USB protocol are common to every variant; only the
upper sine-wave frequency limit changes per model suffix:

| Model    | Sine FS  |
|----------|----------|
| MHS-5206A | 6 MHz   |
| MHS-5212A | 12 MHz  |
| MHS-5220A | 20 MHz  |
| MHS-5225A | 25 MHz  |

This driver was written from scratch using the **public protocol document**
listed in [Protocol reference and credits](#protocol-reference-and-credits)
below. No source code from any other implementation was copied or modified;
the wire protocol was verified live against an MHS-5225A on 2026-06-08.

## Installation

```bash
pip install rf-bench-drivers-koolertron
```

The only runtime dependency is `pyserial`.

## Quick start

```python
from rf_bench.koolertron import (
    MHS5200A, Waveform, CounterMode, Gate, Atten,
)

with MHS5200A() as gen:                         # auto-detect CH340 / PL2303
    print(gen.identify())                       # 'MHS-5225A (5040000)'

    # Function generator
    gen.set_frequency(1, 1_000_000)             # CH1: 1 MHz
    gen.set_amplitude(1, 1.0)                   # CH1: 1.0 Vpp into 50 Ω
    gen.set_waveform(1, Waveform.SINE)
    gen.set_frequency(2, 100_000)               # CH2: 100 kHz
    gen.set_waveform(2, Waveform.SQUARE)
    gen.set_duty_cycle(2, 25.0)                 # CH2: 25% duty
    gen.output_on()                             # master enable (BOTH ch)

    # Arbitrary waveform (16 slots: ARB0..ARB15)
    import math
    sine = [math.sin(2*math.pi*i/1024) for i in range(1024)]
    gen.upload_arb_normalized(0, sine)          # upload to slot 0
    gen.set_waveform(1, Waveform.ARB0)          # use it on CH1

    # Built-in frequency counter (Ext.IN connector on front)
    hz = gen.measure_frequency_hz(gate=Gate.S10)
    print(f"counter sees {hz:.1f} Hz")

    gen.output_off()
```

## Optional calibration

The driver supports optional per-channel amplitude correction and
frequency offset correction. With no cal file present, the driver works
using the unit's built-in (factory) calibration.

To enable corrections, run the calibration tool at
`projects/signal-sources/koolertron-cal/` to characterise your specific
unit. Results are saved to `~/.koolertron_mhs5200_cal.json` and picked
up automatically by the driver.

```python
with MHS5200A() as gen:
    print(gen.calibration_info())
    # -> {'loaded': True, 'frequency_ppm_offset': 11.77, ...}

    # Frequency is pre-corrected for the unit's TCXO offset
    gen.set_frequency(1, 1_000_000)             # actually ≈ 999_988 Hz
                                                 # at the wire so output is 1 MHz

    # set_amplitude_dbm is amp-corrected per channel and per frequency
    gen.set_amplitude_dbm(1, 25_000_000, 0.0)   # delivers 0 dBm at 25 MHz
                                                 # (compensates ~4.7 dB rolloff)
```

To bypass an existing cal file:

```python
gen = MHS5200A(calibration=False)
```

## Hardware

| Item | Value |
|------|-------|
| Instrument | Koolertron / MHinstek MHS-5206A / 5212A / 5220A / 5225A (and rebrands: KKmoon, et al.) |
| USB chip | QinHeng CH340 (1a86:7523) on older firmware, PL2303 (067b:2303) on newer |
| Serial | 57600 8N1, no flow control, CR LF terminators |
| Per-channel parameters | frequency, amplitude, waveform, duty cycle, offset, phase, output attenuator |
| Master output | Global enable (both channels together — hardware quirk) |
| Counter | EXT IN connector on rear; modes: frequency, count, period, +/− pulse width, duty cycle |
| Sweep | Linear or logarithmic, configurable start/stop/time |
| Memory | 10 setup slots (0..9; slot 0 is the power-on default) |
| TTL connector | 10-pin header on rear panel (see below) |

### TTL connector pinout

The 10-pin header on the rear panel (labelled "TTL-Ext." in the manual, "TTL"
on some unit panels) provides digital I/O and power:

| Pin | Function | Notes |
|-----|----------|-------|
| 1   | TTL1     | Synchronized with CH1 (duty cycle follows CH1) |
| 2   | GND      | |
| 3   | TTL2     | Synchronized with CH2 (duty cycle follows CH2) |
| 4   | GND      | |
| 5   | TTL3     | Synchronized with CH1 (duty cycle follows CH1) |
| 6   | GND      | |
| 7   | TTL4     | Synchronized with CH1 (duty cycle follows CH1) |
| 8   | +5V      | Power supply output |
| 9   | TTL IN   | Frequency counter input (alternative to front-panel EXT IN) |
| 10  | +5V      | Power supply output |

#### TTL Input (pin 9)

Selectable as the counter input source via `counter_setup(source_ttl=True)` or
`measure_frequency_hz(source_ttl=True)`. Use this for measuring digital/logic-
level signals where TTL threshold detection is more reliable than the analog
front-panel input.

#### TTL Outputs (pins 1, 3, 5, 7)

Four independent TTL-level outputs synchronized with the main channels:

- **TTL1, TTL3, TTL4**: All synchronized with **CH1**. Duty cycle determined by CH1 waveform.
- **TTL2**: Synchronized with **CH2**. Duty cycle determined by CH2 waveform.

**Phase relationships:** When CH1 and CH2 are synchronized (tracking mode), all
four TTL outputs synchronize together with phase relationships determined by the
CH1/CH2 phase difference setting. The manufacturer describes this as "four
variable phase difference of TTL output."

**Voltage levels:** LOW <0.3V, HIGH 1V–10V (MHS-5200A spec).

**Use cases:**
- Triggering multiple instruments synchronized to the main generator channels
- Multi-phase clock generation when CH1/CH2 are phase-locked
- Logic-level copies of waveforms for TTL/CMOS interfacing
- Duty-cycle-matched sync outputs

**Important:** These outputs mirror the main channel waveforms at TTL levels.
They are **not independently controllable** via the serial protocol — their
behavior is determined by CH1 and CH2 settings. To generate a pure TTL square
wave on CH1/CH2 outputs (maximizing slew rate), use waveform code `w05` (CH1)
or `w15` (CH2) via the serial protocol.

**+5V pins (8, 10)** provide power for external logic. Current limit unknown.

**Reference:** MHS-5200A Operating Manual (2015.05), Section 15: "4-channel TTL
output function" and Section 10: "Having four variable phase difference of TTL
output." Ships as "TTL-Ext. connector" accessory.

## API summary

### Identification and configuration

| Method / attribute | Description |
|-------------------|-------------|
| `MHS5200A(port=None, calibration=None)` | Connect; auto-detects CH340 / PL2303 if port omitted. Calibration: `None` = auto-load `~/.koolertron_mhs5200_cal.json` if present; `False` = ignore any cal; `str` = path to specific JSON; `dict` = use as-is. |
| `gen.model`           | Friendly model string, e.g. `"MHS-5225A"` |
| `gen.raw_model`       | Full raw `:r0c` payload, e.g. `"5225A5040000"` |
| `gen.identify()`      | Combined string, e.g. `"MHS-5225A (5040000)"` |
| `gen.calibration_info()` | Dict describing the active calibration, or `{loaded: False}` |
| `gen.port`            | Active serial port path |
| `MHS5200A.find_port()` | Class method returning the first compatible USB-serial port found, or None |

### Per-channel waveform parameters

| Method | Description / units |
|--------|--------------------|
| `set_frequency(ch, hz)` / `get_frequency(ch)` | Hz; pre-corrected by `frequency_ppm_offset` if cal loaded. Wire register: 0.01 Hz steps. |
| `set_amplitude(ch, vpp)`  / `get_amplitude(ch)` | Vpp into 50 Ω (matches scope reading at 50 Ω; front panel shows 2× this open-circuit value). Wire register: 5 mV steps. NOT cal-corrected. |
| `set_amplitude_dbm(ch, freq, dbm)` | Set amplitude as target dBm into 50 Ω at the given frequency. Frequency-aware; uses calibration if loaded. |
| `set_waveform(ch, w)`   / `get_waveform(ch)`  | `Waveform` enum (SINE/SQUARE/TRIANGLE/UP_SAW/DOWN_SAW/ARB0..ARB15). Special: `Waveform.TTL` (wire code `w05`/`w15`) switches to TTL digital output mode with maximized slew rate for fast edges. |
| `set_duty_cycle(ch, %)` / `get_duty_cycle(ch)` | Percent (wire: 0.1 % steps) |
| `set_offset(ch, signed)` / `get_offset(ch)` | Signed -120..+120 (wire: 0..240 with 120 = no offset) |
| `set_phase(ch, deg)`    / `get_phase(ch)` | Degrees, 0..359 |
| `set_attenuator(ch, a)` / `get_attenuator(ch)` | `Atten.MINUS_20DB` (-20 dB pad) or `Atten.ZERO_DB` |
| `set_channel_enable(ch, on)` / `get_channel_enable(ch)` | Per-channel enable (use master `output_on/off` for normal use) |

### Master output (global to both channels)

| Method | Description |
|--------|-------------|
| `output_on()`  | Enable output (both channels — global) |
| `output_off()` | Disable output |

### Frequency counter (Ext.IN connector on front)

| Method | Description |
|--------|-------------|
| `counter_setup(mode, gate, source_ttl=False)` | Configure mode + gate window + source |
| `counter_start()` / `counter_stop()` / `counter_reset()` | Run / stop / zero |
| `read_counter()` | Raw counter value (units depend on mode) |
| `read_counter_hz()` | FREQ-mode reading scaled to Hz (firmware 5040000) |
| `measure_frequency_hz(gate, ...)` | One-shot helper: setup + start + poll-until-stable + read + stop. Default gate is `Gate.S10` (10 s), reliable from 10 kHz upward. |

`CounterMode` enum: `FREQ`, `COUNT`, `PULSE_HIGH`, `PULSE_LOW`, `PERIOD`, `DUTY`.
`Gate` enum: `S1` (1 s), `S10` (10 s, default for `measure_frequency_hz`), `S0_1` (100 ms), `S0_01` (10 ms).

**Counter input range (firmware 5040000):**

| Gate | Reliable input range |
|------|----------------------|
| `Gate.S10` | ≥ 10 kHz |
| `Gate.S1`  | ≥ 10 MHz |
| `Gate.S0_1` / `Gate.S0_01` | High-frequency only; not characterised |

Below the listed minimum, the counter often fails to lock; the driver's
`measure_frequency_hz` returns the last value read, but it may be
inaccurate. Caller should sanity-check against the expected input.

### Sweep generator (CH1)

| Method | Description |
|--------|-------------|
| `sweep_setup(start_hz, stop_hz, time_s, log=False)` | Configure |
| `sweep_start()` / `sweep_stop()` / `get_sweep_state()` | Run / stop / query |

### Arbitrary waveforms (ARB0..ARB15)

The MHS-5200A has 16 user-defined arbitrary waveform slots (ARB0 through ARB15), each storing 1024 samples at 8-bit resolution (0-255). After uploading a waveform, select it with `set_waveform(channel, Waveform.ARB0 + slot)`.

| Method | Description |
|--------|-------------|
| `upload_arb(slot, samples)` | Upload 1024 integers (0-255) to slot 0-15 |
| `upload_arb_normalized(slot, samples)` | Upload 1024 floats (-1.0 to +1.0) to slot 0-15 |

**Example — generate and upload a sine wave:**

```python
import math
from rf_bench.koolertron import MHS5200A, Waveform

with MHS5200A() as gen:
    # Create normalized sine wave (1024 samples, -1.0 to +1.0)
    sine = [math.sin(2 * math.pi * i / 1024) for i in range(1024)]
    
    # Upload to slot 0 (ARB0)
    gen.upload_arb_normalized(0, sine)
    
    # Output it on channel 1
    gen.set_frequency(1, 100_000)
    gen.set_waveform(1, Waveform.ARB0)
    gen.output_on()
```

**Example — integer samples (0-255 range):**

```python
# Ramp waveform
ramp = [int(i * 255 / 1023) for i in range(1024)]
gen.upload_arb(1, ramp)
gen.set_waveform(1, Waveform.ARB1)
```

**Protocol reference:** Arbitrary waveform upload protocol reverse-engineered by **Al Williams (wd5gnr)** and documented in <https://github.com/wd5gnr/mhs5200a> (public domain). The `setwave5200` shell script in that repository provided the reference implementation from which the wire protocol was understood. This Python implementation is independent.

**Upload format:** The device receives waveforms as 16 chunks of 64 samples each. Each chunk is sent as `:a<slot><chunk>\r\n` followed by a comma-separated list of 64 decimal values. The device replies `ok\r\n` after each chunk. A 10 ms inter-chunk delay is required for reliable uploads (empirically determined from the reference implementation).

### Memory slots

| Method | Description |
|--------|-------------|
| `save_slot(slot=0)` | Save current full setup to slot 0..9 |
| `load_slot(slot=0)` | Load setup; slot 0 is the power-on default |

### Power amplifier (units that have it)

| Method | Description |
|--------|-------------|
| `power_amp(on)` / `get_power_amp()` | Enable/disable optional power amp |

### Other

| Method | Description |
|--------|-------------|
| `snapshot()` | Return a dict with the model + per-channel parameters of both channels |
| `close()`    | Close the serial port (automatic via context manager) |

## Live-test results (2026-06-08)

Confirmed against real **MHS-5225A**, firmware/hardware code `5040000`, USB
adapter CH340 (1a86:7523) on `/dev/ttyUSB0`. CH1 output patched to the rear
EXT IN connector to enable closed-loop counter testing.

```
identify : MHS-5225A (5040000)

TEST 1: CH1 frequency set/get round-trip — 1 Hz to 25 MHz, all OK
TEST 2: CH1 amplitude — 0.5 / 1 / 2.5 / 5 V, all OK
TEST 3: CH1 waveform — SINE/SQUARE/TRIANGLE/UP_SAW/DOWN_SAW, all OK
TEST 4: duty 25 %, offset +30, phase 90°, all OK
TEST 5: CH1=1 MHz / CH2=100 kHz independent — OK
TEST 6: master output on / off — OK (no exception)
TEST 7: frequency counter loopback (CH1 -> EXT IN at 1.234567 MHz):
        measured 1234576.1 Hz   (+7.4 ppm error vs commanded)
TEST 8: counter PERIOD mode at 1.234 MHz: 811 ns (matches 1/1.234 MHz ≈ 810 ns)
TEST 9: snapshot() returns full state for both channels
        0 failures
```

## Protocol reference and credits

This driver's wire protocol is implemented directly from the public reverse-
engineering work of the amateur-radio and electronics community. **All credit
for protocol discovery, reverse-engineering, and the documentation that made
this driver possible belongs to those authors.** Their work is gratefully
acknowledged below; this driver simply exposes their findings through a
clean Python API.

The single most useful resource was:

> **wd5gnr (Al Williams)** — *"Serial Protocol for MHS-5200A"*, document
> version 2, dated 9 August 2015. The complete protocol document, including
> the frequency counter, sweep, and arbitrary waveform upload commands, is
> included in the `MHS5200AProtocol.pdf` file of his open-source reference
> implementation.
>
> Repository: <https://github.com/wd5gnr/mhs5200a>
> Document:   `MHS5200AProtocol.pdf` in that repository.
> Reference implementation: `setwave5200` shell script (public domain).
>
> This protocol document is the canonical public reference; without it, only
> the basic 8 set/get commands from standard serial probing would be known.
> The frequency counter, sweep, arbitrary-waveform upload, and memory-slot
> commands all come from his reverse-engineering work.
>
> **Arbitrary waveform upload:** Al Williams' `setwave5200` shell script
> (explicitly marked "Public Domain — use it how you like" in its header)
> provided the reference implementation from which the wire protocol for
> uploading 1024-sample waveforms to the device's 16 ARB slots was
> understood. The upload format (16 chunks of 64 samples, `:a<slot><chunk>`
> header, comma-separated decimal values, 10 ms inter-chunk delay) was
> derived from studying that script and the accompanying AWK processing
> files. This Python implementation is independent; no code was copied.

Other community sources that helped confirm details:

- **eevblog forum thread**: *"MHS-5200A serial protocol reverse engineered"*
  — community teardown identifying the CH340G + STM8 + Lattice MachXO2
  internals, and providing the additional commands (gate value encoding,
  counter mode select) that supplement the wd5gnr document.
  <https://www.eevblog.com/forum/testgear/mhs-5200a-serial-protocol-reverse-engineered/>

- **sigrok wiki — MHINSTEK MHS-5200A page**: the canonical hardware spec
  reference (R-2R-ladder DAC, dual-channel architecture, ~175 MS/s actual
  sample rate vs. the "200 MSa/s" front-panel claim, and the two USB-serial
  vendor IDs in use).
  <https://www.sigrok.org/wiki/MHINSTEK_MHS-5200A>

If you are the author of one of the sources above and feel this credit
should be expanded or reworded, please open an issue on the rf-bench
repository.

## Hardware verified

- **Make/model**: Sold to the author as a KKmoon-branded "200MSa/s 12Bit"
  dual-channel DDS function generator with frequency counter (no model
  number on the front panel).
- **Identifies as**: `MHS-5225A`, raw model code `5225A5040000`.
- **Channel 1 upper sine frequency**: 25 MHz (set/get round-trip OK at 25 MHz).
- **USB chip**: QinHeng CH340 (`1a86:7523`).
- **Confirmed working**: 2026-06-08, all tests passing against
  `/dev/ttyUSB0`.

## License

GPL-3.0-or-later.
