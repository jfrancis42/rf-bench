#!/usr/bin/env python3
"""
stereo_expander.py — Pseudo-stereo field expander for SSB.

Takes mono SSB audio and synthesizes a stereo field via comb filtering
and Haas effect. Reduces listener fatigue on long ragchews. Purely
cosmetic — no information gain.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np
from scipy.signal import lfilter

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from dsp_pipeline import DSPBlock, Pipeline, TestSignal, add_audio_args, add_test_args


class StereoExpander(DSPBlock):
    """Pseudo-stereo via comb filter + Haas effect."""

    def __init__(self, samplerate: int = 48000, blocksize: int = 1024,
                 delay_ms: float = 15.0, width: float = 0.7,
                 method: str = "haas"):
        super().__init__(samplerate, blocksize, channels=1)
        self.delay_samples = int(delay_ms * samplerate / 1000)
        self.width = np.clip(width, 0.0, 1.0)
        self.method = method
        # delay buffer — must be at least delay_samples + blocksize, use 2× for safety
        self._buf_len = max(self.delay_samples + blocksize, blocksize * 4)
        self._delay_buf = np.zeros(self._buf_len, dtype=np.float32)
        self._buf_pos = 0
        # allpass coefficients for comb method
        self._allpass_coeff = 0.6

    def process(self, samples: np.ndarray) -> np.ndarray:
        mono = samples[:, 0] if samples.ndim == 2 else samples
        n = len(mono)

        if self.method == "haas":
            # Haas effect: one ear gets delayed copy
            # left = original, right = delayed by delay_ms
            left = mono.copy()
            # write to circular buffer with wrap handling
            buf_len = self._buf_len
            end = self._buf_pos + n
            if end <= buf_len:
                self._delay_buf[self._buf_pos:end] = mono
            else:
                first = buf_len - self._buf_pos
                self._delay_buf[self._buf_pos:] = mono[:first]
                self._delay_buf[:n - first] = mono[first:]
            # read delayed samples
            delayed_start = (self._buf_pos - self.delay_samples) % buf_len
            right = np.zeros(n, dtype=np.float32)
            read_end = delayed_start + n
            if read_end <= buf_len:
                right[:] = self._delay_buf[delayed_start:read_end]
            else:
                first = buf_len - delayed_start
                right[:first] = self._delay_buf[delayed_start:]
                right[first:] = self._delay_buf[:n - first]
            self._buf_pos = (self._buf_pos + n) % buf_len

            # mix: width=1 → full stereo, width=0 → mono
            mid = (left + right) * 0.5
            side = (left - right) * 0.5
            out_left = mid + self.width * side
            out_right = mid - self.width * side

        elif self.method == "comb":
            # complementary comb: left gets one comb, right gets inverse
            # creates frequency-dependent L/R difference
            delay = self.delay_samples
            left = np.zeros(n, dtype=np.float32)
            right = np.zeros(n, dtype=np.float32)

            padded = np.concatenate([self._delay_buf[-delay:], mono])
            for i in range(n):
                left[i] = mono[i] + self.width * padded[i]
                right[i] = mono[i] - self.width * padded[i]
            self._delay_buf[-delay:] = mono[-delay:] if n >= delay else np.pad(mono, (delay - n, 0))[-delay:]

            out_left = left * 0.7  # normalize
            out_right = right * 0.7

        else:  # allpass
            # allpass difference: apply allpass to one channel
            a = self._allpass_coeff
            # first-order allpass: H(z) = (a + z^-1) / (1 + a*z^-1)
            b_coeff = np.array([a, 1.0], dtype=np.float32)
            a_coeff = np.array([1.0, a], dtype=np.float32)
            allpassed = lfilter(b_coeff, a_coeff, mono).astype(np.float32)

            out_left = mono
            out_right = allpassed * self.width + mono * (1 - self.width)

        return np.column_stack([out_left, out_right])

    def reset(self):
        self._delay_buf = np.zeros(self.delay_samples + self.blocksize, dtype=np.float32)
        self._buf_pos = 0

    def get_status(self) -> dict:
        return {
            "enabled": self.enabled,
            "method": self.method,
            "width": self.width,
            "delay_ms": self.delay_samples * 1000 / self.samplerate,
        }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Pseudo-stereo field expander for SSB/mono audio.")
    add_audio_args(parser)
    add_test_args(parser)
    parser.add_argument("--delay-ms", type=float, default=15.0,
                        help="Stereo delay in ms (default 15)")
    parser.add_argument("--width", type=float, default=0.7,
                        help="Stereo width 0-1 (default 0.7)")
    parser.add_argument("--method", choices=["haas", "comb", "allpass"],
                        default="haas",
                        help="Stereo synthesis method (default haas)")
    parser.add_argument("--output", metavar="WAV",
                        help="Write stereo output to WAV (test mode)")
    args = parser.parse_args()

    if args.list_devices:
        from dsp_pipeline.args import open_stream_from_args
        open_stream_from_args(args)
        return 0

    block = StereoExpander(
        samplerate=args.samplerate,
        blocksize=args.blocksize,
        delay_ms=args.delay_ms,
        width=args.width,
        method=args.method,
    )
    pipeline = Pipeline([block], samplerate=args.samplerate, blocksize=args.blocksize)

    if args.test:
        ts = TestSignal(args.samplerate, args.test_duration)
        test_audio = ts.speech_like(amplitude=0.4)
        processed = pipeline.process_array(test_audio.reshape(-1, 1))
        print(f"Method: {args.method}, width: {args.width}, delay: {args.delay_ms} ms")
        print(f"Output: stereo ({processed.shape})")

        if args.output:
            import soundfile as sf
            sf.write(args.output, processed, args.samplerate)
            print(f"Wrote {args.output}")
    else:
        pipeline.run_realtime(
            input_device=args.input_device,
            output_device=args.output_device,
            channels_in=args.channels_in,
            channels_out=2,
        )

    return 0


if __name__ == "__main__":
    sys.exit(main())
