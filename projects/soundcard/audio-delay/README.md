# audio-delay — Precision Audio Delay Line

Adds a precise, adjustable delay (0–2000 ms) to the audio path.

## Use cases

- **Synchronize multiple audio sources** — align a WebSDR feed with
  a local radio (WebSDR has ~200 ms latency)
- **Test echo cancellation** — generate a known delay for algorithm
  validation
- **Simulate propagation delay** — EME round-trip (~2.5 s), satellite
  (~500 ms), HF ionospheric (~10 ms)
- **Break-in delay matching** — sync CW sidetone with actual TX audio
- **A/B testing** — align processed vs unprocessed audio for fair
  comparison

## Usage

```bash
# 100 ms delay (default)
python audio_delay.py --input-device 2 --output-device 4

# WebSDR sync: 250 ms to match network latency
python audio_delay.py --delay-ms 250

# EME round-trip simulation
python audio_delay.py --delay-ms 2500

# Test mode: verify delay accuracy
python audio_delay.py --test --delay-ms 50

# Write delayed audio
python audio_delay.py --test --delay-ms 100 --output delayed.wav
```

## Flags

- `--delay-ms MS` — delay in milliseconds (default 100). Range
  0–2000. Precision is 1 sample (0.021 ms at 48 kHz).
- `--output WAV` — save delayed audio (test mode)
- Standard audio flags

## Verification

In test mode, the script verifies delay accuracy via cross-correlation
between input and output signals. Expected and measured delays are
printed — they should match to within 1 sample.

## Limitations

- Maximum delay is limited by available memory. At 48 kHz stereo
  float32, 2000 ms = 384 KB. Not a concern on any modern system.
- Delay is fixed at startup. Changing delay during operation (via
  `set_delay_ms()` API) is supported programmatically but not via
  CLI flag yet.
- No fractional-sample delay (interpolation). Delay precision is
  exactly 1 sample = 20.8 μs at 48 kHz. For sub-sample precision,
  a polyphase interpolation filter would be needed (overkill for
  audio synchronization).
