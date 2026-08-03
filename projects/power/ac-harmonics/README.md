# AC Current Harmonic / THD-i Analyzer

Fluke 80i-400 clamp + SDS2000X scope. Measures the harmonic content of a
mains-frequency **current** waveform: total harmonic distortion (THD-i) and the
per-harmonic breakdown. Great for characterizing switching supplies, LED lamps,
VFDs, and motors, which draw distorted current from a clean voltage.

**Current-only, so safe** — THD-i is a ratio of harmonic currents and needs no
voltage sensing. No mains-voltage contact.

## Connections

```
conductor ──► 80i-400 clamp ──► burden resistor (1 Ω) across clamp leads ──► scope CH1
```
1 Ω burden → 1 mV/A. Pick the burden so the current stays on-screen and within
the resistor's power rating (P = (A/1000)²·R).

## Usage

```bash
python ac_harmonics.py                          # CH1, 1 Ω, 60 Hz
python ac_harmonics.py --mains 50               # 50 Hz mains
python ac_harmonics.py --burden 10 --channel 2  # 10 Ω burden on CH2
python ac_harmonics.py --max-harmonic 25
python ac_harmonics.py --plot harmonics.png
```

Reports fundamental frequency/RMS, total RMS, THD-i %, and a per-harmonic table
(2nd–Nth, ≥0.5 % shown). `--plot` saves a harmonic bar chart.

Validated against synthetic signals: 10 A fundamental + 30 % 3rd + 10 % 5th →
THD-i 31.6 %, 3rd 30.0 %, 5th 10.0 %.

See `ideas/fluke-80i400-projects.md`. Power/PF (needs voltage) → `../ac-power/`.
