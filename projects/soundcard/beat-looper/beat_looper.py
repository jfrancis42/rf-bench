#!/usr/bin/env python3
"""
beat_looper.py — Ambient beat looper.

Detects percussive transients in ambient audio (tapping, knocking,
clapping, footsteps), quantizes them to a tempo grid, and builds
generative rhythm loops. The environment becomes a drum machine.

Works by:
1. Onset detection (energy flux in multiple frequency bands)
2. Tempo estimation (autocorrelation of onset function)
3. Beat quantization (snap onsets to nearest grid position)
4. Loop assembly (layer captured transients into a rhythmic pattern)
5. Playback (loop the assembled pattern continuously)
"""

from __future__ import annotations

import argparse
import signal
import sys
import time
from collections import deque
from pathlib import Path

import numpy as np
from scipy.signal import butter, sosfilt

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from dsp_pipeline import DSPBlock, Pipeline, TestSignal, add_audio_args, add_test_args


class OnsetDetector:
    """Detects percussive onsets using spectral flux."""

    def __init__(self, samplerate: int, hop_size: int = 512,
                 fft_size: int = 1024, threshold_db: float = -25.0):
        self.samplerate = samplerate
        self.hop_size = hop_size
        self.fft_size = fft_size
        self.threshold_ratio = 3.0  # onset must be N× the background level

        self._prev_spectrum = np.zeros(fft_size // 2 + 1, dtype=np.float32)
        self._onset_strength = 0.0
        self._window = np.hanning(fft_size).astype(np.float32)

        # adaptive threshold: track background flux level
        self._history = deque(maxlen=200)
        self._cooldown = 0
        self._cooldown_frames = int(0.08 * samplerate / hop_size)

    def process_frame(self, frame: np.ndarray) -> tuple[bool, float]:
        """Process one hop of audio. Returns (is_onset, strength)."""
        if len(frame) < self.fft_size:
            padded = np.zeros(self.fft_size, dtype=np.float32)
            padded[:len(frame)] = frame
            frame = padded

        windowed = frame[:self.fft_size] * self._window
        spectrum = np.abs(np.fft.rfft(windowed))

        # spectral flux: sum of positive differences (new energy only)
        diff = spectrum - self._prev_spectrum
        flux = np.sum(np.maximum(0, diff))
        self._prev_spectrum = spectrum.copy()

        # normalize by FFT size
        flux /= self.fft_size

        self._onset_strength = flux
        self._history.append(flux)

        # adaptive threshold: percentile-based background estimate
        # only consider non-onset frames for background level
        if len(self._history) > 10:
            hist = np.array(self._history)
            # use 75th percentile as background (ignores onset spikes)
            background = np.percentile(hist, 75)
            adaptive_thresh = background * self.threshold_ratio
        else:
            # during startup, use a fixed low threshold
            adaptive_thresh = 0.001

        # cooldown prevents multiple triggers from single hit
        if self._cooldown > 0:
            self._cooldown -= 1
            return False, flux

        is_onset = flux > adaptive_thresh and flux > 0.001
        if is_onset:
            self._cooldown = self._cooldown_frames

        return is_onset, flux


class TempoEstimator:
    """Estimates tempo from onset timing patterns."""

    def __init__(self, samplerate: int, min_bpm: float = 60.0,
                 max_bpm: float = 200.0):
        self.samplerate = samplerate
        self.min_bpm = min_bpm
        self.max_bpm = max_bpm
        self._onset_times: list[float] = []
        self._tempo_bpm = 120.0
        self._confidence = 0.0

    def add_onset(self, time_sec: float):
        self._onset_times.append(time_sec)
        # keep last 30 seconds
        cutoff = time_sec - 30.0
        self._onset_times = [t for t in self._onset_times if t > cutoff]
        self._estimate()

    def _estimate(self):
        if len(self._onset_times) < 4:
            return

        # compute IOIs (Inter-Onset Intervals)
        iois = np.diff(self._onset_times)
        iois = iois[(iois > 60.0 / self.max_bpm) &
                    (iois < 60.0 / self.min_bpm)]

        if len(iois) < 3:
            return

        # cluster IOIs around the most common interval
        # use histogram approach
        min_ioi = 60.0 / self.max_bpm
        max_ioi = 60.0 / self.min_bpm
        n_bins = 100
        hist, bin_edges = np.histogram(iois, bins=n_bins,
                                        range=(min_ioi, max_ioi))

        peak_bin = np.argmax(hist)
        if hist[peak_bin] < 2:
            return

        best_ioi = (bin_edges[peak_bin] + bin_edges[peak_bin + 1]) / 2

        # also check half and double (handle ambiguity)
        half_ioi = best_ioi / 2
        double_ioi = best_ioi * 2

        # pick whichever has most IOIs nearby
        counts = []
        for candidate in [half_ioi, best_ioi, double_ioi]:
            if min_ioi <= candidate <= max_ioi:
                nearby = np.sum(np.abs(iois - candidate) < candidate * 0.15)
                counts.append((nearby, candidate))

        if counts:
            best_count, best_ioi = max(counts)
            self._tempo_bpm = 60.0 / best_ioi
            self._confidence = min(1.0, best_count / len(iois))

    @property
    def bpm(self) -> float:
        return self._tempo_bpm

    @property
    def confidence(self) -> float:
        return self._confidence

    @property
    def beat_period_samples(self) -> int:
        return int(60.0 / self._tempo_bpm * self.samplerate)


class BeatLooper(DSPBlock):
    """Captures transients, quantizes to grid, loops rhythmically."""

    def __init__(self, samplerate: int = 48000, blocksize: int = 1024,
                 bpm: float = 0, beats_per_loop: int = 8,
                 threshold_db: float = -25.0, quantize: float = 0.5,
                 decay: float = 0.95):
        super().__init__(samplerate, blocksize)
        self.beats_per_loop = beats_per_loop
        self.quantize_strength = quantize
        self.decay = decay

        # onset detection
        self._detector = OnsetDetector(samplerate, threshold_db=threshold_db)
        self._tempo = TempoEstimator(samplerate)
        self._fixed_bpm = bpm

        # capture buffer for transients (~100 ms max)
        self._capture_len = int(0.1 * samplerate)
        self._capturing = False
        self._capture_buf = np.zeros(self._capture_len, dtype=np.float32)
        self._capture_pos = 0

        # loop buffer
        self._update_loop_buffer()
        self._loop_pos = 0
        self._sample_count = 0
        self._start_time = time.time()

        # statistics
        self.onset_count = 0
        self.loop_layers = 0

    def _update_loop_buffer(self):
        """Resize loop buffer to match current tempo."""
        bpm = self._fixed_bpm if self._fixed_bpm > 0 else self._tempo.bpm
        beat_samples = int(60.0 / bpm * self.samplerate)
        loop_len = beat_samples * self.beats_per_loop
        loop_len = max(loop_len, self.samplerate)  # minimum 1 second

        if not hasattr(self, '_loop_buffer') or len(self._loop_buffer) != loop_len:
            old = getattr(self, '_loop_buffer', None)
            self._loop_buffer = np.zeros(loop_len, dtype=np.float32)
            if old is not None and len(old) > 0:
                # preserve old content (stretch/compress to new length)
                indices = np.linspace(0, len(old) - 1, loop_len).astype(int)
                self._loop_buffer = old[indices]

    def _quantize_position(self, pos: int) -> int:
        """Snap position to nearest beat subdivision."""
        if self.quantize_strength == 0:
            return pos

        bpm = self._fixed_bpm if self._fixed_bpm > 0 else self._tempo.bpm
        beat_samples = int(60.0 / bpm * self.samplerate)
        # quantize to 16th notes (beat / 4)
        grid = beat_samples // 4
        if grid <= 0:
            return pos

        # find nearest grid position
        nearest = round(pos / grid) * grid
        # blend between actual and quantized
        return int(pos + self.quantize_strength * (nearest - pos))

    def _add_transient_to_loop(self, transient: np.ndarray, position: int):
        """Layer a captured transient into the loop at the given position."""
        loop_len = len(self._loop_buffer)
        pos = position % loop_len
        n = len(transient)

        # apply decay to existing content before adding
        self._loop_buffer *= self.decay

        # add transient with wrapping
        end = pos + n
        if end <= loop_len:
            self._loop_buffer[pos:end] += transient
        else:
            first = loop_len - pos
            self._loop_buffer[pos:] += transient[:first]
            self._loop_buffer[:end - loop_len] += transient[first:]

        self.loop_layers += 1

    def process(self, samples: np.ndarray) -> np.ndarray:
        mono = samples[:, 0] if samples.ndim == 2 else samples
        n = len(mono)

        # onset detection (process in hops)
        hop = 512
        for i in range(0, n - hop, hop):
            frame = mono[i:i + hop]
            is_onset, strength = self._detector.process_frame(frame)

            if is_onset and not self._capturing:
                self._capturing = True
                self._capture_pos = 0
                self._capture_buf[:] = 0
                self.onset_count += 1
                # register onset time for tempo estimation
                t = self._start_time + self._sample_count / self.samplerate
                self._tempo.add_onset(t)

            # capture transient
            if self._capturing:
                end = min(self._capture_pos + hop, self._capture_len)
                copy_len = end - self._capture_pos
                self._capture_buf[self._capture_pos:end] = frame[:copy_len]
                self._capture_pos = end

                if self._capture_pos >= self._capture_len:
                    self._capturing = False
                    # apply envelope (fast attack, medium decay)
                    env = np.exp(-np.arange(self._capture_len) /
                                  (self._capture_len * 0.3)).astype(np.float32)
                    transient = self._capture_buf * env

                    # quantize position within the loop
                    loop_pos = self._quantize_position(
                        self._loop_pos % len(self._loop_buffer))
                    self._add_transient_to_loop(transient, loop_pos)

                    # update tempo periodically
                    if not self._fixed_bpm:
                        self._update_loop_buffer()

        # generate output: mix input with loop playback
        output = np.zeros_like(mono)
        loop_len = len(self._loop_buffer)

        for i in range(n):
            pos = (self._loop_pos + i) % loop_len
            output[i] = mono[i] * 0.3 + self._loop_buffer[pos] * 0.7

        self._loop_pos = (self._loop_pos + n) % loop_len
        self._sample_count += n

        # format output
        if samples.ndim == 2:
            return output.reshape(-1, 1).astype(np.float32)
        return output.astype(np.float32)

    def get_status(self) -> dict:
        bpm = self._fixed_bpm if self._fixed_bpm > 0 else self._tempo.bpm
        return {
            "bpm": bpm,
            "tempo_confidence": self._tempo.confidence,
            "onset_count": self.onset_count,
            "loop_layers": self.loop_layers,
            "loop_position": self._loop_pos / len(self._loop_buffer),
            "capturing": self._capturing,
        }

    def reset(self):
        self._loop_buffer[:] = 0
        self._loop_pos = 0
        self.onset_count = 0
        self.loop_layers = 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Ambient beat looper — captures percussive transients, "
        "quantizes to a tempo grid, builds rhythm loops.")
    add_audio_args(parser)
    add_test_args(parser)
    parser.add_argument("--bpm", type=float, default=0,
                        help="Fixed BPM (0 = auto-detect from input, default: 0)")
    parser.add_argument("--beats", type=int, default=8,
                        help="Beats per loop (default: 8)")
    parser.add_argument("--threshold", type=float, default=-25.0,
                        help="Onset detection threshold in dBFS (default: -25)")
    parser.add_argument("--quantize", type=float, default=0.5,
                        help="Quantization strength 0-1 (default: 0.5)")
    parser.add_argument("--decay", type=float, default=0.95,
                        help="Loop decay per layer, 0-1 (default: 0.95)")
    args = parser.parse_args()

    if args.list_devices:
        from dsp_pipeline.args import open_stream_from_args
        open_stream_from_args(args)
        return 0

    samplerate = args.samplerate
    blocksize = args.blocksize

    looper = BeatLooper(
        samplerate=samplerate,
        blocksize=blocksize,
        bpm=args.bpm,
        beats_per_loop=args.beats,
        threshold_db=args.threshold,
        quantize=args.quantize,
        decay=args.decay,
    )

    pipeline = Pipeline([looper], samplerate=samplerate, blocksize=blocksize)

    if args.test:
        ts = TestSignal(samplerate, args.test_duration)
        n_samples = ts.n_samples
        t = np.arange(n_samples) / samplerate

        print("Test mode: simulated percussive input at 120 BPM\n")

        # generate 120 BPM clicks (on the beat) with some variation
        bpm = 120.0
        beat_interval = 60.0 / bpm
        test_audio = np.zeros(n_samples, dtype=np.float32)

        # add noise floor
        test_audio += np.random.randn(n_samples).astype(np.float32) * 0.001

        click_times = []
        beat_time = 0.1  # start slightly after beginning
        while beat_time < args.test_duration - 0.2:
            # add slight timing variation (humanize)
            actual_time = beat_time + np.random.uniform(-0.01, 0.01)
            sample_pos = int(actual_time * samplerate)
            if 0 <= sample_pos < n_samples - 200:
                # create a click (short noise burst, loud enough to trigger)
                click_len = np.random.randint(50, 150)
                click = np.random.randn(click_len).astype(np.float32)
                click *= np.exp(-np.arange(click_len) / 20.0)
                click *= 0.8
                test_audio[sample_pos:sample_pos + click_len] += click
                click_times.append(actual_time)
            beat_time += beat_interval

        # use fixed BPM for test
        looper._fixed_bpm = bpm

        # process
        output = pipeline.process_array(test_audio.reshape(-1, 1))

        status = looper.get_status()
        print(f"  Clicks generated:  {len(click_times)}")
        print(f"  Onsets detected:   {status['onset_count']}")
        print(f"  Loop layers:       {status['loop_layers']}")
        print(f"  BPM:               {status['bpm']:.1f}")
        print(f"  Output peak:       {np.max(np.abs(output)):.3f}")

        # verify loop has content (not silence)
        loop_energy = np.sqrt(np.mean(looper._loop_buffer ** 2))
        print(f"  Loop RMS:          {20 * np.log10(loop_energy + 1e-10):.1f} dB")

        # check that most onsets were detected
        detection_rate = status['onset_count'] / len(click_times) if click_times else 0
        print(f"  Detection rate:    {detection_rate:.0%}")

        if detection_rate > 0.5 and loop_energy > 0.001:
            print("\n  PASS: onsets detected and loop populated")
        else:
            print("\n  ISSUE: check threshold or signal level")
    else:
        from dsp_pipeline.stream import AudioStream

        stream = AudioStream(
            input_device=args.input_device,
            output_device=args.output_device,
            samplerate=samplerate,
            blocksize=blocksize,
            channels_in=1,
            channels_out=1,
        )

        def callback(indata, frames):
            return pipeline.process_block(indata)

        stream.set_callback(callback)
        stop = [False]

        def handler(s, f):
            stop[0] = True
        old_handler = signal.signal(signal.SIGINT, handler)

        try:
            stream.start()
            bpm_str = f"{args.bpm:.0f} BPM (fixed)" if args.bpm else "auto-detect"
            print(f"Beat looper running — {bpm_str}", file=sys.stderr)
            print(f"  {args.beats} beats/loop, quantize={args.quantize}",
                  file=sys.stderr)
            print("  Tap, clap, knock near the mic!", file=sys.stderr)
            print("  Ctrl-C to stop\n", file=sys.stderr)

            while not stop[0]:
                time.sleep(0.3)
                status = looper.get_status()
                bar_pos = int(status["loop_position"] * 16)
                bar = "█" * bar_pos + "░" * (16 - bar_pos)
                print(f"\r  [{bar}] {status['bpm']:>5.1f} BPM | "
                      f"Onsets: {status['onset_count']} | "
                      f"Layers: {status['loop_layers']}",
                      end="", flush=True)
        finally:
            stream.stop()
            signal.signal(signal.SIGINT, old_handler)
            print()

    return 0


if __name__ == "__main__":
    sys.exit(main())
