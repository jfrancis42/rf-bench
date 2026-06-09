> 🔶 **Mostly tested** — IQ capture and streaming verified working.
> Device enumeration by serial number and some edge cases may need verification.

# rf-bench-drivers-rtlsdr

RTL-SDR receiver driver for the [rf-bench](https://github.com/jfrancis42/rf-bench)
bench automation suite.  Wraps [pyrtlsdr](https://github.com/roger-/pyrtlsdr)
(librtlsdr) with PPM calibration, consistent import patterns, workflow helpers,
and a thread-safe streaming generator.

**Supported hardware:**
- RTL-SDR Blog v4 (R828D tuner, 1 PPM TCXO, bias tee) — recommended
- RTL-SDR Blog v3 (R820T2 tuner, bias tee)
- Generic RTL2832U-based DVB-T dongles (no TCXO — calibrate PPM before use)

---

## Installation

```bash
pip install rf-bench-drivers-rtlsdr
# or, for the full rf-bench suite:
pip install rf-bench
```

**System dependency:** librtlsdr must be installed.

```bash
# Arch Linux
pacman -S rtl-sdr

# Debian / Ubuntu
apt install rtl-sdr librtlsdr-dev

# macOS
brew install librtlsdr
```

**Linux udev rule** (required to access the device as a non-root user):

```
SUBSYSTEM=="usb", ATTRS{idVendor}=="0bda", ATTRS{idProduct}=="2838", \
    MODE="0664", GROUP="plugdev"
```

Save to `/etc/udev/rules.d/99-rtlsdr.rules`, then `udevadm control --reload-rules`
and re-plug the dongle.

---

## Quick start

```python
from rf_bench.rtlsdr import RTLSDR

# Basic capture
with RTLSDR() as sdr:
    sdr.set_center_freq(144_390_000)   # 144.390 MHz — APRS
    sdr.set_sample_rate(2_400_000)
    sdr.set_gain(30)
    iq = sdr.capture_iq(262_144)
    print(f"Captured {len(iq)} samples, dtype={iq.dtype}")

# Power spectrum
with RTLSDR() as sdr:
    sdr.set_center_freq(433_920_000)
    sdr.set_sample_rate(2_400_000)
    iq = sdr.capture_iq(262_144)
    freq_hz, power_db = sdr.power_spectrum(iq, rbw_hz=1000)
    peak_idx = power_db.argmax()
    print(f"Strongest signal: {freq_hz[peak_idx]/1e6:.3f} MHz  ({power_db[peak_idx]:.1f} dB)")

# Streaming (ADS-B example)
with RTLSDR() as sdr:
    sdr.set_center_freq(1_090_000_000)
    sdr.set_sample_rate(2_000_000)
    sdr.set_gain(40)
    for block in sdr.stream_iq(block_size=65_536):
        process_modes_s(block)
        if should_stop:
            break
    sdr.stop_stream()
```

---

## PPM calibration

The RTL-SDR v4 TCXO is nominally 1 PPM, but the actual offset should be
measured against a known reference for best frequency accuracy:

1. Connect the RTL-SDR to a signal of known frequency (e.g. the SDG1062X set
   to 10.000000 MHz, verified on the SSA).
2. Tune the RTL-SDR to the same frequency.
3. Compute the offset: `ppm = (measured_hz - nominal_hz) / nominal_hz * 1e6`
4. Save it:

```python
with RTLSDR() as sdr:
    sdr.save_calibration(ppm=0.8)    # adjust to your measured value
```

The correction is stored in `~/.rtlsdr_cal.json` and loaded automatically on
every subsequent `RTLSDR()` construction.  Pass `ppm_correction=0` explicitly
to override.

---

## Bias tee (RTL-SDR Blog v3/v4)

The bias tee supplies 5 V (~180 mA) on the SMA centre pin to power an inline
LNA.  Requires librtlsdr >= 2.0.0 (included in the Arch `rtl-sdr` package):

```python
with RTLSDR() as sdr:
    sdr.set_bias_tee(True)    # power the LNA
    sdr.set_center_freq(137_620_000)
    sdr.set_sample_rate(2_400_000)
    iq = sdr.capture_iq(2_400_000 * 10)   # 10 s capture
    sdr.set_bias_tee(False)   # disable before disconnecting the LNA
```

Always disable the bias tee before removing the antenna or LNA to avoid
back-feeding the RTL-SDR input with the bias voltage.

---

## Device enumeration

If multiple dongles are attached, select by serial number for reproducibility:

```python
# List all attached devices
for dev in RTLSDR.find_devices():
    print(dev)
# {'index': 0, 'serial': '00000001', 'name': 'Generic RTL2832U OEM'}

# Connect to a specific dongle
with RTLSDR(serial="00000001") as sdr:
    print(sdr.identify())
```

Set a permanent serial number with `rtl_eeprom -s 00000001` (from the
`rtl-sdr` package).

---

## API reference

### `RTLSDR(serial=None, device_index=0, ppm_correction=None, sample_rate=2_400_000, gain='auto')`

Opens the device.  Raises `RTLSDRError` if the serial is not found.
Raises `RTLSDRBusyError` if another process already has the device open.

| Method | Description |
|--------|-------------|
| `find_devices()` | Class method — list attached devices as `[{'index', 'serial', 'name'}]` |
| `identify()` | Return device info dict: serial, tuner_type, valid_gains_db, sample_rate, center_freq, gain, ppm_correction |
| `set_center_freq(freq_hz)` | Set tuning frequency; PPM correction applied automatically |
| `set_sample_rate(rate)` | Set IQ sample rate in S/s (typical: 250_000 – 3_200_000) |
| `set_gain(gain_db)` | Set gain in dB (snapped to nearest valid step) or `'auto'` |
| `set_bias_tee(enabled)` | Enable/disable bias tee (RTL-SDR Blog v3/v4 only) |
| `capture_iq(num_samples)` | Capture a block; returns complex64 numpy array |
| `power_spectrum(iq, rbw_hz)` | Welch PSD; returns `(freq_hz, power_db)` float32 arrays |
| `scan_activity(threshold_db, num_samples)` | Quick scan; returns list of detected signals |
| `stream_iq(block_size)` | Generator yielding complex64 blocks; call `stop_stream()` when done |
| `stop_stream()` | Stop streaming and join the reader thread |
| `save_calibration(ppm)` | Save PPM correction to `~/.rtlsdr_cal.json` |
| `close()` | Stop streaming and close device |

### Valid sample rates

The RTL2832U supports a continuous range from ~250 kS/s to 3.2 MS/s.
Values outside 900 kS/s – 3.2 MS/s may have increased sample loss on some
systems.  Common choices:

| Rate | Bandwidth | Typical use |
|------|-----------|-------------|
| 250_000 | 200 kHz | Narrow-band FM, single ISM channel |
| 1_024_000 | ~800 kHz | ACARS, P25 channel bank |
| 2_000_000 | ~1.6 MHz | ADS-B (1090 MHz) |
| 2_048_000 | ~1.6 MHz | DVB-T, general use |
| 2_400_000 | ~2.0 MHz | Weather satellites, wideband ISM |
| 3_200_000 | ~2.6 MHz | Maximum reliable rate |

### Power spectrum note

`power_spectrum()` returns power values relative to the peak bin (0 dB = peak).
The values are **not calibrated absolute dBm** — the RTL-SDR has no calibrated
power reference.  Use the SSA3032X Plus for absolute amplitude measurements;
use the RTL-SDR for signal detection, classification, and protocol decode where
relative power and frequency are sufficient.

---

## Hardware connection notes

The RTL-SDR Blog v4 appears as a single USB device (RTL2832U, USB VID 0x0bda PID 0x2838
or variant).  Only one process may open it at a time; `RTLSDR()` raises
`RTLSDRBusyError` if it is already in use.

For ADS-B (1090 MHz), a dedicated 1090 MHz bandpass filter (FA 1090 MHz or similar)
before the LNA significantly reduces out-of-band noise and improves decode rate.

For weather satellites (137 MHz), a V-dipole antenna (~54 cm elements, 120° spread)
is optimal — omnidirectional in elevation, no tracking required for LEO passes.

---

## License

GPL-3.0-or-later
