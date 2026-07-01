#!/usr/bin/env python3
"""
parametric_eq.py — N-band parametric equalizer for receiver audio.

Each band has adjustable center frequency, Q (bandwidth), and gain.
Stores presets per mode (CW, SSB, AM, FM). Implements peaking EQ
biquad filters (scipy.signal) in cascade.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import NamedTuple

import numpy as np
from scipy.signal import sosfilt, sosfilt_zi

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from dsp_pipeline import DSPBlock, Pipeline, TestSignal, add_audio_args, add_test_args


class Band(NamedTuple):
    """A single parametric EQ band definition."""
    freq: float   # center frequency in Hz
    q: float      # quality factor (higher = narrower)
    gain_db: float  # boost/cut in dB


# -----------------------------------------------------------------
# Mode presets — tuned for typical receiver audio paths
# -----------------------------------------------------------------
PRESETS: dict[str, list[Band]] = {
    "cw": [
        Band(400, 4.0, -6.0),    # cut low rumble
        Band(700, 5.0, +6.0),    # boost CW tone center
        Band(1200, 3.0, -4.0),   # cut above CW passband
        Band(2500, 2.0, -12.0),  # steep HF rolloff
    ],
    "ssb": [
        Band(250, 1.5, +3.0),    # warm up low end
        Band(800, 1.0, +2.0),    # presence lift
        Band(1800, 1.2, +1.5),   # clarity
        Band(2700, 2.5, -3.0),   # tame sibilance / IF filter edge
    ],
    "am": [
        Band(100, 1.0, -6.0),    # rumble cut (carrier hum)
        Band(400, 0.8, +2.0),    # body
        Band(1500, 0.7, +1.0),   # midrange presence
        Band(4000, 1.5, -4.0),   # cut AM hiss above 4 kHz
        Band(6000, 2.0, -10.0),  # steep HF cut
    ],
    "fm": [
        Band(80, 1.2, +3.0),     # bass boost (de-emphasis recovery)
        Band(400, 0.7, +1.0),    # warmth
        Band(2500, 0.8, +2.0),   # presence / clarity
        Band(6000, 1.0, +1.5),   # air / sparkle
        Band(12000, 2.0, -3.0),  # tame excessive HF
    ],
    "flat": [],  # bypass — no bands active
}


def _peaking_eq_sos(freq: float, q: float, gain_db: float, fs: float) -> np.ndarray:
    """Design a peaking EQ biquad and return as a single second-order section.

    Peaking EQ (constant-Q): boosts or cuts at center frequency with
    specified Q and gain. Unity gain at DC and Nyquist.

    Based on Audio-EQ-Cookbook (Robert Bristow-Johnson).
    """
    A = 10.0 ** (gain_db / 40.0)  # sqrt of linear gain
    w0 = 2.0 * np.pi * freq / fs
    alpha = np.sin(w0) / (2.0 * q)

    b0 = 1.0 + alpha * A
    b1 = -2.0 * np.cos(w0)
    b2 = 1.0 - alpha * A
    a0 = 1.0 + alpha / A
    a1 = -2.0 * np.cos(w0)
    a2 = 1.0 - alpha / A

    # normalize
    sos = np.array([[b0 / a0, b1 / a0, b2 / a0, 1.0, a1 / a0, a2 / a0]])
    return sos


class ParametricEQ(DSPBlock):
    """N-band cascaded parametric equalizer."""

    def __init__(self, samplerate: int = 48000, blocksize: int = 1024,
                 bands: list[Band] | None = None):
        super().__init__(samplerate, blocksize)
        self.bands: list[Band] = bands if bands is not None else []
        self._sos: np.ndarray | None = None
        self._zi: np.ndarray | None = None
        self._rebuild_filters()

    def _rebuild_filters(self):
        """Recompute cascaded SOS array from current bands."""
        if not self.bands:
            self._sos = None
            self._zi = None
            return

        sections = []
        for band in self.bands:
            # skip bands with 0 dB gain (no effect)
            if abs(band.gain_db) < 0.01:
                continue
            sos = _peaking_eq_sos(band.freq, band.q, band.gain_db, self.samplerate)
            sections.append(sos[0])

        if not sections:
            self._sos = None
            self._zi = None
            return

        self._sos = np.array(sections)
        self._zi = sosfilt_zi(self._sos) * 0.0

    def set_bands(self, bands: list[Band]):
        """Replace all bands and rebuild filters."""
        self.bands = bands
        self._rebuild_filters()

    def process(self, samples: np.ndarray) -> np.ndarray:
        if self._sos is None:
            return samples

        mono = samples[:, 0] if samples.ndim == 2 else samples

        output, self._zi = sosfilt(self._sos, mono, zi=self._zi)
        output = output.astype(np.float32)

        # soft clip to prevent overload from boosted bands
        output = np.tanh(output)

        if samples.ndim == 2:
            return output.reshape(-1, 1).repeat(samples.shape[1], axis=1)
        return output

    def reset(self):
        self._rebuild_filters()

    def get_status(self) -> dict:
        return {
            "enabled": self.enabled,
            "n_bands": len(self.bands),
            "bands": [
                {"freq": b.freq, "q": b.q, "gain_db": b.gain_db}
                for b in self.bands
            ],
        }


def parse_bands(band_str: str) -> list[Band]:
    """Parse band specifications from 'freq:q:gain_db' triplet strings.

    Example: '700:5:+6,1200:3:-4' -> [Band(700, 5, 6), Band(1200, 3, -4)]
    """
    bands = []
    for triplet in band_str.split(","):
        parts = triplet.strip().split(":")
        if len(parts) != 3:
            raise ValueError(
                f"Bad band spec '{triplet}' — expected 'freq:q:gain_db'")
        freq = float(parts[0])
        q = float(parts[1])
        gain_db = float(parts[2])
        if freq <= 0:
            raise ValueError(f"Band frequency must be positive, got {freq}")
        if q <= 0:
            raise ValueError(f"Band Q must be positive, got {q}")
        bands.append(Band(freq, q, gain_db))
    return bands


def main() -> int:
    parser = argparse.ArgumentParser(
        description="N-band parametric equalizer for receiver audio.")
    add_audio_args(parser)
    add_test_args(parser)
    parser.add_argument("--preset", choices=list(PRESETS.keys()),
                        help="Load a mode preset (cw, ssb, am, fm, flat)")
    parser.add_argument("--bands", type=str, metavar="SPEC",
                        help="Custom bands as 'freq:q:gain_db' triplets, "
                             "comma-separated (e.g. '700:5:+6,1200:3:-4')")
    parser.add_argument("--list-presets", action="store_true",
                        help="Show available presets and exit")
    parser.add_argument("--output", metavar="WAV",
                        help="Write processed audio to WAV file (test mode)")
    args = parser.parse_args()

    if args.list_presets:
        for name, bands in PRESETS.items():
            print(f"\n{name}:")
            if not bands:
                print("  (flat — no EQ applied)")
            for b in bands:
                sign = "+" if b.gain_db >= 0 else ""
                print(f"  {b.freq:>6.0f} Hz  Q={b.q:<4.1f}  {sign}{b.gain_db:.1f} dB")
        return 0

    if args.list_devices:
        from dsp_pipeline.args import open_stream_from_args
        open_stream_from_args(args)
        return 0

    # resolve bands: --bands overrides --preset
    if args.bands:
        bands = parse_bands(args.bands)
    elif args.preset:
        bands = PRESETS[args.preset]
    else:
        bands = PRESETS["ssb"]  # sensible default

    block = ParametricEQ(
        samplerate=args.samplerate,
        blocksize=args.blocksize,
        bands=bands,
    )
    pipeline = Pipeline([block], samplerate=args.samplerate, blocksize=args.blocksize)

    if args.test:
        ts = TestSignal(args.samplerate, args.test_duration)
        # speech-like signal is the best test for an EQ
        test_audio = ts.speech_like(amplitude=0.4, noise_amplitude=0.02)

        processed = pipeline.process_array(test_audio.reshape(-1, 1))

        preset_name = args.preset or ("custom" if args.bands else "ssb")
        print(f"Parametric EQ — preset: {preset_name}, {len(bands)} bands")
        for b in bands:
            sign = "+" if b.gain_db >= 0 else ""
            print(f"  {b.freq:>6.0f} Hz  Q={b.q:<4.1f}  {sign}{b.gain_db:.1f} dB")
        print(f"Input peak:  {np.max(np.abs(test_audio)):.4f}")
        print(f"Output peak: {np.max(np.abs(processed)):.4f}")

        if args.output:
            import soundfile as sf
            sf.write(args.output, processed, args.samplerate)
            print(f"Wrote {args.output}")
    else:
        preset_name = args.preset or ("custom" if args.bands else "ssb")
        print(f"Parametric EQ: {preset_name}, {len(bands)} bands", file=sys.stderr)
        for b in bands:
            sign = "+" if b.gain_db >= 0 else ""
            print(f"  {b.freq:>6.0f} Hz  Q={b.q:<4.1f}  {sign}{b.gain_db:.1f} dB",
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
