# rf-bench-drivers-sunsdr

> **⚠ Untested — written to spec.** This driver implements the ExpertSDR3
> TCI 2.0 protocol from the public TCI specification, but has not been
> run against physical SunSDR2 Pro hardware. The code should be correct;
> expect bring-up issues on the first connection — particularly around
> binary IQ frame headers, which the spec leaves slightly ambiguous. Not
> published to PyPI until verified — install from this repo with
> `pip install -e drivers/sunsdr`. Bug reports welcome.

SunSDR2 Pro / ExpertSDR3 TCI driver for the
[rf-bench](https://github.com/jfrancis42/rf-bench) bench automation framework.

The most capable driver in the rf-bench collection: combines radio control
(frequency, mode, PTT, filter — like `rf_bench.icom`) with wide-bandwidth IQ
streaming (like `rf_bench.rtlsdr`), plus TX IQ injection and dual simultaneous
receivers.

## Hardware

[SunSDR2 Pro](https://eesdr.com/) by Expert Electronics.
Connected via Ethernet to ExpertSDR3 (version 3.x) running on a local PC.
TCI (Transceiver Control Interface) WebSocket API, default port 50001.

Frequency coverage:
- **0.1 – 55 MHz** — HF + 6m (RX + TX)
- **100 – 150 MHz** — VHF, covers 2m (RX only)

IQ output rates and instantaneous bandwidth:
| Rate | Bandwidth |
|------|-----------|
| 48 000 S/s | ±24 kHz |
| 96 000 S/s | ±48 kHz |
| 192 000 S/s | **±96 kHz** |

At 192 kHz, a single capture covers the entire 40m CW band (40 kHz wide) in one shot.

## Prerequisites

ExpertSDR3 must be running with TCI enabled:
**Settings → TCI → Enable** (port 50001 by default).

The driver connects to ExpertSDR3 over your LAN — the SunSDR2 Pro itself is
only accessible through ExpertSDR3 (not directly over the network).

## Installation

```bash
pip install rf-bench-drivers-sunsdr
# or from source:
pip install -e drivers/sunsdr
```

Dependency: `websocket-client >= 1.6` (installed automatically).

## Quick start

```python
from rf_bench.sunsdr import SunSDR

# Basic receive
with SunSDR("192.168.1.100") as sdr:
    sdr.set_frequency(14_074_000)       # 20m FT8
    sdr.set_mode("USB")
    sdr.set_sample_rate(192_000)        # ±96 kHz bandwidth
    iq = sdr.capture_iq(192_000)        # 1 second
    freq_hz, power_db = sdr.power_spectrum(iq, rbw_hz=500)

# Dual simultaneous receivers (two independent WebSocket connections)
rx0 = SunSDR("192.168.1.100", trx=0)
rx1 = SunSDR("192.168.1.100", trx=1)
rx0.set_frequency(14_074_000)          # 20m FT8
rx1.set_frequency(144_174_000)         # 2m FT8 (VHF port)

# Band sweep — at 192 kHz rate, 100 kHz steps cover 40m in 3 captures
hits = sdr.scan_band(7_000_000, 7_300_000, step_hz=100_000)

# Continuous stream
for block in sdr.stream_iq(192_000):   # 1-second blocks
    process(block)
sdr.stop_stream()

# TX IQ (requires valid licence + antenna/dummy load)
sdr.set_ptt(True)
sdr.transmit_iq(tx_samples)            # complex64, matches sample_rate
sdr.set_ptt(False)

# Signal strength (dBFS, relative)
strength = sdr.get_strength()
```

## API reference

### `SunSDR(host, port=50001, trx=0, iq_rate=48000, iq_header_len=4, timeout=10.0)`

Opens a WebSocket connection.  Raises `SunSDRConnectionError` if ExpertSDR3
is unreachable.

### Radio control
| Method | Description |
|--------|-------------|
| `set_frequency(hz)` | Set RX (+ TX if in HF range) frequency |
| `get_frequency() → int` | Current RX frequency from state cache |
| `set_tx_frequency(hz)` | Set TX frequency independently (split) |
| `set_mode(mode)` | USB / LSB / CW / CWR / AM / SAM / DSB / NFM / WFM / DIGU / DIGL |
| `get_mode() → str` | Current mode |
| `set_rx_filter(lo_hz, hi_hz)` | Passband relative to carrier |
| `set_volume(0–100)` | Audio output volume |
| `set_squelch(enable, threshold_dbfs)` | Squelch control |
| `set_rf_gain(db)` | Preamp / attenuation (best-effort) |
| `set_ptt(bool)` | PTT on/off ⚠ |
| `set_tune(bool)` | Tune tone on/off |
| `get_strength() → float` | Signal strength in dBFS |
| `get_strength_settled(settle_s) → float` | Strength after settle delay |

### IQ streaming
| Method | Description |
|--------|-------------|
| `set_sample_rate(rate)` | 48000 / 96000 / 192000 S/s |
| `capture_iq(n) → complex64` | Synchronous block capture |
| `stream_iq(block_size)` | Generator of complex64 blocks |
| `stop_stream()` | Stop active stream |
| `power_spectrum(iq, rbw_hz) → (freq_hz, pwr_db)` | Welch PSD |
| `scan_activity(threshold_db, n) → list[dict]` | Detect signals in passband |
| `scan_band(start, stop, step, ...) → list[dict]` | Sweep and detect |

### TX
| Method | Description |
|--------|-------------|
| `transmit_iq(iq)` | Inject complex64 TX samples ⚠ |

### Info / lifecycle
| Method | Description |
|--------|-------------|
| `identify() → dict` | Connection + state snapshot |
| `send_raw(cmd)` | Send arbitrary TCI command string |
| `close()` | Stop streams, PTT off, close WebSocket |
| Context manager | `with SunSDR(...) as sdr:` |

## Protocol

Implements TCI (Transceiver Control Interface) v1.5+ via `websocket-client`.
Text commands: `command:arg1:arg2;`.
Binary IQ frames: `uint16 TRX + uint16 stream_type + float32 LE I/Q pairs`.
If IQ capture returns garbage, adjust `iq_header_len=` (try 0 or 8).

Reference: ExpertSDR3 built-in TCI documentation,
[community TCI spec](https://github.com/maksimus1210/tci).

## License

GPL-3.0-or-later
