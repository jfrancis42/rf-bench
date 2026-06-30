# tdt-pdf — Time-Domain Transmission (S21 → time)

Same math as [`../tdr-pdf/`](../tdr-pdf/), but on **S21** instead of S11.
Finds **lumped reflections inside a 2-port DUT** — bonding-wire
mismatches inside an amplifier package, internal element parasitics
in a multi-section filter, board-trace discontinuities inside a
multi-board chain.

The HP 8712B has this natively as `:CALC:TRAN:STATE ON`. NanoVNA does
it host-side. Either VNA produces identical output via this script.

## Setup

```
VNA Port 1 ── DUT ── VNA Port 2
```

A normal THRU connection (no fixture). Calibrate THRU over the sweep
range first. The "0 delay" of the TDT plot is at the THRU reference
plane.

## Usage

```bash
# Inside a 2 m bandpass filter — peaks reveal element spacing
python tdt_pdf.py --start 100 --stop 200 --units ns \
    --label "2 m BPF, 5-element" --output bpf_tdt.pdf

# Inside an MMIC amp module — bonding-wire delays
python tdt_pdf.py --start 1 --stop 1500 --units ns --average 4 \
    --label "MMIC amp module" --output mmic_tdt.pdf

# Distance-equivalent units (vf-dependent)
python tdt_pdf.py --start 1 --stop 500 --units m --vf 0.66 \
    --label "delay line" --output line.pdf
```

## Output

Two-panel single-page PDF:

1. **Step response** — cumulative impulse, useful for spotting slow
   buildups (matched-section transitions in a filter).
2. **|Impulse response|** — sharp peaks at every internal reflection,
   labelled with the dominant peak's delay or equivalent distance.

X-axis units: ns (raw delay), m, or ft. Distance interpretation only
makes sense when the DUT is a transmission-line element with a known
VF.

## Flags

Same shape as the rest of the swappable-API tools:

- `--vna {nanovna,hp}` — driver (default nanovna)
- `--port` / `--host` — serial path / KISS-488 host
- `--start MHZ` / `--stop MHZ` — sweep range
- `--points N` — sweep points (default 401)
- `--average N` — software-average N sweeps (default 2)
- `--power DBM` — HP-only
- `--vf VF` — velocity factor for `--units m / ft` (default 0.66)
- `--units {ns,m,ft}` — X-axis unit (default ns)
- `--window {rect,hann,hamming,blackman,kaiser}` — sweep window
- `--interp N` — time-domain interpolation factor
- `--label`, `--output`

## Notes

- **TDT delay ≠ cable length / 2.** TDR converts round-trip delay to
  one-way distance (`d = vt/2`); TDT is one-way through the DUT
  already, so distance is just `d = v · t` (no /2).
- A pure delay line shows ONE impulse peak at its electrical length.
  Multiple peaks in TDT mean genuine internal reflections (mode
  conversion, manufacturing defects, bond-wire issues, etc.).
- Wider sweep → better time resolution. Time resolution ≈ 1/span.
- See `../tdr-pdf/` for the same math applied to S11 (= reflections
  on a feedline).
