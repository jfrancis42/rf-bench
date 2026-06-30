# wheeler-cap-pdf — Antenna radiation efficiency

The Wheeler cap method separates *useful* radiation resistance from
*wasted* ohmic resistance in an antenna. Mathematically:

```
η = 1 - (Q_free / Q_cap)
```

where Q_free is the antenna's Q in free space and Q_cap is its Q
inside a conducting cap that suppresses radiation but preserves near-
field current distribution.

For an electrically-short mobile whip:
- High η (>80%): a good antenna; tuning losses are small.
- Low η (<30%): you're heating the loading coil. Replace it with a
  bigger air-wound version or improve the ground plane.

## Workflow

1. Calibrate VNA at the antenna feedpoint.
2. Capture S11 in free space; save as `free.s2p` (use
   [`../impedance-pdf/`](../impedance-pdf/) or
   [`../sparams-pdf/`](../sparams-pdf/)).
3. Install the conducting cap around the antenna (don't touch the
   antenna itself); capture S11 again as `cap.s2p`.
4. Run this script.

```bash
python wheeler_cap_pdf.py \
    --free-space free.s2p --with-cap cap.s2p \
    --label "mobile whip 14 MHz" --output whip_eff.pdf
```

## Flags

- `--free-space FREE.s2p` — antenna in free space
- `--with-cap CAP.s2p` — antenna inside the cap
- `--label`, `--output`

## Output

Side-by-side |S11| trace of both captures with Q values reported in
the legend, plus the derived efficiency η in the title.

## Notes

- The cap diameter must be **< λ / (2π)** at the operating frequency
  for the method to work cleanly. For 80 m antennas you'd need a
  ~13 m cap — impractical. For VHF (~5 cm cap at 144 MHz) the method
  is very practical.
- Resonant frequency typically shifts slightly with the cap installed
  (a few %); the script measures Q at each capture's own resonance.
  If the shift is large, the resonance moved out of band and the
  result is unreliable.
- For mobile-coil-loaded antennas, this is the **only** practical way
  to verify a manufacturer's efficiency claim.
