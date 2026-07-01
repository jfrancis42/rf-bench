# vad-squelch — Voice Activity Detection Squelch

Audio-domain squelch that opens ONLY for human speech. Ignores data
bursts (RTTY, SSTV, packet), CW, pager tones, and noise. Useful for
scanner feeds, busy repeaters with mixed voice/data traffic, or HF
monitoring where you want speech-only recording/alerting.

## Detection features

Four independent classifiers vote on whether the current audio is
human speech:

1. **Spectral shape (30%)** — speech has formant peaks (F1 ~300–900
   Hz, F2 ~900–2500 Hz, F3 ~2500–3500 Hz). Data and noise have flat
   or wrong-shaped envelopes.

2. **Periodicity / pitch (35%)** — voiced speech has strong
   autocorrelation at fundamental frequency (80–400 Hz). Noise and
   data modes do not. Highest-weighted feature.

3. **Zero-crossing rate variability (15%)** — speech alternates
   between high ZCR (unvoiced consonants) and low ZCR (vowels). Noise
   has uniformly high ZCR; tones have uniformly low ZCR.

4. **Syllabic modulation (20%)** — speech amplitude varies at 3–8 Hz
   (syllabic rate). Steady carriers, data, and noise lack this.

The weighted sum produces a confidence score (0–1). When above
threshold, the squelch opens. Hang timer prevents choppy operation
between words.

## Usage

```bash
# Real-time on scanner audio
python vad_squelch.py --input-device 2 --output-device 4

# More sensitive (lower threshold)
python vad_squelch.py --threshold 0.35

# Longer hang time for slow speakers
python vad_squelch.py --hang-ms 500

# Test: speech + CW + noise sequence
python vad_squelch.py --test --output gated.wav
```

## Flags

- `--threshold FLOAT` — confidence threshold 0–1 (default 0.5).
  Lower = more sensitive (may open on music). Higher = stricter.
- `--hang-ms MS` — hold squelch open after speech stops (default
  300 ms). Prevents choppy operation between words.
- `--attack-ms MS` — gate opening speed (default 10 ms)
- `--release-ms MS` — gate closing speed (default 50 ms)
- `--output WAV` — save gated output (test mode)
- Standard audio flags

## Threshold tuning

| Threshold | Opens on |
|-----------|----------|
| 0.3 | Speech, loud music, some whistle tones |
| 0.5 | Speech only (default) |
| 0.7 | Clear speech only (ignores distant/noisy speech) |

## Limitations

- Block-based detection (21 ms blocks at default settings). Cannot
  detect speech faster than one block. First syllable may be clipped
  by a few ms — the attack time and a slightly lower threshold help.
- Singing / music with strong pitch can trigger detection. Not a
  music-vs-speech classifier; it's a speech-vs-data classifier.
- Very noisy speech (poor SNR) reduces all feature scores. At low
  SNR, the VAD becomes unreliable — same as human hearing.
- Pre-emphasized speech (high-frequency boost, common in FM) may
  reduce the spectral-shape score. Adjust threshold if needed.
- Not a replacement for the WebRTC VAD neural network for
  production use, but this implementation has zero dependencies
  beyond numpy/scipy and no model files.
