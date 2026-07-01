#!/usr/bin/env python3
"""
vad_squelch.py — Voice Activity Detection squelch.

Audio-domain squelch that opens ONLY for human speech — ignores data
bursts, SSTV, RTTY, CW, pager signals, typing, and noise. Uses Silero
VAD (ONNX neural net) with a delay line to avoid clipping word onsets.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np
import torch
from silero_vad import load_silero_vad

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from dsp_pipeline import DSPBlock, Pipeline, TestSignal, add_audio_args, add_test_args


class VADSquelch(DSPBlock):
    """Voice activity detection squelch using Silero VAD."""

    def __init__(self, samplerate: int = 48000, blocksize: int = 1024,
                 threshold: float = 0.5, hang_ms: float = 300.0,
                 attack_ms: float = 5.0, release_ms: float = 30.0,
                 min_speech_ms: float = 200.0, floor_db: float = -45.0,
                 lookahead_ms: float = 250.0, debug: bool = False):
        super().__init__(samplerate, blocksize)
        self.threshold = threshold
        self.hang_samples = int(hang_ms * samplerate / 1000)
        self._debug = debug
        self._floor_db = floor_db

        # per-block gate smoothing
        attack_blocks = (attack_ms * samplerate / 1000) / blocksize
        release_blocks = (release_ms * samplerate / 1000) / blocksize
        self.attack_coeff = 1.0 - np.exp(-1.0 / max(attack_blocks, 0.1))
        self.release_coeff = 1.0 - np.exp(-1.0 / max(release_blocks, 0.1))
        self._hang_counter = 0
        self._gate_level = 0.0
        self._is_open = False
        self._speech_detected = False

        # Silero VAD: expects 16kHz, 512-sample chunks
        self._model = load_silero_vad(onnx=True)
        self._vad_rate = 16000
        self._vad_chunk = 512  # 32ms at 16kHz
        self._vad_buf = np.zeros(0, dtype=np.float32)

        # consecutive-frame tracking
        self._min_speech_frames = max(1, int(min_speech_ms / 32.0))
        self._consecutive_speech = 0
        self._last_prob = 0.0

        # delay line
        self._delay_samples = int(lookahead_ms * samplerate / 1000)
        self._delay_buf = np.zeros(self._delay_samples, dtype=np.float32)

    def _downsample_16k(self, samples: np.ndarray) -> np.ndarray:
        """Downsample to 16kHz."""
        ratio = 16000 / self.samplerate
        n_out = int(len(samples) * ratio)
        if n_out == 0:
            return np.zeros(0, dtype=np.float32)
        indices = np.linspace(0, len(samples) - 1, n_out).astype(int)
        return samples[indices]

    def _run_vad(self, mono: np.ndarray) -> bool:
        """Run Silero VAD. Returns True only after sustained speech."""
        rms = np.sqrt(np.mean(mono ** 2))
        level_db = 20.0 * np.log10(rms + 1e-10)
        if level_db < self._floor_db:
            self._consecutive_speech = 0
            if self._debug:
                print(f"  [vad] energy={level_db:.0f}dB < floor → silence",
                      file=sys.stderr)
            return False

        vad_audio = self._downsample_16k(mono)
        self._vad_buf = np.concatenate([self._vad_buf, vad_audio])

        frame_results = []

        while len(self._vad_buf) >= self._vad_chunk:
            chunk = self._vad_buf[:self._vad_chunk]
            self._vad_buf = self._vad_buf[self._vad_chunk:]

            chunk_t = torch.from_numpy(chunk)
            prob = self._model(chunk_t, self._vad_rate).item()
            self._last_prob = prob
            frame_results.append(prob >= self.threshold)

        if not frame_results:
            return self._speech_detected

        if all(frame_results):
            self._consecutive_speech += len(frame_results)
        else:
            self._consecutive_speech = 0

        result = self._consecutive_speech >= self._min_speech_frames

        if self._debug:
            print(f"  [vad] energy={level_db:.0f}dB prob={self._last_prob:.2f} "
                  f"consec={self._consecutive_speech}/{self._min_speech_frames} → {result}",
                  file=sys.stderr)

        return result

    def _push_delay(self, mono: np.ndarray) -> np.ndarray:
        """Push new audio into delay line, return delayed audio."""
        n = len(mono)
        output = self._delay_buf[:n].copy()
        self._delay_buf[:-n] = self._delay_buf[n:]
        self._delay_buf[-n:] = mono
        return output

    def process(self, samples: np.ndarray) -> np.ndarray:
        mono = samples[:, 0] if samples.ndim == 2 else samples

        self._speech_detected = self._run_vad(mono)
        delayed = self._push_delay(mono)

        if self._speech_detected:
            self._is_open = True
            self._hang_counter = self.hang_samples
        elif self._hang_counter > 0:
            self._hang_counter -= len(mono)
        else:
            self._is_open = False

        target = 1.0 if self._is_open else 0.0
        coeff = self.attack_coeff if target > self._gate_level else self.release_coeff
        self._gate_level += coeff * (target - self._gate_level)

        output = delayed * self._gate_level

        if samples.ndim == 2:
            return output.reshape(-1, 1).repeat(samples.shape[1], axis=1)
        return output

    def reset(self):
        self._hang_counter = 0
        self._gate_level = 0.0
        self._is_open = False
        self._speech_detected = False
        self._vad_buf = np.zeros(0, dtype=np.float32)
        self._consecutive_speech = 0
        self._delay_buf = np.zeros(self._delay_samples, dtype=np.float32)
        self._model.reset_states()

    def get_status(self) -> dict:
        return {
            "enabled": self.enabled,
            "open": self._is_open,
            "speech": self._speech_detected,
            "gate_level": f"{self._gate_level:.2f}",
            "prob": f"{self._last_prob:.2f}",
            "consec_speech": self._consecutive_speech,
        }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Voice activity detection squelch (Silero VAD).")
    add_audio_args(parser)
    add_test_args(parser)
    parser.add_argument("--threshold", type=float, default=0.5,
                        help="Speech probability threshold 0-1 (default 0.5)")
    parser.add_argument("--hang-ms", type=float, default=300.0,
                        help="Squelch hang time in ms (default 300)")
    parser.add_argument("--attack-ms", type=float, default=5.0,
                        help="Gate attack time in ms (default 5)")
    parser.add_argument("--release-ms", type=float, default=30.0,
                        help="Gate release time in ms (default 30)")
    parser.add_argument("--min-speech-ms", type=float, default=200.0,
                        help="Minimum consecutive speech before opening (default 200 ms)")
    parser.add_argument("--lookahead-ms", type=float, default=250.0,
                        help="Delay line length in ms (default 250)")
    parser.add_argument("--floor-db", type=float, default=-45.0,
                        help="Energy floor in dB (default -45)")
    parser.add_argument("--debug", action="store_true",
                        help="Print VAD decisions to stderr")
    parser.add_argument("--output", metavar="WAV",
                        help="Write gated output to WAV (test mode)")
    args = parser.parse_args()

    if args.list_devices:
        from dsp_pipeline.args import open_stream_from_args
        open_stream_from_args(args)
        return 0

    block = VADSquelch(
        samplerate=args.samplerate,
        blocksize=args.blocksize,
        threshold=args.threshold,
        hang_ms=args.hang_ms,
        attack_ms=args.attack_ms,
        release_ms=args.release_ms,
        min_speech_ms=args.min_speech_ms,
        lookahead_ms=args.lookahead_ms,
        floor_db=args.floor_db,
        debug=args.debug,
    )
    pipeline = Pipeline([block], samplerate=args.samplerate, blocksize=args.blocksize)

    if args.test:
        ts = TestSignal(args.samplerate, args.test_duration)
        speech = ts.speech_like(amplitude=0.4)
        cw = ts.cw_signal(freq=700, wpm=20, amplitude=0.3, noise_amplitude=0)
        noise = ts.noise(amplitude=0.15)
        n = args.samplerate
        test_audio = np.concatenate([
            speech[:2*n],
            cw[:n],
            noise[:n],
            speech[2*n:3*n],
        ])

        processed = pipeline.process_array(test_audio.reshape(-1, 1))
        speech_energy = np.mean(processed[:2*n]**2)
        nonspeech_energy = np.mean(processed[2*n:4*n]**2)
        print(f"Speech segment energy: {10*np.log10(speech_energy+1e-10):.1f} dB")
        print(f"Non-speech segment energy: {10*np.log10(nonspeech_energy+1e-10):.1f} dB")
        print(f"Rejection: {10*np.log10(speech_energy/(nonspeech_energy+1e-10)):.1f} dB")
        print(f"Latency: {args.lookahead_ms:.0f} ms")

        if args.output:
            import soundfile as sf
            sf.write(args.output, processed, args.samplerate)
            print(f"Wrote {args.output}")
    else:
        print(f"VAD squelch (Silero): threshold={args.threshold}, "
              f"min_speech={args.min_speech_ms} ms, hang={args.hang_ms} ms, "
              f"lookahead={args.lookahead_ms} ms",
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
