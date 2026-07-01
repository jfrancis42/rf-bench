#!/usr/bin/env python3
"""
doppler_speed.py — Acoustic Doppler speed measurement.

Measures the speed of passing vehicles (or any moving sound source) by
detecting the pitch shift between approach and departure. The Doppler
effect causes a passing sound to be higher-pitched approaching and
lower-pitched receding.

v = c × (f_approach - f_recede) / (f_approach + f_recede)

where c = speed of sound (~343 m/s at 20°C).
"""

from __future__ import annotations

import argparse
import signal
import sys
import time
from collections import deque
from pathlib import Path

import numpy as np
from scipy.signal import get_window, butter, sosfilt

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from dsp_pipeline import DSPBlock, Pipeline, TestSignal, add_audio_args, add_test_args


SPEED_OF_SOUND = 343.0  # m/s at 20°C


def detect_pitch_yin(samples: np.ndarray, samplerate: int,
                     min_freq: float = 50.0, max_freq: float = 2000.0,
                     threshold: float = 0.15) -> float:
    """Pitch detection using the YIN algorithm (simplified)."""
    n = len(samples)
    max_lag = min(int(samplerate / min_freq), n // 2)
    min_lag = max(int(samplerate / max_freq), 2)

    # difference function
    diff = np.zeros(max_lag)
    for lag in range(1, max_lag):
        diff[lag] = np.sum((samples[:n - max_lag] - samples[lag:lag + n - max_lag]) ** 2)

    # cumulative mean normalized difference
    cmndf = np.ones(max_lag)
    running_sum = 0.0
    for lag in range(1, max_lag):
        running_sum += diff[lag]
        if running_sum > 0:
            cmndf[lag] = diff[lag] * lag / running_sum
        else:
            cmndf[lag] = 1.0

    # find first dip below threshold in valid range
    for lag in range(min_lag, max_lag - 1):
        if cmndf[lag] < threshold:
            # parabolic interpolation
            if lag > 0 and lag < max_lag - 1:
                alpha = cmndf[lag - 1]
                beta = cmndf[lag]
                gamma = cmndf[lag + 1]
                denom = alpha - 2 * beta + gamma
                if abs(denom) > 1e-10:
                    correction = 0.5 * (alpha - gamma) / denom
                    lag = lag + correction
            return samplerate / lag

    return 0.0


class DopplerAnalyzer(DSPBlock):
    """Detects Doppler shift from passing sound sources."""

    def __init__(self, samplerate: int = 48000, blocksize: int = 1024,
                 analysis_window_ms: float = 100.0,
                 min_level_db: float = -40.0,
                 pitch_smoothing: float = 0.7):
        super().__init__(samplerate, blocksize)
        self.analysis_window = int(analysis_window_ms * samplerate / 1000)
        self.min_level = 10 ** (min_level_db / 20.0)
        self._min_level_db = min_level_db
        self.pitch_smoothing = pitch_smoothing

        self._buffer = np.zeros(0, dtype=np.float32)
        self._pitch_history = deque(maxlen=200)  # ~20 seconds at 10 Hz
        self._level_history = deque(maxlen=200)
        self._current_pitch = 0.0
        self._smoothed_pitch = 0.0

        # event detection state
        self._state = "idle"  # idle, approaching, receding, done
        self._approach_pitches: list[float] = []
        self._recede_pitches: list[float] = []
        self._peak_level = -100.0
        self._events: list[dict] = []

    def process(self, samples: np.ndarray) -> np.ndarray:
        mono = samples[:, 0] if samples.ndim == 2 else samples
        self._buffer = np.concatenate([self._buffer, mono])

        while len(self._buffer) >= self.analysis_window:
            chunk = self._buffer[:self.analysis_window]
            self._buffer = self._buffer[self.analysis_window // 2:]  # 50% overlap

            # level check
            rms = np.sqrt(np.mean(chunk ** 2))
            level_db = 20 * np.log10(rms + 1e-10)
            self._level_history.append(level_db)

            if rms < self.min_level:
                self._current_pitch = 0.0
                self._pitch_history.append(0.0)
                self._update_state(0.0, level_db)
                continue

            # pitch detection
            pitch = detect_pitch_yin(chunk, self.samplerate)
            if pitch > 0:
                self._smoothed_pitch = (self.pitch_smoothing * self._smoothed_pitch +
                                        (1 - self.pitch_smoothing) * pitch)
                self._current_pitch = self._smoothed_pitch
            else:
                self._current_pitch = 0.0

            self._pitch_history.append(self._current_pitch)
            self._update_state(self._current_pitch, level_db)

        return samples

    def _update_state(self, pitch: float, level_db: float):
        """State machine for detecting approach→pass→recede events."""
        if self._state == "idle":
            if pitch > 0 and level_db > self._min_level_db:
                self._state = "approaching"
                self._approach_pitches = [pitch]
                self._peak_level = level_db
        elif self._state == "approaching":
            if pitch > 0 and level_db > self._min_level_db:
                self._approach_pitches.append(pitch)
                self._peak_level = max(self._peak_level, level_db)
                # detect the transition: level starts dropping AND pitch drops
                if (len(self._approach_pitches) > 3 and
                        level_db < self._peak_level - 3):
                    self._state = "receding"
                    self._recede_pitches = [pitch]
            else:
                # lost signal before pass
                if len(self._approach_pitches) > 3:
                    self._state = "receding"
                    self._recede_pitches = self._approach_pitches[-2:]
                else:
                    self._state = "idle"
                    self._approach_pitches = []
        elif self._state == "receding":
            if pitch > 0 and level_db > self._min_level_db:
                self._recede_pitches.append(pitch)
            else:
                # event complete
                self._finish_event()
                self._state = "idle"
            # timeout: if receding for too long, finish
            if len(self._recede_pitches) > 50:
                self._finish_event()
                self._state = "idle"

    def _finish_event(self):
        """Calculate speed from approach/recede pitch data."""
        if len(self._approach_pitches) < 3 or len(self._recede_pitches) < 3:
            return

        # use median from stable portions:
        # first third of approach (strongest Doppler up-shift, before smoothing converges)
        # last third of recede (strongest Doppler down-shift, after smoothing settles)
        n_app = max(3, len(self._approach_pitches) // 3)
        n_rec = max(3, len(self._recede_pitches) // 3)
        f_approach = np.median(self._approach_pitches[:n_app])
        f_recede = np.median(self._recede_pitches[-n_rec:])

        if f_approach <= 0 or f_recede <= 0:
            return
        if f_approach <= f_recede:
            return  # no Doppler detected

        # Doppler formula
        speed_ms = SPEED_OF_SOUND * (f_approach - f_recede) / (f_approach + f_recede)
        speed_kmh = speed_ms * 3.6
        speed_mph = speed_ms * 2.237

        event = {
            "timestamp": time.time(),
            "f_approach_hz": float(f_approach),
            "f_recede_hz": float(f_recede),
            "speed_ms": float(speed_ms),
            "speed_kmh": float(speed_kmh),
            "speed_mph": float(speed_mph),
            "peak_level_db": float(self._peak_level),
            "shift_semitones": float(12 * np.log2(f_approach / f_recede)),
        }
        self._events.append(event)

    def get_events(self) -> list[dict]:
        return self._events.copy()

    def get_latest_event(self) -> dict | None:
        return self._events[-1] if self._events else None

    def get_status(self) -> dict:
        return {
            "state": self._state,
            "current_pitch_hz": self._current_pitch,
            "n_events": len(self._events),
            "latest_speed_kmh": self._events[-1]["speed_kmh"] if self._events else 0.0,
        }

    def reset(self):
        self._buffer = np.zeros(0, dtype=np.float32)
        self._pitch_history.clear()
        self._level_history.clear()
        self._current_pitch = 0.0
        self._smoothed_pitch = 0.0
        self._state = "idle"
        self._approach_pitches = []
        self._recede_pitches = []
        self._events = []


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Acoustic Doppler speed measurement — estimate speed "
        "of passing vehicles from pitch shift.")
    add_audio_args(parser)
    add_test_args(parser)
    parser.add_argument("--min-level", type=float, default=-40.0,
                        help="Minimum level to attempt pitch detection (default: -40 dBFS)")
    parser.add_argument("--window-ms", type=float, default=100.0,
                        help="Analysis window in ms (default: 100)")
    parser.add_argument("--smoothing", type=float, default=0.7,
                        help="Pitch smoothing factor 0-1 (default: 0.7)")
    parser.add_argument("--csv", metavar="FILE",
                        help="Log events to CSV")
    args = parser.parse_args()

    if args.list_devices:
        from dsp_pipeline.args import open_stream_from_args
        open_stream_from_args(args)
        return 0

    samplerate = args.samplerate
    blocksize = args.blocksize

    analyzer = DopplerAnalyzer(
        samplerate=samplerate,
        blocksize=blocksize,
        analysis_window_ms=args.window_ms,
        min_level_db=args.min_level,
        pitch_smoothing=args.smoothing,
    )

    if args.test:
        ts = TestSignal(samplerate, args.test_duration)
        n_samples = ts.n_samples
        t = np.arange(n_samples) / samplerate

        # simulate a passing vehicle with Doppler shift
        # vehicle speed: 50 km/h = 13.9 m/s
        vehicle_speed = 13.9  # m/s
        base_freq = 200.0  # engine harmonic

        # model: vehicle passes closest at t=2.5s, distance 10m
        closest_time = args.test_duration / 2
        min_distance = 10.0

        test_audio = np.zeros(n_samples, dtype=np.float32)
        cum_phase = 0.0
        for i in range(n_samples):
            # position along road relative to closest point
            x = vehicle_speed * (t[i] - closest_time)
            distance = np.sqrt(x ** 2 + min_distance ** 2)
            # radial velocity (positive = approaching)
            v_radial = -vehicle_speed * x / distance
            # Doppler-shifted frequency
            f_doppler = base_freq * (SPEED_OF_SOUND + v_radial) / SPEED_OF_SOUND
            # cumulative phase for correct instantaneous frequency
            cum_phase += 2 * np.pi * f_doppler / samplerate
            # amplitude decreases with distance (1/r), louder overall
            amplitude = min(0.8, 5.0 / distance)
            # generate with cumulative phase
            test_audio[i] = amplitude * np.sin(cum_phase)
            # add harmonics
            test_audio[i] += 0.3 * amplitude * np.sin(2 * cum_phase)
            test_audio[i] += 0.15 * amplitude * np.sin(3 * cum_phase)

        # add noise
        test_audio += np.random.randn(n_samples).astype(np.float32) * 0.005

        print(f"Test mode: simulated vehicle passing at {vehicle_speed * 3.6:.0f} km/h")
        print(f"  Base frequency: {base_freq} Hz")
        print(f"  Expected shift: {base_freq * vehicle_speed / SPEED_OF_SOUND:.1f} Hz")
        print()

        # process
        pipeline = Pipeline([analyzer], samplerate=samplerate, blocksize=blocksize)
        pipeline.process_array(test_audio.reshape(-1, 1))

        # flush any pending event (signal may not drop below threshold by EOF)
        if analyzer._state == "receding" and len(analyzer._recede_pitches) >= 3:
            analyzer._finish_event()
            analyzer._state = "idle"

        events = analyzer.get_events()
        if events:
            for event in events:
                print(f"  Detected pass:")
                print(f"    Approach freq: {event['f_approach_hz']:.1f} Hz")
                print(f"    Recede freq:   {event['f_recede_hz']:.1f} Hz")
                print(f"    Shift:         {event['shift_semitones']:.2f} semitones")
                print(f"    Speed:         {event['speed_kmh']:.1f} km/h "
                      f"({event['speed_mph']:.1f} mph)")
                print(f"    Actual:        {vehicle_speed * 3.6:.1f} km/h")
                error = abs(event['speed_kmh'] - vehicle_speed * 3.6)
                print(f"    Error:         {error:.1f} km/h")
        else:
            print("  No events detected (try adjusting --min-level or --smoothing)")
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
            csv_file.write("timestamp,f_approach_hz,f_recede_hz,speed_kmh,speed_mph,shift_semitones\n")

        last_event_count = 0

        def callback(indata, frames):
            nonlocal last_event_count
            analyzer.process(indata)
            events = analyzer.get_events()
            if len(events) > last_event_count:
                for event in events[last_event_count:]:
                    print(f"\n  PASS DETECTED: {event['speed_kmh']:.0f} km/h "
                          f"({event['speed_mph']:.0f} mph) | "
                          f"{event['f_approach_hz']:.0f}→{event['f_recede_hz']:.0f} Hz",
                          flush=True)
                    if csv_file:
                        csv_file.write(f"{event['timestamp']:.3f},"
                                       f"{event['f_approach_hz']:.1f},"
                                       f"{event['f_recede_hz']:.1f},"
                                       f"{event['speed_kmh']:.1f},"
                                       f"{event['speed_mph']:.1f},"
                                       f"{event['shift_semitones']:.2f}\n")
                        csv_file.flush()
                last_event_count = len(events)
            return None

        stream.set_callback(callback)
        stop = [False]

        def handler(s, f):
            stop[0] = True
        old_handler = signal.signal(signal.SIGINT, handler)

        try:
            stream.start()
            print(f"Doppler speed gun running", file=sys.stderr)
            print(f"  Min level: {args.min_level} dBFS", file=sys.stderr)
            print("  Point mic at passing traffic", file=sys.stderr)
            print("  Ctrl-C to stop", file=sys.stderr)
            print()

            while not stop[0]:
                time.sleep(0.3)
                status = analyzer.get_status()
                pitch = status["current_pitch_hz"]
                state = status["state"]
                if pitch > 0:
                    print(f"\r  [{state:>11}] Pitch: {pitch:>7.1f} Hz | "
                          f"Events: {status['n_events']}", end="", flush=True)
                else:
                    print(f"\r  [{state:>11}] — listening — | "
                          f"Events: {status['n_events']}", end="", flush=True)
        finally:
            stream.stop()
            signal.signal(signal.SIGINT, old_handler)
            if csv_file:
                csv_file.close()
            print(f"\n\nTotal passes detected: {len(analyzer.get_events())}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
