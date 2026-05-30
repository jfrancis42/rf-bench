> ⚠️ **UNTESTED** — This implementation has not been verified against physical hardware.
> Code is complete but has not been bench-tested. Verify behavior before relying on output.

# rf-bench-scope-glitch

**GitHub:** https://github.com/jfrancis42/rf-bench-scope-glitch

Unattended glitch / anomaly trap using the SDS2000X. Configures the scope in single-trigger
mode, waits for each trigger event, and saves every captured waveform to a timestamped `.npz`
file. Optionally sends an SMS alert after N events accumulate. Designed to run overnight.

## Hardware

| Instrument | Role |
|-----------|------|
| Siglent SDS2354X Plus (10.1.1.58) | 500 MHz oscilloscope — single trigger + waveform capture |

## Usage

```
python scope_glitch.py [options]
```

### Options

| Flag | Default | Description |
|------|---------|-------------|
| `--scope HOST` | 10.1.1.58 | Scope IP address |
| `--channel N` | 1 | Scope channel |
| `--threshold V` | 0.0 | Trigger threshold (V) |
| `--above` | default | Rising edge trigger |
| `--below` | — | Falling edge trigger |
| `--duration S` | 0.01 | Capture window (seconds) |
| `--outdir DIR` | glitches | Output directory |
| `--alert N` | off | SMS after every N events |

### Examples

```bash
# Capture supply glitches above 3.5V
python scope_glitch.py --channel 1 --threshold 3.5 --above --outdir supply_glitch/

# Capture undervoltage (falling below 2.8V)
python scope_glitch.py --threshold 2.8 --below --duration 0.05 --outdir undervolt/

# Alert via SMS every 5 events
python scope_glitch.py --threshold 2.5 --above --alert 5 --outdir overnight/
```

## Output files

Each triggered capture is saved as `glitch_YYYYMMDD_HHMMSS_ffffff.npz` in `--outdir`.

### NPZ format

| Array | Contents |
|-------|---------|
| `waveform` | Voltage samples (V) |
| `sample_rate` | Samples per second |
| `timestamp` | Unix timestamp of capture |

## SMS alerts

Requires `~/Dropbox/build/creds/voipms-rest.txt` (3 lines: URL, user, password).
Non-fatal if file is missing or request fails.

## Notes

- The script polls `:TRIG:STAT?` to detect trigger completion. A 30-second timeout
  re-arms if no trigger fires (prevents deadlock on quiet channels).
- Files accumulate in `--outdir`; use `ls | wc -l` to monitor count.
- To replay/plot a saved capture: `np.load('glitch_*.npz')['waveform']`.
