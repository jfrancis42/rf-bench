# filter-pdf — Filter response (S21) PDF

S21 sweep with a filter as the THRU device → annotated single-page PDF
with auto-detected bandwidths, ripple, shape factor, and stopband floor.

Works with either of the swappable VNA drivers:

- `rf_bench.nanovna.NanoVNA` — **default**, USB CDC at `/dev/ttyACM1`
- `rf_bench.hp.HP8712B` — KISS-488 Ethernet-GPIB at `10.1.1.70`

## Setup

```
VNA Port 1 ── filter under test ── VNA Port 2
```

Run a full SOLT (or at minimum a THRU) calibration over the same sweep
range first. Without correction, the trace bakes in the loss of every
cable and adapter between the ports.

## Usage

```bash
# 2 m bandpass: sweep 100–200 MHz to see roll-off well past the band
python filter_pdf.py --start 100 --stop 200 \
    --label "2 m bandpass at the radio" --output 2m_bpf.pdf

# Crystal filter — zoom right around the centre frequency
python filter_pdf.py --start 9.998 --stop 10.002 --points 401 --average 4 \
    --label "9 MHz Inrad SSB filter" --output inrad.pdf

# Broad LPF (HF low-pass): pick wide span so the -60 dB point is visible
python filter_pdf.py --start 0.5 --stop 200 \
    --label "HF LPF at radio output" --output hf_lpf.pdf

# BCB-rejection HPF: sweep AM band and the lower HF region together
python filter_pdf.py --start 0.5 --stop 5 \
    --label "BCB reject HPF" --output bcb_reject.pdf

# Same SSB crystal filter as above, but add phase + group-delay panels:
python filter_pdf.py --start 9.998 --stop 10.002 --points 401 --average 4 \
    --phase --group-delay \
    --label "9 MHz Inrad SSB filter" --output inrad_phasegd.pdf
```

Optional flags:

- `--vna {nanovna,hp}` — driver selection (default nanovna)
- `--port /dev/ttyACM1` — NanoVNA serial path
- `--host 10.1.1.70` — HP KISS-488 host
- `--points N` — sweep points (NanoVNA max 401, HP max 801; default 401)
- `--average N` — software-average N sweeps
- `--power DBM` — HP source power; ignored on NanoVNA
- `--phase` — adds an unwrapped-phase panel below the magnitude panel
- `--group-delay` — adds a group-delay panel (τ_g = −dφ/dω, nanoseconds);
  in-band min / max / peak-to-peak summary is printed and overlaid on the panel

## Output

Single-page PDF with:

- **|S21| (dB) vs frequency** trace
- **Peak marker** at the highest in-band sample
- **-3 dB / -6 dB / -20 dB / -40 dB / -60 dB** bandwidth lines and shaded
  bands, annotated with the corresponding BW in MHz
- **Stopband floor** marker — deepest sample outside the -20 dB band
- **Metrics block** in the lower-left corner with:
  - Peak insertion loss and frequency
  - Each bandwidth (or "not crossed in sweep range")
  - Passband peak-to-peak ripple (within the -3 dB band)
  - Shape factor (-60 dB BW ÷ -6 dB BW) — classic SSB-filter spec
  - Stopband floor in dB and frequency

## On the optional `--phase` / `--group-delay` panels

Both panels are derived from the complex S21 the VNA already returns —
no extra capture step. They work identically on the NanoVNA and on
the HP 8712B.

- The **phase panel** plots `np.unwrap(np.angle(S21))` in degrees.
  Useful for confirming the filter is roughly linear-phase in the
  passband (a Bessel filter looks like a sloped straight line; a
  classic Cauer/elliptic looks like a sloped line with ripple).
- The **group-delay panel** plots `−dφ/dω` in nanoseconds. The trace
  is drawn faintly across the whole sweep and bolded inside the
  detected −3 dB passband, because group delay outside the passband
  is dominated by phase noise and is essentially meaningless. The
  in-band minimum, maximum, and peak-to-peak ripple are reported.
- **NanoVNA caveat:** the NanoVNA has no hardware averaging and a
  coarser noise floor than the HP. The differentiation in group-delay
  amplifies that noise. Use `--average 4` or higher when computing
  group delay; the HP's hardware averaging is tighter still, so once
  it's online you'll get cleaner GD traces from it.
- **NanoVNA bonus on the high end:** because the NanoVNA-F reaches
  1.5 GHz fundamental (HP 8712B stops at 1.3 GHz), VHF/UHF filter
  group-delay work above ~1.3 GHz is **NanoVNA-only** until a higher-
  range VNA arrives.

## Notes

- The analyzer assumes a single passband. For multi-passband filters
  (notch, comb, diplexer skirts), the auto-detected bandwidths reflect
  only the dominant peak. Visual inspection of the trace is still
  required.
- NanoVNA dynamic range is ~50–70 dB; a true -60 dB stopband may
  bottom out in the noise floor and report a falsely-shallow value.
  For deep stopband work the HP 8712B (~100 dB) is the better choice.
- The default 401 points may be too coarse for narrow crystal filters.
  Bump `--average` (HP-averaged sweeps are very tight) or narrow the
  sweep range to put more points across the passband.
- For sharper resolution past the noise floor, sweep with high
  averaging (`--average 8` or more) and re-run.
