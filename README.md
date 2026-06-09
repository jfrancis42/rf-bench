# rf-bench

> **v0.6.0** — meta-package; installs all driver sub-packages.
>
> ⚠️ **This repository is under active development.** Quality varies by subsystem:
>
> | Status | What it means |
> |--------|--------------|
> | ✅ **Works well** | Tested against real hardware, bugs shaken out, used regularly |
> | 🔶 **Works, known limits** | Tested but with caveats — see project README |
> | 🧪 **Experimental** | Code complete, some hardware testing done, may still have rough edges |
> | ❌ **Untested / incomplete** | Code written but not yet run against physical hardware |
>
> See the table below and individual project READMEs for per-project status.
>
> All import paths (`rf_bench.siglent`, `rf_bench.icom`, `rf_bench.yaesu`,
> `rf_bench.utils`, `rf_bench.buspirate`, `rf_bench.flipper`, `rf_bench.rtlsdr`,
> `rf_bench.yertai`, `rf_bench.gpsd`) are stable across releases.
>
> | Package | PyPI | Status | Provides |
> |---------|------|--------|---------|
> | `rf-bench-drivers-siglent` | [![PyPI](https://img.shields.io/pypi/v/rf-bench-drivers-siglent)](https://pypi.org/project/rf-bench-drivers-siglent/) | ✅ | SSA3000X, SDG1000X, SDS2000X, SDM3000X, SPD3303X |
> | `rf-bench-drivers-icom` | [![PyPI](https://img.shields.io/pypi/v/rf-bench-drivers-icom)](https://pypi.org/project/rf-bench-drivers-icom/) | ✅ | IC7300, IC9700 |
> | `rf-bench-drivers-yaesu` | [![PyPI](https://img.shields.io/pypi/v/rf-bench-drivers-yaesu)](https://pypi.org/project/rf-bench-drivers-yaesu/) | ✅ | FT891 |
> | `rf-bench-drivers-utils` | [![PyPI](https://img.shields.io/pypi/v/rf-bench-drivers-utils)](https://pypi.org/project/rf-bench-drivers-utils/) | ✅ | RF math utilities |
> | `rf-bench-drivers-buspirate` | [![PyPI](https://img.shields.io/pypi/v/rf-bench-drivers-buspirate)](https://pypi.org/project/rf-bench-drivers-buspirate/) | 🔶 | Bus Pirate SPI/I2C/UART master — published 0.1.0; untested against hardware |
> | `rf-bench-drivers-yertai` | [![PyPI](https://img.shields.io/pypi/v/rf-bench-drivers-yertai)](https://pypi.org/project/rf-bench-drivers-yertai/) | ✅ | Yertai ET5406A+ programmable DC load |
> | `rf-bench-drivers-flipper` | [![PyPI](https://img.shields.io/pypi/v/rf-bench-drivers-flipper)](https://pypi.org/project/rf-bench-drivers-flipper/) | 🔶 | Flipper Zero Sub-GHz/IR/RFID/NFC — OOK+FSK TX/RX tested; IR/RFID untested |
> | `rf-bench-drivers-rtlsdr` | [![PyPI](https://img.shields.io/pypi/v/rf-bench-drivers-rtlsdr)](https://pypi.org/project/rf-bench-drivers-rtlsdr/) | 🔶 | RTL-SDR IQ capture, streaming, calibration — streaming tested; some edge cases remain |
> | `rf-bench-drivers-gpsd` | [![PyPI](https://img.shields.io/pypi/v/rf-bench-drivers-gpsd)](https://pypi.org/project/rf-bench-drivers-gpsd/) | ✅ | gpsd GPS client 0.1.1 — tested with u-blox receiver; lat/lon/alt/speed/heading/DOP |
> | `rf-bench-drivers-hp` | not on PyPI | ❌ | HP 8712B VNA via KISS-488 Ethernet-GPIB — local 0.1.0, awaiting hardware |
> | `rf-bench-drivers-solartron` | not on PyPI | ❌ | Solartron 7151 6.5-digit DMM via KISS-488 Ethernet-GPIB — local 0.1.0, awaiting hardware |
> | `rf-bench-drivers-koolertron` | not on PyPI yet | ✅ | MHinstek MHS-5200A series DDS gen + counter (KKmoon rebrand) — tested 2026-06-08 against MHS-5225A |
>
> **Projects** (in `projects/`) follow the same grading. Highlights:
>
> | Project | Status | Notes |
> |---------|--------|-------|
> | `rtlsdr/ook-link` | 🔶 | OOK + 2-FSK TX/RX working; GFSK/MSK RX-only (Flipper TX crashes on those presets) |
> | `rtlsdr/adsb` | ✅ | ADS-B decode, SQLite log, HTTP API — tested with Nooelec SMArt v5 |
> | `rtlsdr/aprs` | 🧪 | Receives APRS via rtl_fm+direwolf; compare-to-APRS-IS mode working |
> | `rtlsdr/recorder` | 🧪 | SigMF IQ recorder — basic operation tested |
> | `rtlsdr/wxsat` | ❌ | Weather satellite pass prediction + decode — untested end-to-end |
> | `flipper/*` | ❌ | Sub-GHz library, IR, RFID, sensor-hub etc. — minimally tested |
> | `relay/*` | ❌ | XL9535 relay board projects — hardware ordered, not yet arrived |
> | `radio/receiver-test` | 🧪 | HF MDS, NF, IP3 — code complete; limited hardware testing |
> | `radio/transmitter-test` | 🧪 | TX power, harmonics, ALC — code complete; limited hardware testing |
> | `radio/beacon-logger` | ❌ | IC-9700 VHF/UHF beacon logger — code complete, untested |
> | `radio/vhf-receiver-test` | ❌ | IC-9700 + SSA MDS/NF on 2m/70cm/23cm — code complete, untested |
> | `radio/fm-deviation` | ❌ | IC-9700 FM deviation via Carson's rule — code complete, untested |
> | `radio/rx-crosscheck` | ❌ | IC-9700 ↔ RTL-SDR cross-calibration — code complete, untested |
> | `radio/aprs-igate` | ❌ | IC-9700 USB audio APRS igate — code complete, untested |
> | `radio/dstar-monitor` | ❌ | IC-9700 D-STAR activity monitor — code complete, untested |
> | `vna/*` | ❌ | HP 8712B VNA — hardware adapter not yet installed |
> | `sunsdr/remote-speaker` | ❌ | Browser TCI audio player — code complete, untested (hardware pending) |

---

Python drivers and RF utilities for bench instrument automation. Connects
to Siglent test equipment via raw TCP/SCPI (no pyvisa required) and to HF
transceivers via [Hamlib](https://hamlib.github.io/) rigctld.

## Instruments supported

### Siglent (`rf_bench.siglent`)

| Class | Instrument family | Tested with | Protocol |
|-------|------------------|-------------|---------|
| `SSA3000X` | SSA3000X Plus series spectrum analyzers | SSA3032X Plus (9 kHz–3.2 GHz) | SCPI / TCP port 5025 |
| `SDG1000X` | SDG1000X series function generators | SDG1062X (2-ch, 60 MHz) | EasyWave / TCP port 5025 |
| `SDS2000X` | SDS2000X Plus series oscilloscopes | SDS2504X Plus (500 MHz) | SCPI / TCP port 5025 |
| `SDM3000X` | SDM3000 series bench multimeters | SDM3045X (4.5-digit) | SCPI / TCP port 5025 |
| `SPD3303X` | SPD3303X series triple-output PSUs | SPD3303X-E (2×32 V/3.2 A + fixed) | SCPI / TCP port 5025 |

### Icom (`rf_bench.icom`)

| Class | Instrument | Protocol |
|-------|-----------|---------|
| `IC7300` | IC-7300 HF/6m transceiver | Hamlib rigctld / TCP port 4532 |

### Yaesu (`rf_bench.yaesu`)

| Class | Instrument | Protocol |
|-------|-----------|---------|
| `FT891` | FT-891 HF/6m transceiver | Hamlib rigctld / TCP port 4532 |

### Bus Pirate (`rf_bench.buspirate`)

| Class | Instrument | Protocol |
|-------|-----------|---------|
| `BusPirate` | Bus Pirate v3/v4 | USB CDC serial / binary BBIO mode |

SPI, I2C, UART, and GPIO master. 3.3V/5V selectable I/O, onboard switchable PSU.
Programs synthesizers (Si5351, ADF4351), DDS chips (AD9833, AD9851),
digital step attenuators, RF switches, and I2C sensors.

### Flipper Zero (`rf_bench.flipper`) ⚠️ UNTESTED

| Class | Instrument | Protocol |
|-------|-----------|---------|
| `FlipperZero` | Flipper Zero (CC1101 Sub-GHz, IR, 125 kHz RFID, NFC) | USB CDC ACM / protobuf RPC |

Sub-GHz 300–928 MHz TX/RX, IR transmit/receive, LF RFID read/emulate, NFC read, GPIO.

### Yertai ET5406A+ (`rf_bench.yertai`)

| Class | Instrument | Protocol |
|-------|-----------|---------|
| `ET5406A` | Yertai ET5406A+ 200 W / 120 V / 20 A programmable DC load | USB-serial (CH340) / SCPI |

CC, CV, CP, CR, CC+CV, CR+CV, battery discharge, transient, list, scan, and LED simulation modes.
Auto-detects CH340 adapter. No pyvisa required.

```python
from rf_bench.yertai import ET5406A

with ET5406A() as load:        # auto-detect CH340
    load.CC_mode(1.0)          # 1 A constant current
    load.on()
    v, i, p, r = load.read_all()
    load.off()
```

### RTL-SDR (`rf_bench.rtlsdr`) ⚠️ UNTESTED

| Class | Instrument | Protocol |
|-------|-----------|---------|
| `RTLSDR` | RTL-SDR Blog v4 (R828D, 500 kHz–1766 MHz, 1 PPM TCXO, bias tee) | USB / librtlsdr |

IQ capture, Welch power spectrum, streaming generator, PPM calibration.
Use the SSA for absolute power measurements; RTL-SDR for demodulation and protocol decode.

### gpsd (`rf_bench.gpsd`)

| Class | Provides | Protocol |
|-------|---------|---------|
| `GPSD` | GPS position, speed, altitude, heading, DOP, satellite counts | TCP / gpsd JSON (localhost:2947) |

Background thread with auto-reconnect and stale-data detection. Metric and imperial
unit accessors. `wait_for_fix()` blocking helper. No external Python dependencies.

```python
from rf_bench.gpsd import GPSD

with GPSD() as gps:
    fix = gps.wait_for_fix(timeout=30)
    print(fix.latitude, fix.longitude, fix.altitude_m, fix.speed_kmh)
    print(fix.altitude_ft, fix.speed_mph, fix.speed_knots)
    print(fix.hdop, fix.satellites_used)
```

### Koolertron / MHinstek (`rf_bench.koolertron`) ✅ TESTED

| Class | Instrument family | Tested with | Protocol |
|-------|------------------|-------------|---------|
| `MHS5200A` | Koolertron / MHinstek MHS-5200A series dual-channel DDS, 200 MSa/s 12-bit, with built-in frequency counter and sweep generator. Sold rebranded as KKmoon and others. | MHS-5225A (25 MHz sine), CH340 USB, firmware/HW code 5040000, confirmed 2026-06-08 | ASCII over USB-CDC virtual serial / 57600 8N1 / CR LF |

Written from scratch from the public wd5gnr/MHS5200AProtocol.pdf reverse-
engineering document; no source code copied from any other implementation.
Full set of supported features: per-channel frequency / amplitude / waveform /
duty cycle / offset / phase / output attenuator / per-channel enable; master
output enable; built-in frequency counter (frequency / count / period / +pulse
width / -pulse width / duty modes; configurable gate; analogue or TTL input
selectable); sweep generator (linear or logarithmic, configurable start /
stop / time); 10 memory slots; optional power amplifier toggle.

```python
from rf_bench.koolertron import MHS5200A, Waveform, Gate

with MHS5200A() as gen:
    print(gen.identify())                          # 'MHS-5225A (5040000)'
    gen.set_frequency(1, 1_000_000)                # CH1: 1 MHz
    gen.set_amplitude(1, 1.0)
    gen.set_waveform(1, Waveform.SINE)
    gen.output_on()
    hz = gen.measure_frequency_hz(gate=Gate.S1)    # via EXT IN counter
    print(f"counter sees {hz:.1f} Hz")
    gen.output_off()
```

### Solartron (`rf_bench.solartron`) ⚠️ UNTESTED

| Class | Instrument family | Tested with | Protocol |
|-------|------------------|-------------|---------|
| `Solartron7151` | Solartron 7151 6.5-digit Computing Multimeter (1985) | none yet — awaiting KISS-488 + Solartron 7151 | IEEE-488 / KISS-488 Ethernet-GPIB / TCP port 1234 |

The Solartron 7151 (and its 7150/7150-plus siblings) speaks a 1985-era
device-specific ASCII command language — single ASCII letters with optional
integer arguments — that pre-dates SCPI. Driver wraps the full shortform
command set (MODE/RANGE/NINES/TRACK/TRIG/DELIMIT/LITERALS/DRIFT/NULL/SRQ/LOCK/
STATUS/CALIBRATE) plus calibration commands (HI/LO/WRITE/REFRESH).

```python
from rf_bench.solartron import Solartron7151

with Solartron7151("10.1.1.70") as dmm:
    dmm.set_mode("VDC")
    dmm.set_range_auto()
    dmm.set_integration(Solartron7151.INT_5X9_FILT_OFF)   # 5.5 digits, 400 ms
    dmm.set_track(True)                                   # continuous
    print(dmm.read_value())   # 2.798450
```

### HP (`rf_bench.hp`) ⚠️ UNTESTED

| Class | Instrument family | Tested with | Protocol |
|-------|------------------|-------------|---------|
| `HP8712B` | HP 8712B Vector Network Analyzer (300 kHz–1.3 GHz) | none yet — awaiting KISS-488 + HP 8712B | IEEE-488 / KISS-488 Ethernet-GPIB / TCP port 1234 |

### Utilities (`rf_bench.utils`)

`rf_utils` — pure-Python RF math library. Power conversions, impedance and
reflection math, noise figure, IP3, frequency formatting. No instruments,
no side effects; safe to import anywhere.

## Installation

Install everything at once (recommended):

```bash
pip install rf-bench
```

Or install only the sub-packages you need:

```bash
pip install rf-bench-drivers-siglent   # Siglent instruments
pip install rf-bench-drivers-icom      # Icom IC-7300
pip install rf-bench-drivers-yaesu     # Yaesu FT-891
pip install rf-bench-drivers-utils     # RF math utilities (no instruments)
pip install rf-bench-drivers-yertai    # Yertai ET5406A+ DC load
pip install rf-bench-drivers-gpsd      # gpsd GPS client
pip install rf-bench-drivers-koolertron  # MHinstek MHS-5200A series DDS gen + counter (KKmoon rebrand) — not on PyPI yet
```

**Dependency:** [NumPy](https://numpy.org/) (for `rf_bench.utils` and the
`SDS2000X` waveform decoder).

**For radio control:** [Hamlib](https://hamlib.github.io/) must be installed
and `rigctld` must be running before using `IC7300` or `FT891`.

```bash
# IC-7300  (CI-V baud set to 115200 in radio menu)
rigctld -m 3073 -r /dev/ttyUSB0 -s 115200 &

# FT-891  (CAT baud set to 38400 in Menu 031)
rigctld -m 1036 -r /dev/ttyUSB0 -s 38400 &
```

## Quick start

```python
from rf_bench import SDG1000X, IC7300, dbm_to_vpp, format_freq

# Function generator — two-tone test signal
with SDG1000X("10.1.1.61") as sdg:
    sdg.set_sine(1, freq_hz=14_001_000, level_dbm=-30)
    sdg.set_sine(2, freq_hz=14_001_500, level_dbm=-30)
    sdg.output_on(1)
    sdg.output_on(2)
    # ... run test ...

# IC-7300 S-meter reading
with IC7300() as rig:
    rig.set_frequency(14_200_000)
    rig.set_mode("usb")
    rig.set_agc("off")
    strength = rig.get_strength_settled(settle_s=0.5)
    print(f"Signal: {strength:.1f} STRENGTH units")

# RF math
dbm_to_vpp(-20)          # → 0.0632 Vpp  (P = Vpp²/8R, 50 Ω)
format_freq(14_200_000)  # → '14.2000 MHz'
```

Or import from subpackages:

```python
from rf_bench.siglent import SSA3000X, SDG1000X
from rf_bench.icom   import IC7300
from rf_bench.yaesu  import FT891, PREAMP_OFF, PREAMP_AMP1
from rf_bench.utils  import thermal_noise_floor, ip3_from_imd, rl_to_vswr
```

## Siglent drivers

### SSA3000X

*Tested with: Siglent SSA3032X Plus*

```python
from rf_bench.siglent import SSA3000X

with SSA3000X("10.1.1.60") as ssa:
    ssa.enable_tracking_generator(dbm=0)
    rbw = ssa.setup_band(14_000_000, 14_350_000, points=1001)
    ssa.single_sweep()           # blocks until sweep completes
    trace = ssa.get_trace()      # → np.ndarray of dBm values (length = points)
```

### SDG1000X

*Tested with: Siglent SDG1062X*

```python
from rf_bench.siglent import SDG1000X

with SDG1000X("10.1.1.61") as sdg:
    sdg.set_sine(1, freq_hz=14_001_000, level_dbm=-30)
    sdg.output_on(1)
    sdg.set_level(1, level_dbm=-40)   # change level only, preserve frequency
    info = sdg.query_channel(1)       # → {freq_hz, amp_vpp, amp_dbm, ...}
```

Amplitude range: ≈ −50 dBm (2 mVpp) to +24 dBm (10 Vpp) into 50 Ω.

### SDS2000X

*Tested with: Siglent SDS2504X Plus (firmware 5.4.x)*

```python
from rf_bench.siglent import SDS2000X

with SDS2000X("10.1.1.58") as scope:
    # Waveform capture (deep memory, auto V/div)
    voltages, sample_rate = scope.capture_audio(channel=1, duration_s=2.0)
    rms  = scope.measure_rms(channel=1)
    vpp  = scope.measure_vpp(channel=1)
    freq = scope.measure_freq(channel=1)
    vdiv = scope.autoscale_vdiv(channel=1)
```

#### Built-in AWG [Option — requires AWG license]

The SDS2000X Plus has a licensed 25 MHz single-channel AWG output on the
dedicated "Gen Out" BNC.

*Tested with: SDS2504X Plus (firmware 5.4.x) — AWG license confirmed present.*

```python
# Waveforms — each call configures and enables the output
scope.set_awg_sine(freq_hz=1000, amplitude_vpp=1.0)
scope.set_awg_sine(freq_hz=1000, amplitude_vpp=1.0, offset_v=0.5, phase_deg=90)

scope.set_awg_square(freq_hz=1000, amplitude_vpp=2.0)
scope.set_awg_square(freq_hz=1000, amplitude_vpp=2.0, duty_pct=30.0)

scope.set_awg_ramp(freq_hz=500, amplitude_vpp=1.5)             # sawtooth (100% symmetry)
scope.set_awg_ramp(freq_hz=500, amplitude_vpp=1.5, symmetry_pct=50.0)  # triangle

scope.set_awg_dc(offset_v=2.5)    # constant DC voltage

# Output control
scope.awg_output_on()
scope.awg_output_off()

# Query current state
state = scope.get_awg_state()
# → {'function': 'SINE', 'freq_hz': 1000.0, 'amplitude_vpp': 1.0,
#    'offset_v': 0.0, 'output_on': True}
```

Frequency range: 1 mHz – 25 MHz.  Amplitude: 2 mVpp – 6 Vpp into high
impedance (1 mVpp – 3 Vpp into 50 Ω).  Output impedance: 50 Ω.

#### MSO / Digital channels [Option — hardware not tested]

The SDS2000X Plus supports 16 digital channels (D0–D15) via an optional
MSO hardware probe pod.  Channels D0–D7 form pod 1; D8–D15 form pod 2;
thresholds are set per pod.

> **Note:** This code is implemented from the official Siglent EN11F
> programming guide but has **not been tested with physical MSO
> hardware** — the author does not currently have the digital probe pod.
> Feedback on correctness, especially the bit-packing format and custom
> threshold voltage syntax, is welcome.

```python
# Enable digital display and configure channels
scope.digital_enable()
scope.digital_channel_enable(0)              # turn on D0
scope.digital_channel_enable(5)              # turn on D5
scope.set_digital_threshold(1, "TTL")        # D0–D7: TTL (1.4 V)
scope.set_digital_threshold(2, "LVCMOS33")   # D8–D15: 3.3 V LVCMOS
scope.set_digital_threshold(1, 1.8)          # D0–D7: 1.8 V custom

scope.set_digital_label(0, "CLK")            # label D0 as "CLK"

# Capture digital waveform from current (frozen) acquisition
scope.stop()
samples, sr = scope.capture_digital(0)       # D0 → (bool array, sample_rate Hz)

sr_hz  = scope.get_digital_sample_rate()     # → e.g. 1.25e9
n_pts  = scope.get_digital_point_count()     # → e.g. 2500
print(scope.get_digital_threshold(1))        # → 'TTL'
print(scope.is_digital_channel_enabled(0))   # → True

scope.digital_disable()
```

Digital data returned by `capture_digital()` is a numpy `bool` array with one
element per sample (True = logic HIGH).  Internally the scope returns packed
bits (1 bit per sample, LSB of each byte = earliest sample); the driver
unpacks them automatically.

### SDM3000X

*Tested with: Siglent SDM3045X (4.5-digit)*
*Compatible with: SDM3045X, SDM3055 (5.5-digit), SDM3065X (6.5-digit)*

All measurement functions return SI units (V, A, Ω, Hz, F, °C).  MEAS commands
are one-shot; use `configure_*()` + `read_multiple()` for repeated measurements.

```python
from rf_bench.siglent import SDM3000X

with SDM3000X("10.1.1.63") as dmm:
    v = dmm.measure_vdc()                    # DC voltage, auto-range → V
    v = dmm.measure_vdc(range_v=20)          # DC voltage, 20 V range → V
    i = dmm.measure_idc()                    # DC current → A
    r = dmm.measure_resistance()             # 2-wire resistance → Ω
    r = dmm.measure_resistance(four_wire=True)   # 4-wire (Kelvin) → Ω
    f = dmm.measure_frequency()              # frequency → Hz
    dmm.measure_continuity()                 # resistance; beeps if < ~30 Ω
    dmm.measure_diode()                      # forward voltage → V

    # SDM3055 / SDM3065X only:
    c = dmm.measure_capacitance()            # → F
    t = dmm.measure_temperature()            # → °C (FRTD probe default)

    # Multi-sample: configure once, read many
    dmm.configure_vdc(range_v=5)
    samples = dmm.read_multiple(20)          # → [float, ...] 20 samples
```

### SPD3303X

*Tested with: Siglent SPD3303X-E (2× 0–32 V / 0–3.2 A + fixed CH3)*
*Compatible with: SPD3303C, SPD3303X, SPD3303X-E*

CH1 and CH2 are fully programmable CC/CV channels.  CH3 is a fixed-voltage output
(2.5 V, 3.3 V, or 5 V selected by front-panel switch); its voltage cannot be set
via SCPI but its output can be enabled/disabled and measured.

```python
from rf_bench.siglent import SPD3303X, TRACKING_INDEPENDENT, TRACKING_SERIES

with SPD3303X("10.1.1.64") as psu:
    # Basic CH1 setup
    psu.set_voltage(1, 5.0)          # 5 V setpoint
    psu.set_current(1, 0.5)          # 500 mA current limit
    psu.enable(1)

    v    = psu.measure_voltage(1)    # actual output voltage → V
    i    = psu.measure_current(1)    # actual output current → A
    p    = psu.measure_power(1)      # actual output power → W
    mode = psu.get_mode(1)           # 'CV' or 'CC'

    state = psu.measure_all(1)       # {'voltage_v', 'current_a', 'power_w'}

    # CH3 (fixed voltage — 2.5/3.3/5 V set by front-panel switch)
    psu.enable(3)
    psu.measure_voltage(3)           # reads actual CH3 output voltage

    psu.disable_all()

    # Series tracking: CH1+CH2 in series for up to 64 V
    psu.set_tracking(TRACKING_SERIES)
    psu.set_voltage(1, 24.0)         # CH2 mirrors CH1 automatically
    psu.enable(1)
    psu.enable(2)
    psu.get_status()   # → {'ch1_mode': 'CV', 'ch2_mode': 'CV', 'track_mode': 'SER'}
```

## Radio drivers

`IC7300` and `FT891` share an identical core interface and are drop-in
substitutable.

```python
from rf_bench.icom  import IC7300
from rf_bench.yaesu import FT891, PREAMP_OFF, PREAMP_AMP1

# Shared interface
for RigClass in (IC7300, FT891):
    with RigClass() as rig:
        rig.set_frequency(14_200_000)
        rig.set_mode("usb", passband_hz=2400)
        rig.set_agc("slow")
        rig.set_rf_gain(1.0)
        strength = rig.get_strength_settled()

# FT-891 additions: preamp / attenuator
with FT891() as rig:
    rig.set_preamp(PREAMP_OFF)   # IPO — bypass preamp for large-signal tests
    rig.set_preamp(PREAMP_AMP1)  # AMP1 — ~10 dB gain for sensitivity tests
    rig.set_att(6)               # 0, 6, or 12 dB front-end attenuation
```

**AGC note:** `set_agc("off")` is a true hardware bypass on the IC-7300.
On the FT-891 it maps to the slowest AGC constant — not a true bypass.

If both radios are in use simultaneously, run each rigctld on a separate port:

```bash
rigctld -m 3073 -r /dev/ttyUSB0 -s 115200 -T localhost -t 4532 &
rigctld -m 1036 -r /dev/ttyUSB1 -s 38400  -T localhost -t 4533 &
```

```python
ic  = IC7300("localhost", 4532)
ft  = FT891("localhost", 4533)
```

## RF utilities

`rf_bench.utils` is a pure-Python RF math library. No instruments, no side effects;
safe to import anywhere.

```python
from rf_bench.utils import (
    # Constants
    SPEED_OF_LIGHT,                  # 299 792 458 m/s (exact)
    S9_HF_DBM, S9_VHF_DBM,          # −73 / −93 dBm (ITU S-meter references)

    # Power / voltage (50 Ω default; pass impedance= to override)
    dbm_to_vpp, vpp_to_dbm,         # dBm ↔ Vpp  (sine: P = Vpp²/8R; 0 dBm → 0.6325 Vpp)
    dbm_to_vrms, vrms_to_dbm,       # dBm ↔ Vrms
    dbm_to_watts, watts_to_dbm,     # dBm ↔ Watts
    dbm_to_uv, uv_to_dbm,           # dBm ↔ µVrms

    # Power ratio / extended dB units
    db_to_linear, linear_to_db,     # power ratio ↔ dB
    db_to_voltage_ratio,            # voltage ratio from dB (10^(dB/20))
    voltage_ratio_to_db,            # dB from voltage ratio (20·log10)
    dbm_to_dbw, dbw_to_dbm,         # dBm ↔ dBW
    dbm_to_dbuv, dbuv_to_dbm,       # dBm ↔ dBµV (0 dBm at 50 Ω = 106.99 dBµV)

    # Impedance / reflection
    rl_to_vswr, vswr_to_rl,         # return loss ↔ VSWR
    gamma_to_vswr, vswr_to_gamma,   # reflection coeff ↔ VSWR
    rl_to_gamma, gamma_to_rl,
    rl_to_vswr_v, vswr_to_rl_v,     # vectorized (numpy array) versions
    gamma_to_vswr_v,

    # Noise and dynamic range
    thermal_noise_floor,             # kTB in dBm (exact Boltzmann constant)
    noise_figure_from_mds,           # NF from measured MDS and bandwidth
    mds_from_noise_figure,           # MDS from NF and bandwidth
    ip3_from_imd,                    # OIP3 or IIP3 from two-tone IMD levels
    ip3_to_dynamic_range,            # SFDR = (2/3)(IP3 − noise floor)
    cascaded_noise_figure,           # Friis formula for cascade of (gain_db, nf_db) stages
    noise_temp_to_nf,                # noise temperature (K) → NF (dB)
    nf_to_noise_temp,                # NF (dB) → noise temperature (K)

    # Propagation / antenna
    wavelength, quarter_wave,        # λ, λ/4 in metres; optional velocity_factor
    half_wave,                       # λ/2 in metres
    freespace_path_loss,             # FSPL = 20·log10(4πdf/c) in dB

    # Passive components
    capacitive_reactance,            # Xc = 1/(2πfC) Ω
    inductive_reactance,             # Xl = 2πfL Ω
    lc_resonant_freq,                # f = 1/(2π√(LC)) Hz
    l_from_resonant, c_from_resonant,# compute L or C from resonant frequency
    q_factor, bw_from_q,             # Q = f0/BW ↔ BW = f0/Q
    parallel_resistance,             # 1/Σ(1/Rᵢ) — 2 or more values
    voltage_divider,                 # Vout = Vin · R2 / (R1+R2)
    skin_depth,                      # δ in metres (copper default: 5.8×10⁷ S/m)

    # Attenuator design
    pi_attenuator,                   # π-pad: {'r_shunt': Ω, 'r_series': Ω}
    t_attenuator,                    # T-pad:  {'r_series': Ω, 'r_shunt': Ω}

    # IM products
    intermod_products,               # two-tone near-carrier IM products, odd orders

    # S-meter
    s_unit_to_dbm, dbm_to_s_unit,   # ITU S-unit ↔ dBm (HF default; vhf=True for VHF)

    # Formatting
    format_freq,                     # 14200000 → '14.2000 MHz'; also GHz and Hz
    format_freq_short,               # 14200000 → '14.2 MHz' (trailing zeros trimmed)
    nearest_rbw,                     # nearest Siglent RBW step
    nearest_value,                   # nearest value in any list (E-series, RBW, etc.)

    # Standard value series
    SIGLENT_RBW_SERIES,
    E12_SERIES, E24_SERIES, E48_SERIES, E96_SERIES,
)
```

## Default instrument addresses

| Driver class | Tested instrument | Default IP / address | Port | Notes |
|-------------|------------------|---------------------|------|-------|
| `SSA3000X` | SSA3032X Plus | 10.1.1.60 | 5025 | LAN/SCPI |
| `SDG1000X` | SDG1062X | 10.1.1.55 | 5025 | LAN/SCPI |
| `SDS2000X` | SDS2504X Plus | 10.1.1.58 | 5025 | LAN/SCPI |
| `SDM3000X` | SDM3045X | 10.1.1.63 | 5025 | LAN/SCPI |
| `SPD3303X` | SPD3303X-E | 10.1.1.56 | 5025 | LAN/SCPI |
| `IC7300` | IC-7300 | localhost | 4532 | `rigctld -m 3073 -r /dev/ttyUSB0 -s 115200` |
| `FT891` | FT-891 | localhost | 4532 | `rigctld -m 1036 -r /dev/ttyUSB0 -s 38400` |
| `MHS5200A` | MHS-5225A (KKmoon rebrand) | `/dev/ttyUSB0` (auto-detect CH340/PL2303) | n/a | 57600 8N1 USB CDC; auto-detected by USB VID/PID |

All drivers accept `host` and `port` constructor arguments to override defaults.

## Firmware bugs and quirks

Known instrument firmware issues discovered during live testing. Workarounds are
implemented in the drivers; this section explains the underlying behaviour for
reference when working on driver code or upgrading firmware.

### SDS2000X Plus — firmware 5.4.0.1.6.2R5

**Bug 1: `:WAVeform:DATA?` intermittently returns display-buffer data instead of deep memory**

`:WAVeform:POINt MAX` followed by `:WAVeform:DATA?` occasionally returns 1 000
samples at 2 GSps (the 1 000-point display buffer) instead of full acquisition
memory (10 M samples at 20 MHz for a 1 s capture).  The bug is
**state-dependent** — it is not tied to any specific VDIV or TDIV value.
It appears more frequently when the scope's ADC configuration has been recently
changed (e.g., by an autorange probe at a different VDIV).

*Workaround:* `capture_audio()` detects the display-buffer condition
(`len ≤ 1000` and `sample_rate > 500 MHz`) and retries once; the second
attempt almost always succeeds because re-arming the trigger clears the state.

**Bug 2: ADC not reconfigured after VDIV change — INVESTIGATED, NOT REPRODUCED**

Initially suspected: after `C1:VDIV` changes the vertical scale, WAVEDESC would
report the new (correct) vgain while the ADC data remained scaled for the old
VDIV — a "phantom vgain."  Live debug output disproved this: on attempt 1 of a
deep-memory capture, WAVEDESC-reported vgain matched the ADC data correctly, and
the 99th-percentile amplitude matched the expected signal level.  The inflated
amplitude seen in earlier testing was caused by `numpy.max()` picking up isolated
noise spikes, not a firmware miscalibration.

*Status:* No driver workaround is needed or present.  Retained here to document
the investigation in case the symptom reappears on a different firmware version.

**Bug 3: Stale bytes in socket after binary block read cause PAVA pipeline shift**

After `_read_binary_block()` reads a waveform or preamble block, the scope
appends a trailing `\n` that arrives slightly after the binary payload.  Without
an explicit drain, this byte sits in the TCP receive buffer.  The next
`_query()` call reads the stale byte and returns empty; all subsequent PAVA
queries are shifted by one response (each call returns the previous call's
data).  Symptom: `measure_rms()` returns NaN and subsequent calls return each
other's values.

*Workaround:* `_read_binary_block()` drains all trailing bytes with a 50 ms
timeout after each binary read.  `measure_rms/vpp/freq()` additionally call
`_drain()` before each PAVA query.

**Bug 4: PAVA returns a silent incorrect value when V/div is poorly matched to the signal**

At large V/div (e.g., 2 V/div for a signal only a few mV peak), the signal
occupies only ±1–3 ADC counts.  PAVA returns a near-zero Vpp rather than an
error, with no indication that the measurement is unreliable.  If autorange
naively trusts this small reading it selects a far-too-fine V/div, the ADC
clips the actual signal, and the error compounds.

*Workaround:* `_autorange_vdiv()` captures a short waveform at 0.1 V/div and
computes the 99th-percentile peak directly from the ADC counts, bypassing PAVA
entirely for autorange decisions.

**Behavior note: `:WAVeform:POINt MAX` must be sent before every data read**

Without it, the scope returns the 1 000-point display-decimated trace regardless
of acquisition memory depth.  This is consistent with general SCPI oscilloscope
behavior (default is display resolution, not deep memory) but can surprise users
who expect a long-timebase capture to return deep-memory data automatically.

*Practice:* always issued in `capture_audio()`.

**Bug 6: TDIV/VDIV changes must be made while scope is stopped**

Changing TDIV or VDIV while the scope is running produces a corrupt acquisition
(may return 5 bytes, all +127).

*Workaround:* `capture_audio()` always issues `:STOP` before reconfiguring.

**Bug 7: PAVA requires a fresh, complete sweep before it returns valid data**

After `:STOP`, calling `:RUN` and querying PAVA immediately returns NaN or
wrong values.  PAVA needs at least one full sweep to complete.

*Workaround:* `measure_rms/vpp/freq()` set a short TDIV (2 ms/div = 20 ms
window) before running, so the sweep finishes well within the 0.5 s sleep.

**Bug 8: Changing TDIV while stopped silently corrupts the VDIV register**

When `measure_rms/vpp/freq()` are called after `capture_audio()`, the
`_pava_setup()` helper issues `:STOP`, changes `TDIV` to 2 ms, then runs.
Even though the scope is stopped at the time of the TDIV change (workaround
for Bug 6), the firmware silently resets the VDIV register to an undefined
value.  The acquisition runs at the new TDIV but with a wrong VDIV, causing
PAVA FREQ to return wildly incorrect values (e.g. 45200 Hz, 99500 Hz) while
PAVA RMS and PKPK appear plausible but are off by the VDIV ratio.

*Workaround:* `_pava_setup()` now explicitly re-applies `C{n}:VDIV` after
every TDIV change, using the VDIV that was last set by `capture_audio()` for
that channel (tracked in `self._last_capture_vdiv`), or 0.5 V/div if no
prior capture has been done.

**Bug 9: Built-in AWG ("Gen Out") uses SDG-style `C1:` commands, NOT documented `WGEN`**

The Siglent programming guide documents the AWG using a `WGEN`/`WAVEGENERATOR`
flat-keyword command family. On firmware 5.4.0.1.6.2R5 these commands ALL
return SCPI error -113 "Undefined header". The actual accepted command set is
the SDG-style `C1:BSWV` / `C1:OUTP` / `C1:ARWV` family — the same syntax used
by Siglent's standalone SDG signal generators. The AWG's "C1" command
namespace is disjoint from the analog-input C1 commands (e.g. `C1:CPL`,
`C1:VDIV`); the second token disambiguates.

The discrepancy is between the published programming guide (which describes
the older non-Plus SDS2000X) and the SDS2000X+ firmware. The Plus firmware
re-uses the SDG generator command set rather than introducing a new WGEN
namespace, but the docs were never updated.

*Symptom of the bad commands:* `set_awg_*` commands appear to succeed (no
exception, scope returns no error to the user) but no actual change occurs;
queries via `get_awg_state()` time out with empty responses.

*Workaround:* the driver was rewritten to use `C1:BSWV WVTP,SINE,FRQ,...HZ,...`
for set and `C1:BSWV?` / `C1:OUTP?` for query. Verified on the SDS2504X Plus
(2026-06-08) — all six AWG methods (sine, square, ramp, DC, output on/off,
state query) round-trip correctly.

### SSA3000X Plus — firmware 3.2.2.6.3R2

**Quirk: `:SENS:SWE:POIN` command silently ignored — trace length fixed at 751**

The `setup_band()` method sends `:SENS:SWE:POIN {n}` to request a specific
number of sweep points, but firmware 3.2.x on the SSA3032X Plus ignores the
command.  The instrument always returns traces with exactly 751 points,
regardless of what was requested.  This makes the RBW calculation in
`setup_band()` incorrect if it uses the requested point count instead of the
actual count.

*Workaround:* `setup_band()` calls `get_sweep_points()` to read the actual
point count before computing the RBW, ensuring the RBW matches what the
firmware will use.  The `:SENS:SWE:POIN` command is still sent (it may work
on other firmware versions) but the actual count is read back and used.

**Bug: FM demodulation measurement commands not implemented**

The SSA3032X Plus has an on-screen FM demodulation display mode, but the
corresponding SCPI commands are entirely absent from firmware 3.2.2.6.3R2.
All of the following return `-113,"Undefined header"`:

- `:CALC:DMOD:FM?` / `:CALC:DMOD:FM ON`
- `:CALC:MARK1:FUNC:DMOD:TYPE FM`
- `:MEAS:FM?`, `:MEAS:FDEV?`, `:MEAS:ADEM:FM?`
- `:DMOD:FM?`, `:CALC:DEMOD:FM?`

There is no SCPI path to read FM deviation from this firmware, regardless of
which command syntax is tried.

*Workaround:* `projects/radio/fm-deviation/fm_deviation.py` uses Carson's rule
applied to the spectrum trace: the −26 dB bandwidth of an FM signal equals
2(Δf + fa), so deviation Δf = BW₋₂₆/2 − fa.  The SSA captures the trace via
the standard `:TRAC:DATA?` path (which does work), and Python computes the
bandwidth by finding the −26 dB crossings around the carrier peak.

### SDG1062X — firmware 1.01.01.33R3

**Bug: BSWV response appends unit suffixes to all numeric values**

Querying `C1:BSWV?` returns fields like `FRQ,1000HZ`, `AMP,0.2V`,
`AMPDBM,-10.0dBm`, `OFST,0.0V`.  The `float()` built-in raises `ValueError`
on these strings, silently returning 0 for all channel parameters.

*Workaround:* `_strip_unit()` in `SDG1000X` strips the unit suffix via regex
before parsing.

### SPD3303X-E — firmware (all versions tested)

**Quirk: `OUTP?` does not respond reliably**

`:OUTP? CH1` sometimes returns an empty response.

*Workaround:* `is_enabled()` uses the `SYST:STAT?` status register bitmask
(bits 4–6 = CH1/CH2/CH3 output enable) instead.

## License

GPL-3.0-or-later — see [LICENSE](LICENSE).

---

## Bench Automation Projects

The following projects use the `rf-bench` drivers to automate specific
measurement tasks. Each is a standalone CLI script in its own GitHub repo.

A collection of Python CLI tools for automated RF and electronics bench measurements using
Siglent test equipment. All tools talk to instruments over raw TCP/SCPI (no pyvisa required)
and to radios via Hamlib rigctld.

## Instrument Inventory

| Instrument | Model | IP Address | Role |
|------------|-------|-----------|------|
| Spectrum analyzer | Siglent SSA3032X Plus | 10.1.1.60 | Frequency-domain measurements, tracking generator source |
| Oscilloscope | Siglent SDS2504X Plus | 10.1.1.58 | Time-domain waveform capture, audio FFT, built-in 25 MHz AWG |
| Function generator | Siglent SDG1062X | 10.1.1.55 | Signal source up to 60 MHz, two channels |
| Bench multimeter | Siglent SDM3045X | 10.1.1.63 | DC voltage/current measurement |
| DC power supply | Siglent SPD3303X-E | 10.1.1.56 | Programmable CC-CV supply, two channels |
| DC load | Yertai ET5406A+ | USB serial | Programmable CC discharge load, 200 W |
| GPS | gpsd daemon | TCP localhost:2947 | Position, speed, altitude, heading, DOP |
| Reflection bridge | Siglent RB3X25 | — | Passive bridge for VSWR/impedance measurements |
| Radio (HF) | Icom IC-7300 | USB-B → rigctld | HF transceiver for receiver testing |
| Radio (HF) | Yaesu FT-891 | USB-B → rigctld | HF transceiver for receiver testing |

## Driver Packages

Instrument drivers are distributed as separate PyPI packages:

| Package | Provides |
|---------|---------|
| `rf-bench-drivers-siglent` | SSA3000X, SDG1000X, SDS2000X, SDM3000X, SPD3303X |
| `rf-bench-drivers-icom` | IC7300 (CAT via rigctld) |
| `rf-bench-drivers-yaesu` | FT891 (CAT via rigctld) |
| `rf-bench-drivers-utils` | RF math: power conversions, noise, IP3, impedance, formatting |
| `rf-bench-drivers-buspirate` | BusPirate SPI/I2C/UART master (v3/v4/v5) |
| `rf-bench-drivers-yertai` | Yertai ET5406A+ DC load — CC/CV/CP/CR/BATT/TRAN modes |
| `rf-bench-drivers-rtlsdr` | RTLSDR receiver — IQ capture, streaming, PPM calibration |
| `rf-bench-drivers-gpsd` | gpsd GPS client — position, speed, altitude, heading, DOP; metric + imperial |
| `rf-bench-drivers-koolertron` | MHinstek MHS-5200A series dual-channel DDS gen + counter + sweep (covers KKmoon and other rebrands; tested 2026-06-08 against MHS-5225A) |

---

## Projects

---

### GPS projects (`projects/gps/`)

Requires `rf-bench-drivers-gpsd` and a running `gpsd` daemon.

| Script | Purpose |
|--------|---------|
| `gps/survey/survey.py` | Static position precision survey — mean lat/lon, N/E/2D scatter in metres |
| `gps/gridsquare/gridsquare.py` | Live Maidenhead locator (4/6/8 chars) with optional waypoint distance/bearing |
| `gps/monitor/monitor.py` | Fullscreen GPS quality display — DOP bars, scatter plot, speed, heading |
| `gps/freq-cal/freq_cal.py` | GPS-timestamped frequency drift measurement using SSA3032X |

### GPS-integrated RTL-SDR projects (`projects/rtlsdr/`)

| Script | GPS required | Purpose |
|--------|-------------|---------|
| `rtlsdr/survey/survey.py` | Optional (`--gps`) | Power spectrum capture at regular intervals, geo-tagged CSV |
| `rtlsdr/drivetest/drivetest.py` | Optional (`--gps`) | Single-frequency power logging with GPX track output |
| `rtlsdr/recorder/recorder.py` | Optional (`--gps`) | SigMF IQ recorder — adds `core:geolocation` to metadata |

### GPS-integrated radio projects (`projects/radio/`)

| Script | Radios | GPS required | Purpose |
|--------|--------|-------------|---------|
| `radio/coverage/coverage.py` | IC-7300, IC-9700, FT-891 | Optional (`--gps`) | S-meter vs GPS position; CSV + GPX coverage map |
| `radio/doppler/doppler.py` | IC-7300, IC-9700, FT-891 | Required | Real-time Doppler VFO correction from GPS velocity |

---

### rf-bench-antenna-analyzer

**GitHub:** https://github.com/jfrancis42/rf-bench-antenna-analyzer

**Purpose:** Sweeps antenna VSWR and return loss across any combination of amateur HF/VHF/UHF
bands (160 m through 2.4 GHz), CB, aviation VHF, marine VHF/HF, FRS/GMRS, and MURS. Generates
a calibrated VSWR plot and text report. Calibration is by open-circuit reference — no Siglent
REFL firmware license is required.

**Features:** Adaptive RBW, multi-sweep averaging, live watch/retune mode, automatic precision
narrowing sweep around resonance, comparison overlay of two runs, history log.

**Test equipment:**
- Siglent SSA3032X Plus (spectrum analyzer with tracking generator)
- Siglent RB3X25 reflection bridge

**Fixtures and cabling:**
```
SSA [Gen Out] ──BNC──→ RB3X25 [TG In]
                               │
                        RB3X25 [RF Out] ──BNC──→ SSA [RF In]
                               │
                        RB3X25 [DUT Port]
                               │
                           Antenna
```
Connect the bridge's DUT port to a short BNC-to-SO239 adapter (or BNC-to-SMA) for the
antenna under test. Keep all cables short to minimize port impedance errors.

---

### rf-bench-balun-analyzer

**GitHub:** https://github.com/jfrancis42/rf-bench-balun-analyzer

**Purpose:** Measures choking impedance (|Z| in ohms) versus frequency for baluns, current
chokes, and common-mode chokes. Drives the same reflection bridge hardware as the antenna
analyzer but treats the DUT port as a one-port impedance load rather than an antenna.
Plots |Z| on a log scale and annotates the −3 dB roll-off frequency.

**Test equipment:**
- Siglent SSA3032X Plus (tracking generator required)
- Siglent RB3X25 reflection bridge

**Fixtures and cabling:**
```
SSA [Gen Out] ──BNC──→ RB3X25 [TG In]
                               │
                        RB3X25 [RF Out] ──BNC──→ SSA [RF In]
                               │
                        RB3X25 [DUT Port]
                               │
                      Balun / choke under test
                        (far end open-circuit)
```
The choke is measured as a one-port: connect one winding to the DUT port, leave the far
end open. Calibrate with the DUT port open before connecting the balun.

---

### rf-bench-battery-tester

**GitHub:** https://github.com/jfrancis42/rf-bench-battery-tester

**Purpose:** Measures battery capacity (mAh), internal resistance (mΩ via DC pulse method),
and supports multi-cycle charge/discharge testing to track capacity fade over time. Plots
voltage vs. time during discharge and capacity vs. cycle number for multi-cycle runs.

**Test equipment:**
- Yertai ET5406A+ programmable DC load (discharge)
- Siglent SDM3045X bench multimeter (voltage measurement)
- Siglent SPD3303X-E programmable supply (charge, cycle mode only)

**Note:** Uses `rf_bench.yertai.ET5406A` driver (pure pyserial, no pyvisa). The load has
been bench-tested on a Yertai ET5406A+ via CH340 USB adapter.

**Fixtures and cabling (capacity / internal resistance):**
```
Battery (+) ──── ET5406A+ [V+] ──── SDM [Sense Hi]
Battery (−) ──── ET5406A+ [V−] ──── SDM [Sense Lo]
```
Use separate Kelvin sense leads from the battery terminals to the DMM to eliminate
lead resistance from the voltage measurement.

**Fixtures and cabling (cycle mode, charge + discharge):**
```
SPD CH1 (+) ──[Schottky diode, e.g. 1N5819]──┐
                                               ├── Battery (+) ──── ET5406A+ [V+]
                                               │
SPD CH1 (−) ───────────────────────────────────┴── Battery (−) ──── ET5406A+ [V−]
```
The diode prevents the load from back-driving the supply during discharge. A 1N5819
(~0.3 V Vf) is appropriate for most Li-ion voltages. Do not connect SPD directly in
parallel with the ET54 load without isolation.

---

### rf-bench-bode-plotter

**GitHub:** https://github.com/jfrancis42/rf-bench-bode-plotter

**Purpose:** Generates a Bode plot — gain (dB) and phase (degrees) versus log frequency —
for any linear DUT: audio filters, op-amp circuits, speaker crossovers, RF filters up to
60 MHz. Supports the scope's built-in 25 MHz AWG (phase-coherent, no extra cable) or the
SDG1062X for sweeps above 25 MHz. Automatically finds and annotates the −3 dB frequency.

**Test equipment:**
- Siglent SDS2504X Plus oscilloscope (required; built-in AWG used by default)
- Siglent SDG1062X function generator (optional; required for sweeps above 25 MHz)

**Fixtures and cabling (scope AWG source):**
```
Scope [Gen Out] ──BNC-T──┬──→ Scope CH1 (reference)
                          └──→ DUT input
                                   │
                               DUT output ──→ Scope CH2
```

**Fixtures and cabling (SDG source):**
```
SDG CH1 ──BNC-T──┬──→ Scope CH1 (reference)
                  └──→ DUT input
                             │
                         DUT output ──→ Scope CH2
```
Use 50 Ω termination on the scope inputs when driving RF filters. For high-impedance
audio circuits, switch scope inputs to 1 MΩ coupling.

---

### rf-bench-calibration

**GitHub:** https://github.com/jfrancis42/rf-bench-calibration

**Purpose:** Cross-instrument amplitude calibration. The SDG1062X generates a reference
sine wave at each frequency point; the oscilloscope, spectrum analyzer, and DMM all measure
it simultaneously. Builds per-instrument amplitude correction tables and plots frequency
flatness. This is relative calibration only — it does not establish traceability to an
absolute standard.

**Test equipment:**
- Siglent SDG1062X (reference signal source)
- Siglent SDS2504X Plus oscilloscope
- Siglent SSA3032X Plus spectrum analyzer
- Siglent SDM3045X bench multimeter

**Fixtures and cabling:**
```
SDG CH1 ──BNC-T──┬──→ Scope CH1
                  ├──→ SSA [RF In]
                  └──→ SDM [Volts Hi]    (SDM [Volts Lo] → GND)
```
All instruments measure the same point simultaneously. Use a 4-way BNC splitter or daisy-chain
BNC-T connectors. Keep total cable length short to minimize frequency-dependent insertion loss
in the splitter.

---

### rf-bench-clock-jitter

**GitHub:** https://github.com/jfrancis42/rf-bench-clock-jitter

**Purpose:** Clock jitter measurement and PLL lock-time capture using the oscilloscope's MSO
digital input channels. Jitter mode: captures many edges, builds a histogram, computes RMS
and peak-to-peak jitter. PLL mode: measures write-strobe-to-lock-detect timing after a
frequency hop.

**Test equipment:**
- Siglent SDS2504X Plus oscilloscope with MSO option (digital probe pod required)

**Note:** The MSO digital probe pod option has not been physically tested with this software.
The SCPI commands are implemented from the SDS2000X Plus programming guide. If you
encounter command errors, check the MSO channel naming in the driver against your
firmware version.

**Fixtures and cabling:**
```
MSO probe pod D0 ──→ clock signal under test
MSO probe pod GND ──→ circuit ground reference
Scope CH1 (analog) ──→ same clock signal (optional, for analog reference)
```
The MSO probe pod attaches to the scope's MSO pod connector (right side of instrument).
Use the shortest possible ground leads on the pod to minimize ringing.

---

### rf-bench-crystal-extractor

**GitHub:** https://github.com/jfrancis42/rf-bench-crystal-extractor

**Purpose:** Measures the Butterworth-Van Dyke (BVD) equivalent circuit parameters of quartz
crystals: series resistance Rs (Ω), series inductance Ls (H), series capacitance Cs (F), and
parallel package capacitance Cp (F). Sweeps through resonance, captures the complex impedance
response, and fits the BVD model. Batch mode sorts a bin of crystals by resonant frequency.

**Test equipment:**
- Siglent SDS2504X Plus oscilloscope (with built-in AWG, preferred for HF crystals)
- Siglent SDG1062X function generator (optional; for crystals above 25 MHz)

**Fixtures and cabling:**
```
Scope AWG [Gen Out] ──→ 50 Ω series resistor (reference) ──→ Crystal ──→ GND
                                │                                  │
                            Scope CH1                          Scope CH2
                          (before resistor)                  (after crystal)
```
The series resistor forms a voltage divider with the crystal impedance. CH1 measures the
source voltage; CH2 measures the voltage across the crystal. Complex impedance is derived
from the ratio CH2/CH1 and the reference resistor value.

---

### rf-bench-emi-finder

**GitHub:** https://github.com/jfrancis42/rf-bench-emi-finder

**Purpose:** Identifies EMI sources by correlating spectrum analyzer peaks with digital
clock frequencies. The SSA sweeps for emission peaks; the MSO captures waveforms on
suspected clock signals; harmonic correlation determines which clock is responsible for
each peak.

**Test equipment:**
- Siglent SSA3032X Plus spectrum analyzer
- Siglent SDS2504X Plus oscilloscope with MSO option (digital probe pod required)

**Note:** The MSO digital probe pod option has not been physically tested with this software.
The SCPI commands are implemented from the SDS2000X Plus programming guide.

**Fixtures and cabling:**
```
SSA [RF In] ──→ near-field H/E probe (e.g. home-made loop or purchased EMC probe set)
                 (positioned over PCB area under investigation)

MSO probe pod D0–D3 ──→ suspected clock / data lines on DUT PCB
MSO probe pod GND ──→ PCB ground plane
```
A simple near-field probe can be wound from a few turns of coax with the shield cut at
one end. Keep the SSA input attenuator at ≥10 dB when probing near high-power switching
nodes to protect the input mixer.

---

### rf-bench-iv-tracer

**GitHub:** https://github.com/jfrancis42/rf-bench-iv-tracer

**Purpose:** Plots I-V curves for passive and active devices: diodes (forward/reverse),
Zener diodes (breakdown region), LEDs (turn-on knee), NPN/PNP BJTs (collector family),
and N/P-channel MOSFETs (drain family). The SPD3303X sweeps device voltage while the
SDM3045X measures current.

**Test equipment:**
- Siglent SPD3303X-E programmable power supply
- Siglent SDM3045X bench multimeter

**Fixtures and cabling (diode/Zener):**
```
SPD CH1 (+) ──→ Device anode
SPD CH1 (−) ──→ SDM [Sense Lo] ──→ Device cathode ──→ GND
SDM [Sense Hi] ──→ SPD CH1 (+)
```
The DMM is wired in 4-wire mode to measure voltage directly across the device terminals.
Current is computed from SPD voltage / series resistance or read from SPD current display.

**Fixtures and cabling (BJT family of curves):**
```
SPD CH1 ──→ Collector (via ~100 Ω limit resistor)
SPD CH2 ──→ Base (via base resistor for Ib step)
Emitter ──→ GND
SDM ──→ across collector-emitter
```

---

### rf-bench-mixer-characterizer

**GitHub:** https://github.com/jfrancis42/rf-bench-mixer-characterizer

**Purpose:** Characterizes RF mixers: conversion loss versus RF frequency, LO-to-RF and
LO-to-IF port isolation, spurious IF products, and 1 dB compression point. Automates the
full measurement sweep across a user-specified RF range.

**Test equipment:**
- Siglent SDG1062X function generator (two channels — LO and RF)
- Siglent SSA3032X Plus spectrum analyzer (IF measurement)

**Fixtures and cabling:**
```
SDG CH1 ──→ Mixer [LO port]    (LO level per mixer datasheet, typically +7 to +17 dBm)
SDG CH2 ──→ 6 dB pad ──→ Mixer [RF port]
                Mixer [IF port] ──→ SSA [RF In]
```
Add a 6 dB pad between SDG CH2 and the mixer RF port to improve source impedance. The
IF port typically needs a low-pass filter before the SSA if wideband spurious rejection is
important. Check mixer datasheet for maximum LO drive level before connecting.

---

### rf-bench-power-integrity

**GitHub:** https://github.com/jfrancis42/rf-bench-power-integrity

**Purpose:** Mixed-signal power integrity analyzer. Captures MSO digital channels and an
analog supply voltage rail on a shared timebase. Correlates digital switching activity
(edges, bus transactions) with supply voltage glitches to identify power integrity problems.

**Test equipment:**
- Siglent SDS2504X Plus oscilloscope with MSO option (digital probe pod required)

**Note:** The MSO digital probe pod option has not been physically tested with this software.
The SCPI commands are implemented from the SDS2000X Plus programming guide.

**Fixtures and cabling:**
```
Scope CH1 ──→ Power supply rail under test (use a ×1 passive probe)
MSO probe pod D0–D7 ──→ data/address/control bus signals on DUT
MSO probe pod GND ──→ DUT ground plane (multiple GND connections recommended)
```
Use the scope's 1 MΩ input with a ×1 probe on the power rail to avoid loading it. Keep
the analog probe ground lead as short as possible to avoid aliasing high-frequency glitches.

---

### rf-bench-protocol-analyzer

**GitHub:** https://github.com/jfrancis42/rf-bench-protocol-analyzer

**Purpose:** SPI, I2C, and UART protocol decoder using the oscilloscope's MSO digital input
channels. Captures bit streams, decodes transactions in Python, displays timing diagrams and
annotated transaction logs. Useful for debugging embedded firmware without a dedicated logic
analyzer.

**Test equipment:**
- Siglent SDS2504X Plus oscilloscope with MSO option (digital probe pod required)

**Note:** The MSO digital probe pod option has not been physically tested with this software.
The SCPI commands are implemented from the SDS2000X Plus programming guide.

**Fixtures and cabling (SPI):**
```
MSO D0 ──→ CS (chip select)
MSO D1 ──→ MOSI
MSO D2 ──→ MISO
MSO D3 ──→ SCK (clock)
MSO GND ──→ circuit ground
```

**Fixtures and cabling (I2C):**
```
MSO D0 ──→ SDA
MSO D1 ──→ SCL
MSO GND ──→ circuit ground
```

**Fixtures and cabling (UART):**
```
MSO D0 ──→ TX
MSO D1 ──→ RX  (optional)
MSO GND ──→ circuit ground
```

---

### rf-bench-psrr

**GitHub:** https://github.com/jfrancis42/rf-bench-psrr

**Purpose:** Measures Power Supply Rejection Ratio (PSRR) as a function of frequency for
linear voltage regulators, LDOs, and switching supply post-filters. The scope AWG injects
a swept AC ripple signal onto the regulator input via a coupling capacitor and series
inductor; CH1 and CH2 measure the input and output ripple respectively.
PSRR(f) = 20 · log₁₀(Vin_ripple / Vout_ripple) dB.

**Test equipment:**
- Siglent SDS2504X Plus oscilloscope (built-in AWG used as injection source)

**Custom fixture — AC injection circuit (~$5 in parts):**
```
Scope [Gen Out] ──→ 10 µF (film cap, ≥25 V) ──→ 10 µH inductor ──→ Regulator [Vin]
                                                                             │
                                                                        Scope CH1
                                                                     (input ripple)

Regulator [Vout] ──→ Scope CH2 (output ripple)
Regulator [GND] ──→ Scope GND
```
The capacitor blocks the AWG output DC and the inductor limits the AWG current while
passing AC. Values are not critical; a 100 nF cap and 100 µH inductor also work for audio
frequencies. Increase injection amplitude if output ripple is below the scope noise floor.

---

### rf-bench-psu-characterizer

**GitHub:** https://github.com/jfrancis42/rf-bench-psu-characterizer

**Purpose:** Complete power supply and voltage regulator test suite: load regulation
(Vout vs. Iload), line regulation (Vout vs. Vin), efficiency vs. load, output ripple and
noise, and load transient response. Results are saved as plots and a JSON data file.

**Test equipment:**
- Siglent SPD3303X-E programmable supply (input/reference supply)
- Yertai ET5406A+ programmable DC load (load sweep; required for load regulation and efficiency)
- Siglent SDM3045X bench multimeter (output voltage measurement)
- Siglent SDS2504X Plus oscilloscope (ripple and transient capture)

**Note:** Uses `rf_bench.yertai.ET5406A` driver (pure pyserial, no pyvisa). Load-sweep tests
require the ET5406A+ and will report an error and exit if the device is not reachable.

**Fixtures and cabling:**
```
[PSU / DUT] (+) output ──┬──→ ET5406A+ [V+]   (load)
                          ├──→ SDM [Sense Hi]  (Kelvin voltage)
                          └──→ Scope CH1       (ripple; use ×1 AC-coupled probe)

[PSU / DUT] (−) output ──┬──→ ET5406A+ [V−]
                          ├──→ SDM [Sense Lo]
                          └──→ Scope GND
```
Use Kelvin (4-wire) sense leads from the DUT output terminals to the DMM for accurate
load regulation measurements. The scope measures ripple AC-coupled at the output terminals.

---

### rf-bench-receiver-test

**GitHub:** https://github.com/jfrancis42/rf-bench-receiver-test

**Purpose:** Automated HF receiver test suite for the Icom IC-7300 and Yaesu FT-891.
Measures minimum discernible signal (MDS) and noise figure, S-meter calibration, two-tone
IMD and input-referred third-order intercept (IIP3), blocking dynamic range, and IF filter
selectivity. All measurements are input-referred using a calibrated attenuation chain.

**Test equipment:**
- Siglent SDG1062X function generator (calibrated signal source, two-tone IMD)
- Siglent SDS2504X Plus oscilloscope (audio waveform capture for IMD test)
- Icom IC-7300 or Yaesu FT-891 HF transceiver (radio under test)
- rigctld (Hamlib) for CAT control via USB

**Attenuation chain:** The SDG output (−50 to +10 dBm) passes through a fixed attenuator
chain before the receiver antenna port. A total of 110 dB (60 dB + 30 dB + 20 dB in-line
pads) brings signals down to the −100 to −160 dBm range needed for MDS measurements.

**Resistive combiner for two-tone IMD:** Two SDG channels feed a T-combiner (two 100 Ω
series resistors to a 50 Ω junction). Each port adds 6 dB insertion loss (accounted for
automatically by the script).

**Fixtures and cabling:**
```
SDG CH1 ──→ 100 Ω ──┐
                      ├──→ 60 dB pad ──→ 30 dB pad ──→ 20 dB pad ──→ Radio [Ant]
SDG CH2 ──→ 100 Ω ──┘
           (T-combiner)

Radio [Headphone/Speaker out] ──→ Scope CH1    (IMD test only; AC-coupled)
Radio USB-B ──→ USB-A on PC ──→ rigctld -m 3073 -r /dev/ttyUSB0 -s 115200  (IC-7300)
Radio USB-B ──→ USB-A on PC ──→ rigctld -m 1036 -r /dev/ttyUSB0 -s 38400   (FT-891)
```
Use SMA attenuators for the pad chain. The T-combiner can be assembled from two BNC-T
connectors and two 100 Ω terminations, or purpose-built. For tests other than IMD, only
SDG CH1 is used (no combiner needed).

**Radio CAT setup:**
- IC-7300: Set CI-V baud rate to 115200 via Menu → Set → Connectors → CI-V Baud Rate
- FT-891: Set CAT rate to 38400 via Menu 031 (factory default)

---

### rf-bench-rf-amplifier

**GitHub:** https://github.com/jfrancis42/rf-bench-rf-amplifier

**Purpose:** Characterizes RF amplifiers: gain versus frequency across a user-specified
sweep range, 1 dB compression point (P1dB) by sweeping input power at a fixed frequency,
and harmonic content at a specified output level. Results are saved as a gain/phase plot,
compression curve, and text summary.

**Test equipment:**
- Siglent SDG1062X function generator (RF source)
- Siglent SSA3032X Plus spectrum analyzer (output power measurement)

**Fixtures and cabling:**
```
SDG CH1 ──→ [Amplifier input]
              [Amplifier output] ──→ attenuator (to protect SSA) ──→ SSA [RF In]
```
Add sufficient fixed attenuation between the amplifier output and the SSA RF input to
keep the SSA input level below 0 dBm (typically −10 dBm or less for best accuracy).
Rule of thumb: amplifier Pout_max + headroom ≤ −10 dBm at SSA input.

---

### rf-bench-rf-impedance

**GitHub:** https://github.com/jfrancis42/rf-bench-rf-impedance

**Purpose:** Measures complex impedance Z(f) — resistance R, reactance X, magnitude |Z|,
and phase angle — from 100 kHz to 60 MHz for inductors, capacitors, ferrite beads, RF
transformers, and other passive components. Uses a series-injection voltage divider topology
with a precision 50 Ω reference resistor and two-channel scope capture.

**Test equipment:**
- Siglent SDS2504X Plus oscilloscope (built-in AWG preferred; up to 25 MHz)
- Siglent SDG1062X function generator (optional; extends range to 60 MHz)

**Fixtures and cabling:**
```
Scope [Gen Out] ──→ 50 Ω reference resistor ──┬──→ [DUT] ──→ GND
                                               │
                                           Scope CH1              Scope CH2
                                          (before R_ref)     (between R_ref and DUT)
```
The voltage divider formed by R_ref and the DUT allows Z_DUT to be computed from
V_CH1 and V_CH2 using the reference resistor value. Keep lead lengths short to
minimize parasitic inductance, especially above 10 MHz. Mount the reference resistor
and DUT on an SMA breakout board for clean connections.

---

### rf-bench-scalar-vna

**GitHub:** https://github.com/jfrancis42/rf-bench-scalar-vna

**Purpose:** Two-port scalar network analyzer combining S11 (reflection coefficient /
return loss) and S21 (insertion loss / gain) measurements into a single plot. S11 uses the
same reflection bridge approach as the antenna analyzer. S21 uses through-connection
measurement. Suitable for filter characterization, amplifier tuning, and matching network
measurement up to 3.2 GHz.

**Test equipment:**
- Siglent SSA3032X Plus spectrum analyzer (with tracking generator; required)
- Siglent RB3X25 reflection bridge (for S11 measurement)

**Fixtures and cabling (S11 — reflection):**
```
SSA [Gen Out] ──→ RB3X25 [TG In]
                         │
                  RB3X25 [RF Out] ──→ SSA [RF In]
                         │
                  RB3X25 [DUT Port] ──→ DUT port 1   (port 2 terminated in 50 Ω)
```

**Fixtures and cabling (S21 — insertion):**
```
SSA [Gen Out] ──→ DUT port 1
                        │
                  DUT port 2 ──→ SSA [RF In]
```
Calibrate S11 with port 1 open (open-circuit reference) and with a 50 Ω termination
(matched reference) before connecting the DUT. Calibrate S21 with a through-connection
(port 1 directly to port 2, no DUT).

---

### rf-bench-tdr

**GitHub:** https://github.com/jfrancis42/rf-bench-tdr

**Purpose:** Time-domain reflectometer for locating impedance discontinuities in coax,
twinlead, waveguide, and PCB transmission lines. The scope AWG or SDG generates a fast
rising-edge pulse; the scope captures the incident and reflected waveforms; distances are
computed from the two-way travel time using the cable's velocity factor.

**Test equipment:**
- Siglent SDS2504X Plus oscilloscope (built-in AWG used as pulse source by default)
- Siglent SDG1062X function generator (optional; faster edge gives better spatial resolution)

**Fixtures and cabling (scope AWG):**
```
Scope [Gen Out] ──BNC-T──┬──→ Scope CH1 (captures incident + reflected pulse)
                          └──→ Cable under test (far end open, shorted, or terminated)
```

**Fixtures and cabling (SDG source):**
```
SDG CH1 ──BNC-T──┬──→ Scope CH1 (captures incident + reflected pulse)
                  └──→ Cable under test
```
The BNC-T junction must be at the scope input — this is the reference plane. Use a BNC
barrel to keep the T-junction mechanically tight. The SDG provides a faster edge and is
preferred for short cables (< 1 m) or for measuring PCB traces where spatial resolution
matters most.

---

## Quick-Start

### 1. Install driver packages

```bash
pip install rf-bench-drivers-siglent rf-bench-drivers-icom rf-bench-drivers-yaesu \
            rf-bench-drivers-utils rf-bench-drivers-buspirate
```

Or, for local development from the checked-out tree:

```bash
cd rf-bench/
pip install -e rf-bench-drivers-utils/ -e rf-bench-drivers-siglent/ \
            -e rf-bench-drivers-icom/ -e rf-bench-drivers-yaesu/ \
            -e rf-bench-drivers-buspirate/
```

### 2. Configure instrument IPs

All tools accept `--sdg`, `--scope`, `--ssa` (or `--analyzer`), `--dmm`, `--psu` flags to
override the default IP addresses. Assign static IPs to your instruments via their
Utility → LAN menus and adjust the defaults at the top of each script.

### 3. Start rigctld (receiver test only)

```bash
# IC-7300
rigctld -m 3073 -r /dev/ttyUSB0 -s 115200 &

# FT-891
rigctld -m 1036 -r /dev/ttyUSB0 -s 38400 &
```

### 4. Run a tool

```bash
# Antenna VSWR sweep — HF bands
python rf-bench-antenna-analyzer/antenna_analyzer.py --hf

# Receiver MDS + S-meter cal at 14.200 MHz
python rf-bench-receiver-test/receiver_test.py --radio ic7300 \
    --test smeter-cal mds --freq 14200 --atten 110

# Bode plot of an audio filter, 20 Hz – 20 kHz
python rf-bench-bode-plotter/bode_plotter.py --start 20 --stop 20000

# Crystal BVD parameters
python rf-bench-crystal-extractor/crystal_extractor.py --freq 14318
```

---

### rf-bench-transmitter-test

**GitHub:** https://github.com/jfrancis42/rf-bench-transmitter-test

**Purpose:** Automated HF transmitter test suite for the Icom IC-7300 and Yaesu FT-891.
Measures output power at all band centers, harmonic content with FCC Part 97 pass/fail
(−43 dBc for < 5 W; −60 dBW absolute for ≥ 5 W), ALC compression curve, and SSB carrier
suppression. PTT is controlled via rigctld CAT interface.

**Features:** Multi-band power sweep, harmonic measurement up to 4th harmonic, power control
sweep for ALC characterization, zero-span SSB carrier suppression measurement.

**Test equipment:**
- Siglent SSA3032X Plus (spectrum analyzer — power and harmonic measurement)
- Icom IC-7300 or Yaesu FT-891 (transmitter under test, via Hamlib rigctld)
- Fixed attenuator chain (60 dB default; 3× 20 dB SMA pads)

**Fixtures and cabling:**
```
Radio [TX Antenna port] ──→ 20 dB pad ──→ 20 dB pad ──→ 20 dB pad ──→ SSA [RF In]
                                          (total: 60 dB attenuation)
```
**CAUTION:** Never connect a transmitter directly to the SSA. Use minimum 60 dB
attenuation for a 100 W radio (50 dBm TX − 60 dB = −10 dBm at SSA — safe margin).

---

### rf-bench-phase-noise

**GitHub:** https://github.com/jfrancis42/rf-bench-phase-noise

**Purpose:** Measures single-sideband phase noise L(f) in dBc/Hz at user-specified
carrier offset frequencies using the SSA3032X Plus zero-span technique. Plots the
phase noise profile from near-carrier to 1 MHz offset. Works with any signal source
including external oscillators, transceivers, and the SDG1062X.

**Features:** Configurable offsets, multiple trace averages, linear-domain noise averaging
(correct noise statistics), automatic RBW selection per offset, reference lines at
−100/−120/−140 dBc/Hz.

**Test equipment:**
- Siglent SSA3032X Plus (zero-span noise floor measurement)
- Siglent SDG1062X (optional carrier source; `--source ext` for external oscillators)

**Fixtures and cabling:**
```
Source (SDG CH1 or external oscillator) ──→ [attenuator if needed] ──→ SSA [RF In]
```
Target carrier level: −10 to −20 dBm at SSA input. Use 10–20 dB attenuation for
transceivers or oscillators with higher output levels.

---

### rf-bench-noise-figure

**GitHub:** https://github.com/jfrancis42/rf-bench-noise-figure

**Purpose:** Y-factor noise figure meter using the SSA3032X Plus as the measurement
receiver. Supports single-frequency NF measurement and swept NF versus frequency.
Stores a baseline SSA noise figure calibration to de-embed the analyzer's own noise
from the measurement (Friis formula).

**Features:** Y-factor method, baseline SSA calibration with persistence, Friis
de-embedding for system NF→DUT NF conversion, linear-domain noise averaging,
single and swept measurement modes.

**Test equipment:**
- Siglent SSA3032X Plus (noise floor measurement via zero-span)
- Switched noise source (ENR typically 15–25 dB; toggled manually or via relay)

**Fixtures and cabling (DUT measurement):**
```
Noise source ──→ [DUT under test] ──→ SSA [RF In]
```

**Fixtures and cabling (baseline calibration):**
```
Noise source ──→ SSA [RF In]   (no DUT; measures SSA noise figure)
```

---

### rf-bench-band-occupancy

**GitHub:** https://github.com/jfrancis42/rf-bench-band-occupancy

**Purpose:** Continuous spectrum waterfall logger. Records repeated SSA sweeps over time,
builds a time × frequency power matrix, plots a waterfall image, and saves data as NumPy
`.npz` archives. Supports triggered narrow-band captures when spectrum activity exceeds a
threshold. Multi-band cycling mode visits multiple bands in sequence.

**Features:** Continuous sweep logging, triggered captures, multi-band cycling, offline
waterfall regeneration (`--plot` mode), autosave every 100 sweeps, SIGINT-safe partial
data save.

**Test equipment:**
- Siglent SSA3032X Plus (no other instruments required)

**Fixtures and cabling:**
```
Antenna ──→ SSA [RF In]
```
No special fixtures needed. The SSA's own antenna input is used directly.

---

### rf-bench-osc-stability

**GitHub:** https://github.com/jfrancis42/rf-bench-osc-stability

**Purpose:** Oscillator frequency stability analyzer. Tracks carrier frequency versus time
using SSA3032X Plus narrow-span power-weighted centroid, then computes Allan deviation
σ_y(τ) at multiple tau values. Identifies oscillator noise types from the ADEV slope.
Useful for comparing TCXOs, OCXOs, and Si5351-based oscillators.

**Features:** Sub-bin frequency resolution via centroid weighting, ADEV at multiple
averaging times, noise-type identification (white FM/flicker FM/random walk), offline
replot from saved data.

**Test equipment:**
- Siglent SSA3032X Plus (narrow-span frequency tracking)
- Siglent SDG1062X (optional carrier source; `--source ext` for external oscillators)

**Fixtures and cabling:**
```
Oscillator output ──→ [attenuator to −10 dBm if needed] ──→ SSA [RF In]
```

---

### rf-bench-matching-network

**GitHub:** https://github.com/jfrancis42/rf-bench-matching-network

**Purpose:** Impedance matching network designer for L, Pi, and T topologies. Synthesises
exact component values for any source/load impedance ratio at any frequency. Provides both
low-pass and high-pass configurations, nearest E24 component values, and a Smith chart plot.
Optional frequency response measurement mode with SDG + scope verifies the built network.

**Features:** L/Pi/T synthesis, both LP and HP topologies per design, Smith chart, E24
nearest-value recommendations, optional swept gain/phase measurement.

**Test equipment (synthesis only):**
- None required — pure calculation

**Test equipment (--measure mode):**
- Siglent SDG1062X + Siglent SDS2504X Plus

**Fixtures and cabling (--measure mode):**
```
SDG CH1 ──BNC-T──┬──→ Scope CH1 (reference)
                  └──→ 50 Ω ref resistor ──→ Network input
                                                     │
                                            Network output ──→ Scope CH2
```

---

### rf-bench-varactor

**GitHub:** https://github.com/jfrancis42/rf-bench-varactor

**Purpose:** Varactor (varicap) diode characterizer. Sweeps DC reverse-bias voltage and
measures complex impedance at a fixed RF frequency using the two-channel scope injection
circuit. Extracts capacitance C(V) and Q-factor Q(V) versus bias voltage. The tuning
ratio (C_max/C_min) is annotated on the plot.

**Features:** Full C(V) and Q(V) sweep, tuning ratio annotation, inductive anomaly detection,
RF isolation circuit (choke + bypass cap), safe 10 mA current-limited DC bias.

**Test equipment:**
- Siglent SPD3303X-E (DC bias supply, 10 mA current limit)
- Siglent SDG1062X (RF test signal source, −20 dBm)
- Siglent SDS2504X Plus (two-channel complex impedance capture)

**Fixtures and cabling:**
```
SDG CH1 ──→ [50 Ω ref resistor] ──→ [100 nF bypass cap] ──→ Varactor anode
                                                                      │
                                          [1 mH RF choke] ──→ SPD CH1 (+)
Scope CH1 ↑ (before ref R)     Scope CH2 ↑ (after bypass cap)
Varactor cathode ──→ SPD CH1(−) = Scope GND
```

---

### rf-bench-sdg-cal

**GitHub:** https://github.com/jfrancis42/rf-bench-sdg-cal

**Purpose:** SDG1062X self-characterization and calibration tool. Measures output level
flatness (dB correction vs. frequency), harmonic content (2nd/3rd harmonic dBc), output
power linearity (1 dB compression point), and two-channel amplitude tracking. Generates
per-channel correction tables for use in other measurement scripts.

**Features:** Four independent tests, per-channel flatness correction tables, P1dB
measurement, two-channel tracking, correction file persistence (`~/.sdg_cal.json`).

**Test equipment:**
- Siglent SDG1062X (signal source under test)
- Siglent SSA3032X Plus (reference measurement receiver)

**Fixtures and cabling:**
```
SDG CH1 ──→ SSA [RF In]
(swap to SDG CH2 when prompted for two-channel tests)
```

---

---

### rf-bench-synthesizer-characterizer

**Purpose:** Full performance map for Si5351 (I2C) and ADF4351 (SPI) PLL synthesizer chips.
Programs the chip via Bus Pirate, measures actual output with the SSA3032X Plus. Plots
frequency accuracy (ppm), output power vs. frequency (with sinc rolloff overlay for ADF4351),
harmonic content, and fractional-N spurs. Produces a calibration table JSON for use in VFO
designs.

**Features:** Si5351 full-range sweep (3 kHz–200 MHz), ADF4351 sweep (35 MHz–4.4 GHz with
output divider auto-selection), harmonic measurement at 2nd through 4th, fractional-N spur
detection, JSON calibration output.

**Test equipment:**
- Bus Pirate v3/v4 (SPI for ADF4351; I2C for Si5351)
- Siglent SSA3032X Plus (carrier power and harmonic measurement)

**Chips supported:**

| Chip | Interface | Frequency range | Notes |
|------|-----------|----------------|-------|
| Si5351 | I2C (CPHA=0, 400 kHz) | 3 kHz–200 MHz | 3 outputs; 25 MHz XTAL default |
| ADF4351 | SPI (CPOL=0, CPHA=0, 1 MHz) | 35 MHz–4.4 GHz | INT-N or FRAC-N mode |

**Wiring (Si5351):**
```
Bus Pirate SDA   →  Si5351 SDA
Bus Pirate SCL   →  Si5351 SCL
Bus Pirate +3.3V →  Si5351 VDD
Si5351 CLK0      →  SSA RF input (via SMA)
```

**Wiring (ADF4351):**
```
Bus Pirate CLK   →  ADF4351 CLK
Bus Pirate MOSI  →  ADF4351 DATA
Bus Pirate CS    →  ADF4351 LE (latch enable)
ADF4351 RF_OUT+  →  SSA RF input (via SMA, 50 Ω)
```

---

### rf-bench-dds-characterizer

**Purpose:** Programs AD9833 or AD9851 DDS chips via Bus Pirate SPI and measures actual RF
output on the SSA3032X Plus. Maps SFDR (spurious-free dynamic range), harmonic content,
output power rolloff (sinc envelope), and frequency accuracy across the full tuning word range.
Identifies which tuning word regions are "clean" versus prone to DAC quantization spurs.

**Test equipment:**
- Bus Pirate v3/v4 (SPI master)
- Siglent SSA3032X Plus (carrier power, SFDR, harmonics)

**Chips supported:**

| Chip | Interface | f_out max | Notes |
|------|-----------|-----------|-------|
| AD9833 | SPI Mode 3 (CPOL=1, CPHA=1), 16-bit words | f_mclk/2 | 10 mVpp typical; 25 MHz MCLK default |
| AD9851 | SPI Mode 0 (CPOL=0, CPHA=0), 40-bit words | ~70 MHz | 6× PLL multiplier option; 30 MHz XTAL default |

**Output:** 4-panel plot: output power (sinc rolloff), frequency accuracy (ppm), SFDR (worst
spur within ±1 MHz), harmonic content.

---

### rf-bench-osc-tc

**Purpose:** Oscillator temperature coefficient (TC) measurement. The Bus Pirate reads an I2C
temperature sensor while the SSA tracks carrier frequency in narrow-span centroid mode.
Logs temperature + frequency over time, fits a polynomial to the ppm vs. temperature curve,
and reports TC in ppm/°C. Works with any oscillator visible to the SSA.

**Test equipment:**
- Bus Pirate v3/v4 (I2C master — temperature sensor)
- Siglent SSA3032X Plus (carrier centroid frequency measurement)
- MCP9808, LM75, or BMP280 breakout (~$3)

**Sensor wiring:**
```
Bus Pirate +3.3V  →  Sensor VCC
Bus Pirate GND    →  Sensor GND
Bus Pirate SDA    →  Sensor SDA
Bus Pirate SCL    →  Sensor SCL
Oscillator output →  SSA RF input
```

**Output:** CSV log (timestamp, elapsed_s, temp_c, freq_hz, ppm) and 4-panel plot: temperature
vs. time, ppm vs. time, ppm vs. temperature scatter (with linear and polynomial fit), fit residuals.

---

### rf-bench-dig-atten-cal

**Purpose:** Calibration tool for PE4302 and HMC624A digital step attenuators. The Bus Pirate
steps through all 64 SPI attenuation codes (0 to 31.5 dB in 0.5 dB steps); the SSA tracking
generator provides the RF source; the SSA measures actual attenuation at each step across up
to 10 calibration frequencies. Generates a correction table JSON and 4-panel calibration plot.

**Test equipment:**
- Bus Pirate v3/v4 (SPI master — programs attenuator)
- Siglent SSA3032X Plus (tracking generator source + power measurement)
- PE4302 or HMC624A breakout with SMA connectors

**Wiring:**
```
SSA [Gen Out]    →  Attenuator RF-IN
Attenuator RF-OUT →  SSA [RF In]
Bus Pirate CLK   →  Attenuator CLK/SCLK
Bus Pirate MOSI  →  Attenuator DATA/SIN
Bus Pirate CS    →  Attenuator LE (PE4302) or CSB (HMC624A)
Bus Pirate +3.3V →  Attenuator VDD
```

**Output:** JSON correction table + 4-panel plot: actual vs. nominal attenuation, error vs. step,
error heatmap (step × frequency), RMS error per frequency.

---

### rf-bench-si5351-gen

**GitHub:** https://github.com/jfrancis42/rf-bench-si5351-gen

**Purpose:** Cheap multi-channel frequency generator using the Si5351A I2C clock chip.
Three independent outputs from ~3 kHz to 200 MHz. Useful as a low-cost signal source
for anyone without a bench function generator. Interactive curses TUI for real-time
channel control, or CLI mode for scripted use.

**Test equipment:**
- Bus Pirate v3/v4/v5 (I2C master)
- Si5351A breakout (~$5, e.g. Adafruit #2045 or generic)

**Wiring:**
```
Bus Pirate +3.3V  →  Si5351 VIN
Bus Pirate GND    →  Si5351 GND
Bus Pirate SDA    →  Si5351 SDA
Bus Pirate SCL    →  Si5351 SCL
CLK0 / CLK1 / CLK2  →  circuit under test
```

**PLL architecture note:** The Si5351A has two PLLs. CLK0 → PLL-A (exclusive, independent).
CLK1 and CLK2 share PLL-B; setting either reprograms the VCO. The TUI shows a `*` warning
on shared-PLL channels and always displays actual synthesized frequency alongside the
requested frequency.

**TUI features:** Arrow keys to select channel, SPACE to toggle, `f` to enter frequency,
`d` to cycle drive (2/4/6/8 mA), `a`/`z` for all-on/all-off, `p`/`l` to save/load presets.

**CLI usage:**
```bash
python3 si5351_gen.py --cli --clk0 10e6 --clk1 14.2MHz [--stay]
python3 si5351_gen.py --off   # disable all outputs
```

---

## RTL-SDR Projects

These projects use the `rf_bench.rtlsdr` driver to decode real-world signals from an
RTL-SDR dongle.  They are **receive-only** tools; use the SSA3032X Plus for calibrated
amplitude measurements.

**System requirements:** `rtl-sdr` (pacman), `pyrtlsdr>=0.2.93,<0.4` (pip).

---

### rf-bench-drivers-rtlsdr

**GitHub:** https://github.com/jfrancis42/rf-bench-drivers-rtlsdr

**Purpose:** RTL-SDR receiver driver package (`rf_bench.rtlsdr`).  Wraps pyrtlsdr with
PPM frequency correction (stored in `~/.rtlsdr_cal.json`), a streaming generator,
power spectrum (Welch's method), and signal activity scan.

**Key classes:** `RTLSDR`, `RTLSDRError`, `RTLSDRBusyError`

---

### rf-bench-rtlsdr-adsb

**GitHub:** https://github.com/jfrancis42/rf-bench-rtlsdr-adsb

**Purpose:** ADS-B local receiver.  Decodes Mode S at 1090 MHz using software AM
envelope demodulation, enriches each ICAO hex address with N-number and registration
data from the govt-data `/aircraft` API, logs to SQLite, and serves live JSON over HTTP.
Complements Vestigare (which aggregates internet feeds) by showing what is actually
audible at the antenna.

**Hardware:** RTL-SDR + 1090 MHz antenna.  A 1090 MHz bandpass filter before the
LNA significantly improves decode rate.

---

### rf-bench-rtlsdr-aprs

**GitHub:** https://github.com/jfrancis42/rf-bench-rtlsdr-aprs

**Purpose:** APRS direct-RF receiver on 144.390 MHz via RTL-SDR + direwolf.
Enriches callsigns from the govt-data `/callsigns` API.  The `--compare` flag
connects to the aprs-server PostgreSQL database and produces a three-way report:
heard locally + gated, heard locally but un-gated, and on APRS-IS but not heard locally.

**Hardware:** RTL-SDR + 2m vertical antenna.
**Requires:** `direwolf` (pacman).

---

### rf-bench-rtlsdr-wxsat

**GitHub:** https://github.com/jfrancis42/rf-bench-rtlsdr-wxsat

**Purpose:** Weather satellite receiver and decoder.  Predicts passes using pyorbital,
captures NOAA APT (137 MHz FM) via rtl_fm + sox, captures Meteor-M LRPT via rtl_sdr,
decodes APT to PNG via noaa-apt, decodes LRPT via SatDump.  Automatic scheduling mode
captures every pass above minimum elevation continuously.

**Hardware:** RTL-SDR + LNA + V-dipole antenna (~54 cm elements at 120°, no tracking needed).
**Satellites:** NOAA 15/18/19 (APT), Meteor-M N2-4 (LRPT).
**Requires:** `sox` (pacman), `noaa-apt` (AUR), optionally `satdump`.

---

### rf-bench-rtlsdr-recorder

**GitHub:** https://github.com/jfrancis42/rf-bench-rtlsdr-recorder

**Purpose:** Wideband IQ recorder to SigMF format.  Four capture modes: immediate
(fixed duration), scheduled (UTC start time), threshold-triggered (record only when
signal present), and rotating buffer (keep last N seconds, save on Ctrl-C).  Supports
complex float32 or int8 output (4× smaller).

**Hardware:** RTL-SDR dongle.

---

### rf-bench-rtlsdr-classify

**GitHub:** https://github.com/jfrancis42/rf-bench-rtlsdr-classify

**Purpose:** Signal classifier using instantaneous amplitude, frequency, and phase
variance heuristics.  Classifies detected signals as AM/OOK, FM/NFM, FSK, PSK,
CW/carrier, or pulsed.  Estimates bandwidth and symbol rate.  Optional SSA handoff:
when a signal is detected with sufficient confidence, the SSA is commanded to lock on
for precision amplitude and harmonic measurement.

**Hardware:** RTL-SDR + optionally SSA3032X Plus (for precision measurement).

---

### rf-bench-rtlsdr-fm-rds

**GitHub:** https://github.com/jfrancis42/rf-bench-rtlsdr-fm-rds

**Purpose:** FM band monitor with RDS decode.  Scans 87.5–108 MHz, demodulates
each station with rtl_fm, decodes RDS PI code / PS name / PTY / radiotext via
redsea.  Logs all observations to SQLite.  Identifies distant stations by PI code
region — a tropospheric ducting signature.  Optional `--alert` flag sends an SMS
via `~/money/sms.py` when a new PI region is detected.

**Hardware:** RTL-SDR + FM antenna.
**Requires:** `sox` (pacman), `redsea` (build from source).

---

## Future Projects — HP 8712B Vector Network Analyzer

> **These projects require the HP 8712B VNA and an Ethernet-GPIB adapter (KISS-488 Rev 2).**
> The HP 8712B is not yet connected. All projects below are blocked on the KISS-488 adapter
> being installed and `rf-bench-drivers-hp` being verified with the physical instrument.

The HP 8712B performs full two-port SOLT calibration and returns complex (magnitude + phase)
S-parameters — capabilities beyond what the Siglent instruments offer. The key distinction
is phase: the Siglent tools measure amplitude only. The HP 8712B enables Smith charts, group
delay, true Z = R + jX, and stability circles.

---

### rf-bench-drivers-hp *(future)*

**GitHub:** https://github.com/jfrancis42/rf-bench-drivers-hp

**Purpose:** Python driver package for the HP 8712B VNA via KISS-488 Ethernet-GPIB adapter.
Provides `rf_bench.hp.HP8712B` — the foundation for all HP 8712B projects.

**Requires:** KISS-488 Rev 2 adapter (HX Engineering) at a static IP on the bench LAN.
HP 8712B GPIB address: 16 (default). KISS-488 TCP port: 1234.

---

### rf-bench-drivers-solartron *(future)*

**GitHub:** part of the rf-bench monorepo (path: `drivers/solartron/`).

**Purpose:** Python driver for the Solartron 7151 6.5-digit Computing Multimeter (1985,
IEEE-488) via the same KISS-488 Ethernet-GPIB adapter as the HP 8712B. Provides
`rf_bench.solartron.Solartron7151`. Implements the full single-letter ASCII command
set (MODE, RANGE, NINES, TRACK, TRIG, DELIMIT, LITERALS, DRIFT, NULL, SRQ, LOCK,
STATUS, CALIBRATE/HI/LO/WRITE/REFRESH) extracted from the User Manual ND/7151/2 and
the JoergCH/s7150 reference C driver. Untested against hardware.

**Requires:** KISS-488 Rev 2 adapter (HX Engineering). Solartron 7151 GPIB address
(rear-panel DIP switches): driver default 16. KISS-488 TCP port: 1234. The 7151
must not share an address with the HP 8712B on the same bus.

---

### rf-bench-vna-sparams *(future)*

**GitHub:** https://github.com/jfrancis42/rf-bench-vna-sparams

**Purpose:** Full S-parameter suite (S11, S21, S12, S22) with SOLT calibration. Plots
magnitude and phase for all four S-parameters in a 2×2 grid. Saves Touchstone .s2p files
for import into other tools.

**Requires:** `rf-bench-drivers-hp`, HP 8712B, SOLT calibration standard set.

---

### rf-bench-vna-group-delay *(future)*

**GitHub:** https://github.com/jfrancis42/rf-bench-vna-group-delay

**Purpose:** Group delay measurement from S21 phase data. Useful for filter equalization,
cable dispersion, and amplifier characterization. The HP 8712B computes group delay
directly as −dφ/dω.

**Requires:** `rf-bench-drivers-hp`, HP 8712B.

---

### rf-bench-vna-impedance *(future)*

**GitHub:** https://github.com/jfrancis42/rf-bench-vna-impedance

**Purpose:** True RF impedance analyzer. Measures Z(f) = R(f) + jX(f) with full SOLT
calibration. Plots Smith chart, R and X on Cartesian axes, |Z| and phase. Far more
accurate than the scalar `rf-bench-rf-impedance` tool which lacks phase information.

**Requires:** `rf-bench-drivers-hp`, HP 8712B, SOLT calibration standard set.

---

### rf-bench-vna-transistor *(future)*

**GitHub:** https://github.com/jfrancis42/rf-bench-vna-transistor

**Purpose:** Transistor S-parameter characterization with DC bias. Measures S11, S21, S12,
S22 at each bias point. Computes gain, stability circles, maximum stable gain, and K-factor.
Generates data for transistor model extraction.

**Requires:** `rf-bench-drivers-hp`, HP 8712B, SPD3303X-E (bias), custom bias-T fixture
(RF choke + bypass cap on each port).

---

### rf-bench-vna-tline *(future)*

**GitHub:** https://github.com/jfrancis42/rf-bench-vna-tline

**Purpose:** Transmission line characterizer. Measures velocity factor, loss per unit length,
characteristic impedance, and propagation constant from S21 phase (electrical length) and
S21 magnitude (attenuation). Works for coax, twinlead, and PCB traces.

**Requires:** `rf-bench-drivers-hp`, HP 8712B.

---

### rf-bench-vna-filter *(future)*

**GitHub:** https://github.com/jfrancis42/rf-bench-vna-filter

**Purpose:** Filter characterization with group delay. Adds phase and group delay to the
S21 insertion loss measurement already available from `rf-bench-scalar-vna`. Shows filter
ringing and phase distortion across the passband.

**Requires:** `rf-bench-drivers-hp`, HP 8712B.

---

### rf-bench-vna-antenna *(future)*

**GitHub:** https://github.com/jfrancis42/rf-bench-vna-antenna

**Purpose:** Antenna feed-point impedance measurement. Returns Z(f) = R(f) + jX(f) from
calibrated S11, plus VSWR and return loss. Backwards-compatible with `rf-bench-antenna-analyzer`
output format. The HP 8712B gives R + jX so the engineer knows whether the antenna is
inductive or capacitive at each frequency, enabling direct matching network design.

**Requires:** `rf-bench-drivers-hp`, HP 8712B, SOLT calibration standard set.
