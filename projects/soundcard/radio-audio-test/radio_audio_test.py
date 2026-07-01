#!/usr/bin/env python3
"""
radio_audio_test.py — End-to-end automated radio audio chain tester.

Tests the complete audio path through a radio system:
  SDG1062X → radio TX audio input → (RF link) → radio RX audio output → soundcard

Measures:
- Frequency response (audio passband shape)
- Distortion (THD at several frequencies)
- Signal-to-noise ratio
- Hum and noise components
- TX/RX audio latency

Can also work without the SDG (soundcard-only loopback through a radio
or repeater) using the internal test signal generator.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime
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


def measure_freq_response_multitone(captured: np.ndarray, samplerate: int,
                                     test_freqs: list[float]) -> dict[float, float]:
    """Measure response at discrete test frequencies via Goertzel."""
    results = {}
    n = len(captured)
    window = get_window("blackmanharris", n)
    windowed = captured * window
    spectrum = np.abs(np.fft.rfft(windowed))
    freqs = np.fft.rfftfreq(n, 1.0 / samplerate)

    for f in test_freqs:
        idx = np.argmin(np.abs(freqs - f))
        results[f] = 20 * np.log10(spectrum[idx] + 1e-10)
    return results


def measure_thd_at_freq(captured: np.ndarray, samplerate: int,
                         fundamental: float) -> dict:
    """Measure THD at a specific frequency."""
    n = len(captured)
    window = get_window("blackmanharris", n)
    spectrum = np.abs(np.fft.rfft(captured * window))
    freqs = np.fft.rfftfreq(n, 1.0 / samplerate)

    fund_idx = np.argmin(np.abs(freqs - fundamental))
    fund_power = spectrum[fund_idx] ** 2

    harmonic_power = 0.0
    for h in range(2, 8):
        h_freq = fundamental * h
        if h_freq >= samplerate / 2:
            break
        h_idx = np.argmin(np.abs(freqs - h_freq))
        harmonic_power += spectrum[h_idx] ** 2

    thd_pct = 100 * np.sqrt(harmonic_power) / (np.sqrt(fund_power) + 1e-10)
    return {"freq_hz": fundamental, "thd_pct": thd_pct,
            "thd_db": 20 * np.log10(thd_pct / 100 + 1e-10)}


def measure_snr(captured: np.ndarray, samplerate: int,
                signal_freq: float, bw: float = 100.0) -> float:
    """Measure SNR: signal power in ±bw around freq vs everything else."""
    n = len(captured)
    window = get_window("hann", n)
    spectrum = np.abs(np.fft.rfft(captured * window)) ** 2
    freqs = np.fft.rfftfreq(n, 1.0 / samplerate)

    signal_mask = (freqs >= signal_freq - bw) & (freqs <= signal_freq + bw)
    noise_mask = ~signal_mask & (freqs > 0)

    signal_power = np.sum(spectrum[signal_mask])
    noise_power = np.sum(spectrum[noise_mask])
    return 10 * np.log10(signal_power / (noise_power + 1e-10))


def measure_hum(captured: np.ndarray, samplerate: int) -> dict:
    """Detect hum at 50/60 Hz and harmonics."""
    n = len(captured)
    window = get_window("blackmanharris", n)
    spectrum = np.abs(np.fft.rfft(captured * window))
    freqs = np.fft.rfftfreq(n, 1.0 / samplerate)

    # check both 50 and 60 Hz fundamentals
    hum_results = {}
    for base in [50, 60]:
        total_hum = 0.0
        for h in range(1, 6):
            f = base * h
            idx = np.argmin(np.abs(freqs - f))
            total_hum += spectrum[idx] ** 2
        hum_results[base] = 20 * np.log10(np.sqrt(total_hum) + 1e-10)

    dominant = max(hum_results, key=hum_results.get)
    return {"dominant_hz": dominant, "level_db": hum_results[dominant],
            "50hz_db": hum_results[50], "60hz_db": hum_results[60]}


def measure_latency(reference: np.ndarray, captured: np.ndarray,
                    samplerate: int) -> float:
    """Measure audio latency via cross-correlation."""
    n = max(len(reference), len(captured))
    X = np.fft.rfft(reference, n=2 * n)
    Y = np.fft.rfft(captured, n=2 * n)
    cc = np.fft.irfft(Y * np.conj(X))
    delay_samples = np.argmax(np.abs(cc))
    if delay_samples > n:
        delay_samples -= 2 * n
    return delay_samples / samplerate


def run_sdg_test(sdg_ip: str, test_freqs: list[float], amplitude_vpp: float,
                 duration: float, samplerate: int, input_device) -> list[np.ndarray]:
    """Drive SDG1062X through test frequencies and capture audio."""
    import sounddevice as sd
    from rf_bench.siglent import SDG1000X

    captures = []
    with SDG1000X(sdg_ip) as sdg:
        sdg.set_output(1, True)
        sdg.set_waveform(1, "SINE")
        sdg.set_amplitude(1, amplitude_vpp)

        for freq in test_freqs:
            sdg.set_frequency(1, freq)
            time.sleep(0.3)  # settle
            cap = sd.rec(int(duration * samplerate), samplerate=samplerate,
                         channels=1, dtype="float32", device=input_device)
            sd.wait()
            captures.append(cap.flatten())

        sdg.set_output(1, False)
    return captures


def main() -> int:
    parser = argparse.ArgumentParser(
        description="End-to-end radio audio chain tester.")
    add_audio_args(parser)
    add_test_args(parser)
    parser.add_argument("--sdg", metavar="IP",
                        help="SDG1062X IP for stimulus (omit for soundcard-only)")
    parser.add_argument("--sdg-amplitude", type=float, default=0.1,
                        help="SDG output amplitude in Vpp (default: 0.1)")
    parser.add_argument("--duration", type=float, default=2.0,
                        help="Capture duration per frequency (default: 2 sec)")
    parser.add_argument("--freqs", metavar="LIST",
                        default="200,400,700,1000,1500,2000,2500,3000",
                        help="Comma-separated test frequencies in Hz")
    parser.add_argument("--pdf", metavar="FILE",
                        help="Output PDF report")
    parser.add_argument("--csv", metavar="FILE",
                        help="Output CSV results")
    parser.add_argument("--json", metavar="FILE",
                        help="Output JSON results")
    args = parser.parse_args()

    if args.list_devices:
        from dsp_pipeline.args import open_stream_from_args
        open_stream_from_args(args)
        return 0

    samplerate = args.samplerate
    duration = args.duration
    test_freqs = [float(f) for f in args.freqs.split(",")]

    if args.test:
        print("Test mode: simulating radio audio chain")
        ts = TestSignal(samplerate, duration)

        # simulate radio audio: bandpass 300–3000 Hz, some distortion
        captures = []
        for freq in test_freqs:
            tone = ts.sine(freq=freq, amplitude=0.4)
            # bandpass effect: attenuate outside 300-3000 Hz
            if freq < 300:
                atten = 0.1 * (freq / 300)
            elif freq > 3000:
                atten = 0.1 * (3000 / freq)
            else:
                atten = 1.0
            tone *= atten
            # add some THD
            t = np.arange(len(tone)) / samplerate
            tone += 0.01 * np.sin(2 * np.pi * 2 * freq * t[:len(tone)]).astype(np.float32)
            # add noise
            tone += np.random.randn(len(tone)).astype(np.float32) * 0.002
            # add hum
            tone += 0.003 * np.sin(2 * np.pi * 60 * t[:len(tone)]).astype(np.float32)
            captures.append(tone)
    elif args.sdg:
        print(f"Using SDG1062X at {args.sdg} for stimulus", file=sys.stderr)
        captures = run_sdg_test(args.sdg, test_freqs, args.sdg_amplitude,
                                duration, samplerate, args.input_device)
    else:
        import sounddevice as sd
        print("Soundcard-only mode: playing test tones through output",
              file=sys.stderr)
        captures = []
        ts = TestSignal(samplerate, duration)
        for freq in test_freqs:
            tone = ts.sine(freq=freq, amplitude=0.4)
            cap = sd.playrec(tone.reshape(-1, 1), samplerate=samplerate,
                             input_mapping=[1], output_mapping=[1],
                             device=(args.input_device, args.output_device),
                             dtype="float32")
            sd.wait()
            captures.append(cap.flatten())

    # analyze each capture
    freq_response = {}
    thd_results = []
    snr_results = []

    for freq, capture in zip(test_freqs, captures):
        # frequency response: level at the test frequency
        rms = np.sqrt(np.mean(capture ** 2))
        level_db = 20 * np.log10(rms + 1e-10)
        freq_response[freq] = level_db

        # THD
        thd = measure_thd_at_freq(capture, samplerate, freq)
        thd_results.append(thd)

        # SNR
        snr = measure_snr(capture, samplerate, freq)
        snr_results.append({"freq_hz": freq, "snr_db": snr})

    # hum measurement (use 1 kHz capture — midband, best sensitivity)
    mid_idx = len(captures) // 2
    hum = measure_hum(captures[mid_idx], samplerate)

    # normalize frequency response to midband
    mid_freq = min(freq_response.keys(), key=lambda f: abs(f - 1000))
    ref_level = freq_response[mid_freq]
    normalized_response = {f: v - ref_level for f, v in freq_response.items()}

    # latency (if we have reference)
    latency_ms = None
    if args.test:
        ts2 = TestSignal(samplerate, duration)
        ref = ts2.sine(freq=1000, amplitude=0.4)
        latency_ms = measure_latency(ref, captures[mid_idx], samplerate) * 1000

    # print results
    print(f"\n{'='*60}")
    print(f"Radio Audio Chain Test Results")
    print(f"{'='*60}")
    print(f"\nFrequency Response (relative to {mid_freq:.0f} Hz):")
    print(f"{'Freq (Hz)':<12} {'Level (dB)':<12} {'THD':<12} {'SNR (dB)':<10}")
    print(f"{'-'*46}")
    for i, freq in enumerate(test_freqs):
        print(f"{freq:<12.0f} {normalized_response[freq]:>+7.1f}     "
              f"{thd_results[i]['thd_pct']:>6.3f}%   "
              f"{snr_results[i]['snr_db']:>6.1f}")
    print(f"\nHum: {hum['dominant_hz']} Hz dominant, {hum['level_db']:.1f} dBFS")
    if latency_ms is not None:
        print(f"Latency: {latency_ms:.1f} ms")

    # passband characterization
    in_band = [v for f, v in normalized_response.items() if 300 <= f <= 3000]
    if in_band:
        ripple = max(in_band) - min(in_band)
        print(f"In-band ripple (300–3000 Hz): {ripple:.1f} dB")

    # CSV output
    if args.csv:
        with open(args.csv, "w") as f:
            f.write("freq_hz,level_db,thd_pct,thd_db,snr_db\n")
            for i, freq in enumerate(test_freqs):
                f.write(f"{freq:.0f},{normalized_response[freq]:.2f},"
                        f"{thd_results[i]['thd_pct']:.4f},"
                        f"{thd_results[i]['thd_db']:.1f},"
                        f"{snr_results[i]['snr_db']:.1f}\n")
        print(f"\nCSV saved to {args.csv}")

    # JSON output
    if args.json:
        results = {
            "timestamp": datetime.now().isoformat(),
            "samplerate": samplerate,
            "test_frequencies_hz": test_freqs,
            "freq_response_db": normalized_response,
            "thd": thd_results,
            "snr": [r["snr_db"] for r in snr_results],
            "hum": hum,
            "latency_ms": latency_ms,
        }
        with open(args.json, "w") as f:
            json.dump(results, f, indent=2, default=str)
        print(f"JSON saved to {args.json}")

    # PDF report
    if args.pdf:
        fig, axes = plt.subplots(3, 1, figsize=(10, 9))

        # frequency response
        ax = axes[0]
        x = list(normalized_response.keys())
        y = list(normalized_response.values())
        ax.semilogx(x, y, "b-o", markersize=5)
        ax.axhline(0, color="k", linewidth=0.5)
        ax.axhline(3, color="r", linewidth=0.5, linestyle="--", alpha=0.5)
        ax.axhline(-3, color="r", linewidth=0.5, linestyle="--", alpha=0.5)
        ax.axvline(300, color="g", linewidth=0.5, linestyle=":", alpha=0.5)
        ax.axvline(3000, color="g", linewidth=0.5, linestyle=":", alpha=0.5)
        ax.set_xlabel("Frequency (Hz)")
        ax.set_ylabel("Level (dB re 1 kHz)")
        ax.set_title("Audio Frequency Response")
        ax.grid(True, alpha=0.3, which="both")
        ax.set_xlim(min(test_freqs) * 0.8, max(test_freqs) * 1.2)

        # THD vs frequency
        ax = axes[1]
        thd_freqs = [r["freq_hz"] for r in thd_results]
        thd_pcts = [r["thd_pct"] for r in thd_results]
        ax.semilogx(thd_freqs, thd_pcts, "r-o", markersize=5)
        ax.set_xlabel("Frequency (Hz)")
        ax.set_ylabel("THD (%)")
        ax.set_title("Total Harmonic Distortion")
        ax.grid(True, alpha=0.3, which="both")
        ax.set_xlim(min(test_freqs) * 0.8, max(test_freqs) * 1.2)

        # SNR vs frequency
        ax = axes[2]
        snr_freqs = [r["freq_hz"] for r in snr_results]
        snr_vals = [r["snr_db"] for r in snr_results]
        ax.semilogx(snr_freqs, snr_vals, "g-o", markersize=5)
        ax.set_xlabel("Frequency (Hz)")
        ax.set_ylabel("SNR (dB)")
        ax.set_title("Signal-to-Noise Ratio")
        ax.grid(True, alpha=0.3, which="both")
        ax.set_xlim(min(test_freqs) * 0.8, max(test_freqs) * 1.2)

        fig.suptitle(f"Radio Audio Chain Test — {datetime.now().strftime('%Y-%m-%d %H:%M')}",
                     fontsize=12, fontweight="bold")
        plt.tight_layout()
        fig.savefig(args.pdf, dpi=150)
        plt.close(fig)
        print(f"PDF saved to {args.pdf}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
