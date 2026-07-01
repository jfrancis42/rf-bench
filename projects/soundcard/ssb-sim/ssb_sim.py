#!/usr/bin/env python3
"""
ssb_sim.py — SSB radio signal simulator.

Makes audio input sound like it's being received on an SSB (Single
Sideband) radio. Applies bandwidth limiting, optional frequency offset
(mis-tune), AGC pumping, propagation noise, and selective fading to
recreate the distinctive SSB sound.

Adjustable bandwidth presets match common SSB filter widths:
- Narrow CW:   300 Hz  (250-550 Hz passband)
- CW:          500 Hz  (400-900 Hz passband)
- Narrow SSB:  1.8 kHz (300-2100 Hz passband)
- Standard:    2.4 kHz (300-2700 Hz passband)
- Wide:        2.7 kHz (300-3000 Hz passband)
- AM equiv:    3.5 kHz (100-3600 Hz passband)
- Custom:      any low/high pair
"""

from __future__ import annotations

import argparse
import signal
import sys
import time
from pathlib import Path

import numpy as np
from scipy.signal import butter, sosfilt, sosfilt_zi

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from dsp_pipeline import DSPBlock, Pipeline, TestSignal, add_audio_args, add_test_args


BANDWIDTH_PRESETS = {
    "cw-narrow": (250, 550, "Narrow CW (300 Hz)"),
    "cw":        (400, 900, "CW (500 Hz)"),
    "ssb-narrow": (300, 2100, "Narrow SSB (1.8 kHz)"),
    "ssb":       (300, 2700, "Standard SSB (2.4 kHz)"),
    "ssb-wide":  (300, 3000, "Wide SSB (2.7 kHz)"),
    "am":        (100, 3600, "AM equivalent (3.5 kHz)"),
}


class SSBSimulator(DSPBlock):
    """Simulates SSB radio reception characteristics."""

    def __init__(self, samplerate: int = 48000, blocksize: int = 1024,
                 low_freq: float = 300.0, high_freq: float = 2700.0,
                 freq_offset: float = 0.0, noise_level: float = -40.0,
                 agc_attack_ms: float = 5.0, agc_release_ms: float = 300.0,
                 agc_target_db: float = -12.0,
                 fading: bool = False, fading_rate: float = 0.3):
        super().__init__(samplerate, blocksize)

        self.low_freq = low_freq
        self.high_freq = high_freq
        self.freq_offset = freq_offset
        self.noise_level_linear = 10 ** (noise_level / 20.0)
        self.agc_target = 10 ** (agc_target_db / 20.0)
        self.fading_enabled = fading
        self.fading_rate = fading_rate

        # bandpass filter (6th order Butterworth for steep skirts)
        nyquist = samplerate / 2
        low = max(low_freq / nyquist, 0.001)
        high = min(high_freq / nyquist, 0.999)
        self._bp_sos = butter(6, [low, high], btype="band", output="sos")
        self._bp_state = sosfilt_zi(self._bp_sos) * 0
        self._noise_state = sosfilt_zi(self._bp_sos) * 0

        # AGC state
        self._agc_attack = np.exp(-1.0 / (agc_attack_ms * samplerate / 1000))
        self._agc_release = np.exp(-1.0 / (agc_release_ms * samplerate / 1000))
        self._agc_gain = 1.0
        self._agc_envelope = 0.0

        # frequency offset (mis-tune) — phase accumulator
        self._phase = 0.0
        self._phase_inc = 2 * np.pi * freq_offset / samplerate

        # fading (slow amplitude modulation simulating propagation)
        self._fade_phase = 0.0
        self._fade_inc = 2 * np.pi * fading_rate / samplerate

        # output level tracking
        self.output_level_db = -100.0

    def set_bandwidth(self, low_freq: float, high_freq: float):
        """Change bandwidth on the fly."""
        self.low_freq = low_freq
        self.high_freq = high_freq
        nyquist = self.samplerate / 2
        low = max(low_freq / nyquist, 0.001)
        high = min(high_freq / nyquist, 0.999)
        self._bp_sos = butter(6, [low, high], btype="band", output="sos")
        self._bp_state = sosfilt_zi(self._bp_sos) * 0
        self._noise_state = sosfilt_zi(self._bp_sos) * 0

    def set_freq_offset(self, offset_hz: float):
        """Change frequency offset (mis-tune)."""
        self.freq_offset = offset_hz
        self._phase_inc = 2 * np.pi * offset_hz / self.samplerate

    def process(self, samples: np.ndarray) -> np.ndarray:
        mono = samples[:, 0] if samples.ndim == 2 else samples
        n = len(mono)

        # frequency offset (heterodyne shift)
        if abs(self.freq_offset) > 0.1:
            t = np.arange(n)
            phases = self._phase + self._phase_inc * t
            self._phase = phases[-1] + self._phase_inc
            # keep phase bounded
            self._phase = self._phase % (2 * np.pi)
            # shift by multiplying with complex exponential, take real
            analytic = mono * np.cos(phases).astype(np.float32)
            mono = analytic

        # bandpass filter
        filtered, self._bp_state = sosfilt(self._bp_sos, mono, zi=self._bp_state)
        filtered = filtered.astype(np.float32)

        # add band-limited noise (simulates receiver noise floor)
        if self.noise_level_linear > 0:
            noise = np.random.randn(n).astype(np.float32) * self.noise_level_linear
            # filter noise through same bandpass, maintaining state across blocks
            noise_filtered, self._noise_state = sosfilt(
                self._bp_sos, noise, zi=self._noise_state)
            filtered += noise_filtered.astype(np.float32)

        # selective fading (slow amplitude variation)
        if self.fading_enabled:
            t = np.arange(n)
            fade_phases = self._fade_phase + self._fade_inc * t
            self._fade_phase = fade_phases[-1] + self._fade_inc
            self._fade_phase = self._fade_phase % (2 * np.pi)
            # fade between 0.3 and 1.0 (never fully drops out)
            fade = 0.65 + 0.35 * np.cos(fade_phases).astype(np.float32)
            filtered *= fade

        # AGC (automatic gain control)
        output = np.zeros(n, dtype=np.float32)
        for i in range(n):
            # envelope follower
            abs_sample = abs(filtered[i])
            if abs_sample > self._agc_envelope:
                self._agc_envelope = (self._agc_attack * self._agc_envelope +
                                       (1 - self._agc_attack) * abs_sample)
            else:
                self._agc_envelope = (self._agc_release * self._agc_envelope +
                                       (1 - self._agc_release) * abs_sample)

            # compute gain to reach target level
            if self._agc_envelope > 1e-6:
                desired_gain = self.agc_target / self._agc_envelope
                # limit gain range (don't amplify noise to infinity)
                desired_gain = min(desired_gain, 100.0)
                desired_gain = max(desired_gain, 0.01)
            else:
                desired_gain = 1.0

            # smooth gain changes
            alpha = 0.001
            self._agc_gain = self._agc_gain * (1 - alpha) + desired_gain * alpha
            output[i] = filtered[i] * self._agc_gain

        # soft clip — keeps output strictly within [-1, 1]
        output = np.tanh(output)

        # track output level
        rms = np.sqrt(np.mean(output ** 2))
        self.output_level_db = 20 * np.log10(rms + 1e-10)

        if samples.ndim == 2:
            out = np.zeros_like(samples)
            out[:, 0] = output
            if samples.shape[1] > 1:
                out[:, 1] = output
            return out
        return output

    def get_status(self) -> dict:
        return {
            "bandwidth": f"{self.low_freq:.0f}-{self.high_freq:.0f} Hz",
            "freq_offset_hz": self.freq_offset,
            "output_level_db": self.output_level_db,
            "agc_gain_db": 20 * np.log10(self._agc_gain + 1e-10),
            "fading": self.fading_enabled,
        }

    def reset(self):
        self._bp_state = sosfilt_zi(self._bp_sos) * 0
        self._noise_state = sosfilt_zi(self._bp_sos) * 0
        self._agc_gain = 1.0
        self._agc_envelope = 0.0
        self._phase = 0.0
        self._fade_phase = 0.0


def main() -> int:
    parser = argparse.ArgumentParser(
        description="SSB radio signal simulator — makes audio sound like "
        "it's being received on a single-sideband radio.")
    add_audio_args(parser)
    add_test_args(parser)

    bw_group = parser.add_argument_group("bandwidth")
    bw_group.add_argument("--preset", choices=list(BANDWIDTH_PRESETS.keys()),
                          default="ssb",
                          help="Bandwidth preset (default: ssb = 300-2700 Hz)")
    bw_group.add_argument("--low", type=float, default=None,
                          help="Custom low frequency cutoff (overrides preset)")
    bw_group.add_argument("--high", type=float, default=None,
                          help="Custom high frequency cutoff (overrides preset)")

    fx_group = parser.add_argument_group("effects")
    fx_group.add_argument("--offset", type=float, default=0.0,
                          help="Frequency offset in Hz, simulates mis-tune "
                          "(default: 0)")
    fx_group.add_argument("--noise", type=float, default=-40.0,
                          help="Noise floor level in dB (default: -40, "
                          "use -25 for noisy, -60 for quiet)")
    fx_group.add_argument("--fading", action="store_true",
                          help="Enable selective fading (propagation sim)")
    fx_group.add_argument("--fading-rate", type=float, default=0.3,
                          help="Fading rate in Hz (default: 0.3)")
    fx_group.add_argument("--agc-attack", type=float, default=5.0,
                          help="AGC attack time in ms (default: 5)")
    fx_group.add_argument("--agc-release", type=float, default=300.0,
                          help="AGC release time in ms (default: 300)")
    fx_group.add_argument("--no-agc", action="store_true",
                          help="Disable AGC")

    args = parser.parse_args()

    if args.list_devices:
        from dsp_pipeline.args import open_stream_from_args
        open_stream_from_args(args)
        return 0

    # resolve bandwidth
    if args.low is not None and args.high is not None:
        low_freq, high_freq = args.low, args.high
        bw_name = f"Custom ({args.low:.0f}-{args.high:.0f} Hz)"
    else:
        low_freq, high_freq, bw_name = BANDWIDTH_PRESETS[args.preset]

    samplerate = args.samplerate
    blocksize = args.blocksize

    sim = SSBSimulator(
        samplerate=samplerate,
        blocksize=blocksize,
        low_freq=low_freq,
        high_freq=high_freq,
        freq_offset=args.offset,
        noise_level=args.noise,
        agc_attack_ms=args.agc_attack if not args.no_agc else 0.01,
        agc_release_ms=args.agc_release if not args.no_agc else 0.01,
        fading=args.fading,
        fading_rate=args.fading_rate,
    )

    pipeline = Pipeline([sim], samplerate=samplerate, blocksize=blocksize)

    if args.test:
        ts = TestSignal(samplerate, args.test_duration)
        n_samples = ts.n_samples
        t = np.arange(n_samples) / samplerate

        print(f"Test mode: SSB simulation")
        print(f"  Bandwidth: {bw_name}")
        print(f"  Offset:    {args.offset} Hz")
        print(f"  Noise:     {args.noise} dB")
        print(f"  Fading:    {'ON' if args.fading else 'OFF'}")
        print()

        # generate speech-like test signal (formant frequencies)
        test_audio = np.zeros(n_samples, dtype=np.float32)
        # simulate vowel formants
        formants = [400, 1200, 2500]  # roughly "ah"
        for f in formants:
            test_audio += 0.2 * np.sin(2 * np.pi * f * t +
                                        np.random.uniform(0, 2 * np.pi)
                                        ).astype(np.float32)
        # amplitude envelope (syllable-like)
        env_freq = 3.0  # ~3 syllables/sec
        envelope = (0.5 + 0.5 * np.sin(2 * np.pi * env_freq * t)).astype(np.float32)
        test_audio *= envelope
        # add some broadband (consonant-like)
        test_audio += 0.05 * np.random.randn(n_samples).astype(np.float32) * envelope

        # process
        output = pipeline.process_array(test_audio.reshape(-1, 1))
        output_mono = output[:, 0] if output.ndim == 2 else output

        # analyze
        in_rms = np.sqrt(np.mean(test_audio ** 2))
        out_rms = np.sqrt(np.mean(output_mono ** 2))
        print(f"  Input RMS:   {20 * np.log10(in_rms + 1e-10):.1f} dB")
        print(f"  Output RMS:  {20 * np.log10(out_rms + 1e-10):.1f} dB")
        print(f"  Output peak: {np.max(np.abs(output_mono)):.3f}")

        # verify bandwidth limiting: check energy above and below cutoffs
        spectrum = np.abs(np.fft.rfft(output_mono))
        freqs = np.fft.rfftfreq(len(output_mono), 1.0 / samplerate)
        in_band = (freqs >= low_freq) & (freqs <= high_freq)
        out_band = ~in_band & (freqs > 0)
        in_band_energy = np.sum(spectrum[in_band] ** 2)
        out_band_energy = np.sum(spectrum[out_band] ** 2)
        rejection = 10 * np.log10(in_band_energy / (out_band_energy + 1e-10))
        print(f"  Band rejection: {rejection:.1f} dB")

        if rejection > 15 and np.max(np.abs(output_mono)) <= 1.0:
            print("\n  PASS: signal bandwidth-limited without clipping")
        else:
            print(f"\n  CHECK: rejection={rejection:.1f} dB "
                  f"(expect >15), peak={np.max(np.abs(output_mono)):.3f}")
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
            print(f"SSB simulator running", file=sys.stderr)
            print(f"  Bandwidth: {bw_name}", file=sys.stderr)
            print(f"  Offset:    {args.offset} Hz", file=sys.stderr)
            print(f"  Noise:     {args.noise} dB", file=sys.stderr)
            print(f"  Fading:    {'ON' if args.fading else 'OFF'}",
                  file=sys.stderr)
            print("  Ctrl-C to stop\n", file=sys.stderr)

            while not stop[0]:
                time.sleep(0.3)
                status = sim.get_status()
                print(f"\r  [{status['bandwidth']}] "
                      f"Level: {status['output_level_db']:>5.1f} dB | "
                      f"AGC: {status['agc_gain_db']:>+5.1f} dB",
                      end="", flush=True)
        finally:
            stream.stop()
            signal.signal(signal.SIGINT, old_handler)
            print()

    return 0


if __name__ == "__main__":
    sys.exit(main())
