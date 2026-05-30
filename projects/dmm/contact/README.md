> ⚠️ **UNTESTED** — This implementation has not been verified against physical hardware.
> Code is complete but has not been bench-tested. Verify behavior before relying on output.

# rf-bench-dmm-contact

**GitHub:** https://github.com/jfrancis42/rf-bench-dmm-contact

Kelvin contact resistance survey tool using the SDM3045X in 4-wire mode. Increments
a pin counter automatically after each stable reading. Optionally prompts for a net
label per pin. End-of-session summary shows min/max/mean/σ and fail count.

## Hardware

| Instrument | Role |
|-----------|------|
| Siglent SDM3045X (10.1.1.63) | 4.5-digit DMM — 4-wire resistance |

4-wire Kelvin probes required for sub-ohm measurements. Connect Hi/Lo sense and
Hi/Lo current leads to the DUT pin/joint.

## Usage

```
python dmm_contact.py [options]
```

### Options

| Flag | Default | Description |
|------|---------|-------------|
| `--dmm HOST` | 10.1.1.63 | DMM IP address |
| `--threshold MOHM` | 100 | Fail threshold in mΩ |
| `--log FILE` | — | CSV log path |
| `--labels` | off | Prompt for net name after each pin |
| `--count N` | ∞ | Total pins to measure |

### Examples

```bash
# Measure 40 pins, 100 mΩ threshold
python dmm_contact.py --count 40

# Stricter pass/fail with label prompts
python dmm_contact.py --threshold 50 --log connector.csv --labels --count 80
```

## Console output

```
  Pin   1: Probe now .....→    12.450 mΩ  PASS
  Pin   2: Probe now ...→     198.300 mΩ  FAIL
```

## End-of-session summary

```
================================================================
  CONTACT RESISTANCE SURVEY SUMMARY
================================================================
  Pins measured : 40
  Threshold     : 100.0 mΩ
  Min           :   8.210 mΩ  (pin 5)
  Max           : 198.300 mΩ  (pin 2)
  Mean          :  24.650 mΩ
  Std dev (σ)   :  18.412 mΩ
  Failures      : 1 / 40
  Failed pins   : 2
================================================================
```

## CSV columns

`timestamp`, `pin`, `label`, `mohm`, `result`
