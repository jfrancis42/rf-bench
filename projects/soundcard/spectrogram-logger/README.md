# spectrogram-logger — Wideband Audio Spectrogram Logger

Continuous FFT of soundcard input saved as PNG spectrogram images on a
configurable rotation interval. Produces a visual record of band
activity with very low storage cost — one PNG per hour instead of
gigabytes of raw audio.

## Usage

```bash
# Log spectrograms hourly, default settings
python spectrogram_logger.py --input-device 2

# Log every 15 minutes to a specific directory
python spectrogram_logger.py --input-device 2 --interval 15 --output-dir /data/spectrograms

# Daily rotation with label
python spectrogram_logger.py --input-device 2 --interval daily --label "repeater-147.000"

# Higher frequency resolution (larger FFT)
python spectrogram_logger.py --fft-size 4096

# Wider dynamic range, different colormap
python spectrogram_logger.py --dynamic-range-db 80 --colormap inferno

# Run for exactly 2 hours then stop
python spectrogram_logger.py --duration 7200

# Test mode — generates synthetic activity and produces a sample PNG
python spectrogram_logger.py --test --output-dir /tmp

# Test with custom settings
python spectrogram_logger.py --test --fft-size 4096 --colormap magma --label "demo"
```

## Flags

### Spectrogram

- `--fft-size N` — FFT size in samples (default 2048). Larger = better
  frequency resolution, fewer time columns per second.
- `--interval INTERVAL` — File rotation: `hourly`, `daily`, or a number
  of minutes (e.g., `15`). Default: `hourly`.
- `--colormap CMAP` — Matplotlib colormap name (default `viridis`).
  Good alternatives: `inferno`, `magma`, `plasma`, `hot`, `jet`.
- `--dynamic-range-db DB` — Dynamic range floor below 0 dBFS (default
  60). Signals below this threshold are clipped to the floor color.
- `--label STR` — Label string included in the filename and image
  title. Useful for identifying what is being monitored.
- `--duration SEC` — Total run time in seconds. Omit to run
  indefinitely until Ctrl-C.
- `--output-dir DIR` — Directory for PNG output (default: current
  directory). Created if it does not exist.

### Standard audio flags

- `--input-device ID` — input device (use `--list-devices` to find)
- `--samplerate HZ` — sample rate (default 48000)
- `--blocksize N` — block size (default 2048)
- `--channels-in N` — input channels (default 1)
- `--list-devices` — list available audio devices and exit
- `--test` — generate synthetic test spectrogram without audio hardware
- `--test-duration SEC` — test signal length (default 5.0, not used;
  test mode uses its own 60-second synthetic signal)

## Storage estimation

PNG file sizes depend on image complexity (more activity = more
entropy = larger files). Typical values at default settings (2048-point
FFT, 48 kHz, 150 DPI):

| Interval | Columns/image | Typical PNG size | Daily storage |
|----------|---------------|-----------------|---------------|
| 15 min | ~21,000 | 150-400 KB | 14-38 MB |
| Hourly | ~84,000 | 400-900 KB | 10-22 MB |
| Daily | ~2,000,000 | 2-6 MB | 2-6 MB |

Compared to raw audio (48 kHz, float32): 675 MB/hour, 16 GB/day.
The spectrogram logger reduces storage by 1000x or more while
retaining visual information about band activity.

## Use cases

### Identifying interference

Leave the logger running on a frequency plagued by interference.
The spectrogram reveals the time pattern (e.g., every 30 seconds),
spectral signature (narrowband carrier vs broadband), and duration
of interference events. Compare day and night patterns to identify
time-correlated sources (solar panels, HVAC, lighting).

### Documenting repeater activity

Monitor a VHF/UHF repeater output with the logger. Over days or
weeks, the spectrograms reveal usage patterns: busy hours, kerchunks,
interference events, deviation levels (visible as spectral width).
Label with the repeater frequency for easy identification.

### Spotting band openings

Monitor a VHF frequency normally devoid of signals. When propagation
opens (tropo, sporadic-E), distant stations appear in the spectrogram.
Review hours of monitoring in seconds by scanning the PNG images.
Correlate with propagation prediction tools.

### HF band monitoring

Record the audio output of an HF receiver tuned to a band segment.
The spectrogram shows signal activity, QRM, atmospheric noise
variations, and band opening/closing times without requiring
continuous operator attention.

### Equipment qualification

Connect a receiver to a known-quiet antenna port (terminated) and
log overnight. The spectrogram reveals spurs, birdies, and
internally-generated interference that might not be obvious during
brief manual observations.

## Output format

PNG filenames follow the pattern:
```
spectrogram_[label_]YYYYMMDD_HHMMSS.png
```

Each PNG includes:
- Time axis (horizontal): seconds from interval start
- Frequency axis (vertical): 0 to Nyquist (kHz)
- Color: dBFS magnitude (colormap-dependent)
- Title: label (if set) + UTC start/end timestamps
- Colorbar with dBFS scale

## Frequency resolution

Resolution = samplerate / fft_size:

| FFT size | Resolution (at 48 kHz) |
|----------|----------------------|
| 1024 | 46.9 Hz |
| 2048 | 23.4 Hz (default) |
| 4096 | 11.7 Hz |
| 8192 | 5.9 Hz |

Larger FFT size gives finer frequency resolution but fewer time
columns per second (coarser time resolution).

## Dependencies

- numpy
- sounddevice (live audio)
- matplotlib (PNG rendering)
- dsp_pipeline (parent directory)
