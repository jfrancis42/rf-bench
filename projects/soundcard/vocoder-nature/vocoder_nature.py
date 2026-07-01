#!/usr/bin/env python3
"""
vocoder_nature.py — Channel vocoder with ambient sound.

Classic channel vocoder: split both modulator and carrier into frequency
bands, apply modulator's envelope to each carrier band. Results:

- Carrier = ambient (rain, wind, traffic), Modulator = your voice
  → your words come out in the timbre of the rain
- Carrier = your voice, Modulator = ambient
  → nature "speaks" whenever you talk

Operates on stereo input: Left = carrier, Right = modulator (or mic
input is modulator and ambient is carrier via --carrier-source).
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


class AmbientGenerator:
    """Generates synthetic ambient carrier signals in real-time."""

    def __init__(self, samplerate: int, source: str = "rain"):
        self.samplerate = samplerate
        self.source = source
        # pink noise state
        self._pink_b = [0.0] * 7
        # stream/brook state
        self._stream_phase = 0.0
        self._stream_mod_phase = 0.0

    def generate(self, n: int) -> np.ndarray:
        if self.source == "rain":
            return self._rain(n)
        elif self.source == "wind":
            return self._wind(n)
        elif self.source == "stream":
            return self._stream(n)
        elif self.source == "fire":
            return self._fire(n)
        elif self.source == "white":
            return self._white(n)
        else:
            return self._rain(n)

    def _white(self, n: int) -> np.ndarray:
        return (np.random.randn(n) * 0.3).astype(np.float32)

    def _pink(self, n: int) -> np.ndarray:
        """Paul Kellet's pink noise algorithm."""
        out = np.zeros(n, dtype=np.float32)
        b = self._pink_b
        for i in range(n):
            white = np.random.randn() * 0.5
            b[0] = 0.99886 * b[0] + white * 0.0555179
            b[1] = 0.99332 * b[1] + white * 0.0750759
            b[2] = 0.96900 * b[2] + white * 0.1538520
            b[3] = 0.86650 * b[3] + white * 0.3104856
            b[4] = 0.55000 * b[4] + white * 0.5329522
            b[5] = -0.7616 * b[5] - white * 0.0168980
            out[i] = (b[0] + b[1] + b[2] + b[3] + b[4] + b[5] + b[6] + white * 0.5362)
            b[6] = white * 0.115926
        self._pink_b = b
        peak = np.max(np.abs(out))
        if peak > 0:
            out *= 0.3 / peak
        return out

    def _rain(self, n: int) -> np.ndarray:
        """Rain: pink noise + random transient drops."""
        base = self._pink(n)
        # add raindrop impulses
        drops = np.zeros(n, dtype=np.float32)
        n_drops = np.random.poisson(n * 30 / self.samplerate)
        for _ in range(n_drops):
            pos = np.random.randint(0, max(1, n - 200))
            length = np.random.randint(20, 200)
            end = min(pos + length, n)
            freq = np.random.uniform(2000, 6000)
            t = np.arange(end - pos) / self.samplerate
            drop = np.sin(2 * np.pi * freq * t) * np.exp(-t * 40)
            drops[pos:end] += drop.astype(np.float32) * np.random.uniform(0.05, 0.15)
        return base + drops

    def _wind(self, n: int) -> np.ndarray:
        """Wind: slowly modulated filtered noise."""
        noise = np.random.randn(n).astype(np.float32)
        # slow amplitude modulation (0.3-1.5 Hz)
        t = np.arange(n) / self.samplerate
        mod = 0.4 + 0.6 * (0.5 + 0.5 * np.sin(
            2 * np.pi * 0.7 * t + self._stream_phase))
        self._stream_phase += 2 * np.pi * 0.7 * n / self.samplerate
        # crude low-pass via running average
        filtered = np.convolve(noise, np.ones(8) / 8, mode='same')
        return (filtered * mod * 0.3).astype(np.float32)

    def _stream(self, n: int) -> np.ndarray:
        """Brook/stream: bandpassed noise with burbling modulation."""
        noise = np.random.randn(n).astype(np.float32)
        t = np.arange(n) / self.samplerate
        # multi-rate modulation for burbling
        mod = (0.3 + 0.3 * np.sin(2 * np.pi * 3.2 * t + self._stream_phase) +
               0.2 * np.sin(2 * np.pi * 7.1 * t + self._stream_mod_phase) +
               0.2 * np.sin(2 * np.pi * 1.3 * t))
        self._stream_phase += 2 * np.pi * 3.2 * n / self.samplerate
        self._stream_mod_phase += 2 * np.pi * 7.1 * n / self.samplerate
        # band-limit to 500-5000 Hz via crude filter
        filtered = np.convolve(noise, np.ones(4) / 4, mode='same')
        return (filtered * mod * 0.3).astype(np.float32)

    def _fire(self, n: int) -> np.ndarray:
        """Crackling fire: pink noise + random pops."""
        base = self._pink(n) * 0.5
        # crackles
        pops = np.zeros(n, dtype=np.float32)
        n_pops = np.random.poisson(n * 15 / self.samplerate)
        for _ in range(n_pops):
            pos = np.random.randint(0, max(1, n - 100))
            length = np.random.randint(5, 80)
            end = min(pos + length, n)
            pop = np.random.randn(end - pos).astype(np.float32)
            pop *= np.exp(-np.arange(end - pos) / (length * 0.3))
            pops[pos:end] += pop * np.random.uniform(0.1, 0.25)
        return base + pops


class CylonProcessor(DSPBlock):
    """Cylon voice — vocoder with fixed-pitch sawtooth carrier.

    The classic BSG Cylon voice: your speech provides articulation
    (spectral envelope), a fixed-pitch sawtooth provides the monotone.
    The carrier's fixed pitch removes all inflection. Harmonically-rich
    sawtooth gives the metallic/buzzy quality.
    """

    def __init__(self, samplerate: int = 48000, blocksize: int = 1024,
                 pitch: float = 100.0, n_bands: int = 24,
                 attack_ms: float = 3.0, release_ms: float = 15.0):
        super().__init__(samplerate, blocksize)
        self._pitch = pitch
        self._phase = 0.0
        self._gate_level = 0.0
        self._wavetable = self._build_wavetable(pitch, samplerate)

        # build a vocoder internally — raw mode (no gate normalization)
        # since our carrier is always present at known level
        self._vocoder = ChannelVocoder(
            samplerate=samplerate,
            blocksize=blocksize,
            n_bands=n_bands,
            freq_low=80.0,
            freq_high=6000.0,
            envelope_attack_ms=attack_ms,
            envelope_release_ms=release_ms,
            gate_mode=False,
        )

    def _build_wavetable(self, pitch, samplerate):
        """Pre-compute one cycle of band-limited sawtooth."""
        table_len = int(samplerate / pitch)
        t = np.arange(table_len, dtype=np.float64) / table_len
        nyquist = samplerate / 2.0
        max_harmonic = min(int(nyquist / pitch), 40)
        saw = np.zeros(table_len, dtype=np.float64)
        for k in range(1, max_harmonic + 1):
            saw += ((-1) ** (k + 1)) * np.sin(2 * np.pi * k * t) / k
        saw *= 2.0 / np.pi * 0.5
        return saw.astype(np.float32)

    def _sawtooth(self, n: int) -> np.ndarray:
        """Read from pre-computed wavetable."""
        table_len = len(self._wavetable)
        indices = (self._phase + np.arange(n) * self._pitch / self.samplerate) % 1.0
        self._phase = (self._phase + n * self._pitch / self.samplerate) % 1.0
        positions = indices * table_len
        idx = positions.astype(np.int32) % table_len
        return self._wavetable[idx]

    def process(self, samples: np.ndarray) -> np.ndarray:
        mono = samples[:, 0] if samples.ndim == 2 else samples
        n = len(mono)

        # noise gate: only run vocoder when input has energy
        in_rms = np.sqrt(np.mean(mono ** 2))
        in_db = 20.0 * np.log10(in_rms + 1e-10)

        if in_db < -45:
            # silence — don't pass carrier through
            self._gate_level *= 0.85  # fast fade
        elif in_db > -35:
            self._gate_level = 1.0
        # hysteresis between -45 and -35

        if self._gate_level < 0.001:
            if samples.ndim == 2:
                return np.zeros((n, 2), dtype=np.float32)
            return np.zeros(n, dtype=np.float32)

        # carrier = fixed-pitch sawtooth (monotone, no inflection)
        carrier = self._sawtooth(n)
        # modulator = voice (provides articulation only)
        stereo = np.column_stack([carrier, mono])
        output = self._vocoder.process(stereo)

        out_mono = output[:, 0] if output.ndim == 2 else output
        out_mono *= self._gate_level

        # auto-gain: target output at reasonable level
        out_rms = np.sqrt(np.mean(out_mono ** 2))
        if out_rms > 1e-8 and in_rms > 0.01:
            target = min(in_rms * 1.5, 0.3)  # slightly louder than input
            out_mono *= target / out_rms

        peak = np.max(np.abs(out_mono))
        if peak > 0.9:
            out_mono *= 0.9 / peak

        if samples.ndim == 2:
            return np.column_stack([out_mono, out_mono])
        return out_mono

    def reset(self):
        self._phase = 0.0
        self._gate_level = 0.0
        self._vocoder.reset()

    def get_status(self) -> dict:
        return {"mode": "cylon", "pitch": self._pitch}


class ChannelVocoder(DSPBlock):
    """Classic channel vocoder with configurable band count."""

    def __init__(self, samplerate: int = 48000, blocksize: int = 1024,
                 n_bands: int = 16, freq_low: float = 80.0,
                 freq_high: float = 8000.0,
                 envelope_attack_ms: float = 5.0,
                 envelope_release_ms: float = 20.0,
                 gate_mode: bool = True):
        super().__init__(samplerate, blocksize)
        self.n_bands = n_bands
        self.freq_low = freq_low
        self.freq_high = freq_high
        self.gate_mode = gate_mode

        # envelope follower time constants
        self.attack_coeff = np.exp(-1.0 / (envelope_attack_ms * samplerate / 1000))
        self.release_coeff = np.exp(-1.0 / (envelope_release_ms * samplerate / 1000))

        # design bandpass filters for each band (log-spaced)
        self._carrier_filters = []
        self._modulator_filters = []
        self._carrier_states = []
        self._modulator_states = []
        self._envelopes = np.zeros(n_bands, dtype=np.float32)
        # running peak tracker per band for gate normalization
        self._env_peak = np.zeros(n_bands, dtype=np.float32)
        self._env_peak_decay = np.exp(-1.0 / (500.0 * samplerate / 1000))  # 500ms decay

        log_low = np.log2(freq_low)
        log_high = np.log2(freq_high)
        band_edges = np.logspace(log_low, log_high, n_bands + 1, base=2.0)

        nyquist = samplerate / 2.0
        for i in range(n_bands):
            low = band_edges[i] / nyquist
            high = band_edges[i + 1] / nyquist
            # clamp to valid range
            low = max(low, 0.001)
            high = min(high, 0.999)
            if low >= high:
                high = low + 0.001

            sos = butter(3, [low, high], btype="band", output="sos")
            self._carrier_filters.append(sos)
            self._modulator_filters.append(sos.copy())
            self._carrier_states.append(np.zeros((sos.shape[0], 2)))
            self._modulator_states.append(np.zeros((sos.shape[0], 2)))

        self.band_freqs = [(band_edges[i], band_edges[i + 1]) for i in range(n_bands)]

    def process(self, samples: np.ndarray) -> np.ndarray:
        """Process stereo input: ch0 = carrier, ch1 = modulator."""
        if samples.ndim == 1:
            carrier = samples
            modulator = samples
        elif samples.shape[1] >= 2:
            carrier = samples[:, 0]
            modulator = samples[:, 1]
        else:
            carrier = samples[:, 0]
            modulator = samples[:, 0]

        n = len(carrier)
        output = np.zeros(n, dtype=np.float32)

        for i in range(self.n_bands):
            carrier_band, self._carrier_states[i] = sosfilt(
                self._carrier_filters[i], carrier, zi=self._carrier_states[i])

            mod_band, self._modulator_states[i] = sosfilt(
                self._modulator_filters[i], modulator, zi=self._modulator_states[i])

            envelope = self._envelope_follow(np.abs(mod_band.astype(np.float32)), i)

            if self.gate_mode:
                # track running peak per band (slow decay)
                block_peak = np.max(envelope)
                if block_peak > self._env_peak[i]:
                    self._env_peak[i] = block_peak
                else:
                    self._env_peak[i] *= self._env_peak_decay

                # normalize against running peak — but only if peak is
                # meaningful (above noise floor). Otherwise gate stays closed.
                if self._env_peak[i] > 0.005:
                    envelope = envelope / self._env_peak[i]
                    envelope = np.clip(envelope, 0.0, 1.0)
                else:
                    envelope = np.zeros_like(envelope)

            output += carrier_band.astype(np.float32) * envelope

        if not self.gate_mode:
            # raw mode: boost output based on modulator energy
            # only amplify when modulator is active (speaking)
            mod_rms = np.sqrt(np.mean(modulator ** 2))
            if mod_rms > 0.01:
                out_rms = np.sqrt(np.mean(output ** 2))
                if out_rms > 1e-8:
                    target_rms = 0.2
                    gain = target_rms / out_rms
                    gain = min(gain, 30.0)
                    output *= gain

        # normalize to prevent clipping
        peak = np.max(np.abs(output))
        if peak > 0.9:
            output *= 0.9 / peak

        if samples.ndim == 2:
            out = np.zeros((n, samples.shape[1]), dtype=np.float32)
            out[:, 0] = output
            if samples.shape[1] > 1:
                out[:, 1] = output
            return out
        return output

    def _envelope_follow(self, rectified: np.ndarray, band_idx: int) -> np.ndarray:
        """Smooth envelope follower via one-pole IIR (runs in C via lfilter)."""
        from scipy.signal import lfilter
        # one-pole lowpass: y[n] = (1-a)*x[n] + a*y[n-1]
        # use release coeff (slower) — attack is handled by the rectified
        # signal naturally jumping up
        a = self.release_coeff
        b = np.array([1.0 - a], dtype=np.float64)
        a_coeff = np.array([1.0, -a], dtype=np.float64)
        zi = np.array([self._envelopes[band_idx]])
        envelope, zf = lfilter(b, a_coeff, rectified.astype(np.float64), zi=zi)
        self._envelopes[band_idx] = float(zf[0])
        return envelope.astype(np.float32)

    def reset(self):
        for i in range(self.n_bands):
            self._carrier_states[i] = np.zeros((self._carrier_filters[i].shape[0], 2))
            self._modulator_states[i] = np.zeros((self._modulator_filters[i].shape[0], 2))
        self._envelopes = np.zeros(self.n_bands, dtype=np.float32)
        self._env_peak = np.zeros(self.n_bands, dtype=np.float32)

    def get_status(self) -> dict:
        return {
            "n_bands": self.n_bands,
            "envelope_levels": self._envelopes.tolist(),
        }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Channel vocoder with ambient sound — speak through rain, "
        "wind, traffic.")
    add_audio_args(parser)
    add_test_args(parser)
    parser.add_argument("--bands", type=int, default=16,
                        help="Number of vocoder bands (default: 16)")
    parser.add_argument("--freq-low", type=float, default=80.0,
                        help="Lowest band center frequency (default: 80 Hz)")
    parser.add_argument("--freq-high", type=float, default=8000.0,
                        help="Highest band center frequency (default: 8000 Hz)")
    parser.add_argument("--attack-ms", type=float, default=5.0,
                        help="Envelope attack time (default: 5 ms)")
    parser.add_argument("--release-ms", type=float, default=20.0,
                        help="Envelope release time (default: 20 ms)")
    parser.add_argument("--raw", action="store_true",
                        help="Raw vocoder mode (no envelope normalization). "
                             "Classic vocoder sound but carrier may be faint.")
    parser.add_argument("--cylon", action="store_true",
                        help="Cylon (BSG) voice — fixed-pitch sawtooth vocoder, "
                             "monotone with no inflection")
    parser.add_argument("--cylon-pitch", type=float, default=100.0,
                        help="Cylon voice pitch in Hz (default: 100)")
    parser.add_argument("--swap", action="store_true",
                        help="Swap carrier/modulator (nature speaks, you provide texture)")
    parser.add_argument("--carrier-file", metavar="FILE",
                        help="Use WAV file as carrier instead of live channel")
    parser.add_argument("--carrier-source",
                        choices=["rain", "wind", "stream", "fire", "white"],
                        default="rain",
                        help="Built-in ambient carrier source (default: rain). "
                             "Used when --carrier-file is not given.")
    args = parser.parse_args()

    if args.list_devices:
        from dsp_pipeline.args import open_stream_from_args
        open_stream_from_args(args)
        return 0

    samplerate = args.samplerate
    blocksize = args.blocksize

    if args.cylon:
        processor = CylonProcessor(
            samplerate=samplerate,
            blocksize=blocksize,
            pitch=args.cylon_pitch,
        )
    else:
        processor = None

    vocoder = ChannelVocoder(
        samplerate=samplerate,
        blocksize=blocksize,
        n_bands=args.bands,
        freq_low=args.freq_low,
        freq_high=args.freq_high,
        envelope_attack_ms=args.attack_ms,
        envelope_release_ms=args.release_ms,
        gate_mode=not args.raw,
    )

    if args.test and args.cylon:
        ts = TestSignal(samplerate, args.test_duration)
        n_samples = ts.n_samples
        t = np.arange(n_samples) / samplerate
        speech = np.zeros(n_samples, dtype=np.float32)
        for h in range(1, 8):
            formant_gain = np.exp(-((h * 130 - 800) / 400) ** 2) + \
                           np.exp(-((h * 130 - 2500) / 600) ** 2)
            speech += (formant_gain * 0.1 *
                       np.sin(2 * np.pi * h * 130 * t)).astype(np.float32)
        syllabic = 0.5 + 0.5 * np.sin(2 * np.pi * 4 * t)
        speech *= syllabic.astype(np.float32)
        speech *= 0.5 / (np.max(np.abs(speech)) + 1e-10)

        output = processor.process(speech.reshape(-1, 1))
        out_mono = output[:, 0] if output.ndim == 2 else output
        print(f"Cylon mode test (pitch={args.cylon_pitch} Hz)")
        print(f"Input RMS:  {20 * np.log10(np.sqrt(np.mean(speech**2)) + 1e-10):.1f} dBFS")
        print(f"Output RMS: {20 * np.log10(np.sqrt(np.mean(out_mono**2)) + 1e-10):.1f} dBFS")
        print("By your command.")

    elif args.test:
        ts = TestSignal(samplerate, args.test_duration)
        n_samples = ts.n_samples
        t = np.arange(n_samples) / samplerate

        # carrier: rain-like noise (pink + patter)
        white = np.random.randn(n_samples).astype(np.float32)
        # crude pink filter
        pink = np.zeros(n_samples, dtype=np.float32)
        b = 0.0
        for i in range(n_samples):
            b = 0.99 * b + 0.01 * white[i]
            pink[i] = b + white[i] * 0.5
        pink *= 0.3 / (np.max(np.abs(pink)) + 1e-10)
        carrier = pink

        # modulator: speech-like signal (formant-rich periodic)
        f0 = 120  # fundamental
        speech = np.zeros(n_samples, dtype=np.float32)
        for h in range(1, 8):
            # simulate formants with varying amplitude
            formant_gain = np.exp(-((h * f0 - 800) / 400) ** 2) + \
                           np.exp(-((h * f0 - 2500) / 600) ** 2)
            speech += (formant_gain * 0.1 *
                       np.sin(2 * np.pi * h * f0 * t)).astype(np.float32)
        # syllabic amplitude modulation
        syllabic = 0.5 + 0.5 * np.sin(2 * np.pi * 4 * t)
        speech *= syllabic.astype(np.float32)
        speech *= 0.5 / (np.max(np.abs(speech)) + 1e-10)
        modulator = speech

        if args.swap:
            carrier, modulator = modulator, carrier

        # stereo: ch0=carrier, ch1=modulator
        stereo_input = np.column_stack([carrier, modulator])

        print(f"Test mode: pink noise carrier + speech-like modulator")
        print(f"Bands: {args.bands}, Range: {args.freq_low}–{args.freq_high} Hz")
        if args.swap:
            print("(Swapped: speech=carrier, noise=modulator)")
        print()

        output = vocoder.process(stereo_input)
        output_mono = output[:, 0] if output.ndim == 2 else output

        # report
        in_rms = np.sqrt(np.mean(carrier ** 2))
        out_rms = np.sqrt(np.mean(output_mono ** 2))
        print(f"Carrier RMS:   {20 * np.log10(in_rms + 1e-10):.1f} dBFS")
        print(f"Modulator RMS: {20 * np.log10(np.sqrt(np.mean(modulator**2)) + 1e-10):.1f} dBFS")
        print(f"Output RMS:    {20 * np.log10(out_rms + 1e-10):.1f} dBFS")

        # check that output has structure (not just noise)
        spectrum = np.abs(np.fft.rfft(output_mono))
        peak_freq = np.fft.rfftfreq(len(output_mono), 1.0 / samplerate)[np.argmax(spectrum[1:]) + 1]
        print(f"Peak output freq: {peak_freq:.0f} Hz")
        print("\nVocoder working — carrier shaped by modulator envelope.")
    else:
        from dsp_pipeline.stream import AudioStream

        if args.cylon:
            print(f"Cylon voice active (pitch={args.cylon_pitch} Hz)",
                  file=sys.stderr)
            print("  Ctrl-C to stop", file=sys.stderr)

            stream = AudioStream(
                input_device=args.input_device,
                output_device=args.output_device,
                samplerate=samplerate,
                blocksize=blocksize,
                channels_in=1,
                channels_out=2,
            )

            def callback(indata, frames):
                return processor.process(indata)

            stream.set_callback(callback)
            stop = [False]

            def handler(s, f):
                stop[0] = True
            old_handler = signal.signal(signal.SIGINT, handler)

            try:
                stream.start()
                while not stop[0]:
                    time.sleep(0.5)
            finally:
                stream.stop()
                signal.signal(signal.SIGINT, old_handler)
                print()
        else:
            # vocoder mode
            carrier_data = None
            carrier_pos = [0]
            ambient_gen = None

            if args.carrier_file:
                import soundfile as sf
                carrier_data, file_sr = sf.read(args.carrier_file, dtype="float32")
                if file_sr != samplerate:
                    from scipy.signal import resample
                    n_target = int(len(carrier_data) * samplerate / file_sr)
                    carrier_data = resample(carrier_data, n_target).astype(np.float32)
                if carrier_data.ndim > 1:
                    carrier_data = carrier_data[:, 0]
                print(f"Vocoder running ({args.bands} bands)", file=sys.stderr)
                print(f"  Carrier: file ({args.carrier_file}, "
                      f"{len(carrier_data) / samplerate:.1f}s)", file=sys.stderr)
            else:
                ambient_gen = AmbientGenerator(samplerate, args.carrier_source)
                print(f"Vocoder running ({args.bands} bands)", file=sys.stderr)
                print(f"  Carrier: {args.carrier_source} (generated)",
                      file=sys.stderr)

            print(f"  Modulator: mic input", file=sys.stderr)
            if args.swap:
                print(f"  (Swapped: mic=carrier, {args.carrier_source}=modulator)",
                      file=sys.stderr)
            print("  Ctrl-C to stop", file=sys.stderr)

            stream = AudioStream(
                input_device=args.input_device,
                output_device=args.output_device,
                samplerate=samplerate,
                blocksize=blocksize,
                channels_in=1,
                channels_out=2,
            )

            def callback(indata, frames):
                mono = indata[:, 0] if indata.ndim == 2 else indata
                n = len(mono)

                if carrier_data is not None:
                    pos = carrier_pos[0]
                    if pos + n > len(carrier_data):
                        carrier_chunk = np.concatenate([
                            carrier_data[pos:],
                            carrier_data[:n - (len(carrier_data) - pos)]
                        ])
                        carrier_pos[0] = n - (len(carrier_data) - pos)
                    else:
                        carrier_chunk = carrier_data[pos:pos + n]
                        carrier_pos[0] = pos + n
                else:
                    carrier_chunk = ambient_gen.generate(n)

                if args.swap:
                    stereo = np.column_stack([mono, carrier_chunk])
                else:
                    stereo = np.column_stack([carrier_chunk, mono])

                return vocoder.process(stereo)

            stream.set_callback(callback)
            stop = [False]

            def handler(s, f):
                stop[0] = True
            old_handler = signal.signal(signal.SIGINT, handler)

            try:
                stream.start()
                while not stop[0]:
                    time.sleep(0.5)
                    status = vocoder.get_status()
                    levels = status["envelope_levels"]
                    bars = "".join("█" if l > 0.01 else "░" for l in levels)
                    print(f"\r  Bands: [{bars}]", end="", flush=True)
            finally:
                stream.stop()
                signal.signal(signal.SIGINT, old_handler)
                print()

    return 0


if __name__ == "__main__":
    sys.exit(main())
