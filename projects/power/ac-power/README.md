# AC Power / Power-Factor Analyzer

Fluke 80i-400 clamp + **mains-voltage sense** + SDS2000X scope. Measures true
power (W), apparent power (VA), reactive power (var), and power factor by
capturing v(t) and i(t) **simultaneously** on two scope channels and
integrating p(t) = v(t)·i(t).

## ⚠ SAFETY — read before use

This is the only clamp project that senses the mains **voltage**, which makes it
far more dangerous than the current-only projects. A bench scope's channel
ground is earth-referenced through its mains plug; touching a probe ground to a
live conductor can short line-to-earth violently.

**You MUST use one of:**
- a **differential probe** (e.g. 1400 V CAT III), or
- a **mains isolation transformer** on the DUT.

The script **refuses to run** without `--i-have-isolation`, to force that choice
to be explicit.

## Connections

```
Voltage: mains ──► differential probe / isolation xfmr ──► scope CH1
                   (--volt-scale = mains volts per scope-volt, e.g. 200)
Current: conductor ──► 80i-400 clamp ──► burden (1 Ω) ──► scope CH2
```

Both channels are captured in one acquisition (`SDS2000X.capture_two_channels`)
so V and I are phase-aligned — essential for a correct power factor.

## Usage

```bash
python ac_power.py --i-have-isolation --volt-scale 200
python ac_power.py --i-have-isolation --volt-scale 200 --burden 1 \
                   --ch-v 1 --ch-i 2 --mains 60 --plot power.png
```

Reports V/I rms, real W, apparent VA, reactive var, PF. `--plot` overlays v/i
and the instantaneous-power waveform.

Math validated on synthetic signals: 120 V rms, 10 A rms, 60° lag → P = 600 W,
PF = 0.500 (exact).

## Hardware still needed

A burden resistor (1 Ω, low-inductance) and a differential probe **or** isolation
transformer. See the shopping list in `ideas/fluke-80i400-projects.md`. Until
those are on the bench this project is code-complete but unrun against hardware.
