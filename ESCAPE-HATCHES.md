# Escape Hatch API — Raw Command Access

All rf-bench drivers provide "escape hatch" methods for sending raw commands to devices. This allows users to access functionality not yet wrapped by the driver API.

## Purpose

Drivers implement high-level methods for common operations, but instruments often support additional commands not yet exposed. Escape hatches let you:

- Access undocumented or vendor-specific features
- Test new commands during development
- Work around driver bugs or limitations
- Use features added in newer firmware

## SCPI Instruments (Siglent, Virtual Instruments)

All SCPI-based drivers provide `write()` and `query()` methods:

### `write(cmd: str) -> None`

Send a command without expecting a response.

```python
from rf_bench.siglent import SDM3000X

dmm = SDM3000X("10.1.1.63")
dmm.write("SYST:BEEP")  # Beep the instrument
dmm.write("DISP:TEXT 'HELLO'")  # Display text (if supported)
```

### `query(cmd: str) -> str`

Send a query and return the response.

```python
resp = dmm.query("SYST:VERS?")  # Query SCPI version
print(resp)  # "1995.0"
```

## Drivers with Escape Hatches

### ✅ Implemented

| Driver | Escape Hatch Methods | Protocol | Added |
|--------|---------------------|----------|-------|
| `SDM3000X` | `write()`, `query()` | SCPI/TCP | 2026-06-15 |
| `SDG1000X` | `write()`, `query()` | SCPI/TCP | 2026-06-15 |
| `SDS2000X` | `write()`, `query()` | SCPI/TCP | 2026-06-15 |
| `SPD3303X` | `write()`, `query()` | SCPI/TCP | 2026-06-15 |
| `SSA3000X` | `write()`, `query()` | SCPI/TCP | Pre-existing |
| `ET5406A` | `write()`, `query()` | Serial ASCII | 2026-06-15 |
| `IC7300` | `raw_command()` | Hamlib rigctld | 2026-06-15 |
| `IC9700` | `raw_command()` | Hamlib rigctld | 2026-06-15 |
| `FT891` | `raw_command()` | Hamlib rigctld | 2026-06-15 |
| `FlipperZero` | `raw_command()` | Serial CLI | 2026-06-15 |
| `KiwiSDR` | `send_command()` | WebSocket | 2026-06-15 |
| `SunSDR` | `send_raw()` | TCI WebSocket | Pre-existing (improved docs) |
| `BusPirate` | `raw_command()` | Binary BBIO | 2026-06-15 |

### 🔄 Future Work

| Driver | Planned Methods | Protocol | Note |
|--------|----------------|----------|------|
| Virtual Instruments | `write()`, `query()` | SCPI/TCP | Have private `_write()` methods; need public wrappers |

### ❌ Not Applicable

| Driver | Reason |
|--------|--------|
| `RTLSDR` | Library-based (no command interface) |
| `GPSD` | Read-only JSON protocol (no commands to send) |

## Warnings

**Use escape hatches with caution:**

1. **Invalid commands may crash the instrument** or put it in an unexpected state
2. **No validation** — the driver won't check command syntax
3. **Firmware-specific** — commands may work on one model but not another
4. **State corruption** — raw commands can break driver state tracking
5. **Consult the manual** — always refer to the instrument's programming guide

## Best Practices

### 1. Test in isolation first

```python
# Good: Test raw command in a separate script
with SDM3000X("10.1.1.63") as dmm:
    resp = dmm.query("CONF:VOLT:DC")
    print(f"Config: {resp}")
```

### 2. Always check responses for queries

```python
# Good: Validate the response
resp = dmm.query("*IDN?")
if not resp:
    print("ERROR: No response from instrument")
```

### 3. Document your raw commands

```python
# Good: Explain why you're using a raw command
# Workaround: Driver doesn't support text display yet (see issue #42)
dmm.write("DISP:TEXT 'TESTING'")
```

### 4. Consider filing an issue

If you need an escape hatch repeatedly, request a proper driver method:
```
GitHub: jfrancis42/rf-bench → Issues → New Issue
Title: "Add display_text() method to SDM3000X"
```

## Examples by Driver

### SDM3000X (Multimeter)

```python
from rf_bench.siglent import SDM3000X

with SDM3000X("10.1.1.63") as dmm:
    # Beep the instrument
    dmm.write("SYST:BEEP")
    
    # Query SCPI version
    ver = dmm.query("SYST:VERS?")
    print(f"SCPI version: {ver}")
    
    # Display custom text (firmware-dependent)
    dmm.write("DISP:TEXT 'CAL CHECK'")
```

### SDG1000X (Function Generator)

```python
from rf_bench.siglent import SDG1000X

with SDG1000X("10.1.1.55") as sdg:
    # Set output load impedance to 50 ohm
    sdg.write("OUTP CH1,LOAD,50")
    
    # Query output load
    load = sdg.query("C1:OUTP? LOAD")
    print(f"Load: {load}")  # "LOAD,50OHM"
    
    # Enable burst mode (not yet in driver API)
    sdg.write("C1:BTWV STATE,ON")
```

### SSA3000X (Spectrum Analyzer)

```python
from rf_bench.siglent import SSA3000X

with SSA3000X("10.1.1.60") as ssa:
    # Already has public write() and query() from initial design
    
    # Set display units to dBµV (not wrapped)
    ssa.write(":UNIT:POW DBUV")
    
    # Query current units
    units = ssa.query(":UNIT:POW?")
    print(f"Units: {units}")  # "DBUV"
```

## Finding Valid Commands

### 1. Programming Manual

Each instrument has a SCPI programming manual (PDF):
- **Siglent:** Available on siglent.com → Product Page → Documents
- **SDM3000X:** "SDM3000_ProgrammingGuide_EN_V1.4.pdf"
- **SDG1000X:** "SDG_ProgrammingGuide_PG01-E02A.pdf"
- **SSA3000X:** "SSA3000X_Programming Guide_V1.2.pdf"

### 2. Web Interface

Some instruments have a SCPI console in their web interface:
- Navigate to `http://<instrument-ip>/` in a browser
- Look for "SCPI Control" or "Remote Control" panel
- Send test commands and observe responses

### 3. Vendor Software

Siglent's SDS1000X-E/SDG1000/SSA3000 PC software shows raw SCPI in debug logs.

## Contributing

If you add an escape hatch to a driver:

1. Add `write()` and/or `query()` methods after the communication layer
2. Include docstrings with examples and warnings
3. Update this document (`ESCAPE-HATCHES.md`)
4. Add examples to the driver's README
5. Submit a pull request

## See Also

- `drivers/siglent/README.md` — Siglent driver API documentation
- `drivers/icom/README.md` — Hamlib-based radio drivers
- Individual driver files for implementation examples
