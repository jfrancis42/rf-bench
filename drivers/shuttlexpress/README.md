# rf-bench-drivers-shuttlexpress

Linux driver for the Contour Design ShuttleXpress USB jog/shuttle controller.

## Hardware

The ShuttleXpress has three control types:

- **Jog wheel** (center, free-spinning) — relative encoder, one tick per detent
- **Shuttle ring** (outer, spring-loaded) — absolute position -7 to +7, returns to center
- **Buttons** (5) — momentary press/release

## Installation

```bash
pip install rf-bench-drivers-shuttlexpress
```

Requires Linux with evdev support. The user must be in the `input` group:

```bash
sudo usermod -aG input $USER
# log out and back in
```

## Usage

```python
from rf_bench.shuttlexpress import ShuttleXpress

shuttle = ShuttleXpress()  # auto-discovers device

@shuttle.on_jog
def jog(event):
    print(f"Jog: {event.value}")  # +1 or -1 per detent

@shuttle.on_shuttle
def shuttle_ring(event):
    print(f"Shuttle position: {event.value}")  # -7 to +7

@shuttle.on_button
def button(event):
    print(f"Button {event.value}: {event.type.value}")

shuttle.run()  # blocking; Ctrl-C to stop
```

### Threaded

```python
shuttle = ShuttleXpress()
# ... register callbacks ...
thread = shuttle.run_in_thread()
# do other work
shuttle.stop()
```

### Async

```python
import asyncio
from rf_bench.shuttlexpress import ShuttleXpress

async def main():
    shuttle = ShuttleXpress()
    # ... register callbacks ...
    await shuttle.run_async()

asyncio.run(main())
```

## Event Types

| Event | `event.type` | `event.value` |
|-------|-------------|---------------|
| Jog clockwise | `JOG` | +1 |
| Jog counter-clockwise | `JOG` | -1 |
| Shuttle ring moved | `SHUTTLE` | -7 to +7 (0 = center) |
| Button pressed | `BUTTON_PRESS` | 1-5 |
| Button released | `BUTTON_RELEASE` | 1-5 |

## Applications

- `projects/sunsdr/shuttle-tuner.py` — tune SunSDR2 Pro via TCI
- Any custom mapping: attenuator control, filter sweep, spectrum scroll
