# kramers-kronig-pdf — Causality check via Hilbert transform

Real and imaginary parts of any causal frequency-domain response
are Hilbert transforms of each other. Reconstruct one from the
other and the residual is a measurement-quality diagnostic.

Useful for:

- Validating SOLT calibration ("am I sure my cal is correct?").
- Sanity-checking a fixture .s2p before using it for de-embedding.
- Confirming a passive DUT is actually passive (active DUTs and
  noisy / poorly-calibrated measurements both violate KK).

## Usage

```bash
python kramers_kronig_pdf.py --input cal_check.s2p \
    --parameter S21 --label "BPF after SOLT cal" \
    --output causality.pdf
```

## Output

PDF with three panels:

1. Re S(f) — measured (grey dashed) vs Hilbert-reconstructed (blue)
2. Im S(f) — measured (grey dashed) vs Hilbert-reconstructed (green)
3. Residuals — measured − reconstructed for both real and imag

Verdict on stdout:

- < 5 % RMS-relative-to-signal-std → CAUSAL
- 5–20 % → probable calibration error
- > 20 % → non-causal (bad cal, active DUT, noise)

## Flags

- `--input FILE.s2p` — Touchstone input
- `--parameter {S11,S12,S21,S22}` — which trace to check (default S21)
- `--label TEXT` — chart title text
- `--output FILE.pdf` — PDF path

## Notes

- Pure post-processor; no VNA connection.
- Requires `scipy.signal.hilbert`.
- Most accurate when the sweep includes a wide band around the
  signal's features. Narrow sweeps near a single resonance give
  inflated residuals (the Hilbert transform sees the truncation
  as discontinuity).
