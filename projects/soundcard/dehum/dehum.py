#!/usr/bin/env python3
"""
dehum.py — Power-line hum removal filter.

Auto-detects 50/60 Hz fundamental via spectral peak, then notches the
fundamental and all harmonics up to N (default 15). Very narrow IIR
notches (~1 Hz bandwidth via high Q) so speech damage is negligible.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np
from scipy.signal import iirnotch, sosfilt, sosfilt_zi, tf2sos

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from dsp_pipeline import DSPBlock, Pipeline, TestSignal, add_audio_args, add_test_args


class DeHum(DSPBlock):
    """Power-line hum removal via cascaded narrow IIR notch filters."""

    def __init__(self, samplerate: int = 48000, blocksize: int = 1024,
                 freq: float | None = None, harmonics: int = 15,
                 notch_q: float = 50.0, auto: bool = True):
        super().__init__(samplerate, blocksize)
        self.harmonics = harmonics
        self.notch_q = notch_q
        self.auto = auto
        self._fundamental: float | None = freq
        self._filters: list[tuple[np.ndarray, np.ndarray]] = []  # (sos, zi)
        self._spectrum_avg: np.ndarray | None = None
        self._detection_frames = 0
        self._locked = not auto  # if freq forced, lock immediately

        if freq is not None:
            self._build_filters(freq)

    def _build_filters(self, fundamental: float) -> None:
        """Build cascaded notch filters for fundamental + all harmonics."""
        self._filters = []
        for h in range(1, self.harmonics + 1):
            f_notch = fundamental * h
            if f_notch >= self.samplerate / 2:
                break
            b, a = iirnotch(f_notch, self.notch_q, fs=self.samplerate)
            sos = tf2sos(b, a)
            zi = sosfilt_zi(sos) * 0
            self._filters.append((sos, zi))
        self._fundamental = fundamental

    def _detect_fundamental(self, spectrum: np.ndarray, freqs: np.ndarray) -> float | None:
        """Detect whether hum fundamental is 50 or 60 Hz by comparing spectral energy."""
        # Look for energy at 50 Hz and its harmonics vs 60 Hz and its harmonics.
        # Use a window of +/- 2 Hz around each expected harmonic.
        window_hz = 2.0
        freq_res = freqs[1] - freqs[0] if len(freqs) > 1 else 1.0
        window_bins = max(1, int(window_hz / freq_res))

        def harmonic_energy(fundamental: float) -> float:
            total = 0.0
            count = 0
            for h in range(1, min(6, self.harmonics + 1)):
                f = fundamental * h
                if f >= self.samplerate / 2:
                    break
                idx = int(round(f / freq_res))
                lo = max(0, idx - window_bins)
                hi = min(len(spectrum), idx + window_bins + 1)
                total += np.max(spectrum[lo:hi])
                count += 1
            return total / max(count, 1)

        e50 = harmonic_energy(50.0)
        e60 = harmonic_energy(60.0)

        # Need clear winner — at least 6 dB above noise floor in the 40-70 Hz region
        noise_region = spectrum[(freqs >= 40) & (freqs <= 70)]
        if len(noise_region) == 0:
            return None
        noise_floor = np.median(noise_region)
        threshold = noise_floor * 4.0  # ~12 dB above median

        if e60 > threshold and e60 > e50 * 1.5:
            return 60.0
        elif e50 > threshold and e50 > e60 * 1.5:
            return 50.0
        elif e60 > threshold:
            return 60.0
        elif e50 > threshold:
            return 50.0
        return None

    def process(self, samples: np.ndarray) -> np.ndarray:
        mono = samples[:, 0] if samples.ndim == 2 else samples

        # Auto-detect fundamental if not locked
        if self.auto and not self._locked:
            spectrum = np.abs(np.fft.rfft(mono * np.hanning(len(mono))))
            freqs = np.fft.rfftfreq(len(mono), 1.0 / self.samplerate)

            if self._spectrum_avg is None:
                self._spectrum_avg = spectrum.copy()
            else:
                self._spectrum_avg = 0.7 * self._spectrum_avg + 0.3 * spectrum

            self._detection_frames += 1
            # Wait for a few frames to build up spectrum average
            if self._detection_frames >= 5:
                detected = self._detect_fundamental(self._spectrum_avg, freqs)
                if detected is not None:
                    self._build_filters(detected)
                    self._locked = True
                    print(f"De-hum: locked to {detected:.0f} Hz fundamental, "
                          f"notching {len(self._filters)} harmonics", file=sys.stderr)

        # Apply notch filters in cascade
        if not self._filters:
            return samples

        output = mono.copy()
        for i, (sos, zi) in enumerate(self._filters):
            output, new_zi = sosfilt(sos, output, zi=zi)
            self._filters[i] = (sos, new_zi)

        output = output.astype(np.float32)
        if samples.ndim == 2:
            return output.reshape(-1, 1).repeat(samples.shape[1], axis=1)
        return output

    def reset(self):
        self._filters = []
        self._spectrum_avg = None
        self._detection_frames = 0
        if self.auto:
            self._locked = False
            self._fundamental = None

    def get_status(self) -> dict:
        return {
            "enabled": self.enabled,
            "fundamental": f"{self._fundamental:.0f} Hz" if self._fundamental else "detecting...",
            "locked": self._locked,
            "harmonics_notched": len(self._filters),
        }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Power-line hum removal filter (50/60 Hz + harmonics).")
    add_audio_args(parser)
    add_test_args(parser)

    g = parser.add_argument_group("de-hum parameters")
    g.add_argument("--auto", action="store_true", default=True,
                   help="Auto-detect 50/60 Hz fundamental (default)")
    g.add_argument("--freq", type=float, choices=[50.0, 60.0], default=None,
                   help="Force fundamental frequency (50 or 60 Hz)")
    g.add_argument("--harmonics", type=int, default=15, metavar="N",
                   help="Number of harmonics to notch (default 15)")
    g.add_argument("--notch-q", type=float, default=50.0, metavar="Q",
                   help="Notch Q factor — higher = narrower (default 50, ~1 Hz BW)")
    g.add_argument("--output", metavar="WAV",
                   help="Write processed audio to WAV file (test mode)")
    args = parser.parse_args()

    if args.list_devices:
        from dsp_pipeline.args import open_stream_from_args
        open_stream_from_args(args)
        return 0

    freq = args.freq
    auto = freq is None

    block = DeHum(
        samplerate=args.samplerate,
        blocksize=args.blocksize,
        freq=freq,
        harmonics=args.harmonics,
        notch_q=args.notch_q,
        auto=auto,
    )
    pipeline = Pipeline([block], samplerate=args.samplerate, blocksize=args.blocksize)

    if args.test:
        ts = TestSignal(args.samplerate, args.test_duration)
        # Speech-like signal contaminated with 60 Hz hum + harmonics
        speech = ts.speech_like(amplitude=0.3)
        hum = ts.hum(freq=60.0, harmonics=10, amplitude=0.25)
        test_audio = speech + hum

        print(f"Test: {args.test_duration}s speech + 60 Hz hum (10 harmonics)")
        processed = pipeline.process_array(test_audio.reshape(-1, 1))
        print(f"Status: {block.get_status()}")

        # Report suppression
        pre_power = np.mean(test_audio ** 2)
        post_power = np.mean(processed.flatten() ** 2)
        speech_power = np.mean(speech ** 2)
        print(f"Input power:  {10 * np.log10(pre_power + 1e-12):.1f} dB")
        print(f"Output power: {10 * np.log10(post_power + 1e-12):.1f} dB")
        print(f"Speech power: {10 * np.log10(speech_power + 1e-12):.1f} dB")

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
