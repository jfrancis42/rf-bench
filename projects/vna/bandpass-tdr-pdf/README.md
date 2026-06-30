# bandpass-tdr-pdf — Bandpass-mode TDR for bandlimited sweeps

A normal "low-pass" TDR (`../tdr-pdf/`) assumes the swept S11 starts
**close to DC** and mirrors it back. When the sweep instead lives
entirely above some non-trivial frequency (a UHF-only DUT, a feedline
with a sharp HPF at the input, etc.), the low-pass fold introduces
artefacts that smear the impulse response.

Bandpass mode treats the swept S11 as the complex envelope of an
analytic signal centred at the sweep midpoint. The IFFT then yields
a complex envelope whose magnitude shows reflection ARRIVALS in time
(or one-way distance with a known VF), free of the DC-extrapolation
problem.

When this is the right tool:

- Sweep doesn't start within ~1 % of DC (e.g. 400–600 MHz UHF-only)
- The DUT itself has a high-pass response that kills S11 at low f
- You only care about the *timing* of internal reflections, not
  their reflection coefficient sign

For everything else, the low-pass TDR is sharper and includes step-
response output.

## Setup

```
VNA Port 1 ── DUT  (open or with arbitrary far-end load)
```

OSL-calibrate over the same sweep range.

## Usage

```bash
# Band-limited DUT, UHF-only sweep
python bandpass_tdr_pdf.py --start 400 --stop 900 \
    --vf 0.66 --label "UHF DUT" --output uhf_bptdr.pdf

# 23 cm patch lead, 1240–1300 MHz only
python bandpass_tdr_pdf.py --start 1240 --stop 1300 \
    --vf 0.85 --label "23 cm LMR-400 patch" --output 23cm_bptdr.pdf
```

## Flags

Same shape as `tdr-pdf`:

- `--vna {nanovna,hp}`, `--port`, `--host`
- `--start MHZ` / `--stop MHZ` / `--points` / `--average`
- `--power` (HP only)
- `--vf VF` (default 0.66)
- `--feet` — distance in feet instead of metres
- `--window {rect,hann,hamming,blackman,kaiser}`
- `--interp N` — time-domain interpolation factor
- `--label`, `--output`

## Output

Single-panel PDF: the envelope of the impulse response vs distance.
A clean unloaded reference shows one peak near the connector face;
internal reflections show as additional peaks at their respective
delays.

## Notes

- Bandpass mode loses information about the **sign** of reflections
  that low-pass mode preserves. You'll see "there is a reflection
  here" but not "is it an OPEN-like or SHORT-like fault."
- Spatial resolution is the same as low-pass TDR: `vf · c / (2 ·
  span)`.
- For mixed-band work, sweep low-pass + bandpass and cross-check
  the peak distances. Disagreement points to a calibration error.
