#!/usr/bin/env python3
"""
bird_time_stretch.py — Bird song time-stretcher.

Buffers audio and replays it time-stretched (slower) without pitch shift,
using a phase vocoder. Reveals micro-structure in bird calls, insect
sounds, and any fast transient audio that's too rapid for human
perception at normal speed.

Operation modes:
- Continuous: real-time stretch (output is always behind input)
- Triggered: buffer last N seconds, replay stretched on key/threshold
- Capture: record to file, stretch offline, save result
"""

from __future__ import annotations

import argparse
import signal as sig_module
import sys
import time
from pathlib import Path

import numpy as np
from scipy.signal import get_window

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from dsp_pipeline import DSPBlock, Pipeline, TestSignal, add_audio_args, add_test_args


def phase_vocoder_stretch(audio: np.ndarray, stretch_factor: float,
                          fft_size: int = 2048, hop_size: int = 512) -> np.ndarray:
    """Time-stretch audio by stretch_factor without changing pitch.

    Uses the phase vocoder algorithm:
    1. STFT the input
    2. Advance through input frames at normal rate
    3. Synthesize output frames at stretched rate
    4. Accumulate phase differences to maintain coherence
    """
    n = len(audio)
    window = get_window("hann", fft_size, fftbins=True).astype(np.float32)
    n_frames = (n - fft_size) // hop_size + 1

    # analysis hop vs synthesis hop
    analysis_hop = hop_size
    synthesis_hop = int(hop_size * stretch_factor)

    # output length
    output_len = (n_frames - 1) * synthesis_hop + fft_size
    output = np.zeros(output_len, dtype=np.float32)
    window_sum = np.zeros(output_len, dtype=np.float32)

    # STFT analysis
    prev_phase = np.zeros(fft_size // 2 + 1)
    accum_phase = np.zeros(fft_size // 2 + 1)

    # expected phase advance per analysis hop
    omega = 2 * np.pi * np.arange(fft_size // 2 + 1) * analysis_hop / fft_size

    for frame_idx in range(n_frames):
        # analysis
        start = frame_idx * analysis_hop
        frame = audio[start:start + fft_size] * window
        spectrum = np.fft.rfft(frame)
        magnitude = np.abs(spectrum)
        phase = np.angle(spectrum)

        # compute instantaneous frequency via phase difference
        phase_diff = phase - prev_phase - omega
        # wrap to [-pi, pi]
        phase_diff = phase_diff - 2 * np.pi * np.round(phase_diff / (2 * np.pi))
        # true frequency deviation
        inst_freq = omega + phase_diff
        prev_phase = phase.copy()

        # accumulate phase for synthesis
        accum_phase += inst_freq * (synthesis_hop / analysis_hop)

        # synthesize
        synth_spectrum = magnitude * np.exp(1j * accum_phase)
        synth_frame = np.fft.irfft(synth_spectrum, n=fft_size).astype(np.float32)
        synth_frame *= window

        # overlap-add
        out_start = frame_idx * synthesis_hop
        out_end = out_start + fft_size
        if out_end <= output_len:
            output[out_start:out_end] += synth_frame
            window_sum[out_start:out_end] += window ** 2

    # normalize by window overlap
    mask = window_sum > 1e-6
    output[mask] /= window_sum[mask]

    return output


class RingBuffer:
    """Circular buffer for continuous audio capture."""

    def __init__(self, max_seconds: float, samplerate: int):
        self.size = int(max_seconds * samplerate)
        self.buffer = np.zeros(self.size, dtype=np.float32)
        self.write_pos = 0
        self.filled = 0

    def write(self, samples: np.ndarray):
        n = len(samples)
        if n >= self.size:
            self.buffer[:] = samples[-self.size:]
            self.write_pos = 0
            self.filled = self.size
            return

        end = self.write_pos + n
        if end <= self.size:
            self.buffer[self.write_pos:end] = samples
        else:
            first = self.size - self.write_pos
            self.buffer[self.write_pos:] = samples[:first]
            self.buffer[:n - first] = samples[first:]
        self.write_pos = end % self.size
        self.filled = min(self.filled + n, self.size)

    def read_last(self, n_samples: int) -> np.ndarray:
        """Read the most recent n_samples from the buffer."""
        n = min(n_samples, self.filled)
        if n == 0:
            return np.zeros(0, dtype=np.float32)
        start = (self.write_pos - n) % self.size
        if start + n <= self.size:
            return self.buffer[start:start + n].copy()
        else:
            first = self.size - start
            return np.concatenate([self.buffer[start:], self.buffer[:n - first]])


class LevelDetector:
    """Simple level-threshold trigger with hold time."""

    def __init__(self, threshold_db: float = -30.0, hold_ms: float = 500.0,
                 samplerate: int = 48000, blocksize: int = 1024):
        self.threshold = 10 ** (threshold_db / 20.0)
        self.hold_samples = int(hold_ms * samplerate / 1000)
        self.blocksize = blocksize
        self._hold_counter = 0
        self.triggered = False

    def check(self, samples: np.ndarray) -> bool:
        """Returns True if trigger condition is met."""
        rms = np.sqrt(np.mean(samples ** 2))
        if rms > self.threshold:
            self._hold_counter = self.hold_samples
            self.triggered = True
        elif self._hold_counter > 0:
            self._hold_counter -= len(samples)
        else:
            self.triggered = False
        return self.triggered


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Bird song time-stretcher — slow down audio without pitch "
        "shift to reveal hidden micro-structure.")
    add_audio_args(parser)
    add_test_args(parser)
    parser.add_argument("--stretch", type=float, default=4.0,
                        help="Time stretch factor (default: 4.0 = 4× slower)")
    parser.add_argument("--mode", choices=["continuous", "triggered", "capture"],
                        default="triggered",
                        help="Operation mode (default: triggered)")
    parser.add_argument("--buffer-seconds", type=float, default=5.0,
                        help="Ring buffer size in seconds (default: 5)")
    parser.add_argument("--trigger-db", type=float, default=-30.0,
                        help="Trigger threshold in dBFS (default: -30)")
    parser.add_argument("--fft-size", type=int, default=2048,
                        help="Phase vocoder FFT size (default: 2048)")
    parser.add_argument("--output-file", metavar="FILE",
                        help="Save stretched audio to WAV file")
    args = parser.parse_args()

    if args.list_devices:
        from dsp_pipeline.args import open_stream_from_args
        open_stream_from_args(args)
        return 0

    samplerate = args.samplerate
    blocksize = args.blocksize
    stretch = args.stretch

    if args.test:
        ts = TestSignal(samplerate, args.test_duration)
        # simulate a bird call: rapid FM sweep + harmonics
        duration = args.test_duration
        n_samples = ts.n_samples
        t = np.arange(n_samples) / samplerate

        test_audio = np.zeros(n_samples, dtype=np.float32)
        # chirp "syllables" — rapid descending FM sweeps
        syllable_dur = 0.08  # 80 ms per syllable
        gap_dur = 0.12  # 120 ms gap
        cycle = int((syllable_dur + gap_dur) * samplerate)
        syl_len = int(syllable_dur * samplerate)

        for start in range(0, n_samples - cycle, cycle):
            syl_t = np.arange(syl_len) / samplerate
            # descending FM: 6 kHz → 2 kHz
            f0, f1 = 6000, 2000
            inst_phase = 2 * np.pi * (f0 * syl_t + (f1 - f0) / (2 * syllable_dur) * syl_t ** 2)
            syllable = 0.4 * np.sin(inst_phase)
            # add harmonic at 2×
            syllable += 0.15 * np.sin(2 * inst_phase)
            # add vibrato (rapid AM at 30 Hz)
            syllable *= (1 + 0.3 * np.sin(2 * np.pi * 30 * syl_t))
            # envelope
            env = np.sin(np.pi * np.arange(syl_len) / syl_len)
            test_audio[start:start + syl_len] = (syllable * env).astype(np.float32)

        # add ambient noise
        test_audio += np.random.randn(n_samples).astype(np.float32) * 0.005

        print(f"Test mode: synthetic bird call (6→2 kHz FM chirps with vibrato)")
        print(f"Stretch factor: {stretch}×")
        print(f"Input duration: {duration:.1f}s → Output duration: ~{duration * stretch:.1f}s")
        print()

        # stretch the whole thing
        stretched = phase_vocoder_stretch(test_audio, stretch, args.fft_size)

        # report
        input_rms = np.sqrt(np.mean(test_audio ** 2))
        output_rms = np.sqrt(np.mean(stretched ** 2))
        print(f"Input RMS:  {20 * np.log10(input_rms + 1e-10):.1f} dBFS")
        print(f"Output RMS: {20 * np.log10(output_rms + 1e-10):.1f} dBFS")
        print(f"Input samples:  {len(test_audio)}")
        print(f"Output samples: {len(stretched)}")
        print(f"Actual stretch: {len(stretched) / len(test_audio):.2f}×")

        if args.output_file:
            import soundfile as sf
            sf.write(args.output_file, stretched, samplerate)
            print(f"\nStretched audio saved to {args.output_file}")
    else:
        from dsp_pipeline.stream import AudioStream
        import sounddevice as sd

        ring = RingBuffer(args.buffer_seconds, samplerate)
        trigger = LevelDetector(
            threshold_db=args.trigger_db,
            hold_ms=500,
            samplerate=samplerate,
            blocksize=blocksize,
        )

        stop = [False]
        playing_stretched = [False]
        stretch_buffer = [np.zeros(0, dtype=np.float32)]
        play_pos = [0]

        def handler(s, f):
            stop[0] = True
        old_handler = sig_module.signal(sig_module.SIGINT, handler)

        if args.mode == "continuous":
            # continuous mode: stretch in real-time (will drift behind)
            print(f"Continuous stretch ({stretch}×) — output lags input "
                  f"by {stretch}× real time", file=sys.stderr)
            print("Ctrl-C to stop", file=sys.stderr)

            stream = AudioStream(
                input_device=args.input_device,
                output_device=args.output_device,
                samplerate=samplerate,
                blocksize=blocksize,
                channels_in=1,
                channels_out=1,
            )

            # accumulate input, stretch periodically
            input_accumulator = [np.zeros(0, dtype=np.float32)]
            stretch_chunk_size = int(0.5 * samplerate)  # stretch every 0.5s

            def callback(indata, frames):
                mono = indata[:, 0] if indata.ndim == 2 else indata
                input_accumulator[0] = np.concatenate([input_accumulator[0], mono])

                # once we have enough, stretch and queue
                if len(input_accumulator[0]) >= stretch_chunk_size:
                    chunk = input_accumulator[0][:stretch_chunk_size]
                    input_accumulator[0] = input_accumulator[0][stretch_chunk_size:]
                    stretched_chunk = phase_vocoder_stretch(chunk, stretch, args.fft_size)
                    stretch_buffer[0] = np.concatenate([stretch_buffer[0], stretched_chunk])

                # output from stretched buffer
                n = frames
                if len(stretch_buffer[0]) >= n:
                    out = stretch_buffer[0][:n].reshape(-1, 1)
                    stretch_buffer[0] = stretch_buffer[0][n:]
                    return out
                else:
                    return np.zeros((n, 1), dtype=np.float32)

            stream.set_callback(callback)
            try:
                stream.start()
                while not stop[0]:
                    time.sleep(0.5)
                    buf_sec = len(stretch_buffer[0]) / samplerate
                    print(f"\r  Buffered: {buf_sec:.1f}s stretched audio",
                          end="", flush=True)
            finally:
                stream.stop()
                sig_module.signal(sig_module.SIGINT, old_handler)
                print()

        elif args.mode == "triggered":
            # triggered mode: buffer, detect transient, stretch and play
            print(f"Triggered mode — buffering {args.buffer_seconds}s, "
                  f"stretch {stretch}×", file=sys.stderr)
            print(f"Trigger threshold: {args.trigger_db} dBFS", file=sys.stderr)
            print("Ctrl-C to stop", file=sys.stderr)
            print()

            # input-only stream for buffering
            stream_in = sd.InputStream(
                device=args.input_device,
                samplerate=samplerate,
                blocksize=blocksize,
                channels=1,
                dtype="float32",
            )

            triggered_count = [0]
            last_trigger = [0.0]

            try:
                stream_in.start()
                while not stop[0]:
                    data, _ = stream_in.read(blocksize)
                    mono = data.flatten()
                    ring.write(mono)

                    was_triggered = trigger.triggered
                    is_triggered = trigger.check(mono)

                    # trigger on rising edge (with 2s dead time)
                    if is_triggered and not was_triggered:
                        now = time.time()
                        if now - last_trigger[0] > 2.0:
                            last_trigger[0] = now
                            triggered_count[0] += 1
                            print(f"  Triggered #{triggered_count[0]}! "
                                  f"Stretching {args.buffer_seconds}s...",
                                  flush=True)
                            # grab buffer and stretch
                            buf_samples = int(args.buffer_seconds * samplerate)
                            captured = ring.read_last(buf_samples)
                            stretched = phase_vocoder_stretch(
                                captured, stretch, args.fft_size)
                            # play through output
                            sd.play(stretched, samplerate=samplerate,
                                    device=args.output_device)
                            dur = len(stretched) / samplerate
                            print(f"    Playing {dur:.1f}s of stretched audio")

                            if args.output_file:
                                import soundfile as sf
                                fname = f"{args.output_file}_{triggered_count[0]:03d}.wav"
                                sf.write(fname, stretched, samplerate)
                                print(f"    Saved to {fname}")
            finally:
                stream_in.stop()
                stream_in.close()
                sig_module.signal(sig_module.SIGINT, old_handler)
                print(f"\nTotal triggers: {triggered_count[0]}")

        else:  # capture mode
            print(f"Capture mode: recording {args.buffer_seconds}s...",
                  file=sys.stderr)
            captured = sd.rec(int(args.buffer_seconds * samplerate),
                              samplerate=samplerate, channels=1,
                              dtype="float32", device=args.input_device)
            sd.wait()
            captured = captured.flatten()
            sig_module.signal(sig_module.SIGINT, old_handler)

            print(f"Stretching {stretch}×...", file=sys.stderr)
            stretched = phase_vocoder_stretch(captured, stretch, args.fft_size)
            print(f"Playing {len(stretched) / samplerate:.1f}s...",
                  file=sys.stderr)
            sd.play(stretched, samplerate=samplerate, device=args.output_device)
            sd.wait()

            if args.output_file:
                import soundfile as sf
                sf.write(args.output_file, stretched, samplerate)
                print(f"Saved to {args.output_file}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
