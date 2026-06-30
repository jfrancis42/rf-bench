# rlgc-pul-pdf — Per-unit-length R, L, G, C from two cable lengths

Distributed-line constants from S-parameters. Needs four Touchstone
files:

1. `.s2p` of the **longer** cable sample (S21 transmission)
2. `.s2p` of the **shorter** cable sample (S21 transmission)
3. `.s2p` of the longer cable with the far end **OPEN**
4. `.s2p` of the longer cable with the far end **SHORT**

The two lengths give propagation constant γ(f); the open/short
pair gives characteristic impedance Z₀(f). From those:

```
R + jωL = γ · Z₀
G + jωC = γ / Z₀
```

## Usage

```bash
python rlgc_pul_pdf.py \
    --long lmr400_10m.s2p --length-long-m  10.0 \
    --short lmr400_2m.s2p --length-short-m  2.0 \
    --z0-open lmr400_open.s2p \
    --z0-short lmr400_shor.s2p \
    --label "LMR-400 PUL" --output lmr400.pdf
```

## Output

2 × 2 PDF showing R (Ω/m), L (nH/m), G (µS/m), C (pF/m) vs
frequency. Console prints the median value of each.

## Notes

- Pure post-processor; needs `.s2p` files captured separately
  (e.g. with `../sparams-pdf/`).
- Frequency grids of all four input files must match exactly.
- The companion project `../tline-pdf/` gives just VF, Z₀, and
  loss/m from a single S21 capture. This script does the full RLGC
  extraction when you need a distributed-element SPICE model.
