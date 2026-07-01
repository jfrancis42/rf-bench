#!/usr/bin/env python3
"""
mic_response.py — Microphone frequency response measurement.

Measures a microphone's frequency response by playing a known test signal
through a speaker and recording it with the microphone under test.
Compensates for the speaker+room response using a reference measurement
or a known calibration file.

Methods:
- Log sweep (default): play swept sine, deconvolve
- MLS: Maximum Length Sequence impulse response
- Pink noise: average spectrum over time
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime
from pathlib import Path

import numpy as np
from scipy.signal import get_window, firwin, lfilter

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from dsp_pipeline import TestSignal, add_audio_args, add_test_args

import warnings
warnings.filterwarnings("ignore", message="Unable to import Axes3D")
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt


def generate_mls(order: int = 16) -> np.ndarray:
    """Generate a Maximum Length Sequence (2^order - 1 samples)."""
    n = 2 ** order - 1
    # LFSR with taps for order 16: [16, 15, 13, 4]
    taps = {16: [16, 15, 13, 4], 14: [14, 13, 12, 2],
            12: [12, 11, 10, 4], 10: [10, 7]}
    tap_list = taps.get(order, [order, order - 1])
    reg = [1] * order
    seq = np.zeros(n, dtype=np.float32)
    for i in range(n):
        seq[i] = 2.0 * reg[-1] - 1.0  # map 0/1 → -1/+1
        feedback = 0
        for t in tap_list:
            feedback ^= reg[t - 1]
        reg = [feedback] + reg[:-1]
    return seq


def cross_correlate_align(reference: np.ndarray, captured: np.ndarray) -> int:
    """Find delay between reference and captured using cross-correlation."""
    n = max(len(reference), len(captured))
    X = np.fft.rfft(reference, n=2 * n)
    Y = np.fft.rfft(captured, n=2 * n)
    cc = np.fft.irfft(Y * np.conj(X))
    return int(np.argmax(np.abs(cc)))


def smooth_spectrum(freqs: np.ndarray, magnitude_db: np.ndarray,
                    octave_fraction: float = 3.0) -> np.ndarray:
    """Apply fractional-octave smoothing to spectrum."""
    smoothed = np.copy(magnitude_db)
    for i, f in enumerate(freqs):
        if f <= 0:
            continue
        f_low = f / (2 ** (1.0 / (2 * octave_fraction)))
        f_high = f * (2 ** (1.0 / (2 * octave_fraction)))
        mask = (freqs >= f_low) & (freqs <= f_high)
        if np.any(mask):
            smoothed[i] = np.mean(magnitude_db[mask])
    return smoothed


def measure_sweep(captured: np.ndarray, reference: np.ndarray,
                  samplerate: int) -> tuple[np.ndarray, np.ndarray]:
    """Compute frequency response from sweep using deconvolution."""
    n = min(len(captured), len(reference))
    captured = captured[:n]
    reference = reference[:n]

    # align
    delay = cross_correlate_align(reference, captured)
    if delay > 0 and delay < n // 2:
        captured = np.roll(captured, -delay)

    window = get_window("hann", n)
    X = np.fft.rfft(reference * window)
    Y = np.fft.rfft(captured * window)

    # Wiener deconvolution
    eps = np.max(np.abs(X)) ** 2 * 1e-6
    H = Y * np.conj(X) / (np.abs(X) ** 2 + eps)
    freqs = np.fft.rfftfreq(n, 1.0 / samplerate)
    magnitude_db = 20 * np.log10(np.abs(H) + 1e-10)
    return freqs, magnitude_db


def measure_mls(captured: np.ndarray, mls_seq: np.ndarray,
                samplerate: int) -> tuple[np.ndarray, np.ndarray]:
    """Compute frequency response from MLS via circular cross-correlation."""
    n = len(mls_seq)
    captured = captured[:n]

    # circular cross-correlation gives impulse response
    X = np.fft.rfft(mls_seq, n=n)
    Y = np.fft.rfft(captured, n=n)
    ir = np.fft.irfft(Y * np.conj(X), n=n) / n

    # window the IR and compute frequency response
    ir_windowed = ir[:n // 4] * get_window("hann", n // 4)
    H = np.fft.rfft(ir_windowed)
    freqs = np.fft.rfftfreq(n // 4, 1.0 / samplerate)
    magnitude_db = 20 * np.log10(np.abs(H) + 1e-10)
    return freqs, magnitude_db


def measure_pink_noise(captured: np.ndarray, samplerate: int,
                       n_averages: int = 16) -> tuple[np.ndarray, np.ndarray]:
    """Estimate frequency response from pink noise using averaged spectrum."""
    n = len(captured)
    seg_len = n // n_averages
    window = get_window("hann", seg_len)
    accumulator = np.zeros(seg_len // 2 + 1)

    for i in range(n_averages):
        seg = captured[i * seg_len:(i + 1) * seg_len]
        if len(seg) < seg_len:
            break
        spectrum = np.abs(np.fft.rfft(seg * window))
        accumulator += spectrum ** 2

    accumulator /= n_averages
    freqs = np.fft.rfftfreq(seg_len, 1.0 / samplerate)
    magnitude_db = 10 * np.log10(accumulator + 1e-10)

    # pink noise has -3 dB/octave slope — subtract to flatten
    pink_correction = np.zeros_like(freqs)
    pink_correction[1:] = 10 * np.log10(freqs[1:] / freqs[1])
    magnitude_db -= pink_correction
    return freqs, magnitude_db


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Microphone frequency response measurement.")
    add_audio_args(parser)
    add_test_args(parser)
    parser.add_argument("--method", choices=["sweep", "mls", "pink"],
                        default="sweep",
                        help="Measurement method (default: sweep)")
    parser.add_argument("--duration", type=float, default=5.0,
                        help="Test signal duration in seconds (default: 5)")
    parser.add_argument("--reference", metavar="JSON",
                        help="Reference calibration JSON (from soundcard-cal or "
                        "previous run with known-flat mic)")
    parser.add_argument("--compensate", metavar="JSON",
                        help="Speaker response to subtract (e.g. from soundcard-cal "
                        "loopback)")
    parser.add_argument("--smoothing", type=float, default=3.0,
                        help="Octave-fraction smoothing (default: 1/3 octave)")
    parser.add_argument("--pdf", metavar="FILE",
                        help="Output PDF report")
    parser.add_argument("--csv", metavar="FILE",
                        help="Output CSV data")
    parser.add_argument("--output-json", metavar="FILE",
                        help="Output mic response as calibration JSON")
    args = parser.parse_args()

    if args.list_devices:
        from dsp_pipeline.args import open_stream_from_args
        open_stream_from_args(args)
        return 0

    samplerate = args.samplerate
    duration = args.duration

    if args.test:
        print("Test mode: simulating mic with bass roll-off and presence peak")
        ts = TestSignal(samplerate, duration)

        if args.method == "sweep":
            reference = ts.sweep(f_start=20, f_stop=20000, amplitude=0.5)
            # simulate mic: bass roll-off below 100 Hz, presence peak at 3 kHz
            t = np.arange(len(reference)) / samplerate
            captured = reference.copy()
            # HPF roll-off simulation
            b = firwin(127, 80.0, fs=samplerate, pass_zero=False)
            captured = lfilter(b, 1.0, captured).astype(np.float32)
            # add presence peak (narrow boost)
            boost_freq = 3000.0
            boost = 0.15 * np.sin(2 * np.pi * boost_freq * t[:len(captured)])
            captured = captured + captured * boost * 0.3
            captured += ts.noise(amplitude=0.0005)[:len(captured)]
            freqs, magnitude_db = measure_sweep(captured, reference, samplerate)
        elif args.method == "mls":
            mls_seq = generate_mls(order=16)
            # pad/truncate to duration
            n_samples = int(duration * samplerate)
            if len(mls_seq) < n_samples:
                reference = np.tile(mls_seq, n_samples // len(mls_seq) + 1)[:n_samples]
            else:
                reference = mls_seq[:n_samples]
            captured = reference.copy()
            b = firwin(127, 80.0, fs=samplerate, pass_zero=False)
            captured = lfilter(b, 1.0, captured).astype(np.float32)
            captured += np.random.randn(len(captured)).astype(np.float32) * 0.001
            freqs, magnitude_db = measure_mls(captured, mls_seq, samplerate)
        else:  # pink
            # generate pink noise (1/f spectrum)
            n_samples = int(duration * samplerate)
            white = np.random.randn(n_samples).astype(np.float32)
            # shape to pink via -3 dB/octave filter
            fft_white = np.fft.rfft(white)
            pink_freqs = np.fft.rfftfreq(n_samples, 1.0 / samplerate)
            pink_filter = np.ones_like(pink_freqs)
            pink_filter[1:] = 1.0 / np.sqrt(pink_freqs[1:] / pink_freqs[1])
            reference = np.fft.irfft(fft_white * pink_filter, n=n_samples).astype(np.float32)
            reference *= 0.3 / (np.max(np.abs(reference)) + 1e-10)
            captured = reference.copy()
            b = firwin(127, 80.0, fs=samplerate, pass_zero=False)
            captured = lfilter(b, 1.0, captured).astype(np.float32)
            freqs, magnitude_db = measure_pink_noise(captured, samplerate)
    else:
        import sounddevice as sd
        print("Microphone response measurement", file=sys.stderr)
        print(f"Method: {args.method}, Duration: {duration}s", file=sys.stderr)
        print("Place mic near speaker in quiet environment.", file=sys.stderr)
        print()

        ts = TestSignal(samplerate, duration)

        if args.method == "sweep":
            reference = ts.sweep(f_start=20, f_stop=20000, amplitude=0.5)
            captured = sd.playrec(reference.reshape(-1, 1),
                                  samplerate=samplerate,
                                  input_mapping=[1], output_mapping=[1],
                                  device=(args.input_device, args.output_device),
                                  dtype="float32")
            sd.wait()
            captured = captured.flatten()
            freqs, magnitude_db = measure_sweep(captured, reference, samplerate)
        elif args.method == "mls":
            mls_seq = generate_mls(order=16)
            n_samples = int(duration * samplerate)
            if len(mls_seq) < n_samples:
                play_signal = np.tile(mls_seq, n_samples // len(mls_seq) + 1)[:n_samples]
            else:
                play_signal = mls_seq[:n_samples]
            play_signal *= 0.5
            captured = sd.playrec(play_signal.reshape(-1, 1),
                                  samplerate=samplerate,
                                  input_mapping=[1], output_mapping=[1],
                                  device=(args.input_device, args.output_device),
                                  dtype="float32")
            sd.wait()
            captured = captured.flatten()
            freqs, magnitude_db = measure_mls(captured, mls_seq, samplerate)
        else:  # pink
            n_samples = int(duration * samplerate)
            white = np.random.randn(n_samples).astype(np.float32)
            fft_white = np.fft.rfft(white)
            pink_freqs = np.fft.rfftfreq(n_samples, 1.0 / samplerate)
            pink_filter = np.ones_like(pink_freqs)
            pink_filter[1:] = 1.0 / np.sqrt(pink_freqs[1:] / pink_freqs[1])
            play_signal = np.fft.irfft(fft_white * pink_filter, n=n_samples).astype(np.float32)
            play_signal *= 0.3 / (np.max(np.abs(play_signal)) + 1e-10)
            captured = sd.playrec(play_signal.reshape(-1, 1),
                                  samplerate=samplerate,
                                  input_mapping=[1], output_mapping=[1],
                                  device=(args.input_device, args.output_device),
                                  dtype="float32")
            sd.wait()
            captured = captured.flatten()
            freqs, magnitude_db = measure_pink_noise(captured, samplerate)

    # apply speaker compensation if provided
    if args.compensate:
        with open(args.compensate) as f:
            comp = json.load(f)
        comp_freqs = np.array(comp["freq_response"]["freqs_hz"])
        comp_mag = np.array(comp["freq_response"]["magnitude_db"])
        # interpolate compensation to our frequency grid
        comp_interp = np.interp(freqs, comp_freqs, comp_mag)
        magnitude_db -= comp_interp
        print("Applied speaker compensation from", args.compensate)

    # smooth
    magnitude_smoothed = smooth_spectrum(freqs, magnitude_db, args.smoothing)

    # normalize to 1 kHz = 0 dB
    idx_1k = np.argmin(np.abs(freqs - 1000))
    magnitude_smoothed -= magnitude_smoothed[idx_1k]
    magnitude_db -= magnitude_db[idx_1k]

    # print summary
    mask = (freqs >= 50) & (freqs <= 16000)
    ripple = np.max(magnitude_smoothed[mask]) - np.min(magnitude_smoothed[mask])
    mask_low = (freqs >= 20) & (freqs <= 100)
    bass_rolloff = np.min(magnitude_smoothed[mask_low]) if np.any(mask_low) else 0

    print(f"\n{'='*50}")
    print(f"Microphone Response ({args.method})")
    print(f"{'='*50}")
    print(f"Ripple (50 Hz–16 kHz): {ripple:.1f} dB")
    print(f"Bass roll-off (20–100 Hz): {bass_rolloff:.1f} dB")
    print(f"Smoothing: 1/{args.smoothing:.0f} octave")

    # CSV output
    if args.csv:
        with open(args.csv, "w") as f:
            f.write("freq_hz,magnitude_db,smoothed_db\n")
            for i in range(len(freqs)):
                if freqs[i] >= 20 and freqs[i] <= 20000:
                    f.write(f"{freqs[i]:.1f},{magnitude_db[i]:.2f},{magnitude_smoothed[i]:.2f}\n")
        print(f"CSV saved to {args.csv}")

    # JSON output (for use as compensation in other projects)
    if args.output_json:
        cal = {
            "timestamp": datetime.now().isoformat(),
            "samplerate": samplerate,
            "method": args.method,
            "smoothing_octave_fraction": args.smoothing,
            "freq_response": {
                "freqs_hz": freqs[::10].tolist(),
                "magnitude_db": magnitude_smoothed[::10].tolist(),
            },
        }
        with open(args.output_json, "w") as f:
            json.dump(cal, f, indent=2)
        print(f"Calibration JSON saved to {args.output_json}")

    # PDF output
    if args.pdf:
        fig, ax = plt.subplots(1, 1, figsize=(10, 5))
        mask = (freqs >= 20) & (freqs <= 20000)
        ax.semilogx(freqs[mask], magnitude_db[mask], "b-", alpha=0.3,
                    linewidth=0.5, label="Raw")
        ax.semilogx(freqs[mask], magnitude_smoothed[mask], "b-",
                    linewidth=1.5, label=f"1/{args.smoothing:.0f} oct smoothed")
        ax.axhline(0, color="k", linewidth=0.5, alpha=0.5)
        ax.axhline(3, color="r", linewidth=0.5, alpha=0.3, linestyle="--")
        ax.axhline(-3, color="r", linewidth=0.5, alpha=0.3, linestyle="--")
        ax.set_xlabel("Frequency (Hz)")
        ax.set_ylabel("Magnitude (dB re 1 kHz)")
        ax.set_title(f"Microphone Frequency Response ({args.method})")
        ax.set_xlim(20, 20000)
        ax.set_ylim(-20, 10)
        ax.grid(True, alpha=0.3, which="both")
        ax.legend(loc="lower right")

        fig.suptitle(f"Mic Response — {datetime.now().strftime('%Y-%m-%d %H:%M')}",
                     fontsize=11, fontweight="bold")
        plt.tight_layout()
        fig.savefig(args.pdf, dpi=150)
        plt.close(fig)
        print(f"PDF saved to {args.pdf}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
