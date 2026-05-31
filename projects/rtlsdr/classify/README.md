
# rf-bench-rtlsdr-classify

**GitHub:** https://github.com/jfrancis42/rf-bench-rtlsdr-classify

Protocol hunter and signal classifier: scans a frequency range, captures IQ
bursts from detected signals, and classifies each by modulation type.
Optionally commands the SSA to lock on and measure any signal of interest.

The RTL-SDR finds signals quickly across a wide range; the SSA measures them
accurately.  Together they extend the EMI finder (#16) workflow.

## Hardware

| Component | Role |
|-----------|------|
| RTL-SDR Blog v4 | Signal detection and classification |
| SSA3032X Plus (optional) | Precision amplitude and harmonic measurement |

## Modulation classes

| Class | Detection method |
|-------|-----------------|
| `AM/OOK` | High amplitude variance, low frequency variance |
| `FM` / `NFM` | Constant envelope, high instantaneous frequency variance |
| `FSK` | Constant envelope, bimodal instantaneous frequency histogram |
| `PSK` | Constant envelope, discrete phase steps |
| `CW/carrier` | Very low amplitude and frequency variance |
| `pulsed` | Low duty cycle, impulsive amplitude (radar, transponder) |

## Usage

```
python classify.py --freq HZ [options]
python classify.py --scan START_HZ STOP_HZ [options]
```

| Flag | Default | Description |
|------|---------|-------------|
| `--freq HZ` | — | Single-channel monitor (e.g. `433.92e6`) |
| `--bw HZ` | 2.4e6 | Sample rate / bandwidth |
| `--gain DB` | auto | Gain in dB or `auto` |
| `--threshold DB` | -20 | dB above noise floor to trigger |
| `--scan START STOP` | — | Frequency range scan in Hz |
| `--step HZ` | 2e6 | Step size for range scan |
| `--ssa HOST` | — | SSA IP; lock on each detected signal |
| `--dwell S` | 1.0 | Monitor seconds per frequency step |
| `--json` | — | Output as JSON lines (machine-readable) |
| `--serial S` | first | RTL-SDR serial number |

### Examples

```bash
# Monitor 433 MHz ISM band
python classify.py --freq 433.92e6 --bw 2.4e6

# Monitor with SSA handoff for strong signals
python classify.py --freq 433.92e6 --ssa 10.1.1.60 --threshold -15

# Coarse survey 300–1000 MHz
python classify.py --scan 300e6 1000e6 --step 2e6

# JSON output for logging
python classify.py --freq 433.92e6 --json >> signals.jsonl
```

### Example output

```
[14:23:01] 433.9200 MHz  AM/OOK       conf=0.85  bw=50 kHz  am_idx=0.42 freq_std=0.0012
[14:23:03] 433.9500 MHz  FSK          conf=0.75  bw=25 kHz  freq_modes=2
[14:23:05] 434.1500 MHz  CW/carrier   conf=0.90  bw=5 kHz   unmodulated carrier
  → SSA locked on 434.150 MHz  span=2.0 MHz
```

## Python dependencies

```
pip install rf-bench-drivers-rtlsdr numpy
```
