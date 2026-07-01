# resonance-finder — Acoustic Resonance Finder

Discover the natural frequencies of any object or space. Tap a wine
glass, knock on a wall, pluck a string — the tool identifies all
resonant modes, their frequencies, Q factors, and musical notes.

## How it works

Every physical object has natural frequencies at which it vibrates
most efficiently. A wine glass rings at specific pitches, a room
has standing-wave modes, a guitar body resonates at its wood's
natural frequencies. This tool captures the response to an impulse
(tap/knock/click) and finds all the peaks in the frequency spectrum.

## Modes

### Passive (default)
Wait for you to tap the object near the mic. Detects the transient,
records the decay, analyzes. Simplest — just tap and see.

### Active
Plays a short impulse (click) through the headphones held against the
object. Records the response through the mic. Better reproducibility
since the excitation is controlled.

### Sweep
Plays a slow sine sweep through the object (headphones on surface),
records response. Most sensitive for finding weak resonances that
a single tap might not excite.

## Usage

```bash
# Passive: tap object near mic, auto-detect and analyze
python resonance_finder.py --input-device 2

# Active: play click through headphones pressed to surface
python resonance_finder.py --mode active --input-device 2 --output-device 2

# Sweep mode (most thorough)
python resonance_finder.py --mode sweep --duration 5

# Output PDF report
python resonance_finder.py --pdf resonances.pdf

# Narrow frequency range (low-frequency room modes)
python resonance_finder.py --min-freq 20 --max-freq 200

# Higher sensitivity (lower prominence threshold)
python resonance_finder.py --prominence 5

# Test mode (simulated wine glass)
python resonance_finder.py --test --pdf test_resonance.pdf
```

## Flags

- `--mode {passive,active,sweep}` — measurement mode (default: passive)
- `--duration SECS` — capture/sweep duration (default: 2)
- `--prominence DB` — minimum peak prominence for detection (default: 8)
- `--min-freq HZ` — search range minimum (default: 20)
- `--max-freq HZ` — search range maximum (default: 16000)
- `--trigger-db DB` — passive mode trigger threshold (default: -20)
- `--top N` — show top N resonances (default: 10)
- `--pdf FILE` — output PDF report
- `--csv FILE` — output CSV of all detected resonances
- Standard audio device flags

## Output

```
#    Freq (Hz)    Note     Level      Q        BW (Hz)    Prominence
----------------------------------------------------------------------
1    440.0        A4       -0.0       142      3.1        42.3 dB
2    1108.0       C#6      -8.5       89       12.4       31.2 dB
3    1762.0       A6       -14.0      71       24.8       25.8 dB
4    2645.0       E7 +12¢  -20.1      53       49.9       18.4 dB

Fundamental: 440.0 Hz (A4)
Q factor: 142 (decay time ≈ 103 ms)
```

## What to measure

| Object | Expected resonances |
|--------|-------------------|
| Wine glass | 300-1000 Hz, high Q (long ring) |
| Drum head | 100-500 Hz, low Q (short decay) |
| Guitar body | 80-500 Hz, medium Q |
| Room (standing waves) | 20-200 Hz, depends on dimensions |
| Bell | Multiple modes, very high Q |
| Tuning fork | Single strong mode, extremely high Q |
| Wall (stud vs cavity) | Stud: higher, cavity: lower |
| Bottle (air column) | f = c/4L for closed end |

## Q factor interpretation

| Q | Meaning | Example |
|---|---------|---------|
| < 10 | Heavily damped | Cardboard box |
| 10-50 | Moderate | Wood panel, drum |
| 50-200 | Resonant | Guitar body, glass |
| 200-1000 | Very resonant | Bell, crystal |
| > 1000 | Extremely resonant | Tuning fork |

## Limitations

- Passive mode requires the tap to excite all modes. Some modes
  need excitation at specific points on the object.
- Active mode: headphones are a poor broadband exciter below 100 Hz.
  Use a subwoofer for low-frequency room mode hunting.
- Q estimation from -3 dB bandwidth is approximate. True Q requires
  fitting an exponential decay curve.
- Closely-spaced modes may merge into one broader peak.

## Requirements

- `numpy`, `scipy`, `matplotlib`
- `sounddevice` (for live modes)
