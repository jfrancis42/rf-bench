# speech-compressor — Real-Time SSB Speech Processor

Multi-stage audio processing chain for SSB transmit. Increases average
speech power by 6-10 dB without increasing peak power — equivalent to
an outboard speech processor (Heil ProSet, W2IHY EQplus, Timewave
DSP-599zx).

Feed the output to your radio's line-in, USB audio input, or data port
for SSB/AM transmit. The chain removes low-frequency rumble, compresses
dynamic range, clips to raise average power, and filters clipper
harmonics to prevent adjacent-channel splatter.

## Usage

```bash
# Real-time with default settings (4:1 compression, soft clip at -6 dB)
python speech_compressor.py --input-device 2 --output-device 4

# Aggressive DX contesting settings
python speech_compressor.py --ratio 6 --threshold-db -25 --clip-db -3 --clip-mode hard

# Mild ragchew settings (natural sound, moderate compression)
python speech_compressor.py --ratio 3 --threshold-db -15 --clip-db -9

# Widen passband for AM transmit
python speech_compressor.py --highpass-freq 100 --lowpass-freq 4000

# Narrow for CW-bandwidth SSB (mic compression for QRP)
python speech_compressor.py --lowpass-freq 2400 --ratio 8 --clip-db -3

# Test mode: process synthetic speech, write WAV, show stats
python speech_compressor.py --test --output compressed.wav

# Reduce output level to avoid overdriving radio input
python speech_compressor.py --output-level-db -6
```

## Flags

### Compressor settings

- `--ratio N` — compression ratio (default 4:1). Higher = more
  compression. 2:1 is gentle, 8:1 is heavy limiting.
- `--threshold-db DB` — compression threshold in dBFS (default -20).
  Signals above this level are compressed. Lower = more compression.
- `--attack-ms MS` — compressor attack time (default 5 ms). How fast
  gain reduction kicks in.
- `--release-ms MS` — compressor release time (default 50 ms). How
  fast gain returns after signal drops below threshold.

### Clipper settings

- `--clip-db DB` — clipper threshold in dBFS (default -6). Lower
  value = more clipping = more average power but more distortion.
- `--clip-mode {hard,soft}` — hard clips flat-top the waveform; soft
  uses tanh saturation for smoother harmonics (default soft).

### Filter settings

- `--highpass-freq HZ` — high-pass cutoff (default 200 Hz). Removes
  rumble, plosives, AC hum below this frequency.
- `--lowpass-freq HZ` — low-pass cutoff (default 2700 Hz). Removes
  clipper harmonics above this frequency. Set to match your radio's
  IF bandwidth.

### Output

- `--output-level-db DB` — final output gain in dB (default 0). Use
  negative values to reduce drive level to your radio.
- `--output WAV` — write processed audio to WAV file (test mode only).

### Standard flags

- `--input-device ID`, `--output-device ID` — sounddevice IDs
- `--samplerate HZ` — sample rate (default 48000)
- `--blocksize N` — block size (default 256 for low latency TX path)
- `--channels-in N`, `--channels-out N` — channel counts
- `--list-devices` — list audio devices and exit
- `--test` — use synthetic test signal instead of live audio
- `--test-duration SEC` — test signal duration (default 5 s)

## SSB Speech Processing Explained

SSB transmitters have a fixed peak envelope power (PEP) rating.
Unprocessed speech has a high peak-to-average ratio (12-15 dB) —
most of the time the transmitter is running well below its maximum
power. A speech processor raises the average power closer to the
peak, effectively giving you 6-10 dB more "talk power" without
exceeding PEP limits.

The processing chain:

1. **High-pass filter** — removes sub-vocal energy (room rumble,
   breath pops, 60 Hz hum) that wastes transmitter power on
   inaudible content.

2. **Compressor** — reduces dynamic range by attenuating loud
   syllables. The attack/release times are tuned for speech
   cadence. After compression, quiet syllables are relatively
   louder.

3. **Clipper** — the primary power-increasing stage. By clipping
   peaks, the average level increases dramatically. Hard clipping
   is more effective but harsher; soft clipping (tanh) generates
   lower-order harmonics and sounds more natural.

4. **Low-pass filter** — essential after clipping. The clipper
   generates wideband harmonics that would cause adjacent-channel
   interference (splatter). A steep low-pass at 2700 Hz removes
   these harmonics while preserving speech intelligibility.

5. **Output level** — matches the processor output to your radio's
   input sensitivity. Adjust to keep ALC just below activation.

## Typical Settings

| Use case | Ratio | Threshold | Clip dB | Mode | Notes |
|----------|-------|-----------|---------|------|-------|
| Casual ragchew | 3:1 | -15 | -9 | soft | Natural sound, mild processing |
| General SSB | 4:1 | -20 | -6 | soft | Good balance of power and quality |
| DX / contest | 6:1 | -25 | -3 | hard | Maximum punch, some distortion |
| QRP (low power) | 8:1 | -25 | -3 | hard | Every dB counts |
| AM broadcast | 3:1 | -18 | -6 | soft | Wider passband (--lowpass-freq 4000) |
| Digital voice prep | 4:1 | -20 | -9 | soft | Feed to CODEC2 or FreeDV |

## Latency

Default block size is 256 samples at 48 kHz = 5.3 ms per block.
Total processing latency is approximately one block (the IIR filters
add minimal group delay within the passband). Acceptable for real-time
TX — you will not hear an echo in sidetone.

## Limitations

- No AGC or makeup gain (use --output-level-db to adjust manually).
- Compressor is sample-by-sample (no look-ahead). Attack time means
  the very first transient of a syllable passes uncompressed.
- No ALC feedback from the radio — set output level by ear/meter.
- No sidechain EQ (frequency-dependent compression). All frequencies
  are compressed equally.
- No noise gate — in quiet passages, the compressor raises the noise
  floor. Use a VOX or manual PTT to avoid transmitting noise.
