#!/usr/bin/env python3
"""
soundcard_cal.py — Soundcard-as-instrument self-calibration.

Characterizes the PC soundcard via loopback (output → input):
- Frequency response
- THD+N floor
- Dynamic range / noise floor
- Channel crosstalk
- Sample-clock accuracy (optional, vs known reference)

Produces a calibration JSON file that other soundcard projects can
load to apply correction.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
from scipy.signal import get_window

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from dsp_pipeline import TestSignal, add_audio_args, add_test_args

import warnings
warnings.filterwarnings("ignore", message="Unable to import Axes3D")
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt


def measure_noise_floor(captured: np.ndarray, samplerate: int) -> float:
    """Measure noise floor in dBFS (no signal present)."""
    rms = np.sqrt(np.mean(captured ** 2))
    return 20 * np.log10(rms + 1e-10)


def measure_freq_response(captured: np.ndarray, reference: np.ndarray,
                           samplerate: int) -> tuple[np.ndarray, np.ndarray]:
    """Compute frequency response from sweep capture vs reference."""
    n = min(len(captured), len(reference))
    captured = captured[:n]
    reference = reference[:n]

    # cross-spectral method
    window = get_window("hann", n)
    X = np.fft.rfft(reference * window)
    Y = np.fft.rfft(captured * window)
    H = Y / (X + 1e-10)
    freqs = np.fft.rfftfreq(n, 1.0 / samplerate)
    magnitude_db = 20 * np.log10(np.abs(H) + 1e-10)
    return freqs, magnitude_db


def measure_thd(captured: np.ndarray, samplerate: int, fundamental: float) -> dict:
    """Measure THD of a single-tone capture."""
    n = len(captured)
    window = get_window("blackmanharris", n)
    spectrum = np.abs(np.fft.rfft(captured * window))
    freqs = np.fft.rfftfreq(n, 1.0 / samplerate)

    # find fundamental
    fund_idx = np.argmin(np.abs(freqs - fundamental))
    fund_power = spectrum[fund_idx] ** 2

    # find harmonics
    harmonic_power = 0.0
    harmonics = {}
    for h in range(2, 11):
        h_freq = fundamental * h
        if h_freq >= samplerate / 2:
            break
        h_idx = np.argmin(np.abs(freqs - h_freq))
        h_pow = spectrum[h_idx] ** 2
        harmonic_power += h_pow
        harmonics[h] = 20 * np.log10(spectrum[h_idx] / (spectrum[fund_idx] + 1e-10))

    thd_pct = 100 * np.sqrt(harmonic_power) / (np.sqrt(fund_power) + 1e-10)
    thd_db = 20 * np.log10(thd_pct / 100 + 1e-10)
    return {"thd_pct": thd_pct, "thd_db": thd_db, "harmonics_dbc": harmonics}


def measure_crosstalk(left: np.ndarray, right: np.ndarray) -> float:
    """Measure channel crosstalk in dB (signal on one channel, measure leakage on other)."""
    signal_power = np.mean(left ** 2)
    leakage_power = np.mean(right ** 2)
    if leakage_power < 1e-12:
        return -120.0
    return 10 * np.log10(leakage_power / (signal_power + 1e-10))


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Soundcard self-calibration via loopback.")
    add_audio_args(parser)
    add_test_args(parser)
    parser.add_argument("--output", default="soundcard_cal.json",
                        help="Calibration output JSON file")
    parser.add_argument("--pdf", metavar="FILE",
                        help="Generate calibration report PDF")
    parser.add_argument("--duration", type=float, default=3.0,
                        help="Test signal duration in seconds (default 3)")
    args = parser.parse_args()

    if args.list_devices:
        from dsp_pipeline.args import open_stream_from_args
        open_stream_from_args(args)
        return 0

    samplerate = args.samplerate
    duration = args.duration

    if args.test:
        print("Test mode: simulating loopback with synthetic impairments")
        ts = TestSignal(samplerate, duration)

        # simulate a non-ideal soundcard
        sweep_ref = ts.sweep(f_start=20, f_stop=20000, amplitude=0.5)
        # add slight frequency response roll-off and noise
        t = np.arange(len(sweep_ref)) / samplerate
        rolloff = 1.0 - 0.1 * (t / duration)  # slight HF roll-off
        sweep_cap = sweep_ref * rolloff + ts.noise(amplitude=0.001)

        # THD test
        tone_ref = ts.sine(freq=1000, amplitude=0.5)
        # add 2nd harmonic at -60 dB
        tone_cap = tone_ref + 0.0005 * np.sin(2 * np.pi * 2000 * t[:len(tone_ref)])

        # noise floor
        silence = ts.noise(amplitude=0.0001)

        # crosstalk: signal on left, measure on right
        crosstalk_left = ts.sine(freq=1000, amplitude=0.5)
        crosstalk_right = ts.sine(freq=1000, amplitude=0.0005)  # -60 dB
    else:
        import sounddevice as sd
        print("Loopback calibration requires output → input connection.",
              file=sys.stderr)
        print("Connect soundcard output to input (or use a loopback cable).",
              file=sys.stderr)
        print()

        # 1. Noise floor (silence)
        print("Measuring noise floor...", file=sys.stderr)
        silence = sd.rec(int(duration * samplerate), samplerate=samplerate,
                         channels=1, dtype="float32",
                         device=args.input_device)
        sd.wait()
        silence = silence.flatten()

        # 2. Frequency response (sweep)
        print("Measuring frequency response...", file=sys.stderr)
        ts = TestSignal(samplerate, duration)
        sweep_ref = ts.sweep(f_start=20, f_stop=20000, amplitude=0.5)
        sweep_cap = sd.playrec(sweep_ref.reshape(-1, 1), samplerate=samplerate,
                               input_mapping=[1], output_mapping=[1],
                               device=(args.input_device, args.output_device),
                               dtype="float32")
        sd.wait()
        sweep_cap = sweep_cap.flatten()

        # 3. THD (1 kHz tone)
        print("Measuring THD...", file=sys.stderr)
        tone_ref = ts.sine(freq=1000, amplitude=0.5)
        tone_cap = sd.playrec(tone_ref.reshape(-1, 1), samplerate=samplerate,
                              input_mapping=[1], output_mapping=[1],
                              device=(args.input_device, args.output_device),
                              dtype="float32")
        sd.wait()
        tone_cap = tone_cap.flatten()

        # 4. Crosstalk (tone on ch1, measure ch2)
        print("Measuring crosstalk...", file=sys.stderr)
        stereo_out = np.column_stack([
            ts.sine(freq=1000, amplitude=0.5),
            np.zeros(ts.n_samples, dtype=np.float32),
        ])
        crosstalk_cap = sd.playrec(stereo_out, samplerate=samplerate,
                                   channels=2,
                                   device=(args.input_device, args.output_device),
                                   dtype="float32")
        sd.wait()
        crosstalk_left = crosstalk_cap[:, 0]
        crosstalk_right = crosstalk_cap[:, 1]

    # compute results
    noise_floor_db = measure_noise_floor(silence, samplerate)
    freqs, freq_resp_db = measure_freq_response(sweep_cap, sweep_ref, samplerate)
    thd_result = measure_thd(tone_cap, samplerate, 1000.0)
    crosstalk_db = measure_crosstalk(crosstalk_left, crosstalk_right)

    # dynamic range = signal peak - noise floor
    dynamic_range_db = -noise_floor_db  # assuming full-scale signal

    # summary
    print(f"\n{'='*50}")
    print(f"Soundcard Calibration Results")
    print(f"{'='*50}")
    print(f"Noise floor:    {noise_floor_db:.1f} dBFS")
    print(f"Dynamic range:  {dynamic_range_db:.1f} dB")
    print(f"THD (1 kHz):    {thd_result['thd_pct']:.4f}% ({thd_result['thd_db']:.1f} dB)")
    print(f"Crosstalk:      {crosstalk_db:.1f} dB")
    print(f"Freq response:  {np.max(freq_resp_db[10:-10]) - np.min(freq_resp_db[10:-10]):.2f} dB ripple (20 Hz–20 kHz)")

    # save calibration JSON
    cal = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "samplerate": samplerate,
        "noise_floor_dbfs": float(noise_floor_db),
        "dynamic_range_db": float(dynamic_range_db),
        "thd_1khz_pct": float(thd_result["thd_pct"]),
        "thd_1khz_db": float(thd_result["thd_db"]),
        "crosstalk_db": float(crosstalk_db),
        "freq_response": {
            "freqs_hz": freqs[::10].tolist(),  # downsample for JSON size
            "magnitude_db": freq_resp_db[::10].tolist(),
        },
    }
    with open(args.output, "w") as f:
        json.dump(cal, f, indent=2)
    print(f"\nCalibration saved to {args.output}")

    # optional PDF
    if args.pdf:
        fig, axes = plt.subplots(2, 1, figsize=(10, 7))

        # frequency response
        ax = axes[0]
        mask = (freqs >= 20) & (freqs <= 20000)
        ax.semilogx(freqs[mask], freq_resp_db[mask], "b-", linewidth=0.8)
        ax.set_xlabel("Frequency (Hz)")
        ax.set_ylabel("Magnitude (dB)")
        ax.set_title("Frequency Response (loopback)")
        ax.grid(True, alpha=0.3)
        ax.set_xlim(20, 20000)

        # THD spectrum
        ax = axes[1]
        n = len(tone_cap)
        window = get_window("blackmanharris", n)
        spectrum_db = 20 * np.log10(np.abs(np.fft.rfft(tone_cap * window)) + 1e-10)
        spectrum_db -= np.max(spectrum_db)  # normalize to 0 dB
        tone_freqs = np.fft.rfftfreq(n, 1.0 / samplerate)
        mask = tone_freqs <= 10000
        ax.plot(tone_freqs[mask], spectrum_db[mask], "r-", linewidth=0.5)
        ax.set_xlabel("Frequency (Hz)")
        ax.set_ylabel("Magnitude (dB re fundamental)")
        ax.set_title(f"THD Spectrum (1 kHz, THD = {thd_result['thd_pct']:.4f}%)")
        ax.grid(True, alpha=0.3)
        ax.set_ylim(-100, 5)

        fig.suptitle(f"Soundcard Calibration — {datetime.now().strftime('%Y-%m-%d %H:%M')}",
                     fontsize=12, fontweight="bold")
        plt.tight_layout()
        fig.savefig(args.pdf, dpi=150)
        plt.close(fig)
        print(f"Report saved to {args.pdf}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
