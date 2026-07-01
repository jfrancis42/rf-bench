#!/usr/bin/env python3
"""
wiener_filter.py — Optimal Wiener filter noise reduction.

Estimates signal and noise power spectra, applies frequency-domain
Wiener gain H(f) = Pss(f) / (Pss(f) + Pnn(f)) per bin. Theoretically
optimal linear filter for stationary signals in stationary noise.
Fewer musical artifacts than spectral subtraction.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np
from scipy.signal import get_window

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from dsp_pipeline import DSPBlock, Pipeline, TestSignal, add_audio_args, add_test_args


class WienerFilter(DSPBlock):
    """Frequency-domain Wiener filter."""

    def __init__(self, samplerate: int = 48000, blocksize: int = 1024,
                 noise_frames: int = 20, alpha: float = 0.95,
                 floor_db: float = -30.0):
        super().__init__(samplerate, blocksize)
        self.noise_frames_needed = noise_frames
        self.alpha = alpha  # smoothing for signal PSD estimate
        self.floor = 10 ** (floor_db / 10.0)
        self.noise_psd = None
        self.signal_psd = None
        self._noise_accum = []
        self._capturing_noise = True
        self.window = get_window("hann", blocksize).astype(np.float32)
        self._prev_output = np.zeros(blocksize, dtype=np.float32)
        self.n_fft_bins = blocksize // 2 + 1

    def process(self, samples: np.ndarray) -> np.ndarray:
        mono = samples[:, 0] if samples.ndim == 2 else samples
        if len(mono) < self.blocksize:
            mono = np.pad(mono, (0, self.blocksize - len(mono)))

        windowed = mono * self.window
        spectrum = np.fft.rfft(windowed)
        power = np.abs(spectrum) ** 2

        if self._capturing_noise:
            self._noise_accum.append(power)
            if len(self._noise_accum) >= self.noise_frames_needed:
                self.noise_psd = np.mean(self._noise_accum, axis=0).astype(np.float32)
                self.signal_psd = np.copy(self.noise_psd)
                self._capturing_noise = False
                self._noise_accum = []
            return samples

        # update signal PSD estimate (exponential smoothing)
        self.signal_psd = self.alpha * self.signal_psd + (1 - self.alpha) * power

        # Wiener gain: H(f) = max(Pss - Pnn, floor*Pnn) / Pss
        signal_only_psd = np.maximum(self.signal_psd - self.noise_psd,
                                     self.floor * self.noise_psd)
        gain = signal_only_psd / (self.signal_psd + 1e-10)
        gain = np.clip(gain, 0.0, 1.0)

        # apply gain
        filtered_spectrum = spectrum * gain
        output = np.fft.irfft(filtered_spectrum, n=self.blocksize).astype(np.float32)

        # overlap-add crossfade
        output *= self.window
        result = np.zeros(self.blocksize, dtype=np.float32)
        half = self.blocksize // 2
        result[:half] = output[:half] + self._prev_output[half:]
        result[half:] = output[half:]
        self._prev_output = output.copy()

        if samples.ndim == 2:
            return result.reshape(-1, 1).repeat(samples.shape[1], axis=1)
        return result

    def reset(self):
        self.noise_psd = None
        self.signal_psd = None
        self._noise_accum = []
        self._capturing_noise = True
        self._prev_output = np.zeros(self.blocksize, dtype=np.float32)

    def get_status(self) -> dict:
        avg_gain = 0.0
        if self.noise_psd is not None and self.signal_psd is not None:
            signal_only = np.maximum(self.signal_psd - self.noise_psd,
                                     self.floor * self.noise_psd)
            gain = signal_only / (self.signal_psd + 1e-10)
            avg_gain = float(np.mean(gain))
        return {
            "enabled": self.enabled,
            "noise_captured": self.noise_psd is not None,
            "avg_gain": f"{avg_gain:.3f}",
        }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Optimal Wiener filter noise reduction.")
    add_audio_args(parser)
    add_test_args(parser)
    parser.add_argument("--noise-frames", type=int, default=20,
                        help="Initial frames for noise PSD estimation (default 20)")
    parser.add_argument("--alpha", type=float, default=0.95,
                        help="Signal PSD smoothing factor (default 0.95)")
    parser.add_argument("--floor-db", type=float, default=-30.0,
                        help="Minimum gain floor in dB (default -30)")
    parser.add_argument("--output", metavar="WAV",
                        help="Write processed audio to WAV file (test mode)")
    args = parser.parse_args()

    if args.list_devices:
        from dsp_pipeline.args import open_stream_from_args
        open_stream_from_args(args)
        return 0

    block = WienerFilter(
        samplerate=args.samplerate,
        blocksize=args.blocksize,
        noise_frames=args.noise_frames,
        alpha=args.alpha,
        floor_db=args.floor_db,
    )
    pipeline = Pipeline([block], samplerate=args.samplerate, blocksize=args.blocksize)

    if args.test:
        ts = TestSignal(args.samplerate, args.test_duration)
        noise_only = ts.noise(amplitude=0.1)
        sig_noise = ts.signal_plus_noise(freq=800, sig_amplitude=0.3, noise_amplitude=0.1)
        test_audio = np.concatenate([noise_only[:args.samplerate], sig_noise])

        processed = pipeline.process_array(test_audio.reshape(-1, 1))
        print(f"Processed {len(processed)} samples")
        print(f"Input RMS:  {np.sqrt(np.mean(test_audio**2)):.4f}")
        print(f"Output RMS: {np.sqrt(np.mean(processed**2)):.4f}")
        print(f"Status: {block.get_status()}")

        if args.output:
            import soundfile as sf
            sf.write(args.output, processed, args.samplerate)
            print(f"Wrote {args.output}")
    else:
        print("Keep quiet for the first ~0.5 seconds (noise capture).", file=sys.stderr)
        pipeline.run_realtime(
            input_device=args.input_device,
            output_device=args.output_device,
            channels_in=args.channels_in,
            channels_out=args.channels_out,
        )

    return 0


if __name__ == "__main__":
    sys.exit(main())
