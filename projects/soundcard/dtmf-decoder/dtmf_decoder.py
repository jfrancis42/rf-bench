#!/usr/bin/env python3
"""
dtmf_decoder.py — DTMF (Dual-Tone Multi-Frequency) decoder.

Uses the Goertzel algorithm to detect the 8 DTMF frequencies:
  Low group:  697, 770, 852, 941 Hz
  High group: 1209, 1336, 1477, 1633 Hz

Decodes digits 0-9, A-D, *, #. Logs detected digits with timestamps.
Includes twist detection (high/low group level balance) and minimum
duration validation per ITU-T Q.24 (40 ms on, 40 ms off).
"""

from __future__ import annotations

import argparse
import csv
import signal
import sys
import time
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from dsp_pipeline import DSPBlock, Pipeline, TestSignal, add_audio_args, add_test_args
from dsp_pipeline.stream import AudioStream


# DTMF frequency assignments
LOW_FREQS = [697, 770, 852, 941]
HIGH_FREQS = [1209, 1336, 1477, 1633]

# Digit map: (low_index, high_index) -> digit
DIGIT_MAP = {
    (0, 0): "1", (0, 1): "2", (0, 2): "3", (0, 3): "A",
    (1, 0): "4", (1, 1): "5", (1, 2): "6", (1, 3): "B",
    (2, 0): "7", (2, 1): "8", (2, 2): "9", (2, 3): "C",
    (3, 0): "*", (3, 1): "0", (3, 2): "#", (3, 3): "D",
}


def goertzel_magnitude(samples: np.ndarray, target_freq: float, samplerate: int) -> float:
    """Compute Goertzel magnitude-squared for a single frequency.

    More efficient than FFT when only a few frequencies are needed.
    Returns the power (magnitude squared) at target_freq.
    """
    n = len(samples)
    k = int(0.5 + n * target_freq / samplerate)
    omega = 2.0 * np.pi * k / n
    coeff = 2.0 * np.cos(omega)

    s0 = 0.0
    s1 = 0.0
    s2 = 0.0

    for sample in samples:
        s0 = sample + coeff * s1 - s2
        s2 = s1
        s1 = s0

    # magnitude squared (avoid sqrt for threshold comparison)
    power = s1 * s1 + s2 * s2 - coeff * s1 * s2
    return power / (n * n)


def goertzel_magnitude_vectorized(samples: np.ndarray, target_freq: float, samplerate: int) -> float:
    """Vectorized Goertzel — faster for numpy arrays."""
    n = len(samples)
    k = int(0.5 + n * target_freq / samplerate)
    omega = 2.0 * np.pi * k / n
    coeff = 2.0 * np.cos(omega)

    s1 = 0.0
    s2 = 0.0

    for i in range(n):
        s0 = samples[i] + coeff * s1 - s2
        s2 = s1
        s1 = s0

    power = s1 * s1 + s2 * s2 - coeff * s1 * s2
    return power / (n * n)


class DTMFDecoder(DSPBlock):
    """Real-time DTMF tone decoder using Goertzel algorithm.

    Detects DTMF digits with twist validation and minimum duration
    enforcement per ITU-T Q.24.
    """

    def __init__(
        self,
        samplerate: int = 48000,
        blocksize: int = 1024,
        threshold_db: float = -30.0,
        max_twist_db: float = 4.0,
        max_reverse_twist_db: float = 8.0,
        min_on_ms: float = 40.0,
        min_off_ms: float = 40.0,
    ):
        super().__init__(samplerate, blocksize)
        self.threshold = 10 ** (threshold_db / 10.0)  # power threshold
        self.max_twist = 10 ** (max_twist_db / 10.0)  # high/low ratio limit
        self.max_reverse_twist = 10 ** (max_reverse_twist_db / 10.0)  # low/high ratio limit
        self.min_on_samples = int(min_on_ms * samplerate / 1000.0)
        self.min_off_samples = int(min_off_ms * samplerate / 1000.0)

        # State
        self._current_digit: str | None = None
        self._digit_start_sample: int = 0
        self._digit_on_count: int = 0  # consecutive samples with this digit
        self._off_count: int = 0  # consecutive samples with no detection
        self._digit_confirmed: bool = False
        self._total_samples: int = 0
        self._detected_digits: list[tuple[float, str, float, float]] = []  # (timestamp, digit, low_db, high_db)
        self._last_digit: str | None = None

    def process(self, samples: np.ndarray) -> np.ndarray:
        """Process a block of audio, detect DTMF tones."""
        mono = samples[:, 0] if samples.ndim == 2 else samples
        mono = mono.astype(np.float64)

        # Compute Goertzel power for each DTMF frequency
        low_powers = np.array([goertzel_magnitude_vectorized(mono, f, self.samplerate) for f in LOW_FREQS])
        high_powers = np.array([goertzel_magnitude_vectorized(mono, f, self.samplerate) for f in HIGH_FREQS])

        # Find strongest in each group
        low_idx = np.argmax(low_powers)
        high_idx = np.argmax(high_powers)
        low_power = low_powers[low_idx]
        high_power = high_powers[high_idx]

        # Check threshold — both tones must be above minimum level
        detected_digit = None
        if low_power > self.threshold and high_power > self.threshold:
            # Twist check: ratio between high and low group levels
            # Normal twist: high > low (acceptable up to max_twist)
            # Reverse twist: low > high (acceptable up to max_reverse_twist)
            if high_power > low_power:
                twist_ratio = high_power / low_power
                if twist_ratio <= self.max_twist:
                    detected_digit = DIGIT_MAP.get((low_idx, high_idx))
            else:
                reverse_ratio = low_power / high_power
                if reverse_ratio <= self.max_reverse_twist:
                    detected_digit = DIGIT_MAP.get((low_idx, high_idx))

            # Second tone in each group must be significantly weaker
            # (reject multi-tone interference / talk-off)
            low_sorted = np.sort(low_powers)[::-1]
            high_sorted = np.sort(high_powers)[::-1]
            if low_sorted[0] > 0 and low_sorted[1] / low_sorted[0] > 0.5:
                detected_digit = None
            if high_sorted[0] > 0 and high_sorted[1] / high_sorted[0] > 0.5:
                detected_digit = None

        # Duration-based state machine
        block_samples = len(mono)
        self._total_samples += block_samples

        if detected_digit is not None:
            if detected_digit == self._current_digit:
                self._digit_on_count += block_samples
                self._off_count = 0
            else:
                # New digit detected — check if we had enough off time
                if self._current_digit is not None and self._off_count < self.min_off_samples:
                    # Not enough gap, could be glitch. Keep current.
                    pass
                else:
                    self._current_digit = detected_digit
                    self._digit_on_count = block_samples
                    self._off_count = 0
                    self._digit_confirmed = False
                    self._digit_start_sample = self._total_samples - block_samples

            # Confirm digit after minimum on duration
            if (not self._digit_confirmed and
                    self._digit_on_count >= self.min_on_samples and
                    self._current_digit is not None):
                self._digit_confirmed = True
                timestamp = self._digit_start_sample / self.samplerate
                low_db = 10 * np.log10(low_power + 1e-12)
                high_db = 10 * np.log10(high_power + 1e-12)
                self._detected_digits.append((timestamp, self._current_digit, low_db, high_db))
                self._last_digit = self._current_digit
        else:
            self._off_count += block_samples
            if self._off_count >= self.min_off_samples:
                self._current_digit = None
                self._digit_on_count = 0
                self._digit_confirmed = False

        return samples  # pass through

    def get_detected_digits(self) -> list[tuple[float, str, float, float]]:
        """Return list of (timestamp_sec, digit, low_db, high_db)."""
        return list(self._detected_digits)

    def get_digit_string(self) -> str:
        """Return all detected digits as a string."""
        return "".join(d[1] for d in self._detected_digits)

    def get_status(self) -> dict:
        return {
            "enabled": self.enabled,
            "current_digit": self._current_digit or "-",
            "total_detected": len(self._detected_digits),
            "digit_string": self.get_digit_string(),
            "last_digit": self._last_digit or "-",
        }

    def reset(self):
        self._current_digit = None
        self._digit_on_count = 0
        self._off_count = 0
        self._digit_confirmed = False
        self._total_samples = 0
        self._detected_digits = []
        self._last_digit = None


def main() -> int:
    parser = argparse.ArgumentParser(
        description="DTMF (Dual-Tone Multi-Frequency) decoder.")
    add_audio_args(parser, duplex=False)
    add_test_args(parser)
    parser.add_argument("--threshold", type=float, default=-30.0, metavar="DB",
                        help="Detection threshold in dB (default -30)")
    parser.add_argument("--max-twist", type=float, default=4.0, metavar="DB",
                        help="Max normal twist high/low in dB (default 4)")
    parser.add_argument("--max-reverse-twist", type=float, default=8.0, metavar="DB",
                        help="Max reverse twist low/high in dB (default 8)")
    parser.add_argument("--min-on", type=float, default=40.0, metavar="MS",
                        help="Minimum tone-on duration in ms (default 40, ITU-T Q.24)")
    parser.add_argument("--min-off", type=float, default=40.0, metavar="MS",
                        help="Minimum tone-off gap in ms (default 40, ITU-T Q.24)")
    parser.add_argument("--output", metavar="CSV",
                        help="Log detected digits to CSV file")
    parser.add_argument("--continuous", action="store_true",
                        help="Run continuously (default: stop after --test-duration)")
    args = parser.parse_args()

    if args.list_devices:
        from dsp_pipeline.args import open_stream_from_args
        open_stream_from_args(args, duplex=False)
        return 0

    block = DTMFDecoder(
        samplerate=args.samplerate,
        blocksize=args.blocksize,
        threshold_db=args.threshold,
        max_twist_db=args.max_twist,
        max_reverse_twist_db=args.max_reverse_twist,
        min_on_ms=args.min_on,
        min_off_ms=args.min_off,
    )

    if args.test:
        # Generate synthetic DTMF sequence: "1234567890*#ABCD"
        test_digits = "1234567890*#ABCD"
        ts = TestSignal(args.samplerate, args.test_duration)
        test_audio = ts.dtmf(digits=test_digits, digit_duration=0.1, pause=0.05)

        pipeline = Pipeline([block], samplerate=args.samplerate, blocksize=args.blocksize)
        pipeline.process_array(test_audio.reshape(-1, 1))

        detected = block.get_digit_string()
        print(f"Test sequence: {test_digits}")
        print(f"Detected:      {detected}")
        print(f"Match:         {'OK' if detected == test_digits else 'MISMATCH'}")
        print()
        print("Digit details:")
        print(f"  {'Time':>8s}  {'Digit':>5s}  {'Low dB':>7s}  {'High dB':>7s}")
        for ts_val, digit, low_db, high_db in block.get_detected_digits():
            print(f"  {ts_val:8.3f}  {digit:>5s}  {low_db:7.1f}  {high_db:7.1f}")

        if args.output:
            _write_csv(args.output, block.get_detected_digits())
            print(f"\nCSV written to {args.output}")
    else:
        # Real-time continuous decode
        stream = AudioStream(
            input_device=args.input_device,
            samplerate=args.samplerate,
            blocksize=args.blocksize,
            channels_in=args.channels_in,
        )

        def callback(indata, frames):
            block.process(indata)
            return None

        stream.set_callback(callback)
        stop = [False]

        def handler(s, f):
            stop[0] = True
        old = signal.signal(signal.SIGINT, handler)

        prev_count = 0
        try:
            stream.start()
            print("DTMF decoder running... Ctrl-C to stop", file=sys.stderr)
            print(file=sys.stderr)
            while not stop[0]:
                time.sleep(0.1)
                digits = block.get_detected_digits()
                if len(digits) > prev_count:
                    for ts_val, digit, low_db, high_db in digits[prev_count:]:
                        print(f"[{ts_val:8.3f}s] {digit}  (low {low_db:+.1f} dB, high {high_db:+.1f} dB)")
                    prev_count = len(digits)
        finally:
            stream.stop()
            signal.signal(signal.SIGINT, old)
            print(file=sys.stderr)
            print(f"Decoded: {block.get_digit_string()}", file=sys.stderr)
            if args.output:
                _write_csv(args.output, block.get_detected_digits())
                print(f"CSV written to {args.output}", file=sys.stderr)

    return 0


def _write_csv(path: str, digits: list[tuple[float, str, float, float]]) -> None:
    """Write detected digits to CSV."""
    with open(path, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["timestamp", "digit", "low_db", "high_db"])
        for ts_val, digit, low_db, high_db in digits:
            writer.writerow([f"{ts_val:.3f}", digit, f"{low_db:.1f}", f"{high_db:.1f}"])


if __name__ == "__main__":
    sys.exit(main())
