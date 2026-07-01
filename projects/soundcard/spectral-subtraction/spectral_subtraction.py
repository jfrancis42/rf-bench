#!/usr/bin/env python3
"""
spectral_subtraction.py — Real-time spectral noise reduction.

Captures a noise profile during a quiet interval (or from the first N
seconds automatically), then subtracts the noise spectral envelope from
live audio frame-by-frame. Same algorithm as the TimeWave DSP-599zx.
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

import numpy as np
from scipy.signal import get_window

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from dsp_pipeline import DSPBlock, Pipeline, TestSignal, add_audio_args, add_test_args
from dsp_pipeline.stream import AudioStream


class SpectralSubtraction(DSPBlock):
    """Spectral subtraction noise reducer."""

    def __init__(self, samplerate: int = 48000, blocksize: int = 1024,
                 subtraction_db: float = 12.0, floor_db: float = -40.0,
                 noise_frames: int = 20):
        super().__init__(samplerate, blocksize)
        self.subtraction_factor = 10 ** (subtraction_db / 20.0)
        self.spectral_floor = 10 ** (floor_db / 20.0)
        self.noise_frames_needed = noise_frames
        self.noise_profile = None
        self._noise_accum = []
        self._capturing_noise = True
        self.fft_size = blocksize
        self.window = get_window("hann", blocksize).astype(np.float32)
        # overlap-add state
        self._prev_block = np.zeros(blocksize, dtype=np.float32)

    def capture_noise_profile(self, profile: np.ndarray):
        """Manually set a noise profile (magnitude spectrum)."""
        self.noise_profile = profile.astype(np.float32)
        self._capturing_noise = False

    def process(self, samples: np.ndarray) -> np.ndarray:
        mono = samples[:, 0] if samples.ndim == 2 else samples
        if len(mono) < self.blocksize:
            mono = np.pad(mono, (0, self.blocksize - len(mono)))

        if self._capturing_noise:
            spectrum = np.abs(np.fft.rfft(mono * self.window))
            self._noise_accum.append(spectrum)
            if len(self._noise_accum) >= self.noise_frames_needed:
                self.noise_profile = np.mean(self._noise_accum, axis=0).astype(np.float32)
                self._capturing_noise = False
                self._noise_accum = []
            return samples  # pass through during capture

        windowed = mono * self.window
        spectrum = np.fft.rfft(windowed)
        magnitude = np.abs(spectrum)
        phase = np.angle(spectrum)

        # subtract noise magnitude
        cleaned_mag = magnitude - self.subtraction_factor * self.noise_profile
        cleaned_mag = np.maximum(cleaned_mag, self.spectral_floor * magnitude)

        # reconstruct
        cleaned_spectrum = cleaned_mag * np.exp(1j * phase)
        cleaned_block = np.fft.irfft(cleaned_spectrum, n=self.blocksize).astype(np.float32)

        # overlap-add (50% overlap simulated via crossfade)
        output = cleaned_block * self.window
        result = output[:self.blocksize // 2] + self._prev_block[self.blocksize // 2:]
        self._prev_block = output.copy()

        # pad back to full blocksize
        full_output = np.concatenate([result, output[self.blocksize // 2:]])

        if samples.ndim == 2:
            return full_output.reshape(-1, 1).repeat(samples.shape[1], axis=1)
        return full_output

    def reset(self):
        self.noise_profile = None
        self._noise_accum = []
        self._capturing_noise = True
        self._prev_block = np.zeros(self.blocksize, dtype=np.float32)

    def get_status(self) -> dict:
        return {
            "enabled": self.enabled,
            "noise_captured": self.noise_profile is not None,
            "capturing": self._capturing_noise,
        }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Real-time spectral subtraction noise reducer.")
    add_audio_args(parser)
    add_test_args(parser)
    parser.add_argument("--subtraction-db", type=float, default=12.0,
                        help="Noise subtraction depth in dB (default 12)")
    parser.add_argument("--floor-db", type=float, default=-40.0,
                        help="Spectral floor in dB relative to input (default -40)")
    parser.add_argument("--noise-frames", type=int, default=20,
                        help="Number of initial frames to capture as noise profile (default 20)")
    parser.add_argument("--output", metavar="WAV",
                        help="Write processed audio to WAV file (test mode)")
    args = parser.parse_args()

    if args.list_devices:
        from dsp_pipeline.args import open_stream_from_args
        open_stream_from_args(args)
        return 0

    block = SpectralSubtraction(
        samplerate=args.samplerate,
        blocksize=args.blocksize,
        subtraction_db=args.subtraction_db,
        floor_db=args.floor_db,
        noise_frames=args.noise_frames,
    )
    pipeline = Pipeline([block], samplerate=args.samplerate, blocksize=args.blocksize)

    if args.test:
        ts = TestSignal(args.samplerate, args.test_duration)
        # 1 second of noise only, then signal+noise
        noise_only = ts.noise(amplitude=0.1)
        sig_noise = ts.signal_plus_noise(freq=800, sig_amplitude=0.3, noise_amplitude=0.1)
        test_audio = np.concatenate([
            noise_only[:args.samplerate],  # 1s noise for profile capture
            sig_noise,
        ])
        processed = pipeline.process_array(test_audio.reshape(-1, 1))
        print(f"Processed {len(processed)} samples")
        print(f"Input RMS:  {np.sqrt(np.mean(test_audio**2)):.4f}")
        print(f"Output RMS: {np.sqrt(np.mean(processed**2)):.4f}")
        if args.output:
            import soundfile as sf
            sf.write(args.output, processed, args.samplerate)
            print(f"Wrote {args.output}")
        elif args.output_device is not None:
            pipeline.run_test(test_audio.reshape(-1, 1),
                              output_device=args.output_device,
                              channels_out=args.channels_out)
    else:
        print(f"Capturing noise profile ({args.noise_frames} frames)...",
              file=sys.stderr)
        print("Keep the channel QUIET for the first ~0.5 seconds.", file=sys.stderr)
        pipeline.run_realtime(
            input_device=args.input_device,
            output_device=args.output_device,
            channels_in=args.channels_in,
            channels_out=args.channels_out,
        )

    return 0


if __name__ == "__main__":
    sys.exit(main())
