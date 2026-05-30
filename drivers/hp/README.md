# rf-bench-drivers-hp

> **⚠ Untested — awaiting physical hardware.** This driver was written from documentation
> (HP 8712B Network Analyzer Programmer's Guide, KISS-488 / Prologix protocol specification)
> but has not been run against a real HP 8712B. Commands marked `# Verify against HP 8712B manual`
> in the source are uncertain and must be confirmed once the KISS-488 adapter is installed.

HP 8712B Vector Network Analyzer driver for Python bench automation.

Controls the HP 8712B (300 kHz – 1.3 GHz, 2-port VNA) via a KISS-488 Rev 2
Ethernet-GPIB adapter using a Prologix-compatible command set over TCP.

## Installation

```bash
pip install rf-bench-drivers-hp
```

## Quick start

```python
from rf_bench.hp import HP8712B

with HP8712B("10.1.1.70") as vna:
    print(vna.identify())
    vna.setup_sweep(1e6, 1.3e9, points=401)
    vna.set_parameter("S11")
    vna.set_format("MLOG")
    vna.single_sweep()
    freqs = vna.get_frequencies()   # Hz, numpy array
    db    = vna.get_trace_db()       # dB, numpy array
```

## Hardware

- Instrument: HP 8712B (GPIB address 16 by default)
- Adapter: KISS-488 Rev 2, TCP port 1234
- Default host: 10.1.1.70

## License

GPL-3.0-or-later
