> ⚠️ **UNTESTED** — This implementation has not been verified against physical hardware.
> Code is complete but has not been bench-tested. Verify behavior before relying on output.

# rf-bench-relay-normalize

GitHub: https://github.com/jfrancis42/rf-bench-relay-normalize

2-relay reference/DUT path switcher for scalar RF measurement normalization.
Automates the most common manual step in Bode plotter, scalar VNA, RF amplifier
characterizer, and similar measurements: switching between a "reference through" path
(source connected directly to the detector, no DUT) and the "DUT" path (DUT inserted
between source and detector) without touching coax cables.  Normalized result = DUT
measurement / reference measurement.

## Hardware

| Instrument | Role |
|-----------|------|
| Bus Pirate v3/v4/v5 (/dev/ttyUSB1) | I2C master for XL9535 relay board |
| XL9535 (or PCA9535/TCA9535) relay board, 2 relays minimum | Controlled by Bus Pirate over I2C |
| Two RF relays (see relay selection note below) | Relay 0 = reference bypass; Relay 1 = DUT path |

Connect Bus Pirate SDA/SCL/GND to the relay board's I2C header.  The relay board
requires a separate 5 V supply for the relay coils (the Bus Pirate's 5 V rail is not
sufficient).  I2C address is set by the A0/A1/A2 jumpers on the board (default 0x20
= all jumpers open/unsoldered).

## Wiring diagram

```
Source ──┬── Relay 0 (REF) ──────────────────┬── Detector
         │                                   │
         └── Relay 1 (DUT) ── DUT In──DUT──DUT Out──┘
```

Only one relay is energized at a time (close_only semantics).  Both open = safe
state; neither path is active.

## Relay selection

For measurements above ~5 MHz, use proper RF relays — the HK19F/SRD-05VDC general
purpose relays on most cheap relay breakout boards have high contact inductance and
degrade insertion loss rapidly above HF:

- **Omron G6Y-1** (SPDT, 500 MHz, 50 Ω) — good up to 500 MHz; SMA-compatible footprint
- **Omron G6K-2F** (DPDT, 1 GHz) — for higher frequencies
- **TE OAR-SS-112DM,000** (SPDT, 3 GHz) — if you need L/S-band

For audio-frequency or DC Bode plots only, the HK19F on a standard breakout board
is acceptable.

Use the XL9535 board to drive the relay coil transistors; mount RF relays close to
the RF path with SMA connectors and short controlled-impedance coax jumpers.

## CLI usage

```bash
# Switch to reference path (bypass, no DUT)
python relay_normalize.py --ref

# Switch to DUT path
python relay_normalize.py --dut

# Open both relays (safe state)
python relay_normalize.py --off

# Show active path
python relay_normalize.py --status

# Self-test: cycle between ref and dut 10 times
python relay_normalize.py --cycle 10

# Interactive guided measurement: prompts you at each step
python relay_normalize.py --measure

# Custom hardware options
python relay_normalize.py --ref --bp /dev/ttyUSB2 --addr 0x21 --settle-ms 100

# Active-LOW relay board
python relay_normalize.py --dut --active-low
```

## Python API

### Basic usage

```python
from rf_bench.buspirate import BusPirate
from relay_normalize import PathSwitcher

with BusPirate("/dev/ttyUSB1") as bp:
    with PathSwitcher(bp, ref_relay=0, dut_relay=1,
                      i2c_addr=0x20, settle_ms=50) as ps:
        ps.select_reference()   # energize relay 0, wait 50 ms
        ref_data = measure()
        ps.select_dut()         # energize relay 1, wait 50 ms
        dut_data = measure()
        normalized = dut_data / ref_data
        ps.all_off()            # both relays open (safe state)
```

`__exit__` calls `all_off()` then exits I2C mode; the `finally` / `with` block
ensures relays are de-energized even if `measure()` raises.

### Integration pattern for other scripts

Add `--auto-ref` support to any measurement script by embedding this pattern:

```python
def run_with_normalization(ps, measure_fn):
    """Run measure_fn with reference path, then with DUT path.

    Returns (ref_result, dut_result).  Leaves both relays open on exit.
    """
    ps.select_reference()
    ref = measure_fn()
    ps.select_dut()
    dut = measure_fn()
    ps.all_off()
    return ref, dut
```

Example — Bode plotter integration:

```python
from relay_normalize import PathSwitcher

def bode_with_normalization(bp, measure_bode_fn):
    with PathSwitcher(bp) as ps:
        ref_gain, ref_phase = run_with_normalization(ps, measure_bode_fn)
        dut_gain, dut_phase = run_with_normalization(ps, measure_bode_fn)
    normalized_gain  = dut_gain  - ref_gain   # dB subtraction
    normalized_phase = dut_phase - ref_phase
    return normalized_gain, normalized_phase
```

### PathSwitcher constructor

| Parameter | Default | Description |
|-----------|---------|-------------|
| `bp` | — | BusPirate instance (I2C not yet entered; PathSwitcher enters it) |
| `ref_relay` | 0 | Relay index for the reference bypass path |
| `dut_relay` | 1 | Relay index for the DUT path |
| `i2c_addr` | 0x20 | XL9535 I2C address |
| `active_high` | True | True for ULN2803 boards; False for active-LOW boards |
| `settle_ms` | 50 | Milliseconds to wait after relay switch |

### PathSwitcher methods

| Method | Description |
|--------|-------------|
| `select_reference()` | Energize ref relay only; wait settle_ms |
| `select_dut()` | Energize DUT relay only; wait settle_ms |
| `all_off()` | De-energize both relays (safe state) |
| `close()` | all_off() + exit I2C mode |
| `active_path` | Property: `'ref'`, `'dut'`, or `'off'` |
