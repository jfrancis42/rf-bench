# scheduled-recorder — Scheduled Audio Recorder

Cron-friendly audio recorder with metadata tagging and optional radio
auto-tune via Hamlib rigctld. Records for a specified duration, starting
immediately or at a scheduled time.

## Usage

```bash
# Record 60 seconds immediately, default WAV format
python scheduled_recorder.py --duration 60

# Record at 14:30 local time, 5 minutes, FLAC output
python scheduled_recorder.py --duration 300 --at 14:30:00 --format flac

# Tune to 7074 kHz, label it, save to a specific directory
python scheduled_recorder.py --duration 600 --frequency 7074 \
    --label "FT8-40m" --output-dir ~/recordings/ --mode USB

# Full ISO datetime scheduling
python scheduled_recorder.py --duration 120 --at 2026-07-01T03:00:00 \
    --frequency 10000 --label "WWV" --antenna "dipole-40m"

# Test mode (no hardware needed)
python scheduled_recorder.py --duration 5 --test --label "test-run"
```

## Flags

### Required

- `--duration SEC` — Recording duration in seconds

### Scheduling

- `--at TIME` — Start time: `HH:MM:SS` or `YYYY-MM-DDTHH:MM:SS`.
  If omitted, recording starts immediately. Time-only values use
  today's date; if the time has already passed, schedules for tomorrow.

### Output

- `--output-dir DIR` — Output directory (default: current dir)
- `--label TEXT` — Label included in filename and metadata
- `--format {wav,flac}` — Output format (default: wav).
  WAV uses float32; FLAC uses PCM_24.

### Radio control

- `--frequency KHZ` — Tune radio to this frequency via rigctld before
  recording
- `--rigctld-host HOST` — rigctld hostname (default: localhost)
- `--rigctld-port PORT` — rigctld port (default: 4532)

### Metadata tags

- `--mode MODE` — Operating mode (USB, LSB, CW, FM, AM, etc.)
- `--antenna TEXT` — Antenna description
- `--notes TEXT` — Free-form notes

### Audio (standard dsp_pipeline flags)

- `--input-device ID` — Soundcard input device
- `--samplerate HZ` — Sample rate (default: 48000)
- `--blocksize N` — Block size (default: 1024)
- `--channels-in N` — Input channels (default: 1)
- `--list-devices` — List audio devices and exit
- `--test` — Generate synthetic audio (no hardware)
- `--test-duration SEC` — Test signal duration (unused here; --duration
  controls length)

## Cron examples

```crontab
# Record WWV at the top of every hour for 30 seconds
0 * * * * cd /home/user/recordings && python /path/to/scheduled_recorder.py --duration 30 --frequency 10000 --label WWV --mode AM

# Record 40m FT8 window every 15 minutes, 2 minutes each
*/15 * * * * cd /home/user/recordings && python /path/to/scheduled_recorder.py --duration 120 --frequency 7074 --label FT8-40m --mode USB --format flac

# Record 80m at night (0300-0305 UTC) for propagation study
0 3 * * * cd /home/user/recordings && python /path/to/scheduled_recorder.py --duration 300 --frequency 3573 --label "FT8-80m-night" --mode USB
```

## Output files

Each recording produces two files:

1. **Audio file**: `YYYYMMDD_HHMMSS_label.wav` (or `.flac`)
2. **Metadata sidecar**: `YYYYMMDD_HHMMSS_label.wav.json`

### Metadata JSON format

```json
{
  "file": "20260701_030000_WWV.wav",
  "start_utc": "2026-07-01T03:00:00+00:00",
  "end_utc": "2026-07-01T03:00:30+00:00",
  "start_local": "2026-06-30 21:00:00",
  "end_local": "2026-06-30 21:00:30",
  "duration_sec": 30.0,
  "samplerate": 48000,
  "channels": 1,
  "format": "wav",
  "dtype": "float32",
  "blocksize": 1024,
  "samples_recorded": 1440000,
  "label": "WWV",
  "frequency_khz": 10000.0,
  "mode": "AM",
  "antenna": "dipole-40m",
  "radio": {
    "tuned_hz": 10000000,
    "frequency_hz": 10000000,
    "mode": "AM",
    "passband_hz": 6000
  },
  "peak_dbfs": -3.2,
  "rms_dbfs": -18.4
}
```

## Radio integration

When `--frequency` is provided, the script connects to rigctld (Hamlib
network daemon) and sends a set-frequency command before recording.
It also queries the radio's current mode and passband for the metadata.

rigctld must already be running:

```bash
# IC-7300
rigctld -m 3073 -r /dev/ttyUSB0 -s 115200 &

# FT-891
rigctld -m 1036 -r /dev/ttyUSB0 -s 38400 &

# IC-9700
rigctld -m 3081 -r /dev/ttyUSB0 -s 115200 &
```

The connection to rigctld is opened and closed for each command (no
persistent connection). This keeps the script cron-friendly and avoids
issues with stale sockets.

## Dependencies

- numpy
- sounddevice (live recording)
- soundfile (WAV/FLAC writing)
- dsp_pipeline (sibling package, for TestSignal and argparse helpers)

## Limitations

- No real-time monitoring or level display during recording (use
  `soundcard-cal` or `snr-meter` for that).
- FLAC encoding happens after recording completes (all audio buffered
  in RAM). For very long recordings (>30 min at 48 kHz mono), this
  uses ~330 MB RAM.
- The `--at` scheduler is a simple sleep loop. For complex scheduling
  (multiple recordings per day, skip weekends, etc.), use cron.
- Radio tune failures are logged as warnings but do not abort the
  recording. Check the metadata `radio.tune_error` field.
