# AD831 Phasing Upconverter — Carrier-Null Fix

## Symptom

USB signal is present and mostly correct, but the **carrier leaks through
strongly** — a spike at exactly the LO frequency (7200 kHz). It is unchanged
when the baseband (I/Q) audio is physically disconnected from the PC.

## Root cause

The carrier at exactly the LO frequency is a **DC offset at each mixer's
signal (RF) input** being multiplied by the LO. It does **not** cancel in a
two-mixer phasing (Hartley) upconverter — only the unwanted *sideband*
cancels; the two carrier-feedthrough terms add in quadrature and survive.

Datasheet numbers that make this inherent (AD831 Rev. C, extracted):

- **Output Offset Voltage: +15 mV typ, ±40 mV max** (measured "LO Input
  Switched ±1"). This is the dominant carrier source.
- **LO-to-IF isolation: only 30 dB** (@100 MHz) — a secondary, coupling-based
  source that a DC trim *cannot* fix (see caveat).

Because the AD831 has an **internal LO limiting amplifier**, the mixer core
sees a constant switching level regardless of applied LO drive above the
minimum. **Turning the LO drive down does NOT reduce carrier suppression** —
the ratio is fixed. The only cure for the offset-derived carrier is to inject
an equal-and-opposite DC at the RF input: a **carrier-null trim**.

## LO drive (set once, then leave it)

Reference design / this board: **−10 dBm**. Into a 50 Ω LO termination:

| dBm | mV rms | mV p-p |
|-----|--------|--------|
| −10 dBm (spec) | 70.7 | **200** |

At < 100 MHz the datasheet permits as low as −20 dBm (63 mV p-p), but there is
no benefit for carrier. **Set the Siglent to deliver 200 mV p-p and leave it.**

> Siglent load-impedance trap: if the SDG output is set to **High-Z**, its
> displayed amplitude is **2×** what it delivers into the 50 Ω LO termination —
> set **400 mV p-p** on the display. If set to **50 Ω load**, set **200 mV p-p**
> directly. Confirm this before anything else.

## The fix — one carrier-null trim per AD831 (TWO total)

Each mixer has its own offset, so build this **twice** — once on the I mixer,
once on the Q mixer.

### Parts (per mixer)

- **Trimmer: 10 kΩ, 25-turn cermet** (Bourns 3296W or equivalent). Multiturn is
  important — you need fine resolution around the null.
- **Series resistor: 100 kΩ**, 1/8 W.
- **Filter cap: 1 µF** (ceramic or film; 0.1 µF minimum).

### Where the three legs go (single-supply +9 V board)

```
   +9V ──────[ end 1 ]
                 │
              [ 10k ]   25-turn trimmer
                 │
   GND ──────[ end 2 ]

           wiper (center leg)
                 │
                 ├──── 1 µF ──── GND        (noise / supply-hum filter)
                 │
              [ 100k ]                       (series injection resistor)
                 │
              RFP  (pin 6)  ◄──── your I (or Q) baseband audio also lands here
```

- **Trimmer end 1 → +9 V** (the board's positive rail).
- **Trimmer end 2 → GND.**
- **Trimmer wiper → 100 kΩ → RFP (pin 6)** of that AD831 — the node where the
  I (or Q) audio enters the mixer.
  - Inject on the **mixer side** of the board's RF input coupling cap
    (C1/C2 in the reference circuit), so the DC lands on the pin and is not
    shunted away by the source.
- **1 µF from the wiper to GND** (on the pot side of the 100 kΩ, *not* at RFP —
  a cap at RFP would AC-ground your signal). This keeps supply hum from
  modulating the injected DC and throwing sidebands around the carrier.

Nothing connects to RFN (pin 7); leave the board's existing 0.1 µF bypass on
it. Injecting single-ended at RFP against an AC-grounded RFN produces the
differential DC offset that cancels the chip's internal one.

### Why these values

- The pot swings the wiper **0 V → +9 V**. Through the 100 kΩ series resistor
  into the RF input's **1.3 kΩ** input resistance, the injected shift at the pin
  is about
  `ΔV ≈ (V_wiper − V_bias) × 1.3k / (100k + 1.3k) ≈ (V_wiper − V_bias) × 0.0128`.
- With the internal RF-input bias near mid-rail, that gives roughly **±58 mV**
  of adjustment — comfortably covering the **±40 mV** worst-case offset.
- 25 turns over 9 V → ≈ **4.6 mV per turn** at the pin: fine enough to bury the
  null.

## Adjustment procedure

1. LO on at **200 mV p-p** (delivered). RF/antenna line into the IC-7300.
2. **Zero baseband** — mute/stop the audio, or feed silence. (Carrier is
   independent of baseband, so silence gives the cleanest target.)
3. On the **IC-7300's own scope/waterfall**, watch the spike at **7200 kHz**.
4. Adjust **trimmer #1 (I mixer)** for **minimum** carrier.
5. Adjust **trimmer #2 (Q mixer)** for minimum.
6. The two interact slightly if any LO coupling is present — **iterate #1/#2
   once or twice** to reach the deepest null.
7. Restore baseband audio; confirm the wanted sideband is clean.
8. Offset drifts with temperature — **re-null occasionally**, especially after
   warm-up.

## What this can and cannot fix (honest limits)

- ✅ **Offset-derived carrier** (the dominant term): the trim nulls it. Expect
  the spike to drop to ≈ **40–50 dB** below the sideband — often into the noise.
- ❌ **Parasitic LO coupling** into the output/combiner (the AD831's LO-to-IF
  isolation is only **30 dB**): a DC trim **cannot** touch this.

**How to tell which you have:** if a trimmer can drive the carrier **down into
the noise floor**, you were offset-limited and you're done. If it **bottoms out
well above the floor** (a clear minimum, but still a visible carrier), the
residual is physical LO leakage — that's a **layout/shielding** problem
(shorten and separate LO traces, keep them away from the resistive combiner and
output, shield the combiner node). No amount of DC trim will remove it.

## Board-specific things to verify

These are **inferred from the datasheet reference design** your module copies;
confirm against your actual board:

- **RF input is AC-coupled** (series cap before RFP). If so, inject DC on the
  mixer side of that cap (as above). If your board DC-couples the audio in,
  inject on the mixer side of wherever the last series cap is.
- **RFN (pin 7) is AC-grounded** via 0.1 µF (reference Fig 9/10). If your board
  instead uses RFN as the signal input, put the trim on RFN.
- If a trimmer **hits an end-stop before reaching the null** (bias not centered
  → asymmetric range), **reduce the series resistor** (100 kΩ → 47 kΩ) to widen
  the injection range at some cost in resolution.

## Reference

AD831 datasheet Rev. C (`AD831APZ.PDF`, this directory): Specifications p.2
(Output Offset Voltage, LO-to-IF isolation, RF DC input resistance, LO drive),
Applications pp.10–12 (single-supply Fig 10, quadrature Fig 11, LO drive vs
frequency note).
