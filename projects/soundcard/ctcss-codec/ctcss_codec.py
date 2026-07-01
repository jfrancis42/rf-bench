#!/usr/bin/env python3
"""
ctcss_codec.py — CTCSS (PL tone) encoder/decoder and DCS detector.

Decode mode: detect sub-audible CTCSS tones (67.0-254.1 Hz) in received
FM audio using Goertzel algorithm. Displays frequency and PL code.

Encode mode: generate a sub-audible CTCSS tone mixed with input audio.

DCS detection: identifies Digital Coded Squelch (134.4 bps FSK) when present.
"""

from __future__ import annotations

import argparse
import sys
import time
import wave
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from dsp_pipeline import DSPBlock, Pipeline, TestSignal, add_audio_args, add_test_args
from dsp_pipeline.stream import AudioStream


# Standard EIA CTCSS tone table — all 50 tones with PL designators
CTCSS_TONES = [
    (67.0, "XZ"), (69.3, "WZ"), (71.9, "XA"), (74.4, "WA"),
    (77.0, "XB"), (79.7, "WB"), (82.5, "YZ"), (85.4, "YA"),
    (88.5, "YB"), (91.5, "ZZ"), (94.8, "ZA"), (97.4, "ZB"),
    (100.0, "1Z"), (103.5, "1A"), (107.2, "1B"), (110.9, "2Z"),
    (114.8, "2A"), (118.8, "2B"), (123.0, "3Z"), (127.3, "3A"),
    (131.8, "3B"), (136.5, "4Z"), (141.3, "4A"), (146.2, "4B"),
    (151.4, "5Z"), (156.7, "5A"), (159.8, "5B"), (162.2, "6Z"),
    (165.5, "6A"), (167.9, "6B"), (171.3, "7Z"), (173.8, "7A"),
    (177.3, "7B"), (179.9, "8Z"), (183.5, "8A"), (186.2, "8B"),
    (189.9, "9Z"), (192.8, "9A"), (196.6, "9B"), (199.5, "0Z"),
    (203.5, "0A"), (206.5, "0B"), (210.7, "A1"), (218.1, "A2"),
    (225.7, "B1"), (229.1, "B2"), (233.6, "B3"), (241.8, "B4"),
    (250.3, "C1"), (254.1, "C2"),
]

CTCSS_FREQS = np.array([t[0] for t in CTCSS_TONES], dtype=np.float64)
CTCSS_CODES = [t[1] for t in CTCSS_TONES]

# DCS parameters
DCS_BAUD = 134.4
DCS_MARK_FREQ = 131.8  # Mark tone (Hz)
DCS_SPACE_FREQ = 136.5  # Space tone (Hz)


def goertzel_mag(samples: np.ndarray, freq: float, samplerate: int) -> float:
    """Compute Goertzel magnitude for a single frequency.

    More efficient than FFT when testing a small number of frequencies.
    Returns squared magnitude (power).
    """
    n = len(samples)
    k = int(0.5 + n * freq / samplerate)
    w = 2.0 * np.pi * k / n
    coeff = 2.0 * np.cos(w)

    s0 = 0.0
    s1 = 0.0
    s2 = 0.0

    for sample in samples:
        s0 = sample + coeff * s1 - s2
        s2 = s1
        s1 = s0

    # Squared magnitude
    power = s1 * s1 + s2 * s2 - coeff * s1 * s2
    return power


def goertzel_mag_vectorized(samples: np.ndarray, freqs: np.ndarray, samplerate: int) -> np.ndarray:
    """Vectorized Goertzel for multiple frequencies simultaneously.

    Returns array of squared magnitudes (power) for each frequency.
    """
    n = len(samples)
    k = np.round(n * freqs / samplerate).astype(np.int64)
    w = 2.0 * np.pi * k / n
    coeff = 2.0 * np.cos(w)

    n_freqs = len(freqs)
    s1 = np.zeros(n_freqs, dtype=np.float64)
    s2 = np.zeros(n_freqs, dtype=np.float64)

    for sample in samples:
        s0 = float(sample) + coeff * s1 - s2
        s2 = s1
        s1 = s0

    power = s1 * s1 + s2 * s2 - coeff * s1 * s2
    return power


class CTCSSDecode(DSPBlock):
    """CTCSS tone detector using Goertzel algorithm.

    Uses a sliding analysis window (default 16384 samples at 48 kHz =
    ~341 ms, giving ~2.93 Hz frequency resolution). This window is much
    longer than the processing blocksize and accumulates across multiple
    process() calls, providing the frequency resolution needed to
    distinguish adjacent CTCSS tones (minimum spacing 2.3 Hz).
    """

    def __init__(self, samplerate: int = 48000, blocksize: int = 4096,
                 threshold_db: float = -35.0, integration_blocks: int = 4,
                 analysis_window: int = 0):
        super().__init__(samplerate, blocksize)
        self.threshold_db = threshold_db
        self.integration_blocks = integration_blocks

        # Analysis window: longer than blocksize for frequency resolution.
        # Default: 20480 samples (5 × 4096, ~427 ms at 48 kHz, ~2.34 Hz
        # resolution). This guarantees all 50 CTCSS tones map to unique
        # Goertzel bins (minimum tone spacing is 2.3 Hz at 67.0/69.3;
        # bin width of 2.34 Hz ensures they land in adjacent bins).
        if analysis_window > 0:
            self._analysis_len = analysis_window
        else:
            self._analysis_len = max(blocksize, 20480)

        # Sample accumulator for analysis window
        self._sample_buf = np.zeros(self._analysis_len, dtype=np.float64)
        self._buf_pos = 0
        self._buf_full = False

        # Detection state
        self._detected_freq = 0.0
        self._detected_code = ""
        self._confidence = 0.0
        self._power_history: list[np.ndarray] = []
        self._dcs_detected = False
        self._dcs_code = 0

        # Pre-compute Goertzel coefficients for all CTCSS frequencies
        self._freqs = CTCSS_FREQS
        self._codes = CTCSS_CODES

        # DCS detection: Goertzel at mark and space frequencies
        self._dcs_mark_freq = DCS_MARK_FREQ
        self._dcs_space_freq = DCS_SPACE_FREQ
        self._dcs_bit_buffer: list[int] = []
        self._dcs_sample_count = 0
        self._dcs_samples_per_bit = int(samplerate / DCS_BAUD)

    def process(self, samples: np.ndarray) -> np.ndarray:
        mono = samples[:, 0] if samples.ndim == 2 else samples
        mono_f64 = mono.astype(np.float64)

        # Accumulate samples into analysis window
        n = len(mono_f64)
        if n >= self._analysis_len:
            # Block is larger than analysis window — use last analysis_len samples
            self._sample_buf[:] = mono_f64[-self._analysis_len:]
            self._buf_full = True
        else:
            # Shift buffer left and append new samples
            self._sample_buf[:-n] = self._sample_buf[n:]
            self._sample_buf[-n:] = mono_f64
            self._buf_pos += n
            if self._buf_pos >= self._analysis_len:
                self._buf_full = True

        if self._buf_full:
            # Goertzel over the full analysis window for frequency resolution
            powers = goertzel_mag_vectorized(
                self._sample_buf, self._freqs, self.samplerate
            )

            # Normalize by window length squared
            powers_db = 10.0 * np.log10(powers / (self._analysis_len ** 2) + 1e-12)

            self._power_history.append(powers_db)
            if len(self._power_history) > self.integration_blocks:
                self._power_history = self._power_history[-self.integration_blocks:]

            # Average over integration window
            avg_powers = np.mean(self._power_history, axis=0)

            # Find strongest tone above threshold
            max_idx = np.argmax(avg_powers)
            max_power = avg_powers[max_idx]

            if max_power > self.threshold_db:
                # Check it stands out from neighbors (at least 6 dB above median)
                median_power = np.median(avg_powers)
                if max_power - median_power > 6.0:
                    self._detected_freq = self._freqs[max_idx]
                    self._detected_code = self._codes[max_idx]
                    self._confidence = min(1.0, (max_power - self.threshold_db) / 20.0)
                else:
                    self._detected_freq = 0.0
                    self._detected_code = ""
                    self._confidence = 0.0
            else:
                self._detected_freq = 0.0
                self._detected_code = ""
                self._confidence = 0.0

        # DCS detection: FSK at 134.4 bps
        self._detect_dcs(mono_f64)

        return samples  # pass-through

    def _detect_dcs(self, mono: np.ndarray):
        """Detect DCS codes by demodulating 134.4 bps FSK."""
        # Process in bit-length chunks
        chunk_size = self._dcs_samples_per_bit
        pos = 0
        while pos + chunk_size <= len(mono):
            chunk = mono[pos:pos + chunk_size]
            mark_power = goertzel_mag(chunk, self._dcs_mark_freq, self.samplerate)
            space_power = goertzel_mag(chunk, self._dcs_space_freq, self.samplerate)

            bit = 1 if mark_power > space_power else 0
            self._dcs_bit_buffer.append(bit)
            pos += chunk_size

        # DCS codeword is 23 bits: 3-bit header (100) + 9-bit code + 3-bit CRC + 8 parity
        # Look for valid codewords in the buffer
        if len(self._dcs_bit_buffer) >= 23:
            # Simple search for DCS pattern (header = 100)
            for i in range(len(self._dcs_bit_buffer) - 22):
                if (self._dcs_bit_buffer[i] == 1 and
                        self._dcs_bit_buffer[i + 1] == 0 and
                        self._dcs_bit_buffer[i + 2] == 0):
                    # Extract 9-bit code (octal)
                    code_bits = self._dcs_bit_buffer[i + 3:i + 12]
                    code_val = 0
                    for b in code_bits:
                        code_val = (code_val << 1) | b
                    if 23 <= code_val <= 754:  # valid DCS range
                        self._dcs_detected = True
                        self._dcs_code = code_val
                    break

            # Keep only recent bits
            if len(self._dcs_bit_buffer) > 100:
                self._dcs_bit_buffer = self._dcs_bit_buffer[-50:]

    def get_status(self) -> dict:
        status = {
            "enabled": self.enabled,
            "ctcss_freq": f"{self._detected_freq:.1f}" if self._detected_freq > 0 else "none",
            "ctcss_code": self._detected_code or "none",
            "confidence": f"{self._confidence:.0%}",
        }
        if self._dcs_detected:
            status["dcs_code"] = f"D{self._dcs_code:03o}"
        return status

    def reset(self):
        self._detected_freq = 0.0
        self._detected_code = ""
        self._confidence = 0.0
        self._power_history = []
        self._sample_buf[:] = 0.0
        self._buf_pos = 0
        self._buf_full = False
        self._dcs_detected = False
        self._dcs_code = 0
        self._dcs_bit_buffer = []


class CTCSSEncode(DSPBlock):
    """CTCSS tone generator — mixes sub-audible tone with input audio."""

    def __init__(self, samplerate: int = 48000, blocksize: int = 4096,
                 tone_freq: float = 100.0, tone_level: float = 0.15):
        super().__init__(samplerate, blocksize)
        self.tone_freq = tone_freq
        self.tone_level = tone_level
        self._phase = 0.0
        self._phase_inc = 2.0 * np.pi * tone_freq / samplerate

        # Validate tone frequency
        valid = any(abs(tone_freq - f) < 0.1 for f, _ in CTCSS_TONES)
        if not valid:
            closest = min(CTCSS_TONES, key=lambda t: abs(t[0] - tone_freq))
            print(f"WARNING: {tone_freq} Hz is not a standard CTCSS tone. "
                  f"Closest: {closest[0]} Hz (PL {closest[1]})", file=sys.stderr)

    def process(self, samples: np.ndarray) -> np.ndarray:
        n = samples.shape[0]
        # Generate continuous-phase tone
        phases = self._phase + self._phase_inc * np.arange(n)
        tone = self.tone_level * np.sin(phases).astype(np.float32)
        self._phase = phases[-1] + self._phase_inc
        # Keep phase in [0, 2*pi) to avoid float precision loss
        self._phase = self._phase % (2.0 * np.pi)

        if samples.ndim == 2:
            tone = tone.reshape(-1, 1)
            # Mix: reduce voice level slightly to leave headroom for tone
            output = samples * (1.0 - self.tone_level) + tone
        else:
            output = samples * (1.0 - self.tone_level) + tone

        return np.clip(output, -1.0, 1.0).astype(np.float32)

    def get_status(self) -> dict:
        code = ""
        for freq, c in CTCSS_TONES:
            if abs(freq - self.tone_freq) < 0.1:
                code = c
                break
        return {
            "enabled": self.enabled,
            "tone_freq": f"{self.tone_freq:.1f}",
            "tone_code": code or "non-std",
            "tone_level": f"{self.tone_level:.0%}",
        }

    def reset(self):
        self._phase = 0.0


def print_tone_table():
    """Print the full CTCSS tone table."""
    print("\nStandard EIA CTCSS Tone Table")
    print("=" * 50)
    print(f"{'Freq (Hz)':>10}  {'PL Code':<8}  {'Freq (Hz)':>10}  {'PL Code':<8}")
    print("-" * 50)
    half = (len(CTCSS_TONES) + 1) // 2
    for i in range(half):
        left = CTCSS_TONES[i]
        right = CTCSS_TONES[i + half] if i + half < len(CTCSS_TONES) else None
        line = f"{left[0]:>10.1f}  {left[1]:<8}"
        if right:
            line += f"  {right[0]:>10.1f}  {right[1]:<8}"
        print(line)
    print(f"\nTotal: {len(CTCSS_TONES)} standard tones (67.0 - 254.1 Hz)\n")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="CTCSS (PL tone) encoder/decoder and DCS detector.")
    add_audio_args(parser, duplex=True)
    add_test_args(parser)

    mode_group = parser.add_argument_group("mode")
    mode_group.add_argument("--decode", action="store_true", default=True,
                            help="Decode CTCSS tones from input (default)")
    mode_group.add_argument("--encode", action="store_true",
                            help="Encode CTCSS tone onto input audio")
    mode_group.add_argument("--tone", type=float, default=100.0, metavar="HZ",
                            help="CTCSS tone frequency for encode (default 100.0)")
    mode_group.add_argument("--tone-level", type=float, default=0.15,
                            help="Tone amplitude as fraction of full scale (default 0.15)")
    mode_group.add_argument("--tone-table", action="store_true",
                            help="Print CTCSS tone table and exit")

    decode_group = parser.add_argument_group("decode options")
    decode_group.add_argument("--threshold", type=float, default=-35.0, metavar="DB",
                              help="Detection threshold in dB (default -35)")
    decode_group.add_argument("--integration", type=int, default=4, metavar="N",
                              help="Integration blocks for detection (default 4)")
    decode_group.add_argument("--continuous", action="store_true",
                              help="Run continuously, printing updates")
    decode_group.add_argument("--duration", type=float, default=5.0,
                              help="Decode duration in seconds (default 5)")

    encode_group = parser.add_argument_group("encode options")
    encode_group.add_argument("--output", metavar="WAV",
                              help="Output WAV file (encode mode)")

    args = parser.parse_args()

    # Override default blocksize to 4096 for low-freq resolution
    if args.blocksize == 1024:
        args.blocksize = 4096

    if args.tone_table:
        print_tone_table()
        return 0

    if args.list_devices:
        from dsp_pipeline.args import open_stream_from_args
        open_stream_from_args(args, duplex=False)
        return 0

    if args.encode:
        return _run_encode(args)
    else:
        return _run_decode(args)


def _run_decode(args) -> int:
    """Run CTCSS decode mode."""
    block = CTCSSDecode(
        samplerate=args.samplerate,
        blocksize=args.blocksize,
        threshold_db=args.threshold,
        integration_blocks=args.integration,
    )

    if args.test:
        ts = TestSignal(args.samplerate, args.test_duration)
        # Generate FM audio with CTCSS tone (100.0 Hz, PL 1Z)
        test_audio = ts.ctcss_fm(tone_freq=100.0, voice_freq=800.0)
        pipeline = Pipeline([block], samplerate=args.samplerate, blocksize=args.blocksize)
        pipeline.process_array(test_audio.reshape(-1, 1))
        status = block.get_status()
        print(f"CTCSS Decode (test mode)")
        print(f"  Detected tone: {status['ctcss_freq']} Hz")
        print(f"  PL code:       {status['ctcss_code']}")
        print(f"  Confidence:    {status['confidence']}")
        if "dcs_code" in status:
            print(f"  DCS code:      {status['dcs_code']}")
    else:
        import signal as sig_module

        stream = AudioStream(
            input_device=args.input_device,
            samplerate=args.samplerate,
            blocksize=args.blocksize,
            channels_in=args.channels_in,
        )

        def callback(indata, frames):
            block.process(indata)
            return None

        stream.set_callback(callback)
        stop = [False]

        def handler(s, f):
            stop[0] = True
        old = sig_module.signal(sig_module.SIGINT, handler)

        try:
            stream.start()
            print("CTCSS decoder running... Ctrl-C to stop", file=sys.stderr)
            last_code = ""
            elapsed = 0.0
            while not stop[0]:
                time.sleep(0.25)
                elapsed += 0.25
                status = block.get_status()
                freq_str = status["ctcss_freq"]
                code_str = status["ctcss_code"]
                conf_str = status["confidence"]

                line = f"CTCSS: {freq_str:>6s} Hz  PL: {code_str:<4s}  Conf: {conf_str}"
                if "dcs_code" in status:
                    line += f"  DCS: {status['dcs_code']}"
                print(f"\r{line:<60s}", end="", flush=True)

                # Report new detections
                if code_str != "none" and code_str != last_code:
                    print(f"\n  >> Detected: {freq_str} Hz (PL {code_str})", file=sys.stderr)
                    last_code = code_str
                elif code_str == "none":
                    last_code = ""

                if not args.continuous and elapsed >= args.duration:
                    break
        finally:
            stream.stop()
            sig_module.signal(sig_module.SIGINT, old)
            print()

    return 0


def _run_encode(args) -> int:
    """Run CTCSS encode mode."""
    block = CTCSSEncode(
        samplerate=args.samplerate,
        blocksize=args.blocksize,
        tone_freq=args.tone,
        tone_level=args.tone_level,
    )

    status = block.get_status()
    print(f"CTCSS Encode: {status['tone_freq']} Hz (PL {status['tone_code']}), "
          f"level {status['tone_level']}", file=sys.stderr)

    if args.test:
        ts = TestSignal(args.samplerate, args.test_duration)
        # Voice-like audio — use 300 Hz fundamental to keep harmonics
        # above the CTCSS band (67-254 Hz)
        test_audio = ts.speech_like(fundamental=300.0, amplitude=0.4)
        pipeline = Pipeline([block], samplerate=args.samplerate, blocksize=args.blocksize)
        encoded = pipeline.process_array(test_audio.reshape(-1, 1))

        if args.output:
            _write_wav(args.output, encoded, args.samplerate)
            print(f"Wrote: {args.output}")
        else:
            # Verify by decoding the encoded output
            decoder = CTCSSDecode(
                samplerate=args.samplerate,
                blocksize=args.blocksize,
            )
            verify_pipeline = Pipeline([decoder], samplerate=args.samplerate, blocksize=args.blocksize)
            verify_pipeline.process_array(encoded)
            dec_status = decoder.get_status()
            print(f"Encode test complete.")
            print(f"  Encoded tone:  {status['tone_freq']} Hz (PL {status['tone_code']})")
            print(f"  Verify decode: {dec_status['ctcss_freq']} Hz (PL {dec_status['ctcss_code']})")
            print(f"  Confidence:    {dec_status['confidence']}")
    elif args.output:
        # Encode tone onto live input and write to WAV
        import signal as sig_module

        stream = AudioStream(
            input_device=args.input_device,
            samplerate=args.samplerate,
            blocksize=args.blocksize,
            channels_in=args.channels_in,
        )

        output_blocks: list[np.ndarray] = []

        def callback(indata, frames):
            encoded = block.process(indata)
            output_blocks.append(encoded.copy())
            return None

        stream.set_callback(callback)
        stop = [False]

        def handler(s, f):
            stop[0] = True
        old = sig_module.signal(sig_module.SIGINT, handler)

        try:
            stream.start()
            print(f"Encoding CTCSS {args.tone} Hz to {args.output}... Ctrl-C to stop",
                  file=sys.stderr)
            elapsed = 0.0
            while not stop[0]:
                time.sleep(0.1)
                elapsed += 0.1
                if not args.continuous and elapsed >= args.duration:
                    break
        finally:
            stream.stop()
            sig_module.signal(sig_module.SIGINT, old)

        if output_blocks:
            audio_out = np.concatenate(output_blocks, axis=0)
            _write_wav(args.output, audio_out, args.samplerate)
            print(f"Wrote: {args.output} ({len(audio_out)/args.samplerate:.1f}s)")
    else:
        # Real-time encode: input → add tone → output
        import signal as sig_module

        stream = AudioStream(
            input_device=args.input_device,
            output_device=getattr(args, "output_device", None),
            samplerate=args.samplerate,
            blocksize=args.blocksize,
            channels_in=args.channels_in,
            channels_out=getattr(args, "channels_out", 2),
        )

        def callback(indata, frames):
            return block.process(indata)

        stream.set_callback(callback)
        stop = [False]

        def handler(s, f):
            stop[0] = True
        old = sig_module.signal(sig_module.SIGINT, handler)

        try:
            stream.start()
            print(f"Encoding CTCSS {args.tone} Hz in real-time... Ctrl-C to stop",
                  file=sys.stderr)
            while not stop[0]:
                time.sleep(0.1)
        finally:
            stream.stop()
            sig_module.signal(sig_module.SIGINT, old)
            print()

    return 0


def _write_wav(path: str, audio: np.ndarray, samplerate: int):
    """Write float32 audio to 16-bit WAV file."""
    if audio.ndim == 2:
        channels = audio.shape[1]
    else:
        channels = 1
        audio = audio.reshape(-1, 1)

    # Convert float32 [-1, 1] to int16
    int16_audio = (audio * 32767).clip(-32768, 32767).astype(np.int16)

    with wave.open(path, "w") as wf:
        wf.setnchannels(channels)
        wf.setsampwidth(2)
        wf.setframerate(samplerate)
        wf.writeframes(int16_audio.tobytes())


if __name__ == "__main__":
    sys.exit(main())
