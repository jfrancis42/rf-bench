# rf-bench Drivers

Python driver packages for bench instruments. Each is published to PyPI separately (e.g. `pip install rf-bench-drivers-siglent`) or install all via `pip install rf-bench`.

| Driver dir | Python package | PyPI name | Status |
|---|---|---|---|
| `siglent/` | `rf_bench.siglent` | `rf-bench-drivers-siglent` | ✅ |
| `icom/` | `rf_bench.icom` | `rf-bench-drivers-icom` | ✅ |
| `yaesu/` | `rf_bench.yaesu` | `rf-bench-drivers-yaesu` | ✅ |
| `utils/` | `rf_bench.utils` | `rf-bench-drivers-utils` | ✅ |
| `yertai/` | `rf_bench.yertai` | `rf-bench-drivers-yertai` | ✅ |
| `koolertron/` | `rf_bench.koolertron` | `rf-bench-drivers-koolertron` 0.2.0 | ✅ tested |
| `buspirate/` | `rf_bench.buspirate` | `rf-bench-drivers-buspirate` | 🧪 |
| `flipper/` | `rf_bench.flipper` | `rf-bench-drivers-flipper` | 🔶 |
| `rtlsdr/` | `rf_bench.rtlsdr` | `rf-bench-drivers-rtlsdr` | ✅ |
| `gpsd/` | `rf_bench.gpsd` | `rf-bench-drivers-gpsd` | ✅ |
| `kiwisdr/` | `rf_bench.kiwisdr` | not yet | 🧪 |
| `sunsdr/` | `rf_bench.sunsdr` | not yet | 🧪 |
| `fx2lafw/` | `rf_bench.fx2lafw` | not yet | 🧪 |
| `relay/` | `rf_bench.relay` | not yet | ❌ hw ordered |
| `arduino-relay-board/` | `rf_bench.arduino_relay_board` | `rf-bench-drivers-arduino-relay-board` 0.1.0 | ✅ tested |
| `shuttlexpress/` | `rf_bench.shuttlexpress` | not yet | ✅ tested 2026-07-01 |
| `kestrel/` | `rf_bench.kestrel` | not yet | ✅ tested 2026-07-01 |
| `fluke/` | `rf_bench.fluke` | not yet | ✅ 80i-400 AC clamp (passive CT, 1 mA/A, read via any DMM) |
| `hp/` | `rf_bench.hp` | not yet | ❌ pending KISS-488 |
| `nanovna/` | `rf_bench.nanovna` | `rf-bench-drivers-nanovna` 0.1.0 | ✅ tested 2026-06-30 (API-swappable with `rf_bench.hp.HP8712B`) |
| `solartron/` | `rf_bench.solartron` | not yet | ❌ pending KISS-488 |
| `virtual-*/` | `rf_bench.virtual` | not yet | ✅ all built |

## VNA API compatibility

`rf_bench.nanovna.NanoVNA` and `rf_bench.hp.HP8712B` expose the same core
method names so projects can swap between them by changing only the
construction line. See `nanovna/README.md` for the full parity table.

Capability mismatch raises `NotImplementedError`, not silent fallback:
NanoVNA refuses `set_parameter("S12"|"S22")`, `set_power(dbm)`, and
`set_averaging(count)`; the HP supports all of them.

## Status legend

- ✅ Built, tested against hardware
- 🔶 Built, tested, has known limitations
- 🧪 Code complete, limited or no hardware testing
- ❌ Hardware not yet present
