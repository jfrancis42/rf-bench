> ⚠️ **UNTESTED** — This implementation has not been verified against physical hardware.
> Code is complete but has not been bench-tested. Verify behavior before relying on output.

# rf-bench-rtlsdr-recorder

**GitHub:** https://github.com/jfrancis42/rf-bench-rtlsdr-recorder

Wideband IQ recorder: saves any 2.4 MHz slice of spectrum as a SigMF archive
(`.sigmf-meta` + `.sigmf-data`) for offline demodulation and analysis.

SigMF is compatible with GNU Radio, SDR++, inspectrum, and most SDR software.
A capture made today can be demodulated with a decoder that doesn't exist yet.

## Hardware

Any RTL-SDR dongle.

## Usage

```
python recorder.py --freq HZ [options]
```

| Flag | Default | Description |
|------|---------|-------------|
| `--freq HZ` | required | Center frequency (e.g. `433.92e6`) |
| `--bw HZ` | 2.4e6 | Sample rate / IQ bandwidth |
| `--gain DB` | auto | Gain in dB or `auto` |
| `--duration S` | 60 | Capture length in seconds |
| `--start ISO8601` | now | Scheduled start (UTC) |
| `--trigger DB` | — | Threshold-trigger: N dB above noise |
| `--hold S` | 2.0 | Threshold hold time |
| `--rotate S` | — | Rotating buffer: keep last N seconds |
| `--outdir DIR` | `.` | Output directory |
| `--prefix TEXT` | recording | Output filename prefix |
| `--int8` | — | Save as complex int8 (4× smaller, slight quality loss) |
| `--bias-tee` | — | Enable RTL-SDR Blog bias tee |
| `--serial S` | first | RTL-SDR serial number |
| `--info FILE` | — | Print metadata from a `.sigmf-meta` file |

### Examples

```bash
# 60-second capture at 433 MHz
python recorder.py --freq 433.92e6 --duration 60

# Scheduled capture for a NOAA 19 weather satellite pass
python recorder.py --freq 137.1e6 --start "2026-05-28T21:14:00Z" --dur 600

# Threshold-triggered: record only when a signal appears
python recorder.py --freq 433.92e6 --trigger -20 --hold 3

# Rotating 5-minute buffer (Ctrl-C saves the last 5 minutes)
python recorder.py --freq 144.39e6 --rotate 300

# Inspect a saved capture
python recorder.py --info recording_20260528_120000.sigmf-meta
```

## Storage

| Format | Rate | 10-min size |
|--------|------|-------------|
| complex64 (default) | 19.2 MB/s | ~11 GB |
| complex int8 (`--int8`) | 4.8 MB/s | ~2.9 GB |

## SigMF format

Each capture produces two files:
- `{prefix}_{timestamp}.sigmf-meta` — JSON metadata (frequency, sample rate, hardware, datetime)
- `{prefix}_{timestamp}.sigmf-data` — raw binary IQ samples

## Python dependencies

```
pip install rf-bench-drivers-rtlsdr numpy sigmf
```
