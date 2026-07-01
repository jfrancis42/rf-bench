#!/usr/bin/env python3
"""
rain_classifier.py — Rain intensity classifier.

Classifies rain intensity in real-time from microphone audio by analyzing
spectral characteristics. Rain hitting surfaces has a signature that
varies with drop size and intensity:
- Drizzle: high-frequency broadband (small drops, fast impacts)
- Moderate: broad spectrum, mid-frequency emphasis
- Heavy: more low-frequency energy (large drops, slower impacts)
- Downpour: saturated broadband with strong LF

Also detects: dry (no rain), mist, and hail (distinctive HF clicks).
"""

from __future__ import annotations

import argparse
import signal
import sys
import time
from collections import deque
from pathlib import Path

import numpy as np
from scipy.signal import get_window

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from dsp_pipeline import DSPBlock, Pipeline, TestSignal, add_audio_args, add_test_args


# rain intensity classification thresholds and spectral profiles
RAIN_CLASSES = [
    {"name": "dry", "min_level": -80, "max_level": -50,
     "spectral_slope": None, "description": "No precipitation"},
    {"name": "mist", "min_level": -55, "max_level": -45,
     "spectral_slope": (-1, -3), "description": "Very light, barely audible"},
    {"name": "drizzle", "min_level": -45, "max_level": -35,
     "spectral_slope": (-2, -5), "description": "Light, steady"},
    {"name": "moderate", "min_level": -35, "max_level": -25,
     "spectral_slope": (-3, -6), "description": "Steady rain"},
    {"name": "heavy", "min_level": -25, "max_level": -15,
     "spectral_slope": (-4, -8), "description": "Hard rain"},
    {"name": "downpour", "min_level": -15, "max_level": 0,
     "spectral_slope": (-5, -10), "description": "Torrential"},
]


class RainClassifier(DSPBlock):
    """Classifies rain intensity from spectral characteristics."""

    def __init__(self, samplerate: int = 48000, blocksize: int = 1024,
                 fft_size: int = 4096, averaging: int = 10):
        super().__init__(samplerate, blocksize)
        self.fft_size = fft_size
        self.averaging = averaging

        self._buffer = np.zeros(0, dtype=np.float32)
        self._spectrum_history = deque(maxlen=averaging)
        self._window = get_window("hann", fft_size).astype(np.float32)

        # output state
        self.classification = "dry"
        self.confidence = 0.0
        self.level_db = -100.0
        self.spectral_centroid = 0.0
        self.spectral_slope = 0.0
        self.spectral_flatness = 0.0
        self.rain_rate_mm_hr = 0.0

    def _compute_features(self, spectrum: np.ndarray,
                           freqs: np.ndarray) -> dict:
        """Extract spectral features relevant to rain classification."""
        # level
        power = np.sum(spectrum ** 2)
        level_db = 10 * np.log10(power + 1e-10) - 10 * np.log10(len(spectrum))

        # spectral centroid (center of mass)
        total_power = np.sum(spectrum) + 1e-10
        centroid = np.sum(freqs * spectrum) / total_power

        # spectral slope (dB/octave)
        # fit line to log-frequency vs dB spectrum
        mask = (freqs >= 100) & (freqs <= 10000)
        if np.sum(mask) > 10:
            log_freqs = np.log2(freqs[mask] + 1e-10)
            db_spectrum = 20 * np.log10(spectrum[mask] + 1e-10)
            # linear regression
            n = np.sum(mask)
            x = log_freqs
            y = db_spectrum
            slope = (n * np.sum(x * y) - np.sum(x) * np.sum(y)) / \
                    (n * np.sum(x ** 2) - np.sum(x) ** 2 + 1e-10)
        else:
            slope = 0.0

        # spectral flatness (Wiener entropy)
        # flat = 1 (white noise), peaked = 0 (tonal)
        log_spectrum = np.log(spectrum[1:] + 1e-10)
        geometric_mean = np.exp(np.mean(log_spectrum))
        arithmetic_mean = np.mean(spectrum[1:])
        flatness = geometric_mean / (arithmetic_mean + 1e-10)

        # high-frequency ratio (> 4 kHz vs total)
        hf_mask = freqs >= 4000
        hf_ratio = np.sum(spectrum[hf_mask] ** 2) / (power + 1e-10)

        # low-frequency ratio (< 500 Hz vs total)
        lf_mask = (freqs >= 50) & (freqs <= 500)
        lf_ratio = np.sum(spectrum[lf_mask] ** 2) / (power + 1e-10)

        # impulsiveness (kurtosis — hail has high kurtosis)
        if np.std(spectrum) > 0:
            kurtosis = np.mean((spectrum - np.mean(spectrum)) ** 4) / \
                       (np.std(spectrum) ** 4 + 1e-10)
        else:
            kurtosis = 0.0

        return {
            "level_db": level_db,
            "centroid": centroid,
            "slope": slope,
            "flatness": flatness,
            "hf_ratio": hf_ratio,
            "lf_ratio": lf_ratio,
            "kurtosis": kurtosis,
        }

    def _classify(self, features: dict) -> tuple[str, float]:
        """Classify rain intensity from spectral features."""
        level = features["level_db"]
        flatness = features["flatness"]
        slope = features["slope"]
        centroid = features["centroid"]
        kurtosis = features["kurtosis"]

        # hail detection: extremely high kurtosis (very impulsive) + high HF
        if kurtosis > 30 and features["hf_ratio"] > 0.4 and level > -30:
            return "hail", min(1.0, kurtosis / 50.0)

        # rain requires: broadband (flatness > 0.3) AND some level
        if flatness < 0.2 or level < -55:
            return "dry", max(0.0, 1.0 - flatness * 2)

        # classify by level combined with spectral slope
        # steeper negative slope = larger drops = heavier rain
        # levels are relative to the FFT analysis, not absolute dBFS
        if level < -50:
            return "dry", 0.7
        elif level < -40:
            if flatness > 0.5:
                return "mist", min(1.0, flatness)
            return "dry", 0.5
        elif level < -30:
            return "drizzle", min(1.0, (level + 40) / 10 * 0.5 + 0.5)
        elif level < -15:
            return "moderate", min(1.0, (level + 30) / 15 * 0.5 + 0.5)
        elif level < 0:
            return "heavy", min(1.0, (level + 15) / 15 * 0.5 + 0.5)
        else:
            return "downpour", min(1.0, (level + 5) / 10 * 0.5 + 0.5)

    def _estimate_rain_rate(self, classification: str, level_db: float) -> float:
        """Rough rain rate estimate in mm/hr from classification."""
        rates = {
            "dry": 0.0,
            "mist": 0.1,
            "drizzle": 1.0,
            "moderate": 5.0,
            "heavy": 20.0,
            "downpour": 50.0,
            "hail": 30.0,
        }
        base = rates.get(classification, 0.0)
        # scale within class by level
        return base

    def process(self, samples: np.ndarray) -> np.ndarray:
        mono = samples[:, 0] if samples.ndim == 2 else samples
        self._buffer = np.concatenate([self._buffer, mono])

        while len(self._buffer) >= self.fft_size:
            frame = self._buffer[:self.fft_size]
            self._buffer = self._buffer[self.fft_size // 2:]

            # compute spectrum
            windowed = frame * self._window
            spectrum = np.abs(np.fft.rfft(windowed))
            self._spectrum_history.append(spectrum)

        # average spectra for stability
        if len(self._spectrum_history) >= 3:
            avg_spectrum = np.mean(list(self._spectrum_history), axis=0)
            freqs = np.fft.rfftfreq(self.fft_size, 1.0 / self.samplerate)

            features = self._compute_features(avg_spectrum, freqs)
            classification, confidence = self._classify(features)

            self.classification = classification
            self.confidence = confidence
            self.level_db = features["level_db"]
            self.spectral_centroid = features["centroid"]
            self.spectral_slope = features["slope"]
            self.spectral_flatness = features["flatness"]
            self.rain_rate_mm_hr = self._estimate_rain_rate(
                classification, features["level_db"])

        return samples

    def get_status(self) -> dict:
        return {
            "classification": self.classification,
            "confidence": self.confidence,
            "level_db": self.level_db,
            "centroid_hz": self.spectral_centroid,
            "slope_db_oct": self.spectral_slope,
            "flatness": self.spectral_flatness,
            "rain_rate_mm_hr": self.rain_rate_mm_hr,
        }

    def reset(self):
        self._buffer = np.zeros(0, dtype=np.float32)
        self._spectrum_history.clear()


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Rain intensity classifier — estimate precipitation "
        "from audio spectral characteristics.")
    add_audio_args(parser, duplex=False)
    add_test_args(parser)
    parser.add_argument("--fft-size", type=int, default=4096,
                        help="FFT size for spectral analysis (default: 4096)")
    parser.add_argument("--averaging", type=int, default=10,
                        help="Number of spectra to average (default: 10)")
    parser.add_argument("--csv", metavar="FILE",
                        help="Log classifications to CSV")
    parser.add_argument("--interval", type=float, default=2.0,
                        help="Logging interval in seconds (default: 2)")
    args = parser.parse_args()

    if args.list_devices:
        from dsp_pipeline.args import open_stream_from_args
        open_stream_from_args(args, duplex=False)
        return 0

    samplerate = args.samplerate
    blocksize = args.blocksize

    classifier = RainClassifier(
        samplerate=samplerate,
        blocksize=blocksize,
        fft_size=args.fft_size,
        averaging=args.averaging,
    )

    pipeline = Pipeline([classifier], samplerate=samplerate, blocksize=blocksize)

    if args.test:
        # simulate different rain intensities
        # amplitude controls overall level; slope_factor controls HF rolloff
        scenarios = [
            ("dry", 0.0001, 0.0),
            ("drizzle", 0.002, 0.3),
            ("moderate", 0.010, 0.5),
            ("heavy", 0.050, 0.8),
            ("downpour", 0.250, 1.0),
        ]

        print("Test mode: simulating rain intensities\n")
        print(f"{'Scenario':<12} {'Level':<8} {'Class':<12} "
              f"{'Confidence':<12} {'Flatness':<10}")
        print("-" * 54)

        for name, amplitude, slope_factor in scenarios:
            n_samples = int(2.0 * samplerate)
            # rain-like noise: shaped broadband
            white = np.random.randn(n_samples).astype(np.float32)
            # apply spectral slope (more slope = more LF = heavier rain)
            fft_noise = np.fft.rfft(white)
            freqs = np.fft.rfftfreq(n_samples, 1.0 / samplerate)
            # slope filter: attenuate HF for heavier rain
            slope_filter = np.ones_like(freqs)
            slope_filter[1:] = (freqs[1:] / 1000.0) ** (-slope_factor)
            rain_noise = np.fft.irfft(fft_noise * slope_filter,
                                       n=n_samples).astype(np.float32)
            rain_noise *= amplitude / (np.max(np.abs(rain_noise)) + 1e-10)

            # process (no impulsive drops — keeps it clean for classification)
            classifier.reset()
            pipeline.process_array(rain_noise.reshape(-1, 1))

            status = classifier.get_status()
            print(f"{name:<12} {status['level_db']:>6.1f}  "
                  f"{status['classification']:<12} "
                  f"{status['confidence']:<12.2f} "
                  f"{status['flatness']:<10.3f}")

        print("\nClassification complete.")
    else:
        from dsp_pipeline.stream import AudioStream

        stream = AudioStream(
            input_device=args.input_device,
            samplerate=samplerate,
            blocksize=blocksize,
            channels_in=1,
        )

        csv_file = None
        if args.csv:
            csv_file = open(args.csv, "w")
            csv_file.write("timestamp,classification,confidence,level_db,"
                           "centroid_hz,slope_db_oct,flatness,rain_rate_mm_hr\n")

        def callback(indata, frames):
            pipeline.process_block(indata)
            return None

        stream.set_callback(callback)
        stop = [False]

        def handler(s, f):
            stop[0] = True
        old_handler = signal.signal(signal.SIGINT, handler)

        intensity_bar = {
            "dry": "░░░░░░░░░░",
            "mist": "▒░░░░░░░░░",
            "drizzle": "▒▒░░░░░░░░",
            "moderate": "▒▒▒▒░░░░░░",
            "heavy": "█▒▒▒▒▒░░░░",
            "downpour": "██████████",
            "hail": "⚡⚡⚡⚡⚡⚡⚡⚡⚡⚡",
        }

        try:
            stream.start()
            print(f"Rain classifier running", file=sys.stderr)
            print("  Ctrl-C to stop\n", file=sys.stderr)
            last_log = time.time()

            while not stop[0]:
                time.sleep(0.5)
                status = classifier.get_status()
                bar = intensity_bar.get(status["classification"], "??????????")
                print(f"\r  [{bar}] {status['classification']:>10} "
                      f"({status['confidence']:.0%}) | "
                      f"{status['level_db']:>5.1f} dB | "
                      f"~{status['rain_rate_mm_hr']:.1f} mm/hr",
                      end="", flush=True)

                # periodic CSV logging
                if csv_file and time.time() - last_log >= args.interval:
                    last_log = time.time()
                    csv_file.write(f"{time.time():.1f},"
                                   f"{status['classification']},"
                                   f"{status['confidence']:.2f},"
                                   f"{status['level_db']:.1f},"
                                   f"{status['centroid_hz']:.0f},"
                                   f"{status['slope_db_oct']:.1f},"
                                   f"{status['flatness']:.3f},"
                                   f"{status['rain_rate_mm_hr']:.1f}\n")
                    csv_file.flush()
        finally:
            stream.stop()
            signal.signal(signal.SIGINT, old_handler)
            if csv_file:
                csv_file.close()
            print()

    return 0


if __name__ == "__main__":
    sys.exit(main())
