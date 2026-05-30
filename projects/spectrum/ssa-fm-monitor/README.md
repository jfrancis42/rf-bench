> ⚠️ **UNTESTED** — This implementation has not been verified against physical hardware.
> Code is complete but has not been bench-tested. Verify behavior before relying on output.

# rf-bench-ssa-fm-monitor

**GitHub:** https://github.com/jfrancis42/rf-bench-ssa-fm-monitor

FM broadcast band (87.5–108 MHz) monitor using the SSA3032X Plus. Sweeps continuously,
detects station carriers as peaks above threshold, logs frequency/power vs. time to `.npz`,
and generates a waterfall image. Optionally sends an SMS alert when a new carrier appears
on a previously empty channel.

## Hardware

| Instrument | Role |
|-----------|------|
| Siglent SSA3032X Plus (10.1.1.60) | Spectrum analyzer — 87.5–108 MHz sweep |

Connect a broadband or FM antenna to the SSA RF input.

## Usage

```
python ssa_fm_monitor.py [options]
```

### Options

| Flag | Default | Description |
|------|---------|-------------|
| `--ssa HOST` | 10.1.1.60 | SSA IP address |
| `--duration S` | 3600 | Run duration (seconds) |
| `--threshold DBM` | -70 | Peak detection threshold |
| `--interval S` | 5 | Sweep interval (seconds) |
| `--alert` | off | SMS when new carrier appears |
| `--outdir DIR` | current dir | Output directory |
| `--plot FILE.npz` | — | Offline waterfall regeneration |

### Examples

```bash
# 1-hour FM monitor
python ssa_fm_monitor.py --duration 3600

# Sensitive monitoring with alerts
python ssa_fm_monitor.py --threshold -65 --interval 10 --alert

# Regenerate waterfall from saved data
python ssa_fm_monitor.py --plot fm_monitor_20260527_120000.npz
```

## Output files

| File | Description |
|------|-------------|
| `fm_monitor_{ts}.npz` | Time × frequency data |
| `fm_monitor_{ts}_waterfall.png` | Inferno colormap waterfall |

## NPZ format

Arrays: `times` (Unix timestamps), `traces` (dBm, N×751), `freqs` (Hz), `metadata` (JSON).

## Peak detection

Uses `scipy.signal.find_peaks` with 150 kHz minimum separation (slightly under the
200 kHz US FM channel spacing). Only peaks above `--threshold` are reported.

## SMS alerts

Requires `~/Dropbox/build/creds/voipms-rest.txt` (3 lines: URL, user, password).
Alert fires once per new channel (rounded to 0.1 MHz grid) per session.
