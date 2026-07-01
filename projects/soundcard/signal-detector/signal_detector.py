#!/usr/bin/env python3
"""
signal_detector.py — Signal-presence detector / audio squelch.

Carrier-detect for audio: opens squelch for ANY signal above the noise
floor — CW, data, carriers, voice, tones. Different from vad-squelch
which opens only for speech.

Detection methods:
- energy: power threshold above noise floor (fast, simple)
- spectral_flatness: noise is spectrally flat; signals have peaks
- autocorrelation: periodic/quasi-periodic signals have strong ACF peaks

Outputs squelch gate (open/close) and confidence score (0-1).
"""

from __future__ import annotations

import argparse
import csv
import sys
import time
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from dsp_pipeline import DSPBlock, Pipeline, TestSignal, add_audio_args, add_test_args


class SignalDetector(DSPBlock):
    """Signal-presence detector with configurable detection method."""

    def __init__(self, samplerate: int = 48000, blocksize: int = 1024,
                 method: str = "energy", threshold: float = 0.3,
                 hang_ms: float = 200.0, attack_ms: float = 5.0,
                 release_ms: float = 30.0):
        super().__init__(samplerate, blocksize)
        self.method = method
        self.threshold = threshold
        self.hang_samples = int(hang_ms * samplerate / 1000)
        self.attack_coeff = 1.0 - np.exp(-1.0 / (attack_ms * samplerate / 1000))
        self.release_coeff = 1.0 - np.exp(-1.0 / (release_ms * samplerate / 1000))

        # state
        self._hang_counter = 0
        self._gate_level = 0.0
        self._is_open = False
        self._confidence = 0.0

        # noise floor tracker (exponential moving average of quiet blocks)
        self._noise_floor = 1e-6
        self._noise_alpha = 0.02  # slow adaptation

        # for spectral flatness: smoothed estimate
        self._sf_history: list[float] = []

    def _update_noise_floor(self, block_power: float):
        """Track noise floor: adapt only when signal is absent."""
        if not self._is_open:
            self._noise_floor += self._noise_alpha * (block_power - self._noise_floor)
            # clamp to avoid zero
            self._noise_floor = max(self._noise_floor, 1e-10)

    def _energy_detect(self, mono: np.ndarray) -> float:
        """Energy detector: signal power relative to noise floor.

        Confidence is the dB above noise floor, mapped to 0-1.
        """
        power = np.mean(mono ** 2)
        self._update_noise_floor(power)

        if self._noise_floor < 1e-10:
            return 0.0

        snr_linear = power / self._noise_floor
        # map: 1x noise=0, 10x noise(10 dB)=0.5, 100x(20 dB)=1.0
        snr_db = 10 * np.log10(snr_linear + 1e-10)
        confidence = float(np.clip(snr_db / 20.0, 0.0, 1.0))
        return confidence

    def _spectral_flatness_detect(self, mono: np.ndarray) -> float:
        """Spectral flatness detector.

        Spectral flatness = geometric mean / arithmetic mean of power spectrum.
        Flat noise → SF ≈ 1. Tonal signal → SF ≈ 0.

        We invert it: confidence = 1 - SF, so signals produce high confidence.
        """
        spectrum = np.abs(np.fft.rfft(mono * np.hanning(len(mono)))) ** 2
        # skip DC bin
        spectrum = spectrum[1:]
        if len(spectrum) == 0:
            return 0.0

        # avoid log of zero
        spectrum = np.maximum(spectrum, 1e-20)

        log_mean = np.mean(np.log(spectrum))
        geometric_mean = np.exp(log_mean)
        arithmetic_mean = np.mean(spectrum)

        if arithmetic_mean < 1e-20:
            return 0.0

        flatness = geometric_mean / arithmetic_mean  # 0..1, 1=flat=noise
        confidence = 1.0 - flatness

        # also need above-noise-floor check so silence doesn't trigger
        power = np.mean(mono ** 2)
        self._update_noise_floor(power)
        noise_gate = float(np.clip(10 * np.log10(power / (self._noise_floor + 1e-10)) / 10.0, 0.0, 1.0))

        return float(np.clip(confidence * noise_gate, 0.0, 1.0))

    def _autocorrelation_detect(self, mono: np.ndarray) -> float:
        """Autocorrelation detector.

        Periodic or quasi-periodic signals (CW, voice, data tones, carriers)
        produce strong autocorrelation peaks. Pure noise does not.

        Search range: 2 ms to 20 ms lag (50 Hz to 500 Hz fundamental),
        plus a wider check for slower periodicities.
        """
        n = len(mono)
        if n < 200:
            return 0.0

        frame = mono - np.mean(mono)
        energy = np.sum(frame ** 2)
        if energy < 1e-10:
            return 0.0

        # normalized autocorrelation
        # search lags from ~2 ms (500 Hz) to half the block
        min_lag = int(self.samplerate * 0.002)  # 2 ms → 96 samples at 48k
        max_lag = min(n // 2, int(self.samplerate * 0.020))  # 20 ms

        acf = np.correlate(frame[:max_lag * 2], frame[:max_lag * 2], mode="full")
        acf = acf[len(frame[:max_lag * 2]) - 1:]  # positive lags
        acf = acf / (energy + 1e-10)

        if max_lag <= min_lag:
            return 0.0

        search = acf[min_lag:max_lag]
        if len(search) == 0:
            return 0.0

        peak_val = float(np.max(search))

        # also need above-noise check
        power = np.mean(mono ** 2)
        self._update_noise_floor(power)
        noise_gate = float(np.clip(10 * np.log10(power / (self._noise_floor + 1e-10)) / 10.0, 0.0, 1.0))

        confidence = float(np.clip(peak_val, 0.0, 1.0)) * noise_gate
        return confidence

    def process(self, samples: np.ndarray) -> np.ndarray:
        mono = samples[:, 0] if samples.ndim == 2 else samples

        # compute confidence based on selected method
        if self.method == "energy":
            self._confidence = self._energy_detect(mono)
        elif self.method == "spectral_flatness":
            self._confidence = self._spectral_flatness_detect(mono)
        elif self.method == "autocorrelation":
            self._confidence = self._autocorrelation_detect(mono)
        else:
            self._confidence = self._energy_detect(mono)

        # squelch logic with hysteresis and hang timer
        if self._confidence >= self.threshold:
            self._is_open = True
            self._hang_counter = self.hang_samples
        elif self._hang_counter > 0:
            self._hang_counter -= len(mono)
        else:
            self._is_open = False

        # smooth gate (attack/release)
        target = 1.0 if self._is_open else 0.0
        coeff = self.attack_coeff if target > self._gate_level else self.release_coeff
        self._gate_level += coeff * (target - self._gate_level)

        # apply gate
        output = mono * self._gate_level
        if samples.ndim == 2:
            return output.reshape(-1, 1).repeat(samples.shape[1], axis=1)
        return output

    def reset(self):
        self._hang_counter = 0
        self._gate_level = 0.0
        self._is_open = False
        self._confidence = 0.0
        self._noise_floor = 1e-6

    def get_status(self) -> dict:
        return {
            "enabled": self.enabled,
            "method": self.method,
            "open": self._is_open,
            "confidence": f"{self._confidence:.3f}",
            "gate_level": f"{self._gate_level:.3f}",
            "noise_floor_dbfs": f"{10*np.log10(self._noise_floor + 1e-10):.1f}",
        }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Signal-presence detector / audio squelch. "
                    "Opens for ANY signal (CW, data, carriers, voice).")
    add_audio_args(parser)
    add_test_args(parser)
    parser.add_argument("--method", choices=["energy", "spectral_flatness", "autocorrelation"],
                        default="energy",
                        help="Detection method (default: energy)")
    parser.add_argument("--threshold", type=float, default=0.3,
                        help="Detection threshold 0-1 (default 0.3)")
    parser.add_argument("--hang-ms", type=float, default=200.0,
                        help="Squelch hang time in ms (default 200)")
    parser.add_argument("--attack-ms", type=float, default=5.0,
                        help="Gate attack time in ms (default 5)")
    parser.add_argument("--release-ms", type=float, default=30.0,
                        help="Gate release time in ms (default 30)")
    parser.add_argument("--output", metavar="PATH",
                        help="Write event log CSV (or gated WAV in test mode)")
    args = parser.parse_args()

    if args.list_devices:
        from dsp_pipeline.args import open_stream_from_args
        open_stream_from_args(args)
        return 0

    block = SignalDetector(
        samplerate=args.samplerate,
        blocksize=args.blocksize,
        method=args.method,
        threshold=args.threshold,
        hang_ms=args.hang_ms,
        attack_ms=args.attack_ms,
        release_ms=args.release_ms,
    )
    pipeline = Pipeline([block], samplerate=args.samplerate, blocksize=args.blocksize)

    if args.test:
        ts = TestSignal(args.samplerate, args.test_duration)
        n = args.samplerate  # samples per second

        # build test sequence: 1s noise, 1s CW, 1s noise, 1s tone, 1s noise
        noise1 = ts.noise(amplitude=0.02)[:n]
        cw = ts.cw_signal(freq=700, wpm=20, amplitude=0.3, noise_amplitude=0.02)[:n]
        noise2 = ts.noise(amplitude=0.02)[n:2*n]
        # steady carrier
        t = np.arange(n) / args.samplerate
        carrier = (0.25 * np.sin(2 * np.pi * 1200 * t)).astype(np.float32)
        carrier += ts.noise(amplitude=0.02)[:n]
        noise3 = ts.noise(amplitude=0.02)[2*n:3*n]

        test_audio = np.concatenate([noise1, cw, noise2, carrier, noise3])

        processed = pipeline.process_array(test_audio.reshape(-1, 1))

        # measure gating: signal segments vs noise segments
        sig_energy = np.mean(processed[n:2*n]**2) + np.mean(processed[3*n:4*n]**2)
        noise_energy = np.mean(processed[:n]**2) + np.mean(processed[2*n:3*n]**2) + np.mean(processed[4*n:5*n]**2)
        sig_energy /= 2
        noise_energy /= 3

        print(f"Method: {args.method}")
        print(f"Signal segments energy: {10*np.log10(sig_energy+1e-10):.1f} dBFS")
        print(f"Noise segments energy:  {10*np.log10(noise_energy+1e-10):.1f} dBFS")
        if noise_energy > 1e-12:
            print(f"Rejection: {10*np.log10(sig_energy/(noise_energy+1e-10)):.1f} dB")
        else:
            print("Rejection: >60 dB (noise fully suppressed)")

        if args.output and args.output.endswith(".wav"):
            import soundfile as sf
            sf.write(args.output, processed, args.samplerate)
            print(f"Wrote {args.output}")
        elif args.output:
            # CSV event log from test
            with open(args.output, "w", newline="") as f:
                writer = csv.writer(f)
                writer.writerow(["time_s", "event", "confidence"])
                writer.writerow([0.0, "test_complete", f"{block._confidence:.3f}"])
            print(f"Wrote {args.output}")
    else:
        import signal as sig_module
        from dsp_pipeline.stream import AudioStream

        stream = AudioStream(
            input_device=args.input_device,
            samplerate=args.samplerate,
            blocksize=args.blocksize,
            channels_in=args.channels_in,
        )

        csv_file = None
        csv_writer = None
        if args.output:
            csv_file = open(args.output, "w", newline="")
            csv_writer = csv.writer(csv_file)
            csv_writer.writerow(["timestamp", "event", "confidence", "noise_floor_dbfs"])

        prev_state = False

        def callback(indata, frames):
            nonlocal prev_state
            block.process(indata)
            # log state transitions
            if csv_writer and block._is_open != prev_state:
                event = "open" if block._is_open else "close"
                csv_writer.writerow([
                    f"{time.time():.3f}",
                    event,
                    f"{block._confidence:.3f}",
                    f"{10*np.log10(block._noise_floor+1e-10):.1f}",
                ])
            prev_state = block._is_open
            return None

        stream.set_callback(callback)
        stop = [False]

        def handler(s, f):
            stop[0] = True
        old = sig_module.signal(sig_module.SIGINT, handler)

        try:
            stream.start()
            print(f"Signal detector ({args.method}): threshold={args.threshold}, "
                  f"hang={args.hang_ms} ms", file=sys.stderr)
            print("Ctrl-C to stop.", file=sys.stderr)
            while not stop[0]:
                time.sleep(0.25)
                status = block.get_status()
                state = "OPEN " if block._is_open else "CLOSE"
                line = (f"[{state}] confidence={status['confidence']}  "
                        f"gate={status['gate_level']}  "
                        f"noise_floor={status['noise_floor_dbfs']} dBFS")
                print(f"\r{line:<72}", end="", flush=True)
        finally:
            stream.stop()
            sig_module.signal(sig_module.SIGINT, old)
            if csv_file:
                csv_file.close()
                print(f"\nWrote {args.output}")
            print()

    return 0


if __name__ == "__main__":
    sys.exit(main())
