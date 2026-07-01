#!/usr/bin/env python3
"""
vox_filter.py — VOX with anti-trip filtering.

Software VOX that triggers PTT based on audio level, with configurable
filtering to reject keyboard clicks, background music, and fan noise.
Uses frequency-weighted detection (speech energy 300–3000 Hz).
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

import numpy as np
from scipy.signal import butter, sosfilt, sosfilt_zi

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from dsp_pipeline import DSPBlock, Pipeline, TestSignal, add_audio_args, add_test_args
from dsp_pipeline.stream import AudioStream


class VOXFilter(DSPBlock):
    """VOX with anti-trip speech-band filtering."""

    def __init__(self, samplerate: int = 48000, blocksize: int = 512,
                 threshold_db: float = -30.0, hang_ms: float = 500.0,
                 anti_trip_db: float = 10.0,
                 speech_low: float = 300.0, speech_high: float = 3000.0):
        super().__init__(samplerate, blocksize)
        self.threshold = 10 ** (threshold_db / 20.0)
        self.hang_samples = int(hang_ms * samplerate / 1000)
        self.anti_trip_ratio = 10 ** (anti_trip_db / 20.0)
        self._hang_counter = 0
        self._ptt_state = False
        self._speech_rms = 0.0
        self._total_rms = 0.0

        # speech band filter
        sos = butter(3, [speech_low, speech_high], btype="band",
                     fs=samplerate, output="sos")
        self._speech_sos = sos
        self._speech_zi = sosfilt_zi(sos) * 0

    def process(self, samples: np.ndarray) -> np.ndarray:
        mono = samples[:, 0] if samples.ndim == 2 else samples

        # filter to speech band
        speech_filtered, self._speech_zi = sosfilt(
            self._speech_sos, mono, zi=self._speech_zi)

        # compute RMS of speech band and total
        self._speech_rms = np.sqrt(np.mean(speech_filtered ** 2))
        self._total_rms = np.sqrt(np.mean(mono ** 2))

        # anti-trip: speech band must dominate over out-of-band energy
        out_of_band_rms = np.sqrt(max(0, self._total_rms**2 - self._speech_rms**2))

        # trigger conditions:
        # 1. Speech-band energy above threshold
        # 2. Speech-band energy dominates total (anti-trip)
        speech_dominant = (self._speech_rms > out_of_band_rms / self.anti_trip_ratio
                           if out_of_band_rms > 1e-6 else True)
        above_threshold = self._speech_rms > self.threshold

        if above_threshold and speech_dominant:
            self._ptt_state = True
            self._hang_counter = self.hang_samples
        elif self._hang_counter > 0:
            self._hang_counter -= len(mono)
        else:
            self._ptt_state = False

        return samples  # pass through (VOX doesn't modify audio)

    @property
    def ptt(self) -> bool:
        """Current PTT state."""
        return self._ptt_state

    def reset(self):
        self._hang_counter = 0
        self._ptt_state = False

    def get_status(self) -> dict:
        return {
            "enabled": self.enabled,
            "ptt": self._ptt_state,
            "speech_rms_db": f"{20*np.log10(self._speech_rms + 1e-10):.1f}",
            "total_rms_db": f"{20*np.log10(self._total_rms + 1e-10):.1f}",
        }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="VOX with anti-trip filtering.")
    add_audio_args(parser, duplex=False)
    add_test_args(parser)
    parser.add_argument("--threshold-db", type=float, default=-30.0,
                        help="VOX trigger threshold in dBFS (default -30)")
    parser.add_argument("--hang-ms", type=float, default=500.0,
                        help="PTT hang time in ms (default 500)")
    parser.add_argument("--anti-trip-db", type=float, default=10.0,
                        help="Anti-trip: speech must exceed out-of-band by this (default 10 dB)")
    parser.add_argument("--speech-low", type=float, default=300.0,
                        help="Speech band lower edge (default 300 Hz)")
    parser.add_argument("--speech-high", type=float, default=3000.0,
                        help="Speech band upper edge (default 3000 Hz)")
    parser.add_argument("--output", metavar="CSV",
                        help="Log PTT events to CSV")
    args = parser.parse_args()

    if args.list_devices:
        from dsp_pipeline.args import open_stream_from_args
        open_stream_from_args(args, duplex=False)
        return 0

    block = VOXFilter(
        samplerate=args.samplerate,
        blocksize=args.blocksize,
        threshold_db=args.threshold_db,
        hang_ms=args.hang_ms,
        anti_trip_db=args.anti_trip_db,
        speech_low=args.speech_low,
        speech_high=args.speech_high,
    )

    if args.test:
        ts = TestSignal(args.samplerate, args.test_duration)
        # sequence: silence, speech, keyboard click (broadband impulse), speech
        n = args.samplerate
        silence = np.zeros(n, dtype=np.float32)
        speech = ts.speech_like(amplitude=0.3)[:n]
        click = ts.impulse_noise(base_freq=0, base_amplitude=0, impulse_rate=50, impulse_amplitude=0.8)[:n//2]
        test_audio = np.concatenate([silence, speech, click, speech])

        pipeline = Pipeline([block], samplerate=args.samplerate, blocksize=args.blocksize)
        # process and track PTT state
        ptt_log = []
        for start in range(0, len(test_audio), args.blocksize):
            chunk = test_audio[start:start + args.blocksize]
            if len(chunk) < args.blocksize:
                chunk = np.pad(chunk, (0, args.blocksize - len(chunk)))
            block.process(chunk.reshape(-1, 1))
            ptt_log.append(block.ptt)

        triggered = sum(ptt_log)
        print(f"Total blocks: {len(ptt_log)}")
        print(f"PTT active blocks: {triggered}")
        print(f"PTT duty cycle: {100*triggered/len(ptt_log):.1f}%")
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
            csv_file.write("timestamp,ptt,speech_db,total_db\n")

        prev_ptt = False

        def callback(indata, frames):
            nonlocal prev_ptt
            block.process(indata)
            if block.ptt != prev_ptt:
                state = "TX" if block.ptt else "RX"
                print(f"\r[{state}] Speech: {block.get_status()['speech_rms_db']} dBFS",
                      end="", flush=True)
                if csv_file:
                    csv_file.write(f"{time.time():.3f},{int(block.ptt)},"
                                   f"{20*np.log10(block._speech_rms+1e-10):.1f},"
                                   f"{20*np.log10(block._total_rms+1e-10):.1f}\n")
                prev_ptt = block.ptt
            return None

        stream.set_callback(callback)
        stop = [False]

        def handler(s, f):
            stop[0] = True
        old = sig_module.signal(sig_module.SIGINT, handler)

        try:
            stream.start()
            print("VOX running (Ctrl-C to stop)...", file=sys.stderr)
            print(f"Threshold: {args.threshold_db} dBFS, Hang: {args.hang_ms} ms",
                  file=sys.stderr)
            while not stop[0]:
                time.sleep(0.1)
        finally:
            stream.stop()
            sig_module.signal(sig_module.SIGINT, old)
            if csv_file:
                csv_file.close()
            print()

    return 0


if __name__ == "__main__":
    sys.exit(main())
