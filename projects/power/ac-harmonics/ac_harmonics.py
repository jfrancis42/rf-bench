#!/usr/bin/env python3
"""
AC Current Harmonic / THD-i Analyzer — Fluke 80i-400 clamp + SDS2000X scope

Clamps a mains-frequency conductor with the Fluke 80i-400 and measures the
harmonic content of the *current* waveform: total harmonic distortion (THD-i)
and the per-harmonic breakdown (2nd through Nth). Very revealing on switching
power supplies, LED lamps, VFDs, and motors, which draw badly non-sinusoidal
current even from a clean sine voltage.

Why current-only is valid here:
  THD-i is a ratio of harmonic currents to the fundamental current. It needs
  ONLY the current waveform — no voltage sensing, so no mains-voltage contact
  and no added shock hazard beyond the clamp's own insulation. (True *power*
  and power factor DO need voltage — see projects/power/ac-power/.)

Signal path (see ideas/fluke-80i400-projects.md, "front-end 2"):
  conductor → 80i-400 clamp → burden resistor across the clamp leads → scope CH
  The clamp sources 1 mA/A; through a burden R the scope sees v = (A/1000)*R.
  A 1 Ω burden gives 1 mV/A. Pass --burden to match your resistor.

Usage:
  python ac_harmonics.py                         # CH1, 1 Ω burden, 60 Hz mains
  python ac_harmonics.py --mains 50              # 50 Hz mains
  python ac_harmonics.py --burden 10 --channel 2 # 10 Ω burden on CH2
  python ac_harmonics.py --plot harmonics.png    # save spectrum bar chart
  python ac_harmonics.py --max-harmonic 25       # analyze up to the 25th

Author: Jeff Francis (N0GQ) <gjfrancis@protonmail.com>
License: GPL-3.0-or-later
"""

import argparse
import sys

import numpy as np

from rf_bench.siglent import SDS2000X
from rf_bench.fluke import Fluke80i400


def analyze(amps: np.ndarray, sample_rate: float, mains_hz: float,
            max_harmonic: int):
    """Return (fundamental_hz, harmonics list, thd_percent, rms_amps).

    harmonics: list of dicts {n, freq, amps_rms, percent_of_fundamental}.
    THD-i = sqrt(sum of squares of harmonic RMS) / fundamental RMS * 100.
    """
    n = len(amps)
    if n < 16:
        raise RuntimeError("Too few samples for FFT analysis")

    # Remove DC (the clamp passes no DC anyway, but scope offset can leak in).
    amps = amps - np.mean(amps)

    # Windowed FFT — Hann reduces spectral leakage so harmonic bins are clean.
    window = np.hanning(n)
    # Coherent-gain correction for the Hann window (mean = 0.5).
    win_gain = np.mean(window)
    spectrum = np.fft.rfft(amps * window) / (n * win_gain)
    freqs = np.fft.rfftfreq(n, d=1.0 / sample_rate)

    # Amplitude of each bin → RMS (single-sided, so ×2 except DC; /sqrt(2) RMS).
    mag = np.abs(spectrum) * 2.0
    mag_rms = mag / np.sqrt(2.0)

    def bin_rms_near(f_target):
        """RMS amplitude in the bin nearest f_target (with ±1 bin peak pick)."""
        if f_target > freqs[-1]:
            return 0.0, f_target
        k = int(np.argmin(np.abs(freqs - f_target)))
        lo, hi = max(1, k - 1), min(len(mag_rms) - 1, k + 1)
        kk = lo + int(np.argmax(mag_rms[lo:hi + 1]))
        return float(mag_rms[kk]), float(freqs[kk])

    fund_rms, fund_freq = bin_rms_near(mains_hz)
    if fund_rms <= 0:
        raise RuntimeError("No fundamental detected — check clamp/burden/timebase")

    harmonics = []
    sq_sum = 0.0
    for h in range(2, max_harmonic + 1):
        h_rms, h_freq = bin_rms_near(mains_hz * h)
        pct = 100.0 * h_rms / fund_rms
        harmonics.append({"n": h, "freq": h_freq, "amps_rms": h_rms,
                          "percent": pct})
        sq_sum += h_rms ** 2

    thd = 100.0 * np.sqrt(sq_sum) / fund_rms
    total_rms = float(np.sqrt(np.mean(amps ** 2)))
    return fund_freq, fund_rms, harmonics, thd, total_rms


def main() -> int:
    p = argparse.ArgumentParser(description="AC current harmonic / THD-i analyzer")
    p.add_argument("--scope", default=None, help="Scope IP (default: driver default)")
    p.add_argument("--channel", type=int, default=1, help="Scope channel (default 1)")
    p.add_argument("--burden", type=float, default=1.0,
                   help="Burden resistor across clamp leads, ohms (default 1.0)")
    p.add_argument("--mains", type=float, default=60.0,
                   help="Mains fundamental Hz (default 60)")
    p.add_argument("--max-harmonic", type=int, default=40,
                   help="Highest harmonic to analyze (default 40)")
    p.add_argument("--cycles", type=float, default=12.0,
                   help="Mains cycles to capture (default 12 → fine FFT bins)")
    p.add_argument("--plot", default=None, help="Save spectrum bar chart PNG")
    args = p.parse_args()

    clamp = Fluke80i400()
    print(f"Burden {args.burden} Ω → {clamp.burden_mv_per_amp(args.burden):.1f} mV/A")

    duration = args.cycles / args.mains
    scope = SDS2000X(args.scope) if args.scope else SDS2000X()
    try:
        print(f"Capturing {args.cycles:.0f} cycles ({duration*1000:.0f} ms) "
              f"on CH{args.channel}...")
        v_burden, sr = scope.capture_audio(channel=args.channel,
                                           duration_s=duration)
    finally:
        scope.close()

    amps = clamp.amps_from_burden_waveform(v_burden, args.burden)
    fund_f, fund_rms, harmonics, thd, total_rms = analyze(
        amps, sr, args.mains, args.max_harmonic)

    print(f"\nSample rate:     {sr/1e3:.1f} kS/s   ({len(amps)} samples)")
    print(f"Fundamental:     {fund_f:.1f} Hz, {fund_rms:.2f} A rms")
    print(f"Total RMS:       {total_rms:.2f} A")
    print(f"THD-i:           {thd:.1f} %")
    print(f"\n{'Harmonic':>8} {'Freq (Hz)':>10} {'A rms':>10} {'% fund':>9}")
    print("-" * 40)
    print(f"{'1 (fund)':>8} {fund_f:>10.1f} {fund_rms:>10.3f} {100.0:>8.1f}%")
    for h in harmonics:
        if h["percent"] >= 0.5:   # suppress noise-floor clutter
            print(f"{h['n']:>8} {h['freq']:>10.1f} {h['amps_rms']:>10.3f} "
                  f"{h['percent']:>8.1f}%")

    if args.plot:
        _save_plot(args.plot, fund_f, fund_rms, harmonics, thd, args.mains)
        print(f"\nSaved {args.plot}")
    return 0


def _save_plot(path, fund_f, fund_rms, harmonics, thd, mains_hz):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    orders = [1] + [h["n"] for h in harmonics]
    vals = [fund_rms] + [h["amps_rms"] for h in harmonics]
    fig, ax = plt.subplots(figsize=(10, 5))
    ax.bar(orders, vals, width=0.8, color="#c8102e")
    ax.set_xlabel("Harmonic order")
    ax.set_ylabel("Current (A rms)")
    ax.set_title(f"AC current harmonics — {mains_hz:.0f} Hz mains, THD-i {thd:.1f}%")
    ax.grid(True, axis="y", alpha=0.3)
    fig.tight_layout()
    fig.savefig(path, dpi=120)
    plt.close(fig)


if __name__ == "__main__":
    sys.exit(main())
