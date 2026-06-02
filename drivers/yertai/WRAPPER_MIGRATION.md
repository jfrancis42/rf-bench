# ET5406A Wrapper Migration — June 2, 2026

## Summary

The `rf_bench.yertai.ET5406A` driver has been converted from a standalone pyserial
implementation to a **thin wrapper** around the upstream `philpagel/ET54.py` library
(commit 82be1da, June 2, 2026).

## What Changed

### Architecture

**Before:**
- Direct pyserial implementation (~981 lines)
- Self-contained SCPI protocol implementation
- No external dependencies beyond pyserial

**After:**
- Thin wrapper around `ET54` library (~710 lines)
- Delegates all SCPI operations to upstream `ET54.ch1`
- Dependencies: `ET54>=0.1`, `pyvisa>=1.15.0`, `pyvisa-py>=0.8.0`, `pyserial>=3.5`

### API Compatibility

**100% backward compatible** — no code changes required:

```python
# All existing code continues to work unchanged
from rf_bench.yertai import ET5406A, ET5406AError

with ET5406A() as load:          # ✓ CH340 auto-detection still works
    load.CC_mode(1.0)            # ✓ Same API
    load.on()                    # ✓ Same methods
    v, i, p, r = load.read_all() # ✓ Same return order
    load.off()
```

### Key Features Preserved

- ✅ **CH340 auto-detection** — `ET5406A()` without arguments still auto-detects
- ✅ **Same API surface** — all 80 methods/properties unchanged
- ✅ **Same return values** — `read_all()` returns `(V, I, P, R)` as before
- ✅ **Same exception class** — `ET5406AError` still works
- ✅ **Context manager** — `with ET5406A() as load:` unchanged
- ✅ **All test scripts** — existing test/panel scripts work unmodified

### Implementation Details

The wrapper:

1. Converts CH340 port (e.g., `/dev/ttyUSB0`) to VISA resource (`ASRL/dev/ttyUSB0::INSTR`)
2. Initializes upstream `ET54` instance with correct baud/timeout
3. Exposes `ch1` channel through a flat API (hiding `.ch1` from users)
4. Reorders `read_all()` to maintain `(voltage, current, power, resistance)` order
   (upstream returns `(current, voltage, power, resistance)`)

## Why Wrapper?

### Benefits

1. **Upstream maintenance** — bug fixes and enhancements flow automatically
2. **Multi-device support** — upstream supports ET5407A+, ET5410, ET5411, ET5420 series
3. **Code reduction** — 271 fewer lines to maintain
4. **Standards compliance** — uses pyvisa (industry standard instrument I/O)
5. **Your bug fixes included** — all four fixes from PR #5 now in upstream

### Trade-offs

- **Added dependencies**: pyvisa, pyvisa-py (adds ~1.5 MB installed)
- **Indirect control**: wrapper adds one indirection layer
- **Upstream coupling**: depends on upstream API stability (mitigated by property delegation)

## Testing

All compatibility verified:

```bash
# API surface test — 80 attributes checked
python3 test_wrapper.py

# Full functional test (requires hardware on greybox)
python3 /home/jfrancis/Dropbox/build/rf-bench/yertai_test.py

# Virtual panel (requires hardware or --demo mode)
python3 /home/jfrancis/Dropbox/build/rf-bench/virtual-instruments/et5406a_panel.py --demo
```

## Migration Path (for users)

**No action required** — this is a drop-in replacement.

If you have `rf-bench-drivers-yertai` installed:

```bash
# Reinstall to get new dependencies
pip install --upgrade rf-bench-drivers-yertai
```

If installed via editable mode:

```bash
cd drivers/yertai
pip install -e . --upgrade
```

## Files Changed

| File | Status |
|------|--------|
| `rf_bench/yertai/et5406a.py` | Replaced with wrapper (981 → 710 lines) |
| `pyproject.toml` | Added ET54, pyvisa, pyvisa-py dependencies |
| `README.md` | Updated description |
| `test_wrapper.py` | **NEW** — API compatibility test |
| `WRAPPER_MIGRATION.md` | **NEW** — this document |

## Files Unchanged (still work)

- `et5406a_panel.py` — virtual instrument panel
- `yertai_test.py` — functional test suite
- All project scripts using `rf_bench.yertai.ET5406A`

## Upstream Correspondence

| Item | Upstream (ET54.py) | This Wrapper |
|------|-------------------|--------------|
| Commit | 82be1da (2026-06-02) | Current |
| License | MIT | GPL-3.0-or-later |
| Dependencies | pyvisa, pyvisa-py, pyserial | Same |
| Architecture | `ET54` instrument + `channel` classes | Flat `ET5406A` class |
| Multi-channel | ✓ ET5420 dual-channel support | Single-channel only |
| CH340 detect | ✗ Manual VISA resource string | ✓ Automatic |

## Publication Status

**NOT YET PUBLISHED:**
- GitHub: not pushed
- PyPI: not uploaded

Awaiting explicit approval before:
- `git commit` and `git push`
- `python -m build && twine upload dist/*`

## Rollback Plan

If issues discovered, rollback by:

```bash
cd /home/jfrancis/Dropbox/build/rf-bench
git checkout HEAD~1 drivers/yertai/
pip install -e drivers/yertai/ --force-reinstall
```

The previous standalone implementation is preserved in git history.

---

**Validation:** All tests passed as of 2026-06-02 06:45 MDT.
