#!/usr/bin/env python3
"""
resonance_finder.py — Acoustic resonance finder.

Emit a click or impulse through headphones, hold them against a surface
(guitar body, wall, bottle, table), record the impulse response via mic,
FFT to find resonant modes. Tells you the natural frequency of anything.

Also works passively: tap the object near the mic and analyze the decay.

Modes:
- Active: play impulse, capture IR, analyze
- Passive: wait for transient, analyze decay
- Sweep: play slow sine sweep, measure response at each frequency
"""

from __future__ import annotations

import argparse
import signal
import sys
import time
from pathlib import Path

import numpy as np
from scipy.signal import get_window, find_peaks, butter, sosfilt

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from dsp_pipeline import DSPBlock, Pipeline, TestSignal, add_audio_args, add_test_args

import warnings
warnings.filterwarnings("ignore", message="Unable to import Axes3D")
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt


def generate_impulse(samplerate: int, duration_ms: float = 0.5) -> np.ndarray:
    """Generate a short impulse (click) for excitation."""
    n = int(duration_ms * samplerate / 1000)
    # Gaussian-windowed pulse for controlled bandwidth
    t = np.linspace(-3, 3, n)
    impulse = np.exp(-t ** 2).astype(np.float32)
    impulse *= 0.9 / np.max(np.abs(impulse))
    return impulse


def find_resonances(spectrum_db: np.ndarray, freqs: np.ndarray,
                    prominence: float = 10.0,
                    min_freq: float = 20.0,
                    max_freq: float = 16000.0) -> list[dict]:
    """Find resonant peaks in the spectrum."""
    mask = (freqs >= min_freq) & (freqs <= max_freq)
    masked_spectrum = spectrum_db.copy()
    masked_spectrum[~mask] = -200

    # find peaks with minimum prominence
    peaks, properties = find_peaks(masked_spectrum, prominence=prominence,
                                   distance=5, height=-100)

    resonances = []
    for i, peak_idx in enumerate(peaks):
        freq = freqs[peak_idx]
        level = spectrum_db[peak_idx]
        prom = properties["prominences"][i]

        # estimate Q from -3 dB bandwidth
        half_power = level - 3.0
        # search left
        left_idx = peak_idx
        while left_idx > 0 and spectrum_db[left_idx] > half_power:
            left_idx -= 1
        # search right
        right_idx = peak_idx
        while right_idx < len(spectrum_db) - 1 and spectrum_db[right_idx] > half_power:
            right_idx += 1
        bw = freqs[right_idx] - freqs[left_idx] if right_idx > left_idx else freq / 10
        Q = freq / bw if bw > 0 else 0

        # musical note
        if freq > 0:
            midi = 69 + 12 * np.log2(freq / 440.0)
            note_names = ["C", "C#", "D", "D#", "E", "F",
                          "F#", "G", "G#", "A", "A#", "B"]
            note_idx = int(round(midi)) % 12
            octave = int(round(midi)) // 12 - 1
            note = f"{note_names[note_idx]}{octave}"
            cents_off = (midi - round(midi)) * 100
        else:
            note = "?"
            cents_off = 0

        resonances.append({
            "freq_hz": float(freq),
            "level_db": float(level),
            "prominence_db": float(prom),
            "Q": float(Q),
            "bandwidth_hz": float(bw),
            "note": note,
            "cents_off": float(cents_off),
        })

    # sort by prominence (most prominent first)
    resonances.sort(key=lambda r: r["prominence_db"], reverse=True)
    return resonances


def estimate_rt60(ir: np.ndarray, samplerate: int, freq: float,
                  bandwidth: float = 100.0) -> float:
    """Estimate RT60 (reverberation time) at a specific frequency."""
    # bandpass filter IR around the frequency
    nyquist = samplerate / 2
    low = max((freq - bandwidth / 2) / nyquist, 0.001)
    high = min((freq + bandwidth / 2) / nyquist, 0.999)
    if low >= high:
        return 0.0
    sos = butter(3, [low, high], btype="band", output="sos")
    filtered = sosfilt(sos, ir)

    # Schroeder integration (backward energy sum)
    energy = filtered ** 2
    schroeder = np.cumsum(energy[::-1])[::-1]
    schroeder_db = 10 * np.log10(schroeder / (schroeder[0] + 1e-10) + 1e-10)

    # find time for -60 dB decay
    below_60 = np.where(schroeder_db < -60)[0]
    if len(below_60) > 0:
        return below_60[0] / samplerate
    # extrapolate from -20 dB
    below_20 = np.where(schroeder_db < -20)[0]
    if len(below_20) > 0:
        return 3.0 * below_20[0] / samplerate
    return 0.0


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Acoustic resonance finder — discover the natural "
        "frequencies of objects and spaces.")
    add_audio_args(parser)
    add_test_args(parser)
    parser.add_argument("--mode", choices=["active", "passive", "sweep"],
                        default="passive",
                        help="Measurement mode (default: passive)")
    parser.add_argument("--duration", type=float, default=2.0,
                        help="Capture duration in seconds (default: 2)")
    parser.add_argument("--prominence", type=float, default=8.0,
                        help="Minimum peak prominence in dB (default: 8)")
    parser.add_argument("--min-freq", type=float, default=20.0,
                        help="Minimum frequency to search (default: 20 Hz)")
    parser.add_argument("--max-freq", type=float, default=16000.0,
                        help="Maximum frequency to search (default: 16000 Hz)")
    parser.add_argument("--trigger-db", type=float, default=-20.0,
                        help="Trigger level for passive mode (default: -20 dBFS)")
    parser.add_argument("--pdf", metavar="FILE",
                        help="Output PDF with spectrum and resonance markers")
    parser.add_argument("--csv", metavar="FILE",
                        help="Output CSV of detected resonances")
    parser.add_argument("--top", type=int, default=10,
                        help="Show top N resonances (default: 10)")
    args = parser.parse_args()

    if args.list_devices:
        from dsp_pipeline.args import open_stream_from_args
        open_stream_from_args(args)
        return 0

    samplerate = args.samplerate
    duration = args.duration

    if args.test:
        ts = TestSignal(samplerate, duration)
        n_samples = ts.n_samples
        t = np.arange(n_samples) / samplerate

        # simulate a resonant object (wine glass: strong 440 Hz + weaker overtones)
        # with exponential decay (like tapping)
        print("Test mode: simulated wine glass tap")
        print("  Resonances: 440 Hz (A4), 1100 Hz, 1760 Hz, 2640 Hz")
        print()

        decay = np.exp(-3 * t).astype(np.float32)
        test_audio = np.zeros(n_samples, dtype=np.float32)
        # fundamental
        test_audio += 0.4 * decay * np.sin(2 * np.pi * 440 * t).astype(np.float32)
        # overtones (not perfectly harmonic — real objects have inharmonicity)
        test_audio += 0.15 * decay * np.sin(2 * np.pi * 1108 * t).astype(np.float32)
        test_audio += 0.08 * decay * np.sin(2 * np.pi * 1762 * t).astype(np.float32)
        test_audio += 0.04 * decay * np.sin(2 * np.pi * 2645 * t).astype(np.float32)
        # add noise
        test_audio += np.random.randn(n_samples).astype(np.float32) * 0.001

        captured = test_audio
    elif args.mode == "active":
        import sounddevice as sd
        print("Active mode: playing impulse, recording response...",
              file=sys.stderr)
        impulse = generate_impulse(samplerate)
        # pad with silence before and after
        play_signal = np.concatenate([
            np.zeros(int(0.1 * samplerate), dtype=np.float32),
            impulse,
            np.zeros(int(duration * samplerate), dtype=np.float32),
        ])
        captured = sd.playrec(play_signal.reshape(-1, 1),
                              samplerate=samplerate,
                              input_mapping=[1], output_mapping=[1],
                              device=(args.input_device, args.output_device),
                              dtype="float32")
        sd.wait()
        captured = captured.flatten()
        # trim pre-trigger
        captured = captured[int(0.1 * samplerate):]
    elif args.mode == "passive":
        import sounddevice as sd
        trigger_level = 10 ** (args.trigger_db / 20.0)
        print(f"Passive mode: waiting for tap (threshold {args.trigger_db} dBFS)...",
              file=sys.stderr)
        # record chunks until trigger
        triggered = False
        pre_buffer = np.zeros(int(0.1 * samplerate), dtype=np.float32)
        while not triggered:
            chunk = sd.rec(1024, samplerate=samplerate, channels=1,
                           dtype="float32", device=args.input_device)
            sd.wait()
            chunk = chunk.flatten()
            if np.max(np.abs(chunk)) > trigger_level:
                triggered = True
                pre_buffer = chunk
        # now record the decay
        print("Triggered! Recording decay...", file=sys.stderr)
        decay_rec = sd.rec(int(duration * samplerate), samplerate=samplerate,
                           channels=1, dtype="float32", device=args.input_device)
        sd.wait()
        captured = np.concatenate([pre_buffer, decay_rec.flatten()])
    else:  # sweep
        import sounddevice as sd
        print("Sweep mode: playing slow sine sweep...", file=sys.stderr)
        ts = TestSignal(samplerate, duration * 2)
        sweep = ts.sweep(f_start=args.min_freq, f_stop=args.max_freq,
                         amplitude=0.3)
        captured = sd.playrec(sweep.reshape(-1, 1), samplerate=samplerate,
                              input_mapping=[1], output_mapping=[1],
                              device=(args.input_device, args.output_device),
                              dtype="float32")
        sd.wait()
        captured = captured.flatten()

    # analyze
    n = len(captured)
    window = get_window("blackmanharris", n)
    spectrum = np.abs(np.fft.rfft(captured * window))
    freqs = np.fft.rfftfreq(n, 1.0 / samplerate)
    spectrum_db = 20 * np.log10(spectrum + 1e-10)
    # normalize to peak = 0 dB
    spectrum_db -= np.max(spectrum_db)

    # find resonances
    resonances = find_resonances(spectrum_db, freqs,
                                 prominence=args.prominence,
                                 min_freq=args.min_freq,
                                 max_freq=args.max_freq)

    # print results
    print(f"\n{'='*60}")
    print(f"Resonance Analysis")
    print(f"{'='*60}")
    print(f"\n{'#':<4} {'Freq (Hz)':<12} {'Note':<8} {'Level':<10} "
          f"{'Q':<8} {'BW (Hz)':<10} {'Prominence'}")
    print(f"{'-'*70}")

    for i, r in enumerate(resonances[:args.top]):
        cents = f"{r['cents_off']:+.0f}¢" if abs(r['cents_off']) > 5 else ""
        print(f"{i+1:<4} {r['freq_hz']:<12.1f} {r['note']:<4}{cents:<4} "
              f"{r['level_db']:<10.1f} {r['Q']:<8.0f} "
              f"{r['bandwidth_hz']:<10.1f} {r['prominence_db']:.1f} dB")

    if resonances:
        fund = resonances[0]
        print(f"\nFundamental: {fund['freq_hz']:.1f} Hz ({fund['note']})")
        print(f"Q factor: {fund['Q']:.0f} (decay time ≈ "
              f"{fund['Q'] / (np.pi * fund['freq_hz']) * 1000:.0f} ms)")

    # CSV output
    if args.csv:
        with open(args.csv, "w") as f:
            f.write("rank,freq_hz,note,cents_off,level_db,Q,bandwidth_hz,prominence_db\n")
            for i, r in enumerate(resonances):
                f.write(f"{i+1},{r['freq_hz']:.1f},{r['note']},"
                        f"{r['cents_off']:.1f},{r['level_db']:.1f},"
                        f"{r['Q']:.1f},{r['bandwidth_hz']:.1f},"
                        f"{r['prominence_db']:.1f}\n")
        print(f"\nCSV saved to {args.csv}")

    # PDF output
    if args.pdf:
        fig, axes = plt.subplots(2, 1, figsize=(10, 7))

        # spectrum with resonance markers
        ax = axes[0]
        mask = (freqs >= args.min_freq) & (freqs <= args.max_freq)
        ax.semilogx(freqs[mask], spectrum_db[mask], "b-", linewidth=0.6)
        # mark resonances
        for i, r in enumerate(resonances[:args.top]):
            color = "r" if i == 0 else "orange"
            ax.axvline(r["freq_hz"], color=color, alpha=0.5, linewidth=0.8)
            ax.annotate(f"{r['freq_hz']:.0f} Hz\n{r['note']}",
                        xy=(r["freq_hz"], r["level_db"]),
                        fontsize=7, ha="center", va="bottom",
                        color=color)
        ax.set_xlabel("Frequency (Hz)")
        ax.set_ylabel("Magnitude (dB)")
        ax.set_title("Resonance Spectrum")
        ax.grid(True, alpha=0.3, which="both")
        ax.set_xlim(args.min_freq, args.max_freq)

        # time-domain waveform (decay)
        ax = axes[1]
        t_plot = np.arange(min(len(captured), int(samplerate))) / samplerate * 1000
        ax.plot(t_plot, captured[:len(t_plot)], "g-", linewidth=0.5)
        ax.set_xlabel("Time (ms)")
        ax.set_ylabel("Amplitude")
        ax.set_title("Impulse Response / Decay")
        ax.grid(True, alpha=0.3)

        fig.suptitle("Acoustic Resonance Analysis", fontsize=12, fontweight="bold")
        plt.tight_layout()
        fig.savefig(args.pdf, dpi=150)
        plt.close(fig)
        print(f"PDF saved to {args.pdf}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
