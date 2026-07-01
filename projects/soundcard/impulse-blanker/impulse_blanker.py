#!/usr/bin/env python3
"""
impulse_blanker.py — Real-time impulse noise blanker.

Detects short-duration amplitude spikes (ignition noise, switching PSU
clicks, LED dimmer hash) and blanks them by interpolation. Operates
purely in the time domain for minimal latency.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from dsp_pipeline import DSPBlock, Pipeline, TestSignal, add_audio_args, add_test_args


class ImpulseBlanker(DSPBlock):
    """Time-domain impulse noise blanker."""

    def __init__(self, samplerate: int = 48000, blocksize: int = 1024,
                 threshold_db: float = 12.0, max_blank_ms: float = 2.0,
                 method: str = "linear"):
        super().__init__(samplerate, blocksize)
        self.threshold_db = threshold_db
        self.threshold_ratio = 10 ** (threshold_db / 20.0)
        self.max_blank_samples = int(max_blank_ms * samplerate / 1000)
        self.method = method  # "linear", "zero", "hold"
        # running RMS estimate
        self._rms = 0.01
        self._rms_alpha = 0.001
        self._blanked_count = 0
        self._total_count = 0

    def process(self, samples: np.ndarray) -> np.ndarray:
        mono = samples[:, 0] if samples.ndim == 2 else samples
        output = mono.copy()
        n = len(output)
        self._total_count += n

        i = 0
        while i < n:
            # update running RMS
            self._rms = (1 - self._rms_alpha) * self._rms + self._rms_alpha * abs(output[i])

            # check if sample exceeds threshold
            if abs(output[i]) > self.threshold_ratio * max(self._rms, 1e-6):
                # find extent of impulse
                start = i
                while i < n and i - start < self.max_blank_samples:
                    if abs(output[i]) <= self.threshold_ratio * max(self._rms, 1e-6):
                        break
                    i += 1
                end = i
                self._blanked_count += (end - start)

                # interpolate blanked region
                if self.method == "zero":
                    output[start:end] = 0.0
                elif self.method == "hold":
                    hold_val = output[start - 1] if start > 0 else 0.0
                    output[start:end] = hold_val
                else:  # linear interpolation
                    val_before = output[start - 1] if start > 0 else 0.0
                    val_after = output[end] if end < n else 0.0
                    length = end - start
                    if length > 0:
                        interp = np.linspace(val_before, val_after, length + 2)[1:-1]
                        output[start:end] = interp
            else:
                i += 1

        if samples.ndim == 2:
            result = np.zeros_like(samples)
            result[:, 0] = output
            for ch in range(1, samples.shape[1]):
                result[:, ch] = output
            return result
        return output

    def reset(self):
        self._rms = 0.01
        self._blanked_count = 0
        self._total_count = 0

    def get_status(self) -> dict:
        pct = 100.0 * self._blanked_count / max(self._total_count, 1)
        return {
            "enabled": self.enabled,
            "rms": self._rms,
            "blanked_pct": f"{pct:.2f}%",
        }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Real-time impulse noise blanker.")
    add_audio_args(parser)
    add_test_args(parser)
    parser.add_argument("--threshold-db", type=float, default=12.0,
                        help="Trigger threshold in dB above running RMS (default 12)")
    parser.add_argument("--max-blank-ms", type=float, default=2.0,
                        help="Maximum blank duration in ms (default 2.0)")
    parser.add_argument("--method", choices=["linear", "zero", "hold"], default="linear",
                        help="Interpolation method (default linear)")
    parser.add_argument("--output", metavar="WAV",
                        help="Write processed audio to WAV file (test mode)")
    args = parser.parse_args()

    if args.list_devices:
        from dsp_pipeline.args import open_stream_from_args
        open_stream_from_args(args)
        return 0

    block = ImpulseBlanker(
        samplerate=args.samplerate,
        blocksize=args.blocksize,
        threshold_db=args.threshold_db,
        max_blank_ms=args.max_blank_ms,
        method=args.method,
    )
    pipeline = Pipeline([block], samplerate=args.samplerate, blocksize=args.blocksize)

    if args.test:
        ts = TestSignal(args.samplerate, args.test_duration)
        test_audio = ts.impulse_noise(
            base_freq=800, base_amplitude=0.3,
            impulse_rate=10, impulse_amplitude=0.9,
        )
        processed = pipeline.process_array(test_audio.reshape(-1, 1))
        status = block.get_status()
        print(f"Blanked {status['blanked_pct']} of samples")
        print(f"Input peak:  {np.max(np.abs(test_audio)):.3f}")
        print(f"Output peak: {np.max(np.abs(processed)):.3f}")
        if args.output:
            import soundfile as sf
            sf.write(args.output, processed, args.samplerate)
            print(f"Wrote {args.output}")
    else:
        pipeline.run_realtime(
            input_device=args.input_device,
            output_device=args.output_device,
            channels_in=args.channels_in,
            channels_out=args.channels_out,
        )

    return 0


if __name__ == "__main__":
    sys.exit(main())
