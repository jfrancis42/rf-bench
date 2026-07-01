#!/usr/bin/env python3
"""
speech_compressor.py — Real-time speech processing chain for SSB transmit.

Equivalent to an outboard speech processor (Heil ProSet, W2IHY EQplus).
Processes microphone audio through a multi-stage chain to maximize average
speech power while controlling bandwidth:

  1. High-pass filter (remove sub-200 Hz rumble)
  2. Compressor (reduce dynamic range, adjustable ratio + threshold)
  3. Clipper (hard or soft, add ~6 dB of speech power)
  4. Low-pass filter at 2700 Hz (remove clipper harmonics)
  5. Output level control

Feed output to radio's line-in or USB audio for SSB transmit.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np
from scipy.signal import butter, sosfilt, sosfilt_zi

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from dsp_pipeline import DSPBlock, Pipeline, TestSignal, add_audio_args, add_test_args


# ─────────────────────────────────────────────────────────────────────
# Stage 1: High-pass filter
# ─────────────────────────────────────────────────────────────────────

class HighPassFilter(DSPBlock):
    """Butterworth high-pass to remove sub-vocal rumble, plosives, AC hum."""

    def __init__(self, samplerate: int = 48000, blocksize: int = 256,
                 cutoff_hz: float = 200.0, order: int = 4):
        super().__init__(samplerate, blocksize)
        self.cutoff_hz = cutoff_hz
        self.order = order
        self._design_filter()

    def _design_filter(self):
        self._sos = butter(self.order, self.cutoff_hz, btype='high',
                           fs=self.samplerate, output='sos')
        self._zi = sosfilt_zi(self._sos) * 0.0

    def process(self, samples: np.ndarray) -> np.ndarray:
        mono = samples[:, 0] if samples.ndim == 2 else samples
        output, self._zi = sosfilt(self._sos, mono, zi=self._zi)
        output = output.astype(np.float32)
        if samples.ndim == 2:
            return output.reshape(-1, 1).repeat(samples.shape[1], axis=1)
        return output

    def reset(self):
        self._design_filter()

    def get_status(self) -> dict:
        return {"enabled": self.enabled, "cutoff_hz": self.cutoff_hz,
                "order": self.order}


# ─────────────────────────────────────────────────────────────────────
# Stage 2: Compressor
# ─────────────────────────────────────────────────────────────────────

class Compressor(DSPBlock):
    """Feed-forward RMS compressor with adjustable ratio and threshold.

    Uses a smoothed RMS envelope detector with separate attack and release
    time constants. Gain reduction is computed in dB domain.
    """

    def __init__(self, samplerate: int = 48000, blocksize: int = 256,
                 threshold_db: float = -20.0, ratio: float = 4.0,
                 attack_ms: float = 5.0, release_ms: float = 50.0):
        super().__init__(samplerate, blocksize)
        self.threshold_db = threshold_db
        self.ratio = ratio
        self.attack_ms = attack_ms
        self.release_ms = release_ms
        self._attack_coeff = 1.0 - np.exp(-1.0 / (attack_ms * 0.001 * samplerate))
        self._release_coeff = 1.0 - np.exp(-1.0 / (release_ms * 0.001 * samplerate))
        self._envelope_db = -80.0  # current envelope level in dB

    def process(self, samples: np.ndarray) -> np.ndarray:
        mono = samples[:, 0] if samples.ndim == 2 else samples
        output = np.empty_like(mono)

        threshold = self.threshold_db
        ratio = self.ratio
        attack = self._attack_coeff
        release = self._release_coeff
        env_db = self._envelope_db

        for i in range(len(mono)):
            # convert sample to dB (with floor to avoid log(0))
            sample_abs = abs(mono[i])
            if sample_abs < 1e-10:
                sample_db = -200.0
            else:
                sample_db = 20.0 * np.log10(sample_abs)

            # envelope follower with separate attack/release
            if sample_db > env_db:
                env_db += attack * (sample_db - env_db)
            else:
                env_db += release * (sample_db - env_db)

            # compute gain reduction
            if env_db > threshold:
                over_db = env_db - threshold
                gain_reduction_db = over_db * (1.0 - 1.0 / ratio)
            else:
                gain_reduction_db = 0.0

            # apply gain
            gain_linear = 10.0 ** (-gain_reduction_db / 20.0)
            output[i] = mono[i] * gain_linear

        self._envelope_db = env_db

        output = output.astype(np.float32)
        if samples.ndim == 2:
            return output.reshape(-1, 1).repeat(samples.shape[1], axis=1)
        return output

    def reset(self):
        self._envelope_db = -80.0

    def get_status(self) -> dict:
        return {
            "enabled": self.enabled,
            "threshold_db": self.threshold_db,
            "ratio": self.ratio,
            "envelope_db": round(self._envelope_db, 1),
        }


# ─────────────────────────────────────────────────────────────────────
# Stage 3: Clipper
# ─────────────────────────────────────────────────────────────────────

class Clipper(DSPBlock):
    """Hard or soft clipper to increase average speech power.

    Hard clip: flat-tops the waveform at the threshold level.
    Soft clip: tanh-based saturation — smoother harmonics, less harsh.
    """

    def __init__(self, samplerate: int = 48000, blocksize: int = 256,
                 clip_db: float = -6.0, mode: str = "soft"):
        super().__init__(samplerate, blocksize)
        self.clip_db = clip_db
        self.mode = mode  # "hard" or "soft"
        self._threshold = 10.0 ** (clip_db / 20.0)

    def process(self, samples: np.ndarray) -> np.ndarray:
        mono = samples[:, 0] if samples.ndim == 2 else samples

        if self.mode == "hard":
            output = np.clip(mono, -self._threshold, self._threshold)
        else:
            # tanh soft clip: normalize to threshold, apply tanh, rescale
            # tanh(1) ~ 0.76, so we scale input so threshold maps to ~1.5
            # giving gentle compression above threshold
            scaled = mono / self._threshold * 1.5
            output = self._threshold * np.tanh(scaled) / np.tanh(1.5)

        output = output.astype(np.float32)
        if samples.ndim == 2:
            return output.reshape(-1, 1).repeat(samples.shape[1], axis=1)
        return output

    def reset(self):
        pass

    def get_status(self) -> dict:
        return {"enabled": self.enabled, "clip_db": self.clip_db,
                "mode": self.mode, "threshold_linear": round(self._threshold, 4)}


# ─────────────────────────────────────────────────────────────────────
# Stage 4: Low-pass filter
# ─────────────────────────────────────────────────────────────────────

class LowPassFilter(DSPBlock):
    """Butterworth low-pass to remove clipper harmonics above 2700 Hz.

    Essential after clipping — the clipper generates wideband harmonics
    that would splatter into adjacent channels on SSB.
    """

    def __init__(self, samplerate: int = 48000, blocksize: int = 256,
                 cutoff_hz: float = 2700.0, order: int = 6):
        super().__init__(samplerate, blocksize)
        self.cutoff_hz = cutoff_hz
        self.order = order
        self._design_filter()

    def _design_filter(self):
        self._sos = butter(self.order, self.cutoff_hz, btype='low',
                           fs=self.samplerate, output='sos')
        self._zi = sosfilt_zi(self._sos) * 0.0

    def process(self, samples: np.ndarray) -> np.ndarray:
        mono = samples[:, 0] if samples.ndim == 2 else samples
        output, self._zi = sosfilt(self._sos, mono, zi=self._zi)
        output = output.astype(np.float32)
        if samples.ndim == 2:
            return output.reshape(-1, 1).repeat(samples.shape[1], axis=1)
        return output

    def reset(self):
        self._design_filter()

    def get_status(self) -> dict:
        return {"enabled": self.enabled, "cutoff_hz": self.cutoff_hz,
                "order": self.order}


# ─────────────────────────────────────────────────────────────────────
# Stage 5: Output level control
# ─────────────────────────────────────────────────────────────────────

class OutputLevel(DSPBlock):
    """Simple gain block for final output level adjustment."""

    def __init__(self, samplerate: int = 48000, blocksize: int = 256,
                 gain_db: float = 0.0):
        super().__init__(samplerate, blocksize)
        self.gain_db = gain_db
        self._gain_linear = 10.0 ** (gain_db / 20.0)

    def process(self, samples: np.ndarray) -> np.ndarray:
        return (samples * self._gain_linear).astype(np.float32)

    def reset(self):
        pass

    def get_status(self) -> dict:
        return {"enabled": self.enabled, "gain_db": self.gain_db,
                "gain_linear": round(self._gain_linear, 4)}


# ─────────────────────────────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────────────────────────────

def main() -> int:
    parser = argparse.ArgumentParser(
        description="Real-time speech compressor/processor for SSB transmit.")
    add_audio_args(parser)
    add_test_args(parser)

    g = parser.add_argument_group("compressor settings")
    g.add_argument("--ratio", type=float, default=4.0, metavar="N",
                   help="Compression ratio (default 4:1)")
    g.add_argument("--threshold-db", type=float, default=-20.0, metavar="DB",
                   help="Compression threshold in dBFS (default -20)")
    g.add_argument("--attack-ms", type=float, default=5.0, metavar="MS",
                   help="Compressor attack time (default 5 ms)")
    g.add_argument("--release-ms", type=float, default=50.0, metavar="MS",
                   help="Compressor release time (default 50 ms)")

    g = parser.add_argument_group("clipper settings")
    g.add_argument("--clip-db", type=float, default=-6.0, metavar="DB",
                   help="Clipper threshold in dBFS (default -6)")
    g.add_argument("--clip-mode", choices=["hard", "soft"], default="soft",
                   help="Clipper mode: hard or soft (default soft)")

    g = parser.add_argument_group("filter settings")
    g.add_argument("--highpass-freq", type=float, default=200.0, metavar="HZ",
                   help="High-pass cutoff frequency (default 200 Hz)")
    g.add_argument("--lowpass-freq", type=float, default=2700.0, metavar="HZ",
                   help="Low-pass cutoff frequency (default 2700 Hz)")

    g = parser.add_argument_group("output")
    g.add_argument("--output-level-db", type=float, default=0.0, metavar="DB",
                   help="Output gain in dB (default 0)")
    g.add_argument("--output", metavar="WAV",
                   help="Write processed audio to WAV file (test mode)")

    args = parser.parse_args()

    if args.list_devices:
        from dsp_pipeline.args import open_stream_from_args
        open_stream_from_args(args)
        return 0

    # Use blocksize 256 for lower latency on TX path
    blocksize = args.blocksize if args.blocksize != 1024 else 256
    samplerate = args.samplerate

    # Build the processing chain
    hpf = HighPassFilter(samplerate=samplerate, blocksize=blocksize,
                         cutoff_hz=args.highpass_freq)
    comp = Compressor(samplerate=samplerate, blocksize=blocksize,
                      threshold_db=args.threshold_db, ratio=args.ratio,
                      attack_ms=args.attack_ms, release_ms=args.release_ms)
    clip = Clipper(samplerate=samplerate, blocksize=blocksize,
                   clip_db=args.clip_db, mode=args.clip_mode)
    lpf = LowPassFilter(samplerate=samplerate, blocksize=blocksize,
                         cutoff_hz=args.lowpass_freq)
    output_gain = OutputLevel(samplerate=samplerate, blocksize=blocksize,
                              gain_db=args.output_level_db)

    pipeline = Pipeline(
        [hpf, comp, clip, lpf, output_gain],
        samplerate=samplerate,
        blocksize=blocksize,
    )

    if args.test:
        ts = TestSignal(samplerate, args.test_duration)
        test_audio = ts.speech_like(amplitude=0.5, noise_amplitude=0.03)

        processed = pipeline.process_array(test_audio.reshape(-1, 1))

        input_peak = np.max(np.abs(test_audio))
        output_peak = np.max(np.abs(processed))
        input_rms = np.sqrt(np.mean(test_audio ** 2))
        output_rms = np.sqrt(np.mean(processed ** 2))

        print("Speech Compressor — SSB TX processor")
        print(f"  High-pass:   {args.highpass_freq:.0f} Hz")
        print(f"  Compressor:  {args.ratio:.1f}:1 @ {args.threshold_db:.1f} dBFS")
        print(f"  Clipper:     {args.clip_mode} @ {args.clip_db:.1f} dBFS")
        print(f"  Low-pass:    {args.lowpass_freq:.0f} Hz")
        print(f"  Output gain: {args.output_level_db:+.1f} dB")
        print()
        print(f"  Input  peak: {input_peak:.4f} ({20*np.log10(input_peak+1e-10):.1f} dBFS)")
        print(f"  Output peak: {output_peak:.4f} ({20*np.log10(output_peak+1e-10):.1f} dBFS)")
        print(f"  Input  RMS:  {input_rms:.4f} ({20*np.log10(input_rms+1e-10):.1f} dBFS)")
        print(f"  Output RMS:  {output_rms:.4f} ({20*np.log10(output_rms+1e-10):.1f} dBFS)")
        if input_rms > 1e-10:
            rms_gain = 20 * np.log10(output_rms / input_rms)
            print(f"  RMS gain:    {rms_gain:+.1f} dB (speech power increase)")

        if args.output:
            import soundfile as sf
            sf.write(args.output, processed, samplerate)
            print(f"\n  Wrote {args.output}")
    else:
        print("Speech Compressor — SSB TX processor", file=sys.stderr)
        print(f"  High-pass:   {args.highpass_freq:.0f} Hz", file=sys.stderr)
        print(f"  Compressor:  {args.ratio:.1f}:1 @ {args.threshold_db:.1f} dBFS",
              file=sys.stderr)
        print(f"  Clipper:     {args.clip_mode} @ {args.clip_db:.1f} dBFS",
              file=sys.stderr)
        print(f"  Low-pass:    {args.lowpass_freq:.0f} Hz", file=sys.stderr)
        print(f"  Output gain: {args.output_level_db:+.1f} dB", file=sys.stderr)
        print(f"  Block size:  {blocksize} ({blocksize/samplerate*1000:.1f} ms latency)",
              file=sys.stderr)
        pipeline.run_realtime(
            input_device=args.input_device,
            output_device=args.output_device,
            channels_in=args.channels_in,
            channels_out=args.channels_out,
        )

    return 0


if __name__ == "__main__":
    sys.exit(main())
