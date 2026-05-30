# siglent-emi-finder

Identifies EMI emission sources by correlating spectrum analyzer peaks with digital clock
harmonics. The SSA3032X Plus sweeps the band and finds emission peaks; the SDS2504X Plus
MSO captures all active clocks simultaneously; the tool reports which clock harmonic
matches each peak.

> **MSO hardware note:** All MSO digital channel code is based on the Siglent SDS Series
> SCPI guide. The MSO probe pod has **not** been physically tested. Use `--ssa-only` for
> a spectrum survey without needing the MSO probe pod.

## Hardware required

- Siglent SSA3032X Plus spectrum analyzer (LAN, `10.1.1.60`) — for spectrum sweep
- Siglent SDS2504X Plus with MSO option (LAN, `10.1.1.58`) — for clock measurement
- MSO digital probe pod (connects to scope rear-panel Digital port)
- Near-field H/E probe or antenna connected to SSA input

## Probe connections

- SSA input ← near-field probe placed near DUT (or antenna for radiated EMI)
- MSO pod D0–D7 ← clock signals from DUT (CPU oscillator, SPI clock, MCU GPIO, etc.)

## Usage

```bash
# Full scan: SSA 100 kHz – 500 MHz + MSO D0–D7
python emi_finder.py

# SSA reconnaissance only (no MSO hardware needed)
python emi_finder.py --ssa-only

# MSO clock measurement only (no SSA)
python emi_finder.py --mso-only

# Custom frequency range
python emi_finder.py --ssa-start-khz 1000 --ssa-stop-khz 200000

# Monitor specific digital channels
python emi_finder.py --digital-channels 0,1,2,3

# Tighten correlation tolerance (for TCXO/VCXO clocks with low drift)
python emi_finder.py --harmonic-tol-ppm 200

# Lower noise floor to catch weaker emissions
python emi_finder.py --noise-floor -70

# Extend harmonic search range (check up to 30th harmonic)
python emi_finder.py --harmonic-max 30
```

## Output files

| File | Contents |
|------|----------|
| `<prefix>_emi.png` | Top: SSA spectrum with annotated peaks (green = harmonic match, orange = unmatched). Bottom: bar chart of identified clock frequencies per MSO channel |
| `<prefix>_emi.json` | Complete results: SSA trace data, peak list with frequencies and amplitudes, clock frequencies per channel, full correlation table |
| `<prefix>_emi.txt` | Human-readable report: identified clocks, correlation table sorted by emission amplitude |

## Example output

```
Identified clocks:
  D0: 16.007 MHz  (98,042 cycles)
  D3: 48.012 MHz  (294,183 cycles)

Correlation results (strongest first):
  144.02 MHz  −42.3 dBm  → 9th harmonic of D0 (16.007 MHz)   error: 83 ppm  ← MATCH
   96.01 MHz  −48.7 dBm  → 2nd harmonic of D3 (48.012 MHz)   error: 156 ppm ← MATCH
   32.01 MHz  −55.1 dBm  → 2nd harmonic of D0 (16.007 MHz)   error: 62 ppm  ← MATCH
  237.50 MHz  −61.8 dBm  → no match within 1000 ppm
```

## How it works

1. SSA sweeps the configured band and finds peaks above `--noise-floor` (default −60 dBm)
2. MSO captures all active digital channels; channels with < 5% period jitter are
   classified as clocks
3. For each SSA peak, harmonics `N × f_clock` are checked for N = 1 … `--harmonic-max`
4. Matches within `--harmonic-tol-ppm` (default 1000 ppm) are reported

## Notes

- scipy `find_peaks` is used if available; a simple fallback finder is used otherwise
  (may report more false positives in noisy spectra)
- Default tolerance 1000 ppm is generous — suitable for crystal oscillators with some
  temperature drift. Reduce to 100–200 ppm for TCXO/VCXO designs
- SSA instruments connect and disconnect independently; SSA sweep completes first,
  then the scope clock capture runs

## Dependencies

```
rf-bench >= 0.2.0
numpy >= 1.20
matplotlib >= 3.4
scipy >= 1.7   (optional — peak finding with prominence filter; fallback if absent)
```
