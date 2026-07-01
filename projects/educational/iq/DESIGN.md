# IQ Modulation / Demodulation — Educational Project

## Purpose

Two command-line programs that teach IQ (In-phase / Quadrature) signal
processing by converting real audio into baseband IQ files and back.

- `modulate.py` — reads audio (WAV file or microphone), applies AM/FM/USB/LSB
  modulation, outputs complex baseband IQ.
- `demodulate.py` — reads IQ (file or stdin pipe), applies the matching
  demodulation algorithm, outputs real audio (WAV file or speaker).

Target audience: someone who knows Python and numpy but has never worked with
radio signals. Every algorithm choice optimizes for clarity and inspectability.

Dependencies: `numpy`, `scipy`, `sounddevice`, `soundfile`.

---

## Architecture

```
                        modulate.py
  ┌─────────────────────────────────────────────────────────────┐
  │                                                             │
  │  Audio Source          Processing (48 kHz)      Output      │
  │  ───────────          ──────────────────────    ──────      │
  │                                                             │
  │  WAV file ─┐          ┌─ Bandpass FIR ─┐                   │
  │            ├─ Resample ┤                ├─ Modulate ─┐      │
  │  Mic ─────┘  to 48k   └─ Compressor ───┘   (mode)   │      │
  │                                                      │      │
  │                         ┌─ Decimate 6:1 (48k→8k) ───┘      │
  │                         │                                   │
  │                         └─ complex64 ─┬─ .iq file           │
  │                                       └─ stdout (pipe)      │
  └─────────────────────────────────────────────────────────────┘

                       demodulate.py
  ┌─────────────────────────────────────────────────────────────┐
  │                                                             │
  │  IQ Source             Processing              Output       │
  │  ─────────             ──────────              ──────       │
  │                                                             │
  │  .iq file ─┐                                               │
  │            ├─ complex64 ─ Demodulate ─ Interpolate 1:6 ─┐  │
  │  stdin ────┘              (mode)       (8k→48k)         │  │
  │                                                         │  │
  │                           ┌─ AGC ─ LPF ────────────────┘  │
  │                           │                                │
  │                           └─ float32 ─┬─ .wav file         │
  │                                       └─ speaker           │
  └─────────────────────────────────────────────────────────────┘

                       pipe mode
  ┌────────────────────────────────────────────────────────┐
  │                                                        │
  │  modulate.py --mode usb --stdout | demodulate.py --mode usb --stdin │
  │                                                        │
  │  raw complex64 bytes flow over the Unix pipe           │
  │  no framing, no headers — just continuous samples      │
  └────────────────────────────────────────────────────────┘
```

---

## File Format Decision

**Format:** Raw interleaved `complex64` (IEEE 754 float32 I, float32 Q pairs).

**Extension:** `.iq`

**Companion metadata:** Optional `.json` sidecar with the same stem name.

### Rationale

| Consideration | Decision | Why |
|---------------|----------|-----|
| Inspectability | float32 complex64 | `np.fromfile("x.iq", dtype=np.complex64)` yields a complex array instantly. Values are in [-1, 1]. No scaling, no byte-order confusion. |
| Metadata | Separate `.json` sidecar | Students can ignore it entirely. No binary header to parse. Human-readable with any text editor. |
| Why not SigMF | Too much overhead for baseband | SigMF is designed for RF captures with center frequency, antenna gain, GPS. This is baseband educational audio — SigMF's mandatory fields are meaningless here. |
| Why not WAV | WAV is real-valued | WAV can store stereo (I=L, Q=R) but the I/Q nature is implicit. A complex64 binary file makes the complex nature explicit — students see one complex number per sample. |
| Tool compatibility | numpy native | No extra libraries needed to load. `matplotlib` can plot directly. |

### Sidecar JSON format

```json
{
    "sample_rate": 8000,
    "dtype": "complex64",
    "modulation": "usb",
    "source_file": "voice.wav",
    "source_rate": 48000,
    "created": "2026-07-01T14:30:00Z",
    "description": "USB modulation of voice recording"
}
```

The modulator writes this automatically. The demodulator reads it for defaults
(mode, sample rate) but all parameters can be overridden on the command line.

---

## Sample Rates

| Stage | Rate | Rationale |
|-------|------|-----------|
| Input audio | 44100 or 48000 Hz | Whatever the source provides |
| Internal processing | 48000 Hz | Integer ratio to output (48000/8000 = 6). Modern soundcards default to 48 kHz. No fractional resampler needed for mic input. |
| IQ output | 8000 Hz complex | Specified by project requirements |

### Resampling strategy

- **48 kHz WAV input:** No resampling needed. Proceed directly.
- **44.1 kHz WAV input:** Resample to 48000 via `scipy.signal.resample_poly(audio, 160, 147)`. The ratio 160/147 = 48000/44100 exactly. Done once upfront before processing.
- **Other rates:** `resample_poly(audio, 48000 // gcd, source_rate // gcd)`.
- **48 kHz to 8 kHz:** Decimate by 6 via `resample_poly(iq, 1, 6)`. The anti-alias filter is built into `resample_poly`.

The bandpass filter (300-3000 Hz for voice modes) already limits bandwidth well
below the 4000 Hz Nyquist of the 8 kHz output, so the decimation anti-alias
filter in `resample_poly` has an easy job.

---

## DSP Chain — Modulation

### Common input stage (all modes)

```python
# 1. Load and normalize
audio = soundfile.read(path)           # or sounddevice stream
audio = audio / np.max(np.abs(audio))  # normalize to [-1, 1]

# 2. Resample to 48 kHz if needed
if source_rate != 48000:
    from math import gcd
    g = gcd(48000, source_rate)
    audio = resample_poly(audio, 48000 // g, source_rate // g)

# 3. Bandpass filter (voice modes: 300-3000 Hz)
taps = firwin(255, [300, 3000], pass_zero=False, fs=48000)
audio = lfilter(taps, 1.0, audio)

# 4. Optional compression
audio = np.tanh(audio * drive)  # soft-clip, drive=1.0-3.0
```

### AM (Double-Sideband Full Carrier)

```
audio → scale to modulation_index → add DC carrier → output as complex

IQ:  I = (1 + m*audio),  Q = 0
     equivalently: iq = (1 + m*audio) + 0j
```

```python
def modulate_am(audio, mod_index=0.8):
    """AM: carrier + two sidebands. mod_index in [0, 1]."""
    iq = (1.0 + mod_index * audio).astype(np.complex64)
    return iq  # Q channel is zero (real-only carrier at DC)
```

**Demod:** Envelope detection = `np.abs(iq)`, then subtract DC and normalize.

### FM (Narrowband, 2.5 kHz deviation)

```
audio → integrate (cumsum) → exp(j*phase) → output complex

IQ:  phase(t) = 2*pi*deviation * integral(audio)
     I = cos(phase), Q = sin(phase)
     equivalently: iq = exp(j * phase)
```

```python
def modulate_fm(audio, deviation_hz=2500, sample_rate=48000):
    """NBFM: constant envelope, frequency varies with audio."""
    sensitivity = 2 * np.pi * deviation_hz / sample_rate
    phase = np.cumsum(audio * sensitivity)
    iq = np.exp(1j * phase).astype(np.complex64)
    return iq
```

**Demod:** Conjugate-multiply discriminator:
```python
def demodulate_fm(iq, deviation_hz=2500, sample_rate=8000):
    """FM discriminator: instantaneous frequency from phase difference."""
    # Each sample's phase change = instantaneous frequency
    discriminator = np.angle(iq[1:] * np.conj(iq[:-1]))
    audio = discriminator / (2 * np.pi * deviation_hz / sample_rate)
    return audio
```

Why conjugate-multiply over unwrap+diff: no accumulated phase state to carry
between blocks. Each output sample depends only on two adjacent input samples.
Better for streaming.

### USB (Upper Sideband)

```
audio → analytic signal (Hilbert) → output complex

The analytic signal has zero negative-frequency content.
USB = "transmit only the upper sideband" = positive frequencies only = analytic signal.
```

```python
def modulate_usb(audio):
    """USB: keep positive frequencies, discard negative."""
    analytic = scipy.signal.hilbert(audio)  # complex: real=audio, imag=hilbert(audio)
    return analytic.astype(np.complex64)
```

**Why the phasing (Hilbert) method over Weaver:**
- One function call (`scipy.signal.hilbert`) vs two mixers + a critical LPF
- The concept maps directly to frequency-domain intuition: "zero out negative frequencies"
- Students can verify by FFT-ing the output and seeing one-sided spectrum
- No DC-hole artifact that Weaver introduces
- Weaver's two-stage mixing maps to analog hardware, not to numpy code

**Demod:** Take the real part. Optionally frequency-shift first if there's an
offset, but at baseband (carrier = 0 Hz), demod is just `audio = iq.real`.

```python
def demodulate_usb(iq):
    """USB demod: the real part of the analytic signal IS the original audio."""
    return iq.real.astype(np.float32)
```

### LSB (Lower Sideband)

```
audio → analytic signal → conjugate → output complex

Conjugating flips the spectrum: positive frequencies become negative and vice versa.
LSB = "transmit only the lower sideband" = negative frequencies only = conjugate of analytic.
```

```python
def modulate_lsb(audio):
    """LSB: keep negative frequencies, discard positive."""
    analytic = scipy.signal.hilbert(audio)
    return np.conj(analytic).astype(np.complex64)
```

**Demod:**
```python
def demodulate_lsb(iq):
    """LSB demod: conjugate back, then take real part."""
    return np.conj(iq).real.astype(np.float32)
    # equivalent to: iq.real (since conj doesn't change real part)
    # but conceptually: "flip spectrum back, extract audio"
```

Note: For SSB at baseband (carrier = 0 Hz), USB demod and LSB demod both reduce
to taking the real part of the IQ signal. The difference is in the *modulator*:
USB preserves the original frequency relationships, LSB inverts them. The
demodulator must match so the spectrum flip is undone.

---

## DSP Chain — Demodulation (common output stage)

```python
# 1. Demodulate (mode-specific, produces 8 kHz real audio)
audio_8k = demodulate_X(iq_block)

# 2. Interpolate 8 kHz → 48 kHz
audio_48k = resample_poly(audio_8k, 6, 1)

# 3. AGC (leaky peak detector)
audio_48k = agc.process(audio_48k)

# 4. Low-pass filter (remove interpolation artifacts above 3.5 kHz)
audio_48k = lfilter(output_lpf_taps, 1.0, audio_48k)

# 5. Output
soundfile.write("output.wav", audio_48k, 48000)  # or sounddevice playback
```

---

## FM Deviation Analysis

At 8 kHz IQ sample rate:
- Nyquist = 4000 Hz
- Maximum representable instantaneous frequency = +/- 4000 Hz

With 2.5 kHz deviation and 2700 Hz audio bandwidth:
- Carson's rule BW = 2 * (2500 + 2700) = 10.4 kHz
- This exceeds the 8 kHz total bandwidth, but Carson's rule defines 98% power
  containment, not a hard cutoff. The spectral rolloff is steep beyond the main FM lobe.
- The conjugate-multiply demodulator recovers frequency from phase difference between
  adjacent samples. As long as the phase change per sample stays below pi radians
  (which corresponds to Fs/2 = 4000 Hz deviation), there's no ambiguity.
- At 2500 Hz deviation with peaks at full modulation: max phase change =
  2*pi*2500/8000 = 1.96 radians — well below pi (3.14). No aliasing.

**Conclusion:** 2500 Hz deviation is safe. Maximum safe deviation at 8 kHz is
theoretically 4000 Hz (phase change = pi), but 2500 Hz provides margin and
matches the amateur radio NBFM standard (VHF/UHF repeaters use exactly 2.5 kHz).

---

## CLI Interface

### modulate.py

```
usage: modulate.py [-h] --mode {am,fm,usb,lsb}
                   [--input INPUT] [--mic]
                   [--output OUTPUT] [--stdout]
                   [--rate RATE] [--deviation DEVIATION]
                   [--mod-index MOD_INDEX]
                   [--compress DRIVE] [--no-filter]
                   [--block-size BLOCK_SIZE]

IQ Modulator — convert audio to baseband IQ

required arguments:
  --mode {am,fm,usb,lsb}    Modulation type

input (one required):
  --input INPUT              Input WAV file path
  --mic                      Use default microphone (48 kHz)

output (default: file based on input name):
  --output OUTPUT            Output .iq file path
  --stdout                   Write raw complex64 to stdout (for piping)

processing options:
  --rate RATE                Output IQ sample rate in Hz (default: 8000)
  --deviation DEVIATION      FM deviation in Hz (default: 2500, FM mode only)
  --mod-index MOD_INDEX      AM modulation index 0.0-1.0 (default: 0.8, AM only)
  --compress DRIVE           Compressor drive 1.0-5.0 (default: 1.5, 1.0=off)
  --no-filter                Skip input bandpass filter
  --block-size BLOCK_SIZE    Samples per processing block (default: 512)
```

### demodulate.py

```
usage: demodulate.py [-h] --mode {am,fm,usb,lsb}
                     [--input INPUT] [--stdin]
                     [--output OUTPUT] [--speaker]
                     [--rate RATE] [--deviation DEVIATION]
                     [--agc | --no-agc]
                     [--block-size BLOCK_SIZE]

IQ Demodulator — convert baseband IQ back to audio

required arguments:
  --mode {am,fm,usb,lsb}    Demodulation type

input (one required):
  --input INPUT              Input .iq file path (reads companion .json for defaults)
  --stdin                    Read raw complex64 from stdin (for piping)

output (default: file based on input name):
  --output OUTPUT            Output WAV file path (48 kHz, 16-bit)
  --speaker                  Play through default speaker

processing options:
  --rate RATE                Input IQ sample rate in Hz (default: 8000 or from .json)
  --deviation DEVIATION      FM deviation in Hz (default: 2500, FM mode only)
  --agc                      Enable AGC (default: enabled)
  --no-agc                   Disable AGC
  --block-size BLOCK_SIZE    Samples per processing block (default: 512)
```

### Examples

```bash
# Modulate a voice recording as USB, write to file
python modulate.py --mode usb --input voice.wav --output voice_usb.iq

# Modulate from mic as FM, pipe directly to demodulator, play on speaker
python modulate.py --mode fm --mic --stdout | python demodulate.py --mode fm --stdin --speaker

# Roundtrip test: modulate then demodulate, compare with original
python modulate.py --mode am --input test.wav --output test_am.iq
python demodulate.py --mode am --input test_am.iq --output test_roundtrip.wav

# Inspect the IQ file in Python:
# >>> import numpy as np
# >>> iq = np.fromfile("voice_usb.iq", dtype=np.complex64)
# >>> print(f"{len(iq)} samples, {len(iq)/8000:.1f} seconds")
# >>> import matplotlib.pyplot as plt
# >>> plt.plot(iq.real[:200], label="I"); plt.plot(iq.imag[:200], label="Q"); plt.legend()
```

---

## Streaming Protocol

**Format:** Raw `complex64` bytes. No framing. No headers. No length prefixes.

**Byte order:** Native (little-endian on x86-64 Linux). Since both ends run on
the same machine, byte order is never an issue.

**Flow:**
1. Modulator writes 4096-byte chunks (512 complex64 samples) to stdout.
2. Demodulator reads from stdin in 4096-byte chunks.
3. If a partial read occurs (pipe semantics allow short reads), the demodulator
   buffers until a full 4096-byte block is assembled.
4. On EOF (modulator exits or pipe closes), demodulator flushes any remaining
   partial block (zero-pad to 512 samples, process, truncate output).

**Why no framing:** This matches the Unix philosophy and how existing radio tools
work (`rtl_fm | sox`, `rtl_sdr | csdr`). A student can `dd` a chunk out of the
pipe, save it, and load it with `np.fromfile` — no parser needed.

**Stdout/stdin binary mode:** Both programs must set `sys.stdout.buffer` /
`sys.stdin.buffer` (not text-mode stdout). On Windows, also `msvcrt.setmode`.

---

## Block Sizes and Latencies

| Stage | Block size | Duration | Bytes |
|-------|-----------|----------|-------|
| Mic input (48 kHz) | 3072 samples | 64 ms | 12288 (float32) |
| Processing (48 kHz) | 3072 samples | 64 ms | — |
| IQ output (8 kHz) | 512 samples | 64 ms | 4096 (complex64) |
| Pipe transfer | 4096 bytes | 64 ms | 4096 |
| Demod input (8 kHz) | 512 samples | 64 ms | 4096 (complex64) |
| Audio output (48 kHz) | 3072 samples | 64 ms | 12288 (float32) |

**End-to-end pipe latency:** ~128 ms (one block buffered in modulator + one in
demodulator). Perceptible as slight delay but acceptable for educational use.
Real-time voice conversation is not a goal.

**Why 512 samples at 8 kHz:**
- 4096 bytes = one Linux page size (efficient pipe I/O)
- 64 ms duration — long enough for the FIR filter (255 taps) to operate without
  excessive edge-effect overhead per block
- After 6:1 decimation from 48 kHz, 512 output samples require 3072 input
  samples — a reasonable sounddevice blocksize
- Power of 2 — efficient for any FFT operations

**File mode:** When processing a complete WAV file (not streaming), the entire
file is loaded, processed in one shot (no blocking), and written. Block processing
is only used for mic/speaker/pipe streaming.

---

## Key Implementation Notes

### FIR filter state for streaming

When processing block-by-block, the FIR filter needs to carry state between
blocks (the "tail" from the previous block). Use `scipy.signal.lfilter` with
the `zi` parameter:

```python
from scipy.signal import firwin, lfilter, lfilter_zi

taps = firwin(255, [300, 3000], pass_zero=False, fs=48000)
zi = lfilter_zi(taps, 1.0) * 0  # initial state = zero

# per block:
filtered, zi = lfilter(taps, 1.0, block, zi=zi)
```

### FM modulator phase continuity

For streaming FM, the phase accumulator must carry between blocks:

```python
class FMModulator:
    def __init__(self, deviation_hz=2500, sample_rate=48000):
        self.sensitivity = 2 * np.pi * deviation_hz / sample_rate
        self.phase = 0.0  # carries between blocks

    def process(self, audio_block):
        phase_increments = audio_block * self.sensitivity
        phases = self.phase + np.cumsum(phase_increments)
        self.phase = phases[-1] % (2 * np.pi)  # wrap to avoid float overflow
        return np.exp(1j * phases).astype(np.complex64)
```

### Hilbert transform for streaming SSB

`scipy.signal.hilbert()` uses a full-length FFT — unsuitable for block
streaming. For streaming SSB, use an FIR Hilbert filter instead:

```python
from scipy.signal import remez

# Design a 127-tap FIR Hilbert transformer
n_taps = 127  # must be odd
bands = [100 / 24000, 3500 / 24000]  # passband edges (normalized to Nyquist)
hilbert_taps = remez(n_taps, bands, [1], type='hilbert')

# Per block: apply FIR to get quadrature component
# I channel = original audio (delayed by (n_taps-1)//2 samples)
# Q channel = hilbert FIR output
q = lfilter(hilbert_taps, 1.0, audio_block, zi=hilbert_zi)
i = np.roll(audio_block, -(n_taps - 1) // 2)  # compensate group delay
iq = (i + 1j * q).astype(np.complex64)
```

For file-based (non-streaming) processing, `scipy.signal.hilbert()` is simpler
and produces a perfect analytic signal. The FIR approximation is only needed for
the streaming pipe case.

### AGC implementation

```python
class AGC:
    """Leaky peak-detector AGC with fast attack, slow decay."""

    def __init__(self, sample_rate=48000, attack_ms=5.0, decay_ms=300.0,
                 target=0.5, min_gain=0.01, max_gain=100.0):
        self.attack_coeff = 1.0 - np.exp(-1.0 / (attack_ms * sample_rate / 1000))
        self.decay_coeff = 1.0 - np.exp(-1.0 / (decay_ms * sample_rate / 1000))
        self.target = target
        self.min_gain = min_gain
        self.max_gain = max_gain
        self.level = 0.1  # smoothed envelope estimate

    def process(self, block):
        """Apply AGC to a block of real audio samples."""
        envelope = np.abs(block)
        output = np.empty_like(block)

        for i in range(len(block)):
            # Track envelope with asymmetric smoothing
            if envelope[i] > self.level:
                self.level += self.attack_coeff * (envelope[i] - self.level)
            else:
                self.level += self.decay_coeff * (envelope[i] - self.level)

            # Compute and apply gain
            gain = self.target / (self.level + 1e-10)
            gain = np.clip(gain, self.min_gain, self.max_gain)
            output[i] = block[i] * gain

        return output
```

The per-sample loop is intentionally not vectorized — clarity over speed.
For a numpy-vectorized version (10-100x faster), see the "advanced" section
in the implementation.

### Compression (tanh soft-clipper)

```python
def compress(audio, drive=1.5):
    """Soft compression: tanh saturation curve.

    drive=1.0: no compression (tanh is nearly linear for |x|<0.5)
    drive=2.0: moderate compression
    drive=4.0: heavy compression (sounds like AM radio)
    """
    return np.tanh(audio * drive) / np.tanh(drive)  # normalize so peak=1.0
```

The `/ np.tanh(drive)` normalization ensures that a full-scale input still
produces a full-scale output regardless of drive setting. Without it, higher
drive values would reduce overall level.

### numpy/scipy function summary

| Task | Function | Why this one |
|------|----------|-------------|
| Bandpass filter design | `scipy.signal.firwin(N, [lo, hi], pass_zero=False, fs=fs)` | Linear phase, intuitive Hz params, single call |
| Filter application | `scipy.signal.lfilter(taps, 1.0, x, zi=state)` | Streaming-friendly with state |
| Hilbert (file mode) | `scipy.signal.hilbert(x)` | Returns analytic signal directly |
| Hilbert (streaming) | `scipy.signal.remez(N, bands, [1], type='hilbert')` | FIR approximation for blocks |
| Resample 44.1k→48k | `scipy.signal.resample_poly(x, 160, 147)` | Exact integer ratio, built-in anti-alias |
| Decimate 48k→8k | `scipy.signal.resample_poly(x, 1, 6)` | Integer ratio, proper anti-alias FIR |
| Interpolate 8k→48k | `scipy.signal.resample_poly(x, 6, 1)` | Integer ratio, proper reconstruction |
| FM mod phase | `np.cumsum(audio * sensitivity)` | Phase = integral of frequency |
| FM demod | `np.angle(iq[1:] * np.conj(iq[:-1]))` | Conjugate-multiply discriminator |
| Complex exponential | `np.exp(1j * phase)` | I=cos, Q=sin in one call |
| AM envelope | `np.abs(iq)` | Magnitude of complex = envelope |

### File I/O patterns

```python
# Writing IQ file
iq_data.astype(np.complex64).tofile("output.iq")

# Writing companion metadata
import json
meta = {"sample_rate": 8000, "dtype": "complex64", "modulation": "usb"}
with open("output.json", "w") as f:
    json.dump(meta, f, indent=2)

# Reading IQ file
iq = np.fromfile("output.iq", dtype=np.complex64)

# Reading from stdin (streaming)
chunk = sys.stdin.buffer.read(4096)  # 512 complex64 samples
if len(chunk) == 4096:
    block = np.frombuffer(chunk, dtype=np.complex64)

# Writing to stdout (streaming)
block.astype(np.complex64).tobytes()
sys.stdout.buffer.write(block.tobytes())
sys.stdout.buffer.flush()
```

### Edge cases and robustness

- **Empty/silent input:** Modulator outputs carrier-only (AM: DC=1.0, FM:
  constant phase, SSB: silence). No crash on zero-length input.
- **Clipping:** Input audio is hard-clipped to [-1, 1] after normalization.
  The compressor (if enabled) soft-limits before this point.
- **Partial pipe reads:** Demodulator accumulates bytes in a buffer until a
  full 4096-byte block is ready. Partial blocks at EOF are zero-padded.
- **Ctrl-C:** Both programs register SIGINT handler for clean shutdown (flush
  output, close files, print summary to stderr).
- **Stereo input:** If WAV is stereo, mix to mono: `audio = (L + R) / 2`.

---

## Project File Layout

```
projects/educational/iq/
├── modulate.py          Main modulator script
├── demodulate.py        Main demodulator script
├── DESIGN.md            This document
├── requirements.txt     numpy, scipy, sounddevice, soundfile
└── examples/
    └── roundtrip.sh     Demo script: modulate → demodulate → compare
```
