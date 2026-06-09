# KiwiSDR Projects

HF receiver automation projects using the
[`rf_bench.kiwisdr`](../../drivers/kiwisdr/) driver.

## Hardware

**KiwiSDR** — BeagleBone Black SDR cape.  0–30 MHz, 14-bit ADC, GPS-disciplined
oscillator, up to 4–8 simultaneous receiver channels over WebSocket.
Driver: `rf-bench-drivers-kiwisdr` (see `drivers/kiwisdr/`).

All projects connect to the KiwiSDR via `--host` (default `kiwisdr.local`).

## Projects

| Directory | Script | What it does |
|-----------|--------|-------------|
| `hf-monitor/` | `hf_monitor.py` | HF band activity scanner — sweeps amateur bands, logs signals, rolling display |
| `propagation/` | `propagation_logger.py` | Noise floor + S/N logger at fixed frequencies for propagation tracking |
| `swbc/` | `swbc_scanner.py` | Shortwave broadcast band scanner — detects AM carriers across SW bands |
| `wwv/` | `wwv_monitor.py` | Multi-channel WWV/WWVH monitor — tracks S/N on all time-signal frequencies |
| `cw-skimmer/` | `cw_skimmer.py` | CW band scanner — detects CW activity in amateur CW sub-bands |
| `digital-monitor/` | `digital_monitor.py` | FT8/FT4/JS8/WSPR monitor — detects activity, records IQ to SigMF |
| `band-opening/` | `band_opening.py` | NCDXF beacon monitor — detects band openings, writes alerts for other tools |
| `full-spectrum/` | `full_spectrum.py` | Combined HF+VHF/UHF scanner using KiwiSDR + RTL-SDR simultaneously |
| `panadapter/` | `panadapter.py` | IC-7300 panadapter — follows radio frequency, displays live ASCII waterfall |
| `noise-figure/` | `noise_figure.py` | Y-factor NF measurement using KiwiSDR as the measurement receiver |

## Quick start

```bash
pip install rf-bench-drivers-kiwisdr   # or: pip install -e drivers/kiwisdr

# Scan 40m and 20m
python projects/kiwisdr/hf-monitor/hf_monitor.py --host 192.168.1.100 --bands 40m,20m

# Monitor WWV on all frequencies
python projects/kiwisdr/wwv/wwv_monitor.py --host 192.168.1.100

# Detect 10m band openings
python projects/kiwisdr/band-opening/band_opening.py --host 192.168.1.100

# Combined HF+VHF scan (requires RTL-SDR too)
python projects/kiwisdr/full-spectrum/full_spectrum.py --kiwi-host 192.168.1.100
```

## Key constraints

- KiwiSDR IQ sample rate is **fixed at 12 kHz** — set `SAMPLE_RATE = 12_000`
  in any project using this driver.
- Instantaneous bandwidth: **±5 kHz** (10 kHz) per channel.
- Coverage: **0–30 MHz only** (no VHF/UHF).
- Each `KiwiSDR()` instance opens one WebSocket connection and uses one receiver
  slot.  Standard KiwiSDRs support 4 slots; extended builds support 8.
