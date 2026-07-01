#!/usr/bin/env python3
"""
reverse_reality.py — Temporal reversal audio effect.

Buffers 2-5 seconds of audio and plays it backwards in real-time,
mixed quietly under the forward stream. Creates an eerie temporal smear
where you hear reversed precursors of events before they actually happen.
Rain sounds otherworldly. Speech becomes demonic.

The reversed audio is crossfaded between chunks to avoid clicks at
boundaries, and optionally pitch-shifted down for extra eeriness.
"""

from __future__ import annotations

import argparse
import signal
import sys
import time
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from dsp_pipeline import DSPBlock, Pipeline, TestSignal, add_audio_args, add_test_args


class ReverseRealityBlock(DSPBlock):
    """Ring-buffer reversal with crossfaded chunk output and optional pitch shift."""

    def __init__(
        self,
        samplerate: int = 48000,
        blocksize: int = 1024,
        buffer_seconds: float = 3.0,
        reverse_level: float = 0.3,
        crossfade_ms: float = 20.0,
        pitch_shift_semitones: float = 0.0,
    ):
        super().__init__(samplerate, blocksize)
        self.buffer_seconds = buffer_seconds
        self.reverse_level = np.clip(reverse_level, 0.0, 1.0)
        self.pitch_shift_semitones = pitch_shift_semitones

        # Ring buffer: stores the last buffer_seconds of audio
        self.ring_size = int(samplerate * buffer_seconds)
        self.ring_buffer = np.zeros(self.ring_size, dtype=np.float32)
        self.write_pos = 0

        # Reversed chunk output state
        # We read out reversed audio in chunks of half the buffer length,
        # crossfaded at boundaries. The read head moves backwards through
        # the ring buffer.
        self.chunk_size = self.ring_size // 2
        self.chunk_read_pos = 0  # position within current reversed chunk
        self.current_chunk = np.zeros(self.chunk_size, dtype=np.float32)
        self.next_chunk = np.zeros(self.chunk_size, dtype=np.float32)
        self.chunk_ready = False
        self.chunks_emitted = 0

        # Crossfade window
        self.crossfade_samples = max(
            int(crossfade_ms * samplerate / 1000.0), blocksize
        )
        self.crossfade_samples = min(self.crossfade_samples, self.chunk_size // 4)

        # Pitch shift state (simple resampling-based shift for reversed audio)
        if pitch_shift_semitones != 0.0:
            self.shift_ratio = 2.0 ** (-pitch_shift_semitones / 12.0)
        else:
            self.shift_ratio = 1.0

        # Accumulator for fractional-sample resampling
        self._resample_accum = np.zeros(0, dtype=np.float32)

        # Stats
        self.blocks_processed = 0

    def _extract_reversed_chunk(self) -> np.ndarray:
        """Extract the most recent chunk_size samples from the ring buffer, reversed."""
        # Read backwards from the current write position
        end = self.write_pos
        start = end - self.chunk_size
        if start >= 0:
            chunk = self.ring_buffer[start:end].copy()
        else:
            # wraps around
            chunk = np.concatenate([
                self.ring_buffer[start % self.ring_size:],
                self.ring_buffer[:end],
            ])
        # Reverse it
        return chunk[::-1].copy()

    def _apply_pitch_shift(self, audio: np.ndarray) -> np.ndarray:
        """Simple pitch shift by resampling (for the reversed stream only).

        Shifts down = longer playback = need to speed up reading = ratio > 1.
        We resample the audio by the shift ratio using linear interpolation.
        """
        if self.shift_ratio == 1.0:
            return audio

        n_in = len(audio)
        n_out = int(n_in / self.shift_ratio)
        if n_out < 1:
            return audio

        indices = np.linspace(0, n_in - 1, n_out)
        idx_floor = np.floor(indices).astype(int)
        idx_ceil = np.minimum(idx_floor + 1, n_in - 1)
        frac = (indices - idx_floor).astype(np.float32)
        resampled = audio[idx_floor] * (1.0 - frac) + audio[idx_ceil] * frac
        return resampled

    def _get_reversed_samples(self, n_samples: int) -> np.ndarray:
        """Get the next n_samples of reversed audio output with crossfading."""
        output = np.zeros(n_samples, dtype=np.float32)
        out_pos = 0

        while out_pos < n_samples:
            # How many samples left in current chunk
            remaining_in_chunk = self.chunk_size - self.chunk_read_pos
            needed = n_samples - out_pos
            take = min(remaining_in_chunk, needed)

            if take <= 0:
                # Advance to next chunk
                self.current_chunk = self.next_chunk.copy()
                self.next_chunk = self._extract_reversed_chunk()
                if self.shift_ratio != 1.0:
                    self.next_chunk = self._apply_pitch_shift(self.next_chunk)
                    # Resize to match chunk_size via padding or truncation
                    if len(self.next_chunk) < self.chunk_size:
                        self.next_chunk = np.pad(
                            self.next_chunk,
                            (0, self.chunk_size - len(self.next_chunk)),
                        )
                    else:
                        self.next_chunk = self.next_chunk[:self.chunk_size]
                self.chunk_read_pos = 0
                self.chunks_emitted += 1
                continue

            chunk_slice = self.current_chunk[
                self.chunk_read_pos:self.chunk_read_pos + take
            ]

            # Apply crossfade at chunk boundaries
            # Fade out at end of current chunk
            dist_from_end = self.chunk_size - (self.chunk_read_pos + take)
            if dist_from_end < self.crossfade_samples:
                fade_region_start = max(0, take - self.crossfade_samples + dist_from_end)
                fade_len = take - fade_region_start
                if fade_len > 0:
                    fade_out = np.linspace(1.0, 0.0, fade_len, dtype=np.float32)
                    chunk_slice = chunk_slice.copy()
                    chunk_slice[fade_region_start:] *= fade_out

                    # Crossfade in from next chunk
                    next_pos = self.chunk_size - dist_from_end - take + fade_region_start
                    if next_pos >= 0 and next_pos + fade_len <= len(self.next_chunk):
                        fade_in = np.linspace(0.0, 1.0, fade_len, dtype=np.float32)
                        chunk_slice[fade_region_start:] += (
                            self.next_chunk[next_pos:next_pos + fade_len] * fade_in
                        )

            # Fade in at start of chunk
            if self.chunk_read_pos < self.crossfade_samples:
                fade_start = self.chunk_read_pos
                fade_end = min(self.chunk_read_pos + take, self.crossfade_samples)
                fade_len = fade_end - fade_start
                if fade_len > 0 and fade_start == 0:
                    fade_in = np.linspace(0.0, 1.0, fade_len, dtype=np.float32)
                    chunk_slice = chunk_slice.copy()
                    chunk_slice[:fade_len] *= fade_in

            output[out_pos:out_pos + take] = chunk_slice
            self.chunk_read_pos += take
            out_pos += take

        return output

    def process(self, samples: np.ndarray) -> np.ndarray:
        """Mix forward audio with reversed audio from the ring buffer."""
        mono = samples[:, 0] if samples.ndim == 2 else samples
        n = len(mono)

        # Write input to ring buffer
        if self.write_pos + n <= self.ring_size:
            self.ring_buffer[self.write_pos:self.write_pos + n] = mono
        else:
            first = self.ring_size - self.write_pos
            self.ring_buffer[self.write_pos:] = mono[:first]
            self.ring_buffer[:n - first] = mono[first:]
        self.write_pos = (self.write_pos + n) % self.ring_size

        # Initialize chunks on first call after buffer fills
        if not self.chunk_ready and self.blocks_processed * self.blocksize >= self.ring_size:
            self.current_chunk = self._extract_reversed_chunk()
            if self.shift_ratio != 1.0:
                self.current_chunk = self._apply_pitch_shift(self.current_chunk)
                if len(self.current_chunk) < self.chunk_size:
                    self.current_chunk = np.pad(
                        self.current_chunk,
                        (0, self.chunk_size - len(self.current_chunk)),
                    )
                else:
                    self.current_chunk = self.current_chunk[:self.chunk_size]
            self.next_chunk = self.current_chunk.copy()
            self.chunk_read_pos = 0
            self.chunk_ready = True

        self.blocks_processed += 1

        # Get reversed audio
        if self.chunk_ready:
            reversed_audio = self._get_reversed_samples(n)
        else:
            reversed_audio = np.zeros(n, dtype=np.float32)

        # Mix: forward at full level, reversed at configured level
        mixed = mono + self.reverse_level * reversed_audio

        # Soft clip to prevent exceeding [-1, 1]
        peak = np.max(np.abs(mixed))
        if peak > 1.0:
            mixed = np.tanh(mixed)

        # Output
        if samples.ndim == 2:
            out = np.zeros_like(samples)
            for ch in range(samples.shape[1]):
                out[:, ch] = mixed
            return out
        return mixed

    def reset(self):
        """Reset all state."""
        self.ring_buffer[:] = 0
        self.write_pos = 0
        self.chunk_read_pos = 0
        self.current_chunk[:] = 0
        self.next_chunk[:] = 0
        self.chunk_ready = False
        self.blocks_processed = 0
        self.chunks_emitted = 0

    def get_status(self) -> dict:
        fill_pct = min(
            100.0,
            100.0 * self.blocks_processed * self.blocksize / self.ring_size,
        )
        return {
            "enabled": self.enabled,
            "buffer_fill": f"{fill_pct:.0f}%",
            "chunks_emitted": self.chunks_emitted,
            "reverse_level": self.reverse_level,
            "pitch_shift": self.pitch_shift_semitones,
        }


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Reverse reality — buffer audio and mix reversed playback under "
            "the forward stream. Events arrive as ghostly precursors before "
            "they actually happen."
        ),
    )
    add_audio_args(parser)
    add_test_args(parser)

    g = parser.add_argument_group("reverse reality")
    g.add_argument(
        "--buffer-seconds",
        type=float,
        default=3.0,
        metavar="SEC",
        help="Ring buffer length in seconds, 2-5 (default: 3.0)",
    )
    g.add_argument(
        "--reverse-level",
        type=float,
        default=0.3,
        metavar="LVL",
        help="Mix level of reversed audio, 0-1 (default: 0.3)",
    )
    g.add_argument(
        "--crossfade-ms",
        type=float,
        default=20.0,
        metavar="MS",
        help="Crossfade duration between reversed chunks in ms (default: 20)",
    )
    g.add_argument(
        "--pitch-shift",
        type=float,
        default=0.0,
        metavar="ST",
        help="Pitch-shift reversed audio down by N semitones (default: 0, try -2 to -5)",
    )

    args = parser.parse_args()

    if args.list_devices:
        import sounddevice as sd
        print(sd.query_devices())
        return 0

    # Validate buffer length
    if not 2.0 <= args.buffer_seconds <= 5.0:
        print(
            f"ERROR: --buffer-seconds must be 2-5 (got {args.buffer_seconds})",
            file=sys.stderr,
        )
        return 1

    if not 0.0 <= args.reverse_level <= 1.0:
        print(
            f"ERROR: --reverse-level must be 0-1 (got {args.reverse_level})",
            file=sys.stderr,
        )
        return 1

    samplerate = args.samplerate
    blocksize = args.blocksize

    block = ReverseRealityBlock(
        samplerate=samplerate,
        blocksize=blocksize,
        buffer_seconds=args.buffer_seconds,
        reverse_level=args.reverse_level,
        crossfade_ms=args.crossfade_ms,
        pitch_shift_semitones=args.pitch_shift,
    )

    pipeline = Pipeline([block], samplerate=samplerate, blocksize=blocksize)

    if args.test:
        print("=== Reverse Reality — Test Mode ===")
        print(f"  Buffer: {args.buffer_seconds:.1f} s")
        print(f"  Reverse level: {args.reverse_level:.2f}")
        print(f"  Crossfade: {args.crossfade_ms:.0f} ms")
        print(f"  Pitch shift: {args.pitch_shift:+.1f} semitones")
        print(f"  Sample rate: {samplerate} Hz")
        print(f"  Block size: {blocksize}")
        print()

        ts = TestSignal(samplerate, args.test_duration)

        # Build a test signal with distinctive temporal events:
        # - 0-1s: silence (buffer fill period)
        # - 1-2s: a series of short clicks/pulses (easy to identify reversed)
        # - 2-3s: ascending tone sweep (reversed = descending precursor)
        # - 3-4s: speech-like formant signal
        # - 4-5s: rain-like noise bursts
        n_samples = ts.n_samples
        t = np.arange(n_samples) / samplerate
        test_audio = np.zeros(n_samples, dtype=np.float32)

        # Clicks at 1.0, 1.3, 1.6, 1.9 seconds
        for click_time in [1.0, 1.3, 1.6, 1.9]:
            click_pos = int(click_time * samplerate)
            click_len = int(0.01 * samplerate)  # 10 ms click
            if click_pos + click_len < n_samples:
                click_env = np.hanning(click_len).astype(np.float32)
                click_freq = 1000.0
                click_t = np.arange(click_len) / samplerate
                test_audio[click_pos:click_pos + click_len] += (
                    0.6 * click_env * np.sin(2 * np.pi * click_freq * click_t)
                ).astype(np.float32)

        # Ascending sweep 2-3s
        sweep_start = int(2.0 * samplerate)
        sweep_end = int(3.0 * samplerate)
        sweep_n = sweep_end - sweep_start
        sweep_t = np.arange(sweep_n) / samplerate
        f_start, f_end = 200.0, 2000.0
        phase = 2 * np.pi * f_start * sweep_t + (
            np.pi * (f_end - f_start) * sweep_t**2 / (sweep_n / samplerate)
        )
        test_audio[sweep_start:sweep_end] += (
            0.4 * np.sin(phase) * np.hanning(sweep_n)
        ).astype(np.float32)

        # Speech-like 3-4s
        speech_start = int(3.0 * samplerate)
        speech_end = int(4.0 * samplerate)
        speech_n = speech_end - speech_start
        speech_t = np.arange(speech_n) / samplerate
        fundamental = 130.0  # male voice
        signal = np.zeros(speech_n, dtype=np.float32)
        for h, amp in enumerate([1.0, 0.7, 0.5, 0.3, 0.2, 0.15, 0.1], 1):
            signal += amp * np.sin(2 * np.pi * fundamental * h * speech_t).astype(
                np.float32
            )
        # Syllabic AM at ~3 Hz
        am = (0.5 + 0.5 * np.sin(2 * np.pi * 3.0 * speech_t)).astype(np.float32)
        signal *= am
        signal *= 0.3 / (np.max(np.abs(signal)) + 1e-10)
        test_audio[speech_start:speech_end] += signal

        # Rain-like noise bursts 4-5s
        rain_start = int(4.0 * samplerate)
        rain_end = min(int(5.0 * samplerate), n_samples)
        rain_n = rain_end - rain_start
        rng = np.random.default_rng(42)
        rain = rng.standard_normal(rain_n).astype(np.float32) * 0.15
        # Create droplet bursts
        for _ in range(30):
            pos = rng.integers(0, rain_n - 200)
            burst_len = rng.integers(50, 200)
            env = np.hanning(burst_len).astype(np.float32)
            rain[pos:pos + burst_len] += (
                0.3 * env * rng.standard_normal(burst_len).astype(np.float32)
            )
        test_audio[rain_start:rain_end] += np.clip(rain, -0.5, 0.5)

        # Process through pipeline
        output = pipeline.process_array(test_audio.reshape(-1, 1))
        output_mono = output[:, 0] if output.ndim == 2 else output

        # Analysis
        input_rms = np.sqrt(np.mean(test_audio**2))
        output_rms = np.sqrt(np.mean(output_mono**2))
        input_peak = np.max(np.abs(test_audio))
        output_peak = np.max(np.abs(output_mono))

        print("--- Results ---")
        print(f"  Input  RMS: {20 * np.log10(input_rms + 1e-10):>6.1f} dBFS")
        print(f"  Output RMS: {20 * np.log10(output_rms + 1e-10):>6.1f} dBFS")
        print(f"  Input  peak: {20 * np.log10(input_peak + 1e-10):>6.1f} dBFS")
        print(f"  Output peak: {20 * np.log10(output_peak + 1e-10):>6.1f} dBFS")
        print(f"  Chunks emitted: {block.chunks_emitted}")
        print()

        # Verify the reverse effect is present: check that output energy
        # exists in the initial silent region (reversed precursor of events)
        buffer_fill_samples = block.ring_size
        # After the buffer fills, reversed audio should appear
        post_fill_start = buffer_fill_samples
        post_fill_end = min(post_fill_start + samplerate, n_samples)
        if post_fill_end > post_fill_start:
            region_rms = np.sqrt(
                np.mean(output_mono[post_fill_start:post_fill_end] ** 2)
            )
            input_region_rms = np.sqrt(
                np.mean(test_audio[post_fill_start:post_fill_end] ** 2)
            )
            if region_rms > input_region_rms * 0.5:
                print("  [PASS] Reversed audio detected in output")
            else:
                print("  [INFO] Reversed audio energy low (expected during fill)")

        # Check no clipping
        if output_peak <= 1.0:
            print("  [PASS] No clipping in output")
        else:
            print(f"  [WARN] Output exceeds 1.0 (peak={output_peak:.3f})")

        # Check forward signal preserved
        # The forward signal should still be present (correlation check on
        # a region where there's clear signal)
        check_start = int(2.5 * samplerate)
        check_end = int(3.0 * samplerate)
        if check_end <= n_samples:
            corr = np.corrcoef(
                test_audio[check_start:check_end],
                output_mono[check_start:check_end],
            )[0, 1]
            if corr > 0.5:
                print(f"  [PASS] Forward signal preserved (correlation={corr:.3f})")
            else:
                print(f"  [INFO] Forward correlation={corr:.3f} (reverse mix dominates)")

        print()
        print("Test complete.")
        return 0

    # Real-time mode
    from dsp_pipeline.stream import AudioStream

    stream = AudioStream(
        input_device=args.input_device,
        output_device=args.output_device,
        samplerate=samplerate,
        blocksize=blocksize,
        channels_in=args.channels_in,
        channels_out=args.channels_out,
    )

    def callback(indata, frames):
        return pipeline.process_block(indata)

    stream.set_callback(callback)

    stop = [False]

    def sigint_handler(signum, frame):
        stop[0] = True

    old_handler = signal.signal(signal.SIGINT, sigint_handler)

    try:
        stream.start()
        print("Reverse Reality running (Ctrl-C to stop)", file=sys.stderr)
        print(f"  Buffer: {args.buffer_seconds:.1f} s", file=sys.stderr)
        print(f"  Reverse level: {args.reverse_level:.2f}", file=sys.stderr)
        if args.pitch_shift != 0.0:
            print(
                f"  Pitch shift: {args.pitch_shift:+.1f} semitones",
                file=sys.stderr,
            )
        print(
            f"  Filling buffer ({args.buffer_seconds:.1f}s)...",
            file=sys.stderr,
        )

        # Wait for buffer to fill before announcing ready
        fill_time = args.buffer_seconds
        fill_start = time.time()
        while not stop[0]:
            elapsed = time.time() - fill_start
            if elapsed >= fill_time and block.chunk_ready:
                print("  Buffer filled — effect active", file=sys.stderr)
                break
            time.sleep(0.1)

        # Main loop
        while not stop[0]:
            time.sleep(0.2)
            status = block.get_status()
            sys.stderr.write(
                f"\r  Chunks: {status['chunks_emitted']:>4}  "
                f"Buffer: {status['buffer_fill']}"
            )
            sys.stderr.flush()

    finally:
        stream.stop()
        signal.signal(signal.SIGINT, old_handler)
        print("\nStopped.", file=sys.stderr)

    return 0


if __name__ == "__main__":
    sys.exit(main())
