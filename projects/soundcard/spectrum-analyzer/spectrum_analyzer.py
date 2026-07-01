#!/usr/bin/env python3
"""
spectrum_analyzer.py — Real-time audio spectrum analyzer with optional waterfall.

Live scrolling spectrum display using matplotlib with configurable FFT size,
averaging, peak hold, dBFS scale. Supports terminal text-mode bars, matplotlib
live window, headless CSV logging, and PDF snapshot output.
"""

from __future__ import annotations

import argparse
import csv
import signal
import sys
import time
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from dsp_pipeline import DSPBlock, Pipeline, TestSignal, add_audio_args, add_test_args


class SpectrumAnalyzer(DSPBlock):
    """FFT-based spectrum analyzer with averaging and peak hold."""

    def __init__(self, samplerate: int = 48000, blocksize: int = 2048,
                 fft_size: int = 4096, averaging: int = 8,
                 peak_hold: bool = False):
        super().__init__(samplerate, blocksize)
        self.fft_size = fft_size
        self.averaging = averaging
        self.peak_hold = peak_hold
        self._window = np.hanning(fft_size).astype(np.float32)
        self._avg_spectrum: np.ndarray | None = None
        self._peak_spectrum: np.ndarray | None = None
        self._block_count = 0
        self._accumulator = np.zeros(fft_size // 2 + 1, dtype=np.float64)
        self._acc_count = 0
        # ring buffer for overlap if blocksize < fft_size
        self._buffer = np.zeros(fft_size, dtype=np.float32)
        self._buf_pos = 0

    @property
    def freqs(self) -> np.ndarray:
        """Frequency axis in Hz."""
        return np.fft.rfftfreq(self.fft_size, 1.0 / self.samplerate)

    @property
    def spectrum_dbfs(self) -> np.ndarray | None:
        """Current averaged spectrum in dBFS."""
        return self._avg_spectrum

    @property
    def peak_dbfs(self) -> np.ndarray | None:
        """Peak-hold spectrum in dBFS."""
        return self._peak_spectrum

    def _compute_spectrum(self, samples: np.ndarray) -> np.ndarray:
        """Compute magnitude spectrum in dBFS from windowed samples."""
        windowed = samples[:self.fft_size] * self._window
        spectrum = np.abs(np.fft.rfft(windowed))
        # normalize: full-scale sine = 0 dBFS
        spectrum = spectrum / (self.fft_size / 2.0)
        # convert to dBFS
        with np.errstate(divide='ignore'):
            db = 20.0 * np.log10(np.maximum(spectrum, 1e-20))
        return db

    def process(self, samples: np.ndarray) -> np.ndarray:
        """Process a block — accumulate into ring buffer, compute FFT when ready."""
        mono = samples[:, 0] if samples.ndim == 2 else samples

        # fill ring buffer
        n = len(mono)
        if n >= self.fft_size:
            # block is large enough — use last fft_size samples
            self._buffer[:] = mono[-self.fft_size:]
            self._update_spectrum()
        else:
            # shift buffer left and append new samples
            self._buffer[:-n] = self._buffer[n:]
            self._buffer[-n:] = mono
            self._buf_pos += n
            if self._buf_pos >= self.fft_size:
                self._buf_pos = 0
                self._update_spectrum()

        return samples  # pass-through

    def _update_spectrum(self):
        """Compute spectrum from current buffer and update averaging/peak."""
        db = self._compute_spectrum(self._buffer)
        self._accumulator += db
        self._acc_count += 1

        if self._acc_count >= self.averaging:
            averaged = self._accumulator / self._acc_count
            self._avg_spectrum = averaged.astype(np.float32)
            self._accumulator[:] = 0
            self._acc_count = 0
            self._block_count += 1

            if self.peak_hold:
                if self._peak_spectrum is None:
                    self._peak_spectrum = self._avg_spectrum.copy()
                else:
                    self._peak_spectrum = np.maximum(self._peak_spectrum, self._avg_spectrum)

    def reset(self):
        self._avg_spectrum = None
        self._peak_spectrum = None
        self._accumulator[:] = 0
        self._acc_count = 0
        self._block_count = 0
        self._buffer[:] = 0
        self._buf_pos = 0

    def get_status(self) -> dict:
        peak_freq = None
        peak_db = None
        if self._avg_spectrum is not None:
            idx = np.argmax(self._avg_spectrum)
            peak_freq = float(self.freqs[idx])
            peak_db = float(self._avg_spectrum[idx])
        return {
            "enabled": self.enabled,
            "block_count": self._block_count,
            "peak_freq_hz": peak_freq,
            "peak_dbfs": peak_db,
        }


def _terminal_display(analyzer: SpectrumAnalyzer, width: int = 72):
    """Print text-mode spectrum bars to terminal."""
    spectrum = analyzer.spectrum_dbfs
    if spectrum is None:
        return
    freqs = analyzer.freqs

    # downsample to width bars
    n_bins = len(spectrum)
    step = max(1, n_bins // width)
    bars = []
    for i in range(0, min(n_bins, width * step), step):
        chunk = spectrum[i:i + step]
        bars.append(float(np.max(chunk)))

    # scale: -100 to 0 dBFS
    floor = -100.0
    ceil = 0.0
    max_bar_height = 20

    lines = []
    lines.append(f"  Peak: {freqs[np.argmax(spectrum)]:.0f} Hz @ {np.max(spectrum):.1f} dBFS")
    lines.append("")

    for row in range(max_bar_height, -1, -1):
        threshold = floor + (ceil - floor) * row / max_bar_height
        chars = []
        for val in bars:
            if val >= threshold:
                chars.append("█")
            else:
                chars.append(" ")
        db_label = f"{threshold:>5.0f}|"
        lines.append(db_label + "".join(chars))

    # frequency axis
    nyquist = freqs[-1]
    lines.append("      " + "-" * len(bars))
    lines.append(f"      0 Hz{' ' * (len(bars) - 12)}{nyquist:.0f} Hz")

    # clear screen and print
    sys.stdout.write("\033[2J\033[H")
    sys.stdout.write("\n".join(lines) + "\n")
    sys.stdout.flush()


def _run_matplotlib(analyzer: SpectrumAnalyzer, waterfall: bool = False,
                    duration: float | None = None):
    """Live matplotlib display."""
    import matplotlib.pyplot as plt
    from matplotlib.animation import FuncAnimation

    freqs = analyzer.freqs / 1000.0  # kHz

    if waterfall:
        fig, (ax_spec, ax_wf) = plt.subplots(2, 1, figsize=(10, 8),
                                              gridspec_kw={"height_ratios": [1, 2]})
        waterfall_data = np.full((100, len(freqs)), -120.0)
        im = ax_wf.imshow(waterfall_data, aspect="auto", origin="lower",
                          extent=[freqs[0], freqs[-1], 0, 100],
                          vmin=-100, vmax=0, cmap="inferno")
        ax_wf.set_xlabel("Frequency (kHz)")
        ax_wf.set_ylabel("Time (sweeps)")
        fig.colorbar(im, ax=ax_wf, label="dBFS")
    else:
        fig, ax_spec = plt.subplots(1, 1, figsize=(10, 5))

    line_spec, = ax_spec.plot(freqs, np.full(len(freqs), -120.0), "c-", lw=0.8)
    line_peak = None
    if analyzer.peak_hold:
        line_peak, = ax_spec.plot(freqs, np.full(len(freqs), -120.0), "r-",
                                  lw=0.5, alpha=0.7, label="peak hold")
        ax_spec.legend(loc="upper right")

    ax_spec.set_xlim(freqs[0], freqs[-1])
    ax_spec.set_ylim(-120, 0)
    ax_spec.set_xlabel("Frequency (kHz)")
    ax_spec.set_ylabel("Magnitude (dBFS)")
    ax_spec.set_title("Spectrum Analyzer")
    ax_spec.grid(True, alpha=0.3)
    fig.tight_layout()

    start_time = time.time()
    wf_row = [0]

    def update(frame):
        spectrum = analyzer.spectrum_dbfs
        if spectrum is None:
            return (line_spec,) if line_peak is None else (line_spec, line_peak)

        line_spec.set_ydata(spectrum)
        if line_peak is not None and analyzer.peak_dbfs is not None:
            line_peak.set_ydata(analyzer.peak_dbfs)

        if waterfall:
            waterfall_data[:-1] = waterfall_data[1:]
            waterfall_data[-1] = spectrum
            im.set_data(waterfall_data)
            wf_row[0] += 1

        # auto-close after duration
        if duration is not None and (time.time() - start_time) > duration:
            plt.close(fig)

        return (line_spec,) if line_peak is None else (line_spec, line_peak)

    anim = FuncAnimation(fig, update, interval=50, blit=False, cache_frame_data=False)
    plt.show()


def _capture_and_save(args, analyzer: SpectrumAnalyzer, pipeline: Pipeline,
                      test_audio: np.ndarray | None = None):
    """Capture audio, compute averaged spectrum, save PDF/CSV."""
    if test_audio is not None:
        audio = test_audio
    else:
        import sounddevice as sd
        duration = args.capture_duration
        print(f"Capturing {duration:.1f}s of audio...", file=sys.stderr)
        audio = sd.rec(int(duration * args.samplerate), samplerate=args.samplerate,
                       channels=1, dtype="float32", device=args.input_device)
        sd.wait()
        audio = audio.flatten()

    # process through pipeline in blocksize chunks
    n = len(audio)
    for start in range(0, n, args.blocksize):
        chunk = audio[start:start + args.blocksize]
        if len(chunk) < args.blocksize:
            chunk = np.pad(chunk, (0, args.blocksize - len(chunk)))
        pipeline.process_block(chunk.reshape(-1, 1))

    spectrum = analyzer.spectrum_dbfs
    if spectrum is None:
        print("ERROR: no spectrum computed (audio too short?)", file=sys.stderr)
        return 1

    freqs = analyzer.freqs

    # CSV output
    if args.log:
        csv_path = args.log
        with open(csv_path, "w", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(["freq_hz", "magnitude_dbfs"])
            for freq_hz, mag in zip(freqs, spectrum):
                writer.writerow([f"{freq_hz:.2f}", f"{mag:.2f}"])
        print(f"CSV written: {csv_path}", file=sys.stderr)

    # PDF output
    if args.output:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt

        fig, ax = plt.subplots(1, 1, figsize=(10, 5))
        ax.plot(freqs / 1000.0, spectrum, "c-", lw=0.8)
        if analyzer.peak_hold and analyzer.peak_dbfs is not None:
            ax.plot(freqs / 1000.0, analyzer.peak_dbfs, "r-", lw=0.5,
                    alpha=0.7, label="peak hold")
            ax.legend(loc="upper right")
        ax.set_xlim(freqs[0] / 1000.0, freqs[-1] / 1000.0)
        ax.set_ylim(-120, 0)
        ax.set_xlabel("Frequency (kHz)")
        ax.set_ylabel("Magnitude (dBFS)")
        ax.set_title("Audio Spectrum")
        ax.grid(True, alpha=0.3)
        fig.tight_layout()
        fig.savefig(args.output, format="pdf")
        plt.close(fig)
        print(f"PDF written: {args.output}", file=sys.stderr)

    return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Real-time audio spectrum analyzer with optional waterfall.")
    add_audio_args(parser, duplex=False)
    add_test_args(parser)

    parser.set_defaults(blocksize=2048)

    g = parser.add_argument_group("spectrum")
    g.add_argument("--fft-size", type=int, default=4096, metavar="N",
                   help="FFT size in samples (default 4096)")
    g.add_argument("--averaging", type=int, default=8, metavar="N",
                   help="Number of FFTs to average (default 8)")
    g.add_argument("--peak-hold", action="store_true",
                   help="Enable peak-hold trace")
    g.add_argument("--waterfall", action="store_true",
                   help="Show spectrogram/waterfall below the spectrum")

    g2 = parser.add_argument_group("output")
    g2.add_argument("--terminal", action="store_true",
                    help="Text-mode terminal bars instead of matplotlib")
    g2.add_argument("--log", metavar="FILE.csv",
                    help="Write averaged spectrum to CSV (non-real-time capture)")
    g2.add_argument("--output", metavar="FILE.pdf",
                    help="Save spectrum snapshot as PDF (non-real-time capture)")
    g2.add_argument("--capture-duration", type=float, default=5.0, metavar="SEC",
                    help="Seconds of audio to capture for PDF/CSV output (default 5.0)")

    args = parser.parse_args()

    if args.list_devices:
        from dsp_pipeline.args import open_stream_from_args
        open_stream_from_args(args, duplex=False)
        return 0

    analyzer = SpectrumAnalyzer(
        samplerate=args.samplerate,
        blocksize=args.blocksize,
        fft_size=args.fft_size,
        averaging=args.averaging,
        peak_hold=args.peak_hold,
    )
    pipeline = Pipeline([analyzer], samplerate=args.samplerate, blocksize=args.blocksize)

    # Non-real-time modes: PDF or CSV capture
    if args.log or args.output:
        test_audio = None
        if args.test:
            ts = TestSignal(args.samplerate, args.capture_duration)
            test_audio = ts.two_tone(700, 1900, amplitude=0.3)
            test_audio += ts.noise(amplitude=0.02)
        return _capture_and_save(args, analyzer, pipeline, test_audio)

    # Real-time modes
    if args.test:
        ts = TestSignal(args.samplerate, args.test_duration)
        test_audio = ts.two_tone(700, 1900, amplitude=0.3)
        test_audio += ts.noise(amplitude=0.02)

        # process offline and display result
        pipeline.process_array(test_audio.reshape(-1, 1))
        if args.terminal:
            _terminal_display(analyzer)
            print("\nTest complete.", file=sys.stderr)
        else:
            # show static plot
            import matplotlib.pyplot as plt
            spectrum = analyzer.spectrum_dbfs
            if spectrum is not None:
                freqs = analyzer.freqs / 1000.0
                fig, ax = plt.subplots(1, 1, figsize=(10, 5))
                ax.plot(freqs, spectrum, "c-", lw=0.8, label="averaged")
                if analyzer.peak_hold and analyzer.peak_dbfs is not None:
                    ax.plot(freqs, analyzer.peak_dbfs, "r-", lw=0.5,
                            alpha=0.7, label="peak hold")
                ax.set_xlim(freqs[0], freqs[-1])
                ax.set_ylim(-120, 0)
                ax.set_xlabel("Frequency (kHz)")
                ax.set_ylabel("Magnitude (dBFS)")
                ax.set_title("Spectrum Analyzer (test signal)")
                ax.legend(loc="upper right")
                ax.grid(True, alpha=0.3)
                fig.tight_layout()
                plt.show()
        return 0

    # Live audio mode
    from dsp_pipeline import AudioStream

    stream = AudioStream(
        input_device=args.input_device,
        samplerate=args.samplerate,
        blocksize=args.blocksize,
        channels_in=args.channels_in,
        channels_out=1,
    )

    def audio_callback(indata, frames):
        pipeline.process_block(indata)
        return None

    stream.set_callback(audio_callback)

    stop = [False]

    def sigint_handler(signum, frame):
        stop[0] = True

    old_handler = signal.signal(signal.SIGINT, sigint_handler)

    try:
        stream.start()
        print("Spectrum analyzer running (Ctrl-C to stop)...", file=sys.stderr)

        if args.terminal:
            while not stop[0]:
                time.sleep(0.1)
                _terminal_display(analyzer)
        else:
            _run_matplotlib(analyzer, waterfall=args.waterfall)
    finally:
        stream.stop()
        signal.signal(signal.SIGINT, old_handler)
        print("\nStopped.", file=sys.stderr)

    return 0


if __name__ == "__main__":
    sys.exit(main())
