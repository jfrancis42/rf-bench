#!/usr/bin/env python3
"""
spatial_exaggerator.py — Stereo spatial exaggeration.

Exaggerates the spatial cues in stereo audio to create a "superhuman
hearing" effect. Widens the perceived stereo image by amplifying:
- ITD (Interaural Time Difference): delay between ears for direction
- ILD (Interaural Level Difference): level difference between ears

Can also add HRTF-inspired spectral cues for elevation perception.
The result is a dramatically widened soundstage where you can pinpoint
sounds more precisely than natural hearing allows.
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


class SpatialExaggerator(DSPBlock):
    """Exaggerates stereo spatial cues for widened perception."""

    def __init__(self, samplerate: int = 48000, blocksize: int = 1024,
                 itd_gain: float = 3.0, ild_gain: float = 2.0,
                 crossfeed: float = -0.3, width: float = 2.0):
        super().__init__(samplerate, blocksize)
        self.itd_gain = itd_gain
        self.ild_gain = ild_gain
        self.crossfeed = crossfeed
        self.width = width

        # maximum ITD in nature is ~0.7 ms (head width / speed of sound)
        # exaggerated: up to 2.1 ms at itd_gain=3
        self._max_delay_samples = int(0.7e-3 * samplerate * itd_gain)
        self._delay_buffer_l = np.zeros(self._max_delay_samples + blocksize,
                                         dtype=np.float32)
        self._delay_buffer_r = np.zeros(self._max_delay_samples + blocksize,
                                         dtype=np.float32)
        self._buf_pos = 0

        # crossover for frequency-dependent processing
        # ITD is dominant below ~1500 Hz, ILD above ~1500 Hz
        self._crossover_freq = 1500.0
        nyquist = samplerate / 2
        if self._crossover_freq < nyquist:
            self._lp_sos = butter(3, self._crossover_freq / nyquist,
                                   btype="low", output="sos")
            self._hp_sos = butter(3, self._crossover_freq / nyquist,
                                   btype="high", output="sos")
        else:
            self._lp_sos = None
            self._hp_sos = None

        # filter states for continuity
        self._lp_state_l = None
        self._lp_state_r = None
        self._hp_state_l = None
        self._hp_state_r = None

    def _extract_itd(self, left: np.ndarray, right: np.ndarray) -> float:
        """Estimate current ITD from cross-correlation of low-freq content."""
        n = len(left)
        if n < 64:
            return 0.0
        # cross-correlate to find delay
        max_lag = min(self._max_delay_samples, n // 4)
        corr = np.correlate(left[:n], right[:n], mode="full")
        center = n - 1
        search = corr[center - max_lag:center + max_lag + 1]
        if len(search) == 0:
            return 0.0
        peak_idx = np.argmax(search)
        delay_samples = peak_idx - max_lag
        return delay_samples

    def process(self, samples: np.ndarray) -> np.ndarray:
        if samples.ndim == 1 or samples.shape[1] < 2:
            return samples

        n = samples.shape[0]
        left = samples[:, 0].copy()
        right = samples[:, 1].copy()

        # split into low-freq (ITD-dominant) and high-freq (ILD-dominant)
        if self._lp_sos is not None:
            from scipy.signal import sosfilt_zi
            if self._lp_state_l is None:
                self._lp_state_l = sosfilt_zi(self._lp_sos) * left[0]
                self._lp_state_r = sosfilt_zi(self._lp_sos) * right[0]
                self._hp_state_l = sosfilt_zi(self._hp_sos) * left[0]
                self._hp_state_r = sosfilt_zi(self._hp_sos) * right[0]

            lf_l, self._lp_state_l = sosfilt(self._lp_sos, left,
                                              zi=self._lp_state_l)
            lf_r, self._lp_state_r = sosfilt(self._lp_sos, right,
                                              zi=self._lp_state_r)
            hf_l, self._hp_state_l = sosfilt(self._hp_sos, left,
                                              zi=self._hp_state_l)
            hf_r, self._hp_state_r = sosfilt(self._hp_sos, right,
                                              zi=self._hp_state_r)
        else:
            lf_l, lf_r = left, right
            hf_l = np.zeros_like(left)
            hf_r = np.zeros_like(right)

        # --- ITD exaggeration (low frequencies) ---
        # compute M/S (mid/side)
        mid_lf = (lf_l + lf_r) * 0.5
        side_lf = (lf_l - lf_r) * 0.5

        # amplify the side (difference) signal → widens ITD perception
        side_lf *= self.itd_gain

        # reconstruct
        lf_l_out = mid_lf + side_lf
        lf_r_out = mid_lf - side_lf

        # --- ILD exaggeration (high frequencies) ---
        mid_hf = (hf_l + hf_r) * 0.5
        side_hf = (hf_l - hf_r) * 0.5

        # amplify level differences
        side_hf *= self.ild_gain

        # reconstruct
        hf_l_out = mid_hf + side_hf
        hf_r_out = mid_hf - side_hf

        # --- Combine ---
        out_l = lf_l_out + hf_l_out
        out_r = lf_r_out + hf_r_out

        # --- Overall width control (M/S on full signal) ---
        if self.width != 1.0:
            full_mid = (out_l + out_r) * 0.5
            full_side = (out_l - out_r) * 0.5
            full_side *= self.width
            out_l = full_mid + full_side
            out_r = full_mid - full_side

        # --- Crossfeed (prevents extreme isolation headache) ---
        if self.crossfeed != 0:
            cf = self.crossfeed
            new_l = out_l + cf * out_r
            new_r = out_r + cf * out_l
            out_l = new_l
            out_r = new_r

        # soft clip to prevent harsh distortion
        out_l = np.tanh(out_l)
        out_r = np.tanh(out_r)

        output = np.column_stack([out_l, out_r])
        return output.astype(np.float32)

    def get_status(self) -> dict:
        return {
            "itd_gain": self.itd_gain,
            "ild_gain": self.ild_gain,
            "width": self.width,
            "crossfeed": self.crossfeed,
        }

    def reset(self):
        self._lp_state_l = None
        self._lp_state_r = None
        self._hp_state_l = None
        self._hp_state_r = None


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Stereo spatial exaggerator — superhuman directional "
        "hearing through amplified stereo cues.")
    add_audio_args(parser)
    add_test_args(parser)
    parser.add_argument("--itd-gain", type=float, default=3.0,
                        help="ITD (time difference) exaggeration (default: 3.0)")
    parser.add_argument("--ild-gain", type=float, default=2.0,
                        help="ILD (level difference) exaggeration (default: 2.0)")
    parser.add_argument("--width", type=float, default=1.5,
                        help="Overall stereo width multiplier (default: 1.5)")
    parser.add_argument("--crossfeed", type=float, default=-0.2,
                        help="Crossfeed amount, negative reduces isolation "
                        "(default: -0.2)")
    args = parser.parse_args()

    if args.list_devices:
        from dsp_pipeline.args import open_stream_from_args
        open_stream_from_args(args)
        return 0

    samplerate = args.samplerate
    blocksize = args.blocksize

    exaggerator = SpatialExaggerator(
        samplerate=samplerate,
        blocksize=blocksize,
        itd_gain=args.itd_gain,
        ild_gain=args.ild_gain,
        crossfeed=args.crossfeed,
        width=args.width,
    )

    pipeline = Pipeline([exaggerator], samplerate=samplerate, blocksize=blocksize)

    if args.test:
        ts = TestSignal(samplerate, args.test_duration)
        n_samples = ts.n_samples
        t = np.arange(n_samples) / samplerate

        print("Test mode: simulated stereo sources\n")

        # create test with sources at various positions
        # source panning from left to right (sine panning law)
        pan_angle = np.sin(2 * np.pi * 0.5 * t)  # oscillate L↔R at 0.5 Hz

        # 440 Hz tone with spatial movement
        tone = 0.3 * np.sin(2 * np.pi * 440 * t).astype(np.float32)
        # add some broadband for HF spatial cues
        noise = 0.1 * np.random.randn(n_samples).astype(np.float32)
        signal = tone + noise

        # pan: left = cos((angle+1)*pi/4), right = sin((angle+1)*pi/4)
        left_gain = np.cos((pan_angle + 1) * np.pi / 4).astype(np.float32)
        right_gain = np.sin((pan_angle + 1) * np.pi / 4).astype(np.float32)

        left = signal * left_gain
        right = signal * right_gain

        stereo_input = np.column_stack([left, right])

        # process
        output = pipeline.process_array(stereo_input)

        # analyze widening
        in_mid = (left + right) * 0.5
        in_side = (left - right) * 0.5
        out_mid = (output[:, 0] + output[:, 1]) * 0.5
        out_side = (output[:, 0] - output[:, 1]) * 0.5

        in_ratio = np.sqrt(np.mean(in_side ** 2)) / (np.sqrt(np.mean(in_mid ** 2)) + 1e-10)
        out_ratio = np.sqrt(np.mean(out_side ** 2)) / (np.sqrt(np.mean(out_mid ** 2)) + 1e-10)

        print(f"  Input  S/M ratio: {in_ratio:.3f}")
        print(f"  Output S/M ratio: {out_ratio:.3f}")
        print(f"  Width increase:   {out_ratio / (in_ratio + 1e-10):.1f}x")
        print(f"  Peak output:      {np.max(np.abs(output)):.3f}")
        print(f"  Clipping:         {'NO' if np.max(np.abs(output)) <= 1.0 else 'YES'}")
        print()

        # verify stereo correlation decreased (wider = less correlated)
        in_corr = np.corrcoef(left, right)[0, 1]
        out_corr = np.corrcoef(output[:, 0], output[:, 1])[0, 1]
        print(f"  Input  L/R correlation:  {in_corr:.3f}")
        print(f"  Output L/R correlation:  {out_corr:.3f}")
        print(f"  Decorrelation:           {in_corr - out_corr:.3f}")

        if out_ratio > in_ratio and np.max(np.abs(output)) <= 1.0:
            print("\n  PASS: stereo image widened without clipping")
        else:
            print("\n  ISSUE: check parameters")
    else:
        from dsp_pipeline.stream import AudioStream

        stream = AudioStream(
            input_device=args.input_device,
            output_device=args.output_device,
            samplerate=samplerate,
            blocksize=blocksize,
            channels_in=2,
            channels_out=2,
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
            print(f"Spatial exaggerator running", file=sys.stderr)
            print(f"  ITD gain: {args.itd_gain}x  ILD gain: {args.ild_gain}x  "
                  f"Width: {args.width}x", file=sys.stderr)
            print("  Ctrl-C to stop\n", file=sys.stderr)

            while not stop[0]:
                time.sleep(0.5)
        finally:
            stream.stop()
            signal.signal(signal.SIGINT, old_handler)

    return 0


if __name__ == "__main__":
    sys.exit(main())
