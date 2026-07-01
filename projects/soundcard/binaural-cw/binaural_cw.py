#!/usr/bin/env python3
"""
binaural_cw.py — Binaural CW processor.

Mono CW audio in → stereo out with frequency-dependent spatial
positioning. Each CW signal at a different audio pitch appears to come
from a different direction in the headphone soundstage. Leverages the
brain's spatial separation (cocktail-party effect) for pile-up copy.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np
from scipy.signal import get_window

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from dsp_pipeline import DSPBlock, Pipeline, TestSignal, add_audio_args, add_test_args


class BinauralCW(DSPBlock):
    """Frequency-dependent binaural spatializer for CW."""

    def __init__(self, samplerate: int = 48000, blocksize: int = 1024,
                 low_freq: float = 300.0, high_freq: float = 1200.0,
                 max_itd_ms: float = 0.6, ild_db: float = 8.0):
        super().__init__(samplerate, blocksize, channels=1)
        self.low_freq = low_freq
        self.high_freq = high_freq
        self.max_itd_samples = int(max_itd_ms * samplerate / 1000)
        self.ild_db = ild_db
        self.ild_ratio = 10 ** (ild_db / 20.0)
        self.window = get_window("hann", blocksize).astype(np.float32)
        self.n_fft = blocksize
        # overlap-add buffers (stereo)
        self._prev_left = np.zeros(blocksize, dtype=np.float32)
        self._prev_right = np.zeros(blocksize, dtype=np.float32)

    def process(self, samples: np.ndarray) -> np.ndarray:
        mono = samples[:, 0] if samples.ndim == 2 else samples
        if len(mono) < self.blocksize:
            mono = np.pad(mono, (0, self.blocksize - len(mono)))

        windowed = mono * self.window
        spectrum = np.fft.rfft(windowed)
        freqs = np.fft.rfftfreq(self.n_fft, 1.0 / self.samplerate)

        # compute per-bin pan position: -1 (left) to +1 (right)
        # low frequencies → left, high → right
        pan = np.zeros(len(freqs), dtype=np.float32)
        for i, f in enumerate(freqs):
            if f <= self.low_freq:
                pan[i] = -1.0
            elif f >= self.high_freq:
                pan[i] = 1.0
            else:
                pan[i] = 2.0 * (f - self.low_freq) / (self.high_freq - self.low_freq) - 1.0

        # apply ILD (interaural level difference)
        # pan=-1 → left loud, right quiet; pan=+1 → right loud, left quiet
        left_gain = np.where(pan <= 0, 1.0, 1.0 / (1.0 + pan * (self.ild_ratio - 1)))
        right_gain = np.where(pan >= 0, 1.0, 1.0 / (1.0 - pan * (self.ild_ratio - 1)))

        # apply ITD (interaural time delay) as phase shift
        # pan=-1 → right ear delayed; pan=+1 → left ear delayed
        itd_samples = pan * self.max_itd_samples
        phase_shift = 2 * np.pi * freqs * itd_samples / self.samplerate

        left_spectrum = spectrum * left_gain
        right_spectrum = spectrum * right_gain * np.exp(-1j * phase_shift)

        # IFFT back to time domain
        left = np.fft.irfft(left_spectrum, n=self.n_fft).astype(np.float32) * self.window
        right = np.fft.irfft(right_spectrum, n=self.n_fft).astype(np.float32) * self.window

        # overlap-add
        half = self.blocksize // 2
        out_left = np.zeros(self.blocksize, dtype=np.float32)
        out_right = np.zeros(self.blocksize, dtype=np.float32)
        out_left[:half] = left[:half] + self._prev_left[half:]
        out_left[half:] = left[half:]
        out_right[:half] = right[:half] + self._prev_right[half:]
        out_right[half:] = right[half:]
        self._prev_left = left.copy()
        self._prev_right = right.copy()

        return np.column_stack([out_left, out_right])

    def reset(self):
        self._prev_left = np.zeros(self.blocksize, dtype=np.float32)
        self._prev_right = np.zeros(self.blocksize, dtype=np.float32)

    def get_status(self) -> dict:
        return {
            "enabled": self.enabled,
            "freq_range": f"{self.low_freq:.0f}–{self.high_freq:.0f} Hz",
            "max_itd_ms": f"{self.max_itd_samples * 1000 / self.samplerate:.2f}",
            "ild_db": self.ild_db,
        }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Binaural CW processor — spatial separation by pitch.")
    add_audio_args(parser)
    add_test_args(parser)
    parser.add_argument("--low-freq", type=float, default=300.0,
                        help="Lowest CW pitch → panned full left (default 300 Hz)")
    parser.add_argument("--high-freq", type=float, default=1200.0,
                        help="Highest CW pitch → panned full right (default 1200 Hz)")
    parser.add_argument("--itd-ms", type=float, default=0.6,
                        help="Maximum interaural time delay in ms (default 0.6)")
    parser.add_argument("--ild-db", type=float, default=8.0,
                        help="Maximum interaural level difference in dB (default 8)")
    parser.add_argument("--output", metavar="WAV",
                        help="Write stereo output to WAV (test mode)")
    args = parser.parse_args()

    if args.list_devices:
        from dsp_pipeline.args import open_stream_from_args
        open_stream_from_args(args)
        return 0

    block = BinauralCW(
        samplerate=args.samplerate,
        blocksize=args.blocksize,
        low_freq=args.low_freq,
        high_freq=args.high_freq,
        max_itd_ms=args.itd_ms,
        ild_db=args.ild_db,
    )
    pipeline = Pipeline([block], samplerate=args.samplerate, blocksize=args.blocksize)

    if args.test:
        ts = TestSignal(args.samplerate, args.test_duration)
        # three CW signals at different pitches
        t = np.arange(ts.n_samples) / args.samplerate
        cw1 = ts.cw_signal(freq=400, wpm=20, amplitude=0.3, noise_amplitude=0)
        cw2 = ts.cw_signal(freq=700, wpm=15, amplitude=0.3, noise_amplitude=0)
        cw3 = ts.cw_signal(freq=1000, wpm=25, amplitude=0.3, noise_amplitude=0)
        test_audio = cw1 + cw2 + cw3 + ts.noise(amplitude=0.02)

        processed = pipeline.process_array(test_audio.reshape(-1, 1))
        print(f"Input: mono, 3 CW signals at 400/700/1000 Hz")
        print(f"Output: stereo, spatially separated L→R")

        if args.output:
            import soundfile as sf
            sf.write(args.output, processed, args.samplerate)
            print(f"Wrote {args.output}")
    else:
        print(f"Binaural CW: {args.low_freq:.0f} Hz (left) → "
              f"{args.high_freq:.0f} Hz (right)", file=sys.stderr)
        pipeline.run_realtime(
            input_device=args.input_device,
            output_device=args.output_device,
            channels_in=args.channels_in,
            channels_out=2,
        )

    return 0


if __name__ == "__main__":
    sys.exit(main())
