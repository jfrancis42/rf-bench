# siglent-crystal-extractor

Extracts the Butterworth-Van Dyke (BVD) equivalent circuit parameters of a quartz crystal:
Rs (ESR), Ls (motional inductance), Cs (motional capacitance), Cp (parallel capacitance),
fs (series resonance), fp (parallel resonance), and Q factor.

Batch mode measures and sorts a full bag of crystals by frequency for filter construction.

## Hardware required

- Siglent SDS2504X Plus (LAN, `10.1.1.58`)
- 50 Ω precision metal-film resistor (1%) as series reference
- Crystal socket or test clips
- For `--source sdg` (crystals > 25 MHz): Siglent SDG1062X (LAN, `10.1.1.55`)

## Cable setup

```
Source ──── R_ref (50 Ω 1%) ──── Crystal ──── GND
       CH1 ↑                CH2 ↑
```

Source is either the scope AWG ("Gen Out" BNC) or SDG CH1.

## Generator options

| | AWG | SDG |
|---|---|---|
| Max frequency | 25 MHz | 60 MHz |
| Phase coherence | Yes (same instrument) | No |
| Best for | All HF ham crystals (1.8–21 MHz) | 10m, 45 MHz IF crystals |

The scope AWG covers all common ham HF crystals. Use `--source sdg` only for
crystals above 20–21 MHz.

## Usage

```bash
# Measure a 7 MHz (40m) crystal — AWG default
python crystal_extractor.py --freq-khz 7000

# Wider span for crystals with large separation between fs and fp
python crystal_extractor.py --freq-khz 3579 --span-khz 50

# More points for high-Q crystals (narrow 3dB bandwidth)
python crystal_extractor.py --freq-khz 7000 --span-khz 5 --points 500

# 10m crystal using SDG
python crystal_extractor.py --freq-khz 28000 --source sdg

# Batch mode — measures a set of crystals for filter matching
python crystal_extractor.py --freq-khz 7000 --batch --batch-output ./crystal_batch/

# Small signal level (fragile or old crystals)
python crystal_extractor.py --freq-khz 7000 --level-vpp 0.05
```

## Example output

```
Crystal parameters:
  fs  =  7,000,812 Hz    (series resonance)
  fp  =  7,004,231 Hz    (parallel resonance)
  Rs  =      14.2 Ω      (motional resistance / ESR)
  Ls  =       8.4 mH     (motional inductance)
  Cs  =      61.4 fF     (motional capacitance)
  Cp  =       4.1 pF     (parallel plate capacitance)
  Q   =  23,142           (Q factor at series resonance)
```

## Output files

| File | Contents |
|------|----------|
| `<prefix>_crystal.png` | Two-panel: \|Z\| (log, ohms) and phase (°) vs frequency |
| `<prefix>_crystal.json` | BVD parameters + raw impedance sweep |
| In batch mode: `crystal_001.json` … | One JSON per crystal |
| In batch mode: `batch_summary.json` | All crystals sorted by fs |

## Batch mode summary table

```
Crystal  fs (Hz)    fp (Hz)    Rs (Ω)  Q       Match?
001      7,000,812  7,004,231   14.2  23,142   ← reference
002      7,000,798  7,004,219   15.1  21,890   YES (14 Hz)
003      7,001,847  7,005,282   13.8  24,100   NO  (1035 Hz)
```

Crystals within ±5 Hz of the lowest-frequency crystal are marked as matched — suitable
for use in a 4- or 8-pole ladder crystal filter.

## Notes on measurement accuracy

- Drive level kept at 100 mVpp (default) to avoid heating the crystal
- High-Q crystals (Q > 50,000) have very narrow 3 dB bandwidths — use `--span-khz 2`
  and `--points 500` for adequate resolution; otherwise Q falls back to fs/fp estimate
- BVD model assumes ideal lumped elements; stray lead inductance and probe capacitance
  introduce ~5–20% error depending on setup

## Dependencies

```
rf-bench >= 0.2.0
numpy >= 1.20
matplotlib >= 3.4
scipy >= 1.7   (optional — used for curve fitting; skipped if unavailable)
```
