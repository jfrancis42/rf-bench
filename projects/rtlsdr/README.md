# RTL-SDR Projects

RTL-SDR software-defined radio receiver projects for spectrum monitoring, signal
decoding, and satellite operations.

## Projects

| Directory | Description | Status |
|-----------|-------------|--------|
| `adsb/` | ADS-B aircraft tracking at 1090 MHz | ⚠️ Untested |
| `acars/` | ACARS aircraft messaging at 131 MHz | ⚠️ Untested |
| `ais/` | AIS marine tracking at 162 MHz | ⚠️ Untested |
| `aprs/` | APRS packet radio at 144.390 MHz | ⚠️ Untested |
| `classify/` | Signal classifier (AM/FM/FSK/PSK/CW detection) | ⚠️ Untested |
| `drivetest/` | Mobile signal strength logging + GPX tracks | ⚠️ Untested |
| `fm-rds/` | FM broadcast + RDS decoder | ⚠️ Untested |
| `ook-link/` | OOK ASCII link (Flipper Zero TX → RTL-SDR RX) | ⚠️ Untested |
| `recorder/` | Wideband IQ recorder (SigMF format) | ⚠️ Untested |
| `satellite/` | Satellite downlink wideband monitor with Doppler | ⚠️ Untested |
| `survey/` | Power spectrum logger with GPS geo-tagging | ⚠️ Untested |
| `wxsat/` | Weather satellite reception (NOAA APT + Meteor LRPT) | ⚠️ Untested |

All projects require `rf-bench-drivers-rtlsdr`. Install with:
```bash
pip install rf-bench-drivers-rtlsdr
```

## Common RTL-SDR operations

### Find RTL-SDR devices
```python
from rf_bench.rtlsdr import RTLSDR

for dev in RTLSDR.find_devices():
    print(dev)  # {'index': 0, 'serial': '00000001', 'name': '...'}
```

### Capture IQ samples
```python
from rf_bench.rtlsdr import RTLSDR

with RTLSDR() as sdr:
    sdr.set_center_freq(144_390_000)
    sdr.set_sample_rate(2_400_000)
    sdr.set_gain(30)
    iq = sdr.capture_iq(262_144)
    # Process iq (numpy complex64 array)
```

### Stream IQ continuously
```python
from rf_bench.rtlsdr import RTLSDR

with RTLSDR() as sdr:
    sdr.set_center_freq(1_090_000_000)
    sdr.set_sample_rate(2_000_000)
    for block in sdr.stream_iq(block_size=65_536):
        process(block)
        if done:
            break
    sdr.stop_stream()
```

## RTL-SDR hardware notes

**RTL-SDR Blog v4** (recommended):
- R828D tuner, 500 kHz – 1766 MHz
- 2.4 MHz max IQ bandwidth
- 1 PPM TCXO (very stable frequency reference)
- Bias tee (5V, 180 mA) for LNA power
- USB 2.0

**RTL-SDR Blog v3:**
- R820T2 tuner, similar range
- No bias tee (use external injector if LNA needed)

**PPM calibration:** Even the v4's 1 PPM TCXO should be verified against a known
reference (SDG + SSA on a carrier). Measure the actual PPM error and apply it in
the driver via `set_freq_correction(ppm)`.

**Bias tee:** Enable with `sdr.set_bias_tee(True)` to power an inline LNA.
Disable when not needed to protect the LNA if RF input is removed.

## See also

- [rf-bench-drivers-rtlsdr README](../../drivers/rtlsdr/README.md) — Driver API documentation
- [SigMF specification](https://github.com/gnuradio/SigMF) — IQ recording format
- [RTL-SDR Blog](https://www.rtl-sdr.com) — Hardware, tutorials, community projects
