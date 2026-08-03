# IQ Modulation / Demodulation — Educational Project

Learn how radios encode and decode audio by building the complete signal
chain in Python. Three programs: one modulates audio into IQ (the internal
language of software-defined radios), one simulates realistic HF propagation
effects, and one demodulates it back.

## What you'll learn

- What IQ (In-phase / Quadrature) signals are and why radios use them
- How AM, FM, USB, and LSB modulation work at the sample level
- How the Hilbert transform creates single-sideband signals
- How FM encodes information in frequency rather than amplitude
- How AGC (Automatic Gain Control) keeps volume consistent
- How to work with complex-valued signals in numpy
- How decimation and interpolation change sample rates without aliasing
- How HF propagation affects signals (fading, multipath, noise, interference)
- What the Watterson channel model is and why HF selective fading exists
- Why signals sound different on different bands and at different times

## Quick start

```bash
pip install numpy scipy sounddevice soundfile

# Modulate a WAV file as Upper Sideband
python modulate.py --mode usb --input voice.wav

# Demodulate back to audio
python demodulate.py --mode usb --input voice_usb.iq --output roundtrip.wav

# Real-time: mic → modulate → demodulate → speaker (pipe mode)
python modulate.py --mode fm --mic --stdout | python demodulate.py --mode fm --stdin --speaker

# With realistic HF propagation effects
python modulate.py --mode usb --input voice.wav --stdout \
  | python hf-static.py --preset moderate \
  | python demodulate.py --mode usb --stdin --speaker
```

## Shell script (easy mode)

```bash
# Play any audio file through the full chain
./play-iq.sh audiobook.mp3

# With HF conditions
./play-iq.sh --preset rough audiobook.mp3

# Clean (no HF effects)
./play-iq.sh --clean audiobook.mp3

# FM mode with aurora preset
./play-iq.sh -m fm --preset aurora podcast.wav
```

## Modes

| Mode | What it does | Real-world use |
|------|-------------|----------------|
| `am` | Amplitude modulation (envelope varies) | AM broadcast radio, aircraft |
| `fm` | Frequency modulation (frequency varies) | FM broadcast, VHF/UHF repeaters |
| `usb` | Upper sideband (half the AM bandwidth) | HF radio above 10 MHz, VHF/UHF |
| `lsb` | Lower sideband (mirror of USB) | HF radio below 10 MHz |

## HF Channel Simulator

The `hf-static.py` filter sits in the pipe between modulator and
demodulator, adding realistic propagation effects:

```
modulate.py --stdout | hf-static.py [OPTIONS] | demodulate.py --stdin --speaker
```

### Effects modeled

| Effect | What it does | Real-world cause |
|--------|-------------|-----------------|
| Thermal noise (AWGN) | Background hiss | Electron motion in receiver |
| Atmospheric static (QRN) | Impulsive crashes/pops | Distant lightning |
| Rayleigh fading | Slow amplitude variation | Ionospheric multipath |
| Watterson channel | Selective fading (hollow/watery sound) | Different frequencies fade independently |
| Flutter fading | Rapid buzzing/growling | Aurora, aircraft scatter |
| Long-path echo | Delayed copy of signal | Signal traveling around Earth |
| Ionospheric chirp | Slow pitch drift | Traveling ionospheric disturbances |
| D-layer absorption | Signal weakening/blackout | Solar flares, daytime propagation |
| Power line noise | 60 Hz buzz | Arcing insulators |
| Heterodyne | Steady whistle | Nearby CW station |
| Splatter | Distorted voice garbage | Overdriven nearby transmitter |
| Band noise coloring | Low-frequency rumble | Band-specific noise character |

### Presets

| Preset | Description |
|--------|-------------|
| `clear` | Strong signal, quiet band (20m winter morning) |
| `moderate` | Typical daytime 40m (default) |
| `rough` | Disturbed conditions, deep fading |
| `dx` | Weak DX signal with long-path echo |
| `aurora` | Auroral propagation, rapid flutter |
| `contest` | Crowded band with heterodynes and splatter |
| `summer-80m` | Crushing atmospheric noise |
| `geomagnetic-storm` | Near-blackout conditions |

### Passthrough mode

```bash
# No effects — clean pipe for A/B comparison
hf-static.py --passthrough
```

## File format

Output is raw `complex64` (interleaved float32 I/Q pairs) at 8000 samples/second.

```python
import numpy as np
iq = np.fromfile("voice_usb.iq", dtype=np.complex64)
print(f"{len(iq)} samples = {len(iq)/8000:.1f} seconds")
```

A companion `.json` sidecar records metadata (mode, sample rate, source file).

## Architecture

```
MODULATOR (modulate.py):
  Audio file / mic
       │
       ▼
  Resample to 48 kHz
       │
       ▼
  Bandpass filter (300-3000 Hz)
       │
       ▼
  Compressor (tanh soft-clip)
       │
       ▼
  Modulate (AM / FM / USB / LSB)
       │
       ▼
  Decimate 6:1 (48 kHz → 8 kHz)
       │
       ▼
  complex64 .iq file (or stdout pipe)


HF CHANNEL (hf-static.py):
  IQ stream from stdin
       │
       ▼
  Ionospheric chirp (frequency drift)
       │
       ▼
  Frequency offset (tuning error)
       │
       ▼
  Watterson selective fading (multipath)
       │
       ▼
  Rayleigh flat fading
       │
       ▼
  Flutter fading (auroral/aircraft)
       │
       ▼
  D-layer absorption
       │
       ▼
  Long-path echo
       │
       ▼
  Thermal noise (AWGN)
       │
       ▼
  Band noise coloring
       │
       ▼
  Atmospheric static (QRN)
       │
       ▼
  Power line noise
       │
       ▼
  QRM (heterodyne / splatter)
       │
       ▼
  IQ stream to stdout


DEMODULATOR (demodulate.py):
  .iq file (or stdin pipe)
       │
       ▼
  Demodulate (AM / FM / USB / LSB)
       │
       ▼
  Interpolate 1:6 (8 kHz → 48 kHz)
       │
       ▼
  AGC (automatic gain control)
       │
       ▼
  Lowpass filter
       │
       ▼
  .wav file (or speaker playback)
```

## Examples

```bash
# AM with heavy compression (sounds like AM broadcast radio)
python modulate.py --mode am --input music.wav --compress 3.0 --mod-index 0.9

# FM with narrow deviation (like a walkie-talkie)
python modulate.py --mode fm --input voice.wav --deviation 2500

# Wide audio bandwidth (no filter, for music)
python modulate.py --mode usb --input music.wav --no-filter

# Demodulate with AGC disabled (hear the raw level variations)
python demodulate.py --mode am --input music_am.iq --no-agc --speaker

# Barely-readable DX station
python modulate.py --mode usb --input voice.wav --stdout \
  | python hf-static.py --preset dx \
  | python demodulate.py --mode usb --stdin --speaker

# Contest pileup with interference
python modulate.py --mode usb --input voice.wav --stdout \
  | python hf-static.py --preset contest --snr 12 \
  | python demodulate.py --mode usb --stdin --speaker

# Custom: lots of static, some fading, no other interference
python modulate.py --mode usb --input voice.wav --stdout \
  | python hf-static.py --snr 10 --qrn 12 --fading 0.5 --no-heterodyne --no-splatter \
  | python demodulate.py --mode usb --stdin --speaker

# Inspect IQ in Python:
python -c "
import numpy as np
import matplotlib.pyplot as plt
iq = np.fromfile('voice_usb.iq', dtype=np.complex64)
fig, axes = plt.subplots(3, 1, figsize=(10, 8))
axes[0].plot(iq.real[:500], label='I (in-phase)')
axes[0].plot(iq.imag[:500], label='Q (quadrature)')
axes[0].legend()
axes[0].set_title('Time domain')
axes[1].plot(np.abs(iq[:500]))
axes[1].set_title('Envelope (magnitude)')
axes[2].magnitude_spectrum(iq[:2048], Fs=8000)
axes[2].set_title('Spectrum')
plt.tight_layout()
plt.savefig('iq_analysis.png')
print('Saved iq_analysis.png')
"
```

## Streaming (pipe mode)

Connect modulator to demodulator via Unix pipe for near-real-time
listen-through (~128 ms latency):

```bash
python modulate.py --mode usb --mic --stdout | python demodulate.py --mode usb --stdin --speaker
```

With HF effects:

```bash
python modulate.py --mode usb --mic --stdout \
  | python hf-static.py --preset moderate \
  | python demodulate.py --mode usb --stdin --speaker
```

The pipe carries raw `complex64` bytes — no headers, no framing. This
matches how real SDR tools work (`rtl_fm | sox`, `rtl_sdr | csdr`).

## USB handset PTT button

A C-Media USB handset (e.g. the TEC H-250, USB `0d8c:aaa0`) exposes its
push-to-talk button on a raw HID interface. `ptt.py` reads it, and
`modulate.py --ptt` gates audio on it (hold to talk; off by default).

```bash
./ptt.py                 # print PRESSED / released as you press the button
./ptt.py --find          # show the resolved hidraw path

# Push-to-talk intercom-style monitoring (audio only while button held):
python modulate.py --mode usb --mic --device Handset --ptt --stdout \
  | python demodulate.py --mode usb --stdin --device Handset --speaker
```

### Stable device name + non-root access (udev rule)

By default the button's hidraw node has an unpredictable number
(`/dev/hidraw4`, etc.) and root-only or `audio`-group permissions. The
included **`99-h250-ptt.rules`** fixes both: it creates a stable
`/dev/h250-ptt` symlink and grants read access to the `input` group.

```bash
sudo cp 99-h250-ptt.rules /etc/udev/rules.d/
sudo udevadm control --reload-rules
sudo udevadm trigger --subsystem-match=hidraw
# then replug the handset (or reboot) so the symlink appears

ls -l /dev/h250-ptt
./ptt.py --device /dev/h250-ptt
```

`ptt.py` and `modulate.py --ptt` auto-detect the handset by its USB
VID:PID, so the rule is a convenience (stable name, guaranteed perms),
not a requirement.

## Dependencies

- **numpy** — array math, complex arithmetic
- **scipy** — FIR filter design, Hilbert transform, resampling
- **sounddevice** — microphone input, speaker output
- **soundfile** — reading WAV/MP3/OGG/FLAC files
