# triggered-recorder — Triggered Audio Recorder

Continuously buffers audio in a ring buffer. When signal energy exceeds
a threshold, saves pre-trigger + post-trigger audio to a timestamped
file. Captures interesting signals without recording hours of dead air.

## Usage

```bash
# Basic: record any signal above -30 dBFS
python triggered_recorder.py --input-device 2

# Sensitive threshold for weak signals
python triggered_recorder.py --threshold-db -40

# Long pre-trigger to capture signal onset
python triggered_recorder.py --pre-trigger 10 --post-trigger 15

# FLAC output for smaller files
python triggered_recorder.py --format flac --output-dir ./captures

# Label captures (e.g., frequency or band)
python triggered_recorder.py --label "144MHz" --output-dir ./vhf

# Test mode: generates bursts and gaps, writes captures to disk
python triggered_recorder.py --test --threshold-db -20

# List audio devices
python triggered_recorder.py --list-devices
```

## Flags

- `--threshold-db DBFS` -- trigger level (default -30). Signal peak
  must exceed this to start recording.
- `--pre-trigger SEC` -- seconds of audio buffered before trigger
  (1-30, default 3). Captures the signal onset.
- `--post-trigger SEC` -- seconds to continue recording after signal
  drops below threshold (1-60, default 5). Captures the signal tail
  and prevents choppy recordings from brief dropouts.
- `--format {wav,flac}` -- output format (default wav). FLAC is
  lossless but ~40-60% smaller.
- `--output-dir PATH` -- directory for recordings (default current
  directory). Created if it does not exist.
- `--label TEXT` -- optional text appended to filenames.
- Standard audio input flags: `--input-device`, `--samplerate`,
  `--blocksize`, `--channels-in`

## Recording Workflow

1. Audio streams continuously from the soundcard at 48 kHz float32.
2. Each block (1024 samples = ~21 ms) is checked for peak level.
3. When idle: blocks are pushed into a ring buffer holding
   `--pre-trigger` seconds of history.
4. When peak exceeds `--threshold-db`: trigger fires.
   - Ring buffer contents become the pre-trigger portion.
   - New blocks are appended to the recording.
5. While triggered: if signal stays above threshold, the post-trigger
   hang timer resets (re-trigger). A continuous signal produces one
   long file, not many short ones.
6. When signal drops and hang timer expires: recording is finalized
   and written to disk. Ring buffer resets.
7. On Ctrl-C: any in-progress recording is flushed and saved.

## File Naming

Files are named with UTC timestamp at trigger onset:

```
YYYYMMDD_HHMMSS.wav
YYYYMMDD_HHMMSS_label.flac
```

Examples:
```
20260630_143022.wav
20260630_143022_2m.flac
20260630_150811_40m-cw.wav
```

## Storage Estimation

At 48 kHz, 16-bit mono:

| Duration | WAV size | FLAC size (~55%) |
|----------|----------|------------------|
| 10 s     | 960 KB   | ~530 KB          |
| 30 s     | 2.9 MB   | ~1.6 MB          |
| 60 s     | 5.8 MB   | ~3.2 MB          |
| 5 min    | 29 MB    | ~16 MB           |

With default settings (3s pre + 5s post = minimum 8s per capture):
- Minimum capture size: ~768 KB WAV, ~420 KB FLAC
- 1000 captures at ~10s average: ~960 MB WAV, ~530 MB FLAC

## Tips

- Set `--threshold-db` just above your noise floor. Use the live
  peak display (shown during operation) to gauge levels.
- For radio monitoring: connect radio audio output to soundcard input.
  Set threshold above squelch tail noise.
- For RF lab work: trigger on signal generator output through a
  detector/demodulator chain.
- `--post-trigger` should be longer than expected signal gaps (e.g.,
  pauses between words in voice, gaps between CW characters).
- FLAC saves disk space with zero quality loss. Use it for long
  monitoring sessions.
