#!/usr/bin/env python3
"""
insect_classifier.py — Classify flying insects by wing-beat frequency.

Wing-beat frequency is species-specific and remarkably stable. This tool
detects periodic energy in species-specific frequency bands using
autocorrelation and Goertzel filters, then classifies the insect.

Can even sex mosquitoes: females ~400 Hz, males ~600 Hz.

Detection pipeline:
1. Bandpass prefilter (100-800 Hz) to isolate wing-beat range
2. Multi-band Goertzel energy detection for coarse frequency lock
3. Autocorrelation for precise fundamental frequency measurement
4. Species matching against known wing-beat frequency database
5. Confidence scoring based on periodicity strength and band energy
"""

from __future__ import annotations

import argparse
import csv
import signal
import sys
import time
from datetime import datetime
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from dsp_pipeline import DSPBlock, Pipeline, TestSignal, add_audio_args, add_test_args


# ─── Insect database ───────────────────────────────────────────────────────────

INSECT_DB = [
    # (name, freq_low, freq_high, notes)
    ("Mosquito (female, Aedes aegypti)", 380, 470, "Yellow fever / dengue vector"),
    ("Mosquito (male, Aedes aegypti)", 550, 650, "Higher pitch than female"),
    ("Mosquito (female, Anopheles)", 350, 420, "Malaria vector"),
    ("Mosquito (male, Anopheles)", 500, 620, "Higher pitch than female"),
    ("Mosquito (female, Culex)", 360, 440, "Common house mosquito"),
    ("Mosquito (male, Culex)", 520, 600, "Higher pitch than female"),
    ("Housefly (Musca domestica)", 170, 210, "Common housefly"),
    ("Honeybee (Apis mellifera)", 210, 250, "Worker bee in flight"),
    ("Honeybee (loaded, returning)", 180, 220, "Heavy with pollen/nectar"),
    ("Bumblebee (Bombus)", 110, 150, "Large, slow wingbeat"),
    ("Wasp (Vespula)", 140, 180, "Yellowjacket/paper wasp"),
    ("Hornet (Vespa)", 100, 140, "Larger than wasp, slower beat"),
    ("Blowfly (Calliphora)", 140, 170, "Bluebottle/greenbottle"),
    ("Fruit fly (Drosophila)", 200, 240, "Small, fast wingbeat"),
    ("Hover fly (Syrphidae)", 160, 200, "Mimics bees, different frequency"),
    ("Dragonfly (Odonata)", 25, 45, "Very slow wingbeat, large wings"),
    ("Midge (Chironomidae)", 450, 550, "Non-biting midge swarms"),
    ("Crane fly (Tipulidae)", 45, 65, "Daddy longlegs, very slow"),
]


def get_species_match(freq_hz: float) -> list[tuple[str, float]]:
    """Return matching species with confidence based on how centered the
    frequency is within each species' range.

    Returns list of (name, match_score) sorted by score descending.
    """
    matches = []
    for name, f_lo, f_hi, notes in INSECT_DB:
        if f_lo <= freq_hz <= f_hi:
            # confidence: 1.0 at center, lower toward edges
            center = (f_lo + f_hi) / 2.0
            half_range = (f_hi - f_lo) / 2.0
            distance = abs(freq_hz - center) / half_range if half_range > 0 else 0
            score = 1.0 - 0.4 * distance  # 1.0 at center, 0.6 at edge
            matches.append((name, score))
    matches.sort(key=lambda x: x[1], reverse=True)
    return matches


# ─── Goertzel filter ───────────────────────────────────────────────────────────

def goertzel_magnitude(samples: np.ndarray, target_freq: float, samplerate: int) -> float:
    """Compute Goertzel magnitude for a single target frequency.

    More efficient than FFT when checking a small number of frequencies.
    Returns magnitude (not power) normalized by block length.
    """
    n = len(samples)
    k = int(0.5 + n * target_freq / samplerate)
    w = 2 * np.pi * k / n
    coeff = 2 * np.cos(w)

    s0 = 0.0
    s1 = 0.0
    s2 = 0.0

    for sample in samples:
        s0 = sample + coeff * s1 - s2
        s2 = s1
        s1 = s0

    magnitude = np.sqrt(s1 * s1 + s2 * s2 - coeff * s1 * s2)
    return magnitude / n


def goertzel_magnitude_vectorized(samples: np.ndarray, target_freq: float,
                                  samplerate: int) -> float:
    """Vectorized Goertzel — faster for numpy arrays."""
    n = len(samples)
    k = int(0.5 + n * target_freq / samplerate)
    w = 2 * np.pi * k / n
    coeff = 2 * np.cos(w)

    # Process in a loop (Goertzel is inherently sequential)
    # but the samples are already numpy so indexing is fast
    s1 = 0.0
    s2 = 0.0
    for i in range(n):
        s0 = float(samples[i]) + coeff * s1 - s2
        s2 = s1
        s1 = s0

    magnitude = np.sqrt(s1 * s1 + s2 * s2 - coeff * s1 * s2)
    return magnitude / n


# ─── DSP Block ─────────────────────────────────────────────────────────────────

class InsectClassifier(DSPBlock):
    """Detects and classifies flying insects by wing-beat frequency."""

    def __init__(self, samplerate: int = 48000, blocksize: int = 1024,
                 min_confidence: float = 0.3, analysis_window: int = 4,
                 noise_gate_db: float = -50.0):
        super().__init__(samplerate, blocksize)
        self.min_confidence = min_confidence
        self.noise_gate_db = noise_gate_db

        # Analysis accumulates multiple blocks for better frequency resolution
        self.analysis_window = analysis_window  # number of blocks to accumulate
        self._buffer = np.zeros(blocksize * analysis_window, dtype=np.float32)
        self._buffer_pos = 0
        self._blocks_accumulated = 0

        # Bandpass filter state (100-800 Hz, 2nd order Butterworth)
        self._design_bandpass()

        # Goertzel probe frequencies: sample across all species bands
        self._probe_freqs = self._generate_probe_frequencies()

        # Results
        self._detected_freq = 0.0
        self._periodicity = 0.0
        self._confidence = 0.0
        self._species = ""
        self._species_score = 0.0
        self._band_energy_db = -100.0
        self._noise_floor = 1e-6
        self._noise_alpha = 0.01

    def _design_bandpass(self):
        """Design IIR bandpass filter coefficients (biquad cascade)."""
        # Simple 2nd-order bandpass using bilinear transform
        # Passband: 80-850 Hz (wider than species range to avoid edge effects)
        f_lo = 80.0
        f_hi = 850.0
        # We'll use a simple FIR approach for robustness
        # Design a windowed-sinc bandpass FIR
        ntaps = 127
        nyq = self.samplerate / 2.0
        # Normalized frequencies
        lo = f_lo / nyq
        hi = f_hi / nyq
        # FIR bandpass via windowed sinc
        n = np.arange(ntaps)
        mid = (ntaps - 1) / 2
        denom = np.pi * (n - mid)
        denom_safe = np.where(n == mid, 1.0, denom)  # avoid div-by-zero
        # lowpass at hi
        h_hi = np.where(n == mid, hi, np.sin(np.pi * hi * (n - mid)) / denom_safe)
        # lowpass at lo
        h_lo = np.where(n == mid, lo, np.sin(np.pi * lo * (n - mid)) / denom_safe)
        # bandpass = hi - lo
        h_bp = (h_hi - h_lo) * np.hamming(ntaps)
        self._bp_fir = h_bp.astype(np.float32)
        self._bp_state = np.zeros(ntaps - 1, dtype=np.float32)

    def _apply_bandpass(self, samples: np.ndarray) -> np.ndarray:
        """Apply bandpass FIR filter with state (overlap-save)."""
        # Use numpy convolve with state preservation
        extended = np.concatenate([self._bp_state, samples])
        filtered = np.convolve(extended, self._bp_fir, mode='valid')
        # Save state for next block
        state_len = len(self._bp_fir) - 1
        self._bp_state = extended[-state_len:]
        return filtered[:len(samples)].astype(np.float32)

    def _generate_probe_frequencies(self) -> np.ndarray:
        """Generate Goertzel probe frequencies covering all species bands."""
        # Cover 25-800 Hz in ~5 Hz steps — dense enough to find fundamentals
        return np.arange(25, 800, 5, dtype=np.float32)

    def _find_fundamental_autocorr(self, samples: np.ndarray) -> tuple[float, float]:
        """Find fundamental frequency via autocorrelation.

        Returns (frequency_hz, periodicity_strength).
        periodicity_strength is 0-1 where 1 = perfectly periodic.
        """
        n = len(samples)
        if n < 200:
            return 0.0, 0.0

        # Remove DC
        frame = samples - np.mean(samples)
        energy = np.sum(frame ** 2)
        if energy < 1e-10:
            return 0.0, 0.0

        # Lag range: 1.2 ms (833 Hz) to 40 ms (25 Hz)
        # Covers all species from dragonfly (25 Hz) to midge (550 Hz)
        min_lag = max(1, int(self.samplerate / 833.0))
        max_lag = min(n // 2, int(self.samplerate / 25.0))

        if max_lag <= min_lag:
            return 0.0, 0.0

        # FFT-based autocorrelation (much faster for large windows)
        nfft = 1
        while nfft < 2 * n:
            nfft *= 2
        spectrum = np.fft.rfft(frame, n=nfft)
        power_spectrum = spectrum * np.conj(spectrum)
        acf_full = np.fft.irfft(power_spectrum, n=nfft)[:n]

        # Normalize
        acf_full = acf_full / (energy + 1e-10)

        # Extract search region
        search = acf_full[min_lag:max_lag]
        if len(search) == 0:
            return 0.0, 0.0

        # Find the highest peak
        peak_idx = np.argmax(search)
        peak_val = float(search[peak_idx])

        if peak_val < 0.1:
            return 0.0, 0.0

        # Parabolic interpolation for sub-sample accuracy
        lag = peak_idx + min_lag
        if 0 < peak_idx < len(search) - 1:
            alpha = float(search[peak_idx - 1])
            beta = float(search[peak_idx])
            gamma = float(search[peak_idx + 1])
            denom = alpha - 2 * beta + gamma
            if abs(denom) > 1e-10:
                correction = 0.5 * (alpha - gamma) / denom
                lag = peak_idx + min_lag + correction

        freq = self.samplerate / lag if lag > 0 else 0.0
        return freq, peak_val

    def _compute_band_energy(self, samples: np.ndarray, freq: float) -> float:
        """Compute energy in a narrow band around the detected frequency.

        Uses Goertzel at the fundamental and first few harmonics.
        Returns energy in dB relative to full-scale.
        """
        if freq < 20:
            return -100.0

        total = 0.0
        # Fundamental + harmonics (up to 3rd)
        for h in range(1, 4):
            f = freq * h
            if f > self.samplerate / 2:
                break
            mag = goertzel_magnitude_vectorized(samples, f, self.samplerate)
            total += mag ** 2

        if total < 1e-20:
            return -100.0
        return 10.0 * np.log10(total)

    def _update_noise_floor(self, power: float):
        """Track noise floor when no detection is active."""
        if self._confidence < self.min_confidence:
            self._noise_floor += self._noise_alpha * (power - self._noise_floor)
            self._noise_floor = max(self._noise_floor, 1e-10)

    def process(self, samples: np.ndarray) -> np.ndarray:
        """Process a block: accumulate, analyze when window is full."""
        mono = samples[:, 0] if samples.ndim == 2 else samples

        # Apply bandpass filter
        filtered = self._apply_bandpass(mono)

        # Accumulate into analysis window
        n = len(filtered)
        start = self._buffer_pos
        end = start + n
        if end > len(self._buffer):
            # wrap: start fresh
            self._buffer_pos = 0
            self._blocks_accumulated = 0
            start = 0
            end = n
        self._buffer[start:end] = filtered
        self._buffer_pos = end
        self._blocks_accumulated += 1

        # Analyze when we have enough data
        if self._blocks_accumulated >= self.analysis_window:
            analysis_samples = self._buffer[:self._buffer_pos].copy()
            self._buffer_pos = 0
            self._blocks_accumulated = 0
            self._analyze(analysis_samples)

        # Pass through unchanged (this is an analysis tool, not a filter)
        return samples

    def _analyze(self, samples: np.ndarray):
        """Run full classification on accumulated samples."""
        # Noise gate
        power = float(np.mean(samples ** 2))
        self._update_noise_floor(power)
        power_db = 10.0 * np.log10(power + 1e-10)

        if power_db < self.noise_gate_db:
            self._detected_freq = 0.0
            self._periodicity = 0.0
            self._confidence = 0.0
            self._species = ""
            self._species_score = 0.0
            self._band_energy_db = -100.0
            return

        # Step 1: Autocorrelation for fundamental frequency
        freq, periodicity = self._find_fundamental_autocorr(samples)

        if freq < 20 or periodicity < 0.15:
            self._detected_freq = 0.0
            self._periodicity = 0.0
            self._confidence = 0.0
            self._species = ""
            self._species_score = 0.0
            self._band_energy_db = -100.0
            return

        # Step 2: Band energy at the detected frequency
        band_energy_db = self._compute_band_energy(samples, freq)

        # Step 3: SNR check — signal energy relative to noise floor
        noise_db = 10.0 * np.log10(self._noise_floor + 1e-10)
        snr = power_db - noise_db

        # Step 4: Species matching
        matches = get_species_match(freq)

        # Step 5: Compute overall confidence
        # Factors: periodicity strength, SNR, band energy above noise
        periodicity_factor = min(1.0, periodicity / 0.5)  # saturate at 0.5
        snr_factor = min(1.0, max(0.0, snr / 20.0))  # 0-1 over 0-20 dB
        confidence = periodicity_factor * snr_factor

        # Store results
        self._detected_freq = freq
        self._periodicity = periodicity
        self._confidence = confidence
        self._band_energy_db = band_energy_db

        if matches and confidence >= self.min_confidence:
            self._species = matches[0][0]
            self._species_score = matches[0][1] * confidence
        else:
            self._species = f"Unknown ({freq:.0f} Hz)" if confidence >= self.min_confidence else ""
            self._species_score = 0.0

    def reset(self):
        self._buffer_pos = 0
        self._blocks_accumulated = 0
        self._detected_freq = 0.0
        self._periodicity = 0.0
        self._confidence = 0.0
        self._species = ""
        self._species_score = 0.0
        self._band_energy_db = -100.0
        self._noise_floor = 1e-6
        self._bp_state[:] = 0

    def get_status(self) -> dict:
        return {
            "enabled": self.enabled,
            "species": self._species,
            "species_score": f"{self._species_score:.2f}",
            "frequency_hz": f"{self._detected_freq:.1f}",
            "periodicity": f"{self._periodicity:.3f}",
            "confidence": f"{self._confidence:.3f}",
            "band_energy_db": f"{self._band_energy_db:.1f}",
            "noise_floor_db": f"{10*np.log10(self._noise_floor+1e-10):.1f}",
        }


# ─── Main ──────────────────────────────────────────────────────────────────────

def main() -> int:
    parser = argparse.ArgumentParser(
        description="Classify flying insects by wing-beat frequency. "
                    "Detects periodic energy in species-specific frequency bands "
                    "using autocorrelation and Goertzel filters.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""\
examples:
  %(prog)s --test                     Run with synthetic wing-beat signals
  %(prog)s --test --test-duration 10  Longer test run
  %(prog)s --list-devices             List audio devices
  %(prog)s --input-device 3           Use specific microphone
  %(prog)s --csv detections.csv       Log detections to CSV
  %(prog)s --min-confidence 0.5       Higher threshold (fewer false positives)
""")
    add_audio_args(parser, duplex=False)
    add_test_args(parser)
    parser.add_argument("--min-confidence", type=float, default=0.3, metavar="F",
                        help="Minimum confidence to report detection (0-1, default 0.3)")
    parser.add_argument("--noise-gate", type=float, default=-50.0, metavar="DB",
                        help="Noise gate threshold in dBFS (default -50)")
    parser.add_argument("--analysis-window", type=int, default=4, metavar="N",
                        help="Number of blocks to accumulate before analysis "
                             "(default 4, ~85 ms at 48 kHz/1024)")
    parser.add_argument("--csv", metavar="PATH",
                        help="Log detections to CSV file")
    parser.add_argument("--list-species", action="store_true",
                        help="Print insect database and exit")
    args = parser.parse_args()

    # --list-species
    if args.list_species:
        print(f"{'Species':<42} {'Freq range':>12}  Notes")
        print("-" * 80)
        for name, f_lo, f_hi, notes in sorted(INSECT_DB, key=lambda x: x[1]):
            print(f"{name:<42} {f_lo:>4}-{f_hi:<4} Hz  {notes}")
        return 0

    # --list-devices
    if args.list_devices:
        from dsp_pipeline.args import open_stream_from_args
        open_stream_from_args(args, duplex=False)
        return 0

    block = InsectClassifier(
        samplerate=args.samplerate,
        blocksize=args.blocksize,
        min_confidence=args.min_confidence,
        analysis_window=args.analysis_window,
        noise_gate_db=args.noise_gate,
    )
    pipeline = Pipeline([block], samplerate=args.samplerate, blocksize=args.blocksize)

    if args.test:
        return run_test_mode(args, block, pipeline)
    else:
        return run_realtime_mode(args, block, pipeline)


def run_test_mode(args, block: InsectClassifier, pipeline: Pipeline) -> int:
    """Run with synthetic wing-beat signals and validate detection."""
    ts = TestSignal(args.samplerate, args.test_duration)
    t = np.arange(int(args.samplerate * args.test_duration)) / args.samplerate

    # Generate test scenarios: one species at a time
    test_cases = [
        ("Honeybee (230 Hz)", 230.0, 0.15),
        ("Housefly (190 Hz)", 190.0, 0.12),
        ("Female Aedes mosquito (430 Hz)", 430.0, 0.08),
        ("Male Aedes mosquito (600 Hz)", 600.0, 0.06),
        ("Bumblebee (130 Hz)", 130.0, 0.20),
        ("Wasp (160 Hz)", 160.0, 0.10),
        ("Midge (500 Hz)", 500.0, 0.05),
    ]

    # Segment duration
    seg_duration = max(0.5, args.test_duration / (len(test_cases) + 1))
    seg_samples = int(seg_duration * args.samplerate)

    print("=" * 72)
    print("INSECT CLASSIFIER — TEST MODE")
    print("=" * 72)
    print(f"Sample rate: {args.samplerate} Hz")
    print(f"Block size: {args.blocksize}")
    print(f"Analysis window: {args.analysis_window} blocks "
          f"({args.analysis_window * args.blocksize / args.samplerate * 1000:.0f} ms)")
    print(f"Min confidence: {args.min_confidence}")
    print(f"Segment duration: {seg_duration:.2f} s")
    print()

    csv_file = None
    csv_writer = None
    if args.csv:
        csv_file = open(args.csv, "w", newline="")
        csv_writer = csv.writer(csv_file)
        csv_writer.writerow(["time_s", "test_case", "detected_species",
                             "detected_freq_hz", "confidence", "periodicity",
                             "correct"])

    results = []
    for i, (label, freq, amplitude) in enumerate(test_cases):
        # Generate wing-beat signal: periodic pulse train at the given frequency
        # Real wing beats are not pure sinusoids — they're more like pulse trains
        # with harmonics. Simulate with a clipped sine + harmonics.
        seg_t = np.arange(seg_samples) / args.samplerate
        # Fundamental + 2nd + 3rd harmonic (wing-beat spectrum)
        signal = (amplitude * np.sin(2 * np.pi * freq * seg_t)
                  + 0.5 * amplitude * np.sin(2 * np.pi * 2 * freq * seg_t)
                  + 0.25 * amplitude * np.sin(2 * np.pi * 3 * freq * seg_t))
        # Add amplitude modulation (wing-beat is rhythmic but not perfectly steady)
        am = 0.8 + 0.2 * np.sin(2 * np.pi * 3.0 * seg_t)
        signal = (signal * am).astype(np.float32)
        # Add noise
        rng = np.random.default_rng(42 + i)
        noise = 0.02 * rng.standard_normal(seg_samples).astype(np.float32)
        signal += noise

        # Reset block state between test cases
        block.reset()

        # Process through pipeline
        pipeline.process_array(signal.reshape(-1, 1))

        # Check result
        detected = block._species
        det_freq = block._detected_freq
        confidence = block._confidence
        periodicity = block._periodicity

        # Determine if detection is in the right frequency range
        matches = get_species_match(freq)
        expected_names = [m[0] for m in matches]
        correct = detected in expected_names if detected else False

        status_icon = "PASS" if correct else ("MISS" if not detected else "WRONG")
        results.append((label, correct, status_icon))

        print(f"[{status_icon:>5}] {label}")
        print(f"        Input: {freq:.0f} Hz, amplitude={amplitude:.3f}")
        if detected:
            print(f"        Detected: {detected}")
            print(f"        Frequency: {det_freq:.1f} Hz, "
                  f"confidence: {confidence:.3f}, "
                  f"periodicity: {periodicity:.3f}")
        else:
            print(f"        Detected: (nothing)")
        print()

        if csv_writer:
            csv_writer.writerow([
                f"{i * seg_duration:.2f}",
                label,
                detected or "(none)",
                f"{det_freq:.1f}",
                f"{confidence:.3f}",
                f"{periodicity:.3f}",
                "yes" if correct else "no",
            ])

    # Summary
    n_pass = sum(1 for _, correct, _ in results if correct)
    n_total = len(results)
    print("-" * 72)
    print(f"Results: {n_pass}/{n_total} correctly classified")
    if n_pass == n_total:
        print("All test cases passed.")
    else:
        print("Failed cases:")
        for label, correct, status in results:
            if not correct:
                print(f"  - {label} [{status}]")

    # Additional test: silence should produce no detection
    print()
    print("Silence test:")
    block.reset()
    silence = np.zeros(seg_samples, dtype=np.float32)
    pipeline.process_array(silence.reshape(-1, 1))
    if block._species:
        print(f"  [FAIL] Detected '{block._species}' in silence")
    else:
        print("  [PASS] No false detection in silence")
        n_pass += 1
    n_total += 1

    # Noise-only test
    print()
    print("Noise-only test:")
    block.reset()
    noise_only = 0.05 * np.random.default_rng(99).standard_normal(seg_samples).astype(np.float32)
    pipeline.process_array(noise_only.reshape(-1, 1))
    if block._species and "Unknown" not in block._species:
        print(f"  [FAIL] False detection: '{block._species}' "
              f"(conf={block._confidence:.3f})")
    else:
        print("  [PASS] No false species classification in noise")
        n_pass += 1
    n_total += 1

    print()
    print(f"Final: {n_pass}/{n_total} passed")

    if csv_file:
        csv_file.close()
        print(f"\nWrote {args.csv}")

    return 0 if n_pass >= n_total - 1 else 1


def run_realtime_mode(args, block: InsectClassifier, pipeline: Pipeline) -> int:
    """Run in real-time from microphone input."""
    from dsp_pipeline.stream import AudioStream

    stream = AudioStream(
        input_device=args.input_device,
        samplerate=args.samplerate,
        blocksize=args.blocksize,
        channels_in=args.channels_in,
    )

    csv_file = None
    csv_writer = None
    if args.csv:
        csv_file = open(args.csv, "w", newline="")
        csv_writer = csv.writer(csv_file)
        csv_writer.writerow(["timestamp", "species", "frequency_hz", "confidence",
                             "periodicity", "band_energy_db"])

    last_species = ""

    def callback(indata, frames):
        nonlocal last_species
        block.process(indata)
        # Log new detections to CSV
        if csv_writer and block._species and block._species != last_species:
            csv_writer.writerow([
                datetime.now().isoformat(timespec="milliseconds"),
                block._species,
                f"{block._detected_freq:.1f}",
                f"{block._confidence:.3f}",
                f"{block._periodicity:.3f}",
                f"{block._band_energy_db:.1f}",
            ])
        last_species = block._species
        return None

    stream.set_callback(callback)
    stop = [False]

    def handler(signum, frame):
        stop[0] = True
    old_handler = signal.signal(signal.SIGINT, handler)

    try:
        stream.start()
        print("Insect classifier running. Listening...", file=sys.stderr)
        print(f"  Min confidence: {args.min_confidence}", file=sys.stderr)
        print(f"  Analysis window: {args.analysis_window} blocks "
              f"({args.analysis_window * args.blocksize / args.samplerate * 1000:.0f} ms)",
              file=sys.stderr)
        print("  Ctrl-C to stop.", file=sys.stderr)
        print(file=sys.stderr)

        while not stop[0]:
            time.sleep(0.2)
            status = block.get_status()

            if block._species:
                species = block._species
                freq = block._detected_freq
                conf = block._confidence
                score = block._species_score
                line = (f"  {species:<42} "
                        f"{freq:>6.1f} Hz  "
                        f"conf={conf:.2f}  "
                        f"score={score:.2f}")
            else:
                nf = float(status["noise_floor_db"])
                line = f"  (listening)  noise_floor={nf:.0f} dBFS"

            print(f"\r{line:<78}", end="", flush=True)

    finally:
        stream.stop()
        signal.signal(signal.SIGINT, old_handler)
        if csv_file:
            csv_file.close()
            print(f"\n\nWrote {args.csv}")
        print()

    return 0


if __name__ == "__main__":
    sys.exit(main())
