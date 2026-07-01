#!/usr/bin/env python3
"""
auto_tune_reality.py — Auto-tune reality.

Pitch-detects everything you hear and snaps it to the nearest note in a
musical scale. Car horns become musical, bird calls lock to intervals,
wind becomes a drone chord. The world becomes an accidental composition.

Uses a phase vocoder for pitch shifting: detect pitch, compute the shift
needed to reach the nearest scale degree, apply the shift in real-time.
"""

from __future__ import annotations

import argparse
import signal
import sys
import time
from pathlib import Path

import numpy as np
from scipy.signal import get_window

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from dsp_pipeline import DSPBlock, Pipeline, TestSignal, add_audio_args, add_test_args


# musical scales as semitone offsets from root
SCALES = {
    "chromatic": list(range(12)),
    "major": [0, 2, 4, 5, 7, 9, 11],
    "minor": [0, 2, 3, 5, 7, 8, 10],
    "pentatonic": [0, 2, 4, 7, 9],
    "minor_pentatonic": [0, 3, 5, 7, 10],
    "blues": [0, 3, 5, 6, 7, 10],
    "whole_tone": [0, 2, 4, 6, 8, 10],
    "diminished": [0, 2, 3, 5, 6, 8, 9, 11],
}

NOTE_NAMES = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]


def freq_to_midi(freq: float) -> float:
    """Convert frequency to MIDI note number (A4 = 69 = 440 Hz)."""
    if freq <= 0:
        return 0.0
    return 69.0 + 12.0 * np.log2(freq / 440.0)


def midi_to_freq(midi: float) -> float:
    """Convert MIDI note number to frequency."""
    return 440.0 * 2.0 ** ((midi - 69.0) / 12.0)


def snap_to_scale(midi_note: float, scale: list[int], root: int = 0) -> float:
    """Snap a MIDI note to the nearest degree in the given scale."""
    octave = int(midi_note) // 12
    degree = midi_note - octave * 12

    # find nearest scale degree (accounting for root offset)
    best_dist = 100.0
    best_note = midi_note
    for s in scale:
        target = (s + root) % 12
        dist = abs(degree - target)
        if dist > 6:
            dist = 12 - dist
        if dist < best_dist:
            best_dist = dist
            best_note = octave * 12 + target
            # handle wraparound
            if target < degree - 6:
                best_note += 12
            elif target > degree + 6:
                best_note -= 12

    return best_note


def detect_pitch_autocorr(samples: np.ndarray, samplerate: int,
                           min_freq: float = 60.0,
                           max_freq: float = 4000.0) -> float:
    """Detect fundamental pitch via normalized autocorrelation."""
    n = len(samples)
    if n < 2:
        return 0.0

    # apply window
    windowed = samples * get_window("hann", n)

    # autocorrelation via FFT
    fft_size = 1
    while fft_size < 2 * n:
        fft_size *= 2
    X = np.fft.rfft(windowed, n=fft_size)
    acf = np.fft.irfft(X * np.conj(X))[:n]

    # normalize
    if acf[0] <= 0:
        return 0.0
    acf /= acf[0]

    # search for peak in valid lag range
    min_lag = int(samplerate / max_freq)
    max_lag = min(int(samplerate / min_freq), n - 1)

    if min_lag >= max_lag:
        return 0.0

    # find first significant peak after the dip
    search = acf[min_lag:max_lag]
    if len(search) == 0:
        return 0.0

    # threshold: require correlation > 0.3 for voiced detection
    peak_idx = np.argmax(search)
    if search[peak_idx] < 0.3:
        return 0.0

    lag = peak_idx + min_lag

    # parabolic interpolation for sub-sample accuracy
    if 0 < lag < n - 1:
        alpha = acf[lag - 1]
        beta = acf[lag]
        gamma = acf[lag + 1]
        denom = alpha - 2 * beta + gamma
        if abs(denom) > 1e-10:
            correction = 0.5 * (alpha - gamma) / denom
            lag = lag + correction

    if lag <= 0:
        return 0.0
    return samplerate / lag


class AutoTuneBlock(DSPBlock):
    """Real-time pitch correction via phase vocoder."""

    def __init__(self, samplerate: int = 48000, blocksize: int = 1024,
                 scale: str = "chromatic", root: int = 0,
                 correction_strength: float = 1.0,
                 fft_size: int = 2048):
        super().__init__(samplerate, blocksize)
        self.scale = SCALES.get(scale, SCALES["chromatic"])
        self.root = root
        self.correction_strength = correction_strength
        self.fft_size = fft_size
        self.hop_size = fft_size // 4

        self._input_buffer = np.zeros(0, dtype=np.float32)
        self._output_buffer = np.zeros(0, dtype=np.float32)
        self._ola_pos = 0
        self._prev_phase = np.zeros(fft_size // 2 + 1)
        self._accum_phase = np.zeros(fft_size // 2 + 1)
        self._window = get_window("hann", fft_size, fftbins=True).astype(np.float32)
        self._omega = 2 * np.pi * np.arange(fft_size // 2 + 1) * self.hop_size / fft_size

        self.detected_freq = 0.0
        self.target_freq = 0.0
        self.detected_note = ""
        self.target_note = ""

    def _pitch_shift_frame(self, frame: np.ndarray, shift_semitones: float) -> np.ndarray:
        """Pitch-shift a single windowed frame by shift_semitones."""
        spectrum = np.fft.rfft(frame)
        magnitude = np.abs(spectrum)
        phase = np.angle(spectrum)

        # phase difference
        phase_diff = phase - self._prev_phase - self._omega
        phase_diff -= 2 * np.pi * np.round(phase_diff / (2 * np.pi))
        inst_freq = self._omega + phase_diff
        self._prev_phase = phase.copy()

        # pitch shift by resampling the magnitude spectrum
        shift_ratio = 2.0 ** (shift_semitones / 12.0)
        n_bins = len(magnitude)
        new_magnitude = np.zeros(n_bins)
        new_inst_freq = np.zeros(n_bins)

        for k in range(n_bins):
            new_k = int(k * shift_ratio)
            if 0 <= new_k < n_bins:
                new_magnitude[new_k] += magnitude[k]
                new_inst_freq[new_k] = inst_freq[k] * shift_ratio

        # accumulate output phase
        self._accum_phase += new_inst_freq
        synth = new_magnitude * np.exp(1j * self._accum_phase)
        return np.fft.irfft(synth, n=self.fft_size).astype(np.float32)

    def process(self, samples: np.ndarray) -> np.ndarray:
        mono = samples[:, 0] if samples.ndim == 2 else samples
        n_out = len(mono)

        # accumulate input
        self._input_buffer = np.concatenate([self._input_buffer, mono])

        # process complete frames
        while len(self._input_buffer) >= self.fft_size:
            frame = self._input_buffer[:self.fft_size] * self._window

            # detect pitch
            pitch = detect_pitch_autocorr(
                self._input_buffer[:self.fft_size],
                self.samplerate)

            # compute correction
            shift = 0.0
            if pitch > 60:
                midi = freq_to_midi(pitch)
                target_midi = snap_to_scale(midi, self.scale, self.root)
                shift = (target_midi - midi) * self.correction_strength
                self.detected_freq = pitch
                self.target_freq = midi_to_freq(target_midi)
                note_idx = int(round(midi)) % 12
                self.detected_note = NOTE_NAMES[note_idx]
                target_idx = int(round(target_midi)) % 12
                self.target_note = NOTE_NAMES[target_idx]
            else:
                self.detected_freq = 0
                self.target_freq = 0
                self.detected_note = ""
                self.target_note = ""

            # pitch shift
            shifted = self._pitch_shift_frame(frame, shift)
            shifted *= self._window

            # overlap-add to output buffer at current write position
            write_end = self._ola_pos + self.fft_size
            if write_end > len(self._output_buffer):
                extend = write_end - len(self._output_buffer) + self.fft_size
                self._output_buffer = np.concatenate([
                    self._output_buffer,
                    np.zeros(extend, dtype=np.float32)
                ])
            self._output_buffer[self._ola_pos:self._ola_pos + self.fft_size] += shifted

            # advance write position by hop
            self._ola_pos += self.hop_size

            # advance input
            self._input_buffer = self._input_buffer[self.hop_size:]

        # extract output from front of buffer
        if self._ola_pos >= n_out:
            output = self._output_buffer[:n_out].copy()
            self._output_buffer = self._output_buffer[n_out:]
            self._ola_pos -= n_out
        else:
            output = np.zeros(n_out, dtype=np.float32)
            avail = min(len(self._output_buffer), n_out)
            output[:avail] = self._output_buffer[:avail]
            self._output_buffer = self._output_buffer[avail:]
            self._ola_pos = max(0, self._ola_pos - avail)

        # normalize
        peak = np.max(np.abs(output))
        if peak > 1.0:
            output /= peak

        if samples.ndim == 2:
            out = np.zeros_like(samples)
            out[:, 0] = output
            if samples.shape[1] > 1:
                out[:, 1] = output
            return out
        return output

    def reset(self):
        self._input_buffer = np.zeros(0, dtype=np.float32)
        self._output_buffer = np.zeros(0, dtype=np.float32)
        self._ola_pos = 0
        self._prev_phase = np.zeros(self.fft_size // 2 + 1)
        self._accum_phase = np.zeros(self.fft_size // 2 + 1)

    def get_status(self) -> dict:
        return {
            "detected_freq": self.detected_freq,
            "target_freq": self.target_freq,
            "detected_note": self.detected_note,
            "target_note": self.target_note,
        }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Auto-tune reality — snap all ambient audio to a musical scale.")
    add_audio_args(parser)
    add_test_args(parser)
    parser.add_argument("--scale", choices=list(SCALES.keys()),
                        default="pentatonic",
                        help="Musical scale to snap to (default: pentatonic)")
    parser.add_argument("--root", type=int, default=0,
                        help="Root note as semitones from C (0=C, 2=D, etc.)")
    parser.add_argument("--strength", type=float, default=1.0,
                        help="Correction strength 0-1 (1=full snap, 0=no correction)")
    parser.add_argument("--fft-size", type=int, default=2048,
                        help="Phase vocoder FFT size (default: 2048)")
    args = parser.parse_args()

    if args.list_devices:
        from dsp_pipeline.args import open_stream_from_args
        open_stream_from_args(args)
        return 0

    samplerate = args.samplerate
    blocksize = args.blocksize

    block = AutoTuneBlock(
        samplerate=samplerate,
        blocksize=blocksize,
        scale=args.scale,
        root=args.root,
        correction_strength=args.strength,
        fft_size=args.fft_size,
    )

    pipeline = Pipeline([block], samplerate=samplerate, blocksize=blocksize)

    if args.test:
        ts = TestSignal(samplerate, args.test_duration)
        # generate a chromatic sweep (each note slightly off-pitch)
        duration = args.test_duration
        n_samples = ts.n_samples
        t = np.arange(n_samples) / samplerate

        test_audio = np.zeros(n_samples, dtype=np.float32)
        # car horn at ~349 Hz (between F4 and F#4)
        horn_start = 0
        horn_end = int(1.0 * samplerate)
        test_audio[horn_start:horn_end] = 0.3 * np.sin(
            2 * np.pi * 349 * t[horn_start:horn_end]).astype(np.float32)

        # bird chirp sweeping 800-1200 Hz
        bird_start = int(1.5 * samplerate)
        bird_end = int(2.5 * samplerate)
        bird_t = t[bird_start:bird_end] - t[bird_start]
        bird_freq = 800 + 400 * bird_t / (bird_end - bird_start) * samplerate / samplerate
        # simplify: linear sweep
        bird_phase = 2 * np.pi * np.cumsum(bird_freq) / samplerate
        test_audio[bird_start:bird_end] = (0.25 * np.sin(bird_phase)).astype(np.float32)

        # steady tone at 523 Hz (C5 — should stay put)
        tone_start = int(3.0 * samplerate)
        tone_end = int(4.0 * samplerate)
        test_audio[tone_start:tone_end] = 0.3 * np.sin(
            2 * np.pi * 523.25 * t[tone_start:tone_end]).astype(np.float32)

        # ambient noise
        test_audio += np.random.randn(n_samples).astype(np.float32) * 0.01

        print(f"Test mode: synthetic sounds with off-pitch content")
        print(f"Scale: {args.scale}, Root: {NOTE_NAMES[args.root]}")
        print(f"Strength: {args.strength}")
        print()

        output = pipeline.process_array(test_audio.reshape(-1, 1))
        output_mono = output[:, 0] if output.ndim == 2 else output

        # verify pitch correction happened
        print(f"Input RMS:  {20 * np.log10(np.sqrt(np.mean(test_audio**2)) + 1e-10):.1f} dBFS")
        print(f"Output RMS: {20 * np.log10(np.sqrt(np.mean(output_mono**2)) + 1e-10):.1f} dBFS")
        print(f"Final detected note: {block.detected_note}")
        print(f"Final target note:   {block.target_note}")
        print(f"\nScale degrees ({args.scale}): {', '.join(NOTE_NAMES[s] for s in SCALES[args.scale])}")
    else:
        from dsp_pipeline.stream import AudioStream

        stream = AudioStream(
            input_device=args.input_device,
            output_device=args.output_device,
            samplerate=samplerate,
            blocksize=blocksize,
            channels_in=1,
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
            print(f"Auto-tune reality running", file=sys.stderr)
            print(f"  Scale: {args.scale} (root: {NOTE_NAMES[args.root]})",
                  file=sys.stderr)
            print(f"  Strength: {args.strength}", file=sys.stderr)
            print("  Ctrl-C to stop", file=sys.stderr)
            print()

            while not stop[0]:
                time.sleep(0.3)
                status = block.get_status()
                if status["detected_freq"] > 0:
                    print(f"\r  {status['detected_freq']:>7.1f} Hz "
                          f"({status['detected_note']:>2}) → "
                          f"{status['target_freq']:>7.1f} Hz "
                          f"({status['target_note']:>2})", end="", flush=True)
        finally:
            stream.stop()
            signal.signal(signal.SIGINT, old_handler)
            print()

    return 0


if __name__ == "__main__":
    sys.exit(main())
