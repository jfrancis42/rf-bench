# siglent-clock-jitter

Clock jitter measurement and PLL lock-time capture using the MSO digital channels of
the Siglent SDS2000X Plus oscilloscope.

- **jitter mode:** Captures a clock signal, extracts all rising-edge intervals, and
  produces a jitter histogram (RMS and peak-to-peak in picoseconds).
- **pll-lock mode:** Measures the time from a frequency-change write strobe to the
  first assertion of a PLL LOCK_DETECT signal. Optionally captures the VCO tuning
  voltage on an analog channel.

> **MSO hardware note:** All MSO digital channel code is based on the Siglent SDS Series
> SCPI guide. The MSO probe pod has **not** been physically tested. Requires the MSO
> option license on the oscilloscope and the digital probe pod physically connected.

## Hardware required

- Siglent SDS2504X Plus with MSO option (LAN, `10.1.1.58`)
- MSO digital probe pod (connects to rear-panel Digital port)
- For PLL lock mode with VCO monitoring: analog BNC probe on an analog channel

## Probe connections

**Jitter mode:** Connect the clock signal to any MSO digital channel (default D0).

**PLL lock mode:**

| Ch | Signal |
|----|--------|
| D0 (default `--lock-ch`) | LOCK_DETECT output of PLL IC |
| D1 (default `--write-ch`) | LE (latch enable / write strobe) — active-high pulse |
| C1 (optional `--vco-analog-ch`) | VCO tuning voltage (analog) |

## Usage

```bash
# Jitter measurement — D0 = clock signal, 10 ms capture
python clock_jitter.py --mode jitter --clock-ch 0

# With expected frequency check (warns if measured frequency differs)
python clock_jitter.py --mode jitter --clock-ch 0 --expected-freq-hz 16e6

# Longer capture for better statistics (more cycles)
python clock_jitter.py --mode jitter --clock-ch 2 --duration-s 0.05

# PLL lock time — D0 = LOCK_DETECT, D1 = LE write strobe
python clock_jitter.py --mode pll-lock --lock-ch 0 --write-ch 1

# PLL lock with VCO tuning voltage on scope CH1
python clock_jitter.py --mode pll-lock --lock-ch 0 --write-ch 1 --vco-analog-ch 1

# PLL lock — digital only, no analog channel
python clock_jitter.py --mode pll-lock --lock-ch 0 --write-ch 1 --vco-analog-ch -1

# Set threshold for 5 V TTL logic
python clock_jitter.py --mode jitter --threshold ttl
```

## Output files

### Jitter mode

| File | Contents |
|------|----------|
| `<prefix>_jitter.csv` | cycle_number, period_ns, jitter_ps (deviation from mean) |
| `<prefix>_jitter.png` | Top: jitter histogram + optional Gaussian fit. Bottom: period vs. cycle number |
| `<prefix>_jitter.txt` | Summary: clock frequency, mean period, RMS jitter, pk-pk jitter, cycle count |

### PLL lock mode

| File | Contents |
|------|----------|
| `<prefix>_pll.png` | Top: VCO tuning voltage settling (if captured). Bottom: digital channels with write-strobe and lock-detect timing markers |
| `<prefix>_pll.txt` | Lock time (µs), write strobe timestamp, lock detect timestamp, VCO swing |

## Interpreting jitter results

- **RMS jitter** is the 1σ standard deviation of the period distribution
- **Gaussian fit σ vs raw std:** close agreement → Gaussian (thermal) jitter; large
  divergence → structured jitter (spurs, modulation, crosstalk)
- Typical crystal oscillators: < 100 ps RMS; spread-spectrum clocks: 1–10 ns RMS

## Notes

- scipy is optional — Gaussian fit is skipped if unavailable, but histogram and
  statistics are still generated
- Minimum useful capture: at least 3 rising edges (e.g., 10 ms at 1 kHz clock)
- For 100 MHz+ clocks ensure the scope's digital sample rate is high enough to
  resolve individual cycles

## Dependencies

```
rf-bench >= 0.2.0
numpy >= 1.20
matplotlib >= 3.4
scipy >= 1.7   (optional — Gaussian fit; graceful fallback if absent)
```
