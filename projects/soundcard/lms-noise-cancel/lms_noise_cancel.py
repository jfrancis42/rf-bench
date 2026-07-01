#!/usr/bin/env python3
"""
lms_noise_cancel.py — LMS adaptive noise cancellation (two-input).

Primary input: signal + noise (e.g., radio audio).
Reference input: correlated noise only (e.g., ambient mic near noise source).

The LMS algorithm adapts an FIR filter on the reference signal to predict
and subtract the noise component from the primary signal.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from dsp_pipeline import DSPBlock, Pipeline, TestSignal, add_audio_args, add_test_args
from dsp_pipeline.stream import AudioStream


class LMSNoiseCanceller(DSPBlock):
    """Widrow LMS adaptive noise canceller."""

    def __init__(self, samplerate: int = 48000, blocksize: int = 1024,
                 num_taps: int = 128, mu: float = 0.01, leakage: float = 0.9999):
        super().__init__(samplerate, blocksize, channels=2)
        self.num_taps = num_taps
        self.mu = mu
        self.leakage = leakage
        self.weights = np.zeros(num_taps, dtype=np.float32)
        self._ref_buffer = np.zeros(num_taps, dtype=np.float32)

    def process(self, samples: np.ndarray) -> np.ndarray:
        """Process stereo input: channel 0 = primary (signal+noise),
        channel 1 = reference (noise only)."""
        if samples.ndim == 1:
            return samples  # can't do 2-input on mono

        primary = samples[:, 0]
        reference = samples[:, 1] if samples.shape[1] > 1 else np.zeros_like(primary)
        output = np.zeros(len(primary), dtype=np.float32)

        for i in range(len(primary)):
            # shift reference buffer
            self._ref_buffer = np.roll(self._ref_buffer, 1)
            self._ref_buffer[0] = reference[i]

            # predict noise from reference
            noise_estimate = np.dot(self.weights, self._ref_buffer)

            # error = desired - estimate (desired = primary, which has signal+noise)
            error = primary[i] - noise_estimate
            output[i] = error

            # LMS weight update with leakage
            self.weights = (self.leakage * self.weights +
                            2.0 * self.mu * error * self._ref_buffer)

        return output.reshape(-1, 1)

    def reset(self):
        self.weights = np.zeros(self.num_taps, dtype=np.float32)
        self._ref_buffer = np.zeros(self.num_taps, dtype=np.float32)

    def get_status(self) -> dict:
        return {
            "enabled": self.enabled,
            "weight_power": float(np.sum(self.weights ** 2)),
            "num_taps": self.num_taps,
            "mu": self.mu,
        }


class NLMSNoiseCanceller(DSPBlock):
    """Normalized LMS — adapts step size to signal power for faster convergence."""

    def __init__(self, samplerate: int = 48000, blocksize: int = 1024,
                 num_taps: int = 128, mu: float = 0.5, eps: float = 1e-6,
                 leakage: float = 0.9999):
        super().__init__(samplerate, blocksize, channels=2)
        self.num_taps = num_taps
        self.mu = mu
        self.eps = eps
        self.leakage = leakage
        self.weights = np.zeros(num_taps, dtype=np.float32)
        self._ref_buffer = np.zeros(num_taps, dtype=np.float32)

    def process(self, samples: np.ndarray) -> np.ndarray:
        if samples.ndim == 1:
            return samples

        primary = samples[:, 0]
        reference = samples[:, 1] if samples.shape[1] > 1 else np.zeros_like(primary)
        output = np.zeros(len(primary), dtype=np.float32)

        for i in range(len(primary)):
            self._ref_buffer = np.roll(self._ref_buffer, 1)
            self._ref_buffer[0] = reference[i]

            noise_estimate = np.dot(self.weights, self._ref_buffer)
            error = primary[i] - noise_estimate
            output[i] = error

            # normalized step size
            power = np.dot(self._ref_buffer, self._ref_buffer) + self.eps
            step = self.mu / power
            self.weights = (self.leakage * self.weights +
                            2.0 * step * error * self._ref_buffer)

        return output.reshape(-1, 1)

    def reset(self):
        self.weights = np.zeros(self.num_taps, dtype=np.float32)
        self._ref_buffer = np.zeros(self.num_taps, dtype=np.float32)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="LMS adaptive noise cancellation (two-input).")
    add_audio_args(parser)
    add_test_args(parser)
    parser.add_argument("--taps", type=int, default=128,
                        help="Number of adaptive filter taps (default 128)")
    parser.add_argument("--mu", type=float, default=0.01,
                        help="LMS step size (default 0.01)")
    parser.add_argument("--nlms", action="store_true",
                        help="Use normalized LMS (faster convergence)")
    parser.add_argument("--leakage", type=float, default=0.9999,
                        help="Weight leakage factor (default 0.9999)")
    parser.add_argument("--output", metavar="WAV",
                        help="Write processed audio to WAV file (test mode)")
    args = parser.parse_args()

    if args.list_devices:
        from dsp_pipeline.args import open_stream_from_args
        open_stream_from_args(args)
        return 0

    if args.nlms:
        block = NLMSNoiseCanceller(
            samplerate=args.samplerate, blocksize=args.blocksize,
            num_taps=args.taps, mu=args.mu if args.mu != 0.01 else 0.5,
            leakage=args.leakage,
        )
    else:
        block = LMSNoiseCanceller(
            samplerate=args.samplerate, blocksize=args.blocksize,
            num_taps=args.taps, mu=args.mu, leakage=args.leakage,
        )
    pipeline = Pipeline([block], samplerate=args.samplerate, blocksize=args.blocksize)

    if args.test:
        ts = TestSignal(args.samplerate, args.test_duration)
        # simulate: primary = speech + fan noise, reference = fan noise (delayed)
        rng = np.random.default_rng(42)
        noise_source = ts.noise(amplitude=0.3)
        signal = ts.speech_like(amplitude=0.4)
        # reference is a filtered/delayed version of the same noise
        delay = 5
        reference = np.roll(noise_source, delay) * 0.8
        primary = signal + noise_source

        stereo_input = np.column_stack([primary, reference]).astype(np.float32)
        processed = pipeline.process_array(stereo_input)

        snr_in = 10 * np.log10(np.mean(signal**2) / np.mean(noise_source**2))
        residual_noise = processed.flatten() - signal
        snr_out = 10 * np.log10(np.mean(signal**2) / (np.mean(residual_noise**2) + 1e-10))

        print(f"Input SNR:  {snr_in:.1f} dB")
        print(f"Output SNR: {snr_out:.1f} dB")
        print(f"Improvement: {snr_out - snr_in:.1f} dB")

        if args.output:
            import soundfile as sf
            sf.write(args.output, processed, args.samplerate)
            print(f"Wrote {args.output}")
    else:
        print("Two-input mode: Left channel = primary (signal+noise),", file=sys.stderr)
        print("                Right channel = reference (noise only).", file=sys.stderr)
        print("Use a stereo input with two mics or split cables.", file=sys.stderr)
        args.channels_in = 2
        pipeline.run_realtime(
            input_device=args.input_device,
            output_device=args.output_device,
            channels_in=2,
            channels_out=args.channels_out,
        )

    return 0


if __name__ == "__main__":
    sys.exit(main())
