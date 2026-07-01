# acoustic-magnifier — Acoustic Magnifying Glass

Extreme narrowband gain: pick a 50 Hz-wide band anywhere in the
spectrum, amplify it 40-60 dB, suppress everything else. Sweep it
around like tuning a radio.

## What it does

Isolates a tiny slice of the audio spectrum and makes it loud. You
can "tune" to individual sounds in a complex environment:

- At 60 Hz: hear every transformer and ground loop on the block
- At 120 Hz: fluorescent ballasts, dimmers, bad power supplies
- At 800 Hz: isolate one voice from background chatter
- At 2000 Hz: pick out individual cricket species
- At 4000 Hz: locate ultrasonic equipment whine

It's like having a radio receiver for the acoustic world.

## Usage

```bash
# Fixed at 1 kHz, 50 Hz bandwidth, 40 dB gain
python acoustic_magnifier.py --input-device 2 --output-device 2

# Narrow in on 60 Hz hum
python acoustic_magnifier.py --center 60 --bandwidth 20 --gain 50

# Wide band at 4 kHz (crickets)
python acoustic_magnifier.py --center 4000 --bandwidth 200

# Auto-sweep mode: scan 100-8000 Hz in 10 seconds
python acoustic_magnifier.py --sweep

# Sweep a narrower range slowly
python acoustic_magnifier.py --sweep --sweep-start 50 --sweep-end 500 --sweep-time 20

# Maximum gain (careful with headphone volume!)
python acoustic_magnifier.py --center 2000 --gain 60

# Test mode
python acoustic_magnifier.py --test --center 800
```

## Flags

- `--center HZ` — center frequency (default: 1000)
- `--bandwidth HZ` — passband width (default: 50)
- `--gain DB` — gain applied to the selected band (default: 40)
- `--sweep` — enable automatic frequency sweep
- `--sweep-start HZ` — sweep range start (default: 100)
- `--sweep-end HZ` — sweep range end (default: 8000)
- `--sweep-time SECS` — time for one complete sweep (default: 10)
- Standard audio device flags

## Live display

Shows current frequency, output level, and a level bar. In sweep
mode, the frequency updates continuously as it scans.

```
   1000 Hz |  -12.3 dB | ██████████████████
```

## Sweep mode

Automatically scans from --sweep-start to --sweep-end (log-spaced)
then back, continuously. Like slowly turning a radio dial across
the acoustic spectrum. You hear each frequency band for a moment
as the sweep passes through.

The sweep is logarithmic — spends equal time on each octave,
matching human frequency perception.

## Discovery guide

| Frequency | What you'll find |
|-----------|-----------------|
| 50-60 Hz | Mains hum (EU/US), ground loops |
| 100-120 Hz | 2nd harmonic of mains, machinery |
| 200-400 Hz | Engine rumble, HVAC, wind resonance |
| 400-800 Hz | Speech fundamental range |
| 800-2000 Hz | Speech formants, bird calls |
| 2000-4000 Hz | Crickets, electronics, tinnitus freq |
| 4000-8000 Hz | Insect wings, CRT whine, water trickle |
| 8000-16000 Hz | Bat clicks, capacitor singing |

## Safety note

**Reduce headphone volume before starting.** 40-60 dB of gain on a
narrow band can produce very loud output if there's energy at the
selected frequency. Start with low gain and increase.

## Limitations

- 50 Hz bandwidth is the practical minimum for real-time response
  (narrower filters ring for too long, creating latency).
- Very sharp filters have transient ringing — percussive sounds at
  the center frequency produce a "ping" effect.
- Sweep mode has audible artifacts at the transition between
  frequencies (filter redesign causes brief discontinuity).

## Requirements

- `numpy`, `scipy`
- `sounddevice`
