#!/usr/bin/env python3
"""
freq_response.py — Audio frequency response sweeper.

Generates a logarithmic chirp (20 Hz–20 kHz by default), plays it through the
soundcard output while simultaneously capturing the input, then computes the
transfer function H(f) = Y(f)/X(f) to produce magnitude (dB) and phase
(degrees) vs frequency.  Output is a Bode-plot PDF and/or CSV.

Modes:
  --loopback     Generate + capture simultaneously (soundcard self-test or DUT)
  --analyze FILE Analyze a pre-recorded WAV capture (provide --reference FILE)
  --test         Synthetic test with a known filter applied (no hardware needed)

Uses the dsp_pipeline framework for audio args and test signal generation.
"""

from __future__ import annotations

import argparse
import csv
import sys
import time
from pathlib import Path

import numpy as np
from scipy.signal import butter, sosfilt, fftconvolve

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from dsp_pipeline import TestSignal, add_audio_args, add_test_args


# ---------------------------------------------------------------------------
# Chirp generation
# ---------------------------------------------------------------------------

def generate_log_chirp(
    f_start: float,
    f_stop: float,
    duration: float,
    samplerate: int = 48000,
    amplitude: float = 0.8,
    fade_ms: float = 5.0,
) -> np.ndarray:
    """Generate a logarithmic frequency sweep (sine chirp).

    The instantaneous frequency increases exponentially from f_start to f_stop
    over the given duration.  A short cosine fade-in/out is applied to avoid
    clicks.  The sweep actually extends ~2% beyond f_stop to ensure the stated
    range has full energy despite the fade-out taper.

    Returns float32 array, peak amplitude = `amplitude`.
    """
    # Extend sweep slightly beyond stated range so the fade-out taper
    # does not reduce energy at f_stop.  The transfer function computation
    # clips to [f_start, f_stop] anyway.
    overshoot = 1.02  # 2% beyond f_stop
    f_stop_ext = min(f_stop * overshoot, samplerate / 2.0 * 0.95)

    n_samples = int(samplerate * duration)
    t = np.arange(n_samples) / samplerate

    # Logarithmic chirp: phi(t) = 2*pi*f1*T/ln(f2/f1) * (exp(t/T*ln(f2/f1)) - 1)
    T = duration
    k = np.log(f_stop_ext / f_start)
    phase = 2.0 * np.pi * f_start * T / k * (np.exp(t / T * k) - 1.0)
    chirp = amplitude * np.sin(phase)

    # Cosine fade-in/out to suppress transient clicks
    fade_samples = int(fade_ms * samplerate / 1000.0)
    if fade_samples > 0 and fade_samples < n_samples // 2:
        fade_in = 0.5 * (1.0 - np.cos(np.pi * np.arange(fade_samples) / fade_samples))
        fade_out = 0.5 * (1.0 - np.cos(np.pi * np.arange(fade_samples) / fade_samples))[::-1]
        chirp[:fade_samples] *= fade_in
        chirp[-fade_samples:] *= fade_out

    return chirp.astype(np.float32)


# ---------------------------------------------------------------------------
# Transfer function computation
# ---------------------------------------------------------------------------

def compute_transfer_function(
    reference: np.ndarray,
    captured: np.ndarray,
    samplerate: int = 48000,
    f_start: float = 20.0,
    f_stop: float = 20000.0,
    smoothing_octave: float = 1 / 12,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Compute H(f) = Y(f)/X(f) from reference and captured signals.

    Uses Welch-like cross-spectral division with a Hann window for
    robustness against noise.

    Args:
        reference: the known excitation signal (what was sent out)
        captured: what was received back (after DUT or loopback)
        samplerate: sample rate in Hz
        f_start: lower frequency bound for valid data
        f_stop: upper frequency bound for valid data
        smoothing_octave: fractional-octave smoothing bandwidth (0 to disable)

    Returns:
        (frequencies, magnitude_db, phase_degrees)
        Only bins within [f_start, f_stop] are returned.
    """
    # Ensure equal length
    n = min(len(reference), len(captured))
    reference = reference[:n]
    captured = captured[:n]

    # No additional window: the chirp's own cosine taper handles edge
    # transients, and windowing a chirp destroys energy at the sweep
    # endpoints (where dwell time is already short on a log sweep).
    ref_windowed = reference.astype(np.float64)
    cap_windowed = captured.astype(np.float64)

    # FFT
    X = np.fft.rfft(ref_windowed)
    Y = np.fft.rfft(cap_windowed)
    freqs = np.fft.rfftfreq(n, 1.0 / samplerate)

    # H(f) = Y(f) / X(f), with regularization to avoid division by zero
    # Use Wiener-like deconvolution: H = Y*conj(X) / (|X|^2 + eps)
    # eps is set relative to peak energy — bins where the chirp has <-60 dB
    # of its peak energy are effectively noise-dominated and clamped.
    Sxx = np.abs(X) ** 2
    eps = np.max(Sxx) * 1e-6  # -60 dB regularization floor
    H = (Y * np.conj(X)) / (Sxx + eps)

    magnitude_db = 20.0 * np.log10(np.maximum(np.abs(H), 1e-15))
    phase_deg = np.degrees(np.angle(H))

    # Restrict to [f_start, f_stop]
    mask = (freqs >= f_start) & (freqs <= f_stop)
    freqs = freqs[mask]
    magnitude_db = magnitude_db[mask]
    phase_deg = phase_deg[mask]

    # Optional fractional-octave smoothing
    if smoothing_octave > 0 and len(freqs) > 10:
        magnitude_db = _octave_smooth(freqs, magnitude_db, smoothing_octave)
        phase_deg = _octave_smooth(freqs, phase_deg, smoothing_octave)

    return freqs, magnitude_db.astype(np.float64), phase_deg.astype(np.float64)


def _octave_smooth(
    freqs: np.ndarray, data: np.ndarray, fraction: float
) -> np.ndarray:
    """Apply fractional-octave smoothing to spectral data.

    Each output point is the average of all points within +/- fraction/2
    octaves of the center frequency.  This gives constant resolution on
    a log-frequency axis.
    """
    smoothed = np.empty_like(data)
    ratio = 2.0 ** (fraction / 2.0)

    for i, fc in enumerate(freqs):
        if fc <= 0:
            smoothed[i] = data[i]
            continue
        f_lo = fc / ratio
        f_hi = fc * ratio
        mask = (freqs >= f_lo) & (freqs <= f_hi)
        if np.any(mask):
            smoothed[i] = np.mean(data[mask])
        else:
            smoothed[i] = data[i]

    return smoothed


# ---------------------------------------------------------------------------
# PDF output — Bode plot
# ---------------------------------------------------------------------------

def save_bode_pdf(
    freqs: np.ndarray,
    magnitude_db: np.ndarray,
    phase_deg: np.ndarray,
    output_path: str,
    title: str = "Frequency Response",
):
    """Save a two-panel Bode plot (magnitude + phase) as PDF."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    fig, (ax_mag, ax_phase) = plt.subplots(
        2, 1, figsize=(10, 7), sharex=True,
        gridspec_kw={"height_ratios": [2, 1]}
    )

    # Magnitude panel
    ax_mag.semilogx(freqs, magnitude_db, "b-", lw=0.9)
    ax_mag.set_ylabel("Magnitude (dB)")
    ax_mag.set_title(title)
    ax_mag.grid(True, which="both", alpha=0.3)
    ax_mag.set_xlim(freqs[0], freqs[-1])

    # Auto-scale y with some margin
    valid = magnitude_db[np.isfinite(magnitude_db)]
    if len(valid) > 0:
        y_lo = max(np.min(valid) - 5, -80)
        y_hi = min(np.max(valid) + 5, 20)
        ax_mag.set_ylim(y_lo, y_hi)

    # Phase panel
    ax_phase.semilogx(freqs, phase_deg, "r-", lw=0.7)
    ax_phase.set_xlabel("Frequency (Hz)")
    ax_phase.set_ylabel("Phase (degrees)")
    ax_phase.grid(True, which="both", alpha=0.3)
    ax_phase.set_ylim(-180, 180)
    ax_phase.set_yticks([-180, -90, 0, 90, 180])

    fig.tight_layout()
    fig.savefig(output_path, format="pdf")
    plt.close(fig)
    print(f"PDF written: {output_path}", file=sys.stderr)


# ---------------------------------------------------------------------------
# CSV output
# ---------------------------------------------------------------------------

def save_csv(
    freqs: np.ndarray,
    magnitude_db: np.ndarray,
    phase_deg: np.ndarray,
    csv_path: str,
):
    """Save frequency response data to CSV."""
    with open(csv_path, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["freq_hz", "magnitude_db", "phase_deg"])
        for freq, mag, ph in zip(freqs, magnitude_db, phase_deg):
            writer.writerow([f"{freq:.2f}", f"{mag:.3f}", f"{ph:.2f}"])
    print(f"CSV written: {csv_path}", file=sys.stderr)


# ---------------------------------------------------------------------------
# Loopback measurement
# ---------------------------------------------------------------------------

def run_loopback(args) -> int:
    """Play chirp from output, capture from input, compute H(f)."""
    import sounddevice as sd

    # Generate the reference chirp
    chirp = generate_log_chirp(
        f_start=args.start_freq,
        f_stop=args.stop_freq,
        duration=args.duration,
        samplerate=args.samplerate,
        amplitude=0.8,
    )

    # Pad with silence for latency compensation
    pre_silence = np.zeros(int(0.1 * args.samplerate), dtype=np.float32)
    post_silence = np.zeros(int(0.5 * args.samplerate), dtype=np.float32)
    play_signal = np.concatenate([pre_silence, chirp, post_silence])

    # Duplex play+record
    print(f"Playing {args.duration:.1f}s chirp ({args.start_freq:.0f}–"
          f"{args.stop_freq:.0f} Hz) and recording...", file=sys.stderr)

    # Make stereo output (duplicate mono to both channels)
    play_stereo = np.column_stack([play_signal, play_signal])
    recorded = sd.playrec(
        play_stereo,
        samplerate=args.samplerate,
        channels=1,
        input_mapping=[1],
        output_mapping=[1, 2],
        device=(args.input_device, args.output_device),
        dtype="float32",
    )
    sd.wait()
    captured = recorded.flatten()

    # Align: find the chirp start in the capture using cross-correlation
    reference = chirp
    captured_trimmed = _align_signals(pre_silence, chirp, captured)

    # Compute transfer function
    freqs, mag_db, phase_deg = compute_transfer_function(
        reference=reference,
        captured=captured_trimmed,
        samplerate=args.samplerate,
        f_start=args.start_freq,
        f_stop=args.stop_freq,
        smoothing_octave=args.smoothing,
    )

    _output_results(args, freqs, mag_db, phase_deg, "Loopback Frequency Response")
    return 0


def _align_signals(
    pre_silence: np.ndarray,
    reference: np.ndarray,
    captured: np.ndarray,
) -> np.ndarray:
    """Align captured signal to reference using cross-correlation.

    Returns the portion of captured that corresponds to the reference chirp.
    """
    # Use a short snippet of the reference for correlation (first 10%)
    snippet_len = max(1024, len(reference) // 10)
    snippet = reference[:snippet_len]

    # Cross-correlate to find delay
    corr = np.correlate(captured[:len(captured) // 2], snippet, mode="valid")
    offset = int(np.argmax(np.abs(corr)))

    # Extract aligned region
    end = min(offset + len(reference), len(captured))
    aligned = captured[offset:end]

    # Zero-pad if shorter than reference
    if len(aligned) < len(reference):
        aligned = np.pad(aligned, (0, len(reference) - len(aligned)))

    return aligned


# ---------------------------------------------------------------------------
# Analyze pre-recorded WAV
# ---------------------------------------------------------------------------

def run_analyze(args) -> int:
    """Analyze a pre-recorded WAV file against a reference."""
    import soundfile as sf

    # Load captured WAV
    captured, cap_sr = sf.read(args.analyze, dtype="float32", always_2d=True)
    captured = captured[:, 0]  # use first channel

    if cap_sr != args.samplerate:
        print(f"WARNING: capture sample rate {cap_sr} Hz differs from "
              f"--samplerate {args.samplerate} Hz. Using capture rate.",
              file=sys.stderr)
        args.samplerate = cap_sr

    # Load or generate reference
    if args.reference:
        ref, ref_sr = sf.read(args.reference, dtype="float32", always_2d=True)
        reference = ref[:, 0]
        if ref_sr != args.samplerate:
            print(f"WARNING: reference sample rate {ref_sr} Hz differs from "
                  f"capture rate {args.samplerate} Hz.", file=sys.stderr)
    else:
        # Assume reference was the standard chirp
        print("No --reference file given; generating default chirp as reference.",
              file=sys.stderr)
        reference = generate_log_chirp(
            f_start=args.start_freq,
            f_stop=args.stop_freq,
            duration=args.duration,
            samplerate=args.samplerate,
        )

    # Compute transfer function
    freqs, mag_db, phase_deg = compute_transfer_function(
        reference=reference,
        captured=captured,
        samplerate=args.samplerate,
        f_start=args.start_freq,
        f_stop=args.stop_freq,
        smoothing_octave=args.smoothing,
    )

    _output_results(args, freqs, mag_db, phase_deg, "Frequency Response (WAV analysis)")
    return 0


# ---------------------------------------------------------------------------
# Synthetic test mode
# ---------------------------------------------------------------------------

def run_test(args) -> int:
    """Generate chirp, apply a known filter, compute H(f), verify."""
    samplerate = args.samplerate

    # Generate reference chirp
    reference = generate_log_chirp(
        f_start=args.start_freq,
        f_stop=args.stop_freq,
        duration=args.duration,
        samplerate=samplerate,
    )

    # Apply a known filter: 2nd-order Butterworth LPF at 5 kHz
    # This gives a predictable -12 dB/octave rolloff above 5 kHz
    fc = 5000.0
    sos = butter(2, fc, btype="low", fs=samplerate, output="sos")
    captured = sosfilt(sos, reference).astype(np.float32)

    # Add a small amount of noise to be realistic
    rng = np.random.default_rng(42)
    noise = 0.001 * rng.standard_normal(len(captured)).astype(np.float32)
    captured += noise

    # Compute transfer function
    freqs, mag_db, phase_deg = compute_transfer_function(
        reference=reference,
        captured=captured,
        samplerate=samplerate,
        f_start=args.start_freq,
        f_stop=args.stop_freq,
        smoothing_octave=args.smoothing,
    )

    # Print summary
    print("Test mode: 2nd-order Butterworth LPF @ 5 kHz", file=sys.stderr)
    print(f"  Expected: 0 dB passband, -12 dB/octave asymptotic rolloff",
          file=sys.stderr)

    # Check a few points (theoretical values from sosfreqz)
    idx_1k = np.argmin(np.abs(freqs - 1000))
    idx_5k = np.argmin(np.abs(freqs - 5000))
    idx_10k = np.argmin(np.abs(freqs - 10000))
    idx_20k = np.argmin(np.abs(freqs - 20000))

    print(f"  @ 1 kHz:  {mag_db[idx_1k]:+.1f} dB  (expect ~0 dB)", file=sys.stderr)
    print(f"  @ 5 kHz:  {mag_db[idx_5k]:+.1f} dB  (expect -3 dB)", file=sys.stderr)
    if idx_10k < len(mag_db):
        print(f"  @ 10 kHz: {mag_db[idx_10k]:+.1f} dB  (expect -14.3 dB)", file=sys.stderr)
    if idx_20k < len(mag_db):
        print(f"  @ 20 kHz: {mag_db[idx_20k]:+.1f} dB  (expect -41.7 dB, edge effect likely)", file=sys.stderr)

    _output_results(args, freqs, mag_db, phase_deg,
                    "Frequency Response — Test (Butterworth LPF @ 5 kHz)")
    return 0


# ---------------------------------------------------------------------------
# Output helper
# ---------------------------------------------------------------------------

def _output_results(
    args,
    freqs: np.ndarray,
    mag_db: np.ndarray,
    phase_deg: np.ndarray,
    title: str,
):
    """Save PDF and/or CSV, or print summary to terminal."""
    if args.csv:
        save_csv(freqs, mag_db, phase_deg, args.csv)

    if args.output:
        save_bode_pdf(freqs, mag_db, phase_deg, args.output, title=title)

    if not args.csv and not args.output:
        # Print a short summary to terminal
        print(f"\nFrequency response: {freqs[0]:.0f} Hz – {freqs[-1]:.0f} Hz",
              file=sys.stderr)
        valid = mag_db[np.isfinite(mag_db)]
        if len(valid) > 0:
            print(f"  Magnitude range: {np.min(valid):+.1f} to {np.max(valid):+.1f} dB",
                  file=sys.stderr)
            # Find -3 dB point (relative to max)
            ref_level = np.max(valid)
            below_3db = np.where(mag_db < (ref_level - 3.0))[0]
            if len(below_3db) > 0:
                f3db = freqs[below_3db[0]]
                print(f"  -3 dB bandwidth: {f3db:.0f} Hz", file=sys.stderr)
        print("  (use --output FILE.pdf and/or --csv FILE.csv to save results)",
              file=sys.stderr)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> int:
    parser = argparse.ArgumentParser(
        description="Audio frequency response sweeper (chirp method).",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""\
Examples:
  # Soundcard loopback self-test (output → input cable)
  %(prog)s --loopback --output loopback.pdf --csv loopback.csv

  # Measure DUT: soundcard out → DUT in, DUT out → soundcard in
  %(prog)s --loopback --start-freq 100 --stop-freq 15000 --output dut.pdf

  # Analyze a pre-recorded WAV file
  %(prog)s --analyze captured.wav --reference chirp.wav --output response.pdf

  # Synthetic test (no hardware, verifies algorithm)
  %(prog)s --test --output test.pdf
""",
    )

    add_audio_args(parser, duplex=True)
    add_test_args(parser)

    # Mode selection
    mode = parser.add_argument_group("mode")
    mode.add_argument("--loopback", action="store_true",
                      help="Generate chirp on output, capture on input (duplex)")
    mode.add_argument("--analyze", metavar="FILE.wav",
                      help="Analyze a pre-recorded WAV capture")
    mode.add_argument("--reference", metavar="FILE.wav",
                      help="Reference chirp WAV (for --analyze mode)")

    # Sweep parameters
    sweep = parser.add_argument_group("sweep")
    sweep.add_argument("--start-freq", type=float, default=20.0, metavar="HZ",
                       help="Sweep start frequency (default 20 Hz)")
    sweep.add_argument("--stop-freq", type=float, default=20000.0, metavar="HZ",
                       help="Sweep stop frequency (default 20000 Hz)")
    sweep.add_argument("--duration", type=float, default=5.0, metavar="SEC",
                       help="Chirp duration in seconds (default 5.0)")
    sweep.add_argument("--smoothing", type=float, default=1 / 12, metavar="OCT",
                       help="Fractional-octave smoothing (default 1/12, 0 to disable)")

    # Output
    out = parser.add_argument_group("output files")
    out.add_argument("--output", metavar="FILE.pdf",
                     help="Save Bode plot as PDF")
    out.add_argument("--csv", metavar="FILE.csv",
                     help="Save frequency/magnitude/phase data as CSV")

    args = parser.parse_args()

    if args.list_devices:
        from dsp_pipeline.args import open_stream_from_args
        open_stream_from_args(args, duplex=True)
        return 0

    # Determine mode
    if args.test:
        return run_test(args)
    elif args.analyze:
        return run_analyze(args)
    elif args.loopback:
        return run_loopback(args)
    else:
        parser.error("Specify a mode: --loopback, --analyze FILE, or --test")
        return 1


if __name__ == "__main__":
    sys.exit(main())
