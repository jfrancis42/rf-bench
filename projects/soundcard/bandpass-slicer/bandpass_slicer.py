#!/usr/bin/env python3
"""
bandpass_slicer.py — Audio crossover / frequency band slicer.

Splits incoming mono audio into N configurable frequency bands and
routes each to a different stereo position. Primary use case: CW
pile-up where low-pitched signals go left and high-pitched go right
(poor man's binaural CW). Also useful for separating a CW signal at
one pitch from QRM at another pitch.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np
from scipy.signal import butter, sosfilt, sosfilt_zi

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from dsp_pipeline import DSPBlock, Pipeline, TestSignal, add_audio_args, add_test_args


class BandpassSlicer(DSPBlock):
    """Split mono audio into N frequency bands, pan each across stereo field."""

    def __init__(
        self,
        samplerate: int = 48000,
        blocksize: int = 1024,
        band_edges: list[float] | None = None,
        pan_mode: str = "linear",
        filter_order: int = 4,
    ):
        super().__init__(samplerate, blocksize, channels=1)
        # Default band edges split 300-1200 Hz into 4 bands
        if band_edges is None:
            band_edges = [300.0, 525.0, 750.0, 975.0, 1200.0]
        self.band_edges = band_edges
        self.pan_mode = pan_mode
        self.filter_order = filter_order
        self.n_bands = len(band_edges) - 1
        self._filters: list[np.ndarray] = []
        self._zi: list[np.ndarray] = []
        self._pan_gains: list[tuple[float, float]] = []
        self._build_filters()
        self._compute_pan_gains()

    def _build_filters(self):
        """Build bandpass filters for each frequency band."""
        self._filters = []
        self._zi = []
        nyq = self.samplerate / 2.0
        for i in range(self.n_bands):
            low = self.band_edges[i]
            high = self.band_edges[i + 1]
            # Clamp to valid range
            low = max(20.0, low)
            high = min(nyq - 1.0, high)
            if low >= high:
                # Degenerate band — use an allpass (will be silent)
                low = max(20.0, low - 10.0)
                high = low + 20.0
            sos = butter(self.filter_order, [low, high], btype="band",
                         fs=self.samplerate, output="sos")
            zi = sosfilt_zi(sos)
            self._filters.append(sos)
            self._zi.append(np.zeros_like(zi))

    def _compute_pan_gains(self):
        """Compute L/R gain for each band based on pan mode."""
        self._pan_gains = []
        for i in range(self.n_bands):
            if self.n_bands == 1:
                # Single band: center pan
                pan = 0.5
            else:
                # Position 0.0 (full left) to 1.0 (full right)
                pan = i / (self.n_bands - 1)

            if self.pan_mode == "discrete":
                # Hard-pan: each band goes fully to one side
                # Evenly space across L, L/C, C, R/C, R etc.
                if pan < 0.25:
                    l_gain, r_gain = 1.0, 0.0
                elif pan > 0.75:
                    l_gain, r_gain = 0.0, 1.0
                else:
                    l_gain, r_gain = 0.5, 0.5
            else:
                # Linear pan law (constant power approximation)
                # pan=0 -> full left, pan=1 -> full right
                r_gain = pan
                l_gain = 1.0 - pan

            self._pan_gains.append((l_gain, r_gain))

    def process(self, samples: np.ndarray) -> np.ndarray:
        """Filter into bands and sum into stereo output."""
        # Extract mono
        if samples.ndim == 2:
            mono = samples[:, 0]
        else:
            mono = samples
        n = len(mono)

        # Output stereo buffer
        out = np.zeros((n, 2), dtype=np.float32)

        for i in range(self.n_bands):
            # Apply bandpass filter
            filtered, self._zi[i] = sosfilt(
                self._filters[i], mono, zi=self._zi[i]
            )
            filtered = filtered.astype(np.float32)

            # Pan and accumulate
            l_gain, r_gain = self._pan_gains[i]
            out[:, 0] += l_gain * filtered
            out[:, 1] += r_gain * filtered

        # Soft-clip to prevent overload from summing bands
        peak = np.max(np.abs(out))
        if peak > 1.0:
            out /= peak

        return out

    def reset(self):
        """Reset filter states."""
        self._build_filters()

    def get_status(self) -> dict:
        bands_desc = []
        for i in range(self.n_bands):
            low = self.band_edges[i]
            high = self.band_edges[i + 1]
            l_gain, r_gain = self._pan_gains[i]
            if l_gain > r_gain:
                pos = "L"
            elif r_gain > l_gain:
                pos = "R"
            else:
                pos = "C"
            bands_desc.append(f"{low:.0f}-{high:.0f} Hz -> {pos}")
        return {
            "enabled": self.enabled,
            "bands": self.n_bands,
            "pan_mode": self.pan_mode,
            "detail": bands_desc,
        }


def parse_bands(bands_str: str, low_freq: float, high_freq: float) -> list[float]:
    """Parse --bands argument into a list of band edges.

    Input: comma-separated split points (e.g. "400,800,1200")
    Output: list of edges [low_freq, 400, 800, 1200, high_freq]
    """
    splits = [float(x.strip()) for x in bands_str.split(",")]
    splits.sort()
    edges = [low_freq] + splits + [high_freq]
    # Remove duplicates and ensure monotonic
    deduped = [edges[0]]
    for e in edges[1:]:
        if e > deduped[-1]:
            deduped.append(e)
    return deduped


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Audio crossover / frequency band slicer. "
                    "Splits mono audio into N bands panned across the stereo field.")
    add_audio_args(parser)
    add_test_args(parser)
    parser.add_argument("--bands", type=str, default="400,700,1000",
                        help="Comma-separated split frequencies in Hz "
                             "(e.g. '400,800,1200' creates 4 bands). Default: 400,700,1000")
    parser.add_argument("--low", type=float, default=200.0,
                        help="Lower edge of lowest band in Hz (default 200)")
    parser.add_argument("--high", type=float, default=1400.0,
                        help="Upper edge of highest band in Hz (default 1400)")
    parser.add_argument("--pan-mode", choices=["linear", "discrete"], default="linear",
                        help="Pan law: linear (smooth L-R spread) or "
                             "discrete (hard L/C/R assignment). Default: linear")
    parser.add_argument("--order", type=int, default=4,
                        help="Butterworth filter order per band (default 4)")
    parser.add_argument("--output", metavar="WAV",
                        help="Write processed audio to WAV file (test mode)")
    args = parser.parse_args()

    if args.list_devices:
        from dsp_pipeline.args import open_stream_from_args
        open_stream_from_args(args)
        return 0

    band_edges = parse_bands(args.bands, args.low, args.high)
    n_bands = len(band_edges) - 1

    block = BandpassSlicer(
        samplerate=args.samplerate,
        blocksize=args.blocksize,
        band_edges=band_edges,
        pan_mode=args.pan_mode,
        filter_order=args.order,
    )
    pipeline = Pipeline([block], samplerate=args.samplerate, blocksize=args.blocksize)

    if args.test:
        ts = TestSignal(args.samplerate, args.test_duration)
        # Multiple CW tones at different pitches simulating a pile-up
        t = np.arange(ts.n_samples) / args.samplerate
        freqs = np.linspace(band_edges[0] + 50, band_edges[-1] - 50, min(n_bands + 2, 6))
        test_audio = np.zeros(ts.n_samples, dtype=np.float32)
        for f in freqs:
            test_audio += 0.2 * np.sin(2 * np.pi * f * t).astype(np.float32)
        # Add some noise
        test_audio += ts.noise(0.02)
        test_audio = np.clip(test_audio, -1.0, 1.0)

        processed = pipeline.process_array(test_audio.reshape(-1, 1))
        print(f"Bands: {n_bands} ({args.pan_mode} pan)")
        for i in range(n_bands):
            low = band_edges[i]
            high = band_edges[i + 1]
            l_gain, r_gain = block._pan_gains[i]
            print(f"  Band {i+1}: {low:.0f}–{high:.0f} Hz  "
                  f"L={l_gain:.2f} R={r_gain:.2f}")
        print(f"Input peak:  {np.max(np.abs(test_audio)):.3f}")
        print(f"Output peak: {np.max(np.abs(processed)):.3f}")
        print(f"Output shape: {processed.shape} (stereo)")

        if args.output:
            import soundfile as sf
            sf.write(args.output, processed, args.samplerate)
            print(f"Wrote {args.output}")
    else:
        print(f"Bandpass slicer: {n_bands} bands, {args.pan_mode} pan",
              file=sys.stderr)
        for i in range(n_bands):
            low = band_edges[i]
            high = band_edges[i + 1]
            l_gain, r_gain = block._pan_gains[i]
            pos = f"L={l_gain:.1f} R={r_gain:.1f}"
            print(f"  Band {i+1}: {low:.0f}–{high:.0f} Hz  {pos}",
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
