# AD831 Phasing Upconverter — Opposite-Sideband (Image) Null

Companion to `carrier-fix.md`. That doc addresses the **carrier** at the LO
frequency; this one addresses the **opposite sideband** (the mirror-image
signal). They are different defects with different fixes — read both.

## The two defects, kept straight

A phasing (Hartley) SSB upconverter has two distinct spurs, and it is easy to
confuse them:

| Spur | For USB @ LO=7200, tone=1 kHz | Cause | Fixable by |
|------|-------------------------------|-------|-----------|
| **Carrier** | 7200 kHz (at the LO) | LO-to-IF feedthrough + mixer DC offset | Physical (shielding) for the leakage term; a DC trim for the offset term. See `carrier-fix.md`. |
| **Opposite sideband (image)** | 7199 kHz (LO − tone) | I/Q **gain + phase imbalance** across the chain | **Software pre-distortion of the IQ** — this doc. |

The wanted signal is at 7201 kHz (LO + tone). USB puts the wanted tone *above*
the LO and the image *below* it, mirrored about the carrier.

## Why the image exists

The phasing method cancels the unwanted sideband by summing two mixer outputs
that are 90° apart. The cancellation is only as deep as the I and Q paths are
**matched in amplitude and in quadrature (phase)**. Every real element between
the complex IQ samples and the antenna contributes mismatch:

- the soundcard's two DAC channels have slightly different gain;
- the analog stages / cabling to the mixer differ slightly;
- the AD831's own I and Q sides are not perfectly balanced.

A few percent of gain error or a few degrees of phase error leaks a residual
image. Measured on this bench **before** correction: image only **26.6 dB**
below the wanted signal. Good SSB wants ≥ 40 dB; a phasing exciter should do
much better once balanced.

## The correction

We pre-distort the complex IQ *before it reaches the soundcard* so the
downstream imbalance cancels. Two real parameters null one complex image tone:

```
I' = I
Q' = g * Q + p * I
```

- **`g`** (gain, ≈ 1): trims amplitude imbalance between the paths.
- **`p`** (phase / quadrature crossfeed, ≈ 0): injects a controlled amount of I
  into Q to rotate the effective quadrature, cancelling phase skew.

`g = 1, p = 0` is the identity (no correction). The two knobs are nearly
orthogonal in their effect on the image, so the search surface is well-behaved
and a simplex optimizer converges quickly.

This lives at the very end of the chain (`iq_to_stereo()` in `play-usb-iq.py`),
so it corrects the **whole** downstream path — DAC channels, analog, and mixer —
in one place, regardless of what modulation produced the IQ.

## How it was measured and tuned (closed loop)

Tool: **`iq_balance_trim.py`** (this directory). It runs on the box with the
soundcard (10.1.0.11) and reaches the SSA3032X (10.1.1.60) over the LAN:

1. Generates a seamlessly-looping **1 kHz USB tone** as complex IQ and streams
   it out the soundcard (`I→left`, `Q→right`) at a fixed output scale, with
   `(g, p)` settable live from the audio callback.
2. Configures the SSA for a narrow span bracketing 7199–7201 kHz at **100 Hz
   RBW** (so the three lines, 1 kHz apart, resolve cleanly) and reads the peak
   dBm at the signal, carrier, and image frequencies each sweep.
3. Runs **Nelder-Mead** on `(g, p)` to minimize the **image** line in dBm.
   Output scale is held constant so image level is directly comparable across
   candidates.

Ground-truth measurement (SSA reading the real RF), not a simulation — this is
the honest way to tune it, because the correction has to cancel real hardware
imbalance we cannot predict from first principles.

### Re-running it

```bash
# On 10.1.0.11 (has the soundcard); SSA reachable on the LAN.
cd ~/Dropbox/build/rf-bench/projects/educational/iq/
python3 iq_balance_trim.py                 # LO 7200 kHz, 1 kHz tone, defaults
python3 iq_balance_trim.py --lo 14200000 --tone 1500   # other setups
```

Useful flags: `--ssa`, `--lo`, `--tone`, `--rate`, `--scale` (output peak, lower
if it warns of clipping), `--rbw`, `--ref` (SSA ref level), `--device`,
`--maxiter`. It prints a baseline, every eval, and a final before/after summary,
then holds the optimized tone until Ctrl-C.

## Result (N0GQ bench, 2026-07-19)

| Metric | Before (g=1, p=0) | After |
|--------|-------------------|-------|
| Wanted signal (7201 kHz) | −34.0 dBm | −34.2 dBm (unchanged) |
| Carrier (7200 kHz) | −55.6 dBm | −55.6 dBm (**unchanged, expected**) |
| Image (7199 kHz) | −60.6 dBm | ≤ −100 dBm (into SSA noise floor) |
| **Image suppression** | **26.6 dB** | **> 65 dB (floor-limited)** |

**Best correction found: `g = 0.95987`, `p = 0.08293`.** That implies the chain
had roughly a **4 % gain imbalance** (Q running ~4 % hot) and about a **5°
quadrature phase error**.

The optimizer converged to those values, after which the image reading bounced
randomly between −100 and −110 dBm sweep-to-sweep. That randomness is the
signature that **the image is buried in the analyzer's noise floor** — the
optimizer was chasing noise, not residual image power. So the honest figure is
"**≥ 65 dB, floor-limited**"; the true depth is unknown because the SSA can no
longer see the image. For a phasing exciter this is excellent — the image is
effectively eliminated.

## Where the numbers are baked in

`play-usb-iq.py`:
- Module constants `IQ_BALANCE_GAIN = 0.95987`, `IQ_BALANCE_PHASE = 0.08293`.
- `iq_to_stereo(iq, gain, phase)` applies `Q' = gain*Q + phase*I`.
- CLI overrides `--iq-gain` / `--iq-phase` (set to `1.0` / `0.0` to disable).
- Prints the active trim at startup.

The correction now applies to **everything** transmitted through
`play-usb-iq.py`, not just the calibration tone.

## Honest limits / caveats

- **This does nothing for the carrier.** The carrier at 7200 is LO feedthrough
  (confirmed on this bench: injecting DC at the mixer RF inputs, separately and
  together, moved it *zero* — so it is not the offset term a DC trim fixes; it
  is the AD831's ~30 dB LO-to-IF leakage). That is a physical/shielding problem,
  a separate fight from this one. See `carrier-fix.md`.
- **The constants are bench-specific.** They fold in this soundcard's exact
  channel matching and this AD831's imbalance. A different soundcard or board
  needs a fresh `iq_balance_trim.py` run.
- **They may drift with temperature** and over the audio band (gain/phase
  mismatch is frequency-dependent; a single-tone trim is exact only near the
  calibration tone, though a first-order trim usually helps across all of SSB
  voice). Re-run if the image creeps back, especially after warm-up.
- **Single-tone, single-frequency.** For a flat correction across the whole
  audio passband you would need a frequency-dependent (filter-based) trim; the
  two-scalar trim here is the standard, and effective, first-order fix.

## Reference

- `carrier-fix.md` — the carrier (LO-frequency) spur, the other defect.
- AD831 datasheet (`AD831APZ.PDF`): LO-to-IF isolation 30 dB (p.2) is why the
  carrier can't be trimmed away in baseband; nothing in the datasheet bounds the
  image, because the image is a property of the *external* I/Q balance, not the
  chip.
- `iq_balance_trim.py` — the closed-loop tuning tool (SSA-in-the-loop).
