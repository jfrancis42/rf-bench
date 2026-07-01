#!/usr/bin/env python3
"""
spectrogram_logger.py — Wideband audio spectrogram logger.

Continuous FFT of soundcard input saved as PNG spectrogram images on a
configurable rotation interval (hourly, daily, or custom minutes). Produces
a visual record of band activity with low storage cost — one PNG per hour
vs gigabytes of raw audio.

Time axis (horizontal), frequency axis (vertical), dBFS color intensity.
"""

from __future__ import annotations

import argparse
import signal
import sys
import time
import warnings
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

warnings.filterwarnings("ignore", message="Unable to import Axes3D")
import matplotlib  # noqa: E402
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from dsp_pipeline import TestSignal, add_audio_args, add_test_args  # noqa: E402


class SpectrogramAccumulator:
    """Accumulates FFT columns for spectrogram image generation."""

    def __init__(self, samplerate: int = 48000, blocksize: int = 2048,
                 fft_size: int = 2048, dynamic_range_db: float = 60.0):
        self.samplerate = samplerate
        self.blocksize = blocksize
        self.fft_size = fft_size
        self.dynamic_range_db = dynamic_range_db
        self._window = np.hanning(fft_size).astype(np.float32)
        self._columns: list[np.ndarray] = []
        # ring buffer for overlap if blocksize < fft_size
        self._buffer = np.zeros(fft_size, dtype=np.float32)
        self._buf_pos = 0

    @property
    def freqs(self) -> np.ndarray:
        """Frequency axis in Hz."""
        return np.fft.rfftfreq(self.fft_size, 1.0 / self.samplerate)

    @property
    def n_columns(self) -> int:
        return len(self._columns)

    def process(self, samples: np.ndarray) -> None:
        """Process a block of audio samples, accumulating FFT columns."""
        mono = samples[:, 0] if samples.ndim == 2 else samples

        n = len(mono)
        if n >= self.fft_size:
            # block large enough — use last fft_size samples
            self._buffer[:] = mono[-self.fft_size:]
            self._compute_and_store()
        else:
            # shift buffer left and append new samples
            self._buffer[:-n] = self._buffer[n:]
            self._buffer[-n:] = mono
            self._buf_pos += n
            if self._buf_pos >= self.fft_size:
                self._buf_pos = 0
                self._compute_and_store()

    def _compute_and_store(self) -> None:
        """Compute magnitude spectrum and store as a column."""
        windowed = self._buffer * self._window
        spectrum = np.abs(np.fft.rfft(windowed))
        # normalize: full-scale sine = 0 dBFS
        spectrum = spectrum / (self.fft_size / 2.0)
        with np.errstate(divide='ignore'):
            db = 20.0 * np.log10(np.maximum(spectrum, 1e-20))
        self._columns.append(db.astype(np.float32))

    def save_png(self, output_path: Path, colormap: str = "viridis",
                 label: str = "", start_time: datetime | None = None,
                 end_time: datetime | None = None) -> bool:
        """Render accumulated spectrogram to PNG. Returns True on success."""
        if not self._columns:
            return False

        # Build 2D array: frequency bins x time columns
        data = np.column_stack(self._columns)  # shape: (n_bins, n_columns)

        # Dynamic range clipping
        vmax = 0.0
        vmin = -self.dynamic_range_db

        fig, ax = plt.subplots(1, 1, figsize=(12, 6))

        # Time axis (seconds from start)
        n_cols = data.shape[1]
        duration_sec = n_cols * self.fft_size / self.samplerate
        extent = [0, duration_sec, self.freqs[0] / 1000.0, self.freqs[-1] / 1000.0]

        im = ax.imshow(data, aspect="auto", origin="lower", extent=extent,
                       vmin=vmin, vmax=vmax, cmap=colormap, interpolation="nearest")

        ax.set_xlabel("Time (seconds)")
        ax.set_ylabel("Frequency (kHz)")

        title = "Audio Spectrogram"
        if label:
            title = f"{title} — {label}"
        if start_time:
            title += f"\n{start_time.strftime('%Y-%m-%d %H:%M:%S')} UTC"
            if end_time:
                title += f" to {end_time.strftime('%H:%M:%S')} UTC"
        ax.set_title(title, fontsize=10)

        cbar = fig.colorbar(im, ax=ax, label="dBFS")
        cbar.ax.tick_params(labelsize=8)
        fig.tight_layout()
        fig.savefig(output_path, dpi=150, bbox_inches="tight")
        plt.close(fig)
        return True

    def reset(self) -> None:
        """Clear accumulated columns for next interval."""
        self._columns.clear()
        self._buffer[:] = 0
        self._buf_pos = 0


def _make_filename(output_dir: Path, label: str, timestamp: datetime) -> Path:
    """Generate output filename from label and timestamp."""
    ts_str = timestamp.strftime("%Y%m%d_%H%M%S")
    if label:
        return output_dir / f"spectrogram_{label}_{ts_str}.png"
    return output_dir / f"spectrogram_{ts_str}.png"


def _interval_seconds(interval: str) -> float:
    """Convert interval string to seconds."""
    if interval == "hourly":
        return 3600.0
    elif interval == "daily":
        return 86400.0
    else:
        # custom minutes
        return float(interval) * 60.0


def _run_test(args) -> int:
    """Generate a synthetic spectrogram demonstrating the tool."""
    print("Generating test spectrogram...", file=sys.stderr)

    # Create 60 seconds of synthetic activity
    duration = 60.0
    samplerate = args.samplerate
    ts = TestSignal(samplerate, duration)

    accumulator = SpectrogramAccumulator(
        samplerate=samplerate,
        blocksize=args.blocksize,
        fft_size=args.fft_size,
        dynamic_range_db=args.dynamic_range_db,
    )

    # Build a signal with varied activity:
    # - noise floor throughout
    # - 1 kHz tone from 5-20s
    # - 2.5 kHz tone from 15-35s
    # - sweep from 500 Hz to 8 kHz between 25-45s
    # - burst of 5 kHz at 50-55s
    n_samples = int(duration * samplerate)
    audio = np.zeros(n_samples, dtype=np.float32)

    # noise floor
    rng = np.random.default_rng(42)
    audio += 0.005 * rng.standard_normal(n_samples).astype(np.float32)

    t = np.arange(n_samples) / samplerate

    # 1 kHz tone, 5-20s
    mask = (t >= 5.0) & (t < 20.0)
    audio[mask] += 0.15 * np.sin(2 * np.pi * 1000.0 * t[mask]).astype(np.float32)

    # 2.5 kHz tone, 15-35s
    mask = (t >= 15.0) & (t < 35.0)
    audio[mask] += 0.10 * np.sin(2 * np.pi * 2500.0 * t[mask]).astype(np.float32)

    # sweep 500-8000 Hz, 25-45s
    sweep_start = int(25 * samplerate)
    sweep_end = int(45 * samplerate)
    sweep_dur = sweep_end - sweep_start
    sweep_t = np.arange(sweep_dur) / samplerate
    f_start, f_stop = 500.0, 8000.0
    phase = 2 * np.pi * f_start * (sweep_dur / samplerate) / np.log(f_stop / f_start) * (
        np.exp(sweep_t / (sweep_dur / samplerate) * np.log(f_stop / f_start)) - 1
    )
    audio[sweep_start:sweep_end] += 0.12 * np.sin(phase).astype(np.float32)

    # 5 kHz burst, 50-55s
    mask = (t >= 50.0) & (t < 55.0)
    audio[mask] += 0.20 * np.sin(2 * np.pi * 5000.0 * t[mask]).astype(np.float32)

    # Process through accumulator in blocksize chunks
    blocksize = args.blocksize
    for start in range(0, n_samples, blocksize):
        chunk = audio[start:start + blocksize]
        if len(chunk) < blocksize:
            chunk = np.pad(chunk, (0, blocksize - len(chunk)))
        accumulator.process(chunk)

    # Save the PNG
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    now = datetime.now(timezone.utc)
    output_path = _make_filename(output_dir, args.label or "test", now)

    success = accumulator.save_png(
        output_path,
        colormap=args.colormap,
        label=args.label or "test (synthetic)",
        start_time=now,
        end_time=now,
    )

    if success:
        print(f"Test spectrogram written: {output_path}", file=sys.stderr)
        print(f"  {accumulator.n_columns} FFT columns, "
              f"{duration:.0f}s synthetic audio", file=sys.stderr)
        return 0
    else:
        print("ERROR: no data accumulated", file=sys.stderr)
        return 1


def _run_live(args) -> int:
    """Run continuous spectrogram logging from live audio."""
    import sounddevice as sd

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    interval_sec = _interval_seconds(args.interval)

    accumulator = SpectrogramAccumulator(
        samplerate=args.samplerate,
        blocksize=args.blocksize,
        fft_size=args.fft_size,
        dynamic_range_db=args.dynamic_range_db,
    )

    stop_flag = [False]
    interval_start = [datetime.now(timezone.utc)]

    def sigint_handler(signum, frame):
        stop_flag[0] = True

    old_handler = signal.signal(signal.SIGINT, sigint_handler)

    def save_current_interval():
        """Save the current accumulator data and reset."""
        now = datetime.now(timezone.utc)
        if accumulator.n_columns == 0:
            return
        output_path = _make_filename(output_dir, args.label, interval_start[0])
        success = accumulator.save_png(
            output_path,
            colormap=args.colormap,
            label=args.label,
            start_time=interval_start[0],
            end_time=now,
        )
        if success:
            print(f"Saved: {output_path} ({accumulator.n_columns} columns)",
                  file=sys.stderr)
        accumulator.reset()
        interval_start[0] = now

    # Audio callback
    def callback(indata, frames, time_info, status):
        if status:
            print(f"Audio status: {status}", file=sys.stderr)
        accumulator.process(indata.copy())

    total_duration = args.duration
    start_time = time.time()

    try:
        device_kwargs = {}
        if args.input_device is not None:
            device_kwargs["device"] = args.input_device

        with sd.InputStream(
            samplerate=args.samplerate,
            blocksize=args.blocksize,
            channels=args.channels_in,
            dtype="float32",
            callback=callback,
            **device_kwargs,
        ):
            print(f"Spectrogram logger running (interval={args.interval}, "
                  f"fft_size={args.fft_size}, Ctrl-C to stop)...", file=sys.stderr)

            while not stop_flag[0]:
                time.sleep(0.5)

                # Check if interval has elapsed
                elapsed_interval = (datetime.now(timezone.utc) - interval_start[0]).total_seconds()
                if elapsed_interval >= interval_sec:
                    save_current_interval()

                # Check if total duration has elapsed
                if total_duration is not None:
                    if (time.time() - start_time) >= total_duration:
                        break

    except KeyboardInterrupt:
        pass
    finally:
        signal.signal(signal.SIGINT, old_handler)
        # Save any remaining data
        save_current_interval()
        print("\nStopped.", file=sys.stderr)

    return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Wideband audio spectrogram logger. Continuous FFT of "
                    "soundcard input saved as PNG images on a configurable "
                    "rotation interval.")
    add_audio_args(parser, duplex=False)
    add_test_args(parser)

    parser.set_defaults(blocksize=2048)

    g = parser.add_argument_group("spectrogram")
    g.add_argument("--fft-size", type=int, default=2048, metavar="N",
                   help="FFT size in samples (default 2048)")
    g.add_argument("--interval", default="hourly", metavar="INTERVAL",
                   help="File rotation: 'hourly', 'daily', or minutes as a "
                        "number (e.g., '15' for 15 minutes). Default: hourly")
    g.add_argument("--colormap", default="viridis", metavar="CMAP",
                   help="Matplotlib colormap (default viridis)")
    g.add_argument("--dynamic-range-db", type=float, default=60.0, metavar="DB",
                   help="Dynamic range floor below 0 dBFS (default 60)")
    g.add_argument("--label", default="", metavar="STR",
                   help="Label string included in filename and image title")
    g.add_argument("--duration", type=float, default=None, metavar="SEC",
                   help="Total run time in seconds (default: run until Ctrl-C)")
    g.add_argument("--output-dir", default=".", metavar="DIR",
                   help="Directory for PNG output (default: current directory)")

    args = parser.parse_args()

    if args.list_devices:
        import sounddevice as sd
        print(sd.query_devices())
        return 0

    if args.test:
        return _run_test(args)

    return _run_live(args)


if __name__ == "__main__":
    sys.exit(main())
