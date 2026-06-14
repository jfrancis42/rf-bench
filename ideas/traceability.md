## Bench-internal traceability chain (calibration plan)

A cross-cutting idea that ties several future projects together. The goal
is **±0.05 dB internal-bench-traceability** across SDG / SSA / Koolertron /
scope amplitude — turning the published specs (±0.5 to ±2 dB absolute)
into a tighter relative match good enough for two-tone IMD, NF, and
amplitude comparison work.

The chain:

1. **SDM3045X ↔ Solartron 7151 cross-cal** keeps both DMMs honest at
   10 ppm scale (continuous service — see [future-solartron](#future-solartron)).
   Anchors voltage truth.
2. **SPD3303X-E voltage cal** is verified against the SDM/Solartron at
   two reference points.
3. **Solartron 7151 measures the DC drop across each fixed RF attenuator
   (1 / 10 / 30 dB)** with a calibrated SPD3303X current — at low
   frequency, below RF rolloff. Solartron sees ~1 ppm; that's the ground
   truth for the pad.
4. **Use the characterized pad + SDG to calibrate the SSA3032X amplitude
   flatness** across its 9 kHz–3.2 GHz range.
5. **Use the calibrated SSA to calibrate Koolertron amplitude** (already
   done for one channel/level pair — extend to full range).
6. **Use the calibrated SSA to calibrate the scope amplitude** —
   resolves the unexplained ~1.5× scope-vs-SDG factor by characterizing
   it instead of trying to explain it.

The chain bottoms out at SPD voltage calibration, which the SDM/Solartron
cross-cal keeps honest. Hardware needed: Solartron 7151 (pending KISS-488),
~10 fixed RF attenuators of various values to characterize.

This is the umbrella for `projects/rf/calibration/` (already built,
covering the SDG/SSA/scope/DMM relationship), the future Solartron-side
projects, and a future `projects/rf/atten-cal/` (programmable attenuators
already covered by `projects/signal-sources/dig-atten-cal/`; this would
be the fixed-pad version).

---

