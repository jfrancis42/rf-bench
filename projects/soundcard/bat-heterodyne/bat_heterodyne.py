#!/usr/bin/env python3
"""
bat_heterodyne.py — Ultrasonic heterodyne detector.

Shifts audio above a configurable threshold frequency (default 15 kHz)
down into the audible range (1–4 kHz) so you can hear bat echolocation,
insect ultrasonic emissions, and equipment whines that are normally
inaudible.

Two modes:
- Heterodyne (classic): multiply by a local oscillator, producing sum
  and difference frequencies. Low-pass filter keeps only the difference.
  Like tuning a radio — you pick a center frequency and hear what's there.
- Frequency division: divide all frequencies by a fixed ratio (e.g., ÷10).
  Preserves temporal structure (clicks, sweeps) but compresses the
  entire ultrasonic spectrum into a narrow audible band.
"""

from __future__ import annotations

import argparse
import signal
import sys
import time
from pathlib import Path

import numpy as np
from scipy.signal import butter, sosfilt

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from dsp_pipeline import DSPBlock, Pipeline, TestSignal, add_audio_args, add_test_args


class HeterodyneBlock(DSPBlock):
    """Heterodyne frequency shifter for ultrasonic detection."""

    def __init__(self, samplerate: int = 48000, blocksize: int = 1024,
                 lo_freq: float = 20000.0, output_bw: float = 4000.0,
                 mix_gain: float = 1.0):
        super().__init__(samplerate, blocksize)
        self.lo_freq = lo_freq
        self.output_bw = output_bw
        self.mix_gain = mix_gain
        self._phase = 0.0
        self._setup_filter()

    def _setup_filter(self):
        """Design output low-pass filter to keep only difference frequency."""
        nyquist = self.samplerate / 2
        cutoff = min(self.output_bw, nyquist * 0.9)
        self._lpf_sos = butter(4, cutoff, btype="low", fs=self.samplerate,
                               output="sos")
        self._lpf_state = np.zeros((self._lpf_sos.shape[0], 2))

    def set_lo_frequency(self, freq: float):
        """Change local oscillator frequency (tune to different ultrasonic band)."""
        self.lo_freq = freq

    def process(self, samples: np.ndarray) -> np.ndarray:
        mono = samples[:, 0] if samples.ndim == 2 else samples
        n = len(mono)

        # generate local oscillator
        t = (np.arange(n) + self._phase) / self.samplerate
        lo = np.cos(2 * np.pi * self.lo_freq * t).astype(np.float32)
        self._phase += n

        # mix (multiply)
        mixed = mono * lo * self.mix_gain

        # low-pass filter to keep only the difference frequency
        filtered, self._lpf_state = sosfilt(self._lpf_sos, mixed,
                                            zi=self._lpf_state)
        filtered = filtered.astype(np.float32)

        if samples.ndim == 2:
            out = np.zeros_like(samples)
            out[:, 0] = filtered
            if samples.shape[1] > 1:
                out[:, 1] = filtered
            return out
        return filtered

    def reset(self):
        self._phase = 0.0
        self._lpf_state = np.zeros((self._lpf_sos.shape[0], 2))

    def get_status(self) -> dict:
        return {
            "enabled": self.enabled,
            "lo_freq_hz": self.lo_freq,
            "output_bw_hz": self.output_bw,
        }


class FrequencyDividerBlock(DSPBlock):
    """Frequency divider — divides all frequencies by a fixed ratio."""

    def __init__(self, samplerate: int = 48000, blocksize: int = 1024,
                 division_ratio: int = 10, highpass: float = 12000.0):
        super().__init__(samplerate, blocksize)
        self.division_ratio = division_ratio
        self.highpass = highpass
        self._setup_filters()
        self._env_state = 0.0
        self._last_zero_cross = False

    def _setup_filters(self):
        """Input high-pass to isolate ultrasonic content."""
        nyquist = self.samplerate / 2
        self._hpf_sos = butter(4, self.highpass, btype="high",
                               fs=self.samplerate, output="sos")
        self._hpf_state = np.zeros((self._hpf_sos.shape[0], 2))
        # output smoothing
        out_cutoff = min(self.samplerate / (2 * self.division_ratio), nyquist * 0.4)
        self._lpf_sos = butter(3, out_cutoff, btype="low",
                               fs=self.samplerate, output="sos")
        self._lpf_state = np.zeros((self._lpf_sos.shape[0], 2))

    def process(self, samples: np.ndarray) -> np.ndarray:
        mono = samples[:, 0] if samples.ndim == 2 else samples
        n = len(mono)

        # high-pass to get only ultrasonic content
        ultrasonic, self._hpf_state = sosfilt(self._hpf_sos, mono,
                                              zi=self._hpf_state)

        # envelope following + zero-crossing frequency division
        # simple approach: decimate by counting zero crossings
        output = np.zeros(n, dtype=np.float32)
        envelope = np.abs(ultrasonic)

        # track zero crossings and generate divided square wave
        cross_count = 0
        level = 1.0
        for i in range(n):
            current_positive = ultrasonic[i] >= 0
            if current_positive != self._last_zero_cross:
                cross_count += 1
                self._last_zero_cross = current_positive
                if cross_count >= self.division_ratio:
                    cross_count = 0
                    level = -level
            output[i] = level * envelope[i]

        # smooth the output
        output, self._lpf_state = sosfilt(self._lpf_sos, output,
                                          zi=self._lpf_state)
        output = output.astype(np.float32)

        # normalize
        peak = np.max(np.abs(output))
        if peak > 0.01:
            output *= 0.5 / peak

        if samples.ndim == 2:
            out = np.zeros_like(samples)
            out[:, 0] = output
            if samples.shape[1] > 1:
                out[:, 1] = output
            return out
        return output

    def reset(self):
        self._hpf_state = np.zeros((self._hpf_sos.shape[0], 2))
        self._lpf_state = np.zeros((self._lpf_sos.shape[0], 2))
        self._last_zero_cross = False

    def get_status(self) -> dict:
        return {
            "enabled": self.enabled,
            "division_ratio": self.division_ratio,
            "highpass_hz": self.highpass,
        }


class UltrasonicMeter(DSPBlock):
    """Measures ultrasonic energy level for display purposes."""

    def __init__(self, samplerate: int = 48000, blocksize: int = 1024,
                 threshold_freq: float = 15000.0):
        super().__init__(samplerate, blocksize)
        self.threshold_freq = threshold_freq
        self._hpf_sos = butter(4, threshold_freq, btype="high",
                               fs=samplerate, output="sos")
        self._hpf_state = np.zeros((self._hpf_sos.shape[0], 2))
        self.level_db = -100.0
        self.peak_freq = 0.0

    def process(self, samples: np.ndarray) -> np.ndarray:
        mono = samples[:, 0] if samples.ndim == 2 else samples

        # measure ultrasonic energy
        ultrasonic, self._hpf_state = sosfilt(self._hpf_sos, mono,
                                              zi=self._hpf_state)
        rms = np.sqrt(np.mean(ultrasonic ** 2))
        self.level_db = 20 * np.log10(rms + 1e-10)

        # find peak frequency
        spectrum = np.abs(np.fft.rfft(mono * np.hanning(len(mono))))
        freqs = np.fft.rfftfreq(len(mono), 1.0 / self.samplerate)
        mask = freqs >= self.threshold_freq
        if np.any(mask) and np.max(spectrum[mask]) > 0:
            self.peak_freq = freqs[mask][np.argmax(spectrum[mask])]

        return samples  # pass through unmodified

    def get_status(self) -> dict:
        return {
            "level_db": self.level_db,
            "peak_freq_hz": self.peak_freq,
        }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Ultrasonic heterodyne detector — hear bats, insects, "
        "and electronics that emit above 15 kHz.")
    add_audio_args(parser)
    add_test_args(parser)
    parser.add_argument("--mode", choices=["heterodyne", "divide"],
                        default="heterodyne",
                        help="Detection mode (default: heterodyne)")
    parser.add_argument("--lo-freq", type=float, default=20000.0,
                        help="Local oscillator frequency in Hz for heterodyne "
                        "mode (default: 20000)")
    parser.add_argument("--output-bw", type=float, default=4000.0,
                        help="Output bandwidth in Hz (default: 4000)")
    parser.add_argument("--division", type=int, default=10,
                        help="Frequency division ratio for divide mode (default: 10)")
    parser.add_argument("--highpass", type=float, default=15000.0,
                        help="High-pass cutoff for ultrasonic isolation (default: 15000)")
    parser.add_argument("--gain", type=float, default=10.0,
                        help="Gain applied to ultrasonic content (default: 10)")
    parser.add_argument("--mix-original", type=float, default=0.0,
                        help="Mix level of original audio (0-1, default: 0)")
    args = parser.parse_args()

    if args.list_devices:
        from dsp_pipeline.args import open_stream_from_args
        open_stream_from_args(args)
        return 0

    samplerate = args.samplerate
    blocksize = args.blocksize

    if args.mode == "heterodyne":
        detector = HeterodyneBlock(
            samplerate=samplerate,
            blocksize=blocksize,
            lo_freq=args.lo_freq,
            output_bw=args.output_bw,
            mix_gain=args.gain,
        )
    else:
        detector = FrequencyDividerBlock(
            samplerate=samplerate,
            blocksize=blocksize,
            division_ratio=args.division,
            highpass=args.highpass,
        )

    meter = UltrasonicMeter(
        samplerate=samplerate,
        blocksize=blocksize,
        threshold_freq=args.highpass,
    )

    pipeline = Pipeline([meter, detector], samplerate=samplerate,
                        blocksize=blocksize)

    if args.test:
        ts = TestSignal(samplerate, args.test_duration)
        # simulate bat echolocation: FM sweep from 45 kHz down to 25 kHz
        # (we can only capture up to ~22 kHz at 48 kHz sample rate, so
        # simulate a sweep from 22 kHz down to 16 kHz)
        duration = args.test_duration
        n_samples = ts.n_samples

        t = np.arange(n_samples) / samplerate
        # chirp from 22 kHz → 16 kHz, repeated as pulses
        pulse_dur = 0.005  # 5 ms pulses (typical bat call)
        gap_dur = 0.050  # 50 ms between pulses
        cycle = int((pulse_dur + gap_dur) * samplerate)
        pulse_len = int(pulse_dur * samplerate)

        test_audio = np.zeros(n_samples, dtype=np.float32)
        for start in range(0, n_samples - cycle, cycle):
            pulse_t = np.arange(pulse_len) / samplerate
            # FM sweep: instantaneous frequency goes from 22 kHz to 16 kHz
            f0, f1 = 22000, 16000
            phase = 2 * np.pi * (f0 * pulse_t + (f1 - f0) / (2 * pulse_dur) * pulse_t ** 2)
            pulse = 0.3 * np.sin(phase).astype(np.float32)
            # apply Hann envelope
            envelope = np.sin(np.pi * np.arange(pulse_len) / pulse_len) ** 2
            test_audio[start:start + pulse_len] = pulse * envelope

        # add some ambient noise
        test_audio += np.random.randn(n_samples).astype(np.float32) * 0.01

        print(f"Test mode: simulated bat pulses (22→16 kHz FM chirps)")
        print(f"Mode: {args.mode}")
        if args.mode == "heterodyne":
            print(f"LO frequency: {args.lo_freq:.0f} Hz")
        else:
            print(f"Division ratio: {args.division}×")
        print()

        output = pipeline.process_array(test_audio.reshape(-1, 1))
        output_mono = output[:, 0] if output.ndim == 2 else output

        # report
        peak_out = np.max(np.abs(output_mono))
        rms_out = np.sqrt(np.mean(output_mono ** 2))
        print(f"Output peak: {20 * np.log10(peak_out + 1e-10):.1f} dBFS")
        print(f"Output RMS:  {20 * np.log10(rms_out + 1e-10):.1f} dBFS")
        print(f"Ultrasonic level: {meter.level_db:.1f} dB")
        print(f"Peak ultrasonic freq: {meter.peak_freq:.0f} Hz")

        if peak_out > 0.001:
            print("\nDetection successful — ultrasonic content shifted to audible range.")
        else:
            print("\nWARNING: No output detected. Check parameters.")
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

        mix_original = args.mix_original

        def callback(indata, frames):
            processed = pipeline.process_block(indata)
            if mix_original > 0:
                mono = indata[:, 0] if indata.ndim == 2 else indata
                if processed.ndim == 2:
                    processed[:, 0] += mono * mix_original
                    if processed.shape[1] > 1:
                        processed[:, 1] += mono * mix_original
                else:
                    processed += mono * mix_original
            return processed

        stream.set_callback(callback)
        stop = [False]

        def handler(s, f):
            stop[0] = True
        old_handler = signal.signal(signal.SIGINT, handler)

        try:
            stream.start()
            print(f"Bat heterodyne running ({args.mode} mode)", file=sys.stderr)
            if args.mode == "heterodyne":
                print(f"  LO: {args.lo_freq:.0f} Hz | BW: {args.output_bw:.0f} Hz",
                      file=sys.stderr)
            else:
                print(f"  Division: {args.division}× | HPF: {args.highpass:.0f} Hz",
                      file=sys.stderr)
            print("  Ctrl-C to stop", file=sys.stderr)
            print()

            while not stop[0]:
                time.sleep(0.5)
                status = meter.get_status()
                level = status["level_db"]
                freq = status["peak_freq_hz"]
                bar_len = max(0, int((level + 80) / 2))
                bar = "█" * bar_len
                print(f"\r  Ultrasonic: {level:>6.1f} dB | "
                      f"Peak: {freq:>7.0f} Hz | {bar:<30}", end="",
                      flush=True)
        finally:
            stream.stop()
            signal.signal(signal.SIGINT, old_handler)
            print("\n")

    return 0


if __name__ == "__main__":
    sys.exit(main())
