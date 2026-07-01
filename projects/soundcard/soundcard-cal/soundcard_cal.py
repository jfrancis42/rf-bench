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
    from scipy.signal import correlate

    n = min(len(captured), len(reference))
    captured = captured[:n]
    reference = reference[:n]

    # Find time delay and align signals
    corr = correlate(captured, reference, mode='same')
    delay_samples = np.argmax(corr) - len(reference)//2

    # Align captured signal to reference
    if delay_samples > 0:
        captured_aligned = captured[delay_samples:]
        reference_aligned = reference[:-delay_samples] if delay_samples < n else reference
    elif delay_samples < 0:
        captured_aligned = captured[:delay_samples]
        reference_aligned = reference[-delay_samples:]
    else:
        captured_aligned = captured
        reference_aligned = reference

    # Ensure same length after alignment
    n_aligned = min(len(captured_aligned), len(reference_aligned))
    captured_aligned = captured_aligned[:n_aligned]
    reference_aligned = reference_aligned[:n_aligned]

    # cross-spectral method with aligned signals
    window = get_window("hann", n_aligned)
    X = np.fft.rfft(reference_aligned * window)
    Y = np.fft.rfft(captured_aligned * window)
    H = Y / (X + 1e-10)
    freqs = np.fft.rfftfreq(n_aligned, 1.0 / samplerate)
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


def detect_loopback_gain(device_in, device_out, samplerate: int = 48000,
                         duration: float = 0.5) -> tuple[float | None, float | None, str]:
    """
    Send a test tone and measure loopback gain.
    Returns: (gain_ratio, safe_amplitude, status_message)

    The gain_ratio is the measured output/input ratio.
    The safe_amplitude is scaled to use ~70% of available range.
    """
    import sounddevice as sd

    test_amp = 0.1  # Start conservative
    n_samples = int(duration * samplerate)
    t = np.linspace(0, duration, n_samples, endpoint=False)
    tone = (test_amp * np.sin(2 * np.pi * 1000 * t)).astype(np.float32)

    try:
        recorded = sd.playrec(tone.reshape(-1, 1),
                             samplerate=samplerate,
                             input_mapping=[1],
                             output_mapping=[1],
                             device=(device_in, device_out),
                             dtype='float32')
        sd.wait()
        recorded = recorded.flatten()
    except Exception as e:
        return None, None, f"ERROR: Failed to access device - {e}"

    # Measure gain (AC-coupled RMS)
    tone_ac = tone - np.mean(tone)
    recorded_ac = recorded - np.mean(recorded)
    out_rms = np.sqrt(np.mean(tone_ac ** 2))
    in_rms = np.sqrt(np.mean(recorded_ac ** 2))
    gain = in_rms / (out_rms + 1e-10)

    # Check for problems
    peak = np.max(np.abs(recorded))
    if peak < 0.01:
        return None, None, "ERROR: No signal detected - check loopback connection"
    if peak > 0.95:
        # Try again at 0.01
        tone_low = (0.01 * np.sin(2 * np.pi * 1000 * t)).astype(np.float32)
        recorded_low = sd.playrec(tone_low.reshape(-1, 1),
                                  samplerate=samplerate,
                                  input_mapping=[1],
                                  output_mapping=[1],
                                  device=(device_in, device_out),
                                  dtype='float32')
        sd.wait()
        recorded_low = recorded_low.flatten()
        peak_low = np.max(np.abs(recorded_low))
        if peak_low > 0.95:
            return None, None, "ERROR: Clipping detected even at 0.01 amplitude - check gain/attenuator"
        # Recalculate with lower signal
        tone_low_ac = tone_low - np.mean(tone_low)
        recorded_low_ac = recorded_low - np.mean(recorded_low)
        out_rms = np.sqrt(np.mean(tone_low_ac ** 2))
        in_rms = np.sqrt(np.mean(recorded_low_ac ** 2))
        gain = in_rms / (out_rms + 1e-10)

    # Calculate safe amplitude (target 70% of full scale to avoid clipping)
    target_peak = 0.7
    # Account for crest factor (sine wave peak is sqrt(2) * RMS)
    safe_amp = target_peak / (gain * np.sqrt(2))

    # Sanity check
    if safe_amp < 0.001:
        return gain, 0.001, f"WARNING: Very high gain ({gain:.1f}×), using minimum amplitude 0.001"
    if safe_amp > 0.9:
        safe_amp = 0.9

    return gain, safe_amp, f"OK: {gain:.1f}× gain detected, using amplitude {safe_amp:.3f}"


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Soundcard self-calibration via loopback.")
    add_audio_args(parser)
    add_test_args(parser)
    parser.add_argument("--output", default=None,
                        help="Calibration output JSON file (default: ~/.config/rf-bench/soundcard_cal_<device>.json)")
    parser.add_argument("--pdf", metavar="FILE",
                        help="Generate calibration report PDF")
    parser.add_argument("--duration", type=float, default=3.0,
                        help="Test signal duration in seconds (default 3)")
    parser.add_argument("--amplitude", type=float, default=None,
                        help="Test signal amplitude 0-1 (default: auto-detect)")
    args = parser.parse_args()

    if args.list_devices:
        from dsp_pipeline.args import open_stream_from_args
        open_stream_from_args(args)
        return 0

    samplerate = args.samplerate
    duration = args.duration

    if args.test:
        amplitude = args.amplitude if args.amplitude is not None else 0.5
        print("Test mode: simulating loopback with synthetic impairments")
        ts = TestSignal(samplerate, duration)

        # simulate a non-ideal soundcard
        sweep_ref = ts.sweep(f_start=20, f_stop=20000, amplitude=amplitude)
        # add slight frequency response roll-off and noise
        t = np.arange(len(sweep_ref)) / samplerate
        rolloff = 1.0 - 0.1 * (t / duration)  # slight HF roll-off
        sweep_cap = sweep_ref * rolloff + ts.noise(amplitude=0.001)

        # THD test
        tone_ref = ts.sine(freq=1000, amplitude=amplitude)
        # add 2nd harmonic at -60 dB
        tone_cap = tone_ref + 0.0005 * np.sin(2 * np.pi * 2000 * t[:len(tone_ref)])

        # noise floor
        silence = ts.noise(amplitude=0.0001)

        # crosstalk: signal on left, measure on right
        crosstalk_left = ts.sine(freq=1000, amplitude=amplitude)
        crosstalk_right = ts.sine(freq=1000, amplitude=amplitude * 0.001)  # -60 dB
    else:
        import sounddevice as sd
        print("Loopback calibration requires output → input connection.",
              file=sys.stderr)
        print("Connect soundcard output to input (or use a loopback cable).",
              file=sys.stderr)
        print()

        # Check device capabilities
        input_dev_info = sd.query_devices(args.input_device, 'input')
        max_input_channels = input_dev_info['max_input_channels']
        is_stereo = max_input_channels >= 2

        # Auto-detect loopback gain and determine safe amplitude
        if args.amplitude is None:
            print("Detecting loopback gain...", file=sys.stderr)
            gain, amplitude, status = detect_loopback_gain(
                args.input_device, args.output_device, samplerate, duration=0.5)
            print(f"  {status}", file=sys.stderr)
            if gain is None:
                print(f"ABORT: {status}", file=sys.stderr)
                return 1
        else:
            amplitude = args.amplitude
            print(f"Using user-specified amplitude: {amplitude:.3f}", file=sys.stderr)

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
        sweep_ref = ts.sweep(f_start=20, f_stop=20000, amplitude=amplitude)
        sweep_cap = sd.playrec(sweep_ref.reshape(-1, 1), samplerate=samplerate,
                               input_mapping=[1], output_mapping=[1],
                               device=(args.input_device, args.output_device),
                               dtype="float32")
        sd.wait()
        sweep_cap = sweep_cap.flatten()

        # 3. THD (1 kHz tone)
        print("Measuring THD...", file=sys.stderr)
        tone_ref = ts.sine(freq=1000, amplitude=amplitude)
        tone_cap = sd.playrec(tone_ref.reshape(-1, 1), samplerate=samplerate,
                              input_mapping=[1], output_mapping=[1],
                              device=(args.input_device, args.output_device),
                              dtype="float32")
        sd.wait()
        tone_cap = tone_cap.flatten()

        # 4. Crosstalk (tone on ch1, measure ch2) — only for stereo devices
        if is_stereo:
            print("Measuring crosstalk...", file=sys.stderr)
            stereo_out = np.column_stack([
                ts.sine(freq=1000, amplitude=amplitude),
                np.zeros(ts.n_samples, dtype=np.float32),
            ])
            crosstalk_cap = sd.playrec(stereo_out, samplerate=samplerate,
                                       channels=2,
                                       device=(args.input_device, args.output_device),
                                       dtype="float32")
            sd.wait()
            crosstalk_left = crosstalk_cap[:, 0]
            crosstalk_right = crosstalk_cap[:, 1]
        else:
            print("Skipping crosstalk test (mono device)...", file=sys.stderr)
            crosstalk_left = ts.sine(freq=1000, amplitude=amplitude)
            crosstalk_right = np.zeros_like(crosstalk_left)

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
    if not args.test and 'is_stereo' in locals() and not is_stereo:
        print(f"Crosstalk:      N/A (mono device)")
    else:
        print(f"Crosstalk:      {crosstalk_db:.1f} dB")

    # Calculate ripple in the audio passband (100 Hz - 10 kHz)
    audio_mask = (freqs >= 100) & (freqs <= 10000)
    audio_response = freq_resp_db[audio_mask]
    if len(audio_response) > 0:
        ripple = np.max(audio_response) - np.min(audio_response)
        mean_response = np.mean(audio_response)
        print(f"Freq response:  {ripple:.2f} dB ripple, {mean_response:.1f} dB mean (100 Hz–10 kHz)")
    else:
        print(f"Freq response:  {np.max(freq_resp_db[10:-10]) - np.min(freq_resp_db[10:-10]):.2f} dB ripple (20 Hz–20 kHz)")

    # Determine output path
    if args.output is None:
        # Standard location: ~/.config/rf-bench/soundcard_cal_<device>.json
        from pathlib import Path
        config_dir = Path.home() / ".config" / "rf-bench"
        config_dir.mkdir(parents=True, exist_ok=True)

        # Create a safe device name from the device info
        if args.test:
            device_name = "test"
        else:
            import sounddevice as sd
            dev_info = sd.query_devices(args.input_device, 'input')
            device_name = dev_info['name'].replace('/', '_').replace(' ', '_').replace(':', '_')
            # Truncate to reasonable length
            if len(device_name) > 40:
                device_name = device_name[:40]

        output_path = config_dir / f"soundcard_cal_{device_name}.json"
    else:
        output_path = Path(args.output)

    # save calibration JSON
    cal = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "samplerate": samplerate,
        "device_name": device_name if not args.test else "synthetic",
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
    with open(output_path, "w") as f:
        json.dump(cal, f, indent=2)
    print(f"\nCalibration saved to {output_path}")

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
