# q-cross-check — Three Q methods compared

Three independent Q-extraction methods on the same Touchstone .s2p:

1. **3 dB bandwidth** — Q = f₀ / BW₃dB (the textbook method)
2. **Lorentzian fit** — least-squares fit to A / (1 + ((f-f₀)/γ)²)
3. **Smith-chart Q-circle** — circle fit to Γ(f) + phase-slope analysis

When all three agree, the Q reading is trustworthy. When they
disagree, the measurement is suspect (noise floor too high, sweep
too narrow, sample misidentified). The script reports max/min ratio
and CoV across the three values.

## Usage

```bash
python q_cross_check.py --input crystal.s2p \
    --parameter S21 --label "10 MHz xtal #3" --output xtal_Q.pdf

# For S11-based Q (one-port resonator)
python q_cross_check.py --input antenna.s2p \
    --parameter S11 --label "trap dipole 40 m resonance" --output trap_Q.pdf
```

## Output

4-panel PDF: magnitude, Smith Γ-trajectory, phase, and a results
text block showing all three Q values and their spread.

## Flags

- `--input FILE.s2p` — Touchstone
- `--parameter {S11,S12,S21,S22}` — trace to analyse (default S21)
- `--label`, `--output`

## Notes

- Pure post-processor; no VNA connection.
- Requires `scipy.optimize` for the Lorentzian fit.
- The Smith-circle method works best for one-port reflection
  (S11/S22) data near a single isolated resonance. For S21 it's
  meaningful only inside a narrow passband.
- A 2× max/min disagreement is a sign of: (a) noisy data, (b) a
  sweep that's much wider than the resonance band, or (c) multiple
  resonances near each other.
