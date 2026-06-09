# koolertron-cal

Self-calibration tool for the **Koolertron / MHinstek MHS-5200A series**
dual-channel DDS signal generator (sold rebadged as KKmoon, AliExpress
"200MSa/s 12Bit DDS", and other names).

The MHS-5200A's amplitude rolls off significantly above ~5 MHz and the two
output channels have independent DAC + amplifier paths so they roll off
slightly differently. The internal TCXO error is roughly 7-12 ppm
depending on which reference you compare against. This tool characterises
both and writes a calibration JSON file at `~/.koolertron_mhs5200_cal.json`
that the `rf_bench.koolertron` driver loads automatically.

## What it produces

```json
{
  "instrument": "MHS-5200A",
  "raw_model": "5225A5040000",
  "model": "MHS-5225A",
  "calibrated_at": "2026-06-08T22:00:37+00:00",
  "scope_used": "10.1.1.58",
  "amplitude": {
    "1": [
      {"freq_hz": 1000.0,    "commanded_dbm": 0.0, "commanded_v": 0.63,
       "measured_vpp": 0.633, "measured_dbm": 0.01, "correction_db": -0.01},
      ...
      {"freq_hz": 25000000.0, "commanded_dbm": 0.0, "commanded_v": 0.63,
       "measured_vpp": 0.367, "measured_dbm": -4.73, "correction_db": 4.73}
    ],
    "2": [...]
  },
  "freq_calibrated_at": "2026-06-08T23:09:08+00:00",
  "frequency_ppm_offset": 11.77,
  "freq_source": "SDG1000X @ 10.1.1.51",
  "freq_cal_grid": [
    {"commanded_hz": 10000000.0, "measured_hz": 10000117.7, "error_ppm": 11.77}
  ]
}
```

The driver reads two fields:

* `amplitude.{channel}[]` — used by `set_amplitude_dbm(ch, freq_hz, dbm)` to
  apply a per-channel, frequency-dependent dB correction so the **delivered**
  power into a 50 Ω load matches the requested dBm.
* `frequency_ppm_offset` — used by `set_frequency()` to pre-correct the
  commanded frequency so the **actual** output matches the requested value.

Both fields are optional. With no cal file the driver silently uses the
unit's built-in (factory) calibration.

## Bench wiring

### amp-cal — uses oscilloscope

```
MHS-5200A CHx output  ────── direct BNC ──────  Scope CH1 input (50 Ω)
```

No external attenuator. The scope's calibrated Vpp measurement gives the
actual delivered amplitude at each cal frequency directly. The scope's
input is set to 50 Ω termination programmatically.

For CH1 → CH2 you swap the cable from CH1 BNC to CH2 BNC; the script will
prompt you when it's time to swap.

### freq-cal — two methods

The driver supports two reference sources. Run whichever fits your bench
setup:

**Self-loop** (`--method self`, default; **no external instrument needed**):
```
MHS CH1 output  ──── short BNC patch ────  MHS Ext.IN (front)
```
The MHS CH1 drives its own counter input. The measured ppm error is the
difference between the MHS DDS clock and the MHS counter clock — typically
~7 ppm. This is what corrects the unit so its OWN counter readback agrees
with the commanded frequency.

**SDG-driven** (`--method sdg`; uses Siglent SDG1062X as reference):
```
SDG CH1 output  ──── BNC ──── MHS Ext.IN (front)
```
The SDG drives the MHS counter. The measured ppm error is the SDG's TCXO
offset relative to the MHS counter clock — typically ~12 ppm on this bench.

**Scope-AWG-driven** (`--method scope`; uses SDS2000X+ built-in AWG as reference):
```
Scope AWG output ("Gen Out" BNC, front) ──── BNC ──── MHS Ext.IN (front)
```
The scope's licensed 25 MHz AWG drives the MHS counter. The measured ppm
error is the scope's TCXO offset relative to the MHS counter clock. This
is functionally equivalent to the SDG-driven method but uses one fewer
instrument (most benches already have the scope). The scope's AWG
amplitude is set to 2.0 Vpp into 50 Ω, well above the counter threshold.

None of these three methods provides absolute frequency reference; for
that you need a GPS-disciplined source (the planned `projects/gps/freq-cal/`
Si5351 setup).

## Usage

```bash
# Run both calibrations in sequence. Prompts for cable swaps between
# phases (CH1 ↔ CH2 in amp-cal, then to MHS Ext.IN for freq-cal).
python koolertron_cal.py both

# Just amplitude cal (CH1 + CH2):
python koolertron_cal.py amp-cal

# Skip CH2 in amp-cal:
python koolertron_cal.py amp-cal --channels 1 --no-prompt

# Self-loop frequency cal:
python koolertron_cal.py freq-cal --method self

# SDG-driven frequency cal:
python koolertron_cal.py freq-cal --method sdg --sdg-host 10.1.1.51

# Scope-AWG-driven frequency cal (uses SDS2000X+ Gen Out):
python koolertron_cal.py freq-cal --method scope --scope-host 10.1.1.58
```

After running, the driver picks up the calibration automatically:

```python
from rf_bench.koolertron import MHS5200A

with MHS5200A() as gen:
    print(gen.calibration_info())
    # -> {'loaded': True, 'frequency_ppm_offset': 11.77,
    #     'amplitude_channels': [1, 2], 'calibrated_at': '2026-06-08T...'}

    # Frequency is now pre-corrected for the unit's TCXO offset:
    gen.set_frequency(1, 1_000_000)

    # Amplitude is corrected for the per-channel DAC roll-off:
    gen.set_amplitude_dbm(1, 25_000_000, 0.0)   # delivers 0 dBm at 25 MHz
```

To bypass the cal file (e.g., to characterise the bare instrument), pass
`calibration=False`:

```python
gen = MHS5200A(calibration=False)
```

## Empirical notes (firmware 5040000)

The data below was captured against an MHS-5225A on 2026-06-08.

### Amplitude calibration

CH1 and CH2 produce nearly identical responses (within ~0.4 dB at 25 MHz).
Both are flat from DC to ~5 MHz, then begin a smooth DDS-reconstruction
roll-off:

| Frequency | CH1 correction | CH2 correction |
|----------:|---------------:|---------------:|
|     1 kHz |       -0.01 dB |       -0.01 dB |
|   100 kHz |       -0.01 dB |       -0.01 dB |
|     1 MHz |       -0.01 dB |       -0.01 dB |
|     4 MHz |       +0.21 dB |       +0.21 dB |
|    10 MHz |       +0.95 dB |       +1.21 dB |
|    25 MHz |       +4.73 dB |       +4.36 dB |

### Frequency calibration

| Method | Result | Reproducibility |
|--------|--------|----------------|
| Self-loop | +7.54 ppm | ±0.01 ppm across 4 trials |
| SDG-driven | +11.79 ppm | ±0.04 ppm across 3 trials |

The 4.25 ppm difference between methods is the SDG TCXO's offset relative
to the MHS counter clock. Without an absolute reference (GPS-disciplined),
neither value is "true"; pick the method that matches what your downstream
equipment uses as its reference.

### Counter behaviour quirks

The MHS-5200A counter has unusual settling behaviour that affects how the
freq-cal works:

* **Gate.S1 (1 s gate):** Reliable only for input ≥ 10 MHz. Below that,
  the counter holds partial-gate intermediate values for many gate windows
  before locking, often missing the lock entirely.
* **Gate.S10 (10 s gate, default):** Reliable from ~10 kHz upward. Each
  measurement takes ~22 s wall time but locks repeatably.
* **Below 10 kHz:** The 1-Hz LSB resolution is too coarse for ppm-scale
  measurements regardless of gate.

The driver's `measure_frequency_hz()` method polls until two consecutive
readings agree to within 0.5 Hz (effectively zero given the LSB), with a
timeout of 60 s. The cal script uses this method.

## Requirements

| Item | Notes |
|------|-------|
| MHS-5200A series unit | Driver auto-detects CH340 / PL2303 USB-serial |
| Siglent SDS2000X Plus oscilloscope | LAN, default 10.1.1.58 (`--scope-host`); needed for amp-cal |
| Siglent SDG1062X | LAN, default 10.1.1.51 (`--sdg-host`); needed only for freq-cal `--method sdg` |
| BNC cables | At least two: MHS ↔ scope, and a short MHS-self-loop or SDG-to-MHS cable |

Software:

```bash
pip install rf-bench-drivers-koolertron rf-bench-drivers-siglent
```

## Notes

* Both calibrations open the MHS with `calibration=False` so the new
  measurement is never biased by any existing cal file.
* The amplitude correction is interpolated linearly in log-frequency
  space. The cal table stores 12 log-spaced points from 1 kHz to 25 MHz;
  outside that range the endpoint correction is held.
* CH1 and CH2 amplitude must be measured separately (one cable, two
  sweeps with a swap between). The single TCXO is shared so freq-cal
  is one number, not per-channel.
