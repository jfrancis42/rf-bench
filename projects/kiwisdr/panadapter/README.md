# panadapter — IC-7300 + KiwiSDR Live Spectrum Panadapter

Reads the IC-7300's operating frequency via Hamlib rigctld, tunes the KiwiSDR to
match, and displays a live ASCII waterfall spectrum in the terminal.  The waterfall
scrolls upward; the most recent spectrum trace is shown at the top.

## Requirements

- IC-7300 connected via USB (`/dev/ttyUSB0`)
- Hamlib `rigctld` running:
  ```bash
  rigctld -m 3073 -r /dev/ttyUSB0 -s 115200
  ```
- KiwiSDR reachable on the network
- `rf-bench-drivers-kiwisdr` (`pip install rf-bench-drivers-kiwisdr`)
- `numpy`

## How it works

1. Every `--refresh` seconds, send `\f\n` to rigctld (TCP port 4532) to read the
   current VFO A frequency
2. Tune the KiwiSDR to that frequency (passband centered on the VFO)
3. Capture `max(SAMPLE_RATE, refresh × SAMPLE_RATE)` IQ samples (~1 second minimum)
4. Apply a Hanning window, compute FFT, normalize to dBFS
5. Render one row of the waterfall using block characters `▁▂▃▄▅▆▇█`
6. Scroll the display and print frequency scale

## Limitation

The KiwiSDR covers 0–30 MHz only.  If the IC-7300 is tuned above 30 MHz (e.g. 6m),
the script prints a warning and holds the last valid KiwiSDR position.

## IQ recording

Use `--record-s N` to capture N seconds of IQ to a raw float32 file:

```
recordings/iq_14225000Hz_20260603_142233.f32
```

Format: interleaved float32 I/Q samples at 12,000 S/s.  Load in Python:

```python
import numpy as np
data = np.fromfile("iq_14225000Hz_20260603_142233.f32", dtype=np.float32)
iq = data[0::2] + 1j * data[1::2]   # complex64
```

## Usage

```bash
# Default: follow IC-7300, 10 kHz span, 100 ms refresh
python panadapter.py

# Wider span, slower refresh
python panadapter.py --span 20000 --refresh 0.5

# Remote KiwiSDR and remote rigctld
python panadapter.py --kiwi-host 10.1.0.5 --rigctld-host 192.168.1.10

# Taller waterfall, more history
python panadapter.py --waterfall-lines 40

# Record 60 seconds of IQ
python panadapter.py --record-s 60 --rec-dir /tmp/iq
```

## CLI reference

| Option | Default | Description |
|--------|---------|-------------|
| `--kiwi-host` | `kiwisdr.local` | KiwiSDR hostname or IP |
| `--kiwi-port` | `8073` | KiwiSDR port |
| `--kiwi-password` | _(empty)_ | KiwiSDR password |
| `--rigctld-host` | `localhost` | rigctld host |
| `--rigctld-port` | `4532` | rigctld port |
| `--span` | `10000` | Displayed frequency span in Hz |
| `--refresh` | `0.1` | Update interval in seconds |
| `--waterfall-lines` | `20` | Scrolling history lines |
| `--rbw` | `50` | Resolution bandwidth hint in Hz |
| `--record-s` | `0` | Record IQ for N seconds (0 = off) |
| `--rec-dir` | `recordings/` | IQ recording directory |
| `--no-color` | off | Disable ANSI colours |

## Example output

```
  Panadapter  14:22:33  |  VFO: 14225.000 kHz  USB  |  KiwiSDR: 14225.000 kHz  |  span: 10000 Hz

  ────────────────────────────────────────────────────────────────────────────────
  ░░░░░░▁▁░░░░░░░░░░░░░░░░▃▄▃░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░
  ────────────────────────────────────────────────────────────────────────────────
  ░░░░░░▁▁░░░░░░░░░░░░░░░░▃▄▃░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░
  ░░░░░░▁░░░░░░░░░░░░░░░░░▂▃▂░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░
  ░░░░░░░░░░░░░░░░░░░░░░░░▁▂▁░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░
  14220.00     14221.25     14222.50     14223.75     14225.00  kHz

  noise: -68.3 dBFS  peak: -44.1 dBFS  S/N: 24.2 dB  floor: -95  ceil: -41
```

## rigctld protocol note

The Hamlib rigctld netctl protocol is used:
- `\f\n` → returns current VFO frequency in Hz, e.g. `14225000\n`
- `\m\n` → returns mode and passband, e.g. `USB\n3000\n`

Start rigctld before launching the panadapter.  If rigctld is not running, the
script warns and uses the last known frequency until rigctld comes back.
