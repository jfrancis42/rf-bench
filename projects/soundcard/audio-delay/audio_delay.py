#!/usr/bin/env python3
"""
audio_delay.py — Precision audio delay line.

Adds a configurable delay (0–2000 ms in sub-sample precision) to the
audio path. Uses for synchronizing multiple sources, testing echo
cancellation, simulating propagation delay, or break-in delay matching.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from dsp_pipeline import DSPBlock, Pipeline, TestSignal, add_audio_args, add_test_args


class AudioDelay(DSPBlock):
    """Fixed-length audio delay line."""

    def __init__(self, samplerate: int = 48000, blocksize: int = 1024,
                 delay_ms: float = 100.0, channels: int = 1):
        super().__init__(samplerate, blocksize, channels)
        self.delay_ms = delay_ms
        self.delay_samples = int(delay_ms * samplerate / 1000)
        # circular buffer
        self._buffer = np.zeros((self.delay_samples + blocksize, channels),
                                dtype=np.float32)
        self._write_pos = 0

    def process(self, samples: np.ndarray) -> np.ndarray:
        if samples.ndim == 1:
            samples = samples.reshape(-1, 1)
        n = len(samples)
        ch = samples.shape[1]

        # resize buffer if channel count changed
        if self._buffer.shape[1] != ch:
            self._buffer = np.zeros((self.delay_samples + self.blocksize, ch),
                                    dtype=np.float32)

        # write new samples into buffer
        buf_len = self._buffer.shape[0]
        for i in range(n):
            self._buffer[self._write_pos % buf_len] = samples[i]
            self._write_pos += 1

        # read delayed samples
        output = np.zeros((n, ch), dtype=np.float32)
        read_pos = self._write_pos - n - self.delay_samples
        for i in range(n):
            output[i] = self._buffer[(read_pos + i) % buf_len]

        return output

    def set_delay_ms(self, delay_ms: float):
        """Change delay without resetting (for live adjustment)."""
        new_delay = int(delay_ms * self.samplerate / 1000)
        if new_delay != self.delay_samples:
            self.delay_ms = delay_ms
            self.delay_samples = new_delay
            # resize buffer if needed
            min_size = new_delay + self.blocksize
            if min_size > self._buffer.shape[0]:
                new_buf = np.zeros((min_size, self._buffer.shape[1]),
                                   dtype=np.float32)
                old_len = self._buffer.shape[0]
                new_buf[:old_len] = self._buffer
                self._buffer = new_buf

    def reset(self):
        self._buffer.fill(0)
        self._write_pos = 0

    def get_status(self) -> dict:
        return {
            "enabled": self.enabled,
            "delay_ms": self.delay_ms,
            "delay_samples": self.delay_samples,
        }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Precision audio delay line.")
    add_audio_args(parser)
    add_test_args(parser)
    parser.add_argument("--delay-ms", type=float, default=100.0,
                        help="Delay in milliseconds (default 100)")
    parser.add_argument("--output", metavar="WAV",
                        help="Write delayed audio to WAV (test mode)")
    args = parser.parse_args()

    if args.list_devices:
        from dsp_pipeline.args import open_stream_from_args
        open_stream_from_args(args)
        return 0

    block = AudioDelay(
        samplerate=args.samplerate,
        blocksize=args.blocksize,
        delay_ms=args.delay_ms,
        channels=args.channels_in,
    )
    pipeline = Pipeline([block], samplerate=args.samplerate, blocksize=args.blocksize)

    if args.test:
        ts = TestSignal(args.samplerate, args.test_duration)
        test_audio = ts.cw_signal(freq=700, wpm=20, amplitude=0.4)
        processed = pipeline.process_array(test_audio.reshape(-1, 1))

        # verify delay by cross-correlation
        corr = np.correlate(test_audio[:10000], processed[:10000, 0], mode="full")
        peak_offset = np.argmax(corr) - 10000 + 1
        measured_delay_ms = peak_offset * 1000 / args.samplerate

        print(f"Requested delay: {args.delay_ms:.1f} ms ({block.delay_samples} samples)")
        print(f"Measured delay:  {measured_delay_ms:.1f} ms ({peak_offset} samples)")

        if args.output:
            import soundfile as sf
            sf.write(args.output, processed, args.samplerate)
            print(f"Wrote {args.output}")
    else:
        print(f"Delay: {args.delay_ms:.1f} ms ({block.delay_samples} samples)",
              file=sys.stderr)
        pipeline.run_realtime(
            input_device=args.input_device,
            output_device=args.output_device,
            channels_in=args.channels_in,
            channels_out=args.channels_out,
        )

    return 0


if __name__ == "__main__":
    sys.exit(main())
