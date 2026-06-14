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

