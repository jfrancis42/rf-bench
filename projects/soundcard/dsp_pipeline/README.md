# dsp_pipeline — Shared Real-Time Audio DSP Framework

Common infrastructure for all `projects/soundcard/` tools. Provides
audio I/O, a processing-block chain, synthetic test signals, and
shared CLI flags so every project gets consistent device selection
and `--test` mode for free.

## Architecture

```
AudioStream (sounddevice wrapper)
    ↓ audio blocks
Pipeline (chains N DSPBlocks)
    ↓ processed blocks
AudioStream output (or file/PDF)
```

### Core classes

- **`AudioStream`** — wraps `sounddevice` for real-time input,
  output, or duplex. Handles device selection, sample rate, block
  size, channel count.
- **`DSPBlock`** — base class. Subclass and override `process(samples)`
  to implement your algorithm. Maintains per-block state, can be
  enabled/disabled at runtime.
- **`Pipeline`** — ordered list of DSPBlocks. `process_block()` runs
  one chunk through all stages. `run_realtime()` wires it to an
  AudioStream and blocks until Ctrl-C. `process_array()` runs offline
  on a numpy array.
- **`TestSignal`** — factory for synthetic test signals: sine, noise,
  CW, sweep, IQ, speech-like, hum, heterodyne, DTMF, impulse noise,
  etc.

### Shared argparse helpers

```python
from dsp_pipeline import add_audio_args, add_test_args, open_stream_from_args

parser = argparse.ArgumentParser()
add_audio_args(parser)      # --input-device, --output-device, --samplerate, etc.
add_test_args(parser)       # --test, --test-duration
args = parser.parse_args()
```

## Usage pattern

Every project follows the same skeleton:

```python
import sys, argparse
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from dsp_pipeline import Pipeline, TestSignal, add_audio_args, add_test_args

class MyFilter(DSPBlock):
    def process(self, samples):
        # your DSP here
        return filtered

def main():
    p = argparse.ArgumentParser()
    add_audio_args(p)
    add_test_args(p)
    args = p.parse_args()

    pipeline = Pipeline([MyFilter(samplerate=args.samplerate)])

    if args.test:
        sig = TestSignal(args.samplerate, args.test_duration).signal_plus_noise()
        pipeline.run_test(sig, output_device=args.output_device)
    else:
        pipeline.run_realtime(args.input_device, args.output_device)
```

## Dependencies

- `sounddevice` (PortAudio wrapper)
- `numpy`
- `scipy` (used by individual blocks, not the framework itself)
