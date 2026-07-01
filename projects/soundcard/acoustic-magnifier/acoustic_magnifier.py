#!/usr/bin/env python3
"""
acoustic_magnifier.py — Acoustic magnifying glass.

Extreme narrowband gain: pick a 50 Hz-wide band anywhere in the
spectrum, amplify it 40-60 dB, suppress everything else. Sweep it
around like tuning a radio.

At 120 Hz you hear every transformer on the block. At 4 kHz you
isolate individual cricket species. At 800 Hz you pick out one
conversation across a crowded room.
"""

from __future__ import annotations

import argparse
import signal
import sys
import time
import threading
from pathlib import Path

import numpy as np
from scipy.signal import butter, sosfilt, iirpeak

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from dsp_pipeline import DSPBlock, Pipeline, TestSignal, add_audio_args, add_test_args


class AcousticMagnifier(DSPBlock):
    """Extreme narrowband bandpass with configurable center and bandwidth."""

    def __init__(self, samplerate: int = 48000, blocksize: int = 1024,
                 center_freq: float = 1000.0, bandwidth: float = 50.0,
                 gain_db: float = 40.0, suppress_db: float = -40.0):
        super().__init__(samplerate, blocksize)
        self.center_freq = center_freq
        self.bandwidth = bandwidth
        self.gain_db = gain_db
        self.suppress_db = suppress_db
        self._design_filter()
        self.output_level_db = -100.0

    def _design_filter(self):
        """Design a very narrow bandpass filter."""
        nyquist = self.samplerate / 2.0
        center = min(self.center_freq, nyquist * 0.95)
        bw = max(self.bandwidth, 10.0)

        # Q = center / bandwidth
        Q = center / bw

        # use iirpeak for the resonator (2nd order, very sharp)
        # cascade two for sharper rolloff
        b1, a1 = iirpeak(center / nyquist, Q)
        b2, a2 = iirpeak(center / nyquist, Q * 0.8)

        # convert to sos for numerical stability
        from scipy.signal import tf2sos
        sos1 = tf2sos(b1, a1)
        sos2 = tf2sos(b2, a2)
        self._sos = np.vstack([sos1, sos2])
        self._state = np.zeros((self._sos.shape[0], 2))

        # gain factor
        self._gain_linear = 10 ** (self.gain_db / 20.0)

    def set_center_freq(self, freq: float):
        """Retune the center frequency."""
        self.center_freq = max(20.0, min(freq, self.samplerate / 2 * 0.95))
        self._design_filter()

    def set_bandwidth(self, bw: float):
        """Change bandwidth."""
        self.bandwidth = max(10.0, min(bw, 2000.0))
        self._design_filter()

    def process(self, samples: np.ndarray) -> np.ndarray:
        mono = samples[:, 0] if samples.ndim == 2 else samples

        # apply narrow bandpass
        filtered, self._state = sosfilt(self._sos, mono, zi=self._state)
        filtered = filtered.astype(np.float32)

        # apply gain
        output = filtered * self._gain_linear

        # soft clip to prevent extreme peaks
        output = np.tanh(output * 0.5) * 2.0

        # measure output level
        rms = np.sqrt(np.mean(output ** 2))
        self.output_level_db = 20 * np.log10(rms + 1e-10)

        if samples.ndim == 2:
            out = np.zeros_like(samples)
            out[:, 0] = output
            if samples.shape[1] > 1:
                out[:, 1] = output
            return out
        return output

    def reset(self):
        self._state = np.zeros((self._sos.shape[0], 2))

    def get_status(self) -> dict:
        return {
            "center_freq_hz": self.center_freq,
            "bandwidth_hz": self.bandwidth,
            "gain_db": self.gain_db,
            "output_level_db": self.output_level_db,
        }


class SweepController:
    """Automatic frequency sweep for scanning mode."""

    def __init__(self, start_freq: float, end_freq: float,
                 sweep_time: float, samplerate: int, blocksize: int):
        self.start_freq = start_freq
        self.end_freq = end_freq
        self.sweep_time = sweep_time
        self.position = 0.0  # 0 to 1
        self.blocks_per_sweep = int(sweep_time * samplerate / blocksize)
        self.block_count = 0
        self.direction = 1  # 1 = forward, -1 = reverse
        self.paused = False

    def advance(self) -> float:
        """Advance one block and return current frequency."""
        if self.paused:
            return self.get_freq()

        self.block_count += 1
        self.position = (self.block_count % self.blocks_per_sweep) / self.blocks_per_sweep
        if (self.block_count // self.blocks_per_sweep) % 2 == 1:
            # reverse direction on even sweeps
            self.position = 1.0 - self.position
        return self.get_freq()

    def get_freq(self) -> float:
        """Get current frequency (log interpolation)."""
        log_start = np.log2(self.start_freq)
        log_end = np.log2(self.end_freq)
        log_freq = log_start + self.position * (log_end - log_start)
        return 2.0 ** log_freq


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Acoustic magnifying glass — extreme narrowband gain, "
        "sweep like tuning a radio.")
    add_audio_args(parser)
    add_test_args(parser)
    parser.add_argument("--center", type=float, default=1000.0,
                        help="Center frequency in Hz (default: 1000)")
    parser.add_argument("--bandwidth", type=float, default=50.0,
                        help="Bandwidth in Hz (default: 50)")
    parser.add_argument("--gain", type=float, default=40.0,
                        help="Gain in dB (default: 40)")
    parser.add_argument("--sweep", action="store_true",
                        help="Enable automatic frequency sweep")
    parser.add_argument("--sweep-start", type=float, default=100.0,
                        help="Sweep start frequency (default: 100 Hz)")
    parser.add_argument("--sweep-end", type=float, default=8000.0,
                        help="Sweep end frequency (default: 8000 Hz)")
    parser.add_argument("--sweep-time", type=float, default=10.0,
                        help="Sweep duration in seconds (default: 10)")
    args = parser.parse_args()

    if args.list_devices:
        from dsp_pipeline.args import open_stream_from_args
        open_stream_from_args(args)
        return 0

    samplerate = args.samplerate
    blocksize = args.blocksize

    magnifier = AcousticMagnifier(
        samplerate=samplerate,
        blocksize=blocksize,
        center_freq=args.center,
        bandwidth=args.bandwidth,
        gain_db=args.gain,
    )

    sweeper = None
    if args.sweep:
        sweeper = SweepController(
            start_freq=args.sweep_start,
            end_freq=args.sweep_end,
            sweep_time=args.sweep_time,
            samplerate=samplerate,
            blocksize=blocksize,
        )

    if args.test:
        ts = TestSignal(samplerate, args.test_duration)
        n_samples = ts.n_samples
        t = np.arange(n_samples) / samplerate

        # test: multiple tones at different frequencies + noise
        test_audio = np.zeros(n_samples, dtype=np.float32)
        # weak 800 Hz tone (simulating distant speaker)
        test_audio += 0.001 * np.sin(2 * np.pi * 800 * t).astype(np.float32)
        # medium 2000 Hz tone (cricket)
        test_audio += 0.005 * np.sin(2 * np.pi * 2000 * t).astype(np.float32)
        # strong 60 Hz hum
        test_audio += 0.02 * np.sin(2 * np.pi * 60 * t).astype(np.float32)
        # broadband noise
        test_audio += np.random.randn(n_samples).astype(np.float32) * 0.01

        print(f"Test mode: multiple tones buried in noise")
        print(f"  60 Hz hum at -34 dBFS")
        print(f"  800 Hz tone at -60 dBFS")
        print(f"  2000 Hz tone at -46 dBFS")
        print(f"  Noise floor at -40 dBFS")
        print(f"\nMagnifying at {args.center} Hz, BW={args.bandwidth} Hz, "
              f"Gain={args.gain} dB")
        print()

        # process
        pipeline = Pipeline([magnifier], samplerate=samplerate, blocksize=blocksize)
        output = pipeline.process_array(test_audio.reshape(-1, 1))
        output_mono = output[:, 0] if output.ndim == 2 else output

        # measure what we got
        out_rms = np.sqrt(np.mean(output_mono ** 2))
        print(f"Output RMS: {20 * np.log10(out_rms + 1e-10):.1f} dBFS")

        # verify the magnified frequency dominates
        spectrum = np.abs(np.fft.rfft(output_mono))
        freqs = np.fft.rfftfreq(len(output_mono), 1.0 / samplerate)
        peak_freq = freqs[np.argmax(spectrum[1:]) + 1]
        print(f"Dominant output freq: {peak_freq:.0f} Hz")

        if abs(peak_freq - args.center) < args.bandwidth:
            print(f"\nSuccess: {args.center} Hz signal isolated and amplified.")
        else:
            print(f"\nNote: dominant frequency ({peak_freq:.0f} Hz) differs from "
                  f"center ({args.center:.0f} Hz).")
    else:
        from dsp_pipeline.stream import AudioStream

        stream = AudioStream(
            input_device=args.input_device,
            output_device=args.output_device,
            samplerate=samplerate,
            blocksize=blocksize,
            channels_in=1,
            channels_out=2,
        )

        def callback(indata, frames):
            if sweeper:
                freq = sweeper.advance()
                magnifier.set_center_freq(freq)
            processed = magnifier.process(indata)
            return processed

        stream.set_callback(callback)
        stop = [False]

        def handler(s, f):
            stop[0] = True
        old_handler = signal.signal(signal.SIGINT, handler)

        try:
            stream.start()
            print(f"Acoustic magnifier running", file=sys.stderr)
            if sweeper:
                print(f"  Sweeping {args.sweep_start}–{args.sweep_end} Hz "
                      f"in {args.sweep_time}s", file=sys.stderr)
            else:
                print(f"  Fixed at {args.center} Hz, BW={args.bandwidth} Hz",
                      file=sys.stderr)
            print(f"  Gain: {args.gain} dB", file=sys.stderr)
            print("  Ctrl-C to stop", file=sys.stderr)
            print()

            while not stop[0]:
                time.sleep(0.2)
                status = magnifier.get_status()
                freq = status["center_freq_hz"]
                level = status["output_level_db"]
                bar_len = max(0, int((level + 60) / 1.5))
                bar = "█" * min(bar_len, 40)
                print(f"\r  {freq:>7.0f} Hz | {level:>6.1f} dB | {bar:<40}",
                      end="", flush=True)
        finally:
            stream.stop()
            signal.signal(signal.SIGINT, old_handler)
            print()

    return 0


if __name__ == "__main__":
    sys.exit(main())
