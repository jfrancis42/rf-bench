#!/usr/bin/env python3
"""
snr_meter.py — Audio signal-to-noise ratio meter.

Real-time SNR/SINAD estimation with multiple methods:
- SINAD (signal + noise + distortion to noise + distortion) for FM
- Carrier-to-noise for AM
- Signal-present/signal-absent gated measurement for SSB
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


class SNRMeter(DSPBlock):
    """Real-time SNR / SINAD measurement."""

    def __init__(self, samplerate: int = 48000, blocksize: int = 4096,
                 method: str = "sinad", notch_freq: float = 1000.0,
                 notch_q: float = 5.0):
        super().__init__(samplerate, blocksize)
        self.method = method
        self.notch_freq = notch_freq
        self._snr_db = 0.0
        self._signal_power = 0.0
        self._noise_power = 0.0
        self._history = []

        if method == "sinad":
            # notch filter to remove fundamental for N+D measurement
            from scipy.signal import iirnotch, tf2sos
            b, a = iirnotch(notch_freq, notch_q, fs=samplerate)
            self._notch_sos = tf2sos(b, a)
            self._notch_zi = sosfilt_zi(self._notch_sos) * 0

    def process(self, samples: np.ndarray) -> np.ndarray:
        mono = samples[:, 0] if samples.ndim == 2 else samples

        if self.method == "sinad":
            self._measure_sinad(mono)
        elif self.method == "snr":
            self._measure_snr_spectral(mono)
        elif self.method == "carrier":
            self._measure_carrier_noise(mono)

        return samples  # pass through

    def _measure_sinad(self, mono: np.ndarray):
        """SINAD: ratio of (S+N+D) to (N+D). Classic FM sensitivity test."""
        # total power (S+N+D)
        total_power = np.mean(mono ** 2)

        # remove fundamental via notch → N+D
        notched, self._notch_zi = sosfilt(self._notch_sos, mono, zi=self._notch_zi)
        nd_power = np.mean(notched ** 2)

        if nd_power > 1e-12:
            self._snr_db = 10 * np.log10(total_power / nd_power)
        self._signal_power = total_power
        self._noise_power = nd_power

    def _measure_snr_spectral(self, mono: np.ndarray):
        """Spectral SNR: signal power in peak bin vs noise floor."""
        spectrum = np.abs(np.fft.rfft(mono * np.hanning(len(mono)))) ** 2
        freqs = np.fft.rfftfreq(len(mono), 1.0 / self.samplerate)

        # find peak
        peak_idx = np.argmax(spectrum)
        # signal power: peak ± 3 bins
        sig_bins = slice(max(0, peak_idx - 3), min(len(spectrum), peak_idx + 4))
        sig_power = np.sum(spectrum[sig_bins])

        # noise power: everything else
        noise_power = np.sum(spectrum) - sig_power
        if noise_power > 1e-12:
            self._snr_db = 10 * np.log10(sig_power / noise_power)
        self._signal_power = sig_power
        self._noise_power = noise_power

    def _measure_carrier_noise(self, mono: np.ndarray):
        """Carrier-to-noise: RMS of carrier vs RMS when carrier absent.

        Uses a simple energy-based estimator (signal present vs absent).
        """
        energy = np.mean(mono ** 2)
        self._history.append(energy)
        if len(self._history) > 100:
            self._history = self._history[-100:]

        # estimate noise floor from the quietest 20% of history
        sorted_hist = sorted(self._history)
        noise_est = np.mean(sorted_hist[:max(1, len(sorted_hist) // 5)])
        if noise_est > 1e-12:
            self._snr_db = 10 * np.log10(energy / noise_est)
        self._signal_power = energy
        self._noise_power = noise_est

    def get_status(self) -> dict:
        return {
            "enabled": self.enabled,
            "method": self.method,
            "snr_db": f"{self._snr_db:.1f}",
            "signal_dbfs": f"{10*np.log10(self._signal_power + 1e-12):.1f}",
            "noise_dbfs": f"{10*np.log10(self._noise_power + 1e-12):.1f}",
        }

    def reset(self):
        self._snr_db = 0.0
        self._history = []


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Audio SNR / SINAD meter.")
    add_audio_args(parser, duplex=False)
    add_test_args(parser)
    parser.add_argument("--method", choices=["sinad", "snr", "carrier"],
                        default="sinad",
                        help="Measurement method (default sinad)")
    parser.add_argument("--notch-freq", type=float, default=1000.0,
                        help="SINAD notch frequency in Hz (default 1000)")
    parser.add_argument("--duration", type=float, default=5.0,
                        help="Measurement duration in seconds (default 5)")
    parser.add_argument("--continuous", action="store_true",
                        help="Run continuously, printing updates")
    parser.add_argument("--output", metavar="CSV",
                        help="Log measurements to CSV")
    args = parser.parse_args()

    if args.list_devices:
        from dsp_pipeline.args import open_stream_from_args
        open_stream_from_args(args, duplex=False)
        return 0

    block = SNRMeter(
        samplerate=args.samplerate,
        blocksize=args.blocksize,
        method=args.method,
        notch_freq=args.notch_freq,
    )

    if args.test:
        ts = TestSignal(args.samplerate, args.duration)
        # 1 kHz tone at -10 dBFS + noise at -40 dBFS → expect ~30 dB SNR
        test_audio = ts.signal_plus_noise(freq=1000, sig_amplitude=0.3, noise_amplitude=0.01)
        pipeline = Pipeline([block], samplerate=args.samplerate, blocksize=args.blocksize)
        pipeline.process_array(test_audio.reshape(-1, 1))
        status = block.get_status()
        print(f"Method: {args.method}")
        print(f"SNR: {status['snr_db']} dB")
        print(f"Signal: {status['signal_dbfs']} dBFS")
        print(f"Noise: {status['noise_dbfs']} dBFS")
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
            csv_file.write("timestamp,snr_db,signal_dbfs,noise_dbfs\n")

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
            print(f"SNR meter ({args.method}) running... Ctrl-C to stop",
                  file=sys.stderr)
            while not stop[0]:
                time.sleep(0.5)
                status = block.get_status()
                line = f"SNR: {status['snr_db']:>7s} dB | Signal: {status['signal_dbfs']:>7s} dBFS | Noise: {status['noise_dbfs']:>7s} dBFS"
                print(f"\r{line}", end="", flush=True)
                if csv_file:
                    csv_file.write(f"{time.time():.3f},{block._snr_db:.2f},"
                                   f"{10*np.log10(block._signal_power+1e-12):.2f},"
                                   f"{10*np.log10(block._noise_power+1e-12):.2f}\n")
                if not args.continuous:
                    remaining = args.duration - 0.5
                    if remaining <= 0:
                        break
                    args.duration = remaining
        finally:
            stream.stop()
            sig_module.signal(sig_module.SIGINT, old)
            if csv_file:
                csv_file.close()
            print()

    return 0


if __name__ == "__main__":
    sys.exit(main())
