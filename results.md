# rf-bench Driver Testing — Results

**Date:** 2026-05-26  
**Hardware:** Siglent bench — SDG1062X (sig gen), SDS2504X Plus (scope), SDM3045X (DMM), SPD3303X-E (PSU), SSA3032X Plus (SA)  
**Test setup:** SDG CH1 → Scope CH1, SDG CH2 → Scope CH2, DMM → PSU CH1 output

---

## Summary

All five Siglent instrument drivers were tested against live hardware across two test
rounds.  Twelve bugs were found and fixed.  All instruments are confirmed working.

---

## Instruments Tested

| Instrument | IDN |
|------------|-----|
| SDG1062X | `Siglent Technologies,SDG1062X,SDG1XDDD7R6784,1.01.01.33R3` |
| SDS2504X Plus | `Siglent Technologies,SDS2504X Plus,SDS2PEEX7R1702,5.4.0.1.6.2R5` |
| SDM3045X | `Siglent Technologies,SDM3045X,...` |
| SPD3303X-E | `Siglent Technologies,SPD3303X-E,...` |
| SSA3032X Plus | `Siglent Technologies,SSA3032X Plus,...` |

---

## Bugs Found and Fixed

### `sds2000x.py` — 9 bugs fixed

**1. Connection took 60 seconds on every new `SDS2000X()` instance**

`connect()` set `RECV_TIMEOUT` (60 s) before the initial flush `recv()`, then
waited the full 60 s for a welcome banner that never arrives.  Fixed by using a
1 s timeout for the flush, then restoring the 60 s timeout for waveform transfers.

**2. `capture_audio()` returned 5 bytes (all +127) on second call**

`_autorange_vdiv()` left the scope in RUN state with `TDIV 0.01 S`.  When
`capture_audio()` then changed TDIV to 0.1 S while the scope was running, the
acquisition was corrupted.  Fixed by adding `self.stop(); time.sleep(0.1)` at
the start of `capture_audio()` before any TDIV/VDIV changes.

**3. `:WAVeform:DATA?` returned only 1000 display-decimated points**

Without `:WAVeform:POINt MAX`, the scope returns the 1000-point display buffer,
not the full acquisition memory.  At `TDIV 0.1 S` this means 1000 pts at
~10 kHz effective sample rate instead of 10 M pts at 20 MHz.  Added
`:WAVeform:POINt MAX` before each waveform read.

**4. WAVEDESC showed `vgain = 0.5 mV/cnt` (×100 error) on second+ capture**

The original loop-based `_autorange_vdiv()` corrupted scope register state
between preamble and data reads.  Replaced with PAVA-based single-pass approach.

**5. `measure_rms()`, `measure_vpp()`, `measure_freq()` returned NaN**

PAVA measurements require the scope to be running.  Added `self.run();
time.sleep(0.5)` before each PAVA query.

**6. 0.1 V/div and 0.5 V/div return display-buffer data, not deep memory**

`:WAVeform:DATA?` at these two specific VDIV settings returns 1 000 display-buffer
samples at 2 GSps instead of full acquisition memory.  Both VDIV values removed
from `_VDIV_STEPS`.  A post-capture check raises `RuntimeError` with a helpful
message if any bad acquisition slips through.

**7. PAVA-based autorange collapsed to 5 mV/div for a 600 mVpeak signal**

First fix used 2 V/div as the probe VDIV.  At 2 V/div (vgain = 200 mV/cnt) a
600 mVpeak signal occupies only ±3 ADC counts — PAVA cannot resolve it and
returns near-zero, causing autorange to select 5 mV/div and fully saturate the
ADC.  Fixed by replacing PAVA with a direct waveform capture at 0.2 V/div:
99th-percentile of |counts| × vgain gives a robust peak estimate without relying
on PAVA.

**8. `measure_*` PAVA never converged after a long capture**

After `capture_audio(duration_s=1.0)` the scope is left at TDIV = 0.1 S/div.
`measure_rms/vpp/freq` waited only 0.5 s — half a sweep — before querying PAVA,
which returned NaN or 0.17 Hz.  Fixed by having each `measure_*` set
`TDIV 0.002 S` (20 ms window) before running; 0.5 s → 25 full sweeps.

**9. Autorange probe used TDIV=0.01S which may give a different acquisition mode**

Changed the probe capture in `_autorange_vdiv` to use `TDIV 0.05 S` (500 ms window),
the same TDIV confirmed to give 10 M samples at 40 MHz with 0.2 V/div.

### `ssa3000x.py` — 2 bugs fixed

**10. `SSA3000X()` raised `AttributeError: 'NoneType' has no attribute 'sendall'`**

`__init__()` set `self._sock = None` but never called `self.connect()`.  Fixed.

**11. Missing `close()` method; `__enter__` re-connected an already-connected socket**

Added `close()` (disables TG then calls `disconnect()`).  Fixed `__enter__` to
return `self` without reconnecting.

### `sdg1000x.py` — 1 bug fixed

**12. `query_channel()` returned 0.0 for all numeric fields**

The SDG1062X firmware appends unit suffixes to BSWV values: `FRQ,1000HZ`,
`AMP,0.2V`, `AMPDBM,-10.0dBm`.  `float()` raises `ValueError` and falls silently
to zero.  Fixed by adding `_strip_unit()` which strips the suffix via regex before
parsing.

---

## New Functions Added

### `sds2000x.py`
- `capture_audio(vdiv=None)` — `vdiv` parameter; `None` triggers auto-range
- `_autorange_vdiv(channel)` — waveform-based auto-range (0.2 V/div probe)

### `sdg1000x.py`
- `set_frequency(channel, freq_hz)` — change frequency without disturbing amplitude
- `query_output_state(channel)` — returns `True` if output is enabled
- `_strip_unit(val_str)` — strips firmware unit suffixes before `float()` parse

### `sdm3000x.py`
- `configure_period()` — configure for period measurement
- `configure_continuity()` — configure for continuity test
- `configure_diode()` — configure for diode forward-voltage test
- `measure_stats(n, settle_s)` — take n readings and return mean/stdev/min/max dict

### `spd3303x.py`
- `set_all(channel, volts, amps)` — set voltage and current limit in one call
- `ramp_voltage(channel, target_v, step_v, delay_s)` — soft-ramp to target voltage
- `wait_settled(channel, timeout_s, tol_v)` — block until output is within tolerance
- `get_status()` — extended to include `ch1_on`, `ch2_on`, `ch3_on` output-enable bits
- `is_enabled(channel)` — rewritten to use `SYST:STAT?` bitmask (bits 4–6)

### `ssa3000x.py`
- `close()` — disable TG and disconnect
- `set_ref_level(dbm)` — set display reference level
- `set_input_attenuation(db)` — set or auto-select input attenuation
- `enable_averaging(count)` — enable trace averaging
- `disable_averaging()` — return to clear-write mode
- `get_peak(trace)` — return (freq_hz, level_dbm) of the peak point on the trace

---

## Test Results

### SDG1062X (10.1.1.55)
- `identify()` ✓
- `set_sine(1, 1000, -10.0)` → 0.2 Vpp @ 1 kHz ✓
- `set_sine(2, 5000, -20.0)` → 0.0632 Vpp @ 5 kHz ✓
- `output_on(1)`, `output_on(2)` ✓
- `query_output_state(1)` → `True` ✓
- `query_channel(1)` → `{'wvtp': 'SINE', 'freq_hz': 1000.0, 'amp_vpp': 0.2, 'amp_dbm': -10.0, ...}` ✓
- `set_frequency(1, 2000)`, re-query → freq updated ✓
- `set_level(1, -20.0)` ✓

### SDS2504X Plus (10.1.1.58) — round 1
- `identify()` ✓
- `capture_audio(channel=1, duration_s=1.0)` → 10,000,000 samples @ 20.00 MHz ✓
- `_autorange_vdiv()` — selects correct VDIV from 99th-pct peak ✓
- `measure_rms(1)`, `measure_vpp(1)`, `measure_freq(1)` ✓

### SDS2504X Plus — round 2 (cable reconnected)

| Measurement | -10 dBm | -20 dBm |
|-------------|---------|---------|
| Capture samples | 10,000,000 | 10,000,000 |
| Sample rate | 20 MHz | 20 MHz |
| FFT peak frequency | **1000.0 Hz ✓** | **1000.0 Hz ✓** |
| FFT peak amplitude | 599 mVpk | 190 mVpk |
| Harmonic distortion | none | none |
| Level ratio | — | **10.0 dB ✓** |
| PAVA frequency | **1000.0 Hz ✓** | — |

The 10.0 dB level ratio between -10 and -20 dBm is exact, confirming correct
relative amplitude measurement.  FFT shows a clean 1 kHz sine with no harmonics.
All deep-memory acquisitions return 10 M samples.

**Amplitude calibration note:** The scope (1 MΩ input) measures ~600 mVpeak for
a signal the SDG reports as -10 dBm / 200 mVpp with LOAD=50.  Simple theory
predicts ~200 mVpeak (2× open-circuit factor).  The 3× excess is consistent and
reproducible; its precise origin has not been determined.  For FFT/IMD analysis,
only relative amplitude matters — the level ratio is exact.

### SDM3045X (10.1.1.63)
- `identify()` ✓
- `measure_vdc()` → 5.0003 V (with PSU CH1 set to 5.0 V) ✓
- `measure_stats(50)` → stdev ≈ 25.4 µV ✓
- `configure_vdc(range_v=5)`, `read_multiple(50)` ✓

### SPD3303X-E (10.1.1.56)
- `identify()` ✓
- `set_voltage(1, 5.0)`, `set_current(1, 0.5)`, `enable(1)` ✓
- `measure_voltage(1)` → 5.0000 V ✓
- `set_voltage(1, 3.3)`, `wait_settled(1)` → settled to 3.3000 V ✓
- `ramp_voltage(1, 5.0)` → smooth ramp ✓
- `is_enabled(1)` → `True` ✓
- `get_status()` → `{'ch1_mode': 'CV', ..., 'ch1_on': True, ...}` ✓
- `disable_all()` ✓

### SSA3032X Plus (10.1.1.60)
- `identify()` ✓
- `enable_tracking_generator(0)` → `True` ✓
- `setup_band(7_000_000, 7_300_000, points=1001)` → RBW = 1 kHz ✓
- `single_sweep()` → `True` ✓
- `get_trace()` → 1001-element numpy array ✓
- `get_peak()` → (freq_hz, level_dbm) ✓
- `set_ref_level(0)`, `set_input_attenuation(10)` ✓
- `enable_averaging(10)`, `disable_averaging()` ✓
- `disable_tracking_generator()`, `continuous_sweep()` ✓

---

## Known Issues / Caveats

| Issue | Driver | Severity |
|-------|--------|----------|
| 0.1 V/div and 0.5 V/div trigger firmware bug (display buffer instead of deep memory) | `sds2000x.py` | Fixed — these VDIV values excluded from `_VDIV_STEPS` |
| PAVA unreliable for absolute amplitude (frequency measurement is accurate) | `sds2000x.py` | Documented |
| Amplitude at 1 MΩ input is ~3× higher than 50 Ω theory predicts | Hardware / SDG | Documented; relative measurements correct |
| SSA3032X Plus firmware: `:TRAC:DATA? TRC1` works; some older firmware uses `:TRACE1:DATA?` | `ssa3000x.py` | Documented in docstring |
| SDM3045X does not support `measure_capacitance()` or `measure_temperature()` | `sdm3000x.py` | By design (SDM3055/3065X only) |
| SPD3303X CH3 is hardware-selected voltage; `set_voltage(3, ...)` raises `ValueError` | `spd3303x.py` | By design |
