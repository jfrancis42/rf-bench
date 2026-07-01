#!/usr/bin/env python3
"""
two_tone_imd.py — Two-tone IMD generator + analyzer.

Generates two equal-amplitude tones (default 700 + 1900 Hz, the standard
SSB two-tone test) from soundcard output, captures the result from
soundcard input (or loopback), and measures 3rd/5th/7th-order
intermodulation distortion products. Reports IMD in dB below carrier
(dBc) and produces a PDF spectrum plot with all products labeled.

Modes:
  --generate-only   Output tones, no capture or analysis
  --analyze-only    Capture and measure, no generation
  --loopback        Generate + capture simultaneously (default)
  --test            Synthetic distorted signal (no hardware needed)
"""

from __future__ import annotations

import argparse
import signal
import sys
import time
from datetime import datetime
from pathlib import Path

import numpy as np

# Suppress mixed-install matplotlib Axes3D import warning (harmless).
import warnings
warnings.filterwarnings("ignore", message="Unable to import Axes3D")

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from dsp_pipeline import TestSignal, add_audio_args, add_test_args


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

SAMPLERATE = 48000
DEFAULT_F1 = 700.0      # Hz — standard SSB two-tone lower
DEFAULT_F2 = 1900.0     # Hz — standard SSB two-tone upper
DEFAULT_DURATION = 2.0  # seconds of capture
AMPLITUDE = 0.4         # per-tone amplitude (each tone; sum peaks at 0.8)
WINDOW_FRAC = 0.8       # fraction of capture to window (skip transients)


# ---------------------------------------------------------------------------
# IMD product definitions
# ---------------------------------------------------------------------------

def imd_products(f1: float, f2: float) -> list[tuple[str, float, int]]:
    """Return (label, frequency_hz, order) for all standard IMD products.

    Products are:
      3rd order: 2f1-f2, 2f2-f1
      5th order: 3f1-2f2, 3f2-2f1
      7th order: 4f1-3f2, 4f2-3f1
      Also includes 2nd-order sum/difference: f1+f2, f2-f1
      And higher even-order: 2f1+f2, 2f2+f1 (usually out of passband)
    """
    products = []
    # 2nd order
    products.append(("f2-f1", abs(f2 - f1), 2))
    products.append(("f1+f2", f1 + f2, 2))
    # 3rd order (closest to fundamentals, most critical)
    products.append(("2f1-f2", abs(2 * f1 - f2), 3))
    products.append(("2f2-f1", abs(2 * f2 - f1), 3))
    # 5th order
    products.append(("3f1-2f2", abs(3 * f1 - 2 * f2), 5))
    products.append(("3f2-2f1", abs(3 * f2 - 2 * f1), 5))
    # 7th order
    products.append(("4f1-3f2", abs(4 * f1 - 3 * f2), 7))
    products.append(("4f2-3f1", abs(4 * f2 - 3 * f1), 7))
    # Filter out negative or zero frequencies and above Nyquist
    return [(label, freq, order) for label, freq, order in products
            if 0 < freq < SAMPLERATE / 2]


# ---------------------------------------------------------------------------
# Signal generation
# ---------------------------------------------------------------------------

def generate_two_tone(f1: float, f2: float, duration: float,
                      samplerate: int = SAMPLERATE,
                      amplitude: float = AMPLITUDE) -> np.ndarray:
    """Generate two equal-amplitude sine tones, float32."""
    t = np.arange(int(samplerate * duration)) / samplerate
    signal = amplitude * (np.sin(2 * np.pi * f1 * t) +
                          np.sin(2 * np.pi * f2 * t))
    return signal.astype(np.float32)


# ---------------------------------------------------------------------------
# Synthetic distorted test signal
# ---------------------------------------------------------------------------

def generate_distorted_two_tone(f1: float, f2: float, duration: float,
                                samplerate: int = SAMPLERATE,
                                imd3_db: float = -30.0,
                                imd5_db: float = -50.0,
                                imd7_db: float = -65.0,
                                noise_db: float = -80.0) -> np.ndarray:
    """Generate a two-tone signal with known IMD products for testing.

    IMD levels are specified in dBc (dB below each carrier tone).
    """
    t = np.arange(int(samplerate * duration)) / samplerate
    amp = AMPLITUDE

    # Fundamentals
    sig = amp * np.sin(2 * np.pi * f1 * t) + amp * np.sin(2 * np.pi * f2 * t)

    # Add IMD products at specified levels
    imd3_amp = amp * 10 ** (imd3_db / 20.0)
    imd5_amp = amp * 10 ** (imd5_db / 20.0)
    imd7_amp = amp * 10 ** (imd7_db / 20.0)

    # 3rd order
    sig += imd3_amp * np.sin(2 * np.pi * (2 * f1 - f2) * t)
    sig += imd3_amp * np.sin(2 * np.pi * (2 * f2 - f1) * t)
    # 5th order
    sig += imd5_amp * np.sin(2 * np.pi * (3 * f1 - 2 * f2) * t)
    sig += imd5_amp * np.sin(2 * np.pi * (3 * f2 - 2 * f1) * t)
    # 7th order
    sig += imd7_amp * np.sin(2 * np.pi * (4 * f1 - 3 * f2) * t)
    sig += imd7_amp * np.sin(2 * np.pi * (4 * f2 - 3 * f1) * t)

    # Noise floor
    noise_amp = amp * 10 ** (noise_db / 20.0)
    rng = np.random.default_rng(42)
    sig += noise_amp * rng.standard_normal(len(sig))

    return sig.astype(np.float32)


# ---------------------------------------------------------------------------
# Analysis
# ---------------------------------------------------------------------------

def analyze_imd(signal: np.ndarray, f1: float, f2: float,
                samplerate: int = SAMPLERATE,
                window: str = "blackmanharris") -> dict:
    """Analyze a captured signal for IMD products.

    Returns a dict with:
      - 'fundamentals': list of (freq, level_dB) for f1, f2
      - 'products': list of (label, freq, level_dBc, order)
      - 'carrier_level_dB': average of the two fundamental levels
      - 'spectrum': (freqs, magnitude_dB) for plotting
    """
    n = len(signal)

    # Apply window
    if window == "blackmanharris":
        win = np.blackman(n)  # close to blackman-harris for sidelobe rejection
        # Use actual scipy blackmanharris if available
        try:
            from scipy.signal.windows import blackmanharris
            win = blackmanharris(n)
        except ImportError:
            pass
    elif window == "hann":
        win = np.hanning(n)
    elif window == "flat":
        win = np.ones(n)
    else:
        win = np.blackman(n)

    windowed = signal * win.astype(np.float32)

    # FFT
    spectrum = np.fft.rfft(windowed)
    freqs = np.fft.rfftfreq(n, 1.0 / samplerate)
    magnitude = np.abs(spectrum)

    # Normalize: correct for window coherent gain
    coherent_gain = np.sum(win) / n
    magnitude = magnitude / (coherent_gain * n / 2)

    # Convert to dB (reference: full-scale sine at amplitude 1.0)
    mag_db = 20 * np.log10(np.maximum(magnitude, 1e-12))

    # Find fundamental peaks using peak search within +/- tolerance
    def find_peak_db(target_freq: float, tolerance_hz: float = 20.0) -> float:
        """Find the peak magnitude in dB near target_freq."""
        idx_lo = int((target_freq - tolerance_hz) * n / samplerate)
        idx_hi = int((target_freq + tolerance_hz) * n / samplerate)
        idx_lo = max(0, idx_lo)
        idx_hi = min(len(mag_db) - 1, idx_hi)
        if idx_lo >= idx_hi:
            return -120.0
        return float(np.max(mag_db[idx_lo:idx_hi + 1]))

    # Measure fundamentals
    f1_level = find_peak_db(f1)
    f2_level = find_peak_db(f2)
    carrier_level = (f1_level + f2_level) / 2.0

    # Measure IMD products
    products = imd_products(f1, f2)
    measured = []
    for label, freq, order in products:
        level = find_peak_db(freq)
        level_dbc = level - carrier_level
        measured.append((label, freq, level_dbc, order))

    return {
        "fundamentals": [(f1, f1_level), (f2, f2_level)],
        "products": measured,
        "carrier_level_dB": carrier_level,
        "spectrum": (freqs, mag_db),
    }


# ---------------------------------------------------------------------------
# PDF output
# ---------------------------------------------------------------------------

def write_pdf(results: dict, f1: float, f2: float, output_path: str,
              label: str = "") -> None:
    """Write a single-page PDF with magnitude spectrum and IMD annotations."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    freqs, mag_db = results["spectrum"]
    carrier_db = results["carrier_level_dB"]
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    fig, ax = plt.subplots(figsize=(11, 7.5))

    # Plot spectrum
    ax.plot(freqs, mag_db, color="#1f77b4", linewidth=0.6, alpha=0.8)

    # Mark fundamentals
    for freq, level in results["fundamentals"]:
        ax.axvline(freq, color="green", linestyle="-", linewidth=0.8, alpha=0.6)
        ax.annotate(
            f"{freq:.0f} Hz\n{level:.1f} dB",
            xy=(freq, level), xytext=(5, 8), textcoords="offset points",
            fontsize=7, color="green", fontweight="bold",
        )

    # Mark IMD products
    colors_by_order = {2: "#888888", 3: "red", 5: "darkorange", 7: "purple"}
    for label_str, freq, level_dbc, order in results["products"]:
        color = colors_by_order.get(order, "gray")
        level_abs = carrier_db + level_dbc
        ax.axvline(freq, color=color, linestyle="--", linewidth=0.6, alpha=0.5)
        ax.annotate(
            f"{label_str}\n{level_dbc:.1f} dBc",
            xy=(freq, level_abs), xytext=(3, 10), textcoords="offset points",
            fontsize=6.5, color=color, rotation=45,
            arrowprops=dict(arrowstyle="->", color=color, lw=0.6),
        )

    # Axis formatting
    # Set x-axis to show the interesting region around the tones
    all_freqs = [f1, f2] + [f for _, f, _, _ in results["products"]]
    x_lo = max(0, min(all_freqs) - 200)
    x_hi = min(SAMPLERATE / 2, max(all_freqs) + 200)
    ax.set_xlim(x_lo, x_hi)

    # Y-axis: from noise floor to a bit above the peaks
    y_top = carrier_db + 10
    y_bot = carrier_db - 90
    ax.set_ylim(y_bot, y_top)

    ax.set_xlabel("Frequency (Hz)")
    ax.set_ylabel("Magnitude (dB)")
    ax.grid(True, which="both", alpha=0.3)

    # Title
    title_lines = [
        f"Two-Tone IMD Analysis — {f1:.0f} + {f2:.0f} Hz",
    ]
    # Summary line
    imd3_products = [p for p in results["products"] if p[3] == 3]
    if imd3_products:
        worst_imd3 = max(p[2] for p in imd3_products)
        title_lines.append(
            f"IMD3: {worst_imd3:.1f} dBc  •  "
            f"Carrier: {carrier_db:.1f} dB  •  {ts}"
        )
    else:
        title_lines.append(f"Carrier: {carrier_db:.1f} dB  •  {ts}")
    if label:
        title_lines[0] += f" — {label}"

    ax.set_title("\n".join(title_lines), fontsize=10)

    # Legend for orders
    from matplotlib.lines import Line2D
    legend_elements = [
        Line2D([0], [0], color="green", linewidth=1.5, label="Fundamentals"),
        Line2D([0], [0], color="red", linewidth=1.5, linestyle="--", label="3rd order"),
        Line2D([0], [0], color="darkorange", linewidth=1.5, linestyle="--", label="5th order"),
        Line2D([0], [0], color="purple", linewidth=1.5, linestyle="--", label="7th order"),
    ]
    ax.legend(handles=legend_elements, loc="upper right", fontsize=8, framealpha=0.92)

    fig.tight_layout()
    fig.savefig(output_path, format="pdf")
    plt.close(fig)


# ---------------------------------------------------------------------------
# Print results
# ---------------------------------------------------------------------------

def print_results(results: dict, f1: float, f2: float) -> None:
    """Print IMD measurement results to stdout."""
    print(f"\nTwo-Tone IMD Analysis: {f1:.0f} + {f2:.0f} Hz")
    print("=" * 55)

    print(f"\nFundamentals:")
    for freq, level in results["fundamentals"]:
        print(f"  {freq:8.1f} Hz : {level:+.1f} dB")
    print(f"  Carrier avg  : {results['carrier_level_dB']:+.1f} dB")

    print(f"\nIMD Products:")
    print(f"  {'Product':<12} {'Freq (Hz)':>10} {'Level (dBc)':>12} {'Order':>6}")
    print(f"  {'-'*12} {'-'*10} {'-'*12} {'-'*6}")
    for label, freq, level_dbc, order in sorted(results["products"], key=lambda x: x[3]):
        print(f"  {label:<12} {freq:>10.1f} {level_dbc:>+12.1f} {order:>6}")

    # Summary
    imd3 = [p for p in results["products"] if p[3] == 3]
    imd5 = [p for p in results["products"] if p[3] == 5]
    imd7 = [p for p in results["products"] if p[3] == 7]
    print(f"\nSummary:")
    if imd3:
        worst = max(p[2] for p in imd3)
        print(f"  IMD3 (worst): {worst:+.1f} dBc")
    if imd5:
        worst = max(p[2] for p in imd5)
        print(f"  IMD5 (worst): {worst:+.1f} dBc")
    if imd7:
        worst = max(p[2] for p in imd7)
        print(f"  IMD7 (worst): {worst:+.1f} dBc")


# ---------------------------------------------------------------------------
# Modes
# ---------------------------------------------------------------------------

def run_generate_only(args) -> int:
    """Generate tones continuously until Ctrl-C."""
    import sounddevice as sd

    print(f"Generating {args.f1:.0f} + {args.f2:.0f} Hz tones on output device...")
    print("Press Ctrl-C to stop.")

    # Generate a long buffer and loop it
    duration = 10.0  # 10-second loop buffer
    tone = generate_two_tone(args.f1, args.f2, duration, args.samplerate)

    stop_flag = [False]

    def sigint_handler(signum, frame):
        stop_flag[0] = True

    old_handler = signal.signal(signal.SIGINT, sigint_handler)

    try:
        # Play in a loop
        idx = [0]
        blocksize = args.blocksize

        def callback(outdata, frames, time_info, status):
            start = idx[0]
            end = start + frames
            if end <= len(tone):
                outdata[:, 0] = tone[start:end]
            else:
                # Wrap around
                first = len(tone) - start
                outdata[:first, 0] = tone[start:]
                outdata[first:, 0] = tone[:frames - first]
            # Duplicate to all output channels
            for ch in range(1, outdata.shape[1]):
                outdata[:, ch] = outdata[:, 0]
            idx[0] = (idx[0] + frames) % len(tone)

        channels_out = getattr(args, "channels_out", 2)
        with sd.OutputStream(
            device=args.output_device,
            samplerate=args.samplerate,
            blocksize=blocksize,
            channels=channels_out,
            dtype="float32",
            callback=callback,
        ):
            while not stop_flag[0]:
                time.sleep(0.1)
    finally:
        signal.signal(signal.SIGINT, old_handler)
        print("\nStopped.")

    return 0


def run_analyze_only(args) -> int:
    """Capture audio and analyze for IMD."""
    import sounddevice as sd

    duration = args.duration
    n_samples = int(args.samplerate * duration)
    print(f"Capturing {duration:.1f}s from input device for IMD analysis...")

    captured = sd.rec(
        n_samples,
        samplerate=args.samplerate,
        channels=1,
        dtype="float32",
        device=args.input_device,
    )
    sd.wait()

    audio = captured[:, 0]

    # Skip initial transient — use the middle portion
    skip = int(len(audio) * (1.0 - WINDOW_FRAC) / 2)
    audio = audio[skip:len(audio) - skip]

    results = analyze_imd(audio, args.f1, args.f2, args.samplerate)
    print_results(results, args.f1, args.f2)

    if args.output:
        write_pdf(results, args.f1, args.f2, args.output)
        print(f"\nWrote PDF -> {args.output}")

    return 0


def run_loopback(args) -> int:
    """Generate tones and capture simultaneously."""
    import sounddevice as sd

    duration = args.duration
    n_samples = int(args.samplerate * duration)
    print(f"Loopback: generating {args.f1:.0f} + {args.f2:.0f} Hz, "
          f"capturing {duration:.1f}s...")

    # Generate the tone buffer
    tone = generate_two_tone(args.f1, args.f2, duration + 0.5, args.samplerate)

    # Use playrec for simultaneous play+record
    channels_out = getattr(args, "channels_out", 2)
    play_data = np.tile(tone[:n_samples].reshape(-1, 1), (1, channels_out))

    captured = sd.playrec(
        play_data,
        samplerate=args.samplerate,
        channels=1,
        input_mapping=[1],
        dtype="float32",
        device=(args.input_device, args.output_device),
    )
    sd.wait()

    audio = captured[:, 0]

    # Skip transients
    skip = int(len(audio) * (1.0 - WINDOW_FRAC) / 2)
    audio = audio[skip:len(audio) - skip]

    results = analyze_imd(audio, args.f1, args.f2, args.samplerate)
    print_results(results, args.f1, args.f2)

    if args.output:
        write_pdf(results, args.f1, args.f2, args.output)
        print(f"\nWrote PDF -> {args.output}")

    return 0


def run_test(args) -> int:
    """Run with synthetic distorted signal."""
    print(f"Test mode: synthetic two-tone with known IMD products")
    print(f"  f1={args.f1:.0f} Hz, f2={args.f2:.0f} Hz")
    print(f"  Injected: IMD3=-30 dBc, IMD5=-50 dBc, IMD7=-65 dBc")

    audio = generate_distorted_two_tone(
        args.f1, args.f2, args.duration, args.samplerate,
        imd3_db=-30.0, imd5_db=-50.0, imd7_db=-65.0, noise_db=-80.0,
    )

    results = analyze_imd(audio, args.f1, args.f2, args.samplerate)
    print_results(results, args.f1, args.f2)

    if args.output:
        write_pdf(results, args.f1, args.f2, args.output)
        print(f"\nWrote PDF -> {args.output}")

    return 0


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> int:
    parser = argparse.ArgumentParser(
        description="Two-tone IMD generator + analyzer for SSB transmitter testing.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""\
Modes:
  --generate-only   Output tones only (no capture)
  --analyze-only    Capture and analyze only (no generation)
  --loopback        Generate + capture simultaneously (default)
  --test            Use synthetic distorted signal (no hardware)

Examples:
  python two_tone_imd.py --test --output imd_test.pdf
  python two_tone_imd.py --generate-only --output-device 4
  python two_tone_imd.py --analyze-only --input-device 2 --output imd.pdf
  python two_tone_imd.py --loopback --input-device 2 --output-device 4 --output imd.pdf
  python two_tone_imd.py --f1 600 --f2 1500 --test --output custom.pdf
""",
    )

    add_audio_args(parser)
    add_test_args(parser)

    mode = parser.add_argument_group("mode")
    mode.add_argument("--generate-only", action="store_true",
                      help="Output tones only, no capture or analysis")
    mode.add_argument("--analyze-only", action="store_true",
                      help="Capture and analyze only, no tone generation")
    mode.add_argument("--loopback", action="store_true",
                      help="Generate + capture simultaneously (default if no mode given)")

    params = parser.add_argument_group("IMD parameters")
    params.add_argument("--f1", type=float, default=DEFAULT_F1, metavar="HZ",
                        help=f"First tone frequency in Hz (default {DEFAULT_F1:.0f})")
    params.add_argument("--f2", type=float, default=DEFAULT_F2, metavar="HZ",
                        help=f"Second tone frequency in Hz (default {DEFAULT_F2:.0f})")
    params.add_argument("--duration", type=float, default=DEFAULT_DURATION, metavar="SEC",
                        help=f"Capture duration in seconds (default {DEFAULT_DURATION:.1f})")
    params.add_argument("--label", default="",
                        help="Label for the PDF chart title")

    output = parser.add_argument_group("output")
    output.add_argument("--output", metavar="FILE.pdf",
                        help="Output PDF path")

    args = parser.parse_args()

    if args.list_devices:
        import sounddevice as sd
        print(sd.query_devices())
        return 0

    # Validate tone frequencies
    if args.f1 <= 0 or args.f2 <= 0:
        print("Error: tone frequencies must be positive", file=sys.stderr)
        return 1
    if args.f1 == args.f2:
        print("Error: f1 and f2 must be different frequencies", file=sys.stderr)
        return 1
    if max(args.f1, args.f2) >= args.samplerate / 2:
        print(f"Error: tone frequencies must be below Nyquist "
              f"({args.samplerate / 2:.0f} Hz)", file=sys.stderr)
        return 1

    # Ensure f1 < f2 for consistent product labeling
    if args.f1 > args.f2:
        args.f1, args.f2 = args.f2, args.f1

    # Determine mode
    if args.test:
        return run_test(args)
    elif args.generate_only:
        return run_generate_only(args)
    elif args.analyze_only:
        return run_analyze_only(args)
    else:
        # Default to loopback
        return run_loopback(args)


if __name__ == "__main__":
    sys.exit(main())
