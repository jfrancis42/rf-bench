#!/usr/bin/env python3
"""
selective_call_decoder.py — Sequential tone selective calling decoder.

Decodes two-tone and five-tone sequential signaling (CCIR 493-4, ZVEI,
EIA/EEA) used by commercial/public-safety radios pre-digital era.
Detects the tone sequence and displays the called ID.
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from dsp_pipeline import DSPBlock, Pipeline, TestSignal, add_audio_args, add_test_args
from dsp_pipeline.stream import AudioStream


# Standard tone tables
CCIR_TONES = {
    0: 1981.0, 1: 1124.0, 2: 1197.0, 3: 1275.0, 4: 1358.0,
    5: 1446.0, 6: 1540.0, 7: 1640.0, 8: 1747.0, 9: 1860.0,
    10: 2110.0,  # repeat/group
    11: 2247.0,  # spare
    12: 2400.0,  # spare
    13: 2110.0,  # repeat alt
    14: 2400.0,  # spare alt
    15: 2247.0,  # spare alt
}

ZVEI1_TONES = {
    0: 2400.0, 1: 1060.0, 2: 1160.0, 3: 1270.0, 4: 1400.0,
    5: 1530.0, 6: 1670.0, 7: 1830.0, 8: 2000.0, 9: 2200.0,
    10: 2600.0,  # repeat
}

EIA_TONES = {
    0: 600.0, 1: 741.0, 2: 882.0, 3: 1023.0, 4: 1164.0,
    5: 1305.0, 6: 1446.0, 7: 1587.0, 8: 1728.0, 9: 1869.0,
    10: 2010.0, 11: 2151.0, 12: 459.0,  # 12 = preamble
}

TONE_TABLES = {
    "ccir": CCIR_TONES,
    "zvei": ZVEI1_TONES,
    "eia": EIA_TONES,
}


def goertzel_magnitude(samples: np.ndarray, freq: float, samplerate: int) -> float:
    """Compute magnitude at a specific frequency using Goertzel algorithm."""
    n = len(samples)
    k = int(0.5 + n * freq / samplerate)
    w = 2 * np.pi * k / n
    coeff = 2 * np.cos(w)
    s0 = s1 = s2 = 0.0
    for sample in samples:
        s0 = sample + coeff * s1 - s2
        s2 = s1
        s1 = s0
    power = s1 * s1 + s2 * s2 - coeff * s1 * s2
    return np.sqrt(max(0, power)) / n


class SelectiveCallDecoder(DSPBlock):
    """Sequential tone selective calling decoder."""

    def __init__(self, samplerate: int = 48000, blocksize: int = 1024,
                 tone_system: str = "ccir", min_tone_ms: float = 33.0,
                 max_tone_ms: float = 100.0, threshold_db: float = 10.0,
                 num_tones: int = 5):
        super().__init__(samplerate, blocksize)
        self.tone_system = tone_system
        self.tone_table = TONE_TABLES[tone_system]
        self.min_tone_samples = int(min_tone_ms * samplerate / 1000)
        self.max_tone_samples = int(max_tone_ms * samplerate / 1000)
        self.threshold_db = threshold_db
        self.threshold_ratio = 10 ** (threshold_db / 20.0)
        self.num_tones = num_tones
        self._current_tone = -1
        self._tone_duration = 0
        self._sequence: list[int] = []
        self._decoded_calls: list[tuple[float, str]] = []
        self._analysis_buffer = np.zeros(0, dtype=np.float32)

    def _detect_tone(self, samples: np.ndarray) -> int:
        """Detect which tone (if any) is present in the samples."""
        magnitudes = {}
        for digit, freq in self.tone_table.items():
            mag = goertzel_magnitude(samples, freq, self.samplerate)
            magnitudes[digit] = mag

        # find strongest tone
        if not magnitudes:
            return -1
        best_digit = max(magnitudes, key=magnitudes.get)
        best_mag = magnitudes[best_digit]

        # check if it's significantly above others (threshold)
        others = [m for d, m in magnitudes.items() if d != best_digit]
        avg_others = np.mean(others) if others else 0
        if avg_others > 0 and best_mag / avg_others > self.threshold_ratio:
            return best_digit
        elif avg_others == 0 and best_mag > 0.01:
            return best_digit
        return -1

    def process(self, samples: np.ndarray) -> np.ndarray:
        mono = samples[:, 0] if samples.ndim == 2 else samples

        # accumulate samples for analysis
        self._analysis_buffer = np.concatenate([self._analysis_buffer, mono])

        # analyze in chunks of min_tone_samples
        while len(self._analysis_buffer) >= self.min_tone_samples:
            chunk = self._analysis_buffer[:self.min_tone_samples]
            self._analysis_buffer = self._analysis_buffer[self.min_tone_samples:]

            detected = self._detect_tone(chunk)

            if detected == self._current_tone and detected >= 0:
                self._tone_duration += len(chunk)
            elif detected >= 0:
                # new tone
                if (self._current_tone >= 0 and
                        self._tone_duration >= self.min_tone_samples):
                    self._sequence.append(self._current_tone)
                    if len(self._sequence) >= self.num_tones:
                        call_id = "".join(str(d) for d in self._sequence[-self.num_tones:])
                        self._decoded_calls.append((time.time(), call_id))
                        self._sequence = []
                self._current_tone = detected
                self._tone_duration = len(chunk)
            else:
                # no tone — check if we had a valid final tone
                if (self._current_tone >= 0 and
                        self._tone_duration >= self.min_tone_samples):
                    self._sequence.append(self._current_tone)
                self._current_tone = -1
                self._tone_duration = 0

                # timeout: if we have a partial sequence and no tone for too long
                if self._sequence and self._tone_duration == 0:
                    # partial decode (2-tone or incomplete)
                    if len(self._sequence) >= 2:
                        call_id = "".join(str(d) for d in self._sequence)
                        self._decoded_calls.append((time.time(), call_id))
                    self._sequence = []

        return samples  # pass through

    def get_calls(self) -> list[tuple[float, str]]:
        """Return list of (timestamp, call_id) decoded so far."""
        return self._decoded_calls.copy()

    def reset(self):
        self._current_tone = -1
        self._tone_duration = 0
        self._sequence = []
        self._decoded_calls = []
        self._analysis_buffer = np.zeros(0, dtype=np.float32)

    def get_status(self) -> dict:
        return {
            "enabled": self.enabled,
            "system": self.tone_system,
            "current_tone": self._current_tone,
            "sequence_so_far": "".join(str(d) for d in self._sequence),
            "total_calls": len(self._decoded_calls),
        }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Sequential tone selective calling decoder.")
    add_audio_args(parser, duplex=False)
    add_test_args(parser)
    parser.add_argument("--system", choices=["ccir", "zvei", "eia"], default="ccir",
                        help="Tone system (default ccir)")
    parser.add_argument("--tones", type=int, default=5,
                        help="Number of tones per call (default 5, use 2 for two-tone)")
    parser.add_argument("--threshold-db", type=float, default=10.0,
                        help="Detection threshold above other tones (default 10 dB)")
    parser.add_argument("--min-tone-ms", type=float, default=33.0,
                        help="Minimum tone duration in ms (default 33)")
    parser.add_argument("--output", metavar="CSV",
                        help="Log decoded calls to CSV")
    args = parser.parse_args()

    if args.list_devices:
        from dsp_pipeline.args import open_stream_from_args
        open_stream_from_args(args, duplex=False)
        return 0

    block = SelectiveCallDecoder(
        samplerate=args.samplerate,
        blocksize=args.blocksize,
        tone_system=args.system,
        min_tone_ms=args.min_tone_ms,
        threshold_db=args.threshold_db,
        num_tones=args.tones,
    )

    if args.test:
        ts = TestSignal(args.samplerate, args.test_duration)
        tone_table = TONE_TABLES[args.system]
        # generate a 5-tone sequence: digits 1,2,3,4,5
        tone_dur = int(0.070 * args.samplerate)  # 70 ms per tone
        gap_dur = int(0.010 * args.samplerate)   # 10 ms gap
        sequence = [1, 2, 3, 4, 5]
        audio_parts = []
        for digit in sequence:
            freq = tone_table[digit]
            t = np.arange(tone_dur) / args.samplerate
            tone = 0.4 * np.sin(2 * np.pi * freq * t).astype(np.float32)
            audio_parts.append(tone)
            audio_parts.append(np.zeros(gap_dur, dtype=np.float32))
        # add silence before and after
        test_audio = np.concatenate([
            np.zeros(args.samplerate // 2, dtype=np.float32),
            *audio_parts,
            np.zeros(args.samplerate // 2, dtype=np.float32),
        ])

        pipeline = Pipeline([block], samplerate=args.samplerate, blocksize=args.blocksize)
        pipeline.process_array(test_audio.reshape(-1, 1))

        calls = block.get_calls()
        print(f"System: {args.system.upper()}")
        print(f"Transmitted sequence: {''.join(str(d) for d in sequence)}")
        print(f"Decoded calls: {len(calls)}")
        for ts_val, call_id in calls:
            print(f"  {call_id}")
    else:
        import signal as sig_module

        stream = AudioStream(
            input_device=args.input_device,
            samplerate=args.samplerate,
            blocksize=args.blocksize,
            channels_in=args.channels_in,
        )

        csv_file = None
        if args.output:
            csv_file = open(args.output, "w")
            csv_file.write("timestamp,system,call_id\n")

        last_count = 0

        def callback(indata, frames):
            nonlocal last_count
            block.process(indata)
            calls = block.get_calls()
            if len(calls) > last_count:
                for ts_val, call_id in calls[last_count:]:
                    print(f"\r[{args.system.upper()}] Call: {call_id}  "
                          f"({time.strftime('%H:%M:%S')})", flush=True)
                    if csv_file:
                        csv_file.write(f"{ts_val:.3f},{args.system},{call_id}\n")
                        csv_file.flush()
                last_count = len(calls)
            return None

        stream.set_callback(callback)
        stop = [False]

        def handler(s, f):
            stop[0] = True
        old = sig_module.signal(sig_module.SIGINT, handler)

        try:
            stream.start()
            print(f"Selective call decoder ({args.system.upper()}, "
                  f"{args.tones}-tone) running...", file=sys.stderr)
            while not stop[0]:
                time.sleep(0.1)
        finally:
            stream.stop()
            sig_module.signal(sig_module.SIGINT, old)
            if csv_file:
                csv_file.close()
            print(f"\nTotal calls decoded: {len(block.get_calls())}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
