# group-delay-pdf — Group delay (τ_g = −dφ/dω) PDF

Focused S21 group-delay tool for amplifiers, cables, transmission
lines, and matching networks — anything where you care about the
delay vs frequency but don't need a filter-style magnitude analysis.

For **filter** group delay, prefer the `--group-delay` flag on
[`../filter-pdf/`](../filter-pdf/): same math, but co-plotted with
the auto-detected passband bandwidths.

Works with either of the swappable VNA drivers:

- `rf_bench.nanovna.NanoVNA` — **default**, USB CDC at `/dev/ttyACM1`
- `rf_bench.hp.HP8712B` — KISS-488 Ethernet-GPIB at `10.1.1.70`

## Setup

```
VNA Port 1 ── DUT ── VNA Port 2
```

Run a SOLT (or at minimum a THRU) calibration over the same sweep
range first. Group delay is a derivative of phase, and any phase the
cabling adds shows up as both an offset and a shape error.

## Usage

```bash
# Amplifier under test, 1 MHz – 1.5 GHz
python group_delay_pdf.py --start 1 --stop 1500 --average 8 \
    --label "MMIC amp under test" --output mmic_gd.pdf

# 30 ft RG-58 patch lead group delay
python group_delay_pdf.py --start 1 --stop 1000 --average 4 \
    --label "30 ft RG-58 patch" --output rg58_gd.pdf

# Same patch lead, only score statistics inside 100–500 MHz
python group_delay_pdf.py --start 1 --stop 1000 --roi 100 500 \
    --label "30 ft RG-58 patch (VHF/UHF)" --output rg58_uhf_gd.pdf

# Matching network at 2 m, narrow sweep
python group_delay_pdf.py --start 140 --stop 150 --points 401 --average 8 \
    --label "2 m matching net after retune" --output 2m_match_gd.pdf
```

Optional flags:

- `--vna {nanovna,hp}` — driver selection (default nanovna)
- `--port /dev/ttyACM1` — NanoVNA serial path
- `--host 10.1.1.70` — HP KISS-488 host
- `--points N` — sweep points (NanoVNA max 401, HP max 801; default 401)
- `--average N` — software-average N sweeps (default 4; group delay is
  derivative-sensitive so more is usually better)
- `--power DBM` — HP source power; ignored on NanoVNA
- `--roi MHZ_LO MHZ_HI` — region of interest; statistics computed and
  ROI shaded on every panel

## Output

Three-panel single-page PDF sharing a frequency axis:

1. **|S21| (dB)** — for context: where is there a signal?
2. **∠S21 unwrapped (°)** — the underlying phase trace
3. **Group delay (ns)** — the derivative, in nanoseconds. ROI bolded
   (or the entire sweep, if no ROI given) with min / mean / max /
   peak-to-peak printed in a corner.

## NanoVNA vs HP — group-delay specific notes

- **Hardware averaging.** The HP 8712B has true hardware averaging
  in the IF chain. The NanoVNA does not. Group delay is derivative-
  noise sensitive: a 1° phase wobble at 1 GHz produces an apparent
  ~0.003 ns of GD ripple. Use a higher `--average` on the NanoVNA
  (8 or 16) than you would on the HP (4).
- **NanoVNA noise floor on S21.** Past ~50 dB of through loss the
  NanoVNA's phase estimate becomes effectively random. Group delay
  is therefore only meaningful where the magnitude panel shows the
  DUT is actually passing signal.
- **Frequency range.** NanoVNA-F: 50 kHz – 1.5 GHz fundamental,
  harmonic-extended to ~3 GHz on H4/DiSlord builds (GD above 1.5 GHz
  is only useful for relative comparisons because output level is
  uncalibrated up there). HP 8712B: 300 kHz – 1.3 GHz with much
  cleaner GD across that span.
- **Built-in `GDELAY` format on the HP.** The HP 8712B has a
  hardware `:CALC:FORMAT GDELAY` mode that computes group delay
  on-instrument with smoothing. The driver does not expose it; this
  script computes GD host-side from raw S21 instead, so the result
  is bit-identical between the two VNAs. Once the HP is online, the
  on-instrument mode is a useful cross-check.

## Notes

- The script uses `np.gradient` (central difference) against ω, so
  endpoint samples use one-sided differences and may be 2–3× noisier
  than the interior. If you care about the band-edge GD, sweep
  slightly wider than your ROI.
- The "ROI" flag exists so you can take ONE wide capture and then
  zoom statistics into a band of interest without rerunning the
  hardware. Use it for amplifier or transmission-line work where you
  want broad context but only score the in-band part.
