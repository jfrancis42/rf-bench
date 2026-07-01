#!/usr/bin/env python3
"""
audio_loopback_null.py — Audio loopback null test.

Plays a known signal through the soundcard output, captures it back
through the input (loopback cable), aligns via cross-correlation,
subtracts the original, and measures the residual. This reveals:
- DAC/ADC nonlinearity
- Clock drift / jitter
- Added noise
- Frequency-dependent artifacts

The residual is the "error signal" of the audio system — ideally
nothing, practically a measure of system quality.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime
from pathlib import Path

import numpy as np
from scipy.signal import get_window, resample

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from dsp_pipeline import TestSignal, add_audio_args, add_test_args

import warnings
warnings.filterwarnings("ignore", message="Unable to import Axes3D")
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt


def align_signals(reference: np.ndarray, captured: np.ndarray,
                  samplerate: int) -> tuple[np.ndarray, np.ndarray, int]:
    """Align captured to reference using cross-correlation.
    Returns trimmed, aligned arrays and the delay in samples."""
    n = max(len(reference), len(captured))
    X = np.fft.rfft(reference, n=2 * n)
    Y = np.fft.rfft(captured, n=2 * n)
    cc = np.fft.irfft(Y * np.conj(X))
    delay = int(np.argmax(np.abs(cc)))
    if delay > n:
        delay -= 2 * n

    # trim both to aligned overlap region
    if delay >= 0:
        cap_aligned = captured[delay:]
        ref_aligned = reference[:len(cap_aligned)]
    else:
        ref_aligned = reference[-delay:]
        cap_aligned = captured[:len(ref_aligned)]

    # truncate to common length
    min_len = min(len(ref_aligned), len(cap_aligned))
    return ref_aligned[:min_len], cap_aligned[:min_len], delay


def compensate_gain(reference: np.ndarray, captured: np.ndarray) -> tuple[np.ndarray, float]:
    """Scale captured to match reference RMS, return scaled + gain factor."""
    ref_rms = np.sqrt(np.mean(reference ** 2))
    cap_rms = np.sqrt(np.mean(captured ** 2))
    if cap_rms < 1e-10:
        return captured, 0.0
    gain = ref_rms / cap_rms
    return captured * gain, gain


def analyze_residual(residual: np.ndarray, reference: np.ndarray,
                     samplerate: int) -> dict:
    """Analyze the null residual signal."""
    ref_rms = np.sqrt(np.mean(reference ** 2))
    res_rms = np.sqrt(np.mean(residual ** 2))
    null_depth_db = 20 * np.log10(res_rms / (ref_rms + 1e-10))

    # spectral analysis of residual
    n = len(residual)
    window = get_window("hann", n)
    res_spectrum = np.abs(np.fft.rfft(residual * window))
    ref_spectrum = np.abs(np.fft.rfft(reference * window))
    freqs = np.fft.rfftfreq(n, 1.0 / samplerate)

    # frequency-dependent null depth
    with np.errstate(divide="ignore", invalid="ignore"):
        null_vs_freq = 20 * np.log10(res_spectrum / (ref_spectrum + 1e-10))

    # peak residual frequency
    peak_idx = np.argmax(res_spectrum[1:]) + 1
    peak_freq = freqs[peak_idx]
    peak_level_db = 20 * np.log10(res_spectrum[peak_idx] / (np.max(ref_spectrum) + 1e-10))

    # crest factor of residual (indicates impulsive vs broadband)
    peak_val = np.max(np.abs(residual))
    crest_factor_db = 20 * np.log10(peak_val / (res_rms + 1e-10))

    return {
        "null_depth_db": float(null_depth_db),
        "residual_rms_dbfs": float(20 * np.log10(res_rms + 1e-10)),
        "peak_residual_freq_hz": float(peak_freq),
        "peak_residual_db": float(peak_level_db),
        "crest_factor_db": float(crest_factor_db),
        "freqs": freqs,
        "null_vs_freq": null_vs_freq,
        "res_spectrum_db": 20 * np.log10(res_spectrum + 1e-10),
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Audio loopback null test — subtract original from capture, "
        "measure residual.")
    add_audio_args(parser)
    add_test_args(parser)
    parser.add_argument("--signal", choices=["sweep", "noise", "tone", "multitone"],
                        default="sweep",
                        help="Test signal type (default: sweep)")
    parser.add_argument("--duration", type=float, default=3.0,
                        help="Test signal duration in seconds (default: 3)")
    parser.add_argument("--freq", type=float, default=1000.0,
                        help="Tone frequency for --signal tone (default: 1000)")
    parser.add_argument("--amplitude", type=float, default=0.5,
                        help="Test signal amplitude (default: 0.5)")
    parser.add_argument("--pdf", metavar="FILE",
                        help="Output PDF report")
    parser.add_argument("--csv", metavar="FILE",
                        help="Output CSV (freq, null_depth_db)")
    parser.add_argument("--json", metavar="FILE",
                        help="Output JSON results")
    args = parser.parse_args()

    if args.list_devices:
        from dsp_pipeline.args import open_stream_from_args
        open_stream_from_args(args)
        return 0

    samplerate = args.samplerate
    duration = args.duration
    amplitude = args.amplitude

    ts = TestSignal(samplerate, duration)

    # generate test signal
    if args.signal == "sweep":
        reference = ts.sweep(f_start=20, f_stop=20000, amplitude=amplitude)
    elif args.signal == "noise":
        reference = ts.noise(amplitude=amplitude)
    elif args.signal == "tone":
        reference = ts.sine(freq=args.freq, amplitude=amplitude)
    else:  # multitone
        reference = ts.two_tone(f1=400, f2=1000, amplitude=amplitude / 2)
        # add more tones
        t = np.arange(len(reference)) / samplerate
        reference += (amplitude / 4 * np.sin(2 * np.pi * 2500 * t)).astype(np.float32)
        reference += (amplitude / 4 * np.sin(2 * np.pi * 5000 * t)).astype(np.float32)
        reference = np.clip(reference, -1.0, 1.0)

    if args.test:
        print("Test mode: simulating imperfect loopback")
        # simulate: slight gain error, tiny delay, added noise, mild nonlinearity
        captured = reference.copy()
        captured *= 0.98  # -0.18 dB gain error
        # add noise
        captured += np.random.randn(len(captured)).astype(np.float32) * 0.0003
        # add slight 2nd harmonic (nonlinearity)
        captured += 0.001 * (reference ** 2)
        # add 3-sample delay
        captured = np.roll(captured, 3)
        captured[:3] = 0
    else:
        import sounddevice as sd
        print("Loopback null test — connect output to input", file=sys.stderr)
        print(f"Signal: {args.signal}, Duration: {duration}s", file=sys.stderr)
        print()

        captured = sd.playrec(reference.reshape(-1, 1), samplerate=samplerate,
                              input_mapping=[1], output_mapping=[1],
                              device=(args.input_device, args.output_device),
                              dtype="float32")
        sd.wait()
        captured = captured.flatten()

    # align
    ref_aligned, cap_aligned, delay = align_signals(reference, captured, samplerate)
    print(f"Alignment delay: {delay} samples ({delay / samplerate * 1000:.2f} ms)")

    # gain compensation
    cap_compensated, gain = compensate_gain(ref_aligned, cap_aligned)
    print(f"Gain compensation: {20 * np.log10(gain + 1e-10):.3f} dB")

    # compute residual (the null)
    residual = cap_compensated - ref_aligned

    # analyze
    results = analyze_residual(residual, ref_aligned, samplerate)

    # print results
    print(f"\n{'='*50}")
    print(f"Loopback Null Test Results")
    print(f"{'='*50}")
    print(f"Null depth:          {results['null_depth_db']:.1f} dB")
    print(f"Residual RMS:        {results['residual_rms_dbfs']:.1f} dBFS")
    print(f"Peak residual at:    {results['peak_residual_freq_hz']:.0f} Hz "
          f"({results['peak_residual_db']:.1f} dB)")
    print(f"Crest factor:        {results['crest_factor_db']:.1f} dB")
    print()
    if results['crest_factor_db'] > 12:
        print("High crest factor → residual is impulsive (clock glitches, "
              "buffer underruns)")
    elif results['crest_factor_db'] < 4:
        print("Low crest factor → residual is noise-like (thermal noise, "
              "quantization)")
    else:
        print("Moderate crest factor → mixed residual (distortion + noise)")

    # CSV output
    if args.csv:
        freqs = results["freqs"]
        null_vs_freq = results["null_vs_freq"]
        with open(args.csv, "w") as f:
            f.write("freq_hz,null_depth_db,residual_spectrum_dbfs\n")
            for i in range(len(freqs)):
                if freqs[i] >= 20 and freqs[i] <= 20000:
                    f.write(f"{freqs[i]:.1f},{null_vs_freq[i]:.2f},"
                            f"{results['res_spectrum_db'][i]:.2f}\n")
        print(f"\nCSV saved to {args.csv}")

    # JSON output
    if args.json:
        out = {
            "timestamp": datetime.now().isoformat(),
            "samplerate": samplerate,
            "signal_type": args.signal,
            "duration_s": duration,
            "alignment_delay_samples": delay,
            "gain_compensation_db": float(20 * np.log10(gain + 1e-10)),
            "null_depth_db": results["null_depth_db"],
            "residual_rms_dbfs": results["residual_rms_dbfs"],
            "peak_residual_freq_hz": results["peak_residual_freq_hz"],
            "peak_residual_db": results["peak_residual_db"],
            "crest_factor_db": results["crest_factor_db"],
        }
        with open(args.json, "w") as f:
            json.dump(out, f, indent=2)
        print(f"JSON saved to {args.json}")

    # PDF report
    if args.pdf:
        fig, axes = plt.subplots(3, 1, figsize=(10, 9))

        freqs = results["freqs"]
        mask = (freqs >= 20) & (freqs <= 20000)

        # time domain: original vs captured vs residual
        ax = axes[0]
        t = np.arange(min(2000, len(ref_aligned))) / samplerate * 1000
        ax.plot(t, ref_aligned[:len(t)], "b-", alpha=0.7, linewidth=0.8,
                label="Reference")
        ax.plot(t, cap_compensated[:len(t)], "g-", alpha=0.7, linewidth=0.8,
                label="Captured (aligned)")
        ax.plot(t, residual[:len(t)], "r-", linewidth=1.0,
                label=f"Residual ({results['null_depth_db']:.1f} dB)")
        ax.set_xlabel("Time (ms)")
        ax.set_ylabel("Amplitude")
        ax.set_title("Time Domain — First 2000 Samples")
        ax.legend(loc="upper right", fontsize=8)
        ax.grid(True, alpha=0.3)

        # residual spectrum
        ax = axes[1]
        ax.semilogx(freqs[mask], results["res_spectrum_db"][mask], "r-",
                    linewidth=0.8)
        ax.set_xlabel("Frequency (Hz)")
        ax.set_ylabel("Residual (dBFS)")
        ax.set_title("Residual Spectrum")
        ax.grid(True, alpha=0.3, which="both")
        ax.set_xlim(20, 20000)

        # null depth vs frequency
        ax = axes[2]
        null_smooth = results["null_vs_freq"].copy()
        # clip extreme values for display
        null_smooth = np.clip(null_smooth, -100, 0)
        ax.semilogx(freqs[mask], null_smooth[mask], "m-", linewidth=0.8)
        ax.set_xlabel("Frequency (Hz)")
        ax.set_ylabel("Null Depth (dB)")
        ax.set_title("Null Depth vs Frequency (lower = better)")
        ax.grid(True, alpha=0.3, which="both")
        ax.set_xlim(20, 20000)
        ax.set_ylim(-100, 0)

        fig.suptitle(f"Loopback Null Test — {args.signal} — "
                     f"{datetime.now().strftime('%Y-%m-%d %H:%M')}",
                     fontsize=11, fontweight="bold")
        plt.tight_layout()
        fig.savefig(args.pdf, dpi=150)
        plt.close(fig)
        print(f"PDF saved to {args.pdf}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
