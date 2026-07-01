"""
TestSignal — synthetic signal generators for --test mode.

Each method returns a numpy array suitable for pipeline testing.
"""

from __future__ import annotations

import numpy as np


class TestSignal:
    """Factory for synthetic test signals."""

    def __init__(self, samplerate: int = 48000, duration: float = 5.0):
        self.samplerate = samplerate
        self.duration = duration
        self.n_samples = int(samplerate * duration)

    def _time(self) -> np.ndarray:
        return np.arange(self.n_samples) / self.samplerate

    def sine(self, freq: float = 1000.0, amplitude: float = 0.5) -> np.ndarray:
        """Pure sine tone."""
        t = self._time()
        return (amplitude * np.sin(2 * np.pi * freq * t)).astype(np.float32)

    def two_tone(self, f1: float = 700.0, f2: float = 1900.0, amplitude: float = 0.3) -> np.ndarray:
        """Two equal-amplitude tones (standard SSB IMD test)."""
        t = self._time()
        return (amplitude * (np.sin(2 * np.pi * f1 * t) + np.sin(2 * np.pi * f2 * t))).astype(np.float32)

    def noise(self, amplitude: float = 0.1, color: str = "white") -> np.ndarray:
        """White or pink noise."""
        rng = np.random.default_rng(42)
        white = rng.standard_normal(self.n_samples).astype(np.float32)
        if color == "pink":
            # spectral shaping: -3 dB/octave
            freqs = np.fft.rfftfreq(self.n_samples, 1.0 / self.samplerate)
            spectrum = np.fft.rfft(white)
            freqs[0] = 1.0  # avoid div by zero
            spectrum *= 1.0 / np.sqrt(freqs)
            white = np.fft.irfft(spectrum, n=self.n_samples).astype(np.float32)
        return amplitude * white / np.max(np.abs(white))

    def signal_plus_noise(
        self,
        freq: float = 800.0,
        sig_amplitude: float = 0.3,
        noise_amplitude: float = 0.1,
    ) -> np.ndarray:
        """Sine tone buried in white noise."""
        return self.sine(freq, sig_amplitude) + self.noise(noise_amplitude)

    def cw_signal(
        self,
        freq: float = 700.0,
        wpm: int = 20,
        amplitude: float = 0.4,
        noise_amplitude: float = 0.05,
    ) -> np.ndarray:
        """Simulated CW (Morse) signal: repeated dits at the given frequency."""
        t = self._time()
        dit_duration = 1.2 / wpm
        dit_samples = int(dit_duration * self.samplerate)
        space_samples = dit_samples

        envelope = np.zeros(self.n_samples, dtype=np.float32)
        pos = 0
        while pos + dit_samples < self.n_samples:
            envelope[pos:pos + dit_samples] = 1.0
            pos += dit_samples + space_samples

        # smooth edges (5 ms rise/fall)
        edge_samples = int(0.005 * self.samplerate)
        if edge_samples > 0:
            from scipy.signal import fftconvolve
            window = np.hanning(edge_samples * 2)
            window = window / window.sum()
            envelope = fftconvolve(envelope, window, mode="same").astype(np.float32)

        carrier = amplitude * np.sin(2 * np.pi * freq * t).astype(np.float32)
        signal = carrier * envelope
        if noise_amplitude > 0:
            signal += self.noise(noise_amplitude)
        return signal

    def sweep(
        self,
        f_start: float = 20.0,
        f_stop: float = 20000.0,
        amplitude: float = 0.5,
    ) -> np.ndarray:
        """Logarithmic frequency sweep."""
        t = self._time()
        phase = 2 * np.pi * f_start * self.duration / np.log(f_stop / f_start) * (
            np.exp(t / self.duration * np.log(f_stop / f_start)) - 1
        )
        return (amplitude * np.sin(phase)).astype(np.float32)

    def impulse_noise(
        self,
        base_freq: float = 800.0,
        base_amplitude: float = 0.3,
        impulse_rate: float = 5.0,
        impulse_amplitude: float = 0.9,
    ) -> np.ndarray:
        """Signal with random impulse spikes (simulates ignition noise)."""
        t = self._time()
        signal = base_amplitude * np.sin(2 * np.pi * base_freq * t).astype(np.float32)
        rng = np.random.default_rng(123)
        n_impulses = int(impulse_rate * self.duration)
        for _ in range(n_impulses):
            pos = rng.integers(0, self.n_samples)
            width = rng.integers(1, int(0.001 * self.samplerate))
            end = min(pos + width, self.n_samples)
            signal[pos:end] += impulse_amplitude * rng.choice([-1.0, 1.0])
        return np.clip(signal, -1.0, 1.0)

    def iq_signal(
        self,
        offsets_hz: list[float] | None = None,
        amplitudes: list[float] | None = None,
        noise_amplitude: float = 0.02,
    ) -> np.ndarray:
        """Stereo I/Q signal (L=I, R=Q) with multiple carriers at given offsets from DC.

        Returns shape (n_samples, 2).
        """
        if offsets_hz is None:
            offsets_hz = [-1200.0, -400.0, 600.0, 1500.0]
        if amplitudes is None:
            amplitudes = [0.3, 0.4, 0.25, 0.2]

        t = self._time()
        iq = np.zeros(self.n_samples, dtype=np.complex64)
        for freq, amp in zip(offsets_hz, amplitudes):
            iq += amp * np.exp(1j * 2 * np.pi * freq * t)

        rng = np.random.default_rng(77)
        iq += noise_amplitude * (rng.standard_normal(self.n_samples) + 1j * rng.standard_normal(self.n_samples)).astype(np.complex64)

        stereo = np.column_stack([iq.real, iq.imag]).astype(np.float32)
        return stereo

    def speech_like(
        self,
        fundamental: float = 150.0,
        amplitude: float = 0.4,
        noise_amplitude: float = 0.05,
    ) -> np.ndarray:
        """Crude speech-like signal: fundamental + formant harmonics with amplitude modulation."""
        t = self._time()
        # fundamental + harmonics with formant-like envelope
        formant_freqs = [fundamental, 2 * fundamental, 3 * fundamental, 5 * fundamental, 7 * fundamental]
        formant_amps = [1.0, 0.7, 0.5, 0.2, 0.1]
        signal = np.zeros(self.n_samples, dtype=np.float32)
        for f, a in zip(formant_freqs, formant_amps):
            signal += a * np.sin(2 * np.pi * f * t).astype(np.float32)

        # syllabic-rate AM (4 Hz)
        mod = 0.5 + 0.5 * np.sin(2 * np.pi * 4.0 * t).astype(np.float32)
        signal *= mod * amplitude / np.max(np.abs(signal))

        if noise_amplitude > 0:
            signal += self.noise(noise_amplitude)
        return signal

    def hum(self, freq: float = 60.0, harmonics: int = 10, amplitude: float = 0.3) -> np.ndarray:
        """Power-line hum with harmonics."""
        t = self._time()
        signal = np.zeros(self.n_samples, dtype=np.float32)
        for h in range(1, harmonics + 1):
            signal += (1.0 / h) * np.sin(2 * np.pi * freq * h * t).astype(np.float32)
        return amplitude * signal / np.max(np.abs(signal))

    def heterodyne(
        self,
        signal_freq: float = 800.0,
        het_freq: float = 1200.0,
        signal_amp: float = 0.4,
        het_amp: float = 0.3,
    ) -> np.ndarray:
        """Signal with an interfering heterodyne carrier."""
        t = self._time()
        return (signal_amp * np.sin(2 * np.pi * signal_freq * t) +
                het_amp * np.sin(2 * np.pi * het_freq * t)).astype(np.float32)

    def ctcss_fm(self, tone_freq: float = 100.0, voice_freq: float = 800.0) -> np.ndarray:
        """Simulated FM audio with sub-audible CTCSS tone + voice."""
        t = self._time()
        ctcss = 0.1 * np.sin(2 * np.pi * tone_freq * t)
        voice = 0.4 * np.sin(2 * np.pi * voice_freq * t)
        # syllabic AM on voice
        mod = 0.5 + 0.5 * np.sin(2 * np.pi * 3.5 * t)
        return (ctcss + voice * mod).astype(np.float32)

    def dtmf(self, digits: str = "1234", digit_duration: float = 0.1, pause: float = 0.05) -> np.ndarray:
        """DTMF tone sequence."""
        dtmf_freqs = {
            "1": (697, 1209), "2": (697, 1336), "3": (697, 1477), "A": (697, 1633),
            "4": (770, 1209), "5": (770, 1336), "6": (770, 1477), "B": (770, 1633),
            "7": (852, 1209), "8": (852, 1336), "9": (852, 1477), "C": (852, 1633),
            "*": (941, 1209), "0": (941, 1336), "#": (941, 1477), "D": (941, 1633),
        }
        samples_per_digit = int(digit_duration * self.samplerate)
        samples_per_pause = int(pause * self.samplerate)
        output = []
        for d in digits:
            if d.upper() in dtmf_freqs:
                f1, f2 = dtmf_freqs[d.upper()]
                t = np.arange(samples_per_digit) / self.samplerate
                tone = 0.3 * (np.sin(2 * np.pi * f1 * t) + np.sin(2 * np.pi * f2 * t))
                output.append(tone.astype(np.float32))
            output.append(np.zeros(samples_per_pause, dtype=np.float32))
        result = np.concatenate(output)
        if len(result) < self.n_samples:
            result = np.pad(result, (0, self.n_samples - len(result)))
        return result[:self.n_samples]
