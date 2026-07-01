#!/usr/bin/env python3
"""
triggered_recorder.py — Triggered audio recorder.

Continuously buffers the last N seconds in a ring buffer. When signal
is detected (level threshold trigger), saves pre-trigger + post-trigger
audio to a WAV/FLAC file with UTC timestamp filename.

Automatically captures interesting signals without recording hours of
dead air.
"""

from __future__ import annotations

import argparse
import sys
import time
import threading
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import soundfile as sf

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from dsp_pipeline import DSPBlock, TestSignal, add_audio_args, add_test_args
from dsp_pipeline.stream import AudioStream


class SileroVADTrigger:
    """Silero VAD wrapper for speech-triggered recording."""

    def __init__(self, samplerate: int, threshold: float = 0.5,
                 min_speech_ms: float = 200.0):
        import torch
        from silero_vad import load_silero_vad
        self._torch = torch
        self._model = load_silero_vad(onnx=True)
        self._vad_rate = 16000
        self._vad_chunk = 512  # 32ms at 16kHz
        self._vad_buf = np.zeros(0, dtype=np.float32)
        self._threshold = threshold
        self._min_speech_frames = max(1, int(min_speech_ms / 32.0))
        self._consecutive_speech = 0
        self._samplerate = samplerate
        self._active = False

    def _downsample_16k(self, samples: np.ndarray) -> np.ndarray:
        ratio = 16000 / self._samplerate
        n_out = int(len(samples) * ratio)
        if n_out == 0:
            return np.zeros(0, dtype=np.float32)
        indices = np.linspace(0, len(samples) - 1, n_out).astype(int)
        return samples[indices]

    def is_triggered(self, mono: np.ndarray) -> bool:
        """Returns True if sustained speech detected in this block."""
        vad_audio = self._downsample_16k(mono)
        self._vad_buf = np.concatenate([self._vad_buf, vad_audio])

        frame_results = []
        while len(self._vad_buf) >= self._vad_chunk:
            chunk = self._vad_buf[:self._vad_chunk]
            self._vad_buf = self._vad_buf[self._vad_chunk:]
            chunk_t = self._torch.from_numpy(chunk)
            prob = self._model(chunk_t, self._vad_rate).item()
            frame_results.append(prob >= self._threshold)

        if not frame_results:
            return self._active

        if all(frame_results):
            self._consecutive_speech += len(frame_results)
        else:
            self._consecutive_speech = 0

        self._active = self._consecutive_speech >= self._min_speech_frames
        return self._active

    def reset(self):
        self._vad_buf = np.zeros(0, dtype=np.float32)
        self._consecutive_speech = 0
        self._active = False
        self._model.reset_states()


class TriggerDetector(DSPBlock):
    """Level-based trigger with pre-trigger ring buffer and post-trigger hang.
    Optionally uses Silero VAD for speech-only triggering."""

    def __init__(self, samplerate: int = 48000, blocksize: int = 1024,
                 threshold_db: float = -30.0, pre_trigger_s: float = 3.0,
                 post_trigger_s: float = 5.0, vad: bool = False,
                 vad_threshold: float = 0.5, vad_min_speech_ms: float = 200.0):
        super().__init__(samplerate, blocksize)
        self.threshold = 10 ** (threshold_db / 20.0)
        self.threshold_db = threshold_db
        self.pre_trigger_s = pre_trigger_s
        self.post_trigger_s = post_trigger_s

        # optional VAD trigger
        self._vad = None
        if vad:
            self._vad = SileroVADTrigger(
                samplerate=samplerate,
                threshold=vad_threshold,
                min_speech_ms=vad_min_speech_ms,
            )

        # ring buffer: stores pre_trigger_s worth of audio blocks
        self._ring_capacity = int(np.ceil(pre_trigger_s * samplerate / blocksize))
        self._ring: list[np.ndarray] = []
        self._ring_pos = 0

        # state
        self._triggered = False
        self._hang_remaining = 0  # blocks remaining in post-trigger
        self._recording_blocks: list[np.ndarray] = []
        self._peak_db = -120.0

        # completed recordings ready for writing
        self._completed: list[tuple[np.ndarray, float]] = []
        self._lock = threading.Lock()

    def _push_ring(self, block: np.ndarray):
        """Push a block into the ring buffer."""
        if len(self._ring) < self._ring_capacity:
            self._ring.append(block.copy())
        else:
            self._ring[self._ring_pos] = block.copy()
        self._ring_pos = (self._ring_pos + 1) % max(self._ring_capacity, 1)

    def _drain_ring(self) -> list[np.ndarray]:
        """Get ring buffer contents in order (oldest first)."""
        if len(self._ring) < self._ring_capacity:
            return [b.copy() for b in self._ring]
        # ring is full, read from current pos (oldest) onwards
        ordered = []
        for i in range(len(self._ring)):
            idx = (self._ring_pos + i) % len(self._ring)
            ordered.append(self._ring[idx].copy())
        return ordered

    def process(self, samples: np.ndarray) -> np.ndarray:
        mono = samples[:, 0] if samples.ndim == 2 else samples

        # compute peak level
        peak = np.max(np.abs(mono))
        peak_db = 20 * np.log10(peak + 1e-10)
        self._peak_db = float(peak_db)

        if self._vad is not None:
            above = self._vad.is_triggered(mono)
        else:
            above = peak > self.threshold

        if not self._triggered:
            if above:
                # trigger fires: capture ring buffer as pre-trigger
                self._triggered = True
                self._recording_blocks = self._drain_ring()
                self._recording_blocks.append(mono.copy())
                self._hang_remaining = int(np.ceil(
                    self.post_trigger_s * self.samplerate / self.blocksize))
            else:
                # no trigger: push to ring buffer
                self._push_ring(mono)
        else:
            # currently recording
            self._recording_blocks.append(mono.copy())
            if above:
                # re-trigger: reset hang timer
                self._hang_remaining = int(np.ceil(
                    self.post_trigger_s * self.samplerate / self.blocksize))
            else:
                self._hang_remaining -= 1
                if self._hang_remaining <= 0:
                    # hang expired: finalize recording
                    audio = np.concatenate(self._recording_blocks)
                    trigger_time = time.time() - (
                        len(self._recording_blocks) * self.blocksize / self.samplerate)
                    with self._lock:
                        self._completed.append((audio, trigger_time))
                    self._recording_blocks = []
                    self._triggered = False
                    # reset ring buffer
                    self._ring = []
                    self._ring_pos = 0

        return samples

    def pop_completed(self) -> list[tuple[np.ndarray, float]]:
        """Pop completed recordings (thread-safe)."""
        with self._lock:
            result = self._completed
            self._completed = []
        return result

    def flush(self) -> np.ndarray | None:
        """Flush any in-progress recording (call at shutdown)."""
        if self._triggered and self._recording_blocks:
            audio = np.concatenate(self._recording_blocks)
            self._recording_blocks = []
            self._triggered = False
            return audio
        return None

    def reset(self):
        self._ring = []
        self._ring_pos = 0
        self._triggered = False
        self._hang_remaining = 0
        self._recording_blocks = []
        with self._lock:
            self._completed = []

    def get_status(self) -> dict:
        return {
            "enabled": self.enabled,
            "triggered": self._triggered,
            "peak_db": f"{self._peak_db:.1f}",
            "threshold_db": f"{self.threshold_db:.1f}",
            "ring_fill": f"{len(self._ring)}/{self._ring_capacity}",
            "recording_s": f"{len(self._recording_blocks) * self.blocksize / self.samplerate:.1f}"
            if self._triggered else "0.0",
        }


def make_filename(trigger_time: float, output_dir: Path, label: str,
                  fmt: str) -> Path:
    """Generate UTC timestamp filename. Adds fractional seconds if needed to avoid collision."""
    dt = datetime.fromtimestamp(trigger_time, tz=timezone.utc)
    name = dt.strftime("%Y%m%d_%H%M%S")
    if label:
        name = f"{name}_{label}"
    path = output_dir / f"{name}.{fmt}"
    if path.exists():
        # add fractional seconds to disambiguate
        frac = f"{trigger_time % 1:.2f}"[1:]  # e.g. ".37"
        name_frac = dt.strftime("%Y%m%d_%H%M%S") + frac
        if label:
            name_frac = f"{name_frac}_{label}"
        path = output_dir / f"{name_frac}.{fmt}"
    return path


def write_recording(audio: np.ndarray, path: Path, samplerate: int,
                    fmt: str):
    """Write audio to WAV or FLAC."""
    subtype = "PCM_16" if fmt == "wav" else "PCM_16"
    sf.write(str(path), audio, samplerate, subtype=subtype,
             format=fmt.upper())


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Triggered audio recorder. Continuously buffers audio; "
                    "saves pre+post-trigger segments when signal is detected.")
    add_audio_args(parser, duplex=False)
    add_test_args(parser)
    parser.add_argument("--threshold-db", type=float, default=-30.0,
                        help="Trigger threshold in dBFS (default -30)")
    parser.add_argument("--pre-trigger", type=float, default=3.0, metavar="SEC",
                        help="Pre-trigger buffer length in seconds (1-30, default 3)")
    parser.add_argument("--post-trigger", type=float, default=5.0, metavar="SEC",
                        help="Post-trigger hang time in seconds (1-60, default 5)")
    parser.add_argument("--format", choices=["wav", "flac"], default="wav",
                        help="Output format (default wav)")
    parser.add_argument("--output-dir", type=str, default=".",
                        help="Output directory for recordings (default '.')")
    parser.add_argument("--label", type=str, default="",
                        help="Optional label appended to filenames")
    parser.add_argument("--vad", action="store_true",
                        help="Use Silero VAD (neural net) for speech-only triggering "
                             "instead of level threshold")
    parser.add_argument("--vad-threshold", type=float, default=0.5,
                        help="VAD speech probability threshold 0-1 (default 0.5)")
    parser.add_argument("--vad-min-speech-ms", type=float, default=200.0,
                        help="Minimum consecutive speech before triggering (default 200 ms)")
    args = parser.parse_args()

    if args.list_devices:
        from dsp_pipeline.args import open_stream_from_args
        open_stream_from_args(args, duplex=False)
        return 0

    # validate ranges
    args.pre_trigger = max(1.0, min(30.0, args.pre_trigger))
    args.post_trigger = max(1.0, min(60.0, args.post_trigger))

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    block = TriggerDetector(
        samplerate=args.samplerate,
        blocksize=args.blocksize,
        threshold_db=args.threshold_db,
        pre_trigger_s=args.pre_trigger,
        post_trigger_s=args.post_trigger,
        vad=args.vad,
        vad_threshold=args.vad_threshold,
        vad_min_speech_ms=args.vad_min_speech_ms,
    )

    if args.test:
        # generate test signal: silence, burst, silence, burst, silence
        ts = TestSignal(args.samplerate, args.test_duration)
        n = args.samplerate  # 1 second in samples

        silence1 = np.zeros(n * 2, dtype=np.float32)  # 2s silence
        burst1 = 0.3 * np.sin(
            2 * np.pi * 1000 * np.arange(n) / args.samplerate
        ).astype(np.float32)  # 1s tone burst
        silence2 = np.zeros(n * 3, dtype=np.float32)  # 3s gap
        burst2 = 0.4 * np.sin(
            2 * np.pi * 800 * np.arange(int(n * 0.5)) / args.samplerate
        ).astype(np.float32)  # 0.5s tone burst
        silence3 = np.zeros(n * 2, dtype=np.float32)  # 2s silence

        test_audio = np.concatenate([silence1, burst1, silence2, burst2, silence3])
        print(f"Test signal: {len(test_audio)/args.samplerate:.1f}s total")
        print(f"  0-2s: silence")
        print(f"  2-3s: 1 kHz burst at -10.5 dBFS")
        print(f"  3-6s: silence")
        print(f"  6-6.5s: 800 Hz burst at -8 dBFS")
        print(f"  6.5-8.5s: silence")
        print(f"Threshold: {args.threshold_db} dBFS")
        print(f"Pre-trigger: {args.pre_trigger}s, Post-trigger: {args.post_trigger}s")
        print()

        # process through the block
        captures = 0
        for start in range(0, len(test_audio), args.blocksize):
            chunk = test_audio[start:start + args.blocksize]
            if len(chunk) < args.blocksize:
                chunk = np.pad(chunk, (0, args.blocksize - len(chunk)))
            block.process(chunk.reshape(-1, 1))

            for audio, trigger_time in block.pop_completed():
                captures += 1
                duration = len(audio) / args.samplerate
                peak_db = 20 * np.log10(np.max(np.abs(audio)) + 1e-10)
                path = make_filename(trigger_time, output_dir, args.label,
                                     args.format)
                write_recording(audio, path, args.samplerate, args.format)
                print(f"  CAPTURE {captures}: {path.name} "
                      f"({duration:.2f}s, peak {peak_db:.1f} dBFS)")

        # flush any in-progress recording
        remaining = block.flush()
        if remaining is not None:
            captures += 1
            duration = len(remaining) / args.samplerate
            peak_db = 20 * np.log10(np.max(np.abs(remaining)) + 1e-10)
            path = make_filename(time.time(), output_dir, args.label, args.format)
            write_recording(remaining, path, args.samplerate, args.format)
            print(f"  CAPTURE {captures}: {path.name} "
                  f"({duration:.2f}s, peak {peak_db:.1f} dBFS) [flushed]")

        print(f"\nTotal captures: {captures}")
    else:
        import signal as sig_module

        stream = AudioStream(
            input_device=args.input_device,
            samplerate=args.samplerate,
            blocksize=args.blocksize,
            channels_in=args.channels_in,
        )

        captures = [0]

        def callback(indata, frames):
            block.process(indata)
            # check for completed recordings
            for audio, trigger_time in block.pop_completed():
                captures[0] += 1
                duration = len(audio) / args.samplerate
                peak_db = 20 * np.log10(np.max(np.abs(audio)) + 1e-10)
                path = make_filename(trigger_time, output_dir, args.label,
                                     args.format)
                write_recording(audio, path, args.samplerate, args.format)
                print(f"\n  CAPTURE {captures[0]}: {path.name} "
                      f"({duration:.2f}s, peak {peak_db:.1f} dBFS)")
            return None

        stream.set_callback(callback)
        stop = [False]

        def handler(s, f):
            stop[0] = True
        old = sig_module.signal(sig_module.SIGINT, handler)

        try:
            stream.start()
            print(f"Triggered recorder running", file=sys.stderr)
            if args.vad:
                print(f"  Trigger: Silero VAD (threshold={args.vad_threshold}, "
                      f"min_speech={args.vad_min_speech_ms} ms)", file=sys.stderr)
            else:
                print(f"  Trigger: level threshold {args.threshold_db} dBFS",
                      file=sys.stderr)
            print(f"  Pre-trigger: {args.pre_trigger}s", file=sys.stderr)
            print(f"  Post-trigger: {args.post_trigger}s", file=sys.stderr)
            print(f"  Format: {args.format}", file=sys.stderr)
            print(f"  Output: {output_dir.resolve()}", file=sys.stderr)
            print("Ctrl-C to stop.", file=sys.stderr)
            while not stop[0]:
                time.sleep(0.25)
                status = block.get_status()
                state = "REC " if block._triggered else "WAIT"
                line = (f"[{state}] peak={status['peak_db']} dBFS  "
                        f"ring={status['ring_fill']}  "
                        f"captures={captures[0]}")
                if block._triggered:
                    line += f"  rec={status['recording_s']}s"
                print(f"\r{line:<72}", end="", flush=True)
        finally:
            stream.stop()
            sig_module.signal(sig_module.SIGINT, old)
            # flush in-progress recording
            remaining = block.flush()
            if remaining is not None:
                captures[0] += 1
                duration = len(remaining) / args.samplerate
                path = make_filename(time.time(), output_dir, args.label,
                                     args.format)
                write_recording(remaining, path, args.samplerate, args.format)
                print(f"\n  CAPTURE {captures[0]}: {path.name} "
                      f"({duration:.2f}s) [flushed at shutdown]")
            print(f"\nTotal captures: {captures[0]}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
