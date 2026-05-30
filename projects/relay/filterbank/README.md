> ⚠️ **UNTESTED** — This implementation has not been verified against physical hardware.
> Code is complete but has not been bench-tested. Verify behavior before relying on it.

# rf-bench-relay-filterbank

GitHub: https://github.com/jfrancis42/rf-bench-relay-filterbank

Relay-switched bandpass or low-pass filter bank controller.  Each relay in an
XL9535-driven relay board selects a different filter stage.  The script can run
standalone (switch to a specific band by frequency) or be imported as a Python
module by other rf-bench projects to automatically switch filters as frequency
changes.

## Primary use cases

1. **TX low-pass filter bank** — switch the correct LPF before the SSA when
   doing transmitter harmonic measurements across HF bands.  The
   `rf-bench-transmitter-test` project imports `FilterBank` and calls
   `select_for_freq()` before each band's harmonic sweep.

2. **RX bandpass filter bank** — switch the appropriate BPF before the IC-7300
   for receiver sensitivity or IMD tests.

## Hardware

| Instrument | Role |
|-----------|------|
| Bus Pirate v3/v4/v5 (/dev/ttyUSB1) | I2C master for XL9535 |
| XL9535 relay board (8-relay, ULN2803) | Relay driver IC, address 0x20 |
| Filter bank (LPF or BPF stages) | DUT switched by the relays |

Wire the Bus Pirate I2C pins (SDA, SCL) to the XL9535 board's I2C header.
Enable the Bus Pirate's internal pull-ups (the driver does this automatically).

**RF relay note:** For signals in the signal path use coaxial RF relays
(Omron G6Y-1, Omron G2RL-1, or equivalent) or dedicated coaxial relay modules.
Generic PCB relays (HK19F, SRD series) are designed for audio/DC and have poor
RF characteristics above a few MHz — high contact resistance, poor isolation,
and significant insertion loss at HF.  The XL9535 driver board switches the
relay coils; the RF path is routed through the relay contacts separately.

## Usage

### Standalone CLI

```bash
# List all filters in the config
python relay_filterbank.py --list

# Switch to the filter covering 14.2 MHz (20m LPF)
python relay_filterbank.py --freq 14200000

# Switch to relay 3 directly
python relay_filterbank.py --relay 3

# Turn all relays off (bypass / no filter)
python relay_filterbank.py --off

# Cycle through all relays for hardware verification (500 ms each)
python relay_filterbank.py --ping --dwell 500

# Use a custom config file and non-default Bus Pirate port
python relay_filterbank.py --freq 3573000 --config rx-bpf-bank.json --bp /dev/ttyUSB2

# Active-LOW relay board
python relay_filterbank.py --freq 7074000 --active-low

# Quiet mode (no status output, useful in scripts)
python relay_filterbank.py --freq 14200000 --quiet
```

### Embedded module (transmitter-test integration)

```python
from rf_bench.buspirate import BusPirate
from relay_filterbank import FilterBank, FilterBankError

with BusPirate("/dev/ttyUSB1") as bp:
    with FilterBank(bp, config_file="hf-lpf-bank.json") as fb:
        # Automatically select 20m LPF for 14.2 MHz
        fb.select_for_freq(14_200_000)
        # ... run harmonic measurement ...

        # Automatically select 40m LPF for 7.074 MHz
        fb.select_for_freq(7_074_000)
        # ... run harmonic measurement ...
```

The transmitter-test project would call `fb.select_for_freq(freq_hz)` before
each SSA sweep so the correct LPF is always in circuit.

### Minimal integration without context manager

```python
with BusPirate("/dev/ttyUSB1") as bp:
    fb = FilterBank(bp)
    try:
        fb.select_for_freq(21_074_000)   # 17m LPF
        # ... do work ...
    finally:
        fb.close()                        # all_off + i2c_exit
```

## Config file format

```json
{
  "name": "HF TX LPF Bank",
  "filters": [
    {"relay": 0, "label": "160m LPF", "f_low_hz": 0,        "f_high_hz": 2200000},
    {"relay": 1, "label": "80m LPF",  "f_low_hz": 2200000,  "f_high_hz": 5000000},
    {"relay": 2, "label": "40m LPF",  "f_low_hz": 5000000,  "f_high_hz": 8000000}
  ]
}
```

| Field | Type | Description |
|-------|------|-------------|
| `name` | string | Human-readable name shown in status output |
| `filters` | array | One entry per relay/filter stage |
| `filters[].relay` | int | Relay index (0-based, must be contiguous 0..N-1) |
| `filters[].label` | string | Human-readable filter name |
| `filters[].f_low_hz` | int | Lower frequency bound (inclusive), Hz |
| `filters[].f_high_hz` | int | Upper frequency bound (exclusive), Hz |

Frequency ranges must be non-overlapping.  `select_for_freq()` picks the first
entry where `f_low_hz <= freq_hz < f_high_hz`.  Gaps between ranges are
allowed — a frequency in a gap raises `FilterBankError`.

The supplied `hf-lpf-bank.json` covers the full HF range (DC through 60 MHz)
with an 8-relay bank.  Create your own JSON for a BPF bank or different relay
count.

## Options reference

```
--bp PORT       Bus Pirate port (default /dev/ttyUSB1)
--addr ADDR     XL9535 I2C address in hex (default 0x20)
--config FILE   Filter bank JSON config (default: hf-lpf-bank.json)
--active-low    Relay board is active-LOW (default: active-HIGH / ULN2803)
--dwell MS      Dwell per relay in --ping mode, milliseconds (default 500)
--quiet         Suppress status output
```
