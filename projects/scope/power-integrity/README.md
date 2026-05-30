# siglent-power-integrity

Mixed-signal power integrity analyzer. Captures MSO digital switching activity and an
analog power supply rail simultaneously on a shared timebase, then correlates digital
transitions with supply voltage glitches to identify which signals are causing noise.

> **MSO hardware note:** All MSO digital channel code is based on the Siglent SDS Series
> SCPI guide. The MSO probe pod has **not** been physically tested. Requires the MSO
> option license on the oscilloscope and the digital probe pod physically connected.

## Hardware required

- Siglent SDS2504X Plus with MSO option (LAN, `10.1.1.58`)
- MSO digital probe pod (connects to rear-panel Digital port)
- Probe or BNC cable to monitor the power supply rail

## Cable setup

```
Scope analog CH1 ─── power rail (+)   (×1 probe, AC or DC coupled)
Scope GND        ─── power rail GND

MSO pod D0–D7   ─── digital switching signals (bus lines, SPI clock, GPIO, etc.)
```

Both the analog and digital channels are frozen at the same trigger event, so their
time axes are aligned without any additional synchronization.

## Usage

```bash
# Default: CH1 = supply rail, D0–D3 = digital channels, 10 ms window
python power_integrity.py

# Custom channel set and longer window
python power_integrity.py --digital-channels 0,1,2,3 --analog-channel 1 --duration-s 0.05

# Finer analog resolution (50 mV/div for low-noise rail)
python power_integrity.py --vdiv 0.05

# Print statistics per capture
python power_integrity.py --stats

# Continuous mode (re-captures every 2 s until Ctrl-C)
python power_integrity.py --continuous

# Trigger on rising edge of D0 (for reproducible captures)
python power_integrity.py --trigger-on-edge 0

# Second analog channel (for comparing two rails)
python power_integrity.py --analog-channel2 2
```

## Output files

| File | Contents |
|------|----------|
| `<prefix>_pi.png` | Multi-panel: supply voltage deviation (mV) + per-channel digital step-plots |
| `<prefix>_pi.csv` | Aligned columns: time_s, analog_v, D0, D1, D2, … (digital resampled to analog time grid) |
| `<prefix>_pi.txt` | Summary: supply Vpp, AC RMS, worst glitch; switching rate and duty cycle per digital channel |

## Statistics reported

**Power rail:**
- Mean (DC setpoint), Vpp (total noise), AC RMS (standard deviation), worst single-sample glitch

**Digital channels:**
- Edge count, switching rate (Hz), duty cycle (%)

## Notes

- The supply deviation plot shows millivolt deviation from the mean — this makes
  small ripple visible even on a 3.3 V or 5 V rail
- `--continuous` mode writes a new set of output files per capture (numbered suffix)
- `--trigger-on-edge` is noted in the CLI but edge-triggered capture is not yet
  fully implemented; the scope runs in auto-trigger mode

## Dependencies

```
rf-bench >= 0.2.0
numpy >= 1.20
matplotlib >= 3.4
```
