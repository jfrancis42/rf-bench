# lms-noise-cancel — LMS Adaptive Noise Cancellation

Two-input adaptive noise canceller using the Widrow LMS algorithm.
Requires a primary input (signal + noise) and a reference input
(noise only, correlated with the noise in the primary). The algorithm
adapts an FIR filter to predict the noise contribution and subtract it.

## When to use

- Fan noise, AC hum, or computer noise that can be picked up by a
  separate reference microphone placed near the noise source
- Any situation where you have access to a signal correlated with the
  interference but NOT with the desired signal
- Works on non-stationary noise (unlike spectral subtraction)

## Setup

```
Radio/Signal → Left channel (or mic 1) → Primary input
Noise source → Right channel (or mic 2) → Reference input
```

The reference mic should be close to the noise source and far from
the signal source. The closer the reference is to pure noise (no
desired signal leakage), the better the cancellation.

## Usage

```bash
# Real-time with stereo input (L=primary, R=reference)
python lms_noise_cancel.py --input-device 2 --output-device 4

# NLMS (normalized LMS) for faster convergence
python lms_noise_cancel.py --nlms --input-device 2 --output-device 4

# More taps for longer noise paths (e.g., room reflections)
python lms_noise_cancel.py --taps 256 --mu 0.005

# Test mode
python lms_noise_cancel.py --test --test-duration 10 --output cleaned.wav
```

## Flags

- `--taps N` — adaptive filter length (default 128). More taps
  handles longer delay paths between reference and primary noise.
  More taps = slower convergence, more computation.
- `--mu STEP` — LMS step size (default 0.01 for LMS, 0.5 for NLMS).
  Larger = faster adaptation but less stable. Too large → divergence.
- `--nlms` — use Normalized LMS (divides step by signal power).
  Converges faster and is less sensitive to mu setting.
- `--leakage FACTOR` — weight leakage (default 0.9999). Prevents
  unbounded weight growth. Set closer to 1.0 for more stable
  cancellation; closer to 0.99 for faster forgetting.
- `--output WAV` — write processed audio to file (test mode).
- Standard audio flags: `--input-device`, `--output-device`,
  `--samplerate`, `--blocksize`, `--list-devices`, `--test`.

## LMS vs NLMS

- **LMS:** simpler, fixed step size. Works well when noise power is
  relatively constant. Sensitive to mu selection — too high diverges,
  too low converges slowly.
- **NLMS:** normalizes the step by instantaneous reference power.
  Self-adjusting convergence rate. Generally preferred unless you
  have reason to hand-tune mu.

## Limitations

- Requires two audio inputs. If you only have one input (radio audio
  only, no reference mic), use spectral subtraction instead.
- Per-sample processing loop in Python — higher CPU load than FFT-
  based methods for large tap counts. At 128 taps and 48 kHz, CPU
  load is manageable on any modern machine.
- Reference signal must NOT contain the desired signal. If the
  reference mic picks up your voice (e.g., in a small room), the
  algorithm will try to cancel your voice too.
- Convergence takes a few hundred milliseconds. During initial
  adaptation, noise passes through.
