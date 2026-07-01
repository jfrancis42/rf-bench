#!/usr/bin/env python3
"""
thd_analyzer.py — Audio THD+N analyzer.

Captures audio from a soundcard (or generates a test signal), finds the
fundamental frequency via peak detection, measures individual harmonics
(2nd through 10th), and computes THD as percentage and dB, THD+N, and
SINAD.

Outputs results to terminal and optionally generates a PDF with the
magnitude spectrum showing fundamental + harmonics labeled, and/or CSV.

Uses the dsp_pipeline framework for audio capture and test signals.
"""

from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path

import numpy as np
from scipy.signal import get_window

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from dsp_pipeline import TestSignal, add_audio_args, add_test_args


# ---------------------------------------------------------------------------
# Analysis parameters
# ---------------------------------------------------------------------------

ANALYSIS_BLOCKSIZE = 65536  # ~1.37 s at 48 kHz, gives 0.73 Hz resolution
NUM_HARMONICS = 10          # fundamental + 9 harmonics
WINDOW_TYPE = "blackmanharris"  # excellent sidelobe rejection (-92 dB)
HARMONIC_BIN_RADIUS = 5     # bins on each side of harmonic peak to sum


# ---------------------------------------------------------------------------
# Core measurement functions
# ---------------------------------------------------------------------------

def compute_spectrum(signal: np.ndarray, samplerate: int, window: str = WINDOW_TYPE
                     ) -> tuple[np.ndarray, np.ndarray]:
    """Compute magnitude spectrum in dBFS.

    Returns (frequencies, magnitude_dbfs).
    """
    n = len(signal)
    win = get_window(window, n)
    # Coherent gain compensation
    coherent_gain = np.sum(win) / n
    windowed = signal * win
    spectrum = np.fft.rfft(windowed)
    # Normalize to full-scale (1.0 peak = 0 dBFS)
    magnitude = np.abs(spectrum) * 2.0 / (n * coherent_gain)
    # DC bin should not be doubled
    magnitude[0] /= 2.0
    # Convert to dBFS (clip to avoid log(0))
    magnitude_dbfs = 20.0 * np.log10(np.maximum(magnitude, 1e-15))
    frequencies = np.fft.rfftfreq(n, 1.0 / samplerate)
    return frequencies, magnitude_dbfs


def find_fundamental(frequencies: np.ndarray, magnitude_dbfs: np.ndarray,
                     expected_freq: float | None = None,
                     search_range: tuple[float, float] = (20.0, 20000.0)
                     ) -> tuple[int, float]:
    """Find the fundamental frequency bin.

    If expected_freq is given, search within +/-5% of it.
    Otherwise, find the highest peak in the search range.

    Returns (bin_index, frequency_hz).
    """
    freq_res = frequencies[1] - frequencies[0]

    if expected_freq is not None:
        # Search within +/-5% of expected
        f_lo = expected_freq * 0.95
        f_hi = expected_freq * 1.05
    else:
        f_lo, f_hi = search_range

    mask = (frequencies >= f_lo) & (frequencies <= f_hi)
    if not np.any(mask):
        raise ValueError(f"No frequency bins in range {f_lo:.1f}-{f_hi:.1f} Hz")

    indices = np.where(mask)[0]
    peak_idx = indices[np.argmax(magnitude_dbfs[indices])]

    # Quadratic interpolation for sub-bin accuracy
    if 0 < peak_idx < len(magnitude_dbfs) - 1:
        alpha = magnitude_dbfs[peak_idx - 1]
        beta = magnitude_dbfs[peak_idx]
        gamma = magnitude_dbfs[peak_idx + 1]
        # Parabolic interpolation offset
        delta = 0.5 * (alpha - gamma) / (alpha - 2 * beta + gamma)
        freq_hz = frequencies[peak_idx] + delta * freq_res
    else:
        freq_hz = frequencies[peak_idx]

    return peak_idx, freq_hz


def measure_harmonics(frequencies: np.ndarray, magnitude_dbfs: np.ndarray,
                      fundamental_freq: float, num_harmonics: int = NUM_HARMONICS,
                      bin_radius: int = HARMONIC_BIN_RADIUS
                      ) -> list[dict]:
    """Measure power of each harmonic (1st through num_harmonics-th).

    Returns list of dicts with keys: harmonic, freq_hz, level_dbfs, bin_idx.
    """
    freq_res = frequencies[1] - frequencies[0]
    nyquist = frequencies[-1]
    results = []

    for h in range(1, num_harmonics + 1):
        target_freq = fundamental_freq * h
        if target_freq > nyquist:
            break

        # Find closest bin
        center_bin = int(round(target_freq / freq_res))
        if center_bin >= len(frequencies):
            break

        # Search within bin_radius for the actual peak
        lo = max(0, center_bin - bin_radius)
        hi = min(len(magnitude_dbfs), center_bin + bin_radius + 1)
        local_peak = lo + np.argmax(magnitude_dbfs[lo:hi])

        results.append({
            "harmonic": h,
            "freq_hz": frequencies[local_peak],
            "level_dbfs": magnitude_dbfs[local_peak],
            "bin_idx": local_peak,
        })

    return results


def compute_thd(harmonics: list[dict]) -> tuple[float, float]:
    """Compute THD from harmonic levels.

    THD = sqrt(sum(V2^2 + V3^2 + ... + Vn^2)) / V1

    Returns (thd_percent, thd_db).
    """
    if len(harmonics) < 2:
        return 0.0, -np.inf

    # Convert dBFS back to linear voltage
    fundamental_v = 10 ** (harmonics[0]["level_dbfs"] / 20.0)
    harmonic_sum_sq = 0.0
    for h in harmonics[1:]:
        v = 10 ** (h["level_dbfs"] / 20.0)
        harmonic_sum_sq += v ** 2

    thd_ratio = np.sqrt(harmonic_sum_sq) / fundamental_v
    thd_percent = thd_ratio * 100.0
    thd_db = 20.0 * np.log10(max(thd_ratio, 1e-15))
    return thd_percent, thd_db


def compute_thd_n(signal: np.ndarray, samplerate: int, fundamental_freq: float,
                  window: str = WINDOW_TYPE, bin_radius: int = HARMONIC_BIN_RADIUS
                  ) -> tuple[float, float]:
    """Compute THD+N by notching the fundamental and measuring residual.

    THD+N = RMS(everything except fundamental) / RMS(total)

    Returns (thd_n_percent, sinad_db).
    """
    n = len(signal)
    win = get_window(window, n)
    windowed = signal * win
    spectrum = np.fft.rfft(windowed)
    freq_res = samplerate / n

    # Zero out the fundamental bin and immediate neighbors
    fund_bin = int(round(fundamental_freq / freq_res))
    lo = max(0, fund_bin - bin_radius)
    hi = min(len(spectrum), fund_bin + bin_radius + 1)

    # Total power (in spectral domain)
    total_power = np.sum(np.abs(spectrum) ** 2)

    # Fundamental power (bins we're notching)
    fund_power = np.sum(np.abs(spectrum[lo:hi]) ** 2)

    # Noise + distortion = total - fundamental
    nd_power = total_power - fund_power

    if total_power == 0:
        return 0.0, np.inf

    thd_n_ratio = np.sqrt(nd_power / total_power)
    thd_n_percent = thd_n_ratio * 100.0

    # SINAD = 1 / THD+N (as ratio), expressed in dB
    sinad_db = -20.0 * np.log10(max(thd_n_ratio, 1e-15))

    return thd_n_percent, sinad_db


# ---------------------------------------------------------------------------
# Test signal generation
# ---------------------------------------------------------------------------

def generate_test_signal(samplerate: int, duration: float,
                         fundamental: float = 1000.0,
                         amplitude: float = 0.8) -> np.ndarray:
    """Generate a 1 kHz sine with known harmonic distortion for verification.

    Adds:
      - 2nd harmonic at -40 dB (1% of fundamental)
      - 3rd harmonic at -50 dB (0.316% of fundamental)
      - 4th harmonic at -60 dB (0.1% of fundamental)
      - White noise floor at -90 dB

    Expected THD: sqrt(0.01^2 + 0.00316^2 + 0.001^2) = ~1.056%
    """
    ts = TestSignal(samplerate, duration)
    t = ts._time()

    # Fundamental
    signal = amplitude * np.sin(2 * np.pi * fundamental * t)

    # 2nd harmonic: -40 dB relative = 0.01 * amplitude
    signal += amplitude * 0.01 * np.sin(2 * np.pi * 2 * fundamental * t)

    # 3rd harmonic: -50 dB relative = 0.00316 * amplitude
    signal += amplitude * 0.00316 * np.sin(2 * np.pi * 3 * fundamental * t)

    # 4th harmonic: -60 dB relative = 0.001 * amplitude
    signal += amplitude * 0.001 * np.sin(2 * np.pi * 4 * fundamental * t)

    # Noise floor at -90 dB relative
    rng = np.random.default_rng(42)
    noise_amp = amplitude * 10 ** (-90 / 20.0)
    signal += noise_amp * rng.standard_normal(len(t))

    return signal.astype(np.float32)


# ---------------------------------------------------------------------------
# Output: PDF
# ---------------------------------------------------------------------------

def generate_pdf(frequencies: np.ndarray, magnitude_dbfs: np.ndarray,
                 harmonics: list[dict], thd_pct: float, thd_db: float,
                 thd_n_pct: float, sinad_db: float,
                 fundamental_freq: float, output_path: str) -> None:
    """Generate single-page PDF with spectrum and measurements."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.backends.backend_pdf import PdfPages

    fig, ax = plt.subplots(figsize=(11, 7))

    # Plot magnitude spectrum
    ax.plot(frequencies, magnitude_dbfs, linewidth=0.5, color="steelblue", alpha=0.8)

    # Mark harmonics
    colors = plt.cm.tab10(np.linspace(0, 1, NUM_HARMONICS))
    for i, h in enumerate(harmonics):
        marker = "v" if h["harmonic"] == 1 else "o"
        label = f"H{h['harmonic']}: {h['freq_hz']:.1f} Hz @ {h['level_dbfs']:.1f} dBFS"
        ax.plot(h["freq_hz"], h["level_dbfs"], marker=marker, markersize=8,
                color=colors[i], label=label, zorder=5)
        # Vertical line from noise floor to peak
        ax.axvline(h["freq_hz"], color=colors[i], alpha=0.3, linewidth=0.8, linestyle="--")

    ax.set_xlabel("Frequency (Hz)")
    ax.set_ylabel("Magnitude (dBFS)")
    ax.set_title(f"THD Analysis — Fundamental: {fundamental_freq:.2f} Hz")
    ax.set_xlim(0, min(frequencies[-1], fundamental_freq * (NUM_HARMONICS + 2)))
    ax.set_ylim(max(np.min(magnitude_dbfs), -140), 5)
    ax.grid(True, alpha=0.3)
    ax.legend(loc="upper right", fontsize=7, framealpha=0.9)

    # Annotation box with measurements
    textstr = (
        f"THD:    {thd_pct:.4f}%  ({thd_db:.1f} dB)\n"
        f"THD+N:  {thd_n_pct:.4f}%\n"
        f"SINAD:  {sinad_db:.1f} dB\n"
        f"Fund:   {fundamental_freq:.2f} Hz\n"
        f"Fund level: {harmonics[0]['level_dbfs']:.1f} dBFS"
    )
    props = dict(boxstyle="round,pad=0.5", facecolor="lightyellow", alpha=0.9, edgecolor="gray")
    ax.text(0.02, 0.02, textstr, transform=ax.transAxes, fontsize=9,
            verticalalignment="bottom", fontfamily="monospace", bbox=props)

    plt.tight_layout()

    with PdfPages(output_path) as pdf:
        pdf.savefig(fig, dpi=150)

    plt.close(fig)
    print(f"PDF written: {output_path}")


# ---------------------------------------------------------------------------
# Output: CSV
# ---------------------------------------------------------------------------

def write_csv(harmonics: list[dict], thd_pct: float, thd_db: float,
              thd_n_pct: float, sinad_db: float,
              fundamental_freq: float, output_path: str) -> None:
    """Write harmonic data and summary to CSV."""
    with open(output_path, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["# THD Analysis"])
        writer.writerow(["# Fundamental (Hz)", f"{fundamental_freq:.4f}"])
        writer.writerow(["# THD (%)", f"{thd_pct:.6f}"])
        writer.writerow(["# THD (dB)", f"{thd_db:.2f}"])
        writer.writerow(["# THD+N (%)", f"{thd_n_pct:.6f}"])
        writer.writerow(["# SINAD (dB)", f"{sinad_db:.2f}"])
        writer.writerow([])
        writer.writerow(["harmonic", "frequency_hz", "level_dbfs", "relative_db"])
        fund_level = harmonics[0]["level_dbfs"] if harmonics else 0
        for h in harmonics:
            writer.writerow([
                h["harmonic"],
                f"{h['freq_hz']:.4f}",
                f"{h['level_dbfs']:.2f}",
                f"{h['level_dbfs'] - fund_level:.2f}",
            ])
    print(f"CSV written: {output_path}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> int:
    parser = argparse.ArgumentParser(
        description="Audio THD+N analyzer. Captures audio, measures harmonic "
                    "distortion, THD, THD+N, and SINAD.")
    add_audio_args(parser, duplex=False)
    add_test_args(parser)

    parser.add_argument("--fundamental", type=float, default=None, metavar="HZ",
                        help="Expected fundamental frequency (auto-detect if not given)")
    parser.add_argument("--duration", type=float, default=2.0, metavar="SEC",
                        help="Capture duration in seconds (default 2.0)")
    parser.add_argument("--output", metavar="PDF",
                        help="Write spectrum PDF to this path")
    parser.add_argument("--csv", metavar="CSV",
                        help="Write harmonic data to CSV")
    parser.add_argument("--window", default=WINDOW_TYPE,
                        choices=["blackmanharris", "hann", "flattop", "hamming", "kaiser"],
                        help=f"FFT window function (default {WINDOW_TYPE})")
    args = parser.parse_args()

    if args.list_devices:
        import sounddevice as sd
        print(sd.query_devices())
        return 0

    samplerate = args.samplerate

    # -----------------------------------------------------------------------
    # Acquire signal
    # -----------------------------------------------------------------------
    if args.test:
        fund_freq = args.fundamental if args.fundamental else 1000.0
        duration = args.test_duration if args.test_duration else args.duration
        print(f"Generating test signal: {fund_freq:.0f} Hz fundamental, "
              f"{duration:.1f} s, {samplerate} Hz sample rate")
        print("  Known distortion: H2=-40 dB, H3=-50 dB, H4=-60 dB, noise=-90 dB")
        print(f"  Expected THD: ~1.056%")
        signal = generate_test_signal(samplerate, duration,
                                      fundamental=fund_freq)
    else:
        import sounddevice as sd
        duration = args.duration
        print(f"Capturing {duration:.1f} s from input device "
              f"(samplerate={samplerate} Hz)...")
        recording = sd.rec(int(duration * samplerate), samplerate=samplerate,
                           channels=1, dtype="float32",
                           device=args.input_device)
        sd.wait()
        signal = recording.flatten()
        print(f"Captured {len(signal)} samples ({len(signal)/samplerate:.2f} s)")

    # -----------------------------------------------------------------------
    # Use the center portion to avoid transients, sized to analysis blocksize
    # -----------------------------------------------------------------------
    n_analysis = min(ANALYSIS_BLOCKSIZE, len(signal))
    # If signal is longer than blocksize, take center
    if len(signal) > n_analysis:
        start = (len(signal) - n_analysis) // 2
        analysis_segment = signal[start:start + n_analysis]
    else:
        analysis_segment = signal

    # -----------------------------------------------------------------------
    # Compute spectrum
    # -----------------------------------------------------------------------
    frequencies, magnitude_dbfs = compute_spectrum(
        analysis_segment, samplerate, window=args.window)

    # -----------------------------------------------------------------------
    # Find fundamental
    # -----------------------------------------------------------------------
    try:
        fund_bin, fundamental_freq = find_fundamental(
            frequencies, magnitude_dbfs, expected_freq=args.fundamental)
    except ValueError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1

    # -----------------------------------------------------------------------
    # Measure harmonics
    # -----------------------------------------------------------------------
    harmonics = measure_harmonics(frequencies, magnitude_dbfs, fundamental_freq,
                                  bin_radius=HARMONIC_BIN_RADIUS)

    if not harmonics:
        print("Error: no harmonics found.", file=sys.stderr)
        return 1

    # -----------------------------------------------------------------------
    # Compute THD and THD+N
    # -----------------------------------------------------------------------
    thd_pct, thd_db = compute_thd(harmonics)
    thd_n_pct, sinad_db = compute_thd_n(analysis_segment, samplerate,
                                         fundamental_freq, window=args.window,
                                         bin_radius=HARMONIC_BIN_RADIUS)

    # -----------------------------------------------------------------------
    # Terminal output
    # -----------------------------------------------------------------------
    print()
    print("=" * 60)
    print(f"  THD Analysis Results")
    print("=" * 60)
    print(f"  Fundamental:  {fundamental_freq:.2f} Hz")
    print(f"  Fund. level:  {harmonics[0]['level_dbfs']:.1f} dBFS")
    print(f"  Window:       {args.window}")
    print(f"  FFT size:     {n_analysis} ({samplerate/n_analysis:.2f} Hz/bin)")
    print("-" * 60)
    print(f"  {'Harmonic':<10} {'Freq (Hz)':<12} {'Level (dBFS)':<14} {'Relative (dB)'}")
    print("-" * 60)
    for h in harmonics:
        rel_db = h["level_dbfs"] - harmonics[0]["level_dbfs"]
        marker = " <-- fund" if h["harmonic"] == 1 else ""
        print(f"  H{h['harmonic']:<9} {h['freq_hz']:<12.2f} {h['level_dbfs']:<14.1f} {rel_db:+.1f}{marker}")
    print("-" * 60)
    print(f"  THD:    {thd_pct:.4f}%  ({thd_db:.1f} dB)")
    print(f"  THD+N:  {thd_n_pct:.4f}%")
    print(f"  SINAD:  {sinad_db:.1f} dB")
    print("=" * 60)

    # -----------------------------------------------------------------------
    # Optional outputs
    # -----------------------------------------------------------------------
    if args.output:
        generate_pdf(frequencies, magnitude_dbfs, harmonics,
                     thd_pct, thd_db, thd_n_pct, sinad_db,
                     fundamental_freq, args.output)

    if args.csv:
        write_csv(harmonics, thd_pct, thd_db, thd_n_pct, sinad_db,
                  fundamental_freq, args.csv)

    return 0


if __name__ == "__main__":
    sys.exit(main())
