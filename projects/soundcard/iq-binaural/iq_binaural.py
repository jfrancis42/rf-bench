#!/usr/bin/env python3
"""
iq_binaural.py — IQ-to-binaural stereo converter.

Accepts stereo L/R I/Q audio (Left=I, Right=Q) and produces binaural
stereo headphone audio where signals at different offsets from the
carrier appear at different spatial positions.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np
from scipy.signal import get_window

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from dsp_pipeline import DSPBlock, Pipeline, TestSignal, add_audio_args, add_test_args


class IQBinaural(DSPBlock):
    """Convert I/Q stereo input to binaural spatial audio output."""

    def __init__(self, samplerate: int = 48000, blocksize: int = 1024,
                 passband_hz: float = 3000.0, pan_mode: str = "linear",
                 max_itd_ms: float = 0.6, ild_db: float = 10.0):
        super().__init__(samplerate, blocksize, channels=2)
        self.passband_hz = passband_hz
        self.pan_mode = pan_mode
        self.max_itd_samples = int(max_itd_ms * samplerate / 1000)
        self.ild_db = ild_db
        self.ild_ratio = 10 ** (ild_db / 20.0)
        self.window = get_window("hann", blocksize).astype(np.float32)
        self.n_fft = blocksize
        self._prev_left = np.zeros(blocksize, dtype=np.float32)
        self._prev_right = np.zeros(blocksize, dtype=np.float32)

    def _freq_to_pan(self, freq: float) -> float:
        """Map frequency offset to pan position [-1, +1]."""
        if self.pan_mode == "linear":
            return np.clip(freq / self.passband_hz, -1.0, 1.0)
        elif self.pan_mode == "log":
            # compress center, expand edges
            if abs(freq) < 1.0:
                return 0.0
            sign = 1.0 if freq > 0 else -1.0
            normalized = np.log1p(abs(freq)) / np.log1p(self.passband_hz)
            return sign * np.clip(normalized, 0.0, 1.0)
        else:
            return np.clip(freq / self.passband_hz, -1.0, 1.0)

    def process(self, samples: np.ndarray) -> np.ndarray:
        if samples.ndim == 1 or samples.shape[1] < 2:
            # mono input — can't do IQ processing
            return np.column_stack([samples.flatten(), samples.flatten()])

        i_signal = samples[:, 0]
        q_signal = samples[:, 1]
        n = len(i_signal)

        if n < self.blocksize:
            i_signal = np.pad(i_signal, (0, self.blocksize - n))
            q_signal = np.pad(q_signal, (0, self.blocksize - n))

        # form complex IQ
        iq = (i_signal + 1j * q_signal).astype(np.complex64)

        # window and FFT the complex signal
        windowed = iq * self.window
        spectrum = np.fft.fft(windowed)  # full complex FFT (not rfft — IQ is complex)
        freqs = np.fft.fftfreq(self.n_fft, 1.0 / self.samplerate)

        # compute per-bin spatial parameters
        left_spectrum = np.zeros(self.n_fft, dtype=np.complex64)
        right_spectrum = np.zeros(self.n_fft, dtype=np.complex64)

        for i in range(self.n_fft):
            f = freqs[i]
            pan = self._freq_to_pan(f)

            # ILD
            if pan <= 0:
                left_gain = 1.0
                right_gain = 1.0 / (1.0 + abs(pan) * (self.ild_ratio - 1))
            else:
                right_gain = 1.0
                left_gain = 1.0 / (1.0 + pan * (self.ild_ratio - 1))

            # ITD as phase shift on right channel
            itd_phase = 2 * np.pi * abs(f) * (pan * self.max_itd_samples / self.samplerate)

            left_spectrum[i] = spectrum[i] * left_gain
            right_spectrum[i] = spectrum[i] * right_gain * np.exp(-1j * itd_phase)

        # IFFT back — take real part (we've spatially distributed the complex signal)
        left_time = np.real(np.fft.ifft(left_spectrum)).astype(np.float32) * self.window
        right_time = np.real(np.fft.ifft(right_spectrum)).astype(np.float32) * self.window

        # overlap-add
        half = self.blocksize // 2
        out_left = np.zeros(self.blocksize, dtype=np.float32)
        out_right = np.zeros(self.blocksize, dtype=np.float32)
        out_left[:half] = left_time[:half] + self._prev_left[half:]
        out_left[half:] = left_time[half:]
        out_right[:half] = right_time[:half] + self._prev_right[half:]
        out_right[half:] = right_time[half:]
        self._prev_left = left_time.copy()
        self._prev_right = right_time.copy()

        return np.column_stack([out_left, out_right])

    def reset(self):
        self._prev_left = np.zeros(self.blocksize, dtype=np.float32)
        self._prev_right = np.zeros(self.blocksize, dtype=np.float32)

    def get_status(self) -> dict:
        return {
            "enabled": self.enabled,
            "passband": f"±{self.passband_hz:.0f} Hz",
            "pan_mode": self.pan_mode,
            "itd_ms": f"{self.max_itd_samples * 1000 / self.samplerate:.2f}",
            "ild_db": self.ild_db,
        }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="IQ-to-binaural stereo converter.")
    add_audio_args(parser)
    add_test_args(parser)
    parser.add_argument("--passband", type=float, default=3000.0,
                        help="Passband half-width in Hz (default 3000)")
    parser.add_argument("--pan-mode", choices=["linear", "log"], default="linear",
                        help="Frequency-to-pan mapping (default linear)")
    parser.add_argument("--itd-ms", type=float, default=0.6,
                        help="Maximum interaural time delay in ms (default 0.6)")
    parser.add_argument("--ild-db", type=float, default=10.0,
                        help="Maximum interaural level difference in dB (default 10)")
    parser.add_argument("--output", metavar="WAV",
                        help="Write binaural stereo to WAV (test mode)")
    args = parser.parse_args()

    if args.list_devices:
        from dsp_pipeline.args import open_stream_from_args
        open_stream_from_args(args)
        return 0

    block = IQBinaural(
        samplerate=args.samplerate,
        blocksize=args.blocksize,
        passband_hz=args.passband,
        pan_mode=args.pan_mode,
        max_itd_ms=args.itd_ms,
        ild_db=args.ild_db,
    )
    pipeline = Pipeline([block], samplerate=args.samplerate, blocksize=args.blocksize)

    if args.test:
        ts = TestSignal(args.samplerate, args.test_duration)
        # generate IQ with multiple carriers at different offsets
        test_iq = ts.iq_signal(
            offsets_hz=[-2000, -800, 200, 1500, 2500],
            amplitudes=[0.2, 0.35, 0.4, 0.25, 0.15],
            noise_amplitude=0.02,
        )
        processed = pipeline.process_array(test_iq)
        print(f"Input: stereo I/Q with carriers at -2000, -800, +200, +1500, +2500 Hz")
        print(f"Output: binaural stereo ({processed.shape})")
        print(f"Pan mode: {args.pan_mode}, passband: ±{args.passband:.0f} Hz")

        if args.output:
            import soundfile as sf
            sf.write(args.output, processed, args.samplerate)
            print(f"Wrote {args.output}")
    else:
        print("Input: stereo L=I, R=Q from radio IQ output", file=sys.stderr)
        print(f"Passband: ±{args.passband:.0f} Hz, pan: {args.pan_mode}", file=sys.stderr)
        args.channels_in = 2
        pipeline.run_realtime(
            input_device=args.input_device,
            output_device=args.output_device,
            channels_in=2,
            channels_out=2,
        )

    return 0


if __name__ == "__main__":
    sys.exit(main())
