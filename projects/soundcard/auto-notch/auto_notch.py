#!/usr/bin/env python3
"""
auto_notch.py — Automatic heterodyne notch filter.

Detects steady-state carriers (birdies, heterodynes, tuner-uppers) via
spectral peak detection and spawns narrow IIR notch filters at each
detected frequency. Tracks drift. Removes up to N simultaneous
heterodynes without affecting the desired signal.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np
from scipy.signal import iirnotch, sosfilt, sosfilt_zi, tf2sos

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from dsp_pipeline import DSPBlock, Pipeline, TestSignal, add_audio_args, add_test_args


class AutoNotch(DSPBlock):
    """Automatic multi-carrier notch filter."""

    def __init__(self, samplerate: int = 48000, blocksize: int = 1024,
                 max_notches: int = 5, notch_q: float = 50.0,
                 detection_threshold_db: float = 15.0,
                 min_freq: float = 100.0, max_freq: float = 4000.0,
                 tracking_rate: float = 0.2):
        super().__init__(samplerate, blocksize)
        self.max_notches = max_notches
        self.notch_q = notch_q
        self.detection_threshold_db = detection_threshold_db
        self.min_freq = min_freq
        self.max_freq = max_freq
        self.tracking_rate = tracking_rate
        self._notch_freqs: list[float] = []
        self._notch_filters: list[tuple[np.ndarray, np.ndarray]] = []  # (sos, zi)
        self._spectrum_avg = None

    def _make_notch(self, freq: float) -> tuple[np.ndarray, np.ndarray]:
        """Create a notch filter at the given frequency."""
        b, a = iirnotch(freq, self.notch_q, fs=self.samplerate)
        sos = tf2sos(b, a)
        zi = sosfilt_zi(sos) * 0
        return sos, zi

    def _detect_carriers(self, spectrum: np.ndarray, freqs: np.ndarray) -> list[float]:
        """Find spectral peaks that look like steady carriers."""
        mask = (freqs >= self.min_freq) & (freqs <= self.max_freq)
        if not np.any(mask):
            return []

        masked = spectrum.copy()
        masked[~mask] = 0

        # median noise floor in the search band
        noise_floor = np.median(spectrum[mask])
        threshold = noise_floor * (10 ** (self.detection_threshold_db / 20.0))

        # find peaks above threshold
        peaks = []
        above = masked > threshold
        indices = np.where(above)[0]

        if len(indices) == 0:
            return []

        # cluster adjacent bins
        clusters = []
        cluster_start = indices[0]
        for i in range(1, len(indices)):
            if indices[i] - indices[i-1] > 3:
                clusters.append((cluster_start, indices[i-1]))
                cluster_start = indices[i]
        clusters.append((cluster_start, indices[-1]))

        # peak of each cluster
        for start, end in clusters[:self.max_notches]:
            peak_idx = start + np.argmax(masked[start:end+1])
            peaks.append(float(freqs[peak_idx]))

        return peaks

    def process(self, samples: np.ndarray) -> np.ndarray:
        mono = samples[:, 0] if samples.ndim == 2 else samples

        # spectral analysis for carrier detection
        spectrum = np.abs(np.fft.rfft(mono * np.hanning(len(mono))))
        freqs = np.fft.rfftfreq(len(mono), 1.0 / self.samplerate)

        # smooth spectrum estimate
        if self._spectrum_avg is None:
            self._spectrum_avg = spectrum.copy()
        else:
            self._spectrum_avg = 0.8 * self._spectrum_avg + 0.2 * spectrum

        # detect carriers
        detected = self._detect_carriers(self._spectrum_avg, freqs)

        # update notch positions (track existing, add new, remove gone)
        new_freqs = []
        for det_freq in detected:
            # check if close to an existing notch
            matched = False
            for i, existing in enumerate(self._notch_freqs):
                if abs(det_freq - existing) < 50:  # within 50 Hz = same carrier
                    # track it
                    new_freq = existing + self.tracking_rate * (det_freq - existing)
                    new_freqs.append(new_freq)
                    matched = True
                    break
            if not matched and len(new_freqs) < self.max_notches:
                new_freqs.append(det_freq)

        # rebuild filters if notch set changed
        if new_freqs != self._notch_freqs:
            self._notch_freqs = new_freqs
            self._notch_filters = [self._make_notch(f) for f in self._notch_freqs]

        # apply notch filters in cascade
        output = mono.copy()
        for i, (sos, zi) in enumerate(self._notch_filters):
            output, new_zi = sosfilt(sos, output, zi=zi)
            self._notch_filters[i] = (sos, new_zi)

        output = output.astype(np.float32)
        if samples.ndim == 2:
            return output.reshape(-1, 1).repeat(samples.shape[1], axis=1)
        return output

    def reset(self):
        self._notch_freqs = []
        self._notch_filters = []
        self._spectrum_avg = None

    def get_status(self) -> dict:
        return {
            "enabled": self.enabled,
            "notches": [f"{f:.0f} Hz" for f in self._notch_freqs],
            "count": len(self._notch_freqs),
        }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Automatic heterodyne notch filter.")
    add_audio_args(parser)
    add_test_args(parser)
    parser.add_argument("--max-notches", type=int, default=5,
                        help="Maximum simultaneous notches (default 5)")
    parser.add_argument("--notch-q", type=float, default=50.0,
                        help="Notch Q factor — higher = narrower (default 50)")
    parser.add_argument("--threshold-db", type=float, default=15.0,
                        help="Detection threshold above noise floor (default 15 dB)")
    parser.add_argument("--min-freq", type=float, default=100.0,
                        help="Minimum notch frequency (default 100 Hz)")
    parser.add_argument("--max-freq", type=float, default=4000.0,
                        help="Maximum notch frequency (default 4000 Hz)")
    parser.add_argument("--tracking-rate", type=float, default=0.2,
                        help="Frequency tracking rate 0-1 (default 0.2)")
    parser.add_argument("--output", metavar="WAV",
                        help="Write processed audio to WAV file (test mode)")
    args = parser.parse_args()

    if args.list_devices:
        from dsp_pipeline.args import open_stream_from_args
        open_stream_from_args(args)
        return 0

    block = AutoNotch(
        samplerate=args.samplerate,
        blocksize=args.blocksize,
        max_notches=args.max_notches,
        notch_q=args.notch_q,
        detection_threshold_db=args.threshold_db,
        min_freq=args.min_freq,
        max_freq=args.max_freq,
        tracking_rate=args.tracking_rate,
    )
    pipeline = Pipeline([block], samplerate=args.samplerate, blocksize=args.blocksize)

    if args.test:
        ts = TestSignal(args.samplerate, args.test_duration)
        # speech-like signal with two heterodyne carriers
        test_audio = ts.speech_like(amplitude=0.3)
        t = np.arange(len(test_audio)) / args.samplerate
        het1 = 0.2 * np.sin(2 * np.pi * 1200 * t).astype(np.float32)
        het2 = 0.15 * np.sin(2 * np.pi * 2800 * t).astype(np.float32)
        test_audio = test_audio + het1 + het2

        processed = pipeline.process_array(test_audio.reshape(-1, 1))
        print(f"Detected notches: {block.get_status()['notches']}")
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
