#!/usr/bin/env python3
"""
cw_bandpass.py — Adaptive CW audio bandpass filter with AFC.

Tight audio bandpass (25–500 Hz user-selectable bandwidth) that
auto-tracks the CW tone via peak detection. Sharper than any radio's
built-in IF filter.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np
from scipy.signal import iirpeak, sosfilt, sosfilt_zi, butter, sosfilt as sos_filter

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from dsp_pipeline import DSPBlock, Pipeline, TestSignal, add_audio_args, add_test_args


class CWBandpass(DSPBlock):
    """Adaptive CW bandpass filter with automatic frequency control."""

    def __init__(self, samplerate: int = 48000, blocksize: int = 1024,
                 center_freq: float = 700.0, bandwidth: float = 100.0,
                 afc: bool = True, afc_rate: float = 0.1):
        super().__init__(samplerate, blocksize)
        self.center_freq = center_freq
        self.bandwidth = bandwidth
        self.afc_enabled = afc
        self.afc_rate = afc_rate
        self._current_freq = center_freq
        self._sos = None
        self._zi = None
        self._update_filter()

    def _update_filter(self):
        """Recompute the bandpass filter at current frequency."""
        # 4th-order Butterworth bandpass
        low = max(20.0, self._current_freq - self.bandwidth / 2)
        high = min(self.samplerate / 2 - 1, self._current_freq + self.bandwidth / 2)
        self._sos = butter(4, [low, high], btype="band",
                           fs=self.samplerate, output="sos")
        self._zi = sosfilt_zi(self._sos)
        # scale zi to avoid transients
        self._zi = np.zeros_like(self._zi)

    def _detect_peak_frequency(self, samples: np.ndarray) -> float:
        """Find dominant frequency via FFT peak detection."""
        spectrum = np.abs(np.fft.rfft(samples * np.hanning(len(samples))))
        freqs = np.fft.rfftfreq(len(samples), 1.0 / self.samplerate)

        # only look within ±2× bandwidth of current center
        search_low = max(50, self._current_freq - 2 * self.bandwidth)
        search_high = min(self.samplerate / 2, self._current_freq + 2 * self.bandwidth)
        mask = (freqs >= search_low) & (freqs <= search_high)

        if not np.any(mask):
            return self._current_freq

        masked_spectrum = spectrum * mask
        peak_idx = np.argmax(masked_spectrum)
        peak_freq = freqs[peak_idx]

        # only track if peak is significantly above noise floor
        noise_floor = np.median(spectrum[mask])
        if spectrum[peak_idx] > 3 * noise_floor:
            return float(peak_freq)
        return self._current_freq

    def process(self, samples: np.ndarray) -> np.ndarray:
        mono = samples[:, 0] if samples.ndim == 2 else samples

        # AFC: detect peak and slew toward it
        if self.afc_enabled:
            detected = self._detect_peak_frequency(mono)
            freq_diff = detected - self._current_freq
            self._current_freq += self.afc_rate * freq_diff
            self._current_freq = np.clip(self._current_freq, 100, self.samplerate / 2 - 100)
            self._update_filter()

        # apply bandpass
        filtered, self._zi = sosfilt(self._sos, mono, zi=self._zi)
        filtered = filtered.astype(np.float32)

        if samples.ndim == 2:
            return filtered.reshape(-1, 1).repeat(samples.shape[1], axis=1)
        return filtered

    def reset(self):
        self._current_freq = self.center_freq
        self._update_filter()

    def get_status(self) -> dict:
        return {
            "enabled": self.enabled,
            "center_freq": f"{self._current_freq:.1f} Hz",
            "bandwidth": f"{self.bandwidth:.0f} Hz",
            "afc": self.afc_enabled,
        }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Adaptive CW audio bandpass filter with AFC.")
    add_audio_args(parser)
    add_test_args(parser)
    parser.add_argument("--freq", type=float, default=700.0,
                        help="Initial center frequency in Hz (default 700)")
    parser.add_argument("--bandwidth", type=float, default=100.0,
                        help="Filter bandwidth in Hz (default 100)")
    parser.add_argument("--no-afc", action="store_true",
                        help="Disable automatic frequency control")
    parser.add_argument("--afc-rate", type=float, default=0.1,
                        help="AFC tracking rate 0-1 (default 0.1)")
    parser.add_argument("--output", metavar="WAV",
                        help="Write processed audio to WAV file (test mode)")
    args = parser.parse_args()

    if args.list_devices:
        from dsp_pipeline.args import open_stream_from_args
        open_stream_from_args(args)
        return 0

    block = CWBandpass(
        samplerate=args.samplerate,
        blocksize=args.blocksize,
        center_freq=args.freq,
        bandwidth=args.bandwidth,
        afc=not args.no_afc,
        afc_rate=args.afc_rate,
    )
    pipeline = Pipeline([block], samplerate=args.samplerate, blocksize=args.blocksize)

    if args.test:
        ts = TestSignal(args.samplerate, args.test_duration)
        # CW signal at 700 Hz + interfering tone at 1200 Hz + noise
        test_audio = ts.cw_signal(freq=700, wpm=20, amplitude=0.4, noise_amplitude=0.05)
        # add interfering tone
        t = np.arange(len(test_audio)) / args.samplerate
        interference = 0.3 * np.sin(2 * np.pi * 1200 * t).astype(np.float32)
        test_audio = test_audio + interference

        processed = pipeline.process_array(test_audio.reshape(-1, 1))
        print(f"Center freq tracked to: {block._current_freq:.1f} Hz")
        print(f"Input peak:  {np.max(np.abs(test_audio)):.3f}")
        print(f"Output peak: {np.max(np.abs(processed)):.3f}")

        if args.output:
            import soundfile as sf
            sf.write(args.output, processed, args.samplerate)
            print(f"Wrote {args.output}")
    else:
        print(f"CW filter: {args.freq:.0f} Hz, BW {args.bandwidth:.0f} Hz, "
              f"AFC {'on' if not args.no_afc else 'off'}", file=sys.stderr)
        pipeline.run_realtime(
            input_device=args.input_device,
            output_device=args.output_device,
            channels_in=args.channels_in,
            channels_out=args.channels_out,
        )

    return 0


if __name__ == "__main__":
    sys.exit(main())
