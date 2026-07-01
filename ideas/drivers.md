## Driver status

| Driver | PyPI name | Version | Status | Notes |
|--------|-----------|---------|--------|-------|
| `rf_bench.siglent` | `rf-bench-drivers-siglent` | 0.1.0 | ✅ | All 5 instruments tested; 9 documented firmware workarounds |
| `rf_bench.icom` | `rf-bench-drivers-icom` | 0.1.0 (0.2.0 local) | ✅ | IC-7300 + IC-9700; Hamlib-based. Local 0.2.0 adds IC-9700 satellite/PTT extras, unpublished |
| `rf_bench.yaesu` | `rf-bench-drivers-yaesu` | 0.1.0 | ✅ | FT-891 only |
| `rf_bench.utils` | `rf-bench-drivers-utils` | 0.1.0 | ✅ | Pure RF math — no instruments |
| `rf_bench.yertai` | `rf-bench-drivers-yertai` | 0.1.0 | ✅ | ET5406A+ DC load. Wraps philpagel/ET54.py with field-order fix |
| `rf_bench.gpsd` | `rf-bench-drivers-gpsd` | 0.1.1 | ✅ | gpsd JSON/TCP client; tested with u-blox |
| `rf_bench.koolertron` | `rf-bench-drivers-koolertron` | 0.2.0 | ✅ | MHS-5225A, tested 2026-06-08; 0.2.0 adds arbitrary-waveform upload |
| `rf_bench.rtlsdr` | `rf-bench-drivers-rtlsdr` | 0.1.2 | ✅ | Thin pyrtlsdr wrapper + PPM cal cache |
| `rf_bench.nanovna` | `rf-bench-drivers-nanovna` | 0.1.0 | ✅ | NanoVNA-F tested 2026-06-30; 17 API smoke tests pass; API swappable with `rf_bench.hp.HP8712B` |
| `rf_bench.flipper` | `rf-bench-drivers-flipper` | 0.2.1 | 🔶 | Sub-GHz OOK + 2-FSK only; IR/RFID/NFC untested |
| `rf_bench.buspirate` | `rf-bench-drivers-buspirate` | 0.1.0 | 🧪 | Published, untested in rf-bench context |
| `rf_bench.kiwisdr` | (not yet on PyPI) | 0.1.0 local | 🧪 | Code complete; IP TBD |
| `rf_bench.sunsdr` | (not yet on PyPI) | 0.2.0 local | 🧪 | Code complete; IP TBD |
| `rf_bench.fx2lafw` | (not yet on PyPI) | 0.1.0 local | ✅ | FX2LAFW 8-ch logic analyzer; sigrok-cli subprocess; ready to publish |
| `rf_bench.relay` | (not on PyPI) | local | ❌ | Hardware ordered 2026-06-03 |
| `rf_bench.arduino_relay_board` | `rf-bench-drivers-arduino-relay-board` | 0.1.0 | ✅ | Arduino Uno + Vilros Ethernet R3 (W5100), 4-ch network relay, TCP :5025 — tested 2026-06-25 |
| `rf_bench.shuttlexpress` | (not yet on PyPI) | 0.1.0 local | ✅ | Contour Design ShuttleXpress jog/shuttle USB HID; Linux evdev; tested 2026-07-01 on 10.1.0.10 |
| `rf_bench.kestrel` | (not yet on PyPI) | 0.1.0 local | ✅ | Kestrel 5500L BLE weather meter; reverse-engineered GATT; async (bleak); tested 2026-07-01 on 10.1.0.10 |
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

### VNA API compatibility

`rf_bench.nanovna.NanoVNA` and `rf_bench.hp.HP8712B` expose the same
core method names so projects can swap between them by changing only the
construction line:

```
setup_sweep(start_hz, stop_hz, points),
set_parameter("S11"|"S21"|"S12"|"S22"), get_parameter(),
set_format("MLOG"|"PHAS"|...),
single_sweep() → bool, pause(), resume(), hold(), continuous(),
get_frequencies() → ndarray,
get_s_data() → complex ndarray (selected parameter),
get_trace_db() → ndarray, get_trace_phase() → ndarray,
get_trace_db_at(freq_hz) → float,
get_s11() → ndarray, get_s21() → ndarray,
set_marker(freq_hz, marker=1), get_marker_value(marker=1) → float,
marker_off(marker=1),
correction_on() / correction_off() / cal_on() / cal_off(),
is_correction_on() → bool,
average_s_data(n) → ndarray,
close(), context manager
```

**Capability mismatch raises `NotImplementedError`, not silent fallback:**

- NanoVNA refuses `set_parameter("S12")` / `set_parameter("S22")` — the
  hardware is forward-only (1.5-port). Reverse the DUT physically.
- NanoVNA refuses `set_power(dbm)` — hardware exposes only a coarse
  `power 0..3` index with uncalibrated absolute output. Use
  `vna.raw_power_index(0..3)` when you need it.
- NanoVNA refuses `set_averaging(count)` — firmware has no host-side
  averaging control. Use `average_s_data(n)` for software averaging
  (also works on the HP).

NanoVNA-only extras:
- `get_s_data_full() → (freqs, s11, s21)` (exploits the NanoVNA's
  simultaneous S11+S21 measurement)
- SOLT walkthrough: `cal_reset/open/short/load/isoln/thru/done`
- `save_cal(slot)` / `recall_cal(slot)` — flash slots
- `iter_segments(...)` — span > 401 points across multiple sweeps
- `raw(cmd)` — escape hatch to the shell

---

