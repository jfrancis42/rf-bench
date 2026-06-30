# sparams-4port-from-2port — Assemble a 4-port .s4p from six 2-port captures

Classic recipe: with a 2-port VNA and 50-Ω terminations, you can
characterise a 4-port DUT by capturing pairwise S-parameters six
times (one per port pair). This script stitches the six .s2p files
into a single 4-port .s4p suitable for `../mixed-mode-pdf/` etc.

## Capture procedure

Number the DUT ports 1, 2, 3, 4. Six captures:

| Capture | DUT ports on VNA | Other ports |
|--------:|------------------|-------------|
| `p12`   | 1 ↔ 2            | 3, 4 → 50 Ω |
| `p13`   | 1 ↔ 3            | 2, 4 → 50 Ω |
| `p14`   | 1 ↔ 4            | 2, 3 → 50 Ω |
| `p23`   | 2 ↔ 3            | 1, 4 → 50 Ω |
| `p24`   | 2 ↔ 4            | 1, 3 → 50 Ω |
| `p34`   | 3 ↔ 4            | 1, 2 → 50 Ω |

Use `../sparams-pdf/` for each. Then:

```bash
python sparams_4port_from_2port.py \
    --p12 p12.s2p --p13 p13.s2p --p14 p14.s2p \
    --p23 p23.s2p --p24 p24.s2p --p34 p34.s2p \
    --output mydut.s4p
```

## Output

A standard Touchstone `.s4p`. Feed it to `../mixed-mode-pdf/` for
differential / common-mode analysis.

## Notes

- The diagonals S11/S22/S33/S44 appear in multiple pair captures
  and are averaged for noise reduction.
- Off-diagonals are unique to one capture each.
- The same .s4p workflow has been tested for synthetic data; field
  use is pending.
