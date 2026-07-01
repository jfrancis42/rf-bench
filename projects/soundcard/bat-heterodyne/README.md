# bat-heterodyne — Ultrasonic Heterodyne Detector

Shifts ultrasonic audio (above 15 kHz) down into the audible range so
you can hear bat echolocation, insect wing-beats, capacitor whine,
switching power supply noise, and other sounds normally above human
hearing.

## How it works

At 48 kHz sample rate, the mic captures up to ~22 kHz. Many bats
echolocate at 20-45 kHz (we catch the lower edge), insects produce
ultrasonic clicks, and electronics emit whines at 15-22 kHz that
are inaudible but present in the audio stream.

### Heterodyne mode (default)

Classic bat-detector approach: multiply the input by a local oscillator
(sine wave at the "tuning" frequency). This produces sum and difference
frequencies. A low-pass filter keeps only the difference, shifting the
ultrasonic content down. Tuning the LO to 20 kHz means a bat call at
21 kHz becomes audible at 1 kHz.

### Frequency division mode

Count zero crossings of the high-passed signal, output a pulse every
N crossings. This divides ALL ultrasonic frequencies by the ratio
(default 10×). A 20 kHz signal becomes 2 kHz. Preserves temporal
structure (FM sweeps sound like FM sweeps, just lower) but compresses
the entire ultrasonic spectrum into a narrow band.

## Usage

```bash
# Basic heterodyne, tuned to 20 kHz
python bat_heterodyne.py --input-device 2 --output-device 2

# Tune higher (for detecting higher-frequency bats)
python bat_heterodyne.py --lo-freq 22000

# Frequency division mode (preserves temporal structure)
python bat_heterodyne.py --mode divide --division 10

# Wider output bandwidth
python bat_heterodyne.py --output-bw 6000

# Mix some original audio in (hear both normal + ultrasonic)
python bat_heterodyne.py --mix-original 0.3

# More gain for weak ultrasonic signals
python bat_heterodyne.py --gain 20

# Test mode (synthetic bat pulses)
python bat_heterodyne.py --test
```

## Flags

- `--mode {heterodyne,divide}` — detection method (default: heterodyne)
- `--lo-freq HZ` — local oscillator frequency (default: 20000)
- `--output-bw HZ` — output low-pass bandwidth (default: 4000)
- `--division N` — frequency division ratio for divide mode (default: 10)
- `--highpass HZ` — input high-pass cutoff (default: 15000)
- `--gain N` — gain multiplier for ultrasonic content (default: 10)
- `--mix-original 0-1` — mix original audio into output (default: 0)
- Standard audio device flags

## Live display

While running, shows a real-time level meter of ultrasonic energy and
the frequency of the strongest ultrasonic peak. Useful for sweeping
the mic around to locate ultrasonic sources.

## What you can hear

| Source | Typical frequency | Character |
|--------|------------------|-----------|
| Pipistrelle bat | 45-48 kHz (below 48k capture) | Rapid chirps |
| Brown long-eared bat | 20-50 kHz | Quiet, rapid clicks |
| Myotis species | 30-80 kHz | FM sweeps |
| Grasshoppers | 10-30 kHz | Rhythmic rasps |
| Switching PSU | 15-22 kHz | Steady whine |
| CRT monitors | 15.7 kHz | Constant tone |
| LED dimmers | 20-40 kHz | Buzzy tone |
| Ceramic capacitors | 16-20 kHz | Singing under load |

## Limitations

- 48 kHz sample rate limits capture to ~22 kHz. Many bats echolocate
  higher. For serious bat work, use a 192 kHz or 384 kHz USB interface.
- Cheap electret mics roll off above 15 kHz. A MEMS mic (e.g.,
  Knowles SPH0645) or a dedicated bat mic extends to 100+ kHz.
- Heterodyne mode only hears one narrow band at a time (like tuning
  a radio). Division mode hears the whole ultrasonic spectrum at once.

## Requirements

- `numpy`, `scipy`
- `sounddevice`
- A microphone with reasonable response above 15 kHz
