# rf-bench-drivers-nanovna

Python driver for the **NanoVNA** family of low-cost vector network
analyzers — the original edy555 NanoVNA, hugen79 NanoVNA-H / NanoVNA-H4,
DiSlord NanoVNA-H4 builds, and the Deepelec **NanoVNA-F** (verified
2026-06-30 against an F-series HW2.3/HW3.1 running firmware 0.2.1).

Speaks the ASCII shell protocol over the on-board USB CDC serial port (no
NanoVNA-Saver / nanovna-python dependency). Returns numpy arrays.

## Status

🧪 **First release.** Verified against the user's NanoVNA-F:
`identify`, `setup_sweep`, `get_frequencies`, `get_s11`, `get_s21`,
`get_trace_db`, `get_trace_phase`, `set_parameter`, `set_marker`,
`is_correction_on`, `average_s_data`, `single_sweep`, `pause`, `resume`,
`get_trace_db_at`, refusal of S12/S22 and `set_power(dbm)`. Calibration
flow (`cal_open/short/load/isoln/thru/done/save`) is wired but has not
been exercised end-to-end with the user's cal kit.

Not yet supported:
- NanoVNA-V2 / S-A-A-2 (binary protocol — a different driver class).
- LiteVNA / NanoVNA-F V2 (also binary protocol).

## Supported hardware

| Variant | Protocol | Tested? |
|---|---|---|
| NanoVNA (edy555 original) | ASCII shell over CDC | ✅ same protocol family |
| NanoVNA-H / H4 (hugen79) | ASCII shell over CDC | ✅ same protocol family |
| NanoVNA-H4 (DiSlord) | ASCII shell over CDC (superset) | ✅ extras via `.raw()` |
| **NanoVNA-F (Deepelec)** | ASCII shell over CDC | **✅ tested 2026-06-30** |
| NanoVNA-V2 / S-A-A-2 | binary protocol | ❌ not supported |
| LiteVNA | binary protocol | ❌ not supported |

## Install

```bash
pip install rf-bench-drivers-nanovna
```

or development:

```bash
cd drivers/nanovna
pip install -e . --break-system-packages
```

Requires `pyserial>=3.5` and `numpy>=1.20`.

## Quick start

```python
from rf_bench.nanovna import NanoVNA
import numpy as np

with NanoVNA("/dev/ttyACM1") as vna:        # autodetect: NanoVNA()
    print(vna.identify())
    vna.setup_sweep(start_hz=1e6, stop_hz=900e6, points=101)
    freqs, s11, s21 = vna.get_s_data_full() # all three at once
    print(f"S11 dB: {20*np.log10(np.abs(s11)+1e-30).min():.1f}")
```

## Swappable API with HP 8712B

This driver implements the same core method names as
`rf_bench.hp.HP8712B`, so projects can switch between them by changing
only the construction call:

```python
def run(vna):
    vna.setup_sweep(1e6, 900e6, points=101)
    vna.set_parameter("S11")
    vna.single_sweep()
    freqs = vna.get_frequencies()
    s_data = vna.get_s_data()
    db = vna.get_trace_db()
    phase = vna.get_trace_phase()
    return freqs, s_data, db, phase

# Works with either driver:
from rf_bench.nanovna import NanoVNA
from rf_bench.hp import HP8712B
run(NanoVNA())
run(HP8712B("10.1.1.70"))
```

Methods available on **both** drivers:

| Method | NanoVNA | HP 8712B |
|---|---|---|
| `identify() -> str` | ✅ | ✅ |
| `setup_sweep(start, stop, points)` | ✅ | ✅ |
| `set_parameter("S11" \| "S21" \| "S12" \| "S22")` | ✅ (S11/S21 only) | ✅ |
| `get_parameter() -> str` | ✅ | ✅ |
| `set_format("MLOG" \| "PHAS" \| ...)` | ✅ | ✅ |
| `single_sweep() -> bool` | ✅ | ✅ |
| `pause() / resume() / hold() / continuous()` | ✅ | ✅ |
| `get_frequencies() -> ndarray` | ✅ | ✅ |
| `get_s_data() -> ndarray (complex)` | ✅ (selected param) | ✅ (selected param) |
| `get_trace_db() -> ndarray` | ✅ | ✅ |
| `get_trace_phase() -> ndarray` | ✅ | ✅ |
| `get_trace_db_at(freq_hz) -> float` | ✅ | ✅ |
| `get_s11() -> ndarray` | ✅ | ✅ |
| `get_s21() -> ndarray` | ✅ | ✅ |
| `set_marker(freq_hz, marker=1)` | ✅ | ✅ |
| `get_marker_value(marker=1) -> float` | ✅ | ✅ |
| `marker_off(marker=1)` | ✅ | ✅ |
| `correction_on() / correction_off() / cal_on() / cal_off()` | ✅ | ✅ |
| `is_correction_on() -> bool` | ✅ | ✅ |
| `average_s_data(n) -> ndarray` | ✅ | ✅ |
| `close()` / context manager | ✅ | ✅ |

Methods NanoVNA-only (HP raises `AttributeError`):

- `get_s_data_full() -> (freqs, s11, s21)` — exploits the NanoVNA's
  simultaneous S11+S21 measurement (HP must re-sweep per parameter)
- `cal_reset/open/short/load/isoln/thru/done` — SOLT walkthrough
- `save_cal(slot)` / `recall_cal(slot)` — flash slots
- `iter_segments(start, stop, seg_points)` — span > 401 points across
  segments
- `set_marker_index(marker, point_index)` — direct index addressing
- `raw_power_index(0..3)` — coarse hardware power index
- `raw(cmd) -> str` — escape hatch to the shell

Methods HP-only (NanoVNA raises `NotImplementedError`):

- `set_power(dbm)` — NanoVNA exposes only a coarse index (`raw_power_index`)
- `set_averaging(count)` — NanoVNA firmware has no host-side averaging
  control; use `average_s_data(n)` for software averaging

S-parameter scope: NanoVNA hardware is forward-only (1.5-port VNA).
`set_parameter("S12")` / `set_parameter("S22")` raise
`NotImplementedError`. To measure S22 / S12 on a DUT, reverse it
physically and re-measure as S11 / S21 from the new orientation.

## Calibration

SOLT walkthrough for the standard 12-term error model:

```python
with NanoVNA() as vna:
    vna.setup_sweep(1e6, 900e6, points=101)
    vna.cal_reset()
    input("Attach OPEN to port 0,  press Enter…"); vna.cal_open()
    input("Attach SHORT to port 0, press Enter…"); vna.cal_short()
    input("Attach LOAD  to port 0, press Enter…"); vna.cal_load()
    input("Attach LOAD  to port 1, press Enter…"); vna.cal_isoln()
    input("Connect THRU port 0→1,   press Enter…"); vna.cal_thru()
    vna.cal_done()
    vna.save_cal(0)            # save to flash slot 0
```

To recall later:

```python
with NanoVNA() as vna:
    vna.setup_sweep(1e6, 900e6, points=101)
    vna.recall_cal(0)
```

Calibration applies only over the swept range it was measured at. Change
the sweep, recalibrate.

## Building & publishing

```bash
cd drivers/nanovna
python -m build
twine upload dist/* --skip-existing
```

## License

GPL-3.0-or-later
