#!/usr/bin/env python3
"""
Radio Audio Chain Tester

Tests IC-7300 transmit audio chain. SDG1062X injects calibrated tones into
the microphone input; IC-7300 USB audio (sounddevice) captures processed TX audio.

Measurements:
  response  — TX audio frequency response (100 Hz – 5 kHz)
  alc       — ALC compression curve (power vs. drive level)
  thd       — THD at 1 kHz (2nd/3rd harmonic)
  filter    — CW/SSB IF filter shape

Hardware: SDG CH1 → BNC-to-3.5mm adapter → IC-7300 MIC input.

Usage:
    python audio_chain.py --sdg 10.1.1.55 --test response
    python audio_chain.py --sdg 10.1.1.55 --test all --plot audio.png
"""

import argparse
import sys
import time

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

try:
    import sounddevice as sd
    HAS_SD = True
except ImportError:
    HAS_SD = False

from rf_bench.siglent import SDG1000X
from rf_bench.icom import IC7300

DEFAULT_SDG    = "10.1.1.55"
DEFAULT_RIG    = "localhost"
DEFAULT_PORT   = 4532
AUDIO_RATE     = 48000
CAPTURE_S      = 0.5
TEST_LEVEL_DBM = -30.0   # SDG output level for audio tests


def find_audio_device(keyword="IC-7300"):
    """Find IC-7300 USB audio device by name."""
    if not HAS_SD:
        return None
    devices = sd.query_devices()
    for i, d in enumerate(devices):
        if keyword.lower() in d["name"].lower() and d["max_input_channels"] > 0:
            return i
    return None


def capture_audio(device, duration_s=CAPTURE_S, rate=AUDIO_RATE):
    """Capture audio from IC-7300 USB audio interface."""
    if not HAS_SD:
        raise RuntimeError("sounddevice not installed: pip install sounddevice")
    samples = sd.rec(int(rate * duration_s), samplerate=rate,
                     channels=1, dtype="float32", device=device)
    sd.wait()
    return samples.flatten()


def measure_level_fft(audio, rate, freq_hz):
    """Measure RMS level at freq_hz via FFT. Returns dBFS."""
    n        = len(audio)
    fft      = np.abs(np.fft.rfft(audio)) / n
    freqs    = np.fft.rfftfreq(n, 1.0 / rate)
    idx      = int(np.argmin(np.abs(freqs - freq_hz)))
    # Average over ±5 bins
    lo, hi   = max(0, idx - 5), min(len(fft), idx + 6)
    rms      = float(np.sqrt(np.mean(fft[lo:hi]**2)))
    return 20 * np.log10(max(rms, 1e-12))


def test_frequency_response(sdg, rig, device, freq_start=100, freq_stop=5000):
    """Sweep SDG from freq_start to freq_stop Hz, measure output level."""
    print("TX audio frequency response")
    freqs  = list(range(freq_start, freq_stop + 1, 100))
    levels = []

    rig.set_mode("usb")
    rig.set_agc("off")
    sdg.output_on(1)

    for f in freqs:
        sdg.set_sine(1, freq_hz=float(f), level_dbm=TEST_LEVEL_DBM)
        time.sleep(0.05)
        audio = capture_audio(device)
        lv    = measure_level_fft(audio, AUDIO_RATE, f)
        levels.append(lv)
        print(f"\r  {f:5d} Hz  {lv:6.1f} dBFS", end="", flush=True)

    sdg.output_off(1)
    print(f"\n  Range: {min(levels):.1f} – {max(levels):.1f} dBFS")
    return freqs, levels


def test_alc(sdg, rig, device, freq=1000.0):
    """Sweep SDG level, measure output — finds ALC knee."""
    print("ALC compression curve")
    levels_in  = list(range(-50, 5, 5))  # dBm
    levels_out = []

    rig.set_mode("usb")
    sdg.output_on(1)

    for lvl in levels_in:
        sdg.set_sine(1, freq_hz=freq, level_dbm=float(lvl))
        time.sleep(0.1)
        audio = capture_audio(device)
        lv    = measure_level_fft(audio, AUDIO_RATE, freq)
        levels_out.append(lv)
        print(f"\r  IN={lvl:4d} dBm  OUT={lv:6.1f} dBFS", end="", flush=True)

    sdg.output_off(1)
    print()
    return levels_in, levels_out


def test_thd(sdg, rig, device, freq=1000.0):
    """Measure 2nd and 3rd harmonic relative to fundamental."""
    print(f"THD at {freq:.0f} Hz")
    rig.set_mode("usb")
    sdg.set_sine(1, freq_hz=freq, level_dbm=TEST_LEVEL_DBM + 10)
    sdg.output_on(1)
    time.sleep(0.1)

    audio = capture_audio(device, duration_s=1.0)
    f1    = measure_level_fft(audio, AUDIO_RATE, freq)
    f2    = measure_level_fft(audio, AUDIO_RATE, freq * 2)
    f3    = measure_level_fft(audio, AUDIO_RATE, freq * 3)

    sdg.output_off(1)
    print(f"  Fundamental: {f1:.1f} dBFS")
    print(f"  2nd harmonic: {f2:.1f} dBFS  ({f2-f1:.1f} dBc)")
    print(f"  3rd harmonic: {f3:.1f} dBFS  ({f3-f1:.1f} dBc)")
    return {"f1": f1, "f2": f2, "f3": f3, "hd2": f2-f1, "hd3": f3-f1}


def main():
    if not HAS_SD:
        print("sounddevice not installed. Install: pip install sounddevice --break-system-packages",
              file=sys.stderr)
        sys.exit(1)

    ap = argparse.ArgumentParser(description="Radio audio chain tester")
    ap.add_argument("--sdg",     default=DEFAULT_SDG)
    ap.add_argument("--rig",     default=DEFAULT_RIG)
    ap.add_argument("--rig-port", type=int, default=DEFAULT_PORT)
    ap.add_argument("--test",   choices=["response", "alc", "thd", "all"], default="response")
    ap.add_argument("--device", type=int, default=None, help="Audio device index")
    ap.add_argument("--plot",   metavar="FILE")
    args = ap.parse_args()

    device = args.device
    if device is None:
        device = find_audio_device("IC-7300")
        if device is None:
            print("IC-7300 USB audio device not found. Use --device INDEX.")
            print("Available devices:")
            for i, d in enumerate(sd.query_devices()):
                if d["max_input_channels"] > 0:
                    print(f"  {i}: {d['name']}")
            sys.exit(1)
        print(f"Using audio device {device}: {sd.query_devices(device)['name']}")

    with SDG1000X(args.sdg) as sdg, IC7300(args.rig, args.rig_port) as rig:
        results = {}
        if args.test in ("response", "all"):
            results["response"] = test_frequency_response(sdg, rig, device)
        if args.test in ("alc", "all"):
            results["alc"] = test_alc(sdg, rig, device)
        if args.test in ("thd", "all"):
            results["thd"] = test_thd(sdg, rig, device)

    if args.plot and results:
        n_plots = len(results)
        fig, axes = plt.subplots(1, n_plots, figsize=(6 * n_plots, 4))
        if n_plots == 1:
            axes = [axes]
        ax_idx = 0
        if "response" in results:
            ax = axes[ax_idx]; ax_idx += 1
            freqs, levels = results["response"]
            ax.plot(freqs, levels)
            ax.set_xlabel("Frequency (Hz)"); ax.set_ylabel("Level (dBFS)")
            ax.set_title("TX Audio Frequency Response"); ax.grid(True)
        if "alc" in results:
            ax = axes[ax_idx]; ax_idx += 1
            lin, lout = results["alc"]
            ax.plot(lin, lout)
            ax.set_xlabel("Input (dBm)"); ax.set_ylabel("Output (dBFS)")
            ax.set_title("ALC Compression"); ax.grid(True)
        plt.tight_layout()
        plt.savefig(args.plot, dpi=150)
        print(f"Plot saved: {args.plot}")


if __name__ == "__main__":
    main()
