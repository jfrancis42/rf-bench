# rf-bench-drivers-fluke

Fluke current-clamp accessories for use with a generic bench DMM.

Currently: the **Fluke 80i-400 AC current clamp**.

## What this is

The 80i-400 is a *passive current transformer* — no digital interface, no
battery, no display. You clamp it around a conductor and it outputs an AC
current into a meter's current jacks at a fixed **1 mA per amp** ratio
(1000:1). It is normally sold to pair with a Fluke meter, but it works with
any DMM: the milliamp value the meter reads *is* the conductor current in amps.

This package is therefore not a communications driver. It is a thin,
well-documented conversion + accuracy layer that optionally composes with any
rf-bench DMM driver (anything exposing `measure_iac()` returning amperes) so a
script can read amps through the clamp directly.

## Datasheet

| Spec | Value |
|---|---|
| Output ratio | 1 mA/A (1000:1) |
| Output type | AC current, banana plugs |
| Current range | 1 A – 400 A AC |
| Frequency | 48 Hz – 1000 Hz |
| Accuracy | ±(3 % of reading + 0.4 A) |
| Power | none (passive CT) |
| Max conductor | one ⌀30 mm or two ⌀25 mm |

## Wiring (read this — it's the common mistake)

1. Plug the probe into the meter's **current (A / mA) input**, *not* the
   volts input. It is a current source; on a volts range it reads ~zero.
2. Set the meter to **AC current** (true-RMS preferred).
3. At 400 A the probe delivers **400 mA** — check the meter's mA range and
   fuse are rated for it.

## Installation

```bash
pip install rf-bench-drivers-fluke     # not yet on PyPI; pip install -e drivers/fluke
```

No dependencies. Pure conversion works with no hardware at all; live reads
need one of the rf-bench DMM drivers.

## Usage

Pure conversion (no instrument):

```python
from rf_bench.fluke import Fluke80i400

clamp = Fluke80i400()
clamp.amps_from_milliamps(240.0)    # 240.0  (meter on mA range)
clamp.amps_from_meter_amps(0.240)   # 240.0  (meter on A range -> *1000)
clamp.accuracy(240.0)               # 7.6    (± amps: 3% + 0.4 A)

r = clamp.reading_from_milliamps(240.0)
print(f"{r.amps:.1f} +/- {r.uncertainty:.1f} A  (in_range={r.in_range})")
```

Live read through any rf-bench DMM driver:

```python
from rf_bench.siglent import SDM3045X
from rf_bench.fluke import Fluke80i400

dmm   = SDM3045X("10.1.0.50")
clamp = Fluke80i400(dmm=dmm)

r = clamp.read()                    # meter set to AC mA
print(f"{r.amps:.1f} +/- {r.uncertainty:.1f} A")
```

The clamp only calls the meter's `measure_iac()` (and `measure_idc()` if you
pass `dc=True`), so any driver matching that shape works — it is meter-agnostic.

## Note on DC

The 80i-400 is an AC current transformer and is **not specified for DC**.
`read(dc=True)` exists only for off-label experimentation and its results are
not guaranteed by the datasheet.
