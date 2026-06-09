# rf-bench-drivers-kiwisdr

> **⚠ Untested — written to spec.** This driver implements the KiwiSDR
> WebSocket SND/IQ protocol from the public KiwiSDR source code and
> protocol documentation, but has not been run against physical hardware.
> The code should be correct; expect bring-up issues on the first
> connection. Not published to PyPI until verified — install from this
> repo with `pip install -e drivers/kiwisdr`. Bug reports welcome.

KiwiSDR HF receiver driver for the [rf-bench](https://github.com/jfrancis42/rf-bench)
bench automation framework.

Connects to a [KiwiSDR](https://www.rx-888.com/kiwisdr/) (0–30 MHz HF software-defined
receiver) over its WebSocket SND API and exposes a `capture_iq()` / `stream_iq()` /
`power_spectrum()` interface matching `rf_bench.rtlsdr.RTLSDR`, making it a drop-in
HF backend for any rf-bench project.

## Hardware

The KiwiSDR is a BeagleBone Black cape that digitises 0–30 MHz at 66 MS/s (14-bit ADC),
runs a GPS-disciplined TCXO for frequency accuracy, and serves up to 4–8 simultaneous
receiver channels over a WebSocket API.  It is network-connected (LAN or internet).

Key specs relevant to this driver:
- **Frequency range:** 0–30 MHz (full HF, plus LW/MW)
- **IQ output rate:** 12 000 S/s per channel (fixed by FPGA, not configurable)
- **Instantaneous bandwidth:** ±5 kHz per channel (configurable up to ±6 kHz)
- **Simultaneous channels:** 4 (standard) or 8 (extended build)
- **Calibration:** GPS-disciplined oscillator — no PPM correction needed

## Installation

```bash
pip install rf-bench-drivers-kiwisdr
# or from source:
pip install -e drivers/kiwisdr
```

Dependency: `websocket-client >= 1.6` (installed automatically).

## Quick start

```python
from rf_bench.kiwisdr import KiwiSDR

# Single channel
with KiwiSDR("192.168.1.100") as kiwi:
    kiwi.set_center_freq(14_074_000)          # 20m FT8
    iq = kiwi.capture_iq(12_000)             # 1 second at 12 kHz
    freq_hz, power_db = kiwi.power_spectrum(iq, rbw_hz=50)

# Multiple simultaneous channels on one device
ch0 = KiwiSDR("192.168.1.100", channel=0)
ch1 = KiwiSDR("192.168.1.100", channel=1)
ch0.set_center_freq(14_074_000)              # 20m
ch1.set_center_freq(7_074_000)               # 40m
import threading
t0 = threading.Thread(target=lambda: process(ch0.capture_iq(12_000)))
t1 = threading.Thread(target=lambda: process(ch1.capture_iq(12_000)))

# Password-protected server
kiwi = KiwiSDR("192.168.1.100", password="secret")

# Sweep a band
signals = kiwi.scan_band(
    start_hz=3_500_000,
    stop_hz=4_000_000,
    step_hz=10_000,
    threshold_db=-20,
)
for s in signals:
    print(f"{s['freq_hz']/1e6:.3f} MHz  {s['power_db']:+.1f} dB")

# Continuous stream (1-second blocks)
kiwi.set_center_freq(14_025_000)             # 20m CW
for block in kiwi.stream_iq(block_size=12_000):
    process(block)
    if done:
        break
kiwi.stop_stream()
```

## Key differences from rf_bench.rtlsdr.RTLSDR

| Feature | RTL-SDR | KiwiSDR |
|---------|---------|---------|
| Sample rate | 250 kS/s – 3.2 MS/s | **12 kS/s fixed** |
| Instantaneous BW | 2.4 MHz | **±5 kHz (10 kHz)** |
| Frequency | 24 MHz – 1766 MHz | **0 – 30 MHz** |
| Connection | USB | **WebSocket / LAN** |
| Simultaneous Rx | 1 per device | **4–8 per device** |
| Frequency accuracy | PPM calibration file | **GPS-disciplined (no cal needed)** |

`set_sample_rate()` raises `KiwiSDRError` if called with any value other than 12000.
`set_gain()` maps to the AGC threshold (approximate; not the same as RTL-SDR dB gain steps).

## API reference

### `KiwiSDR(host, port=8073, password="", channel=0, passband_hz=5000, timeout=10.0)`

Open a connection.  Raises `KiwiSDRBusyError` if no channels are free.

### Tuning
- `set_center_freq(freq_hz)` — tune 0–30 MHz
- `set_passband(lo_hz, hi_hz)` — asymmetric passband (e.g. `-3000, 0` for LSB)
- `set_gain(gain_db)` — AGC threshold adjustment; 0 or `'auto'` for normal AGC

### Capture
- `capture_iq(num_samples=4096) → np.ndarray[complex64]`
- `stream_iq(block_size=4096) → Generator[np.ndarray]`
- `stop_stream()`

### Analysis
- `power_spectrum(iq, rbw_hz=100) → (freq_hz, power_db)`
- `scan_activity(threshold_db=-20, num_samples=4096) → list[dict]`
- `scan_band(start_hz, stop_hz, step_hz=10000, ...) → list[dict]`

### Info / lifecycle
- `identify() → dict`
- `close()`
- Context manager (`with KiwiSDR(...) as kiwi:`)

## Protocol

The driver implements the KiwiSDR WebSocket SND protocol directly using
`websocket-client`.  Binary SND frames contain interleaved int16 big-endian
I/Q pairs normalised to ±1.0.  See the source and
[kiwiclient](https://github.com/jks-prv/kiwiclient) for full protocol details.

## License

GPL-3.0-or-later
